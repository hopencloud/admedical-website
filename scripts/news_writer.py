"""
원고 생성 — 주제 선정 → 초고 작성 → 자체 검수(팩트체크).

핵심 설계 원칙 (AdSense 정책·저작권·의료정보 리스크 대응):
  1. 기사 본문을 크롤링하지 않는다. RSS 제목/요약만 재료로 쓴다.
  2. 수치는 AI가 만들지 않는다. 도표 데이터는 우리 심의 DB(statistics.json)의 실측값만 사용.
  3. 검수 단계에서 '근거 없는 주장'이 발견되면 문장을 지우거나, 심하면 발행 자체를 포기한다.
  4. 원본 사이트 데이터(심의 통과 시안 통계)를 반드시 엮어 고유 관점을 만든다.

실행 (단독 테스트):
    python scripts/news_writer.py
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from openai import OpenAI

from news_sources import NewsItem, normalize_topic_key

KST = timezone(timedelta(hours=9))

WRITER_MODEL = os.getenv("NEWS_MODEL", "gpt-4o")
CHEAP_MODEL = os.getenv("NEWS_CHEAP_MODEL", "gpt-4o-mini")

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY가 .env에 없습니다.")
        _client = OpenAI(api_key=key)
    return _client


def _chat_json(model: str, system: str, user: str, max_tokens: int = 4000,
               temperature: float = 0.4) -> dict:
    """JSON 응답을 강제하는 공통 호출."""
    resp = get_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return json.loads(resp.choices[0].message.content)


# ==========================================================
# 1단계 — 주제 선정
# ==========================================================

TOPIC_SYSTEM = """당신은 병의원 마케팅 전문 매체의 편집장입니다.
독자는 병원·의원의 마케팅 담당자와 원장입니다.
독자가 '오늘 이걸 알아야 실무가 달라진다'고 느낄 기사를 고릅니다."""

TOPIC_PROMPT = """오늘 수집된 의료계 뉴스 목록입니다.

{items}

이 중에서 **병의원 마케팅 담당자에게 가장 실무 가치가 큰 주제 1개**를 정하세요.

[우선순위 — 위일수록 좋음]
1. 의료광고 규제·심의·의료법 개정 (마케터 업무에 직접 영향)
2. 보건복지부·정부 정책 변화 (비급여, 수가, 제도)
3. 환자 유입 채널·플랫폼·검색 환경 변화
4. 진료과별 시장 트렌드

[제외]
- 특정 병원 홍보성 소식, 인사·수상·학회 개최
- 제약사 실적·신약 허가 (병의원 마케팅과 무관)
- 이미 다룬 주제: {published}

[중요]
- 여러 매체가 같은 사안을 보도했다면 함께 묶어 근거로 삼으세요.
- 목록에 마케팅 관련 주제가 하나도 없으면 selected를 false로 하세요. 억지로 고르지 마세요.

JSON으로만 답하세요:
{{
  "selected": true,
  "topic": "기사 주제 한 문장",
  "angle": "병의원 마케터 관점에서 무엇을 짚을지 한 문장",
  "source_indexes": [0, 3, 7],
  "reason": "왜 이 주제인지 한 문장"
}}"""


def select_topic(items: list[NewsItem], published_topics: list[str]) -> dict | None:
    """수집 목록에서 오늘 다룰 주제 하나를 고른다. 마땅한 게 없으면 None."""
    if not items:
        return None

    listing = "\n".join(
        f"[{i}] ({it.source} / {it.published:%m-%d}) {it.title}\n     {it.summary[:180]}"
        for i, it in enumerate(items[:60])
    )
    recent = ", ".join(published_topics[-25:]) if published_topics else "(없음)"

    result = _chat_json(
        CHEAP_MODEL,
        TOPIC_SYSTEM,
        TOPIC_PROMPT.format(items=listing, published=recent),
        max_tokens=800,
        temperature=0.5,
    )

    if not result.get("selected"):
        print(f"  [정보] 적합한 주제 없음: {result.get('reason', '')}")
        return None

    idxs = [i for i in result.get("source_indexes", []) if isinstance(i, int) and 0 <= i < len(items)]
    if not idxs:
        return None

    result["sources"] = [items[i] for i in idxs[:6]]
    return result


# ==========================================================
# 2단계 — 초고 작성
# ==========================================================

WRITER_SYSTEM = """당신은 의료광고 심의 데이터를 다루는 전문 매체 'admedical'의 기자이자 SEO 편집자입니다.
독자는 병원·의원 마케팅 담당자입니다.

