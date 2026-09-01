"""
뉴스 소스 수집 — 의료 전문지 RSS + 정부 보도자료 (+ OpenAI 웹검색 보강).

수집만 담당한다. 주제 선정·원고 작성은 news_writer.py.

저작권 원칙:
    RSS가 배포 목적으로 제공하는 제목/요약(description)만 사용한다.
    기사 본문을 크롤링하지 않는다. 원문 링크는 항상 출처로 표기한다.

실행 (단독 테스트):
    source venv/bin/activate
    python scripts/news_sources.py
"""
from __future__ import annotations

import html
import os
import re
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (compatible; admedical-newsbot/1.0; +https://www.admedical.co.kr/)"
TIMEOUT_SEC = 20

# 2026-08-01 기준 응답 확인된 피드만 등록.
# 피드가 죽어도 나머지로 계속 돌아가도록 개별 실패는 무시한다.
FEEDS: list[dict] = [
    {"name": "청년의사",      "url": "https://www.docdocdoc.co.kr/rss/allArticle.xml",  "kind": "press"},
    {"name": "의협신문",      "url": "https://www.doctorsnews.co.kr/rss/allArticle.xml", "kind": "press"},
    {"name": "히트뉴스",      "url": "https://www.hitnews.co.kr/rss/allArticle.xml",     "kind": "press"},
    {"name": "의학신문",      "url": "https://www.bosa.co.kr/rss/allArticle.xml",        "kind": "press"},
    {"name": "메디칼업저버",  "url": "https://www.monews.co.kr/rss/allArticle.xml",      "kind": "press"},
    {"name": "보건복지부 보도자료",
     "url": "https://www.mohw.go.kr/rss/board.es?mid=a10503010100&bid=0027",             "kind": "gov"},
]

# 병의원 마케터에게 의미 있는 기사만 남기기 위한 1차 키워드 필터.
# 여기서 넓게 거른 뒤 최종 선별은 AI가 한다.
RELEVANT_KEYWORDS = [
    # 광고·마케팅
    "광고", "마케팅", "홍보", "심의", "브랜딩", "홈페이지", "블로그", "유튜브", "인스타",
    "SNS", "검색", "네이버", "카카오", "플랫폼", "앱",
    # 규제·정책
    "의료법", "규제", "복지부", "보건복지부", "고시", "개정", "법령", "행정처분", "과징금",
    "벌금", "위반", "단속", "공정위", "지침", "가이드라인", "제도", "시범사업", "수가",
    "급여", "비급여", "실손", "보험",
    # 경영·시장
    "개원", "폐업", "병원", "의원", "클리닉", "환자", "진료", "비만", "피부", "성형",
    "치과", "한의", "안과", "정형", "내과", "산부인과", "소아", "검진", "비대면",
    "원격", "디지털", "AI", "인공지능", "데이터",
]

# 명백히 관련 없는 기사 제거 (인사·부고·학술 초청 등)
NOISE_PATTERNS = [
    r"부고", r"인사말", r"^\[인사\]", r"승진", r"취임", r"별세", r"장례",
    r"초청 ?강연", r"학술대회 개최", r"조직개편", r"채용공고",
    r"신간", r"포토", r"^\[포토", r"화보",
]

# 업체 보도자료 — 남의 회사 홍보를 우리 기사로 써주는 일을 막는다.
#
# 2026-08-19 에 "미소몰닷컴 리뉴얼, 병의원 마케팅에 미칠 잠재적 영향" 이 발행됐다.
# 근거로 쓴 두 건이 전부 GC메디아이의 플랫폼 리뉴얼 보도자료였다. 프롬프트의
# "홍보성 소식 제외" 지시는 병원만 걸렀고 업체·플랫폼은 그냥 통과했다.
# AI 에게 부탁하는 대신 파이썬이 제목에서 잘라낸다 (중복 차단 때와 같은 이유).
# 업체가 무언가를 내놓았다는 신호. 제도 기사에는 나올 일이 없다.
# 아래 POLICY_RESCUE 로도 구제되지 않는다.
#
# 2026-08-30 에 "의료광고 심의 자동화 서비스의 등장" 이 발행됐다. 근거가
# 경쟁 업체(MADMEDCHECK)의 자사 홈페이지 한 곳이었다. 제목에 "의료광고"와
# "심의"가 들어 있어 POLICY_RESCUE 가 통째로 살려버린 것이다. 이 사이트 주제상
# 업체 홍보에도 그 단어들이 반드시 들어가므로, 구제 조건을 나눠야 한다.
HARD_PROMO_PATTERNS = [
    r"출시", r"런칭", r"론칭", r"리뉴얼", r"재단장", r"새단장",
    r"그랜드 ?오픈", r"정식 ?오픈", r"선보(여|인|이|입)", r"등장", r"첫 ?공개",
    r"상용화", r"베타 ?(서비스|버전)", r"정식 ?서비스", r"신규 ?서비스", r"신제품",
    r"업무 ?협약", r"MOU", r"양해각서", r"맞손", r"손잡", r"파트너십",
    r"수상", r"[0-9]+년 ?연속", r"[0-9]+주년",
    r"매출", r"영업이익", r"실적", r"흑자", r"투자 ?유치", r"시리즈 ?[A-C]", r"상장",
]

# 약한 신호. 제도 기사에도 쓰일 수 있어 POLICY_RESCUE 로 구제된다.
PROMO_PATTERNS = [
    r"오픈", r"개원", r"확장 ?이전", r"제휴", r"기념",
    r"인증 ?획득", r"허가 ?획득", r"승인 ?획득", r"특허",
    r"기부", r"후원", r"봉사", r"나눔", r"전달식",
    r"심포지엄", r"세미나 ?개최", r"컨퍼런스 ?개최", r"간담회 ?개최",
]

# 위 단어가 들어 있어도 제도·규제 기사면 살린다.
# "심의 대상 매체 확대 시행", "의료법 개정안 공개" 같은 것들.
POLICY_RESCUE = [
    "의료법", "의료광고", "심의", "복지부", "보건복지부", "식약처", "공정위",
    "법 개정", "개정안", "입법", "고시", "행정처분", "과태료", "벌금", "판결",
    "가이드라인", "규제", "위반", "단속",
]


# 웹검색 결과로 받아들일 도메인.
#
# 2026-08-30 에 경쟁 업체(MADMEDCHECK)의 **자사 홈페이지**가 근거 자료로 들어와
# 그 업체를 홍보하는 기사가 발행됐다. 법률사무소·마케팅 대행사 블로그도 같이
# 섞여 들어왔다. 이런 곳은 기사가 아니라 영업 콘텐츠다.
#
# 화이트리스트로 간다. 새 매체를 넣을 때는 그게 정말 언론사인지 확인할 것.
CREDIBLE_DOMAINS = {
    # 의료 전문지
    "docdocdoc.co.kr", "doctorsnews.co.kr", "bosa.co.kr", "monews.co.kr",
    "hitnews.co.kr", "medicaltimes.com", "dailymedi.com", "medipana.com",
    "쿠키뉴스".encode().decode(), "kukinews.com", "yakup.com", "hkn24.com",
    "mdtoday.co.kr", "whosaeng.com", "medifonews.com", "dailypharm.com",
    # 종합지·통신사
    "yna.co.kr", "yonhapnews.co.kr", "chosun.com", "donga.com", "joongang.co.kr",
    "hani.co.kr", "khan.co.kr", "hankyung.com", "mk.co.kr", "sedaily.com",
    "kbs.co.kr", "imnews.imbc.com", "news.sbs.co.kr", "ytn.co.kr", "newsis.com",
    # 포털 뉴스 — 등록 언론사 기사만 실린다. 원문 매체명은 기사에 표기된다.
    "v.daum.net", "news.daum.net", "n.news.naver.com", "news.naver.com",
    # 정부·공공
    "mohw.go.kr", "mfds.go.kr", "law.go.kr", "korea.kr", "ftc.go.kr",
    "hira.or.kr", "nhis.or.kr", "kdca.go.kr",
}


def is_credible_source(link: str) -> bool:
    """언론사·정부 도메인인가. 업체 자사 사이트·블로그는 근거로 쓰지 않는다."""
    try:
        from urllib.parse import urlparse
        host = (urlparse(link).hostname or "").lower().lstrip("www.")
    except Exception:
        return False
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in CREDIBLE_DOMAINS)


