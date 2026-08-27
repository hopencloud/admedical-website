"""진료과별 통과 표현 페이지 생성 → website/expressions/<slug>.html

왜 있는가:
    서치콘솔을 뜯어보니 노출의 92%가 "대한의사협회 의료광고심의위원회"(의협 공식
    사이트 찾기)와 "국가법령정보센터 의료법 제57조"(법령 원문 찾기)에서 나왔다.
    순위 6~9위인데 클릭 0. 우리를 찾는 사람이 아니다.

    정작 "정형외과 광고 문구", "피부과 의료광고 심의 통과 사례" 처럼 우리 데이터가
    진짜 답인 검색어로는 뜨는 페이지가 없었다. 이 스크립트가 그 페이지를 만든다.

도어웨이가 되지 않기 위해:
    · 페이지마다 **그 진료과의 실측 집계**가 들어간다 (표현·등장 횟수·심의번호 예시).
    · 해설은 집계 결과를 근거로 AI 가 쓰되, 표에 없는 표현은 언급하지 못하게 막는다.
    · 진료과 이름만 바꾼 같은 글이 나오면 그 페이지는 버린다 (유사도 검사).
    · 페이지 수를 늘리는 게 목적이 아니다. 진료과를 함부로 추가하지 말 것.

실행:
    python scripts/render_dept_pages.py
    python scripts/render_dept_pages.py --slug orthopedics --dry-run
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
WEB = ROOT / "website"
DATA_DIR = WEB / "assets" / "data" / "dept"
OUT_DIR = WEB / "expressions"
BASE_URL = "https://www.admedical.co.kr"
KST = timezone(timedelta(hours=9))

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv(ROOT / ".env")

import news_render  # noqa: E402  (공통 헤더 재사용)
import news_writer  # noqa: E402

SYSTEM = """당신은 의료광고 심의 데이터를 다루는 매체 'admedical'의 에디터입니다.
독자는 그 진료과 병의원의 마케팅 담당자와 원장입니다.

[절대 규칙]
- 제공된 표현 목록에 **실제로 있는 표현만** 언급하세요. 없는 표현을 지어내면 안 됩니다.
- 건수·비율을 새로 만들지 마세요. 주어진 숫자만 씁니다.
- "이 표현을 쓰면 통과한다"고 단정하지 마세요. 심의는 시안 전체를 봅니다.
- 의학적 효과를 단정하지 마세요."""

PROMPT = """아래는 **{dept}** 광고 중 의료광고심의위원회를 통과한 {ads:,}건에서
실제로 자주 등장한 표현을 집계한 결과입니다.

{table}

이 집계를 근거로 해설을 쓰세요. **{dept} 에만 해당하는 이야기**여야 합니다.
다른 진료과에 그대로 옮겨도 말이 되는 문장은 쓰지 마세요.

JSON으로만 답하세요:
{{
  "intro": "이 진료과 통과 시안의 특징을 짚는 도입 3~4문장. 위 표에서 눈에 띄는 것을 근거로.",
  "sections": [
    {{"heading": "질문형 또는 결론형 소제목 (검색어를 포함)",
      "body": "3~4문장. 위 표의 특정 표현을 실제로 언급하며 설명"}},
    {{"heading": "...", "body": "..."}},
    {{"heading": "...", "body": "..."}}
  ],
  "caution": "이 진료과 광고에서 특히 조심할 지점 2~3문장. 의료법상 금지되는 표현 유형과 엮어서.",
  "meta_description": "검색결과용 설명문 80자 이내"
}}

