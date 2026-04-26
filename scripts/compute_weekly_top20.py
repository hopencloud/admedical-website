"""
지난주 TOP 20 표현 계산.

지난주 = 지난 월요일 ~ 지난 일요일 (오늘 기준).
매주 월요일 새벽에 자동 실행되어, 직전 주 데이터로 갱신된다.

결과: website/assets/data/weekly_top20.json
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from top_expressions import compute_top20  # noqa: E402

ROOT = Path(__file__).parent.parent
KST = timezone(timedelta(hours=9))
OUTPUT_PATH = ROOT / "website" / "assets" / "data" / "weekly_top20.json"


def main() -> None:
    load_dotenv(ROOT / ".env")

    today = datetime.now(KST).date()
    # 이번주 월요일
    this_monday = today - timedelta(days=today.weekday())
    # 지난주 월요일~일요일
    last_monday = this_monday - timedelta(days=7)
    last_sunday = this_monday - timedelta(days=1)

    label = f"지난주 ({last_monday.isoformat()} ~ {last_sunday.isoformat()})"
    result = compute_top20(last_monday.isoformat(), last_sunday.isoformat(), label)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[저장됨] {OUTPUT_PATH.relative_to(ROOT)}")
    print(f"  표현 수: {len(result['top20'])}개")
    print(f"  방식: {result['method']}")


if __name__ == "__main__":
    main()