[절대 규칙 — 어기면 발행되지 않습니다]
- 원문 기사의 문장을 그대로 옮기지 마세요. 사실만 취하고 문장은 100% 새로 쓰세요.
- 제공된 자료에 없는 수치·날짜·통계·인용문을 절대 만들어내지 마세요.
  (본문의 모든 숫자는 기계가 근거 자료와 대조합니다)
- 의학적 효능이나 치료 결과를 단정하지 마세요. 진단·치료 조언을 하지 마세요.
- 법령 조항은 확실히 아는 것만 쓰세요. 애매하면 조항 번호를 빼고 서술하세요.
- 특정 병원·의료인을 홍보하거나 비방하지 마세요.
- 확정되지 않은 사안은 "논의 중", "예정", "검토 단계" 처럼 상태를 정확히 표기하세요.

[검색 노출 원칙 — 이 매체의 최우선 목표]
- 독자가 실제로 검색창에 칠 법한 표현을 제목과 소제목에 넣으세요.
  ("의료광고 심의", "병원 마케팅", "의료법 제56조", "비급여 광고" 같은 구체적 명사)
- 소제목(H2)은 **질문형이나 결론형**으로 쓰세요. 검색 결과 스니펫과 AI 답변에 그대로 인용됩니다.
- 각 문단은 첫 문장에 결론을 두고 뒤에 근거를 붙이세요 (역피라미드).
- 핵심 요약은 그 자체로 완결된 문장이어야 합니다. 앞뒤 문맥 없이 읽어도 뜻이 통해야 합니다.

[문체]
- 한국어. 실무자에게 말하듯 담백하고 구체적으로.
- 과장·감탄사·클릭베이트 금지. "충격", "대박", "필수" 같은 표현 금지.
- 한 문단 3~4문장."""

WRITER_PROMPT = """아래 자료로 기사 한 편을 작성하세요.

[주제]
{topic}

[관점]
{angle}

[근거 자료 — 이 안의 사실만 사용]
{sources}

[우리 사이트 자체 데이터 — 기사와 관련이 있을 때만 인용하세요]
admedical은 대한의사협회 의료광고심의위원회 통과 시안을 매일 수집해 텍스트로 인덱싱합니다.
- 최근 집계일({yesterday_date}) 심의 통과: {yesterday_count}건
- 이번 주 누적: {this_week_count}건
- 지난달 전체: {last_month_count}건
- 누적 인덱싱: {total_count}건
- 최근 자주 통과된 표현: {top_expressions}
※ 주제와 무관한데 억지로 끼워 넣지 마세요. 관련 없으면 언급하지 않아도 됩니다.

[기사 구성]
- summary 는 반드시 80자 이내. 넘으면 검색결과에서 잘린다.
- 도입(lead): 무슨 일이 있었는지 3~4문장
- 본문 4개 섹션. 소제목은 검색어를 포함한 질문형/결론형으로.
- 마지막: 마케터가 당장 확인할 체크리스트 3~5개
- FAQ 정확히 3개

[분량 — 반드시 지킬 것]
- 전체 본문 1,200자 이상 (공백 제외)
- 각 섹션은 문단 2~3개, 각 문단 3~4문장·150자 이상

[도식(infographic) 선택 — 기사에 가장 맞는 것 하나]
최근 발행분이 쓴 유형: {recent_types}
가능하면 위와 다른 유형을 고르세요. 내용상 도저히 안 맞으면 같은 유형을 써도 됩니다.
아래 다섯 중 기사 내용에 실제로 어울리는 것을 고르세요.
  · comparison  — 대비가 핵심일 때 (반려 표현 vs 대안, 개정 전 vs 후)
  · timeline    — 시행 일정·단계별 진행이 핵심일 때
  · process     — 절차·신청 순서가 핵심일 때
  · checklist   — 실무 점검 항목이 핵심일 때
  · stat_trend  — 우리 심의 통과 건수 추이가 기사와 **직접** 관련될 때만