[소제목 힌트 — 실제로 검색되는 말을 쓰세요]
"{dept} 광고 문구", "{dept} 의료광고 심의", "{dept} 마케팅" 같은 표현을
소제목 중 최소 하나에 넣으세요."""


def load_all() -> list[dict]:
    return [json.loads(f.read_text(encoding="utf-8"))
            for f in sorted(DATA_DIR.glob("*.json"))]


def write_copy(d: dict) -> dict:
    table = "\n".join(
        f"  {i:>2}. {x['expression']} — {x['count']}건 등장"
        for i, x in enumerate(d["expressions"], 1))
    return news_writer._chat_json(
        news_writer.WRITER_MODEL, SYSTEM,
        PROMPT.format(dept=d["dept"], ads=d["ads_analyzed"], table=table),
        max_tokens=2500, temperature=0.5)


def bigrams(s: str) -> set[str]:
    t = re.sub(r"[^0-9a-zA-Z가-힣]", "", s)
    return {t[i:i + 2] for i in range(len(t) - 1)} or {t}


def similarity(a: str, b: str) -> float:
    x, y = bigrams(a), bigrams(b)
    return len(x & y) / len(x | y) if x | y else 0.0


def body_text(copy: dict) -> str:
    return " ".join([copy.get("intro", ""),
                     *(s.get("body", "") for s in copy.get("sections", [])),
                     copy.get("caution", "")])


def fmt_date(iso: str | None) -> str:
    try:
        from datetime import date
        d = date.fromisoformat(iso)
        return f"{d.year}년 {d.month}월 {d.day}일"
    except (ValueError, TypeError):
        return iso or ""


def render(d: dict, copy: dict) -> str:
    dept, slug = d["dept"], d["slug"]
    url = f"{BASE_URL}/expressions/{slug}"
    title = f"{dept} 광고 문구 — 심의 통과 표현 {len(d['expressions'])}선"
    desc = (copy.get("meta_description") or
            f"{dept} 의료광고 심의 통과 시안 {d['ads_analyzed']:,}건에서 자주 쓰인 표현 정리.")[:80]

    rows = "\n".join(
        f'<tr class="border-b border-slate-100">'
        f'<td class="py-2.5 pr-3 text-slate-400 tabular-nums">{i}</td>'
        f'<td class="py-2.5 pr-3 font-medium text-slate-900">{html.escape(x["expression"])}</td>'
        f'<td class="py-2.5 pr-3 text-slate-600 tabular-nums whitespace-nowrap">{x["count"]}건</td>'
        f'<td class="py-2.5 text-xs text-slate-500 tabular-nums">'
        f'{html.escape(", ".join(x["examples"][:2]))}</td></tr>'
        for i, x in enumerate(d["expressions"], 1))

    sections = "\n".join(
        f'<section class="mb-8">'
        f'<h2 class="text-xl font-bold mb-3 tracking-tight">{html.escape(s.get("heading", ""))}</h2>'
        f'<p class="text-slate-700 leading-relaxed">{html.escape(s.get("body", ""))}</p>'
        f'</section>'
        for s in copy.get("sections", []))

    others = "\n".join(
        f'<a href="/expressions/{o["slug"]}" class="px-3 py-1.5 bg-white border border-slate-200 '
        f'rounded-lg text-sm hover:border-brand-500 hover:text-brand-600 transition">'
        f'{html.escape(o["dept"])}</a>'
        for o in load_all() if o["slug"] != slug)

    ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": title,
        "description": desc,
        "url": url,
        "inLanguage": "ko",
        "isAccessibleForFree": True,
        "creator": {"@type": "Organization", "name": "admedical", "url": BASE_URL},
        "temporalCoverage": f'{d.get("first_date", "")}/{d.get("last_date", "")}',
        "variableMeasured": [x["expression"] for x in d["expressions"][:10]],
    }, ensure_ascii=False, indent=2)

    crumb = json.dumps({
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "홈", "item": f"{BASE_URL}/"},
            {"@type": "ListItem", "position": 2, "name": "진료과별 통과 표현",
             "item": f"{BASE_URL}/expressions"},
            {"@type": "ListItem", "position": 3, "name": dept, "item": url},
        ]}, ensure_ascii=False, indent=2)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="google-adsense-account" content="ca-pub-7650355816152791">
    <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-7650355816152791"
            crossorigin="anonymous"></script>
    <link rel="icon" href="/favicon.ico" sizes="any">
    <link rel="icon" type="image/png" sizes="32x32" href="/assets/img/favicon-32x32.png">
    <link rel="apple-touch-icon" sizes="180x180" href="/assets/img/favicon-180x180.png">
    <title>{html.escape(title)} | admedical</title>
    <meta name="description" content="{html.escape(desc)}">
    <meta name="keywords" content="{dept} 광고 문구, {dept} 의료광고, {dept} 의료광고 심의, {dept} 마케팅, {dept} 광고 심의 통과">
    <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1">
    <meta name="naver:robots" content="all">
    <link rel="canonical" href="{url}">
    <link rel="alternate" type="application/rss+xml" title="admedical 의료광고 인사이트" href="{BASE_URL}/rss.xml">
    <meta property="og:type" content="article">
    <meta property="og:site_name" content="admedical">
    <meta property="og:title" content="{html.escape(title)}">
    <meta property="og:description" content="{html.escape(desc)}">
    <meta property="og:url" content="{url}">
    <meta property="og:image" content="{BASE_URL}/assets/img/ogimage.png">
    <meta property="og:image:alt" content="{html.escape(title)}">
    <meta property="og:locale" content="ko_KR">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{html.escape(title)}">
    <meta name="twitter:description" content="{html.escape(desc)}">
    <meta name="twitter:image" content="{BASE_URL}/assets/img/ogimage.png">
    <meta name="twitter:image:alt" content="{html.escape(title)}">
    <link rel="preconnect" href="https://cdn.jsdelivr.net">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {{ theme: {{ extend: {{
            fontFamily: {{ sans: ['"Pretendard Variable"', 'Pretendard', '-apple-system', 'system-ui', 'sans-serif'] }},
            colors: {{ brand: {{ 50: '#eff6ff', 100: '#dbeafe', 500: '#3b82f6', 600: '#2563eb', 700: '#1d4ed8', 900: '#1e3a8a' }} }},
            boxShadow: {{ soft: '0 1px 2px rgba(15,23,42,.04), 0 4px 12px rgba(15,23,42,.04)' }},
        }} }} }};
    </script>
    <link rel="stylesheet" href="/assets/css/site.css?v=20260804a">
    <script type="application/ld+json">
{ld}
    </script>
    <script type="application/ld+json">
{crumb}
    </script>
</head>
<body class="bg-slate-50 text-slate-900 antialiased">

{news_render.STATIC_HEADER}

<main class="max-w-3xl mx-auto px-5 sm:px-6 py-8 sm:py-12">
    <nav class="text-xs text-slate-500 mb-4">
        <a href="/" class="hover:text-brand-600">홈</a> ›
        <a href="/expressions" class="hover:text-brand-600">진료과별 통과 표현</a> ›
        <span class="text-slate-700">{html.escape(dept)}</span>
    </nav>

    <h1 class="text-3xl md:text-4xl font-bold mb-4 tracking-tight leading-tight">
        {html.escape(dept)} 광고 문구 — 심의 통과 표현 {len(d['expressions'])}선
    </h1>

    <p class="text-base text-slate-700 leading-relaxed mb-8 bg-brand-50 border-l-4 border-brand-500 px-4 py-3 rounded-r-lg">
        대한의사협회 의료광고심의위원회를 <strong>통과한 {html.escape(dept)} 광고
        {d['ads_analyzed']:,}건</strong>({fmt_date(d.get('first_date'))} ~ {fmt_date(d.get('last_date'))})의
        문구를 집계했습니다. 아래 표현은 <strong>실제로 심의를 통과한 시안에 쓰인 말</strong>이며,
        각 행의 심의번호로 원본을 확인하실 수 있습니다.
    </p>

    <div class="ad-slot" data-slot-name="dept-top" data-ad-format="auto"></div>

    <p class="text-slate-700 leading-relaxed mb-8">{html.escape(copy.get('intro', ''))}</p>

    <h2 class="text-xl font-bold mb-3 tracking-tight">
        {html.escape(dept)} 통과 시안에 자주 쓰인 표현
    </h2>
    <div class="bg-white rounded-2xl border border-slate-200 shadow-soft p-5 mb-4 overflow-x-auto">
        <table class="w-full text-sm">
            <thead>
                <tr class="border-b-2 border-slate-200 text-left text-xs text-slate-500">
                    <th class="pb-2 pr-3 font-semibold">#</th>
                    <th class="pb-2 pr-3 font-semibold">표현</th>
                    <th class="pb-2 pr-3 font-semibold whitespace-nowrap">등장</th>
                    <th class="pb-2 font-semibold">심의번호 예시</th>
                </tr>
            </thead>
            <tbody>
{rows}
            </tbody>
        </table>
    </div>
    <p class="text-xs text-slate-500 mb-10">
        같은 광고 안에서 여러 번 나와도 1건으로 셉니다. 심의번호는
        <a href="https://www.admedical.org/application/approval_confirm.do" target="_blank"
           rel="noopener nofollow" class="text-brand-600 hover:underline">의협 공식 사이트</a>에서
        조회하시면 원본 시안을 보실 수 있습니다.
    </p>

{sections}

    <section class="bg-amber-50 border border-amber-300 rounded-2xl p-5 mb-10">
        <h2 class="text-base font-bold text-slate-900 mb-2">{html.escape(dept)} 광고에서 조심할 것</h2>
        <p class="text-sm text-slate-700 leading-relaxed">{html.escape(copy.get('caution', ''))}</p>
        <p class="text-sm text-slate-700 leading-relaxed mt-3">
            <strong>이 목록은 통과를 보장하지 않습니다.</strong> 심의는 문구 하나가 아니라
            시안 전체를 봅니다. 같은 표현도 어떤 시술을 어떻게 설명하느냐에 따라 결과가 갈립니다.
            <a href="/guide/forbidden-expressions" class="text-brand-600 hover:underline">금지 표현과 대안</a>을
            함께 확인하세요.
        </p>
    </section>

    <div class="ad-slot" data-slot-name="dept-bottom" data-ad-format="auto"></div>

    <section class="mb-10">
        <h2 class="text-base font-bold text-slate-900 mb-3">다른 진료과 보기</h2>
        <div class="flex flex-wrap gap-2">
{others}
        </div>
    </section>

    <section class="bg-white rounded-2xl border border-slate-200 shadow-soft p-5">
        <h2 class="text-base font-bold text-slate-900 mb-3">함께 보면 좋은 문서</h2>
        <ul class="space-y-2 text-sm">
            <li><a href="/guide/forbidden-expressions" class="text-brand-600 hover:underline">→ 의료광고 금지 표현과 대안</a></li>
            <li><a href="/guide/application" class="text-brand-600 hover:underline">→ 심의 신청 절차·서류·수수료</a></li>
            <li><a href="/top20" class="text-brand-600 hover:underline">→ 전체 진료과 통과 표현 TOP 20</a></li>
            <li><a href="/" class="text-brand-600 hover:underline">→ 통과 문구 키워드 검색</a></li>
        </ul>
    </section>
</main>

<footer class="bg-white border-t border-slate-200 mt-20">
    <div class="max-w-5xl mx-auto px-5 sm:px-6 py-8 text-sm text-slate-500">
        <div class="flex flex-wrap gap-5 mb-3 font-medium">
            <a href="/about" class="hover:text-brand-600">서비스 소개</a>
            <a href="/news" class="hover:text-brand-600">의료광고 인사이트</a>
            <a href="/top20" class="hover:text-brand-600">심의통과 TOP 20 키워드</a>
            <a href="/contact" class="hover:text-brand-600">문의</a>
            <a href="/terms" class="hover:text-brand-600">이용약관</a>
            <a href="/privacy" class="hover:text-brand-600">개인정보처리방침</a>
        </div>
        <p class="text-xs">본 페이지는 심의 통과 시안의 텍스트를 집계한 것으로, 심의 통과를 보장하지 않습니다.</p>
    </div>
</footer>
<script src="/assets/js/site.js?v=20260804a"></script>
<script src="/assets/js/ads.js?v=20260804a" defer></script>
</body>
</html>
"""


