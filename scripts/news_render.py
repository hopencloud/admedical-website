"""
정적 HTML 렌더링 — 기사 상세 / 목록 / 사이트맵.

Supabase가 아니라 정적 파일을 원본으로 삼는다. 이유:
  · 검색엔진이 JS 실행 없이 본문을 그대로 읽는다 (SEO·애드센스 크롤러에 유리)
  · Vercel 정적 호스팅이라 추가 비용·지연이 없다
  · 글이 깨져도 git 이력으로 즉시 되돌릴 수 있다

검색 노출을 위해 기사 페이지에 넣는 것:
  · H1 1개 + H2 소제목(앵커 id) + 목차 → 스니펫·AI 답변 인용 대상
  · 핵심 요약 박스 → 문맥 없이 읽어도 완결된 문장 (AEO/GEO)
  · NewsArticle + BreadcrumbList + FAQPage + ImageObject + speakable 스키마
  · OG/Twitter 전체 필드, article:* 메타
  · 본문 키워드 → 가이드 페이지 자동 내부링크
"""
from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

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

# 본문에 이 표현이 처음 나오면 해당 가이드로 링크한다.
# 긴 표현이 먼저 와야 짧은 표현에 먹히지 않는다.
INTERNAL_LINKS: list[tuple[str, str]] = [
    ("의료광고 사전심의", "/guide/about-review"),
    ("의료광고심의위원회", "/guide/about-review"),
    ("의료광고 심의", "/guide/about-review"),
    ("심의 신청", "/guide/application"),
    ("심의 대상 매체", "/guide/target-media"),
    ("심의 면제", "/guide/exempt"),
    ("금지 표현", "/guide/forbidden-expressions"),
    ("심의번호", "/guide/review-number"),
    ("의료법 제56조", "/guide/forbidden-expressions"),
    ("의료법 제57조", "/guide/about-review"),
    ("비급여", "/guide/forbidden-expressions"),
]


def esc(text) -> str:
    return html.escape(str(text or ""), quote=True)


def slug_anchor(text: str, idx: int) -> str:
    base = re.sub(r"[^0-9a-zA-Z가-힣]+", "-", str(text)).strip("-").lower()
    return f"sec-{idx + 1}-{base[:24]}" if base else f"sec-{idx + 1}"


def autolink(text: str, used: set[str]) -> str:
    """이스케이프된 문단에 가이드 링크를 심는다. 표현당 문서 전체에서 1회만."""
    for phrase, url in INTERNAL_LINKS:
        if phrase in used or phrase not in text:
            continue
        text = text.replace(
            phrase,
            f'<a href="{url}" class="text-brand-600 hover:underline">{phrase}</a>',
            1,
        )
        used.add(phrase)
    return text


# ---------- 공통 head ----------

