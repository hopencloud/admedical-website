"""
클라우드 파이프라인 — GitHub Actions 에서 매일 실행.

동작:
  1. Supabase `ads` 테이블에서 MAX(review_num) 조회 → collector seed
  2. collector 로 admedical.org 에서 신규 시안 이미지 다운로드 (임시 폴더)
  3. 다운로드된 이미지들 OpenAI Vision OCR → 심의번호별로 텍스트 합치기
  4. 마스킹 → Supabase `ads` upsert
  5. compute_statistics 로 statistics.json 재계산 → website/assets/data/
  6. this_week / this_month TOP20 재계산
  7. (매주 월요일) 지난주 TOP20, (매월 1일) 지난달 TOP20 추가
  8. 임시 폴더 정리
  9. git commit + push (호출자가 처리; 여기선 파일만 갱신)

로컬 SQLite / launchd / macOS 권한 / 맥북 슬립 등 로컬 인프라 의존성 0.
"""
from __future__ import annotations
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

load_dotenv(ROOT / ".env")

# collector 를 임포트하기 전에 저장 경로를 임시 폴더로 지정.
TMP_DIR = Path(tempfile.mkdtemp(prefix="admedical_"))
os.environ["ADMEDICAL_SAVE_DIR"] = str(TMP_DIR)

import collector  # noqa: E402
from masking import clean_ocr_text  # noqa: E402
from vision_ocr import vision_ocr  # noqa: E402


KST = timezone(timedelta(hours=9))


def db():
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


# ---------- 1. Collector ----------

def run_collector(seed_hint: int | None) -> None:
    """collector.main 을 직접 호출하는 대신 필요한 부분만 인라인 실행."""
    log = collector.setup_logging()
    seed = seed_hint if seed_hint is not None else collector.auto_seed()
    if seed is None:
        log.warning("seed 미확인 — collector 스킵")
        return
    seed += 1
    log.info(f"수집 시작: seed={seed}, 저장={TMP_DIR}")

    session = collector.make_session()
    miss_streak = 0
    miss_limit = 15
    max_attempts = 250
    for i in range(max_attempts):
        num = seed + i
        status = collector.process_one(session, num, log)
        if status == "hit":
            miss_streak = 0
        else:
            miss_streak += 1
            log.info(f"[{num}] miss (streak {miss_streak}/{miss_limit})")
        if miss_streak >= miss_limit:
            log.info(f"종료(연속 미스 {miss_limit}회 도달)")
            break
        # 부드러운 rate limit
        time.sleep(1.0 + (0.5 * (i % 3)))


# ---------- 2. OCR + Supabase upload ----------

FILENAME_RE = re.compile(r"^(\d{6})-중-(\d+)(?:_\d+)?\.[A-Za-z0-9]+$")


def parse_filename(name: str) -> tuple[str, int] | None:
    """'260702-중-215678_1.png' → ('2026-07-02', 215678)"""
    m = FILENAME_RE.match(name)
    if not m:
        return None
    ymd, num = m.group(1), int(m.group(2))
    yy, mm, dd = int(ymd[:2]), int(ymd[2:4]), int(ymd[4:6])
    year = 2000 + yy
    return f"{year:04d}-{mm:02d}-{dd:02d}", num


def collect_pages() -> dict[int, dict]:
    """TMP_DIR 스캔 → { review_num: {'date': ..., 'pages': [Path,...]} }"""
    groups: dict[int, dict] = defaultdict(lambda: {"date": None, "pages": []})
    for p in TMP_DIR.iterdir():
        if not p.is_file() or p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            continue
        parsed = parse_filename(p.name)
        if not parsed:
            continue
        d, num = parsed
        groups[num]["date"] = d
        groups[num]["pages"].append(p)
    return dict(groups)


def existing_review_nums(sb) -> set[int]:
    existing: set[int] = set()
    page = 0
    while True:
        r = sb.table("ads").select("review_num").range(page * 1000, page * 1000 + 999).execute()
        rows = r.data or []
        if not rows:
            break
        existing.update(row["review_num"] for row in rows)
        if len(rows) < 1000:
            break
        page += 1
    return existing


