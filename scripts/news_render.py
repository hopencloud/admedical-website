"""
정적 HTML 렌더링 — 기사 상세 / 목록 / 사이트맵.

Supabase가 아니라 정적 파일을 원본으로 삼는다. 이유:
  · 검색엔진이 JS 실행 없이 본문을 그대로 읽는다 (SEO·애드센스 크롤러에 유리)
  · Vercel 정적 호스팅이라 추가 비용·지연이 없다
  · 글이 깨져도 git 이력으로 즉시 되돌릴 수 있다

기존 페이지(guide/*.html)와 동일한 디자인 토큰을 쓴다.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))
from build_header import build_block, extract_header_html   # noqa: E402

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent.parent
WEB = ROOT / "website"
NEWS_DIR = WEB / "news"
INDEX_JSON = WEB / "assets" / "data" / "news-index.json"
SITEMAP = WEB / "sitemap.xml"

BASE_URL = "https://www.admedical.co.kr"
ADSENSE_PUB = "ca-pub-7650355816152791"
ASSET_VER = "20260801a"

SITEMAP_BEGIN = "    <!-- news:begin (자동 생성 — 직접 수정하지 마세요) -->"
SITEMAP_END = "    <!-- news:end -->"


# 헤더는 정적으로 심는다 — 네이버 Yeti 는 JS 주입 헤더의 링크를 못 읽는다.
STATIC_HEADER = build_block(extract_header_html())


def esc(text) -> str:
    return html.escape(str(text or ""), quote=True)


# ---------- 공통 head ----------

def _head(title: str, description: str, canonical: str, og_image: str,
          og_type: str = "article", extra_ld: str = "") -> str:
    return f"""<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <!-- Google AdSense -->
    <meta name="google-adsense-account" content="{ADSENSE_PUB}">
    <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADSENSE_PUB}"
            crossorigin="anonymous"></script>

    <link rel="icon" href="/favicon.ico" sizes="any">
    <link rel="icon" type="image/png" sizes="32x32" href="/assets/img/favicon-32x32.png">
    <link rel="icon" type="image/png" sizes="16x16" href="/assets/img/favicon-16x16.png">
    <link rel="apple-touch-icon" sizes="180x180" href="/assets/img/favicon-180x180.png">

    <title>{esc(title)}</title>
    <meta name="description" content="{esc(description)}">
    <meta name="author" content="admedical">
    <meta name="robots" content="index, follow, max-image-preview:large">
    <meta name="naver:robots" content="all">
    <meta name="Yeti" content="index, follow">
    <link rel="canonical" href="{esc(canonical)}">

    <meta property="og:type" content="{og_type}">
    <meta property="og:site_name" content="admedical 의료광고 인사이트">
    <meta property="og:title" content="{esc(title)}">
    <meta property="og:description" content="{esc(description)}">
    <meta property="og:url" content="{esc(canonical)}">
    <meta property="og:image" content="{esc(og_image)}">
    <meta property="og:locale" content="ko_KR">

    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{esc(title)}">
    <meta name="twitter:description" content="{esc(description)}">
    <meta name="twitter:image" content="{esc(og_image)}">

    <link rel="preconnect" href="https://cdn.jsdelivr.net">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">

    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {{
            theme: {{ extend: {{
                fontFamily: {{ sans: ['"Pretendard Variable"', 'Pretendard', '-apple-system', 'BlinkMacSystemFont', 'system-ui', 'sans-serif'] }},
                colors: {{ brand: {{ 50: '#eff6ff', 100: '#dbeafe', 500: '#3b82f6', 600: '#2563eb', 700: '#1d4ed8', 900: '#1e3a8a' }} }},
                boxShadow: {{ soft: '0 1px 2px rgba(15, 23, 42, 0.04), 0 4px 12px rgba(15, 23, 42, 0.04)' }},
            }} }},
        }};
    </script>
    <link rel="stylesheet" href="/assets/css/site.css?v={ASSET_VER}">
{extra_ld}</head>"""


FOOTER = f"""<footer class="bg-white border-t border-slate-200 mt-20">
    <div class="max-w-5xl mx-auto px-4 py-8 text-sm text-slate-500">
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

