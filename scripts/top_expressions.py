"""
TOP 20 표현 추출 공유 모듈.

파이프라인:
  1. Supabase에서 기간 내 마스킹된 ocr_text 모두 가져오기
  2. N-gram (2~4단어) 추출 + 빈도수 카운트
  3. 불용어 사전(config/stopwords.txt)으로 필터링
  4. 길이/문자 종류로 추가 필터 (자모 깨짐, 숫자만 등)
  5. 상위 100개 후보 → OpenAI gpt-4o-mini로 정제 (마케팅 가치 있는 20개 선별)
  6. AI 호출 실패 시 빈도수 기반으로 fallback (그대로 상위 20개)

사용 예:
    from top_expressions import compute_top20
    result = compute_top20(start_date="2026-04-13", end_date="2026-04-19", label="지난주")
"""

import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from openai import OpenAI, APIError, RateLimitError

ROOT = Path(__file__).parent.parent
KST = timezone(timedelta(hours=9))

# ---------- 불용어 / 필터 ----------

def load_stopwords() -> set[str]:
    path = ROOT / "config" / "stopwords.txt"
    if not path.exists():
        return set()
    words: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        words.add(line)
    return words


# 자모만 있는 토큰 (ㄱ, ㅏ 같은 단독 자모 또는 의미 없는 조합)
_JAMO_ONLY = re.compile(r"^[ㄱ-ㆎᄀ-ᇿ]+$")
# 한자 포함
_HAS_HANJA = re.compile(r"[一-鿿]")
# 숫자/특수문자만
_NUMERIC_OR_PUNCT_ONLY = re.compile(r"^[\d\W_]+$")
# 한글 음절 + 알파벳 혼재 (의미 있는 경우 제외하기 어려워 일단 제거)
_HANGUL_LATIN_MIX = re.compile(r"[가-힣].*[A-Za-z]|[A-Za-z].*[가-힣]")


def is_garbage_token(token: str) -> bool:
    """OCR 깨짐/의미 없는 토큰인지 판정."""
    if len(token) < 2:
        return True
    if _JAMO_ONLY.match(token):
        return True
    if _HAS_HANJA.search(token):
        return True
    if _NUMERIC_OR_PUNCT_ONLY.match(token):
        return True
    return False


def is_garbage_ngram(ngram: str, stopwords: set[str]) -> bool:
    """N-gram 전체가 의미 없거나 불용어인지 판정."""
    if ngram in stopwords:
        return True
    tokens = ngram.split()
    # 토큰의 절반 이상이 깨진 토큰이면 제외
    bad = sum(1 for t in tokens if is_garbage_token(t))
    if bad >= len(tokens) / 2 + 1:
        return True
    # 모든 토큰이 한 글자(2자 이상이라도 너무 짧은 것 제외 위함)
    if all(len(t) <= 2 for t in tokens):
        return True
    return False


# ---------- Supabase에서 데이터 가져오기 ----------

def fetch_ads_in_range(start_date: str, end_date: str) -> list[dict]:
    """Supabase ads 테이블에서 기간 내 광고 가져오기 (페이징)."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL/SERVICE_KEY가 .env에 없습니다.")

    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    out: list[dict] = []
    page_size = 1000
    offset = 0
    while True:
        r = requests.get(
            f"{url}/rest/v1/ads"
            f"?select=review_num,review_no_display,review_date,ocr_text"
            f"&review_date=gte.{start_date}&review_date=lte.{end_date}"
            f"&order=review_num.asc"
            f"&offset={offset}&limit={page_size}",
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        out.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return out


# ---------- N-gram 추출 ----------

# 단일 토큰을 후보로 인정하는 최소 한글 길이
_UNIGRAM_MIN_HANGUL = 3
_HANGUL_RE = re.compile(r"[가-힣]")


def extract_ngrams(text: str, ngram_sizes: tuple[int, ...] = (1, 2, 3, 4)) -> list[str]:
    """공백 단위 토큰으로 N-gram 생성. n=1(단일 단어)는 한글 3자 이상만."""
    tokens = text.split()
    ngrams: list[str] = []
    for n in ngram_sizes:
        for i in range(len(tokens) - n + 1):
            window = tokens[i : i + n]
            if n == 1:
                tok = window[0]
                # 단일 토큰: 한글 음절 3자 이상이면서 깨진 토큰이 아닐 때만
                if len(_HANGUL_RE.findall(tok)) < _UNIGRAM_MIN_HANGUL:
                    continue
                if is_garbage_token(tok):
                    continue
            ngrams.append(" ".join(window))
    return ngrams


def build_candidates(
    ads: list[dict],
    stopwords: set[str],
    top_k: int = 100,
) -> list[tuple[str, int, list[str]]]:
    """N-gram 빈도 카운트 + 필터링 후 상위 후보 (표현, 빈도, 예시 review_no_display 3개) 반환."""
    counter: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)

    for ad in ads:
        text = (ad.get("ocr_text") or "").strip()
        if not text:
            continue
        seen_in_ad: set[str] = set()  # 같은 광고에서 중복 카운트 안 함
        for ng in extract_ngrams(text):
            if is_garbage_ngram(ng, stopwords):
                continue
            if ng in seen_in_ad:
                continue
            seen_in_ad.add(ng)
            counter[ng] += 1
            if len(examples[ng]) < 3:
                examples[ng].append(ad.get("review_no_display", str(ad.get("review_num", ""))))

    return [(ng, cnt, examples[ng]) for ng, cnt in counter.most_common(top_k)]


# ---------- AI 정제 ----------

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


REFINE_PROMPT = """당신은 의료광고 마케팅 분석가입니다.