도식 안의 문구도 근거 자료 범위를 벗어나면 안 됩니다.

[이미지 — 사진 1장 + 일러스트 1장, 성격이 완전히 달라야 합니다]

1) photo (표지) — **실사 사진**입니다.
   실제로 카메라로 찍을 수 있는 장면만 쓰세요. 병원 접수 데스크의 태블릿, 책상 위 서류와 도장,
   진료실 창가, 스마트폰 화면을 보는 손 같은 구체적 사물·공간.
   추상 개념(화살표, 떠 있는 아이콘, 그래프 도형)은 사진에 쓸 수 없습니다.

2) illustration (본문) — **플랫 벡터 일러스트**입니다.
   사진으로 찍을 수 없는 개념을 도식적으로 표현하세요. 관계·흐름·대비 같은 것.

두 장 모두 concept 은 이 기사에서만 나올 수 있는 장면을 영어 25단어 이상으로 묘사하세요.
"medical marketing concept" 같은 뻔한 표현 금지. 무엇이 어디에 어떻게 놓이는지 쓰세요.
글자·숫자는 이미지에 넣지 마세요 (모델이 한글을 깨뜨립니다).
사람은 뒷모습·손·실루엣까지만. 얼굴이 보이면 안 됩니다. alt 는 한국어로.

JSON으로만 답하세요:
{{
  "title": "40자 이내. 핵심 검색어를 앞쪽에 둔 사실 중심 제목",
  "seo_title": "검색결과용 제목 60자 이내. 제목 + 핵심 키워드 보강",
  "slug_hint": "url-용-영문소문자-하이픈-4~6단어",
  "summary": "검색결과에 뜨는 설명문. **80자 이내** 한 문장 (네이버가 그 이상은 잘라낸다)",
  "key_points": ["기사 핵심 3가지. 각 한 문장, 문맥 없이 읽어도 뜻이 통하게"],
  "keywords": ["검색 키워드 5~8개"],
  "lead": "도입 문단",
  "sections": [
    {{"heading": "검색어를 포함한 질문형/결론형 소제목",
      "paragraphs": ["문단1", "문단2"]}}
  ],
  "checklist": ["체크 항목1", "체크 항목2", "체크 항목3"],
  "faq": [{{"q": "실무자가 검색할 법한 질문", "a": "2~3문장 답변"}}],
  "infographic": {{
    "type": "comparison | timeline | process | checklist | stat_trend",
    "title": "도식 제목",
    "caption": "도식 아래 설명 1문장",
    "alt": "도식 대체 텍스트 (한국어)",
    "left_title": "comparison 일 때만", "right_title": "comparison 일 때만",
    "rows": [{{"left": "...", "right": "..."}}],
    "steps": [{{"when": "timeline 일 때", "label": "...", "note": "process 일 때 보조설명"}}],
    "items": ["checklist 일 때"]
  }},
  "images": [
    {{"role": "photo", "concept": "실제로 촬영 가능한 구체적 장면 (영어, 25단어 이상)",
      "detail": "렌즈·앵글·빛·전경/배경 배치 보충 (영어)", "alt": "한국어 대체 텍스트 (80자 이내)"}},
    {{"role": "illustration", "concept": "사진으로 못 찍는 개념의 도식적 표현 (영어, 25단어 이상)",
      "detail": "구성·배치·강조점 보충 (영어)", "alt": "한국어 대체 텍스트 (80자 이내)"}}
  ],
  "tags": ["태그 3~5개"]
}}"""


def _fmt_sources(sources: list[NewsItem]) -> str:
    return "\n\n".join(
        f"- 매체: {s.source} ({s.published:%Y-%m-%d})\n"
        f"  제목: {s.title}\n"
        f"  요약: {s.summary}\n"
        f"  링크: {s.link}"
        for s in sources
    )


def write_article(topic: dict, stats: dict, top_expressions: list[str],
                  recent_types: list[str] | None = None) -> dict:
    prompt = WRITER_PROMPT.format(
        recent_types=", ".join(recent_types or []) or "(없음)",
        topic=topic["topic"],
        angle=topic.get("angle", ""),
        sources=_fmt_sources(topic["sources"]),
        yesterday_date=stats.get("yesterday", {}).get("date", "-"),
        yesterday_count=stats.get("yesterday", {}).get("count", "-"),
        this_week_count=stats.get("this_week", {}).get("count", "-"),
        last_month_count=stats.get("last_month", {}).get("count", "-"),
        total_count=stats.get("total", {}).get("count", "-"),
        top_expressions=", ".join(top_expressions[:12]) or "(집계 중)",
    )
    return _chat_json(WRITER_MODEL, WRITER_SYSTEM, prompt, max_tokens=4000, temperature=0.5)


# ==========================================================
# 2.5단계 — 분량 보강
# ==========================================================

MIN_CHARS = int(os.getenv("NEWS_MIN_CHARS", "1100"))

EXPAND_PROMPT = """아래 기사가 {current}자로 너무 짧습니다. {target}자 이상으로 늘려주세요.