@dataclass
class NewsItem:
    title: str
    link: str
    summary: str
    published: datetime
    source: str
    kind: str = "press"          # press | gov | web
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "link": self.link,
            "summary": self.summary,
            "published": self.published.isoformat(),
            "source": self.source,
            "kind": self.kind,
        }


# ---------- 유틸 ----------

def strip_html(raw: str) -> str:
    """RSS description 안의 태그·엔티티·CDATA 제거."""
    if not raw:
        return ""
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", raw, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_pubdate(raw: str) -> datetime | None:
    """RSS pubDate 파싱. 국내 언론사 CMS는 RFC822와 'YYYY-MM-DD HH:MM:SS'를 섞어 쓴다."""
    if not raw:
        return None
    raw = raw.strip()

    # RFC822 (Fri, 31 Jul 2026 08:04:00 GMT / +0900)
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        return dt.astimezone(KST)
    except Exception:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:len(fmt) + 2].strip(), fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    return None


def normalize_topic_key(title: str) -> str:
    """같은 사안을 여러 매체가 보도했을 때 묶기 위한 키. 조사·기호 제거 후 앞 단어들."""
    t = unicodedata.normalize("NFC", title)
    t = re.sub(r"\[[^\]]*\]", " ", t)              # [단독], [포토] 같은 머리표 제거
    t = re.sub(r"[^\w가-힣 ]", " ", t)
    words = [w for w in t.split() if len(w) >= 2]
    return " ".join(sorted(words)[:6]).lower()


