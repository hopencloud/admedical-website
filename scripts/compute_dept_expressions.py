"""진료과별 통과 표현 집계 → website/assets/data/dept/<slug>.json

왜 있는가:
    서치콘솔을 뜯어보니 노출 7,930회 중 92%가 두 페이지에서 나오는데,
    그 검색어가 전부 "대한의사협회 의료광고심의위원회"(=의협 공식 사이트 찾기)와
    "국가법령정보센터 의료법 제57조"(=법령 원문 찾기)였다. 순위는 6~9위인데
    클릭이 0이다. 우리를 찾는 사람이 아니기 때문이다.

    정작 우리가 답이 되는 검색어 — "정형외과 광고 문구", "피부과 의료광고 심의
    통과 사례" 같은 것 — 로는 뜨는 페이지가 아예 없었다. 이 스크립트가 그 페이지를
    만든다.

도어웨이 페이지가 되지 않기 위한 규칙:
    · 시안 100건 이상 쌓인 진료과만. 표본이 적으면 순위가 의미 없다.
    · 각 페이지는 **실측 집계**를 싣는다. 표현마다 등장 횟수와 심의번호 예시가 붙는다.
    · 해설은 그 진료과의 집계 결과를 근거로 쓴다. 진료과 이름만 바꾼 같은 글이면
      의미가 없다.
    · 자동 생성 페이지 수를 늘리는 것이 목적이 아니다. 진료과는 늘리지 말 것.

실행:
    python scripts/compute_dept_expressions.py
    python scripts/compute_dept_expressions.py --dept 정형외과
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))
load_dotenv(ROOT / ".env")

from top_expressions import (  # noqa: E402
    build_candidates, load_stopwords,
)

KST = timezone(timedelta(hours=9))
OUT_DIR = ROOT / "website" / "assets" / "data" / "dept"

# (표시명, URL 슬러그). 시안 100건 이상인 진료과만 둔다.
# 늘리기 전에 반드시 건수를 확인할 것 — 표본이 적으면 순위가 요동친다.
DEPTS = [
    ("정형외과", "orthopedics"),
    ("내과", "internal-medicine"),
    ("피부과", "dermatology"),
    ("성형외과", "plastic-surgery"),
    ("신경외과", "neurosurgery"),
    ("안과", "ophthalmology"),
    ("재활의학과", "rehabilitation"),
    ("산부인과", "obstetrics"),
    ("비뇨의학과", "urology"),
    ("이비인후과", "ent"),
    ("소아청소년과", "pediatrics"),
]

MIN_ADS = 100          # 이보다 적으면 페이지를 만들지 않는다
PAGE = 1000            # Supabase 한 번에 가져오는 행 수


def db():
    from supabase import create_client
    return create_client(os.environ["SUPABASE_URL"],
                         os.environ.get("SUPABASE_SERVICE_KEY")
                         or os.environ["SUPABASE_ANON_KEY"])


def fetch_dept_ads(sb, dept: str) -> list[dict]:
    """해당 진료과 이름이 OCR 텍스트에 들어 있는 시안 전부."""
    rows: list[dict] = []
    offset = 0
    while True:
        r = (sb.table("ads")
             .select("review_num, review_no_display, review_date, ocr_text")
             .ilike("ocr_text", f"%{dept}%")
             .range(offset, offset + PAGE - 1)
             .execute())
        batch = r.data or []
        rows.extend(batch)
        if len(batch) < PAGE:
            break
        offset += PAGE
    return rows


def summarize(dept: str, slug: str, ads: list[dict], stopwords: set[str]) -> dict | None:
    if len(ads) < MIN_ADS:
        print(f"  [건너뜀] {dept} — {len(ads)}건 (최소 {MIN_ADS}건)")
        return None

    # 진료과 이름 자체는 순위에서 뺀다. 전 시안에 들어 있어 1위가 뻔하다.
    drop = set(stopwords) | {dept, dept.replace("과", ""), "의원", "병원", "클리닉"}
    candidates = build_candidates(ads, drop, top_k=40)

    items = [{"expression": ng, "count": cnt, "examples": ex[:3]}
             for ng, cnt, ex in candidates[:25]]
    if len(items) < 10:
        print(f"  [건너뜀] {dept} — 표현 후보가 {len(items)}개뿐")
        return None

    dates = sorted(a["review_date"] for a in ads if a.get("review_date"))
    return {
        "dept": dept,
        "slug": slug,
        "ads_analyzed": len(ads),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "generated_at": datetime.now(KST).isoformat(),
        "expressions": items,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dept", help="특정 진료과만")
    args = ap.parse_args()

    sb = db()
    stopwords = load_stopwords()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    targets = [(d, s) for d, s in DEPTS if not args.dept or d == args.dept]
    made = 0
    for dept, slug in targets:
        ads = fetch_dept_ads(sb, dept)
        data = summarize(dept, slug, ads, stopwords)
        if not data:
            continue
        (OUT_DIR / f"{slug}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        top = ", ".join(x["expression"] for x in data["expressions"][:4])
        print(f"  {dept:8} {len(ads):>5,}건 → {len(data['expressions'])}개 표현  ({top})")
        made += 1

    print(f"\n{made}개 진료과 집계 완료 → {OUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