<script src="/assets/js/site.js?v={ASSET_VER}"></script>
<script src="/assets/js/ads.js?v={ASSET_VER}" defer></script>
</body>
</html>
"""

AI_DISCLOSURE = """
    <aside class="mt-10 bg-slate-100 border border-slate-200 rounded-2xl px-5 py-4">
        <p class="text-xs text-slate-600 leading-relaxed">
            <strong class="text-slate-700">콘텐츠 생성 방식 안내</strong><br>
            본 글은 공개된 언론 보도와 정부 보도자료, 그리고 admedical이 자체 수집한 의료광고 심의 통과 시안
            데이터를 바탕으로 AI 도구의 도움을 받아 작성되었습니다. 사실관계는 하단 출처에서 직접 확인하시기
            바라며, 법적 판단이 필요한 사안은 대한의사협회 의료광고심의위원회 또는 관계 당국에 문의하시기 바랍니다.
            본 콘텐츠는 정보 제공 목적이며 법적 자문이 아닙니다.
        </p>
    </aside>
"""


# ---------- 기사 상세 ----------

def render_post(article: dict, meta: dict, chart_svg: str = "",
                checklist_svg: str = "") -> str:
    """meta: {slug, date, cover, inline_image, sources:[{title,source,link,date}]}"""
    slug = meta["slug"]
    date_str = meta["date"]                       # YYYY-MM-DD
    canonical = f"{BASE_URL}/news/{slug}"
    cover = meta.get("cover") or ""
    og_image = f"{BASE_URL}{cover}" if cover else f"{BASE_URL}/assets/img/ogimage.png"

    ld_article = json.dumps({
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": article.get("title", "")[:110],
        "description": article.get("summary", ""),
        "image": og_image,
        "datePublished": f"{date_str}T09:00:00+09:00",
        "dateModified": f"{date_str}T09:00:00+09:00",
        "inLanguage": "ko",
        "author": {"@type": "Organization", "name": "admedical"},
        "publisher": {
            "@type": "Organization",
            "name": "admedical",
            "logo": {"@type": "ImageObject", "url": f"{BASE_URL}/assets/img/ogimage.png"},
        },
        "mainEntityOfPage": canonical,
    }, ensure_ascii=False, indent=4)

    ld_crumb = json.dumps({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "홈", "item": f"{BASE_URL}/"},
            {"@type": "ListItem", "position": 2, "name": "의료광고 인사이트", "item": f"{BASE_URL}/news"},
            {"@type": "ListItem", "position": 3, "name": article.get("title", ""), "item": canonical},
        ],
    }, ensure_ascii=False, indent=4)

    extra_ld = (f'    <script type="application/ld+json">\n{ld_article}\n    </script>\n'
                f'    <script type="application/ld+json">\n{ld_crumb}\n    </script>\n')

    # FAQ 스키마 — 구글 리치결과와 AI 검색 답변 인용(AEO)에 쓰인다.
    faqs = [f for f in (article.get("faq") or []) if f.get("q") and f.get("a")][:5]
    if faqs:
        ld_faq = json.dumps({
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": f["q"],
                 "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                for f in faqs
            ],
        }, ensure_ascii=False, indent=4)
        extra_ld += f'    <script type="application/ld+json">\n{ld_faq}\n    </script>\n'

    head = _head(
        title=f"{article.get('title', '')} | admedical 의료광고 인사이트",
        description=article.get("summary", ""),
        canonical=canonical,
        og_image=og_image,
        extra_ld=extra_ld,
    )

    # ----- 본문 조립 -----
    body: list[str] = []

    # alt 는 AI가 기사 내용에 맞춰 써 준 설명문을 쓰고, 없으면 제목으로 대체한다.
    cover_alt = article.get("cover_alt") or f'{article.get("title", "")} 내용을 표현한 일러스트'
    inline_alt = article.get("inline_alt") or f'{article.get("title", "")} 관련 설명 일러스트'

    if cover:
        body.append(
            f'<figure class="mb-8 -mx-4 sm:mx-0">'
            f'<img src="{esc(cover)}" alt="{esc(cover_alt)}" '
            f'class="w-full sm:rounded-2xl border border-slate-200" loading="eager" width="1536" height="1024">'
            f'</figure>'
        )

    if article.get("lead"):
        body.append(
            f'<p class="text-base md:text-lg text-slate-700 leading-relaxed mb-8 '
            f'bg-brand-50 border-l-4 border-brand-500 px-4 py-3 rounded-r-lg">'
            f'{esc(article["lead"])}</p>'
        )

    body.append('<div class="ad-slot" data-slot-name="article-section" data-ad-format="auto"></div>')

    sections = article.get("sections") or []
    inline_img = meta.get("inline_image")

    for idx, sec in enumerate(sections):
        body.append('<section class="mb-10">')
        if sec.get("heading"):
            body.append(
                f'<h2 class="text-2xl font-bold mb-4 tracking-tight text-slate-900">{esc(sec["heading"])}</h2>'
            )
        for para in sec.get("paragraphs", []):
            body.append(f'<p class="text-[15px] md:text-base text-slate-700 leading-[1.9] mb-4">{esc(para)}</p>')
        body.append('</section>')

        # 첫 섹션 뒤 = 데이터 도표, 두 번째 섹션 뒤 = 본문 일러스트
        if idx == 0 and chart_svg:
            body.append(chart_svg)
        if idx == 1 and inline_img:
            body.append(
                f'<figure class="my-8">'
                f'<img src="{esc(inline_img)}" alt="{esc(inline_alt)}" '
                f'class="w-full rounded-2xl border border-slate-200" loading="lazy" width="1024" height="1024">'
                f'</figure>'
            )
        if idx == 1:
            body.append('<div class="ad-slot" data-slot-name="article-section" data-ad-format="auto"></div>')

    # 도표/일러스트가 섹션 수 부족으로 못 들어갔으면 마지막에 붙인다
    if chart_svg and not any(chart_svg in b for b in body):
        body.append(chart_svg)
    if inline_img and not any(str(inline_img) in b for b in body):
        body.append(
            f'<figure class="my-8">'
            f'<img src="{esc(inline_img)}" alt="{esc(inline_alt)}" '
            f'class="w-full rounded-2xl border border-slate-200" loading="lazy" width="1024" height="1024">'
            f'</figure>'
        )

    if checklist_svg:
        body.append(checklist_svg)

    checklist = article.get("checklist") or []
    if checklist:
        items = "".join(
            f'<li class="flex gap-3"><span class="text-brand-600 font-bold shrink-0">✓</span>'
            f'<span class="text-slate-700">{esc(c)}</span></li>'
            for c in checklist
        )
        body.append(
            '<section class="mb-10 bg-white rounded-2xl border border-slate-200 p-6 shadow-soft">'
            '<h2 class="text-lg font-bold mb-4 text-slate-900">마케터 체크리스트</h2>'
            f'<ul class="space-y-3 text-[15px] leading-relaxed">{items}</ul>'
            '</section>'
        )

    # FAQ — 본문에도 노출해야 스키마와 내용이 일치한다.
    if faqs:
        qa = "".join(
            '<details class="faq bg-white p-5 rounded-2xl border border-slate-200 shadow-soft">'
            f'<summary><span class="font-semibold text-slate-900">{esc(f["q"])}</span></summary>'
            f'<p class="mt-3 text-sm text-slate-700 leading-relaxed">{esc(f["a"])}</p>'
            '</details>'
            for f in faqs
        )
        body.append(
            '<section class="mb-10">'
            '<h2 class="text-2xl font-bold mb-4 tracking-tight text-slate-900">자주 묻는 질문</h2>'
            f'<div class="space-y-3">{qa}</div>'
            '</section>'
        )

    # 출처
    sources = meta.get("sources") or []
    if sources:
        rows = "".join(
            f'<li><a href="{esc(s["link"])}" target="_blank" rel="noopener nofollow" '
            f'class="text-brand-600 hover:underline">{esc(s["title"])}</a>'
            f'<span class="text-slate-500"> — {esc(s["source"])}'
            + (f', {esc(s["date"])}' if s.get("date") else "") + '</span></li>'
            for s in sources
        )
        body.append(
            '<section class="mb-10">'
            '<h2 class="text-lg font-bold mb-3 text-slate-900">출처</h2>'
            f'<ol class="list-decimal pl-5 space-y-2 text-sm leading-relaxed">{rows}</ol>'
            '<p class="text-xs text-slate-500 mt-4">원문 기사의 저작권은 각 언론사에 있습니다. '
            '본 글은 사실관계를 요약·해설한 것이며 원문을 대체하지 않습니다.</p>'
            '</section>'
        )

    tags = article.get("tags") or []
    tag_html = ""
    if tags:
        chips = "".join(
            f'<span class="inline-block bg-slate-100 text-slate-600 text-xs font-medium '
            f'px-3 py-1 rounded-full mr-2 mb-2">#{esc(t)}</span>'
            for t in tags[:6]
        )
        tag_html = f'<div class="mt-8">{chips}</div>'

    dt = datetime.strptime(date_str, "%Y-%m-%d")

    return f"""<!DOCTYPE html>