def render_index(items: list[dict]) -> str:
    cards = "\n".join(
        f'<li><a href="/expressions/{d["slug"]}" '
        f'class="block bg-white rounded-2xl border border-slate-200 p-5 shadow-soft '
        f'hover:border-brand-500 transition">'
        f'<div class="font-bold text-slate-900 mb-1">{html.escape(d["dept"])} 광고 문구</div>'
        f'<div class="text-sm text-slate-600">통과 시안 {d["ads_analyzed"]:,}건 · '
        f'표현 {len(d["expressions"])}개</div>'
        f'<div class="text-xs text-slate-500 mt-2">'
        f'{html.escape(", ".join(x["expression"] for x in d["expressions"][:4]))} …</div>'
        f'</a></li>'
        for d in sorted(items, key=lambda x: -x["ads_analyzed"]))

    total = sum(d["ads_analyzed"] for d in items)
    desc = f"진료과별 의료광고 심의 통과 문구 집계. {len(items)}개 과, 통과 시안 {total:,}건 분석."
    ld = json.dumps({
        "@context": "https://schema.org", "@type": "CollectionPage",
        "name": "진료과별 의료광고 심의 통과 표현",
        "description": desc, "url": f"{BASE_URL}/expressions", "inLanguage": "ko",
    }, ensure_ascii=False, indent=2)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="google-adsense-account" content="ca-pub-7650355816152791">
    <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-7650355816152791"
            crossorigin="anonymous"></script>
    <link rel="icon" href="/favicon.ico" sizes="any">
    <link rel="apple-touch-icon" sizes="180x180" href="/assets/img/favicon-180x180.png">
    <title>진료과별 의료광고 심의 통과 표현 — {len(items)}개 진료과 | admedical</title>
    <meta name="description" content="{html.escape(desc[:80])}">
    <meta name="robots" content="index, follow, max-image-preview:large">
    <meta name="naver:robots" content="all">
    <link rel="canonical" href="{BASE_URL}/expressions">
    <link rel="alternate" type="application/rss+xml" title="admedical 의료광고 인사이트" href="{BASE_URL}/rss.xml">
    <meta property="og:type" content="website">
    <meta property="og:site_name" content="admedical">
    <meta property="og:title" content="진료과별 의료광고 심의 통과 표현">
    <meta property="og:description" content="{html.escape(desc[:80])}">
    <meta property="og:url" content="{BASE_URL}/expressions">
    <meta property="og:image" content="{BASE_URL}/assets/img/ogimage.png">
    <meta property="og:image:alt" content="진료과별 의료광고 심의 통과 표현">
    <meta property="og:locale" content="ko_KR">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="진료과별 의료광고 심의 통과 표현">
    <meta name="twitter:description" content="{html.escape(desc[:80])}">
    <meta name="twitter:image" content="{BASE_URL}/assets/img/ogimage.png">
    <meta name="twitter:image:alt" content="진료과별 의료광고 심의 통과 표현">
    <link rel="preconnect" href="https://cdn.jsdelivr.net">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {{ theme: {{ extend: {{
            fontFamily: {{ sans: ['"Pretendard Variable"', 'Pretendard', '-apple-system', 'system-ui', 'sans-serif'] }},
            colors: {{ brand: {{ 50: '#eff6ff', 100: '#dbeafe', 500: '#3b82f6', 600: '#2563eb', 700: '#1d4ed8', 900: '#1e3a8a' }} }},
            boxShadow: {{ soft: '0 1px 2px rgba(15,23,42,.04), 0 4px 12px rgba(15,23,42,.04)' }},
        }} }} }};
    </script>
    <link rel="stylesheet" href="/assets/css/site.css?v=20260804a">
    <script type="application/ld+json">
{ld}
    </script>
