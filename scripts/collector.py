"""
의료광고심의위원회 사이트에서 신규 통과 시안을 다운로드.

매일 새벽 자동 실행되며, 직전까지 수집된 최대 승인번호 다음부터 +1씩 증가시키며 조회.
연속 N회 결과 없음이면 종료.

저장 경로: ~/Desktop/admedical_ads/
파일명: 전체승인번호 + 확장자 (예: 260424-중-211923.png)
다중 파일: _1, _2 suffix
메타: ~/Desktop/admedical_ads/metadata.csv

실행:
    source venv/bin/activate
    python scripts/collector.py                  # seed 자동 (metadata.csv 최대값 + 1)
    python scripts/collector.py --seed 211924    # 명시적 seed
    python scripts/collector.py --miss-limit 30  # 종료 조건 변경
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import random
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent

FORM_URL = "https://www.admedical.org/application/approval_confirm.do"
API_URL = "https://www.admedical.org/application/approval_confirm_proc.do"
IMAGE_BASE = "https://www.admedical.org/upload/review/"
DOWNLOAD_URL = "https://www.admedical.org/fileDownload.do"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

CERT_PATH = str(Path(__file__).parent / "certs" / "admedical_chain.pem")
SAVE_DIR = Path.home() / "Desktop" / "admedical_ads"
METADATA_PATH = SAVE_DIR / "metadata.csv"
METADATA_COLUMNS = [
    "approval_suffix", "full_approval_no", "valid_until",
    "filename", "file_kind", "org_file_name", "fetched_at",
]


def setup_logging() -> logging.Logger:
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = log_dir / f"collector_{ts}.log"

    logger = logging.getLogger("collector")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", datefmt="%H:%M:%S")
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


def load_known_suffixes() -> set[int]:
    if not METADATA_PATH.exists():
        return set()
    out: set[int] = set()
    with open(METADATA_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            s = row.get("approval_suffix")
            if s and s.isdigit():
                out.add(int(s))
    return out


def auto_seed() -> int | None:
    """metadata.csv 최대 + index.sqlite 최대 review_num 중 더 큰 값.

    index.sqlite에 데이터가 있으나 metadata.csv가 비어있는 경우(이전 시스템에서
    수집된 경우)에도 올바른 시작점을 잡는다.
    """
    candidates: list[int] = []
    suffixes = load_known_suffixes()
    if suffixes:
        candidates.append(max(suffixes))

    db_path = ROOT / "index.sqlite"
    if db_path.exists():
        try:
            conn = sqlite3.connect(db_path)
            row = conn.execute("SELECT MAX(review_num) FROM files WHERE review_num > 0").fetchone()
            conn.close()
            if row and row[0]:
                candidates.append(int(row[0]))
        except Exception:
            pass

    return max(candidates) if candidates else None


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    })
    # 사전 세션 쿠키 확보
    s.get(FORM_URL, timeout=15, verify=CERT_PATH, headers={"Referer": FORM_URL})
    return s


def query(session: requests.Session, suffix: int, log: logging.Logger) -> dict | None:
    """승인번호 조회. 결과 dict 반환 (실패 시 None)."""
    headers = {
        "Referer": FORM_URL,
        "Origin": "https://www.admedical.org",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    delay = 2.0
    for attempt in range(3):
        try:
            r = session.post(
                API_URL,
                data={"approval_num": str(suffix)},
                headers=headers,
                timeout=20,
                verify=CERT_PATH,
            )
            ct = (r.headers.get("content-type") or "").lower()
            if r.status_code in (429,) or 500 <= r.status_code < 600:
                raise requests.HTTPError(f"{r.status_code}")
            if "application/json" not in ct:
                # 세션 만료 가능성 → 재획득 후 재시도
                log.warning("non-json response (%s); re-acquiring session", ct)
                session.get(FORM_URL, timeout=15, verify=CERT_PATH, headers={"Referer": FORM_URL})
                raise requests.HTTPError("non-json")
            return r.json()
        except Exception as e:
            if attempt == 2:
                log.warning("[%s] query error after retries: %s", suffix, e)
                return None
            time.sleep(delay)
            delay *= 2
    return None


def sanitize(name: str) -> str:
    return re.sub(r"[/\x00\x3a]", "_", name)


def plan_filenames(full_no: str, files: list[dict]) -> list[tuple[dict, str, str]]:
    """파일별로 (file_dict, kind, filename) 계획."""
    full_clean = sanitize(full_no)
    out = []
    for idx, fd in enumerate(files, start=1):
        ct = (fd.get("content_type") or "").lower()
        is_image = ct.startswith("image/")
        kind = "image" if is_image else "attachment"
        org = fd.get("org_file_name") or fd.get("save_file_name") or ""
        ext = os.path.splitext(org)[1]
        if not ext:
            ext = ".jpg" if is_image else ".bin"
        fname = f"{full_clean}{ext}" if len(files) == 1 else f"{full_clean}_{idx}{ext}"
        out.append((fd, kind, fname))
    return out


def download(session: requests.Session, fd: dict, kind: str, dest: Path) -> None:
    save_name = fd.get("save_file_name") or ""
    org_name = fd.get("org_file_name") or ""
    if kind == "image":
        url = IMAGE_BASE + save_name
        r = session.get(url, timeout=60, verify=CERT_PATH, headers={"Referer": FORM_URL})
    else:
        params = {
            "save_prop_path": "fileReviewPath",
            "org_file_name": org_name,
            "save_file_name": save_name,
        }
        r = session.get(DOWNLOAD_URL, params=params, timeout=120,
                        verify=CERT_PATH, headers={"Referer": FORM_URL})
    r.raise_for_status()
    tmp = dest.with_suffix(dest.suffix + ".part")
    with open(tmp, "wb") as f:
        f.write(r.content)
    os.replace(tmp, dest)


def append_metadata(suffix: int, full_no: str, valid_until: str,
                    filename: str, file_kind: str, org_file_name: str) -> None:
    is_new = not METADATA_PATH.exists()
    with open(METADATA_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=METADATA_COLUMNS)
        if is_new:
            w.writeheader()
        w.writerow({
            "approval_suffix": suffix,
            "full_approval_no": full_no,
            "valid_until": valid_until,
            "filename": filename,
            "file_kind": file_kind,
            "org_file_name": org_file_name,
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
        })


def process_one(session: requests.Session, suffix: int, log: logging.Logger) -> str:
    """returns 'hit' | 'miss' | 'error'"""
    payload = query(session, suffix, log)
    if payload is None:
        return "error"
    if not isinstance(payload, dict) or payload.get("result", 0) <= 0:
        return "miss"
    app_info = payload.get("applicationInfo") or {}
    files = payload.get("fileList") or []
    full_no = app_info.get("approval_num") or ""
    valid_until = app_info.get("expiration_dt") or ""
    app_post_num = app_info.get("post_num")
    matched = [f for f in files if f.get("post_num") == app_post_num]
    if not matched or not full_no:
        return "miss"

    saved = False
    for fd, kind, fname in plan_filenames(full_no, matched):
        dest = SAVE_DIR / fname
        if dest.exists():
            continue
        try:
            download(session, fd, kind, dest)
        except Exception as e:
            log.warning("[%s] download failed (%s): %s", suffix, fname, e)
            continue
        append_metadata(suffix, full_no, valid_until, fname, kind, fd.get("org_file_name") or "")
        saved = True
        log.info("[%s] saved %s (%s, %s)", suffix, fname, kind, valid_until)
    return "hit" if saved else "miss"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=None,
                        help="시작 승인번호 (생략하면 metadata.csv/index.sqlite 최대값 + 1)")
    parser.add_argument("--miss-limit", type=int, default=15,
                        help="연속 결과 없음 종료 한도 (기본 15)")
    parser.add_argument("--max-attempts", type=int, default=250,
                        help="최대 조회 시도 횟수 (기본 250)")
    parser.add_argument("--sleep-min", type=float, default=1.0)
    parser.add_argument("--sleep-max", type=float, default=2.0)
    args = parser.parse_args()

    log = setup_logging()

    SAVE_DIR.mkdir(parents=True, exist_ok=True)

    if args.seed is None:
        last = auto_seed()
        if last is None:
            log.error("metadata.csv가 비어있고 --seed도 없음. --seed N 으로 시작 번호 지정 필요.")
            sys.exit(1)
        seed = last + 1
        log.info("auto seed: %s (마지막 %s + 1)", seed, last)
    else:
        seed = args.seed

    known = load_known_suffixes()
    log.info("이미 수집된 항목: %d개", len(known))

    session = make_session()
    cursor = seed
    miss_streak = 0
    saved_count = 0
    error_count = 0
    attempts = 0  # 실제 HTTP 조회 시도 횟수 (skip은 제외)

    log.info("수집 시작: seed=%d miss_limit=%d max_attempts=%d",
             seed, args.miss_limit, args.max_attempts)

    while miss_streak < args.miss_limit and attempts < args.max_attempts:
        if cursor in known:
            log.info("[%s] skip (이미 수집됨)", cursor)
            cursor += 1
            continue

        attempts += 1
        outcome = process_one(session, cursor, log)
        if outcome == "hit":
            miss_streak = 0
            saved_count += 1
            known.add(cursor)
        elif outcome == "miss":
            miss_streak += 1
            log.info("[%s] miss (streak %d/%d)", cursor, miss_streak, args.miss_limit)
        else:
            error_count += 1

        cursor += 1
        time.sleep(random.uniform(args.sleep_min, args.sleep_max))

    if miss_streak >= args.miss_limit:
        reason = f"연속 미스 {args.miss_limit}회 도달"
    elif attempts >= args.max_attempts:
        reason = f"최대 시도 {args.max_attempts}회 도달"
    else:
        reason = "기타"

    log.info("종료(%s): 신규 저장 %d건, 시도 %d회, 에러 %d건, 시도 범위 %d~%d",
             reason, saved_count, attempts, error_count, seed, cursor - 1)


if __name__ == "__main__":
    main()
