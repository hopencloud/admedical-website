"""통계·TOP20 을 정적 HTML 로 미리 박아 넣는다.

왜 있는가:
    /top20 과 / 의 알맹이가 전부 JS 렌더였다. 크롤러가 받는 HTML 에는
    "로딩 중...", "- 건" 만 있었고, 그래서 /top20 의 정적 본문은 559자에 불과했다.
    구글 애드센스가 '가치가 별로 없는 콘텐츠' 로 사이트를 반려한 직접적인 원인이다
    (2026-08-10 정책 위반 통보).

    데이터는 이미 빌드 시점에 JSON 으로 다 만들어져 있다. JS 가 그리기 전에
    같은 내용을 HTML 에 넣어두면 크롤러도 사람도 같은 것을 본다.
    JS 는 그대로 두고 덮어쓰게 한다 (탭 전환이 계속 동작해야 하므로).

실행:
    python scripts/prerender_static.py

daily_pipeline.sh 와 news 워크플로가 통계를 갱신한 뒤 이걸 부른다.
"""
from __future__ import annotations

import html
import json
import re
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
WEB = ROOT / "website"
DATA = WEB / "assets" / "data"

BEGIN = "<!-- prerender:{}:begin -->"
END = "<!-- prerender:{}:end -->"


def load(name: str) -> dict:
    path = DATA / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def inject(text: str, key: str, block: str) -> str:
    """마커 사이를 갈아끼운다. 마커가 없으면 그대로 돌려준다."""
    begin, end = BEGIN.format(key), END.format(key)
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        raise SystemExit(f"[오류] '{key}' 마커가 없습니다. HTML 에 먼저 넣어주세요.")
    return pattern.sub(f"{begin}\n{block}\n{end}", text, count=1)


def fmt_date(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
        return f"{d.year}년 {d.month}월 {d.day}일"
    except (ValueError, TypeError):
        return iso or ""


# ==========================================================
# /top20
# ==========================================================

def render_top20() -> None:
    data = load("weekly_top20")          # 첫 화면 기본 탭이 '지난주'
    items = data.get("top20") or []
    if not items:
        print("  [건너뜀] 지난주 TOP20 데이터가 비어 있습니다.")
        return

    # label 에 이미 "지난주 (2026-08-03 ~ 2026-08-09)" 형태로 기간이 들어 있다.
    # 여기서 날짜를 또 붙이면 같은 기간이 두 번 찍힌다.
    label = str(data.get("label") or "지난주")
    span = f"{fmt_date(data.get('start_date'))} ~ {fmt_date(data.get('end_date'))}"
    period = f"{label} · 광고 {data.get('ads_analyzed', 0):,}건 분석"

    rows = []
    for i, item in enumerate(items, 1):
        expr = html.escape(str(item.get("expression", "")))
        cnt = item.get("count", 0)
        rows.append(
            '<li class="flex items-center gap-4 bg-white p-4 rounded-2xl border border-slate-200">'
            f'<span class="w-8 text-center font-bold text-brand-600 tabular-nums">{i}</span>'
            f'<span class="flex-1 font-medium text-slate-900">{expr}</span>'
            f'<span class="text-xs text-slate-500 tabular-nums">{cnt}건 등장</span></li>'
        )

    # 순위표만 있으면 표 하나짜리 페이지다. 그 주에 무엇이 눈에 띄었는지
    # 문장으로 정리해 사람이 읽을 거리를 만든다. 수치는 전부 실측값에서 뽑는다.
    top3 = ", ".join(html.escape(str(x.get("expression", ""))) for x in items[:3])
    total = sum(x.get("count", 0) for x in items)
    lead = (
        f'<p class="text-slate-700 leading-relaxed mb-4">'
        f'{span} 심의를 통과한 광고 '
        f'{data.get("ads_analyzed", 0):,}건에서 가장 자주 등장한 표현은 '
        f'<strong>{top3}</strong> 순이었습니다. 상위 20개 표현은 모두 합쳐 '
        f'{total:,}회 등장했습니다.</p>'
        f'<p class="text-slate-700 leading-relaxed mb-6">'
        f'여기 오른 표현은 <strong>심의를 통과한 시안에 실제로 쓰인 문구</strong>입니다. '
        f'다만 같은 단어라도 시안 전체 맥락에 따라 판단이 달라지므로, '
        f'그대로 옮겨 쓰기보다 어떤 맥락에서 쓰였는지를 심의번호로 확인하시는 편이 안전합니다.</p>'
    )

    block = (f'<div class="text-sm text-slate-500 mb-5">{period}</div>\n'
             f'{lead}\n'
             f'<ol class="space-y-2">\n' + "\n".join(rows) + "\n</ol>")

    path = WEB / "top20.html"
    path.write_text(inject(path.read_text(encoding="utf-8"), "top20", block),
                    encoding="utf-8")
    print(f"  top20.html — {len(items)}개 표현 정적화")


# ==========================================================
# / (메인 통계)
# ==========================================================

def render_index() -> None:
    stats = load("statistics")
    if not stats:
        print("  [건너뜀] statistics.json 이 없습니다.")
        return

    y = stats.get("yesterday", {})
    lw = stats.get("last_week", {})
    lm = stats.get("last_month", {})
    total = stats.get("total", {})

    def delta(d: dict) -> str:
        n = d.get("delta", 0)
        if n > 0:
            return f"지난 기간 대비 +{n:,}건"
        if n < 0:
            return f"지난 기간 대비 {n:,}건"
        return "지난 기간과 동일"

    block = (
        f'<p class="text-slate-700 leading-relaxed">'
        f'{fmt_date(y.get("date"))} 기준 대한의사협회 의료광고심의위원회를 통과한 광고는 '
        f'<strong>{y.get("count", 0):,}건</strong>입니다. '
        f'이번 주에는 {stats.get("this_week", {}).get("count", 0):,}건, '
        f'지난주에는 {lw.get("count", 0):,}건이 통과했습니다({delta(lw)}). '
        f'지난달 전체로는 {lm.get("count", 0):,}건이며, '
        f'{fmt_date(total.get("first_date"))}부터 지금까지 '
        f'<strong>{total.get("count", 0):,}건</strong>의 통과 시안을 텍스트로 인덱싱해 두었습니다.'
        f'</p>'
    )

    path = WEB / "index.html"
    path.write_text(inject(path.read_text(encoding="utf-8"), "stats", block),
                    encoding="utf-8")
    print(f"  index.html — 통계 문장 정적화 (누적 {total.get('count', 0):,}건)")


def main() -> None:
    print("[정적 렌더]")
    render_top20()
    render_index()


if __name__ == "__main__":
    main()
