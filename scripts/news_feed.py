"""
RSS 2.0 피드 생성 — 네이버 서치어드바이저 / 구글 서치콘솔 제출용.

네이버 서치어드바이저는 사이트맵과 별개로 RSS 제출을 지원하며, RSS 쪽이
신규 문서 수집이 빠르다. 구글도 사이트맵 대신 RSS/Atom 피드 제출을 허용한다.

출력: website/rss.xml   (https://www.admedical.co.kr/rss.xml)

네이버 요구사항에 맞춘 부분:
  · RSS 2.0 규격, 채널에 title/link/description/language 필수
  · item 마다 title/link/description/pubDate 포함
  · pubDate 는 RFC822 형식
  · 최신 글이 위로 오도록 정렬, 최대 100건
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent.parent
WEB = ROOT / "website"
RSS_PATH = WEB / "rss.xml"

BASE_URL = "https://www.admedical.co.kr"
MAX_ITEMS = 100

CHANNEL_TITLE = "admedical 의료광고 인사이트"
CHANNEL_DESC = (
    "병의원 마케터를 위한 의료광고 규제·정책·시장 동향 브리핑. "
    "대한의사협회 의료광고심의위원회 통과 시안 데이터와 함께 매일 업데이트됩니다."
)


def _mime(path: str) -> str:
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg",
            "webp": "image/webp", "png": "image/png"}.get(ext, "image/jpeg")


def _rfc822(date_str: str) -> str:
    """'2026-08-01' → 'Sat, 01 Aug 2026 09:00:00 +0900'"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=9, tzinfo=KST)
    except ValueError:
        dt = datetime.now(KST)
    from email.utils import format_datetime
    return format_datetime(dt)


def build_rss(posts: list[dict]) -> str:
    now = datetime.now(KST)
    from email.utils import format_datetime

    items: list[str] = []
    for p in posts[:MAX_ITEMS]:
        url = f"{BASE_URL}/news/{p['slug']}"
        cover = p.get("cover")
        enclosure = ""
        if cover:
            enclosure = (
                f'\n            <enclosure url="{escape(BASE_URL + cover)}" '
                f'type="{_mime(cover)}" length="0"/>'
            )
        categories = "".join(
            f"\n            <category>{escape(t)}</category>"
            for t in (p.get("tags") or [])[:5]
        )
        items.append(f"""        <item>
            <title>{escape(p.get('title', ''))}</title>
            <link>{escape(url)}</link>
            <guid isPermaLink="true">{escape(url)}</guid>
            <description>{escape(p.get('summary', ''))}</description>
            <author>admedical</author>
            <pubDate>{_rfc822(p.get('date', ''))}</pubDate>{categories}{enclosure}
        </item>""")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
    <channel>
        <title>{escape(CHANNEL_TITLE)}</title>
        <link>{BASE_URL}/news</link>
        <description>{escape(CHANNEL_DESC)}</description>
        <language>ko</language>
        <generator>admedical news pipeline</generator>
        <lastBuildDate>{format_datetime(now)}</lastBuildDate>
        <pubDate>{format_datetime(now)}</pubDate>
        <ttl>60</ttl>
        <atom:link href="{BASE_URL}/rss.xml" rel="self" type="application/rss+xml"/>
        <image>
            <url>{BASE_URL}/assets/img/ogimage.png</url>
            <title>{escape(CHANNEL_TITLE)}</title>
            <link>{BASE_URL}/news</link>
        </image>
{chr(10).join(items)}
    </channel>
</rss>
"""


def write_rss(posts: list[dict]) -> Path:
    RSS_PATH.write_text(build_rss(posts), encoding="utf-8")
    return RSS_PATH


if __name__ == "__main__":
    import json
    idx = WEB / "assets" / "data" / "news-index.json"
    data = json.loads(idx.read_text(encoding="utf-8")) if idx.exists() else {"posts": []}
    path = write_rss(data.get("posts", []))
    print(f"RSS 생성: {path} ({len(data.get('posts', []))}건)")