[근거 자료 — 이 안의 사실만 사용]
{sources}

[늘리는 방법 — 이것만 하세요]
- 기존 문단을 더 구체적으로 풀어 씁니다 (적용 대상, 판단 기준, 준비 순서, 흔한 오해).
- 실무자가 실제로 마주할 상황을 예시로 설명합니다.
- 섹션을 하나 더 추가해도 좋습니다.

[절대 하지 말 것]
- 근거 자료에 없는 수치·날짜·기관명·인용문을 새로 만들지 마세요.
- 같은 말을 바꿔 쓰며 늘리지 마세요.
- 제목·요약·이미지 프롬프트·태그는 그대로 두세요.

[기사]
{draft}

기사와 완전히 같은 JSON 구조로만 답하세요."""


def expand_article(article: dict, topic: dict) -> dict:
    """분량 미달 시 한 번 더 늘린다. 실패하면 원본을 그대로 쓴다."""
    current = word_count(article)
    if current >= MIN_CHARS:
        return article

    try:
        result = _chat_json(
            WRITER_MODEL,
            WRITER_SYSTEM,
            EXPAND_PROMPT.format(
                current=current,
                target=MIN_CHARS + 200,
                sources=_fmt_sources(topic["sources"]),
                draft=json.dumps(article, ensure_ascii=False, indent=2),
            ),
            max_tokens=5000,
            temperature=0.5,
        )
    except Exception as exc:
        print(f"  [정보] 분량 보강 실패 (원본 유지): {exc}")
        return article

    if result.get("title") and result.get("sections") and word_count(result) > current:
        return result
    return article


# ==========================================================
# 3단계 — 자체 검수 (팩트체크 / 정책 리스크)
# ==========================================================

REVIEW_SYSTEM = """당신은 의료 전문 매체의 데스크(교열·검증 책임자)입니다.
기자가 쓴 초고를 근거 자료와 대조해 검증합니다. 통과시키는 것이 목적이 아니라 걸러내는 것이 목적입니다."""

REVIEW_PROMPT = """[근거 자료]
{sources}

[우리 사이트 실측 데이터]
어제 심의 통과 {yesterday_count}건 / 이번 주 {this_week_count}건 / 지난달 {last_month_count}건 / 누적 {total_count}건

[검수할 초고]
{draft}

다음을 하나씩 점검하고 문제가 있으면 **직접 고친 최종본**을 반환하세요.

