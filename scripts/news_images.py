"""
기사 시각자료 생성 — AI 일러스트(PNG) + 데이터 도표(SVG).

두 종류를 쓰는 이유:
  · 일러스트: OpenAI 이미지 API. 사람 얼굴·글자 없는 추상 일러스트로 고정해
    오인 소지와 초상권 문제를 없앤다.
  · 도표: 우리 심의 DB의 실측값만 SVG로 그린다. AI가 수치를 만들지 않는다.
    SVG를 HTML에 인라인하므로 한글 폰트 파일이 필요 없다(페이지 폰트를 그대로 씀).

이미지 생성이 실패해도 파이프라인은 멈추지 않는다. 표지는 SVG 대체본으로 떨어진다.
"""
from __future__ import annotations

import base64
import os
import re
from pathlib import Path

# 브랜드 톤 고정 — 매일 나오는 그림의 결을 맞추고 정책 리스크를 줄인다.
STYLE_SUFFIX = (
    "flat vector editorial illustration, muted blue and slate color palette, "
    "clean minimal geometric shapes, soft subtle shadows, generous white space, "
    "professional and calm business tone. "
    "Strictly no text, no letters, no numbers, no logos, no watermarks, "
    "no human faces, no recognizable people, no brand marks, no medical gore."
)

# 2026-08-01 기준 이 프로젝트 키로 접근 가능한 이미지 모델.
# 계정 권한이 바뀌어도 죽지 않도록 순서대로 시도한다.
IMAGE_MODEL = os.getenv("NEWS_IMAGE_MODEL", "gpt-image-2")
FALLBACK_IMAGE_MODELS = ["chatgpt-image-latest", "gpt-image-1"]

# 원본은 장당 1.5MB 안팎이라 그대로 커밋하면 저장소가 금방 불어난다.
# 웹 표시에 충분한 크기로 줄이고 WebP 로 변환해 100~250KB 수준으로 맞춘다.
MAX_WIDTH = 1200
WEBP_QUALITY = 82


# ==========================================================
# AI 일러스트
# ==========================================================

