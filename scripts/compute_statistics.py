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


# 재시도 간격(초). 연결 자체가 안 되는 경우와 중간에 끊기는 경우는 성격이 다르다.
#
#   ReadError  — 조회 도중 커넥션이 끊김. 곧바로 다시 걸면 대개 붙는다.
#   ConnectError — DNS 조차 안 풀림. 맥북이 자다 깨서 와이파이가 아직 안 붙은 상태다.
#                  짧게 재시도해봐야 소용없고, 네트워크가 올라올 때까지 기다려야 한다.
#                  실제로 8/22 에 2·4·8초(합 14초) 안에 4번 다 실패하고 그날 통계가 날아갔다.
BACKOFF_READ = [2, 4, 8, 16]
BACKOFF_CONNECT = [10, 20, 40, 60, 60, 60]        # 최대 4분 가까이 기다린다


def retry(fn, *, what: str = "질의"):
    """Supabase 조회를 재시도한다.

    한 번 끊겼다고 통계 갱신이 통째로 죽으면 그날 사이트 숫자가 멈춘다.
    실제로 8/14·8/19(커넥션 끊김), 8/22(DNS 실패) 에 그랬다.
    """
    import time
    schedule = BACKOFF_READ
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:
            name = type(exc).__name__
            # 첫 실패가 연결 실패면 대기 일정을 통째로 늘린다.
            # (반복문 안에서 바꿔야 하므로 미리 만든 이터레이터를 쓰지 않는다)
            if attempt == 0 and "Connect" in name:
                schedule = BACKOFF_CONNECT
            if attempt >= len(schedule):
                raise
            wait = schedule[attempt]
            attempt += 1
            print(f"  [재시도] {what} 실패 ({name}) — {wait}초 후 "
                  f"{attempt + 1}/{len(schedule) + 1}", file=sys.stderr)
            time.sleep(wait)


def count_between(sb: Client, start: date, end: date) -> int:
    r = retry(lambda: (
        sb.table("ads")
        .select("review_num", count="exact")
        .gte("review_date", start.isoformat())
        .lte("review_date", end.isoformat())
        .limit(1)
        .execute()
    ), what=f"{start}~{end} 건수")
    return r.count or 0


def fetch_daily_counts(sb: Client, start: date, end: date) -> tuple[dict[str, int], dict[str, str]]:
    """지정 기간의 날짜별 (건수, 그날의 마지막 심의번호).

    마지막 심의번호는 그래프 툴팁에 띄운다. 그 날짜에 어디까지 발급됐는지
    한눈에 보이고, 우리 수집이 어디까지 왔는지도 같이 확인된다.
    Supabase 페이지네이션(1000개 상한)을 넘어가면 여러 번 fetch.
    """
    counts: dict[str, int] = {}
    last_no: dict[str, tuple[int, str]] = {}
    page_size = 1000
    offset = 0
    while True:
        r = retry(lambda: (
            sb.table("ads")
            .select("review_date, review_num, review_no_display")
            .gte("review_date", start.isoformat())
            .lte("review_date", end.isoformat())
            .range(offset, offset + page_size - 1)
            .execute()
        ), what=f"일자별 건수 offset={offset}")
        rows = r.data or []
        for row in rows:
            d = row["review_date"]
            counts[d] = counts.get(d, 0) + 1
            num = row.get("review_num") or 0
            if d not in last_no or num > last_no[d][0]:
                last_no[d] = (num, row.get("review_no_display") or str(num))
        if len(rows) < page_size:
            break
        offset += page_size
    return counts, {d: v[1] for d, v in last_no.items()}


def main() -> None:
    sb = db()
    today = datetime.now(KST).date()

    # "어제" = 달력상 어제가 아니라 **실제 데이터가 있는 가장 최근 날**.
    #
    # 의협 사이트는 심의 결과를 당일에 올리지 않는 경우가 있다. 달력상 어제를 그대로
    # 쓰면 아직 게시되지 않은 날이 '0건'으로 표시되어, 실제로 심의가 0건이었던 것처럼
    # 잘못 읽힌다. (2026-07-31 금요일이 0건으로 표시된 사례)
    # 주말은 원래 심의가 없으므로 건너뛰고, 최대 10일까지 거슬러 올라간다.
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
    total_count = retry(
        lambda: sb.table("ads").select("review_num", count="exact").limit(1).execute(),
        what="누적 건수").count or 0

    yesterday_count = count_between(sb, yesterday, yesterday)
    yesterday_pending = False          # 달력상 어제 데이터가 아직 안 올라온 상태인가
    if yesterday_count == 0:
        probe = yesterday
        for _ in range(10):
            probe -= timedelta(days=1)
            if probe.weekday() >= 5:
                continue
            c = count_between(sb, probe, probe)
            if c > 0:
                yesterday_pending = True
                yesterday, yesterday_count = probe, c
                break
    week_count = count_between(sb, week_start, today)
    month_count = count_between(sb, month_start, today)
    last_week_count = count_between(sb, last_week_start, last_week_end)
    prev_last_week_count = count_between(sb, prev_last_week_start, prev_last_week_end)
    last_month_count = count_between(sb, last_month_start, last_month_end)
    prev_last_month_count = count_between(sb, prev_last_month_start, prev_last_month_end)

    # 30일 그래프
    by_date, last_by_date = fetch_daily_counts(sb, chart_start, today)
    chart: list[dict[str, object]] = []
    cursor = chart_start
    while cursor <= today:
        key = cursor.isoformat()
        row: dict[str, object] = {"date": key, "count": by_date.get(key, 0)}
        if key in last_by_date:
            row["last_review_no"] = last_by_date[key]
        chart.append(row)
        cursor += timedelta(days=1)

    # 데이터 범위
    r_min = retry(lambda: sb.table("ads").select("review_date")
                  .order("review_date", desc=False).limit(1).execute(), what="최초 심의일")
    r_max = retry(lambda: sb.table("ads").select("review_date")
                  .order("review_date", desc=True).limit(1).execute(), what="최종 심의일")
    first_date = r_min.data[0]["review_date"] if r_min.data else None
    last_date = r_max.data[0]["review_date"] if r_max.data else None

    payload = {
        "generated_at": datetime.now(KST).isoformat(),
        "yesterday": {
            "date": yesterday.isoformat(),
            "count": yesterday_count,
            # true 면 달력상 어제 데이터가 아직 게시 전이라 그 이전 집계일로 대체한 것
            "pending": yesterday_pending,
        },
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
    note = " ← 달력상 어제는 아직 게시 전이라 대체" if yesterday_pending else ""
    print(f"  최근 집계일({yesterday}): {yesterday_count}건{note}")
    print(f"  이번주({week_start} ~ {today}): {week_count}건")
    print(f"  이번달({month_start} ~ {today}): {month_count}건")
    print(f"  지난주({last_week_start} ~ {last_week_end}): {last_week_count}건 (지지난주 대비 {last_week_count - prev_last_week_count:+d})")
    print(f"  지난달({last_month_start} ~ {last_month_end}): {last_month_count}건 (지지난달 대비 {last_month_count - prev_last_month_count:+d})")
    print(f"  30일 그래프: {len(chart)}일치")


if __name__ == "__main__":
    main()