1. 근거 자료에 없는 수치·날짜·기관명·인용문이 있는가? → 있으면 해당 서술을 삭제하거나 근거 있는 표현으로 바꾼다.
2. 확정되지 않은 사안을 확정된 것처럼 썼는가? → "논의 중/예정/검토" 로 정정한다.
3. 의학적 효능·치료 결과를 단정했는가? → 삭제한다.
4. 법령 조항 번호가 틀렸을 가능성이 있는가? → 번호를 빼고 서술로 바꾼다.
5. 원문 기사 문장을 그대로 베낀 흔적이 있는가? → 다시 쓴다.
6. 특정 병원·업체 홍보로 읽힐 여지가 있는가? → 중립적으로 바꾼다.
7. 제목이 내용보다 과장되었는가? → 사실에 맞게 낮춘다.

[판정 기준]
- 고쳐서 살릴 수 있으면 verdict = "revised" (또는 문제없으면 "pass")
- 근거가 너무 빈약해 기사 자체가 성립하지 않으면 verdict = "reject"

JSON으로만 답하세요. article 필드는 초고와 완전히 같은 구조를 유지하세요:
{{
  "verdict": "pass" | "revised" | "reject",
  "issues": ["발견한 문제 1", "문제 2"],
  "article": {{ ...수정된 기사 전체... }}
}}"""


def review_article(draft: dict, topic: dict, stats: dict) -> tuple[str, dict, list[str]]:
    """(verdict, 최종 기사, 지적사항) 반환."""
    prompt = REVIEW_PROMPT.format(
        sources=_fmt_sources(topic["sources"]),
        yesterday_count=stats.get("yesterday", {}).get("count", "-"),
        this_week_count=stats.get("this_week", {}).get("count", "-"),
        last_month_count=stats.get("last_month", {}).get("count", "-"),
        total_count=stats.get("total", {}).get("count", "-"),
        draft=json.dumps(draft, ensure_ascii=False, indent=2),
    )
    result = _chat_json(WRITER_MODEL, REVIEW_SYSTEM, prompt, max_tokens=4000, temperature=0.2)

    verdict = result.get("verdict", "reject")
    issues = result.get("issues") or []
    article = result.get("article") or draft

    # 검수본이 구조를 망가뜨렸으면 초고를 신뢰한다.
    if not article.get("title") or not article.get("sections"):
        article = draft
        verdict = "pass" if verdict != "reject" else verdict

    return verdict, article, issues


# ==========================================================
# 4단계 — 수치 검증 (결정적 검사)
# ==========================================================
#
# AI에게 "지어내지 마라"고 지시하는 것만으로는 부족하다. 검수 단계가 "고쳤다"고
# 답하면서 실제로는 수치를 그대로 두는 경우가 있었다. 그래서 파이썬이 직접
# 본문의 모든 숫자를 근거 자료와 대조한다.

# 연도·비율·순번처럼 근거에 없어도 자연스러운 표현은 검사에서 제외한다.
_NUM_SKIP = re.compile(r"^(19|20)\d{2}$")


def _numbers_in(text: str) -> set[str]:
    """쉼표를 제거한 숫자 토큰 집합."""
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*", text)}


def _article_text(article: dict) -> str:
    """수치 검증 대상 텍스트. 화면에 보이는 문자열은 전부 포함해야 한다."""
    chunks = [article.get("title", ""), article.get("seo_title", ""),
              article.get("summary", ""), article.get("lead", "")]
    chunks += list(article.get("key_points", []) or [])
    for sec in article.get("sections", []):
        chunks.append(sec.get("heading", ""))
        chunks.extend(sec.get("paragraphs", []))
    chunks.extend(article.get("checklist", []))
    for f in article.get("faq", []) or []:
        chunks.extend([f.get("q", ""), f.get("a", "")])

    # 도식 안의 문구도 독자에게 보이므로 같은 기준으로 검증한다.
    from news_images import infographic_text
    chunks.append(infographic_text(article.get("infographic") or {}))

    return " ".join(c for c in chunks if c)


def unsupported_numbers(article: dict, topic: dict, stats: dict) -> list[str]:
    """근거 자료·자체 통계 어디에도 없는 숫자를 찾아낸다."""
    allowed = set()
    for s in topic["sources"]:
        allowed |= _numbers_in(f"{s.title} {s.summary}")

    for key in ("yesterday", "this_week", "this_month", "last_week", "last_month", "total"):
        block = stats.get(key) or {}
        allowed |= _numbers_in(str(block.get("count", "")))
        allowed |= _numbers_in(str(block.get("date", "")))

    found = _numbers_in(_article_text(article))
    return sorted(
        n for n in found - allowed
        if not _NUM_SKIP.match(n) and len(n) >= 2
    )


STRIP_PROMPT = """아래 기사에 근거 자료로 확인되지 않는 숫자가 들어 있습니다.