def ocr_pages(pages: list[Path]) -> str:
    """각 페이지 OCR 후 공백 결합. 실패 페이지는 건너뜀."""
    texts = []
    for p in pages:
        try:
            t = vision_ocr(str(p), detail="high")
            if t:
                texts.append(t.strip())
        except Exception as e:
            print(f"  [OCR 실패] {p.name}: {e}")
    return "\n\n".join(texts)


def make_display_no(review_date: str, review_num: int) -> str:
    d = datetime.strptime(review_date, "%Y-%m-%d")
    return f"{d.strftime('%y%m%d')}-중-{review_num}"


def process_new_reviews(sb) -> int:
    groups = collect_pages()
    if not groups:
        print("[OCR] 신규 시안 없음")
        return 0

    existing = existing_review_nums(sb)
    todo_nums = sorted(n for n in groups if n not in existing)
    print(f"[OCR] 그룹 {len(groups)}개, 신규 {len(todo_nums)}개")

    if not todo_nums:
        return 0

    success = 0
    for i, num in enumerate(todo_nums, 1):
        g = groups[num]
        review_date = g["date"]
        pages = sorted(g["pages"])
        print(f"  [{i}/{len(todo_nums)}] #{num} ({review_date}) — {len(pages)}장 OCR...")
        combined = ocr_pages(pages)
        if not combined.strip():
            print(f"    ↳ 텍스트 없음, 건너뜀")
            continue
        try:
            masked = clean_ocr_text(combined)
        except Exception as e:
            print(f"    ↳ 마스킹 실패: {e}")
            continue
        try:
            sb.table("ads").upsert({
                "review_num": num,
                "review_date": review_date,
                "review_no_display": make_display_no(review_date, num),
                "ocr_text": masked or "",
                "page_count": len(pages),
            }, on_conflict="review_num").execute()
            success += 1
        except Exception as e:
            print(f"    ↳ 업로드 실패: {e}")
    return success


# ---------- 3. 후속 단계: 통계 + TOP20 ----------

def run_subprocess(cmd: list[str]) -> bool:
    print(f"\n$ {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=str(ROOT))
    return r.returncode == 0


def run_stats_and_top20() -> None:
    py = sys.executable
    steps = [
        ("일일 통계", [py, str(ROOT / "scripts" / "compute_statistics.py")]),
        ("이번주 TOP20", [py, str(ROOT / "scripts" / "compute_this_week_top20.py")]),
        ("이번달 TOP20", [py, str(ROOT / "scripts" / "compute_this_month_top20.py")]),
    ]
    today = datetime.now(KST).date()
    if today.weekday() == 0:  # 월요일
        steps.append(("지난주 TOP20", [py, str(ROOT / "scripts" / "compute_weekly_top20.py")]))
    if today.day == 1:
        steps.append(("지난달 TOP20", [py, str(ROOT / "scripts" / "compute_monthly_top20.py")]))
    for name, cmd in steps:
        print(f"\n--- {name} ---")
        ok = run_subprocess(cmd)
        print(f"[{name}] {'OK' if ok else '실패 (계속)'}")


# ---------- main ----------

def main() -> None:
    started = time.time()
    print(f"[cloud_pipeline] 시작 {datetime.now(KST).isoformat()}")
    print(f"[cloud_pipeline] TMP_DIR={TMP_DIR}")

    try:
        # 1. Collector
        print("\n=== 1/3 Collector ===")
        run_collector(seed_hint=None)

        # 2. OCR + Supabase upload
        print("\n=== 2/3 OCR + Supabase ===")
        sb = db()
        n_uploaded = process_new_reviews(sb)
        print(f"[OCR] 업로드 완료: {n_uploaded}건")

        # 3. Stats + TOP20
        print("\n=== 3/3 Statistics + TOP20 ===")
        run_stats_and_top20()

        elapsed = time.time() - started
        print(f"\n[cloud_pipeline] 완료 (소요 {elapsed/60:.1f}분)")
    finally:
        # 임시 폴더 정리
        try:
            shutil.rmtree(TMP_DIR, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
