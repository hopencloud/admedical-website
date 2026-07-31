"""
공통 헤더를 각 페이지에 정적 HTML로 심는다.

왜 필요한가:
    헤더를 site.js 가 런타임에 주입하면, 자바스크립트를 실행하지 않는 크롤러에게는
    내부 링크가 존재하지 않는 것과 같다. 특히 네이버 Yeti 는 JS 렌더링이 제한적이라
    가이드 7개 페이지로 가는 링크를 전혀 발견하지 못하고 있었다.
    (실측: 메인페이지 정적 내부 링크가 푸터 6개뿐)

동작:
    site.js 의 HEADER_HTML 을 그대로 읽어와 각 페이지의
    <div id="site-header"></div> 자리 또는 기존 정적 헤더를 교체한다.
    헤더 문구를 바꿀 때는 site.js 만 고치고 이 스크립트를 다시 돌리면 된다.

실행:
    python scripts/build_header.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
WEB = ROOT / "website"
SITE_JS = WEB / "assets" / "js" / "site.js"

SKIP_NAMES = {
    "naver48bf0a622da5771affd07f27cfa1ad53.html",
    "naver536ba2b5323508822dfc8329784571b2.html",
}
SKIP_DIRS = {"admin"}

BEGIN = "<!-- site-header:begin (scripts/build_header.py 가 생성 — 직접 수정하지 마세요) -->"
END = "<!-- site-header:end -->"


def extract_header_html() -> str:
    """site.js 의 HEADER_HTML 템플릿 리터럴을 꺼낸다."""
    js = SITE_JS.read_text(encoding="utf-8")
    match = re.search(r"const HEADER_HTML = `(.*?)`;", js, flags=re.S)
    if not match:
        raise RuntimeError("site.js 에서 HEADER_HTML 을 찾지 못했습니다.")
    return match.group(1).strip()


def build_block(header_html: str) -> str:
    return f"{BEGIN}\n{header_html}\n{END}"


def apply(path: Path, block: str) -> bool:
    text = path.read_text(encoding="utf-8")

    # 이미 심어둔 블록이 있으면 통째로 교체
    if BEGIN in text and END in text:
        new = re.sub(
            re.escape(BEGIN) + r".*?" + re.escape(END),
            lambda _: block,
            text,
            flags=re.S,
        )
    elif '<div id="site-header"></div>' in text:
        new = text.replace('<div id="site-header"></div>', block, 1)
    else:
        return False

    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def main() -> None:
    block = build_block(extract_header_html())

    changed = 0
    for path in sorted(WEB.rglob("*.html")):
        if path.name in SKIP_NAMES or SKIP_DIRS & set(path.parts):
            continue
        if apply(path, block):
            print(f"  {path.relative_to(WEB)}")
            changed += 1

    print(f"\n헤더 반영: {changed}개 페이지")


if __name__ == "__main__":
    main()
