"""
사이트 불변조건 검사 — 배포 전/후 자동 점검.

왜 있는가:
    실제로 새어나간 버그들이다. 전부 사람이 눈으로 봐야만 발견되던 것들이라
    검사 항목으로 고정한다.

      · 사이트맵의 .html 확장자가 되살아나 12개 URL 이 308 리다이렉트를 탐
        (네이버는 리디렉션 URL 을 수집 실패 처리한다)
      · 아직 게시 전인 날을 '0건'으로 표시해 심의가 0건이었던 것처럼 보임
      · 헤더가 JS 주입이라 크롤러에게 내부 링크가 안 보임
      · 이미지 alt 누락

사용:
    python scripts/validate_site.py            # 로컬 파일 검사 (커밋 전)
    python scripts/validate_site.py --live     # 배포된 사이트까지 검사
    python scripts/validate_site.py --live-only

실패하면 종료 코드 1. CI 가 이걸 보고 막는다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent.parent
WEB = ROOT / "website"
BASE_URL = "https://www.admedical.co.kr"

# 검색엔진 소유확인용 파일 — 규칙 적용 대상이 아니다
SKIP_NAMES = {
    "naver48bf0a622da5771affd07f27cfa1ad53.html",
    "naver536ba2b5323508822dfc8329784571b2.html",
}
SKIP_DIRS = {"admin"}          # 관리자 페이지는 noindex 영역

failures: list[str] = []
warnings: list[str] = []


def fail(check: str, detail: str) -> None:
    failures.append(f"{check}: {detail}")


def warn(check: str, detail: str) -> None:
    warnings.append(f"{check}: {detail}")


def public_pages() -> list[Path]:
    return [p for p in sorted(WEB.rglob("*.html"))
            if p.name not in SKIP_NAMES and not SKIP_DIRS & set(p.parts)]


def rel(p: Path) -> str:
    return str(p.relative_to(WEB))


# ==========================================================
# 로컬 파일 검사
# ==========================================================

def check_internal_links() -> None:
    """내부 링크에 .html 이 남으면 cleanUrls 때문에 전부 308 리다이렉트를 탄다."""
    for p in public_pages():
        text = p.read_text(encoding="utf-8")
        bad = re.findall(r'href="(/[^"]*?\.html[^"]*)"', text)
        if bad:
            fail("내부링크 확장자", f"{rel(p)} → {bad[:3]}")

    js = (WEB / "assets" / "js" / "site.js").read_text(encoding="utf-8")
    bad = re.findall(r'href="(/[^"]*?\.html[^"]*)"', js)
    if bad:
        fail("내부링크 확장자", f"site.js → {bad[:3]}")


def check_static_header() -> None:
    """헤더가 JS 주입으로 남아 있으면 네이버 Yeti 가 내부 링크를 못 읽는다."""
    for p in public_pages():
        text = p.read_text(encoding="utf-8")
        if 'id="site-header"' in text:
            fail("헤더 정적화", f"{rel(p)} 에 JS 주입 슬롯이 남아 있음")
        elif "site-header:begin" not in text:
            fail("헤더 정적화", f"{rel(p)} 에 정적 헤더가 없음")


def check_images_alt() -> None:
    for p in public_pages():
        for tag in re.findall(r"<img\b[^>]*>", p.read_text(encoding="utf-8")):
            m = re.search(r'alt="([^"]*)"', tag)
            if not m:
                fail("이미지 alt", f"{rel(p)} → alt 속성 없음: {tag[:70]}")
            elif not m.group(1).strip():
                fail("이미지 alt", f"{rel(p)} → alt 가 비어 있음: {tag[:70]}")


def check_headings() -> None:
    """H1 은 정확히 1개, H2 는 최소 1개. 검색엔진이 문서 구조를 읽는 기준이다."""
    for p in public_pages():
        text = p.read_text(encoding="utf-8")
        h1 = len(re.findall(r"<h1\b", text))
        h2 = len(re.findall(r"<h2\b", text))
        if h1 != 1:
            fail("제목 구조", f"{rel(p)} → H1 이 {h1}개 (정확히 1개여야 함)")
        if h2 < 1:
            fail("제목 구조", f"{rel(p)} → H2 가 없음")


def check_title_tag() -> None:
    """<title> 은 문서에 정확히 1개.

    SVG 안에 툴팁용 <title> 을 넣었더니 네이버 SEO 진단이 '제목 태그 2개' 로
    잡았다. SVG 규격상으로는 문제없지만 검사기는 문서 전체를 센다.
    """
    for p in public_pages():
        n = len(re.findall(r"<title[\s>]", p.read_text(encoding="utf-8")))
        if n != 1:
            fail("제목 태그", f"{rel(p)} → <title> 이 {n}개 (정확히 1개여야 함)")


def check_description_length() -> None:
    """네이버는 페이지 설명을 80자 이내로 권장한다. 넘으면 잘려 나온다."""
    for p in public_pages():
        m = re.search(r'<meta name="description" content="([^"]*)"',
                      p.read_text(encoding="utf-8"))
        if m and len(m.group(1)) > 80:
            warn("페이지 설명", f"{rel(p)} → {len(m.group(1))}자 (권장 80자 이내)")


def check_social_meta() -> None:
    """OG/트위터 카드 필수 필드. 공유·네이버 미리보기에 직접 쓰인다."""
    required = [
        ('property="og:title"', "og:title"),
        ('property="og:description"', "og:description"),
        ('property="og:image"', "og:image"),
        ('property="og:image:alt"', "og:image:alt"),
        ('property="og:url"', "og:url"),
        ('property="og:locale"', "og:locale"),
        ('name="twitter:card"', "twitter:card"),
        ('name="twitter:image"', "twitter:image"),
        ('name="description"', "meta description"),
    ]
    for p in public_pages():
        text = p.read_text(encoding="utf-8")
        missing = [label for needle, label in required if needle not in text]
        if missing:
            fail("소셜/메타", f"{rel(p)} → 누락: {', '.join(missing)}")


def check_interactive_assets() -> None:
    """폼만 있고 동작 스크립트가 없으면 눌러도 아무 일도 안 일어난다.

    실제로 /contact 에 구독 폼을 넣으면서 newsletter.js 를 빠뜨려
    사용자가 구독 신청을 눌러도 등록되지 않는 상태로 배포됐다.
    """
    pairs = [
        ("newsletter-form", "/assets/js/newsletter.js", "뉴스레터 구독 폼"),
        ("ad-slot", "/assets/js/ads.js", "광고 슬롯"),
    ]
    for p in public_pages():
        text = p.read_text(encoding="utf-8")
        for marker, script, label in pairs:
            if marker in text and script not in text:
                fail("스크립트 누락", f"{rel(p)} → {label}은 있는데 {script} 가 없음")

    for name in ("newsletter.js", "ads.js", "site.js"):
        if not (WEB / "assets" / "js" / name).exists():
            fail("스크립트 누락", f"assets/js/{name} 파일이 없음")


def check_canonical() -> None:
    for p in public_pages():
        text = p.read_text(encoding="utf-8")
        m = re.search(r'<link rel="canonical" href="([^"]+)"', text)
        if not m:
            fail("canonical", f"{rel(p)} 에 canonical 없음")
            continue
        if ".html" in m.group(1):
            fail("canonical", f"{rel(p)} → 확장자 포함: {m.group(1)}")
        if not m.group(1).startswith(BASE_URL):
            fail("canonical", f"{rel(p)} → 절대 URL 아님: {m.group(1)}")


def check_jsonld() -> None:
    for p in public_pages():
        blocks = re.findall(
            r'<script type="application/ld\+json">(.*?)</script>',
            p.read_text(encoding="utf-8"), flags=re.S)
        for i, block in enumerate(blocks):
            try:
                json.loads(block)
            except json.JSONDecodeError as e:
                fail("JSON-LD", f"{rel(p)} #{i + 1} 파싱 실패: {e}")


def check_sitemap() -> None:
    path = WEB / "sitemap.xml"
    if not path.exists():
        fail("사이트맵", "sitemap.xml 없음")
        return

    text = path.read_text(encoding="utf-8")
    try:
        ET.fromstring(text.encode())
    except ET.ParseError as e:
        fail("사이트맵", f"XML 파싱 실패: {e}")
        return

    locs = re.findall(r"<loc>(.*?)</loc>", text)
    bad = [u for u in locs if ".html" in u]
    if bad:
        fail("사이트맵", f"확장자 포함 URL {len(bad)}개 → {bad[:3]}")

    dupes = {u for u in locs if locs.count(u) > 1}
    if dupes:
        fail("사이트맵", f"중복 URL: {sorted(dupes)[:3]}")

    # 실제 파일이 있는 공개 페이지가 사이트맵에 빠지지 않았는지
    for p in public_pages():
        slug = rel(p).removesuffix(".html").removesuffix("/index")
        url = f"{BASE_URL}/" if slug in ("index", "") else f"{BASE_URL}/{slug}"
        if url not in locs:
            warn("사이트맵", f"{rel(p)} 누락 ({url})")


def check_rss() -> None:
    path = WEB / "rss.xml"
    if not path.exists():
        warn("RSS", "rss.xml 없음 (아직 글이 없으면 정상)")
        return
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8").encode())
    except ET.ParseError as e:
        fail("RSS", f"XML 파싱 실패: {e}")
        return
    for item in root.findall(".//item"):
        link = (item.findtext("link") or "")
        if ".html" in link:
            fail("RSS", f"확장자 포함 링크: {link}")
        if not item.findtext("title"):
            fail("RSS", "제목 없는 item 존재")


def check_news_index() -> None:
    path = WEB / "assets" / "data" / "news-index.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    posts = data.get("posts", [])

    for post in posts:
        html = WEB / "news" / f"{post['slug']}.html"
        if not html.exists():
            fail("뉴스 인덱스", f"{post['slug']} → HTML 파일 없음")
        for field in ("title", "summary", "date"):
            if not post.get(field):
                fail("뉴스 인덱스", f"{post['slug']} → {field} 비어 있음")
        cover = post.get("cover")
        if cover and not (WEB / cover.lstrip("/")).exists():
            fail("뉴스 인덱스", f"{post['slug']} → 표지 이미지 없음: {cover}")

    slugs = [p["slug"] for p in posts]
    if len(slugs) != len(set(slugs)):
        fail("뉴스 인덱스", "중복 slug 존재")

    # 썸네일 — 목록·메인·SNS 공유에 쓰인다
    for post in posts:
        thumb = post.get("thumb")
        if not thumb:
            fail("뉴스 썸네일", f"{post['slug']} → 썸네일 없음")
        elif not (WEB / thumb.lstrip("/")).exists():
            fail("뉴스 썸네일", f"{post['slug']} → 파일 없음: {thumb}")

    # 최신 글이 먼저 와야 한다 (같은 날 여러 편이면 발행 시각으로 비교)
    keys = [p.get("published_at") or f'{p["date"]}T00:00:00+09:00' for p in posts]
    if keys != sorted(keys, reverse=True):
        fail("뉴스 정렬", "최신 글이 맨 위가 아님 — news-index.json 정렬 확인 필요")


SKIP_FRESHNESS = False


def check_statistics() -> None:
    """아직 게시 전인 날을 0건으로 노출하면 '심의 0건'으로 잘못 읽힌다."""
    path = WEB / "assets" / "data" / "statistics.json"
    if not path.exists():
        fail("통계", "statistics.json 없음")
        return

    data = json.loads(path.read_text(encoding="utf-8"))
    y = data.get("yesterday") or {}

    if y.get("count", 0) <= 0:
        fail("통계", f"최근 집계일({y.get('date')})이 0건 — 집계 전 데이터가 그대로 노출됨")

    chart = data.get("chart_30d") or []
    if not any(r.get("count", 0) > 0 for r in chart):
        fail("통계", "30일 그래프에 실측값이 하나도 없음")

    # 데이터가 며칠째 안 들어오면 수집이 멈춘 것.
    #
    # 수집은 사장님 맥북에서만 돌아간다 (admedical.org 가 데이터센터 IP 를 차단해
    # 클라우드·VPN 경유가 전부 막힘 — probe-admedical / probe-nordvpn 참고).
    # 맥북이 꺼져 있거나 파이프라인이 실패하면 조용히 멈추므로 여기서 잡아 알린다.
    #
    # 의협은 심의 결과를 며칠 늦게 올린다. 금요일치가 마지막이면 월요일 아침에
    # 이미 3일 전이고, 게시가 하루이틀 더 밀리면 5일까지 간다.
    # 4일로 잡았더니 정상 상황에서도 경보가 울렸다. 6일로 둔다.
    try:
        last = max((r["date"] for r in chart if r.get("count", 0) > 0), default=None)
        if last:
            behind = (datetime.now(KST).date() - date.fromisoformat(last)).days
            if SKIP_FRESHNESS:
                if behind >= 3:
                    warn("통계", f"최신 데이터가 {behind}일 전({last})")
            elif behind >= 6:
                fail("통계", f"최신 데이터가 {behind}일 전({last}) — 수집이 멈춘 것으로 보입니다. "
                             f"맥북 전원과 daily_pipeline 로그를 확인하세요.")
            elif behind >= 3:
                warn("통계", f"최신 데이터가 {behind}일 전({last})")
    except Exception:
        pass


def check_adsense_and_robots() -> None:
    ads = WEB / "ads.txt"
    if not ads.exists() or "pub-" not in ads.read_text(encoding="utf-8"):
        fail("ads.txt", "게시자 ID 레코드가 없음")

    robots = WEB / "robots.txt"
    if not robots.exists():
        fail("robots.txt", "파일 없음")
    else:
        text = robots.read_text(encoding="utf-8")
        if "sitemap.xml" not in text.lower():
            fail("robots.txt", "Sitemap 라인 없음")

    missing = [rel(p) for p in public_pages()
               if "googlesyndication" not in p.read_text(encoding="utf-8")]
    if missing:
        fail("애드센스 스니펫", f"누락 {len(missing)}개 → {missing[:3]}")


# ==========================================================
# 라이브 검사
# ==========================================================

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _head(url: str) -> tuple[int, str]:
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "admedical-validator/1.0"})
    try:
        r = opener.open(req, timeout=20)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return 0, str(e)


def check_live() -> None:
    code, body = _head(f"{BASE_URL}/sitemap.xml")
    if code != 200:
        fail("라이브 사이트맵", f"HTTP {code}")
        return

    locs = re.findall(r"<loc>(.*?)</loc>", body)
    for url in locs:
        status, _ = _head(url)
        if status != 200:
            fail("라이브 URL", f"HTTP {status} (리다이렉트/오류) — {url}")

    for path in ("/rss.xml", "/robots.txt", "/ads.txt", "/llms.txt"):
        status, _ = _head(BASE_URL + path)
        if status != 200:
            fail("라이브 파일", f"HTTP {status} — {path}")

    # 네이버 회귀 방지: JS 없이 읽히는 본문·내부 링크가 충분한가
    status, home = _head(BASE_URL + "/")
    if status == 200:
        static = re.sub(r"<script.*?</script>", " ", home.split("<body")[1], flags=re.S)
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", static)).strip()
        links = set(re.findall(r'href="(/[^"#?]*)', static))
        if len(text) < 1000:
            fail("라이브 메인", f"JS 없이 읽히는 본문이 {len(text)}자 (1,000자 미만)")
        if len(links) < 10:
            fail("라이브 메인", f"정적 내부링크가 {len(links)}개 (10개 미만)")


# ==========================================================

def main() -> int:
    ap = argparse.ArgumentParser(description="사이트 불변조건 검사")
    ap.add_argument("--live", action="store_true", help="배포된 사이트까지 검사")
    ap.add_argument("--live-only", action="store_true", help="라이브만 검사")
    ap.add_argument("--skip-freshness", action="store_true",
                    help="통계 신선도 검사 제외 (뉴스 발행 전 검사용). "
                         "수집이 밀린 것과 기사 품질은 별개 문제다.")
    args = ap.parse_args()

    global SKIP_FRESHNESS
    SKIP_FRESHNESS = args.skip_freshness

    if not args.live_only:
        for fn in (check_internal_links, check_static_header, check_images_alt,
                   check_headings, check_title_tag, check_description_length,
                   check_social_meta, check_interactive_assets,
                   check_canonical, check_jsonld,
                   check_sitemap, check_rss, check_news_index, check_statistics,
                   check_adsense_and_robots):
            try:
                fn()
            except Exception as e:
                fail(fn.__name__, f"검사 자체가 실패: {type(e).__name__}: {e}")

    if args.live or args.live_only:
        try:
            check_live()
        except Exception as e:
            fail("check_live", f"검사 자체가 실패: {type(e).__name__}: {e}")

    for w in warnings:
        print(f"  [경고] {w}")

    if failures:
        print(f"\n실패 {len(failures)}건:")
        for f in failures:
            print(f"  ✗ {f}")
        return 1

    print(f"\n통과 — 문제 없음 (경고 {len(warnings)}건)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
