"""뉴스가 없는 날 쓰는 기사 — 우리 심의 데이터가 근거다.

왜 있는가:
    주제를 의료광고·마케팅으로 좁히고 나니 발행이 0편인 날이 생겼다.
    2026-09-01 에 후보 178건 중 광고 관련이 하나도 없었다. 당연하다.
    의료광고 규제 뉴스가 매일 나오지는 않는다.

    그렇다고 임상·예산 기사를 억지로 쓰면 사이트 정체성이 무너지고, 안 쓰면
    발행이 끊겨 검색엔진과 애드센스 양쪽에 불리하다.

    답은 우리 데이터다. 심의 통과 시안 15,000건은 다른 곳에 없다.
    이번 주에 어떤 표현이 늘었는지, 어느 진료과가 몰렸는지는 우리만 쓸 수 있고
    독자(병의원 마케터)에게 그대로 쓸모가 있다.

원칙:
    · 숫자는 전부 우리 집계 파일에서만 온다. AI 가 만들지 않는다.
    · 근거로 넘기는 텍스트에 그 숫자가 그대로 들어가므로, 기존 수치 검증
      (unsupported_numbers) 이 그대로 작동한다.
    · 매번 같은 글이 되지 않도록 데이터에서 실제로 달라진 것을 골라 쓴다.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from news_sources import NewsItem

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent.parent
DATA = ROOT / "website" / "assets" / "data"
BASE_URL = "https://www.admedical.co.kr"


def _load(name: str) -> dict:
    p = DATA / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _dept_rows() -> list[dict]:
    out = []
    for f in sorted((DATA / "dept").glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return sorted(out, key=lambda d: -d.get("ads_analyzed", 0))


def _delta(this: list[dict], last: list[dict]) -> list[tuple[str, int, int]]:
    """양쪽 목록에 **모두 있는** 표현의 증감 (표현, 이번, 지난).

    한쪽에만 있는 표현을 "지난주 0건" 으로 쓰면 거짓말이 된다. TOP20 목록에
    없었을 뿐 실제로는 여러 번 나왔을 수 있다. 우리가 가진 건 상위 20개뿐이므로
    교집합에서만 증감을 말할 수 있다.
    """
    prev = {x["expression"]: x["count"] for x in last}
    out = [(x["expression"], x["count"], prev[x["expression"]])
           for x in this if x["expression"] in prev and x["count"] > prev[x["expression"]]]
    out.sort(key=lambda t: -(t[1] - t[2]))
    return out


def build_topic() -> dict | None:
    """우리 데이터로 오늘 쓸 주제를 만든다. 데이터가 모자라면 None."""
    stats = _load("statistics.json")
    weekly = _load("weekly_top20.json")
    this_week = _load("this_week_top20.json")
    depts = _dept_rows()

    top = weekly.get("top20") or []
    if not stats or len(top) < 10 or not depts:
        return None

    total = stats.get("total", {})
    last_week = stats.get("last_week", {})
    this_month = stats.get("this_month", {})

    risers = _delta(this_week.get("top20") or [], top)[:6]
    # weekly_top20.json 은 AI 가 '마케팅 가치' 기준으로 고른 순서라 빈도순이 아니다.
    # (1위 16건, 2위 19건 같은 일이 생긴다) "가장 자주" 라고 쓰려면 다시 정렬해야 한다.
    top5 = sorted(top, key=lambda x: -x.get("count", 0))[:5]
    dept5 = depts[:5]

    # 근거 텍스트. 여기 있는 숫자만 기사에 쓸 수 있다.
    lines = [
        f"집계 기간: {weekly.get('label', '지난주')}",
        f"지난주 심의 통과: {last_week.get('count', 0)}건 "
        f"(지지난주 대비 {last_week.get('delta', 0):+d}건)",
        f"전체 인덱싱: {total.get('count', 0)}건 "
        f"({total.get('first_date', '')} ~ {total.get('last_date', '')})",
        f"지난주 분석 대상 광고: {weekly.get('ads_analyzed', 0)}건",
    ]
    # 월초에는 이번 달 누적이 0이라 "0건" 이 오해를 부른다. 값이 있을 때만 넣는다.
    if this_month.get("count"):
        lines.append(f"이번 달 누적: {this_month['count']}건")
    lines += ["", "지난주 가장 자주 통과된 표현:"]
    lines += [f"  {i}. {x['expression']} — {x['count']}건 (예: {', '.join(x['examples'][:2])})"
              for i, x in enumerate(top5, 1)]

    if risers:
        lines += ["", "지난주보다 이번 주에 더 자주 나온 표현 "
                      "(양쪽 상위 20개에 모두 든 것만):"]
        lines += [f"  {e} — 이번 주 {now}건 (지난주 {before}건)"
                  for e, now, before in risers]

    lines += ["", "진료과별 누적 통과 시안:"]
    lines += [f"  {d['dept']} — {d['ads_analyzed']}건 "
              f"(자주 쓰인 표현: {', '.join(x['expression'] for x in d['expressions'][:3])})"
              for d in dept5]

    evidence = "\n".join(lines)

    lead_expr = top5[0]["expression"] if top5 else ""
    riser_expr = risers[0][0] if risers else ""

    if riser_expr:
        topic = (f"이번 주 의료광고 심의 통과 시안에서 '{riser_expr}' 표현이 늘었다 "
                 f"— 지난주 통과 {last_week.get('count', 0)}건 집계")
        angle = (f"'{riser_expr}' 가 어떤 맥락에서 통과됐는지, 비슷한 문구를 쓰려는 "
                 f"마케터가 무엇을 확인해야 하는지 짚는다.")
    else:
        topic = (f"지난주 의료광고 심의 통과 {last_week.get('count', 0)}건 분석 "
                 f"— '{lead_expr}' 가 가장 많이 쓰였다")
        angle = ("자주 통과된 표현이 무엇을 뜻하는지, 그대로 베껴 쓰면 왜 위험한지 짚는다.")

    src = NewsItem(
        title=f"admedical 자체 집계 — {weekly.get('label', '지난주')} 심의 통과 시안 분석",
        link=f"{BASE_URL}/top20",
        summary=evidence,
        published=datetime.now(KST),
        source="admedical 자체 데이터",
        kind="data",
    )

    return {
        "selected": True,
        "topic": topic,
        "angle": angle,
        "sources": [src],
        "reason": "수집된 뉴스에 의료광고 주제가 없어 자체 집계로 대체",
        "is_data_story": True,
    }