</head>
<body class="bg-slate-50 text-slate-900 antialiased">

{news_render.STATIC_HEADER}

<main class="max-w-3xl mx-auto px-5 sm:px-6 py-8 sm:py-12">
    <h1 class="text-3xl md:text-4xl font-bold mb-4 tracking-tight">진료과별 의료광고 심의 통과 표현</h1>
    <p class="text-slate-700 leading-relaxed mb-8">
        대한의사협회 의료광고심의위원회를 통과한 광고 시안을 진료과별로 나눠,
        실제로 자주 쓰인 문구를 집계했습니다. 지금까지 <strong>{len(items)}개 진료과
        {total:,}건</strong>을 분석했습니다. 각 표현에는 등장 횟수와 심의번호 예시가 붙어 있어
        원본 시안을 직접 확인하실 수 있습니다.
    </p>

    <h2 class="text-base font-bold text-slate-900 mb-3">진료과 선택</h2>
    <ul class="grid sm:grid-cols-2 gap-3 mb-10">
{cards}
    </ul>

    <section class="bg-white rounded-2xl border border-slate-200 shadow-soft p-6">
        <h2 class="text-base font-bold text-slate-900 mb-3">집계 방식과 한계</h2>
        <p class="text-sm text-slate-700 leading-relaxed mb-3">
            통과 시안의 광고 문구를 기계로 읽어(OCR) 2~4단어 구간을 뽑고, 정형구와
            인식 오류를 걸러낸 뒤 등장 횟수를 셉니다. 같은 광고 안에서 여러 번 나와도
            1건으로 셉니다. 진료과 분류는 시안 문구에 그 진료과 이름이 나오는지를 기준으로 하며,
            한 시안이 여러 진료과에 걸칠 수 있습니다.
        </p>
        <p class="text-sm text-slate-700 leading-relaxed">
            <strong>여기 오른 표현이 통과를 보장하지는 않습니다.</strong> 심의는 문구가 아니라
            시안 전체를 보고 판단합니다. 참고 지표로만 쓰시고, 실제 문구는 시술 내용에 맞게
            새로 쓰시기 바랍니다.
        </p>
    </section>
