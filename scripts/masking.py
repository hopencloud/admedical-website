"""
의료광고 OCR 텍스트 마스킹/정제 모듈.

OpenAI gpt-4o-mini를 사용해 OCR 텍스트에서 다음을 제거하고
순수 광고 문구만 남긴다:
  - 병원/의원/클리닉/치과/한의원 이름
  - 의사/원장/교수/전문의 이름
  - 전화/팩스 번호, 주소, 영업시간, URL
  - 심의번호/유효기간 등 행정 정보 (DB에 별도 저장)
  - OCR 오류로 보이는 의미 없는 글자

다른 스크립트에서 import해 사용:
    from masking import clean_ocr_text
    cleaned = clean_ocr_text(raw_ocr_text)
"""

import os
import re
import time
from openai import OpenAI, APIError, RateLimitError

_client = None

SYSTEM_PROMPT = """당신은 의료광고 시안 OCR 텍스트에서 (1) 병원 식별 정보와 (2) 의협 심의 정형구·의미 없는 OCR 깨짐 토막을 제거하는 작업을 합니다.

[가장 중요한 원칙 — 절대 위반하지 마세요]
1. 원본에 없는 단어/문장을 절대 만들어내지 마세요.
2. 원본 문구를 풀어쓰거나 요약하거나 다듬지 마세요. 원본 단어 순서/표현 유지.
3. "전문 클리닉입니다", "정확한 진단을 도와드립니다" 같은 일반 마케팅 표현 추가 금지.
4. 식별 정보·의협 정형구·OCR 깨짐 토막만 잘라내고, 나머지는 한국어 단어 그대로 두세요.
5. **식별 정보(병원/의사/위치)가 의심되면 무조건 지웁니다 — "혹시"로 남겨두지 말 것.**

[제거 대상 1A — 의료기관명 (브랜드/상호 일체 — 매우 적극적으로 제거)]
- 한국어 의료기관명 (OCR 오류로 깨진 형태 포함):
  예: "강북보아스이비인후과", "애플비뇨기과의원", "봄봄이비인후과", "차앤유의원", "차앤유의훤"
  → "이비인후과", "비뇨기과의원" 같이 고유명사 빠진 일반 명칭은 남겨도 됨.
  → 단독으로 등장한 "봄봄", "BORNBOM", "리쥬란", "라온" 같은 브랜드 토막도 제거.
- 영문 의료기관명/브랜드:
  예: "PANGYO SAEROTNTN REHABILITATION CLINIC", "SHINE BEAM", "BORNBOM"
- 「고유명사 + 의원/병원/클리닉/치과/한의원/한방병원/요양병원/메디컬」형태는 전부 제거.
- 약자/이니셜 (예: "BB의원", "K-derma", "SH클리닉") 도 제거.

[제거 대상 1B — 의료진 이름·직함 (모두 제거)]
- 직함과 한국 성씨가 인접하면 무조건 의사명으로 보고 제거:
  예: "김철수 원장", "유종호 박사", "이OO 원장", "원장 박OO", "대표원장 정민우",
       "27년경력 대표원장 유종호", "이사장 한OO", "교수 윤OO"
- 직함 단독("원장", "박사", "전문의")은 식별 정보가 아니므로 남겨도 됨.
- "원장님이 직접 진료" 같은 표현에서 이름이 함께 나오면 이름만 잘라냄.

[제거 대상 1C — 위치·접근성 안내 (광고에서 어느 병원인지 추론 가능한 모든 단서, 매우 적극적으로 제거)]
- 지하철·도보 안내:
  예: "7호선 사가정역 1번 출구", "강남역 도보 5분", "지하철 OO역 N번 출구",
       "OO역 도보 N분", "OO역 인근", "역세권", "OO역 직결", "OO역 바로 앞"
- 버스 안내: "OO정류장", "버스 N번 OO 정류장 하차"
- 랜드마크 기반 위치:
  예: "OO 맞은편", "OO 건너편", "OO 옆", "OO 앞", "OO 뒤편", "OO 근처",
       "이마트 옆", "스타벅스 건너편", "롯데마트 뒤편", "현대백화점 1층"
- 건물·층수:
  예: "OO빌딩 3층", "OO타워 10F", "지하 1층", "OO상가 N호", "OO프라자 N층",
       "OO센터 N층", "OO몰 N층", "멜포트몰 2층"
- 사거리·교차로·지명: "OO사거리", "OO오거리", "OO로타리", "OO중앙시장",
       "OO파출소 옆", "OO우체국 앞"
- 도로명/지번 주소 (전체 또는 부분 모두):
  예: "경남 창원시 성산구 외동반림로 126번길 56", "서울시 강남구 테헤란로 123",
       "OO구 OO동 N-N", "OO읍 OO리"
- 시·도·구·동 단위 행정구역이 단독으로 등장하면 그대로 둠 — 단,
  "OO구 OO" 처럼 의료기관·서비스와 결합돼 위치를 식별하면 제거.

[제거 대상 1D — 연락 수단]
- 전화/팩스 — 숫자-숫자 패턴은 무조건 제거:
  예: "031-212-1912", "02-1234-5678", "1588-XXXX", "055 282-2222", "010-XXXX-XXXX"
- 카카오톡 ID, 카카오 채널: "@OO병원", "카카오톡 친구추가", "ㅋㅌ @id"
- 홈페이지/이메일/SNS:
  예: "wwwgkbornbomcom", "www.example.com", "@id", "blog.naver.com/...",
       "instagram.com/...", "youtube.com/@..."

[제거 대상 2 — 의협 심의 정형구 / OCR 깨짐 토막]
- 심의 안내문: "심의필", "효력은 본 페이지에 국한됨", "본 동영상에 국한됨", "심의번호 000000-중-...", "유효기간..." 류
- 의협 직권 수정 안내문(길게 등장하는 절차문, 일부가 OCR로 깨진 형태):
  "일부 경미한 ... 직권으로 ... 수정 또는 삭제 ... 사후통보를 통해 ... 등록근거자료 첨부..." 형태
  → 이 절차 안내는 광고 본문이 아니라 의협이 PDF 하단에 같이 찍는 안내문이므로 통째로 제거.
- 한자/특수문자가 섞인 의미 없는 토막:
  예: "긍음孔뇨", "宗모곱", "弓읍o", "Iylyl", "HloIvy", "Ivv우 늉", "긍해하하루Y"
- 자모만 있거나 의미 없는 라틴 알파벳 조합: "ㅡㅡ", "ㅁㅁ", "Bozr", "rRy"
- 광고 메타 라벨: "PC 소재 미리보기", "기본형 소재", "이미지 끝으는", "소재 미리보기"

[남길 것 — 원본에 있는 그대로]
- 진료 항목, 시술명, 치료 효과, 적응증, 부작용 안내, 주의사항
  예: "허리디스크", "스마일수술", "튼살치료", "수면다원검사", "부작용 주의", "개인에 따라 피부 발진/염증"
- 광고 슬로건/캐치프레이즈 (식별 정보가 없는 한):
  예: "나도 안경 다닐래!", "결코 쉽게 생각하지 마십시오", "건강을 지키세요"
- 키워드/해시태그: "#피부탄력", "#리프팅"

[출력 형식]
- 위 제거 대상만 빼고 출력. 식별 정보 자리는 단순히 비우세요(대체 단어/표시 X).
- 원본의 자연스러운 줄바꿈만 유지하고, 단어마다 줄바꿈하지 마세요.
- 마크다운 줄바꿈(줄 끝 공백 2칸) 절대 사용 금지.
- 따옴표/머리말/JSON/코드블록 금지. 평문 텍스트만 반환.
- 남길 것이 전혀 없으면 빈 문자열만 반환."""


