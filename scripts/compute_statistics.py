"""
일일 통계 계산: 오늘/이번주/이번달 건수 + 30일 일자별 그래프.
결과를 website/assets/data/statistics.json 으로 저장.

웹사이트가 이 JSON을 fetch해서 메인 대시보드에 표시한다.

데이터 출처: index.sqlite (페이지 수가 아니라 심의번호 단위 카운트)

실행:
    source venv/bin/activate
    python scripts/compute_statistics.py
"""

import json
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "index.sqlite"
OUTPUT_PATH = ROOT / "website" / "assets" / "data" / "statistics.json"

KST = timezone(timedelta(hours=9))


def main() -> None:
    if not DB_PATH.exists():
        print(f"[오류] index.sqlite를 찾을 수 없음: {DB_PATH}")
        sys.exit(1)

    today = datetime.now(KST).date()

    # 이번주 = 월요일 시작
    week_start = today - timedelta(days=today.weekday())
    # 지난주 = 직전 월~일
    last_week_end = week_start - timedelta(days=1)
    last_week_start = last_week_end - timedelta(days=6)
    # 지지난주 = 그 직전 월~일 (지난주와 비교용)
    prev_last_week_end = last_week_start - timedelta(days=1)
    prev_last_week_start = prev_last_week_end - timedelta(days=6)

    # 이번달 = 1일 시작
    month_start = today.replace(day=1)
    # 지난달 = 직전 달 1일 ~ 말일
    last_month_end = month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    # 지지난달 = 그 직전 달 1일 ~ 말일 (지난달과 비교용)
    prev_last_month_end = last_month_start - timedelta(days=1)
    prev_last_month_start = prev_last_month_end.replace(day=1)

    # 지난 30일 그래프 시작점
    chart_start = today - timedelta(days=29)

    conn = sqlite3.connect(DB_PATH)

    # 1. 카운트 (심의번호 unique 기준)
    def count_unique_reviews(start: date, end: date) -> int:
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT review_num)
            FROM files
            WHERE is_notice = 0
              AND review_date BETWEEN ? AND ?
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchone()
        return row[0] if row else 0

    total_count = conn.execute(
        "SELECT COUNT(DISTINCT review_num) FROM files WHERE is_notice = 0"
    ).fetchone()[0]

    today_count = count_unique_reviews(today, today)
    week_count = count_unique_reviews(week_start, today)
    month_count = count_unique_reviews(month_start, today)
    last_week_count = count_unique_reviews(last_week_start, last_week_end)
    prev_last_week_count = count_unique_reviews(prev_last_week_start, prev_last_week_end)
    last_month_count = count_unique_reviews(last_month_start, last_month_end)
    prev_last_month_count = count_unique_reviews(prev_last_month_start, prev_last_month_end)

    # 2. 30일 일자별 그래프 데이터
    rows = conn.execute(
        """
        SELECT review_date, COUNT(DISTINCT review_num) AS cnt
        FROM files
        WHERE is_notice = 0
          AND review_date BETWEEN ? AND ?
        GROUP BY review_date
        """,
        (chart_start.isoformat(), today.isoformat()),
    ).fetchall()
    by_date: dict[str, int] = {d: c for d, c in rows}

    chart: list[dict[str, object]] = []
    cursor = chart_start
    while cursor <= today:
        chart.append({"date": cursor.isoformat(), "count": by_date.get(cursor.isoformat(), 0)})
        cursor += timedelta(days=1)

    # 3. 데이터 범위 (참고용)
    first_date, last_date = conn.execute(
        "SELECT MIN(review_date), MAX(review_date) FROM files WHERE is_notice = 0"
    ).fetchone()
    conn.close()

    payload = {
        "generated_at": datetime.now(KST).isoformat(),
        "today": {
            "date": today.isoformat(),
            "count": today_count,
        },
        "this_week": {
            "start": week_start.isoformat(),
            "end": today.isoformat(),
            "count": week_count,
        },
        "this_month": {
            "start": month_start.isoformat(),
            "end": today.isoformat(),
            "count": month_count,
        },
        "last_week": {
            "start": last_week_start.isoformat(),
            "end": last_week_end.isoformat(),
            "count": last_week_count,
            "delta": last_week_count - prev_last_week_count,
            "prev_count": prev_last_week_count,
        },
        "last_month": {
            "start": last_month_start.isoformat(),
            "end": last_month_end.isoformat(),
            "count": last_month_count,
            "delta": last_month_count - prev_last_month_count,
            "prev_count": prev_last_month_count,
        },
        "total": {
            "count": total_count,
            "first_date": first_date,
            "last_date": last_date,
        },
        "chart_30d": chart,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[저장됨] {OUTPUT_PATH.relative_to(ROOT)}")
    print(f"  총 누적: {total_count:,}건  ({first_date} ~ {last_date})")
    print(f"  오늘({today}): {today_count}건")
    print(f"  이번주({week_start} ~ {today}): {week_count}건")
    print(f"  이번달({month_start} ~ {today}): {month_count}건")
    print(f"  지난주({last_week_start} ~ {last_week_end}): {last_week_count}건 (지지난주 대비 {last_week_count - prev_last_week_count:+d})")
    print(f"  지난달({last_month_start} ~ {last_month_end}): {last_month_count}건 (지지난달 대비 {last_month_count - prev_last_month_count:+d})")
    print(f"  30일 그래프: {len(chart)}일치 데이터")


if __name__ == "__main__":
    main()
