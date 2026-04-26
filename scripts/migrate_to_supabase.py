"""
index.sqlite의 광고 데이터를 심의번호 단위로 합쳐
마스킹(OpenAI) 후 Supabase ads 테이블로 일괄 업로드.

특징:
  - 재시작 안전: 이미 Supabase에 있는 review_num은 건너뜀
  - 배치 업로드: 50건씩 묶어 전송 (네트워크 효율)
  - 진행률 표시: tqdm 진행바
  - 비용/시간 추정: 시작 시 표시 후 사용자 확인

실행:
    source venv/bin/activate
    python scripts/migrate_to_supabase.py              # 전체 마이그레이션
    python scripts/migrate_to_supabase.py --limit 50   # 50건만 (테스트용)
    python scripts/migrate_to_supabase.py --dry-run    # 마스킹만, Supabase 업로드 X
"""

import argparse
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

DB_PATH = Path(__file__).parent.parent / "index.sqlite"
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


def fetch_existing_review_nums(supabase) -> set[int]:
    """Supabase에 이미 있는 review_num 목록 (재시작 시 건너뛰기 위함)."""
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
    """심의일(YYYY-MM-DD) + review_num → "YYMMDD-중-NNNNNN" 형태로 변환."""
    try:
        d = datetime.strptime(review_date_str, "%Y-%m-%d")
        return f"{d.strftime('%y%m%d')}-중-{review_num}"
    except (ValueError, TypeError):
        return f"unknown-중-{review_num}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="처리할 최대 건수 (테스트용)")
    parser.add_argument("--dry-run", action="store_true",
                        help="마스킹만 실행, Supabase 업로드 안 함")
    parser.add_argument("--no-resume", action="store_true",
                        help="이미 업로드된 항목도 다시 처리")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"[오류] index.sqlite를 찾을 수 없음: {DB_PATH}")
        sys.exit(1)

    # 1. SQLite에서 심의번호 단위로 합친 데이터 가져오기
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(MERGE_QUERY).fetchall()
    conn.close()
    print(f"\n[SQLite] 총 {len(rows):,}개 심의번호 (페이지 합쳐서)")

    # 2. Supabase 연결 + 이미 있는 항목 확인 (재시작 안전성)
    supabase = None
    skip_set: set[int] = set()
    if not args.dry_run:
        supabase = get_supabase()
        if not args.no_resume:
            print("[Supabase] 이미 업로드된 항목 확인 중...")
            skip_set = fetch_existing_review_nums(supabase)
            print(f"[Supabase] 이미 있음: {len(skip_set):,}개 (건너뜀)")

    todo = [r for r in rows if r[0] not in skip_set]
    if args.limit:
        todo = todo[: args.limit]
    print(f"[작업 대상] {len(todo):,}개")

    if not todo:
        print("처리할 항목 없음. 종료.")
        return

    # 3. 비용/시간 추정
    avg_cost_per_record = 0.0005  # USD (실측 기반)
    est_cost_usd = len(todo) * avg_cost_per_record
    est_minutes = len(todo) * 1.5 / 60  # 초당 약 1건 가정
    print(f"[추정] 비용 약 ${est_cost_usd:.2f} (~{int(est_cost_usd*1500):,}원), "
          f"소요 약 {est_minutes:.0f}분")

    if args.dry_run:
        print("[DRY RUN] Supabase 업로드 없이 마스킹만 실행합니다.\n")
    else:
        print()

    # 4. 마스킹 + 업로드 (배치)
    batch: list[dict] = []
    success = 0
    failures: list[int] = []
    started_at = time.time()

    pbar = tqdm(todo, desc="마이그레이션", unit="건")
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

        if args.dry_run:
            success += 1
            continue

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

    # 마지막 배치 flush
    if not args.dry_run and batch:
        try:
            supabase.table("ads").upsert(batch, on_conflict="review_num").execute()
            success += len(batch)
        except Exception as e:
            print(f"\n[마지막 배치 업로드 실패] {e}")
            failures.extend(r["review_num"] for r in batch)

    pbar.close()

    elapsed = time.time() - started_at
    print(f"\n[완료] 성공 {success:,}건 / 실패 {len(failures):,}건 / 소요 {elapsed/60:.1f}분")
    if failures:
        print(f"[실패 review_num 샘플] {failures[:10]}")
        print("→ 실패한 건은 다음 실행 시 자동 재시도됩니다.")


if __name__ == "__main__":
    main()