# 이 사이트가 다루는 주제인가를 판단하는 핵심어.
#
# 프롬프트에 "임상·정책 일반 뉴스는 고르지 마라"고 아무리 써도 AI 가 지키지
# 않는다. 2026-09-01 에 "편두통 예방치료 지침 개정, CGRP 치료제 주목" 이
# 나왔다. 병의원 마케팅 담당자와 아무 상관이 없다.
# 중복 차단·홍보 차단 때와 같다 — 파이썬이 잘라야 한다.
MARKETING_CORE = [
    # 광고·심의 (1군)
    "광고", "심의", "마케팅", "홍보", "브랜딩", "과대", "과장", "허위",
    "유인", "알선", "환자 유치", "환자유치", "리뷰", "후기", "체험단", "이벤트",
    # 표시·가격 (광고 문구에 직결)
    "비급여", "진료비", "가격 표시", "표시 의무", "가격 공개",
    # 채널
    "SNS", "인스타", "유튜브", "블로그", "검색", "네이버", "카카오",
    "플랫폼", "수수료", "앱", "홈페이지",
    # 규제·제재 (광고와 엮이는 것)
    "의료법", "행정처분", "과태료", "과징금", "업무정지", "고발", "단속", "적발",
    # 시장
    "개원", "폐업", "비만", "미용", "성형", "피부", "라식", "임플란트",
]


def is_our_topic(title: str, summary: str = "") -> bool:
    """병의원 마케팅 매체가 다룰 주제인가.

    제목에 핵심어가 있어야 한다. 요약에만 스치듯 나오는 것은 인정하지 않는다.
    (요약까지 보면 "예산" 기사에도 '광고' 두 글자가 섞여 들어와 다 통과한다)
    """
    return any(kw in title for kw in MARKETING_CORE)


def is_promo(item: NewsItem) -> bool:
    """업체 홍보인가.

    강한 신호(출시·등장·MOU·실적 등)는 제목에 '의료광고'·'심의'가 들어 있어도
    구제하지 않는다. 이 사이트 주제상 업체 홍보에도 그 단어가 반드시 들어간다.
    """
    if any(re.search(p, item.title) for p in HARD_PROMO_PATTERNS):
        return True
    if any(kw in item.title for kw in POLICY_RESCUE):
        return False
    return any(re.search(p, item.title) for p in PROMO_PATTERNS)


def is_relevant(item: NewsItem) -> bool:
    blob = f"{item.title} {item.summary}"
    if any(re.search(p, item.title) for p in NOISE_PATTERNS):
        return False
    if is_promo(item):
        return False
    if item.kind == "gov":
        return True                                  # 보도자료는 전량 후보
    return any(kw in blob for kw in RELEVANT_KEYWORDS)


# ---------- RSS ----------

def fetch_feed(feed: dict) -> list[NewsItem]:
    req = urllib.request.Request(feed["url"], headers={"User-Agent": UA})
    try:
        raw = urllib.request.urlopen(req, timeout=TIMEOUT_SEC).read()
        root = ET.fromstring(raw)
    except Exception as exc:
        print(f"  [경고] {feed['name']} 피드 실패: {exc}")
        return []

    items: list[NewsItem] = []
    for node in root.findall(".//item"):
        title = strip_html(node.findtext("title") or "")
        link = (node.findtext("link") or "").strip()
        if not title or not link:
            continue
        summary = strip_html(node.findtext("description") or "")
        published = parse_pubdate(node.findtext("pubDate") or "") or datetime.now(KST)
        items.append(NewsItem(
            title=title,
            link=link,
            summary=summary[:600],
            published=published,
            source=feed["name"],
            kind=feed.get("kind", "press"),
        ))
    return items


# ---------- OpenAI 웹검색 (보강용) ----------

WEB_SEARCH_QUERY = (
    "최근 일주일 국내 병원·의원 마케팅, 의료광고 규제, 의료법 개정, "
    "보건복지부 의료광고 관련 뉴스"
)


