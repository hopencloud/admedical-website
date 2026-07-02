"""
일일 통계 계산: 오늘/이번주/이번달 건수 + 30일 일자별 그래프.
결과를 website/assets/data/statistics.json 으로 저장.

데이터 출처: Supabase `ads` 테이블 (심의번호 단위)

실행:
    python scripts/compute_statistics.py
"""

from __future__ import annotations
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import Client, create_client

ROOT = Path(__file__).parent.parent
OUTPUT_PATH = ROOT / "website" / "assets" / "data" / "statistics.json"
KST = timezone(timedelta(hours=9))

load_dotenv(ROOT / ".env")


def db() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_ANON_KEY"]
    return create_client(url, key)


def count_between(sb: Client, start: date, end: date) -> int:
    r = (
        sb.table("ads")
        .select("review_num", count="exact")
        .gte("review_date", start.isoformat())
        .lte("review_date", end.isoformat())
        .limit(1)
        .execute()
    )
    return r.count or 0


def fetch_daily_counts(sb: Client, start: date, end: date) -> dict[str, int]:
    """지정 기간의 날짜별 건수. Supabase 페이지네이션(1000개 상한)을 넘어가면 여러 번 fetch."""
    out: dict[str, int] = {}
    page_size = 1000
    offset = 0
    while True:
        r = (
            sb.table("ads")
            .select("review_date")
            .gte("review_date", start.isoformat())
            .lte("review_date", end.isoformat())
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = r.data or []
        for row in rows:
            d = row["review_date"]
            out[d] = out.get(d, 0) + 1
        if len(rows) < page_size:
            break
        offset += page_size
    return out


def main() -> None:
    sb = db()
    today = datetime.now(KST).date()

    # 어제 = 가장 최근 영업일 (Sat/Sun skip)
    yesterday = today - timedelta(days=1)
    while yesterday.weekday() >= 5:
        yesterday -= timedelta(days=1)

    week_start = today - timedelta(days=today.weekday())
    last_week_end = week_start - timedelta(days=1)
    last_week_start = last_week_end - timedelta(days=6)
    prev_last_week_end = last_week_start - timedelta(days=1)
    prev_last_week_start = prev_last_week_end - timedelta(days=6)

    month_start = today.replace(day=1)
    last_month_end = month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    prev_last_month_end = last_month_start - timedelta(days=1)
    prev_last_month_start = prev_last_month_end.replace(day=1)

    chart_start = today - timedelta(days=29)

    # 카운트
    total_count = sb.table("ads").select("review_num", count="exact").limit(1).execute().count or 0
    yesterday_count = count_between(sb, yesterday, yesterday)
    week_count = count_between(sb, week_start, today)
    month_count = count_between(sb, month_start, today)
    last_week_count = count_between(sb, last_week_start, last_week_end)
    prev_last_week_count = count_between(sb, prev_last_week_start, prev_last_week_end)
    last_month_count = count_between(sb, last_month_start, last_month_end)
    prev_last_month_count = count_between(sb, prev_last_month_start, prev_last_month_end)

    # 30일 그래프
    by_date = fetch_daily_counts(sb, chart_start, today)
    chart: list[dict[str, object]] = []
    cursor = chart_start
    while cursor <= today:
        chart.append({"date": cursor.isoformat(), "count": by_date.get(cursor.isoformat(), 0)})
        cursor += timedelta(days=1)

    # 데이터 범위
    r_min = sb.table("ads").select("review_date").order("review_date", desc=False).limit(1).execute()
    r_max = sb.table("ads").select("review_date").order("review_date", desc=True).limit(1).execute()
    first_date = r_min.data[0]["review_date"] if r_min.data else None
    last_date = r_max.data[0]["review_date"] if r_max.data else None

    payload = {
        "generated_at": datetime.now(KST).isoformat(),
        "yesterday": {"date": yesterday.isoformat(), "count": yesterday_count},
        "this_week": {"start": week_start.isoformat(), "end": today.isoformat(), "count": week_count},
        "this_month": {"start": month_start.isoformat(), "end": today.isoformat(), "count": month_count},
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
        "total": {"count": total_count, "first_date": first_date, "last_date": last_date},
        "chart_30d": chart,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[저장됨] {OUTPUT_PATH.relative_to(ROOT)}")
    print(f"  총 누적: {total_count:,}건  ({first_date} ~ {last_date})")
    print(f"  어제({yesterday}, 최근 영업일): {yesterday_count}건")
    print(f"  이번주({week_start} ~ {today}): {week_count}건")
    print(f"  이번달({month_start} ~ {today}): {month_count}건")
    print(f"  지난주({last_week_start} ~ {last_week_end}): {last_week_count}건 (지지난주 대비 {last_week_count - prev_last_week_count:+d})")
    print(f"  지난달({last_month_start} ~ {last_month_end}): {last_month_count}건 (지지난달 대비 {last_month_count - prev_last_month_count:+d})")
    print(f"  30일 그래프: {len(chart)}일치")


if __name__ == "__main__":
    main()