def _head(title: str, description: str, canonical: str, og_image: str,
          og_type: str = "article", extra_ld: str = "", extra_meta: str = "",
          image_alt: str = "") -> str:
    alt = esc(image_alt or title)
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
    <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1">
    <meta name="googlebot" content="index, follow, max-image-preview:large, max-snippet:-1">
    <meta name="naver:robots" content="all">
    <meta name="Yeti" content="index, follow">
    <link rel="canonical" href="{esc(canonical)}">
    <link rel="alternate" type="application/rss+xml" title="admedical 의료광고 인사이트" href="{BASE_URL}/rss.xml">

    <meta property="og:type" content="{og_type}">
    <meta property="og:site_name" content="admedical 의료광고 인사이트">
    <meta property="og:title" content="{esc(title)}">
    <meta property="og:description" content="{esc(description)}">
    <meta property="og:url" content="{esc(canonical)}">
    <meta property="og:image" content="{esc(og_image)}">
    <meta property="og:image:secure_url" content="{esc(og_image)}">
    <meta property="og:image:width" content="1200">
    <meta property="og:image:height" content="630">
    <meta property="og:image:alt" content="{alt}">
    <meta property="og:locale" content="ko_KR">

    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{esc(title)}">
    <meta name="twitter:description" content="{esc(description)}">
    <meta name="twitter:image" content="{esc(og_image)}">
    <meta name="twitter:image:alt" content="{alt}">
{extra_meta}
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
<script src="/assets/js/newsletter.js?v={ASSET_VER}" defer></script>
</body>
</html>
"""

# 일러스트마다 붙는 짧은 고지. 독자가 실제 사진으로 오해하지 않도록.
AI_IMAGE_NOTE = "이해를 돕기 위해 AI로 제작한 일러스트입니다."


def _img_caption(alt: str, kind: str = "일러스트") -> str:
    note = f"이해를 돕기 위해 AI로 제작한 {kind}입니다."
    return (f'<figcaption class="text-xs text-slate-500 mt-3 leading-relaxed">'
            f'{esc(alt)}<span class="text-slate-400"> · {note}</span></figcaption>')


SUBSCRIBE_FORM = """
    <section class="my-10 bg-brand-50 border border-brand-100 rounded-2xl p-6">
        <h2 class="text-lg font-bold text-slate-900 mb-1.5">의료광고 인사이트 뉴스레터</h2>
        <p class="text-sm text-slate-600 leading-relaxed mb-4">
            병의원 마케터가 알아야 할 규제·정책 변화를 매일 아침 메일로 보내드립니다.
            이메일 주소만 남기시면 됩니다. 언제든 메일 하단 링크로 수신을 해지하실 수 있습니다.
        </p>
        <form class="newsletter-form flex flex-col sm:flex-row gap-2" novalidate>
            <label class="sr-only" for="nl-email-{uid}">이메일 주소</label>
            <input id="nl-email-{uid}" type="email" name="email" required
                   autocomplete="email" placeholder="name@example.com"
                   class="flex-1 px-4 py-3 rounded-xl border border-slate-300 bg-white
                          focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-brand-500">
            <input type="text" name="website" tabindex="-1" autocomplete="off"
                   class="hidden" aria-hidden="true">
            <button type="submit"
                    class="px-6 py-3 rounded-xl bg-brand-600 text-white font-semibold
                           hover:bg-brand-700 transition disabled:bg-slate-300">
                구독하기
            </button>
        </form>
        <p class="newsletter-msg hidden mt-3 text-sm"></p>
        <p class="text-xs text-slate-500 mt-3">
            입력하신 이메일은 뉴스레터 발송 목적으로만 사용하며,
            <a href="/privacy" class="text-brand-600 hover:underline">개인정보처리방침</a>에 따라 관리됩니다.
        </p>
    </section>
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