</main>

<footer class="bg-white border-t border-slate-200 mt-20">
    <div class="max-w-5xl mx-auto px-5 sm:px-6 py-8 text-sm text-slate-500">
        <div class="flex flex-wrap gap-5 mb-3 font-medium">
            <a href="/about" class="hover:text-brand-600">서비스 소개</a>
            <a href="/news" class="hover:text-brand-600">의료광고 인사이트</a>
            <a href="/top20" class="hover:text-brand-600">심의통과 TOP 20 키워드</a>
            <a href="/contact" class="hover:text-brand-600">문의</a>
            <a href="/terms" class="hover:text-brand-600">이용약관</a>
            <a href="/privacy" class="hover:text-brand-600">개인정보처리방침</a>
        </div>
    </div>
</footer>
<script src="/assets/js/site.js?v=20260804a"></script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    items = load_all()
    if not items:
        print("[오류] compute_dept_expressions.py 를 먼저 돌리세요.")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[tuple[str, str]] = []      # (dept, 본문)
    made = []

    for d in items:
        if args.slug and d["slug"] != args.slug:
            continue
        copy = write_copy(d)
        text = body_text(copy)

        # 진료과 이름만 바꾼 같은 글이면 버린다. 그런 페이지가 도어웨이로 걸린다.
        dupe = next((n for n, t in written if similarity(text, t) >= 0.55), None)
        if dupe:
            print(f"  [버림] {d['dept']} — {dupe} 와 본문이 거의 같음")
            continue
        written.append((d["dept"], text))

        n = len(re.sub(r"\s", "", text))
        print(f"  {d['dept']:8} 해설 {n:>4}자 · 표현 {len(d['expressions'])}개")
        if not args.dry_run:
            (OUT_DIR / f"{d['slug']}.html").write_text(render(d, copy), encoding="utf-8")
        made.append(d)

    if not args.dry_run and made:
        (OUT_DIR / "index.html").write_text(render_index(made), encoding="utf-8")

    print(f"\n{len(made)}개 페이지" + (" (dry-run)" if args.dry_run else f" → {OUT_DIR.relative_to(ROOT)}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