<html lang="ko">
{head}
<body class="bg-slate-50 text-slate-900 antialiased">

{STATIC_HEADER}

<main class="max-w-3xl mx-auto px-4 py-10">

    <nav class="text-xs text-slate-500 mb-4" aria-label="Breadcrumb">
        <ol class="flex flex-wrap items-center gap-1.5">
            <li><a href="/" class="hover:text-brand-600">홈</a></li>
            <li class="text-slate-400">›</li>
            <li><a href="/news" class="hover:text-brand-600">의료광고 인사이트</a></li>
        </ol>
    </nav>

    <h1 class="text-3xl md:text-4xl font-bold mb-4 tracking-tight leading-tight">{esc(article.get('title', ''))}</h1>

    <div class="flex flex-wrap items-center gap-3 text-sm text-slate-500 mb-8 pb-6 border-b border-slate-200">
        <time datetime="{esc(date_str)}">{dt:%Y년 %-m월 %-d일}</time>
        <span class="text-slate-300">·</span>
        <span>admedical 편집팀</span>
    </div>

{"".join(body)}
{tag_html}
{AI_DISCLOSURE}

    <aside class="mt-10 bg-white rounded-2xl border border-slate-200 p-6 shadow-soft">
        <h2 class="text-sm font-bold text-slate-700 mb-4">📎 함께 보면 좋은 자료</h2>
        <ul class="space-y-2.5 text-sm">
            <li><a href="/" class="text-brand-600 hover:underline font-medium">→ 심의 통과 문구 키워드 검색</a></li>
            <li><a href="/top20" class="text-brand-600 hover:underline font-medium">→ 심의통과 TOP 20 키워드</a></li>
            <li><a href="/guide/forbidden-expressions" class="text-brand-600 hover:underline font-medium">→ 의료광고 금지 표현과 대안</a></li>
            <li><a href="/guide/faq" class="text-brand-600 hover:underline font-medium">→ 의료광고 FAQ 30선</a></li>
            <li><a href="/news" class="text-brand-600 hover:underline font-medium">→ 지난 인사이트 전체 보기</a></li>
        </ul>
    </aside>