def render_post(article: dict, meta: dict, infographic_svg: str = "",
                extra_svg: str = "") -> str:
    """meta: {slug, date, cover, inline_image, thumb, sources:[...]}"""
    slug = meta["slug"]
    date_str = meta["date"]
    canonical = f"{BASE_URL}/news/{slug}"

    cover = meta.get("cover") or ""
    thumb = meta.get("thumb") or cover
    og_image = f"{BASE_URL}{thumb}" if thumb else f"{BASE_URL}/assets/img/ogimage.png"

    title = article.get("title", "")
    seo_title = article.get("seo_title") or f"{title} | admedical 의료광고 인사이트"
    summary = article.get("summary", "")
    keywords = [k for k in (article.get("keywords") or []) if k][:10]
    tags = [t for t in (article.get("tags") or []) if t][:6]
    key_points = [p for p in (article.get("key_points") or []) if p][:4]
    faqs = [f for f in (article.get("faq") or []) if f.get("q") and f.get("a")][:5]
    sections = article.get("sections") or []

    imgs = article.get("images") or []

    def _by_role(*roles):
        return next((i for i in imgs if i.get("role") in roles), {})

    cover_meta = _by_role("photo", "cover")
    inline_meta = _by_role("illustration", "inline")
    cover_alt = cover_meta.get("alt") or f"{title} 관련 사진"
    inline_alt = inline_meta.get("alt") or f"{title} 관련 설명 일러스트"

    body_text = " ".join(
        [article.get("lead", "")] +
        [p for s in sections for p in s.get("paragraphs", [])]
    )

    # ----- 스키마 -----
    ld_article = json.dumps({
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": title[:110],
        "alternativeHeadline": seo_title[:110],
        "description": summary,
        "image": {
            "@type": "ImageObject",
            "url": og_image,
            "width": 1200,
            "height": 630,
            "caption": cover_alt,
        },
        "datePublished": f"{date_str}T04:30:00+09:00",
        "dateModified": f"{date_str}T04:30:00+09:00",
        "inLanguage": "ko",
        "isAccessibleForFree": True,
        "articleSection": "의료광고",
        "keywords": ", ".join(keywords or tags),
        "wordCount": len(re.sub(r"\s", "", body_text)),
        "author": {"@type": "Organization", "name": "admedical", "url": f"{BASE_URL}/about"},
        "publisher": {
            "@type": "Organization",
            "name": "admedical",
            "url": BASE_URL,
            "logo": {"@type": "ImageObject", "url": f"{BASE_URL}/assets/img/ogimage.png"},
        },
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
        # 음성 검색·AI 답변이 읽어갈 부분을 지정한다 (AEO)
        "speakable": {
            "@type": "SpeakableSpecification",
            "cssSelector": [".article-summary", "h1"],
        },
    }, ensure_ascii=False, indent=4)

    ld_crumb = json.dumps({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "홈", "item": f"{BASE_URL}/"},
            {"@type": "ListItem", "position": 2, "name": "의료광고 인사이트", "item": f"{BASE_URL}/news"},
            {"@type": "ListItem", "position": 3, "name": title, "item": canonical},
        ],
    }, ensure_ascii=False, indent=4)

    extra_ld = (f'    <script type="application/ld+json">\n{ld_article}\n    </script>\n'
                f'    <script type="application/ld+json">\n{ld_crumb}\n    </script>\n')

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

    extra_meta = (
        f'    <meta name="keywords" content="{esc(", ".join(keywords or tags))}">\n'
        f'    <meta property="article:published_time" content="{date_str}T04:30:00+09:00">\n'
        f'    <meta property="article:modified_time" content="{date_str}T04:30:00+09:00">\n'
        f'    <meta property="article:author" content="admedical">\n'
        f'    <meta property="article:section" content="의료광고">\n'
        + "".join(f'    <meta property="article:tag" content="{esc(t)}">\n' for t in tags)
    )

    head = _head(seo_title, summary, canonical, og_image,
                 extra_ld=extra_ld, extra_meta=extra_meta, image_alt=cover_alt)

    # ----- 본문 -----
    body: list[str] = []
    used_links: set[str] = set()

    def para(text: str, cls: str) -> str:
        return f'<p class="{cls}">{autolink(esc(text), used_links)}</p>'

    if cover:
        body.append(
            f'<figure class="mb-8 -mx-4 sm:mx-0">'
            f'<img src="{esc(cover)}" alt="{esc(cover_alt)}" '
            f'class="w-full sm:rounded-2xl border border-slate-200" '
            f'loading="eager" fetchpriority="high" width="1400" height="933">'
            f'{_img_caption(cover_alt, "이미지")}'
            f'</figure>'
        )

    if article.get("lead"):
        body.append(para(
            article["lead"],
            "text-base md:text-lg text-slate-700 leading-relaxed mb-8 "
            "bg-brand-50 border-l-4 border-brand-500 px-4 py-3 rounded-r-lg"))

    # 핵심 요약 — AI 검색·스니펫이 그대로 인용하는 자리
    if key_points:
        items = "".join(
            f'<li class="flex gap-2.5"><span class="text-brand-600 font-bold shrink-0">·</span>'
            f'<span>{autolink(esc(p), used_links)}</span></li>'
            for p in key_points
        )
        body.append(
            '<section class="article-summary mb-8 bg-white rounded-2xl border border-slate-200 p-5 shadow-soft">'
            '<h2 class="text-sm font-bold text-slate-700 mb-3">3줄 요약</h2>'
            f'<ul class="space-y-2 text-[15px] text-slate-800 leading-relaxed">{items}</ul>'
            '</section>'
        )

    # 목차 — 앵커 링크. 구글 사이트링크 스니펫 대상.
    anchors = [(slug_anchor(s.get("heading", ""), i), s.get("heading", ""))
               for i, s in enumerate(sections) if s.get("heading")]
    if len(anchors) >= 3:
        links = "".join(
            f'<li><a href="#{a}" class="text-brand-600 hover:underline">{esc(h)}</a></li>'
            for a, h in anchors
        )
        body.append(
            '<nav class="mb-8 bg-slate-100 rounded-2xl px-5 py-4" aria-label="목차">'
            '<h2 class="text-sm font-bold text-slate-700 mb-2">이 글의 순서</h2>'
            f'<ol class="list-decimal pl-5 space-y-1 text-sm">{links}</ol>'
            '</nav>'
        )

    body.append('<div class="ad-slot" data-slot-name="article-section" data-ad-format="auto"></div>')

    inline_img = meta.get("inline_image")
    for idx, sec in enumerate(sections):
        anchor = slug_anchor(sec.get("heading", ""), idx)
        body.append(f'<section id="{anchor}" class="mb-10 scroll-mt-24">')
        if sec.get("heading"):
            body.append(
                f'<h2 class="text-2xl font-bold mb-4 tracking-tight text-slate-900">'
                f'{esc(sec["heading"])}</h2>')
        for p in sec.get("paragraphs", []):
            body.append(para(p, "text-[15px] md:text-base text-slate-700 leading-[1.9] mb-4"))
        body.append('</section>')

        if idx == 0 and infographic_svg:
            body.append(infographic_svg)
        if idx == 1 and inline_img:
            body.append(
                f'<figure class="my-8">'
                f'<img src="{esc(inline_img)}" alt="{esc(inline_alt)}" '
                f'class="w-full rounded-2xl border border-slate-200" loading="lazy" '
                f'width="1024" height="1024">'
                f'{_img_caption(inline_alt)}'
                f'</figure>'
            )
            body.append('<div class="ad-slot" data-slot-name="article-section" data-ad-format="auto"></div>')

    if infographic_svg and infographic_svg not in body:
        body.append(infographic_svg)
    if inline_img and not any(str(inline_img) in b for b in body):
        body.append(
            f'<figure class="my-8"><img src="{esc(inline_img)}" alt="{esc(inline_alt)}" '
            f'class="w-full rounded-2xl border border-slate-200" loading="lazy" '
            f'width="1024" height="1024">{_img_caption(inline_alt)}</figure>')
    if extra_svg:
        body.append(extra_svg)

    checklist = article.get("checklist") or []
    if checklist:
        items = "".join(
            f'<li class="flex gap-3"><span class="text-brand-600 font-bold shrink-0">✓</span>'
            f'<span class="text-slate-700">{autolink(esc(c), used_links)}</span></li>'
            for c in checklist
        )
        body.append(
            '<section class="mb-10 bg-white rounded-2xl border border-slate-200 p-6 shadow-soft">'
            '<h2 class="text-lg font-bold mb-4 text-slate-900">마케터 체크리스트</h2>'
            f'<ul class="space-y-3 text-[15px] leading-relaxed">{items}</ul>'
            '</section>'
        )

    if faqs:
        qa = "".join(
            '<details class="faq bg-white p-5 rounded-2xl border border-slate-200 shadow-soft">'
            f'<summary><h3 class="font-semibold text-slate-900 inline">{esc(f["q"])}</h3></summary>'
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

    tag_html = ""
    if tags:
        chips = "".join(
            f'<span class="inline-block bg-slate-100 text-slate-600 text-xs font-medium '
            f'px-3 py-1 rounded-full mr-2 mb-2">#{esc(t)}</span>'
            for t in tags
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

    <article>
    <h1 class="text-3xl md:text-4xl font-bold mb-4 tracking-tight leading-tight">{esc(title)}</h1>

    <div class="flex flex-wrap items-center gap-3 text-sm text-slate-500 mb-8 pb-6 border-b border-slate-200">
        <time datetime="{esc(date_str)}">{dt:%Y년 %-m월 %-d일}</time>
        <span class="text-slate-300">·</span>
        <span>admedical 편집팀</span>
    </div>

{"".join(body)}
{tag_html}
    </article>

{SUBSCRIBE_FORM.replace("{uid}", "post")}
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

    ld_list = json.dumps({
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": "의료광고 인사이트",
        "description": "병의원 마케터를 위한 의료광고 규제·정책·시장 동향 브리핑",
        "url": canonical,
        "inLanguage": "ko",
        "mainEntity": {
            "@type": "ItemList",
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1,
                 "url": f"{BASE_URL}/news/{p['slug']}", "name": p["title"]}
                for i, p in enumerate(posts[:30])
            ],
        },
    }, ensure_ascii=False, indent=4)

    head = _head(
        title="의료광고 인사이트 — 병의원 마케팅 뉴스 | admedical",
        description="병의원 마케터를 위한 의료광고 규제·정책·시장 동향 브리핑. 심의 통과 시안 데이터와 함께 매일 업데이트됩니다.",
        canonical=canonical,
        og_image=f"{BASE_URL}/assets/img/ogimage.png",
        og_type="website",
        extra_ld=f'    <script type="application/ld+json">\n{ld_list}\n    </script>\n',
    )

    if not posts:
        rows = ('<div class="p-8 text-center">'
                '<h2 class="text-base font-bold text-slate-700 mb-2">준비 중입니다</h2>'
                '<p class="text-slate-500 text-sm">첫 번째 글을 작성하고 있습니다. 곧 올라옵니다.</p>'
                '</div>')
    else:
        rows = "".join(_row(p) for p in posts)

    return f"""<!DOCTYPE html>
<html lang="ko">
{head}
<body class="bg-slate-50 text-slate-900 antialiased">

{STATIC_HEADER}

<main class="max-w-4xl mx-auto px-4 py-10">

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

    <div class="divide-y divide-slate-200 bg-white rounded-2xl border border-slate-200 shadow-soft overflow-hidden">
{rows}
    </div>

{SUBSCRIBE_FORM.replace("{uid}", "list")}
</main>

{FOOTER}"""


