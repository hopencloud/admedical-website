"""
지난달 TOP 20 표현 계산.

지난달 = 직전 월의 1일 ~ 말일.
매월 1일 새벽에 자동 실행되어, 직전 달 데이터로 갱신된다.

결과: website/assets/data/monthly_top20.json
"""

import calendar
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from top_expressions import compute_top20  # noqa: E402

ROOT = Path(__file__).parent.parent
KST = timezone(timedelta(hours=9))
OUTPUT_PATH = ROOT / "website" / "assets" / "data" / "monthly_top20.json"


def main() -> None:
    load_dotenv(ROOT / ".env")

    today = datetime.now(KST).date()
    first_of_this_month = today.replace(day=1)
    last_day_prev_month = first_of_this_month - timedelta(days=1)
    first_of_prev_month = last_day_prev_month.replace(day=1)

    label = (
        f"지난달 ({first_of_prev_month.year}년 {first_of_prev_month.month}월: "
        f"{first_of_prev_month.isoformat()} ~ {last_day_prev_month.isoformat()})"
    )
    result = compute_top20(
        first_of_prev_month.isoformat(),
        last_day_prev_month.isoformat(),
        label,
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[저장됨] {OUTPUT_PATH.relative_to(ROOT)}")
    print(f"  표현 수: {len(result['top20'])}개")
    print(f"  방식: {result['method']}")


if __name__ == "__main__":
    main()