def generate_illustration(prompt: str, out_path: Path, landscape: bool = True) -> bool:
    """
    OpenAI 이미지 API로 일러스트 1장 생성. 성공하면 True.
    모델·파라미터가 바뀌어도 자동화가 멈추지 않도록 단계적으로 폴백한다.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("  [경고] OPENAI_API_KEY 없음 — 일러스트 건너뜀")
        return False
    if os.getenv("NEWS_ILLUSTRATION", "1") != "1":
        return False

    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    full_prompt = f"{prompt.strip()}. {STYLE_SUFFIX}"
    primary_size = "1536x1024" if landscape else "1024x1024"

    attempts = [{"model": IMAGE_MODEL, "size": primary_size},
                {"model": IMAGE_MODEL, "size": "1024x1024"}]
    attempts += [{"model": m, "size": "1024x1024"} for m in FALLBACK_IMAGE_MODELS]

    for opts in attempts:
        try:
            resp = client.images.generate(
                model=opts["model"],
                prompt=full_prompt,
                size=opts["size"],
                n=1,
            )
            raw = _extract_image_bytes(resp.data[0])
            if not raw:
                continue

            out_path.parent.mkdir(parents=True, exist_ok=True)
            saved = _compress(raw, out_path)
            print(f"  일러스트 생성: {out_path.name} "
                  f"({opts['model']} {opts['size']}, {len(raw) // 1024}KB → {saved // 1024}KB)")
            return True
        except Exception as exc:
            print(f"  [정보] 이미지 생성 실패 ({opts['model']} {opts['size']}): {type(exc).__name__}: {exc}")
            continue

    return False


def _compress(raw: bytes, out_path: Path) -> int:
    """가로 폭을 줄이고 WebP 로 저장. Pillow가 없으면 원본을 그대로 쓴다."""
    try:
        import io
        from PIL import Image

        img = Image.open(io.BytesIO(raw)).convert("RGB")
        if img.width > MAX_WIDTH:
            ratio = MAX_WIDTH / img.width
            img = img.resize((MAX_WIDTH, round(img.height * ratio)), Image.LANCZOS)
        if out_path.suffix.lower() in (".jpg", ".jpeg"):
            img.save(out_path, "JPEG", quality=88, optimize=True, progressive=True)
        else:
            img.save(out_path, "WEBP", quality=WEBP_QUALITY, method=6)
        return out_path.stat().st_size
    except Exception as exc:
        print(f"  [정보] 이미지 압축 생략 ({type(exc).__name__}) — 원본 저장")
        out_path.write_bytes(raw)
        return len(raw)


def _extract_image_bytes(data) -> bytes | None:
    """b64_json 우선, 없으면 url 다운로드."""
    b64 = getattr(data, "b64_json", None)
    if b64:
        return base64.b64decode(b64)

    url = getattr(data, "url", None)
    if url:
        import urllib.request
        try:
            return urllib.request.urlopen(url, timeout=60).read()
        except Exception:
            return None
    return None


# ==========================================================
# 데이터 도표 (SVG)
# ==========================================================

def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render_trend_chart_svg(points: list[dict], title: str, caption: str = "") -> str:
    """
    최근 심의 통과 건수 추이 막대그래프.

    points: [{"date": "2026-07-30", "count": 80}, ...]  — statistics.json 실측값
    반환: HTML에 그대로 인라인할 <figure> 마크업
    """
    # 0건인 날은 제외한다. 주말·공휴일은 심의가 열리지 않고, 당일치는 아직 집계 전이라
    # 그대로 그리면 실제로 통과 건수가 급감한 것처럼 잘못 읽힌다.
    points = [p for p in points
              if isinstance(p.get("count"), (int, float)) and p["count"] > 0][-14:]
    if len(points) < 3:
        return ""

    W, H = 720, 300
    PAD_L, PAD_R, PAD_T, PAD_B = 44, 16, 28, 44
    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B

    counts = [p["count"] for p in points]
    top = max(counts)
    y_max = max(10, int(top * 1.15))

    n = len(points)
    slot = plot_w / n
    bar_w = min(34, slot * 0.62)

    parts: list[str] = []

    # 가로 눈금 4단계
    for i in range(5):
        val = round(y_max * i / 4)
        y = PAD_T + plot_h - (plot_h * i / 4)
        parts.append(
            f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" '
            f'stroke="#e2e8f0" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{PAD_L - 8}" y="{y + 4:.1f}" text-anchor="end" '
            f'font-size="11" fill="#94a3b8">{val}</text>'
        )

    # 막대 + 날짜 라벨
    label_every = 1 if n <= 8 else 2
    for i, p in enumerate(points):
        h = plot_h * (p["count"] / y_max) if y_max else 0
        x = PAD_L + slot * i + (slot - bar_w) / 2
        y = PAD_T + plot_h - h
        is_last = i == n - 1
        color = "#2563eb" if is_last else "#93c5fd"

        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{max(h, 1):.1f}" '
            f'rx="3" fill="{color}"><title>{_esc(p["date"])}: {p["count"]}건</title></rect>'
        )
        if is_last or n <= 10:
            parts.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{y - 6:.1f}" text-anchor="middle" '
                f'font-size="11" font-weight="700" fill="#1e40af">{p["count"]}</text>'
            )
        if i % label_every == 0 or is_last:
            mmdd = _esc(p["date"][5:].replace("-", "/"))
            parts.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{H - PAD_B + 18}" text-anchor="middle" '
                f'font-size="10" fill="#64748b">{mmdd}</text>'
            )

    # 축
    parts.append(
        f'<line x1="{PAD_L}" y1="{PAD_T + plot_h}" x2="{W - PAD_R}" y2="{PAD_T + plot_h}" '
        f'stroke="#cbd5e1" stroke-width="1.5"/>'
    )
    parts.append(
        f'<text x="{PAD_L}" y="16" font-size="12" font-weight="700" fill="#334155">{_esc(title)}</text>'
    )
    parts.append(
        f'<text x="{W - PAD_R}" y="16" text-anchor="end" font-size="10" fill="#94a3b8">'
        f'단위: 건 · 심의 진행일 기준</text>'
    )

    svg = (
        f'<svg viewBox="0 0 {W} {H}" width="100%" height="auto" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="{_esc(title)}">{"".join(parts)}</svg>'
    )

    cap = (f'<figcaption class="text-xs text-slate-500 mt-3 leading-relaxed">{_esc(caption)}</figcaption>'
           if caption else "")

    return (
        '<figure class="my-8 bg-white rounded-2xl border border-slate-200 p-5 shadow-soft">'
        f'{svg}{cap}'
        '</figure>'
    )


def render_checklist_card_svg(title: str, items: list[str]) -> str:
    """체크리스트를 카드형 SVG로. 일러스트 생성이 실패해도 시각자료를 하나 보장한다."""
    items = [i for i in items if i][:5]
    if not items:
        return ""

    W = 720
    row_h = 46
    H = 74 + row_h * len(items)

    parts = [
        f'<rect x="0" y="0" width="{W}" height="{H}" rx="16" fill="#f8fafc"/>',
        f'<rect x="0" y="0" width="{W}" height="52" rx="16" fill="#2563eb"/>',
        f'<rect x="0" y="36" width="{W}" height="16" fill="#2563eb"/>',
        f'<text x="24" y="33" font-size="15" font-weight="700" fill="#ffffff">{_esc(title)}</text>',
    ]

    for i, text in enumerate(items):
        y = 52 + 16 + row_h * i
        parts.append(f'<rect x="16" y="{y}" width="{W - 32}" height="{row_h - 8}" rx="10" fill="#ffffff"/>')
        parts.append(f'<circle cx="40" cy="{y + (row_h - 8) / 2:.0f}" r="10" fill="#dbeafe"/>')
        parts.append(
            f'<text x="40" y="{y + (row_h - 8) / 2 + 4:.0f}" text-anchor="middle" '
            f'font-size="11" font-weight="700" fill="#2563eb">{i + 1}</text>'
        )
        clipped = text if len(text) <= 46 else text[:45] + "…"
        parts.append(
            f'<text x="60" y="{y + (row_h - 8) / 2 + 5:.0f}" font-size="13" fill="#1e293b">{_esc(clipped)}</text>'
        )

    svg = (
        f'<svg viewBox="0 0 {W} {H}" width="100%" height="auto" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{_esc(title)}">'
        f'{"".join(parts)}</svg>'
    )
    return f'<figure class="my-8">{svg}</figure>'


def render_fallback_cover_svg(title: str, date_label: str) -> str:
    """AI 이미지가 실패했을 때 쓰는 표지 대체 카드."""
    W, H = 1200, 630
    safe = _esc(title[:38])
    tail = _esc(title[38:76]) if len(title) > 38 else ""

    return (
        f'<svg viewBox="0 0 {W} {H}" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="{_esc(title)}">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0%" stop-color="#1e3a8a"/><stop offset="100%" stop-color="#2563eb"/>'
        f'</linearGradient></defs>'
        f'<rect width="{W}" height="{H}" fill="url(#g)"/>'
        f'<circle cx="1040" cy="120" r="180" fill="#ffffff" opacity="0.06"/>'
        f'<circle cx="180" cy="540" r="220" fill="#ffffff" opacity="0.05"/>'
        f'<text x="80" y="180" font-size="22" font-weight="700" fill="#93c5fd">admedical 의료광고 인사이트</text>'
        f'<text x="80" y="300" font-size="52" font-weight="800" fill="#ffffff">{safe}</text>'
        f'<text x="80" y="368" font-size="52" font-weight="800" fill="#ffffff">{tail}</text>'
        f'<text x="80" y="540" font-size="24" fill="#bfdbfe">{_esc(date_label)}</text>'
        f'</svg>'
    )


def safe_filename(slug: str, suffix: str, ext: str = "webp") -> str:
    """표지는 jpg(카카오톡·페이스북 공유 호환), 본문 이미지는 webp(용량)."""
    base = re.sub(r"[^a-z0-9\-]", "", slug.lower())
    return f"{base}-{suffix}.{ext}"