def _row(post: dict) -> str:
    """게시판형 목록 한 줄 — 좌측 썸네일, 우측 제목·요약. 모든 글이 같은 크기."""
    dt = datetime.strptime(post["date"], "%Y-%m-%d")
    thumb = post.get("thumb") or post.get("cover")

    thumb_html = (
        f'<img src="{esc(thumb)}" alt="{esc(post["title"])}" loading="lazy" '
        f'width="1200" height="630" '
        f'class="w-28 h-20 sm:w-40 sm:h-[90px] object-cover rounded-lg border border-slate-200 shrink-0">'
        if thumb else
        '<div class="w-28 h-20 sm:w-40 sm:h-[90px] rounded-lg bg-slate-100 shrink-0"></div>'
    )

    tags = "".join(
        f'<span class="inline-block bg-slate-100 text-slate-500 text-[11px] font-medium '
        f'px-2 py-0.5 rounded-full mr-1.5">#{esc(t)}</span>'
        for t in (post.get("tags") or [])[:3]
    )

    return f"""        <article>
            <a href="/news/{esc(post['slug'])}" class="flex gap-4 p-4 sm:p-5 hover:bg-slate-50 transition">
                {thumb_html}
                <div class="min-w-0 flex-1">
                    <time class="text-xs text-slate-400" datetime="{esc(post['date'])}">{dt:%Y.%m.%d}</time>
                    <h2 class="text-base sm:text-lg font-bold text-slate-900 mt-0.5 mb-1 leading-snug line-clamp-2">{esc(post['title'])}</h2>
                    <p class="text-sm text-slate-600 leading-relaxed line-clamp-2">{esc(post.get('summary', ''))}</p>
                    <div class="mt-2 hidden sm:block">{tags}</div>
                </div>
            </a>
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
        img = ""
        thumb = p.get("thumb") or p.get("cover")
        if thumb:
            img = (f"""
        <image:image>
            <image:loc>{BASE_URL}{thumb}</image:loc>
            <image:title>{html.escape(p['title'])}</image:title>
        </image:image>""")
        entries.append(f"""
    <url>
        <loc>{BASE_URL}/news/{p['slug']}</loc>
        <lastmod>{p['date']}</lastmod>
        <changefreq>monthly</changefreq>
        <priority>0.7</priority>{img}
    </url>""")

    block = SITEMAP_BEGIN + "".join(entries) + "\n" + SITEMAP_END

    if SITEMAP_BEGIN in text and SITEMAP_END in text:
        text = re.sub(
            re.escape(SITEMAP_BEGIN) + r".*?" + re.escape(SITEMAP_END),
            lambda _: block, text, flags=re.S)
    else:
        text = text.replace("</urlset>", block + "\n\n</urlset>")

    # 이미지 사이트맵 네임스페이스 보강
    if "xmlns:image" not in text:
        text = text.replace(
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
            '        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">')

    SITEMAP.write_text(text, encoding="utf-8")


def write_post_files(posts: list[dict]) -> None:
    NEWS_DIR.mkdir(parents=True, exist_ok=True)
    (NEWS_DIR / "index.html").write_text(render_list(posts), encoding="utf-8")
    save_index(posts)
    update_sitemap(posts)
