"""
실제 SQLite에서 다양한 길이의 샘플 10건을 뽑아 마스킹 결과를 보여주는 테스트.

실행:
    source venv/bin/activate
    python scripts/test_masking_samples.py
"""

import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

# 같은 폴더의 masking 모듈 import 가능하도록
sys.path.insert(0, str(Path(__file__).parent))
from masking import clean_ocr_text  # noqa: E402

load_dotenv(Path(__file__).parent.parent / ".env")

DB_PATH = Path(__file__).parent.parent / "index.sqlite"

# 이전 테스트와 동일한 10건 (사장님이 비교 가능하도록 고정)
FIXED_REVIEW_NUMS = [
    211022, 206325, 206245, 206603, 207549,
    211577, 208254, 207837, 205793, 210382,
]

SAMPLE_QUERY = f"""
SELECT
    review_num,
    MAX(review_date) AS review_date,
    GROUP_CONCAT(ocr_text, ' ') AS combined_text,
    SUM(LENGTH(COALESCE(ocr_text, ''))) AS total_len
FROM files
WHERE is_notice = 0
  AND ocr_done = 1
  AND ocr_text IS NOT NULL
  AND review_num IN ({','.join(str(n) for n in FIXED_REVIEW_NUMS)})
GROUP BY review_num
ORDER BY review_num;
"""


def main():
    if not DB_PATH.exists():
        print(f"[오류] index.sqlite를 찾을 수 없음: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(SAMPLE_QUERY).fetchall()
    conn.close()

    print(f"\n총 {len(rows)}개 샘플을 마스킹합니다...\n")
    print("=" * 80)

    for i, (review_num, review_date, raw, total_len) in enumerate(rows, 1):
        print(f"\n[샘플 {i}/{len(rows)}]  심의번호: {review_num}  ({review_date})  원문 {total_len}자")
        print("-" * 80)
        print("[원문]")
        print(raw)
        print()
        print("[정제 결과]")
        cleaned = clean_ocr_text(raw)
        print(cleaned if cleaned else "(빈 결과)")
        print("=" * 80)

    print("\n완료. 위 결과 확인 후 사장님께 보고합니다.")


if __name__ == "__main__":
    main()
