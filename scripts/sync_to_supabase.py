"""
index.sqlite의 신규 항목만 Supabase로 증분 동기화.

매일 indexer.py 실행 후에 호출되어, Supabase에 없는 review_num만 마스킹+업로드.
이미 있는 review_num은 건너뜀 (재처리 안 함).

migrate_to_supabase.py와 차이:
  - migrate: 일괄 마이그레이션 (전체)
  - sync:    매일 증분만 (신규 분만)

실행:
    source venv/bin/activate
    python scripts/sync_to_supabase.py
"""
from __future__ import annotations
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))
from masking import clean_ocr_text  # noqa: E402

load_dotenv(Path(__file__).parent.parent / ".env")

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "index.sqlite"
BATCH_SIZE = 50

MERGE_QUERY = """
SELECT
    review_num,
    MAX(review_date) AS review_date,
    GROUP_CONCAT(ocr_text, ' ') AS combined_text,
    COUNT(*) AS page_count
FROM files
WHERE is_notice = 0
  AND ocr_done = 1
  AND ocr_text IS NOT NULL
  AND TRIM(ocr_text) != ''
GROUP BY review_num
ORDER BY review_num;
"""


def get_supabase():
    from supabase import create_client
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL 또는 SUPABASE_SERVICE_KEY가 .env에 없습니다.")
    return create_client(url, key)


def fetch_existing(supabase) -> set[int]:
    existing: set[int] = set()
    page = 0
    page_size = 1000
    while True:
        resp = (
            supabase.table("ads")
            .select("review_num")
            .range(page * page_size, (page + 1) * page_size - 1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            break
        existing.update(r["review_num"] for r in rows)
        if len(rows) < page_size:
            break
        page += 1
    return existing


def make_display_no(review_date_str: str, review_num: int) -> str:
    try:
        d = datetime.strptime(review_date_str, "%Y-%m-%d")
        return f"{d.strftime('%y%m%d')}-중-{review_num}"
    except (ValueError, TypeError):
        return f"unknown-중-{review_num}"


def main() -> None:
    if not DB_PATH.exists():
        print(f"[오류] index.sqlite를 찾을 수 없음: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(MERGE_QUERY).fetchall()
    conn.close()

    supabase = get_supabase()
    print(f"[Supabase] 기존 항목 확인 중...")
    existing = fetch_existing(supabase)
    print(f"[Supabase] 이미 있음: {len(existing):,}개")

    todo = [r for r in rows if r[0] not in existing]
    print(f"[작업 대상] {len(todo):,}건 (신규)")

    if not todo:
        print("[종료] 동기화할 신규 항목 없음.")
        return

    batch: list[dict] = []
    success = 0
    failures: list[int] = []
    started = time.time()

    pbar = tqdm(todo, desc="동기화", unit="건")
    for review_num, review_date, combined_text, page_count in pbar:
        try:
            cleaned = clean_ocr_text(combined_text)
        except Exception as e:
            print(f"\n[마스킹 예외] review_num={review_num}: {e}")
            failures.append(review_num)
            continue

        record = {
            "review_num": review_num,
            "review_date": review_date,
            "review_no_display": make_display_no(review_date, review_num),
            "ocr_text": cleaned or "",
            "page_count": page_count,
        }
        batch.append(record)

        if len(batch) >= BATCH_SIZE:
            try:
                supabase.table("ads").upsert(batch, on_conflict="review_num").execute()
                success += len(batch)
                batch = []
            except Exception as e:
                print(f"\n[업로드 실패 — 배치 {len(batch)}건] {e}")
                failures.extend(r["review_num"] for r in batch)
                batch = []
        pbar.set_postfix({"성공": success, "실패": len(failures)})

    if batch:
        try:
            supabase.table("ads").upsert(batch, on_conflict="review_num").execute()
            success += len(batch)
        except Exception as e:
            print(f"\n[마지막 배치 실패] {e}")
            failures.extend(r["review_num"] for r in batch)

    pbar.close()
    elapsed = time.time() - started
    print(f"\n[완료] 성공 {success:,}건 / 실패 {len(failures):,}건 / 소요 {elapsed/60:.1f}분")
    if failures:
        print(f"[실패 review_num 샘플] {failures[:10]}")


if __name__ == "__main__":
    main()