def _get_client():
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY가 .env에 없습니다.")
        _client = OpenAI(api_key=api_key)
    return _client


def _postprocess(text: str) -> str:
    """AI 출력 후처리: 마크다운 줄바꿈 제거, 단어별 줄바꿈 정리, 공백 정리."""
    if not text:
        return ""
    # 줄 끝 공백 두 개(마크다운 line break) → 일반 줄바꿈
    text = re.sub(r"  +\n", "\n", text)
    # 라인별로 잘라 양 끝 공백 제거
    lines = [ln.strip() for ln in text.splitlines()]
    # 한 단어만 있는 짧은 라인이 연속되면 한 줄로 합침 (가독성 개선)
    merged: list[str] = []
    buffer: list[str] = []
    for ln in lines:
        if not ln:
            if buffer:
                merged.append(" ".join(buffer))
                buffer = []
            merged.append("")
        elif len(ln) <= 8 and " " not in ln:
            buffer.append(ln)
        else:
            if buffer:
                merged.append(" ".join(buffer))
                buffer = []
            merged.append(ln)
    if buffer:
        merged.append(" ".join(buffer))
    out = "\n".join(merged)
    # 연속 빈 줄 1개로 축약
    out = re.sub(r"\n{3,}", "\n\n", out)
    # 연속 공백 1개로 축약
    out = re.sub(r" {2,}", " ", out)
    return out.strip()


def clean_ocr_text(raw_text: str, model: str = "gpt-4o-mini", max_retries: int = 3) -> str:
    """OCR 원문을 받아 광고 문구만 남긴 정제 텍스트를 반환.

    실패 시 빈 문자열 반환 (호출 측에서 fallback 처리 가능).
    """
    raw = (raw_text or "").strip()
    if not raw:
        return ""

    client = _get_client()

    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": raw},
                ],
                temperature=0.2,
                max_tokens=1000,
            )
            return _postprocess((resp.choices[0].message.content or "").strip())
        except RateLimitError:
            wait = 2 ** attempt
            time.sleep(wait)
        except APIError as e:
            if attempt == max_retries - 1:
                print(f"[masking] APIError 최종 실패: {e}")
                return ""
            time.sleep(2 ** attempt)
        except Exception as e:
            print(f"[masking] 예외: {type(e).__name__}: {e}")
            return ""

    return ""


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    sample = (
        "강남세브란스병원 김철수 원장이 직접 진료합니다. "
        "허리디스크 비수술 치료, 목디스크 주사 치료. "
        "문의 02-1234-5678, 서울특별시 강남구 테헤란로 123. "
        "심의번호: 260101-중-12345"
    )
    print("=== 원문 ===")
    print(sample)
    print()
    print("=== 정제 결과 ===")
    print(clean_ocr_text(sample))