[확인 불가한 숫자]
{numbers}

[근거 자료]
{sources}

이 숫자들이 들어간 서술을 고치세요.

[고치는 방법]
- 숫자를 빼고 서술로 바꿉니다. 예: "324개 기관이 참여했다" → "다수의 종합병원이 참여했다"
- 문장을 통째로 지워도 됩니다. 대신 문단이 너무 짧아지지 않게 앞뒤를 자연스럽게 이어주세요.
- 다른 숫자로 바꾸지 마세요. 추측한 숫자를 새로 넣는 것이 가장 나쁩니다.
- 근거 자료에 실제로 있는 숫자는 그대로 두세요.

[기사]
{draft}

기사와 완전히 같은 JSON 구조로만 답하세요."""


def strip_unsupported_numbers(article: dict, topic: dict, stats: dict,
                              max_rounds: int = 2) -> tuple[dict, list[str]]:
    """확인 불가한 숫자를 제거한다. (최종 기사, 남은 문제 숫자)"""
    for _ in range(max_rounds):
        bad = unsupported_numbers(article, topic, stats)
        if not bad:
            return article, []

        try:
            result = _chat_json(
                WRITER_MODEL,
                REVIEW_SYSTEM,
                STRIP_PROMPT.format(
                    numbers=", ".join(bad),
                    sources=_fmt_sources(topic["sources"]),
                    draft=json.dumps(article, ensure_ascii=False, indent=2),
                ),
                max_tokens=5000,
                temperature=0.1,
            )
        except Exception as exc:
            print(f"  [정보] 수치 정정 호출 실패: {exc}")
            return article, bad

        if result.get("title") and result.get("sections"):
            article = result
        else:
            return article, bad

    return article, unsupported_numbers(article, topic, stats)


# ==========================================================
# 유틸
# ==========================================================

def make_slug(article: dict, date: datetime) -> str:
    """URL 슬러그. 영문 힌트가 없으면 제목에서 만들되 항상 날짜를 접두로 둔다."""
    hint = (article.get("slug_hint") or "").strip().lower()
    hint = unicodedata.normalize("NFKD", hint)
    hint = re.sub(r"[^a-z0-9]+", "-", hint).strip("-")

    if not hint or len(hint) < 3:
        hint = "medical-marketing-news"

    return f"{date:%Y-%m-%d}-{hint[:60]}"


def article_topic_key(article: dict) -> str:
    return normalize_topic_key(article.get("title", ""))


def word_count(article: dict) -> int:
    text = article.get("lead", "")
    for sec in article.get("sections", []):
        text += " ".join(sec.get("paragraphs", []))
    return len(re.sub(r"\s", "", text))


if __name__ == "__main__":
    from pathlib import Path
    from dotenv import load_dotenv
    import news_sources

    load_dotenv(Path(__file__).parent.parent / ".env")

    items = news_sources.collect(use_web_search=False)
    print(f"수집 {len(items)}건")

    picked = select_topic(items, [])
    if not picked:
        raise SystemExit("주제 선정 실패")
    print(f"\n주제: {picked['topic']}\n관점: {picked['angle']}")

    stats_path = Path(__file__).parent.parent / "website" / "assets" / "data" / "statistics.json"
    stats = json.loads(stats_path.read_text(encoding="utf-8"))

    draft = write_article(picked, stats, [])
    print(f"\n초고 제목: {draft['title']} ({word_count(draft)}자)")

    verdict, final, issues = review_article(draft, picked, stats)
    print(f"검수: {verdict}")
    for i in issues:
        print(f"  - {i}")
    print(f"\n최종 제목: {final['title']}")
