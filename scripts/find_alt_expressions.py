"""
Supabase에서 카테고리별로 "안전한 통과 표현"을 검색해 대안 표현 후보를 추출.

각 카테고리:
  1. 과장·치료 효과 보장 → 부작용 안내, 개인차 명시 표현 검색
  2. 비교·우월성 → 객관적 사실 (전문의 N명, N년 경력) 검색
  3. 자격·전문성 → 전문의/박사/교수 정확한 표현
  4. 안전·시술 안내 → 시술명 + 부작용 안내

각 후보마다 review_no_display 표시 → 사용자가 admedical.org에서 검증 가능.
"""
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SERVICE_KEY")
HEADERS = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"}

# 검색 키워드별 후보 수집 설정
SEARCH_QUERIES = {
    "side_effects": ["부작용 주의", "개인에 따라", "발생할 수 있", "차이가 있을 수"],
    "expertise": ["전문의", "년 경력", "박사", "교수", "출신"],
    "treatment_neutral": ["치료", "시술", "관리"],
    "exam_screening": ["검진", "검사", "진단"],
    "facility": ["365일", "야간 진료", "당일 진료", "예약"],
    "specific_conditions": ["허리디스크", "목디스크", "오십견", "보톡스", "필러", "라식"],
}

# 각 카테고리별 대안표현 매칭 — 실제 통과 표현이 어떤 모양이어야 하는지
CATEGORY_PATTERNS = {
    "1_과장_효과보장_대안": {
        "description": "과장 표현 대신 '부작용/개인차 안내' 같은 안전한 표현",
        "include_patterns": [r"부작용", r"개인.{0,5}따라", r"있을 수 있", r"차이가 있"],
        "exclude_patterns": [r"100\s?%", r"완벽", r"보장", r"절대", r"전혀 없"],
    },
    "2_비교우월성_대안": {
        "description": "비교 대신 객관적 사실(연차/경력/도입연도) 표현",
        "include_patterns": [r"\d+\s?년", r"전문의\s?\d+", r"전공", r"출신"],
        "exclude_patterns": [r"국내 1", r"최고", r"최초", r"최첨단", r"독보", r"압도"],
    },
    "3_자격사칭_대안": {
        "description": "직함과 자격을 정확히 표시한 안전 표현",
        "include_patterns": [r"전문의", r"외과 전문의", r"내과 전문의", r"피부과 전문의"],
        "exclude_patterns": [r"권위자", r"명의\b", r"세계 최초", r"FDA"],
    },
    "4_시술안내_대안": {
        "description": "시술/치료를 안전하게 안내하는 표현",
        "include_patterns": [r"치료", r"시술", r"진료"],
        "exclude_patterns": [r"\d+\s?만\s?원", r"할인", r"이벤트", r"이전&", r"비포"],
    },
}


def fetch_search(keyword: str, limit: int = 50) -> list[dict]:
    """ocr_text에 keyword가 포함된 행 검색."""
    safe = keyword.replace("%", "\\%")
    url = (
        f"{SB_URL}/rest/v1/ads"
        f"?select=review_num,review_no_display,review_date,ocr_text"
        f"&ocr_text=ilike.*{requests.utils.quote(safe)}*"
        f"&order=review_date.desc"
        f"&limit={limit}"
    )
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def passes(text: str, include: list[str], exclude: list[str]) -> bool:
    if not text:
        return False
    for pat in exclude:
        if re.search(pat, text):
            return False
    for pat in include:
        if re.search(pat, text):
            return True
    return False


def main():
    print("=== Supabase에서 카테고리별 안전 통과 표현 추출 ===\n")

    # 후보 풀 모으기 (다양한 키워드로 광고 수집)
    seen = set()
    pool: list[dict] = []
    for kw_group in SEARCH_QUERIES.values():
        for kw in kw_group:
            try:
                rows = fetch_search(kw, limit=80)
                for row in rows:
                    rn = row["review_num"]
                    if rn in seen:
                        continue
                    seen.add(rn)
                    pool.append(row)
            except Exception as e:
                print(f"  [경고] '{kw}' 검색 실패: {e}")
    print(f"수집된 광고 풀: {len(pool):,}건\n")

    # 카테고리별 매칭
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for cat, cfg in CATEGORY_PATTERNS.items():
        for row in pool:
            text = (row.get("ocr_text") or "").strip()
            if not text or len(text) < 8:
                continue
            if passes(text, cfg["include_patterns"], cfg["exclude_patterns"]):
                by_cat[cat].append(row)

    # 출력
    for cat, rows in by_cat.items():
        print(f"\n{'=' * 78}")
        print(f"📌 {cat}")
        print(f"   {CATEGORY_PATTERNS[cat]['description']}")
        print(f"   매칭: {len(rows)}건")
        print('=' * 78)
        # 상위 25개만 표시 (다양한 review_date 분포 고려해서 정렬)
        rows_sorted = sorted(rows, key=lambda r: r["review_date"], reverse=True)[:25]
        for r in rows_sorted:
            text = r["ocr_text"][:200].replace("\n", " ")
            print(f"  [{r['review_no_display']}] {text}")


if __name__ == "__main__":
    main()