</main>

{FOOTER}"""


# ---------- 목록 ----------

def render_list(posts: list[dict]) -> str:
    canonical = f"{BASE_URL}/news"
    head = _head(
        title="의료광고 인사이트 — 병의원 마케팅 뉴스 | admedical",
        description="병의원 마케터를 위한 의료광고 규제·정책·시장 동향 브리핑. 심의 통과 시안 데이터와 함께 매일 업데이트됩니다.",
        canonical=canonical,
        og_image=f"{BASE_URL}/assets/img/ogimage.png",
        og_type="website",
    )

    if not posts:
        cards = ('<p class="text-slate-500 text-sm bg-white rounded-2xl border border-slate-200 '
                 'p-8 text-center">첫 번째 글을 준비하고 있습니다.</p>')
    else:
        cards = "".join(_card(p, featured=(i == 0)) for i, p in enumerate(posts))

    return f"""<!DOCTYPE html>
<html lang="ko">
{head}
<body class="bg-slate-50 text-slate-900 antialiased">

{STATIC_HEADER}

<main class="max-w-5xl mx-auto px-4 py-10">

    <nav class="text-xs text-slate-500 mb-4" aria-label="Breadcrumb">
        <ol class="flex flex-wrap items-center gap-1.5">
            <li><a href="/" class="hover:text-brand-600">홈</a></li>
            <li class="text-slate-400">›</li>
            <li><span class="text-slate-700 font-semibold">의료광고 인사이트</span></li>
        </ol>
    </nav>

    <h1 class="text-3xl md:text-4xl font-bold mb-3 tracking-tight">의료광고 인사이트</h1>
    <p class="text-slate-600 mb-8 leading-relaxed">
        병의원 마케터가 알아야 할 규제·정책·시장 변화를 매일 정리합니다.
        심의 통과 시안 데이터와 함께 읽으면 실무 판단이 빨라집니다.
    </p>

    <div class="ad-slot" data-slot-name="article-section" data-ad-format="auto"></div>

    <div class="grid gap-5 md:grid-cols-2">
{cards}
    </div>