아래는 의료광고 심의 통과 시안에서 자주 등장한 표현 후보 목록입니다.
각 항목은 (표현, 빈도수) 형태입니다.

이 후보 중에서 "의료광고 마케터에게 인사이트가 될 만한 표현" 20개를 골라주세요.

[가장 중요한 규칙 — 절대 위반 금지]
- 반드시 후보 목록에 있는 표현만 그대로 골라주세요.
- 후보에 없는 표현을 새로 만들거나, 표현을 수정·합성하거나, 단어를 추가하지 마세요.
- 선택한 표현은 후보 목록의 텍스트와 한 글자도 다르지 않아야 합니다 (공백 포함).

[선별 우선순위 — 이런 후보를 우선 고르세요]
- 진료 항목/시술명/치료법 (예: 수면다원검사, 도수치료, 인공관절수술)
- 진료 효능/특징/방식 (예: 당일치료, 비수술, 365일진료)
- 소비자 어필 슬로건/캐치프레이즈
- 해시태그형 키워드 (#로 시작)

[제외 기준]
- OCR 오류로 보이는 의미 없는 토막
- 너무 일반적인 단어 나열 ("수 있습니다", "그리고 또")
- 한자/특수문자가 섞인 깨진 표현

다양한 진료 영역(피부/성형/안과/이비인후과/정형/내과 등)에서 골고루 선별하세요.
한 진료 영역의 비슷한 표현이 여러 개면 가장 대표적인 것 1~2개만 선택.

결과를 다음 JSON 형식으로만 반환하세요. 설명/주석 추가 금지.

{
  "top20": [
    "표현1",
    "표현2",
    "...",
    "표현20"
  ]
}
"""


def refine_with_ai(
    candidates: list[tuple[str, int, list[str]]],
    period_label: str,
    max_retries: int = 3,
) -> list[str] | None:
    """후보 목록을 OpenAI에 보내 마케팅 가치 있는 20개 선별. 실패 시 None."""
    if not candidates:
        return []

    user_msg = f"기간: {period_label}\n\n후보 100개:\n" + "\n".join(
        f"- {ng} (빈도 {cnt})" for ng, cnt, _ in candidates
    )

    client = _get_client()
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": REFINE_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=2000,
            )
            data = json.loads(resp.choices[0].message.content or "{}")
            top20 = data.get("top20", [])
            if isinstance(top20, list) and top20:
                return [str(s).strip() for s in top20 if str(s).strip()][:20]
        except RateLimitError:
            time.sleep(2 ** attempt)
        except (APIError, json.JSONDecodeError) as e:
            print(f"[AI 정제] 시도 {attempt+1} 실패: {type(e).__name__}: {e}")
            time.sleep(2 ** attempt)
        except Exception as e:
            print(f"[AI 정제] 예외: {type(e).__name__}: {e}")
            return None
    return None


# ---------- 통합 함수 ----------

def compute_top20(
    start_date: str,
    end_date: str,
    label: str,
) -> dict:
    """기간 내 광고에서 TOP 20 표현을 계산해 dict로 반환."""
    print(f"\n[{label}] {start_date} ~ {end_date} 분석 시작")

    stopwords = load_stopwords()
    ads = fetch_ads_in_range(start_date, end_date)
    print(f"  - 대상 광고: {len(ads):,}건")

    candidates = build_candidates(ads, stopwords, top_k=100)
    print(f"  - 빈도 후보: {len(candidates)}개 (필터링 후)")

    ai_top20 = refine_with_ai(candidates, label)
    if ai_top20:
        # 후보 목록에 실제 있는 것만 통과 (AI 환각 차단)
        cand_lookup = {ng: (cnt, ex) for ng, cnt, ex in candidates}
        items = []
        dropped: list[str] = []
        for expr in ai_top20:
            if expr in cand_lookup:
                cnt, ex = cand_lookup[expr]
                items.append({"expression": expr, "count": cnt, "examples": ex})
            else:
                dropped.append(expr)
        # AI가 환각 만든 게 있어 부족하면 빈도수 상위에서 채워 넣기
        if len(items) < 20:
            already = {it["expression"] for it in items}
            for ng, cnt, ex in candidates:
                if ng not in already:
                    items.append({"expression": ng, "count": cnt, "examples": ex})
                    already.add(ng)
                    if len(items) >= 20:
                        break
        if dropped:
            print(f"  - AI 환각 {len(dropped)}건 제거: {dropped[:3]}{'...' if len(dropped) > 3 else ''}")
        print(f"  - AI 정제 성공: {len(items)}개 (유효)")
        method = "ai_refined"
    else:
        print(f"  - AI 정제 실패 → 빈도수 기반 fallback")
        items = [
            {"expression": ng, "count": cnt, "examples": ex}
            for ng, cnt, ex in candidates[:20]
        ]
        method = "frequency_only"

    return {
        "label": label,
        "start_date": start_date,
        "end_date": end_date,
        "ads_analyzed": len(ads),
        "method": method,
        "generated_at": datetime.now(KST).isoformat(),
        "top20": items,
    }


# ---------- CLI 단독 실행 (디버깅용) ----------

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    if len(sys.argv) < 3:
        print("사용법: python top_expressions.py START_DATE END_DATE [LABEL]")
        print("예시: python top_expressions.py 2026-04-13 2026-04-19 '지난주'")
        sys.exit(1)

    result = compute_top20(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "테스트")
    print(json.dumps(result, ensure_ascii=False, indent=2))
