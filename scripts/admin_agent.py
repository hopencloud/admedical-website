"""
관리자 대시보드 Agent — 맥북 백그라운드 폴러.

Supabase의 admin_jobs 테이블을 5초마다 polling 해서,
status='pending' 인 작업을 발견하면 해당 스크립트를 subprocess 로 실행하고,
표준출력을 실시간으로 admin_jobs.log_tail / counter / message 에 반영한다.

작업 종류:
    - collector → scripts/collector.py
    - indexer   → scripts/batch_vision_ocr.py + sync_to_supabase.py
    - pipeline  → scripts/daily_pipeline.sh

사용:
    python scripts/admin_agent.py            # foreground (테스트용)
    launchctl load ~/Library/LaunchAgents/com.admedical.admin_agent.plist  # 상시 실행
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# venv 라이브러리 자동 사용
VENV_PY = ROOT / "venv" / "bin" / "python"
sys.path.insert(0, str(ROOT / "venv" / "lib" / "python3.9" / "site-packages"))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(ROOT / ".env")
except Exception:
    pass

try:
    from supabase import create_client, Client  # type: ignore
except Exception as e:
    print(f"[fatal] supabase 패키지 없음: {e}", flush=True)
    sys.exit(1)


SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("[fatal] SUPABASE_URL / SUPABASE_SERVICE_KEY 가 .env 에 없음", flush=True)
    sys.exit(1)

POLL_INTERVAL_SEC = 5
LOG_TAIL_LINES = 80
HEARTBEAT_SEC = 3   # 작업 실행 중 DB 갱신 주기

JOB_COMMANDS = {
    "collector": [str(VENV_PY), str(ROOT / "scripts" / "collector.py")],
    "indexer":   [
        # OCR + Supabase 동기화 묶음 (인덱싱 = 새 이미지 → 검색가능 상태까지)
        # daily_pipeline.sh 의 2~4 단계와 동일.
        "__indexer_chain__",
    ],
    "pipeline":  ["/bin/bash", str(ROOT / "scripts" / "daily_pipeline.sh")],
}


# ---------- Supabase 헬퍼 ----------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def db() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def claim_next_job(client: Client) -> dict | None:
    """가장 오래된 pending 작업을 가져와서 running 으로 마킹.
    동시 agent 다중 실행은 가정하지 않음 (단일 노드)."""
    res = (
        client.table("admin_jobs")
        .select("*")
        .eq("status", "pending")
        .order("created_at", desc=False)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return None
    job = rows[0]
    upd = (
        client.table("admin_jobs")
        .update({
            "status": "running",
            "started_at": now_iso(),
            "message": "agent 시작",
            "progress": 0,
            "counter": 0,
            "log_tail": "",
            "error_text": None,
        })
        .eq("id", job["id"])
        .eq("status", "pending")  # 더블클릭/경합 방지
        .execute()
    )
    if not upd.data:
        return None
    return upd.data[0]


def update_job(client: Client, job_id: int, **fields) -> None:
    try:
        client.table("admin_jobs").update(fields).eq("id", job_id).execute()
    except Exception as e:
        print(f"[warn] update_job({job_id}) failed: {e}", flush=True)


# ---------- 로그 → 진행률 파서 ----------

# collector: "[212086] saved 260429-중-..." 형태가 1건 다운로드 = counter += 1
RE_COLLECTOR_SAVED = re.compile(r"\bsaved\s+\d{6}-")
# vision OCR: tqdm 진행률 라인은 대부분 \r 로 갱신되지만, "OCR XXX done" / "[XXXX] ok" 형태도 있을 수 있음.
# 보수적으로 "ok" 또는 "saved" 라인 카운트.
RE_OCR_DONE = re.compile(r"\b(ok|saved|done|completed|stored)\b", re.IGNORECASE)
# pipeline: "--- [N/4 ...] ---" 단계 라인을 진행률로 환산
RE_PIPELINE_STEP = re.compile(r"---\s*\[(\d+)/(\d+)\s*([^\]]*)\]")


def parse_progress(job_type: str, line: str, state: dict) -> dict:
    """라인 한 줄 받아서 counter / progress / message 갱신값을 dict 로 리턴."""
    out: dict = {}
    if job_type == "collector":
        if RE_COLLECTOR_SAVED.search(line):
            state["counter"] = state.get("counter", 0) + 1
            out["counter"] = state["counter"]
            out["message"] = f"다운로드 {state['counter']}건"
    elif job_type == "indexer":
        if RE_OCR_DONE.search(line):
            state["counter"] = state.get("counter", 0) + 1
            out["counter"] = state["counter"]
            out["message"] = f"인덱싱 {state['counter']}건"
    elif job_type == "pipeline":
        m = RE_PIPELINE_STEP.search(line)
        if m:
            cur, total, label = int(m.group(1)), int(m.group(2)), m.group(3).strip()
            pct = int(cur / total * 100) if total else 0
            out["progress"] = pct
            out["message"] = f"단계 {cur}/{total} · {label}"
    return out


# ---------- subprocess 실행 ----------

class JobRunner(threading.Thread):
    def __init__(self, client: Client, job: dict):
        super().__init__(daemon=True)
        self.client = client
        self.job = job
        self.tail: deque[str] = deque(maxlen=LOG_TAIL_LINES)
        self.state: dict = {}
        self.dirty = False
        self.lock = threading.Lock()
        self.stop_flag = False

    def heartbeat_loop(self) -> None:
        while not self.stop_flag:
            time.sleep(HEARTBEAT_SEC)
            self.flush()

    def flush(self) -> None:
        with self.lock:
            if not self.dirty:
                return
            payload = dict(self.state.get("_payload", {}))
            payload["log_tail"] = "\n".join(self.tail)
            self.dirty = False
        update_job(self.client, self.job["id"], **payload)

    def run(self) -> None:
        job_id = self.job["id"]
        job_type = self.job["job_type"]
        cmd = JOB_COMMANDS[job_type]
        try:
            if cmd == ["__indexer_chain__"]:
                # OCR → 통계 → sync 순차 실행 (daily_pipeline 의 2~4 단계만)
                steps = [
                    ("OCR 인덱싱", [str(VENV_PY), str(ROOT / "scripts" / "batch_vision_ocr.py"),
                                    "--src", str(Path.home() / "Desktop" / "admedical_ads"),
                                    "--workers", "5"]),
                    ("일일 통계", [str(VENV_PY), str(ROOT / "scripts" / "compute_statistics.py")]),
                    ("Supabase 동기화", [str(VENV_PY), str(ROOT / "scripts" / "sync_to_supabase.py")]),
                ]
                for i, (label, sub_cmd) in enumerate(steps, 1):
                    self.append_log(f"=== {i}/{len(steps)} {label} ===")
                    self.set_field(progress=int((i - 1) / len(steps) * 100), message=label)
                    rc = self.run_cmd(sub_cmd)
                    if rc != 0:
                        raise RuntimeError(f"{label} 실패 (exit {rc})")
                self.set_field(progress=100, message="완료")
                self.finalize("done")
            else:
                rc = self.run_cmd(cmd)
                if rc == 0:
                    self.set_field(progress=100, message="완료")
                    self.finalize("done")
                else:
                    raise RuntimeError(f"exit code {rc}")
        except Exception as e:
            self.append_log(f"[ERROR] {e}")
            self.set_field(error_text=str(e), message="실패")
            self.finalize("failed")

    def run_cmd(self, cmd: list[str]) -> int:
        self.append_log(f"$ {' '.join(cmd)}")
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            text=True,
        )
        assert proc.stdout
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            self.append_log(line)
            updates = parse_progress(self.job["job_type"], line, self.state)
            if updates:
                self.set_field(**updates)
        return proc.wait()

    def append_log(self, line: str) -> None:
        with self.lock:
            self.tail.append(line)
            self.dirty = True

    def set_field(self, **kv) -> None:
        with self.lock:
            payload = self.state.setdefault("_payload", {})
            payload.update(kv)
            self.dirty = True

    def finalize(self, status: str) -> None:
        self.stop_flag = True
        with self.lock:
            payload = self.state.get("_payload", {}) or {}
            payload.update({
                "status": status,
                "finished_at": now_iso(),
                "log_tail": "\n".join(self.tail),
            })
            self.dirty = False
        update_job(self.client, self.job["id"], **payload)


# ---------- 메인 루프 ----------

def main() -> None:
    print(f"[agent] 시작. polling 주기={POLL_INTERVAL_SEC}s. ROOT={ROOT}", flush=True)
    client = db()
    stop = {"flag": False}
    consecutive_fails = 0
    # 슬립 → 깨어남 사이에 supabase client 가 죽은 connection / DNS 캐시를 들고
    # 무한 재시도하는 문제 회피용. N번 연속 실패 시 client 재생성.
    RECONNECT_AFTER_FAILS = 3

    def _sig(_signum, _frame):
        stop["flag"] = True
        print("[agent] 종료 신호 수신", flush=True)

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    while not stop["flag"]:
        try:
            job = claim_next_job(client)
            consecutive_fails = 0
        except Exception as e:
            consecutive_fails += 1
            print(f"[warn] claim 실패 ({consecutive_fails}회): {e}", flush=True)
            if consecutive_fails >= RECONNECT_AFTER_FAILS:
                print(f"[agent] {RECONNECT_AFTER_FAILS}회 연속 실패 → client 재생성", flush=True)
                try:
                    client = db()
                    consecutive_fails = 0
                except Exception as e2:
                    print(f"[warn] client 재생성 실패: {e2}", flush=True)
            time.sleep(POLL_INTERVAL_SEC)
            continue

        if not job:
            time.sleep(POLL_INTERVAL_SEC)
            continue

        print(f"[agent] 작업 시작 id={job['id']} type={job['job_type']}", flush=True)
        runner = JobRunner(client, job)
        runner.start()
        # 하트비트는 동기적으로 메인 스레드에서 (단순화)
        while runner.is_alive():
            time.sleep(HEARTBEAT_SEC)
            runner.flush()
        runner.flush()
        print(f"[agent] 작업 종료 id={job['id']}", flush=True)


if __name__ == "__main__":
    main()