</main>

{FOOTER}"""


def _card(post: dict, featured: bool = False) -> str:
    dt = datetime.strptime(post["date"], "%Y-%m-%d")
    span = ' md:col-span-2' if featured else ''
    cover = post.get("cover")

    thumb = ""
    if cover:
        h = "h-56" if featured else "h-40"
        thumb = (f'<img src="{esc(cover)}" alt="{esc(post["title"])}" loading="lazy" '
                 f'class="w-full {h} object-cover rounded-xl mb-4 border border-slate-200">')

    tags = "".join(
        f'<span class="inline-block bg-slate-100 text-slate-500 text-[11px] font-medium '
        f'px-2 py-0.5 rounded-full mr-1.5">#{esc(t)}</span>'
        for t in (post.get("tags") or [])[:3]
    )

    return f"""        <article class="bg-white rounded-2xl border border-slate-200 p-5 shadow-soft hover:border-brand-500 transition{span}">
            <a href="/news/{esc(post['slug'])}" class="block">
                {thumb}
                <time class="text-xs text-slate-400" datetime="{esc(post['date'])}">{dt:%Y.%m.%d}</time>
                <h2 class="text-lg font-bold text-slate-900 mt-1.5 mb-2 leading-snug">{esc(post['title'])}</h2>
                <p class="text-sm text-slate-600 leading-relaxed line-clamp-3">{esc(post.get('summary', ''))}</p>
            </a>
            <div class="mt-3">{tags}</div>
        </article>
"""


# ---------- 인덱스 / 사이트맵 ----------

def load_index() -> list[dict]:
    if not INDEX_JSON.exists():
        return []
    try:
        data = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
        return data.get("posts", []) if isinstance(data, dict) else data
    except json.JSONDecodeError:
        return []


def save_index(posts: list[dict]) -> None:
    INDEX_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(KST).isoformat(),
        "count": len(posts),
        "posts": posts,
    }
    INDEX_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def update_sitemap(posts: list[dict]) -> None:
    """사이트맵의 news 블록만 통째로 교체. 기존 정적 URL은 건드리지 않는다."""
    if not SITEMAP.exists():
        return

    text = SITEMAP.read_text(encoding="utf-8")

    latest = posts[0]["date"] if posts else f"{datetime.now(KST):%Y-%m-%d}"

    entries = [f"""
    <url>
        <loc>{BASE_URL}/news</loc>
        <lastmod>{latest}</lastmod>
        <changefreq>daily</changefreq>
        <priority>0.9</priority>
    </url>"""]

    for p in posts[:500]:
        entries.append(f"""
    <url>
        <loc>{BASE_URL}/news/{p['slug']}</loc>
        <lastmod>{p['date']}</lastmod>
        <changefreq>monthly</changefreq>
        <priority>0.7</priority>
    </url>""")

    block = SITEMAP_BEGIN + "".join(entries) + "\n" + SITEMAP_END

    if SITEMAP_BEGIN in text and SITEMAP_END in text:
        text = re.sub(
            re.escape(SITEMAP_BEGIN) + r".*?" + re.escape(SITEMAP_END),
            lambda _: block,
            text,
            flags=re.S,
        )
    else:
        text = text.replace("</urlset>", block + "\n\n</urlset>")

    SITEMAP.write_text(text, encoding="utf-8")


def write_post_files(posts: list[dict]) -> None:
    """목록 페이지 + 사이트맵 + 인덱스 JSON 재생성."""
    NEWS_DIR.mkdir(parents=True, exist_ok=True)
    (NEWS_DIR / "index.html").write_text(render_list(posts), encoding="utf-8")
    save_index(posts)
    update_sitemap(posts)
