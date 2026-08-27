"""이미 발행된 기사의 검색용 제목(<title>)을 다시 짓는다.

왜 있는가:
    구글 서치콘솔 기준 평균 게재순위 7.6(첫 페이지)인데 클릭률이 0.5%다.
    같은 순위면 보통 3~5% 나온다. 노출 7,930회에 클릭이 36회뿐이었다.
    원인은 제목에 사람들이 검색하는 말이 없어서다.

      "입원환자 다학제팀의료 제도화 필요성"
      "국립대병원 보건복지부 이관, 정책 변화 예상"

    병의원 마케터가 검색창에 칠 말이 하나도 없다. 의료 전문지 기사 제목을
    그대로 옮긴 꼴이다.

    기사 본문은 건드리지 않는다. <title> 과 og:title / twitter:title 만 바꾼다.
    이미 색인된 페이지라 재수집되면 검색결과의 제목이 바로 갈린다.

실행:
    python scripts/retitle_existing.py --dry-run   # 새 제목만 뽑아보기
    python scripts/retitle_existing.py             # 실제로 반영
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
NEWS_DIR = ROOT / "website" / "news"
INDEX_JSON = ROOT / "website" / "assets" / "data" / "news-index.json"

load_dotenv(ROOT / ".env")

import news_writer  # noqa: E402

SYSTEM = """당신은 병의원 마케팅 매체의 SEO 편집자입니다.
기사 내용은 그대로 두고, 구글 검색결과에 뜨는 제목만 다시 답니다."""

PROMPT = """아래 기사의 검색용 제목을 다시 지으세요.

[현재 제목]
{title}

[기사 요약]
{summary}

[기사 소제목들]
{headings}

[규칙 — 클릭률이 여기서 갈립니다]
독자는 **병원·의원의 마케팅 담당자**입니다. 진료하는 사람이 아니라 광고를 만드는 사람입니다.

1. **맨 앞 15자 안에 이 사람이 검색창에 칠 말을 넣으세요.**
   좋음: 의료광고 심의 / 병원 마케팅 / 비급여 광고 / 의료법 위반 / 불법 의료광고 /
         환자 유인 / 병원 홍보 / 심의 기준
   나쁨: 다학제팀의료 / 제도화 / 선례 / 이관 / 필요성 / 논의

2. 그 뒤에 **이 기사에만 있는 구체적 내용**을 붙이세요. 뭉뚱그리지 마세요.

3. **45자 이내.** 넘으면 구글이 잘라냅니다.

4. "~필요성", "~예상", "~논의", "~전망" 같은 흐지부지한 끝맺음 금지.
   무엇이 어떻게 되는지 쓰세요.

5. **키워드를 앞에 갖다 붙이지 마세요.** 이게 제일 흔한 실패입니다.
   "병원 마케팅, ○○○" 처럼 쉼표로 이어 붙이면 검색엔진이 키워드 스터핑으로 봅니다.
   키워드는 **문장 안에 자연스럽게 녹아** 있어야 합니다.

   나쁨: 병원 마케팅, 응급구조사 국시 지정대학 졸업생 제한
   나쁨: 병원 마케팅, 약국 명칭 사용 제한과 오남용 예방 강화
   좋음: 부당청구로 영업정지, 병원 광고에 미치는 영향

6. **기사에 없는 사실을 만들지 마세요.** 요약과 소제목 범위 안에서만 씁니다.

7. **억지로 엮지 마세요.** 기사가 광고·마케팅과 정말 상관없으면
   마케팅 키워드를 넣지 말고, 그 사안 자체를 독자가 검색할 만한 말로 쓰세요.
   그것도 마땅치 않으면 `"seo_title": ""` 로 비워서 답하세요. 그대로 두겠습니다.
   억지 제목은 안 넣느니만 못합니다.

예)
  전: 입원환자 다학제팀의료 제도화 필요성
  후: 병원 홍보에 '다학제 진료' 쓸 때 심의 주의점

  전: 의료기관 영업정지 판결, 부당청구 규제의 법적 선례
  후: 부당청구로 영업정지, 병원 광고에 미치는 영향

JSON으로만 답하세요:
{{"seo_title": "새 검색용 제목", "why": "왜 이 제목인지 한 문장"}}"""


def extract(html: str) -> dict:
    """기사 HTML 에서 제목·요약·소제목을 뽑는다."""
    title = re.search(r"<title>(.*?)</title>", html, re.S)
    desc = re.search(r'<meta name="description" content="([^"]*)"', html)
    heads = re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.S)
    clean = lambda s: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()
    return {
        "title": clean(title.group(1) if title else ""),
        "summary": clean(desc.group(1) if desc else ""),
        "headings": " / ".join(clean(h) for h in heads[:6]),
    }


def new_title(info: dict) -> str | None:
    try:
        r = news_writer._chat_json(
            news_writer.CHEAP_MODEL, SYSTEM,
            PROMPT.format(**info), max_tokens=300, temperature=0.6)
    except Exception as exc:
        print(f"    [실패] {type(exc).__name__}: {exc}")
        return None
    t = (r.get("seo_title") or "").strip()
    return t or None


def patch(html: str, old: str, new: str) -> str:
    """<title> 과 og/twitter 제목만 교체. 본문 h1 은 그대로 둔다.

    본문 제목까지 바꾸면 목록·RSS·구조화 데이터와 어긋난다. 검색결과에 보이는
    것만 갈아끼우는 것이 목적이다.
    """
    html = html.replace(f"<title>{old}</title>", f"<title>{new}</title>", 1)
    for attr in ('property="og:title"', 'name="twitter:title"'):
        html = re.sub(rf'(<meta {re.escape(attr)} content=")[^"]*(")',
                      lambda m: m.group(1) + new.replace("\\", "") + m.group(2),
                      html, count=1)
    return html


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    posts = json.loads(INDEX_JSON.read_text(encoding="utf-8"))["posts"]
    posts = sorted(posts, key=lambda p: p["date"])
    if args.limit:
        posts = posts[-args.limit:]

    changed = 0
    for i, p in enumerate(posts, 1):
        f = NEWS_DIR / f"{p['slug']}.html"
        if not f.exists():
            continue
        html = f.read_text(encoding="utf-8")
        info = extract(html)
        if not info["title"]:
            continue

        t = new_title(info)
        if not t or t == info["title"]:
            print(f"  [{i:>2}] 변경 없음 — {info['title'][:40]}")
            continue
        if len(t) > 60:
            print(f"  [{i:>2}] 너무 김({len(t)}자) — 건너뜀: {t[:50]}")
            continue

        print(f"  [{i:>2}] {info['title'][:44]}")
        print(f"       → {t}")
        changed += 1

        if not args.dry_run:
            f.write_text(patch(html, info["title"], t), encoding="utf-8")

    print(f"\n{len(posts)}편 중 {changed}편 제목 교체"
          f"{' (dry-run — 저장 안 함)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