def openai_web_search(max_items: int = 5) -> list[NewsItem]:
    """
    OpenAI Responses API의 웹검색 도구로 최신 이슈를 보강 수집.

    API 형태가 바뀌어도 일일 자동화가 멈추면 안 되므로, 실패 시 빈 리스트를
    반환하고 RSS 결과만으로 진행한다.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return []
    if os.getenv("NEWS_WEB_SEARCH", "1") != "1":
        return []

    prompt = (
        f"{WEB_SEARCH_QUERY}\n\n"
        "국내 병의원 마케터에게 실무적으로 의미 있는 최신 소식 "
        f"{max_items}건을 웹에서 찾아 아래 JSON 형식으로만 답하세요.\n"
        '{"items":[{"title":"...","link":"https://...","summary":"2~3문장 요약",'
        '"source":"매체명","date":"YYYY-MM-DD"}]}\n'
        "- 반드시 실제 접속 가능한 URL만 포함하세요. URL을 지어내지 마세요.\n"
        "- 확인된 사실만 요약하세요."
    )

    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    # 한 번만 시도한다. 예전에는 두 가지 도구 이름을 순서대로 시도했는데,
    # 실패할 때마다 수 분이 날아가 전체 실행이 25분 제한을 넘겼다.
    # 웹검색은 어차피 보강용이고 RSS 만으로도 후보가 200건 가까이 나온다.
    try:
        resp = client.responses.create(
            model=os.getenv("NEWS_SEARCH_MODEL", "gpt-4o"),
            tools=[{"type": "web_search"}],
            input=prompt,
            timeout=90,
        )
        return _parse_search_json(getattr(resp, "output_text", "") or "", max_items)
    except Exception as exc:
        print(f"  [정보] 웹검색 건너뜀 ({type(exc).__name__}) — RSS/보도자료만 사용합니다.")
        return []


def _parse_search_json(text: str, max_items: int) -> list[NewsItem]:
    import json
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []

    out: list[NewsItem] = []
    for row in (data.get("items") or [])[:max_items]:
        link = (row.get("link") or "").strip()
        title = strip_html(row.get("title") or "")
        if not link.startswith("http") or not title:
            continue
        published = parse_pubdate(row.get("date") or "") or datetime.now(KST)
        out.append(NewsItem(
            title=title,
            link=link,
            summary=strip_html(row.get("summary") or "")[:600],
            published=published,
            source=(row.get("source") or "웹검색").strip(),
            kind="web",
        ))
    return out


# ---------- 통합 ----------

def collect(hours: int = 48, use_web_search: bool = True) -> list[NewsItem]:
    """최근 `hours` 시간 이내 기사 중 관련성 있는 것만 최신순으로 반환."""
    cutoff = datetime.now(KST) - timedelta(hours=hours)
    seen_links: set[str] = set()
    collected: list[NewsItem] = []

    for feed in FEEDS:
        items = fetch_feed(feed)
        kept = 0
        for item in items:
            if item.published < cutoff:
                continue
            if item.link in seen_links:
                continue
            if not is_relevant(item):
                continue
            seen_links.add(item.link)
            collected.append(item)
            kept += 1
        print(f"  {feed['name']}: {len(items)}건 중 {kept}건 채택")

    if use_web_search:
        # 웹검색 결과가 필터를 통째로 건너뛰고 있었다. RSS 는 is_relevant() 를
        # 거치는데 여기만 그대로 append 했다. 그래서 경쟁 업체 자사 홈페이지가
        # 근거 자료로 들어와 홍보 기사가 나갔다 (2026-08-30).
        kept = dropped = 0
        for item in openai_web_search():
            if item.link in seen_links:
                continue
            if not is_credible_source(item.link):
                print(f"  [제외] 언론사가 아님: {item.source} — {item.title[:40]}")
                dropped += 1
                continue
            if not is_relevant(item):
                print(f"  [제외] 홍보성: {item.title[:50]}")
                dropped += 1
                continue
            seen_links.add(item.link)
            collected.append(item)
            kept += 1
        print(f"  웹검색: {kept}건 채택 / {dropped}건 제외")

    collected.sort(key=lambda i: i.published, reverse=True)
    return collected


if __name__ == "__main__":
    from dotenv import load_dotenv
    from pathlib import Path

    load_dotenv(Path(__file__).parent.parent / ".env")

    print("뉴스 수집 테스트 (최근 48시간)")
    results = collect()
    print(f"\n총 {len(results)}건\n")
    for it in results[:25]:
        print(f"  [{it.source}] {it.title[:64]}")
        print(f"     {it.published:%Y-%m-%d %H:%M}  {it.link}")
