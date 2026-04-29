"""
이번달 TOP 20 표현 계산.

이번달 = 이번달 1일 ~ 오늘 (KST 기준).
매일 새벽 자동 실행되며, 진행 중인 달의 데이터로 갱신된다.
달이 끝나기 전까지는 계속 누적되는 데이터.

결과: website/assets/data/this_month_top20.json
"""

from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from top_expressions import compute_top20  # noqa: E402

ROOT = Path(__file__).parent.parent
KST = timezone(timedelta(hours=9))
OUTPUT_PATH = ROOT / "website" / "assets" / "data" / "this_month_top20.json"


def main() -> None:
    load_dotenv(ROOT / ".env")

    today = datetime.now(KST).date()
    first_of_this_month = today.replace(day=1)

    label = (
        f"이번달 ({first_of_this_month.year}년 {first_of_this_month.month}월: "
        f"{first_of_this_month.isoformat()} ~ {today.isoformat()})"
    )
    result = compute_top20(first_of_this_month.isoformat(), today.isoformat(), label)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[저장됨] {OUTPUT_PATH.relative_to(ROOT)}")
    print(f"  표현 수: {len(result['top20'])}개")
    print(f"  방식: {result['method']}")


if __name__ == "__main__":
    main()
