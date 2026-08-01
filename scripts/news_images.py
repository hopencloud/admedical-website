"""
기사 시각자료 — AI 일러스트 / 인포그래픽 SVG / 썸네일.

세 종류를 쓰는 이유가 다르다.

  · AI 일러스트 (gpt-image-2)
      기사마다 다른 구도·소재를 쓰도록 프롬프트를 기사 본문에서 뽑아 만든다.
      한글 텍스트는 이미지 모델이 자주 깨뜨리므로 이미지 안에는 넣지 않는다.

  · 인포그래픽 SVG (파이썬 렌더)
      한글이 정확해야 하는 도표는 우리가 직접 그린다. 기사 성격에 맞춰
      비교표 / 타임라인 / 절차도 / 체크리스트 / 실데이터 추이 중에서 고른다.
      심의 통과 추이 막대만 매번 붙던 문제를 이걸로 해결한다.

  · 썸네일 (Pillow)
      목록·메인·SNS 공유에 쓰는 1200x630 카드. 표지 이미지 위에 제목을
      정확한 한글로 얹는다. 디자인은 전 기사 동일.
"""
from __future__ import annotations

import base64
import io
import os
import re
import textwrap
from pathlib import Path

# ==========================================================
# 모델 / 스타일
# ==========================================================

IMAGE_MODEL = os.getenv("NEWS_IMAGE_MODEL", "gpt-image-2")
FALLBACK_IMAGE_MODELS = ["chatgpt-image-latest", "gpt-image-1"]

MAX_WIDTH = 1400
WEBP_QUALITY = 84
JPEG_QUALITY = 88

# 매일 나오는 그림의 결을 맞추는 공통 지시.
# 구도·소재는 기사마다 달라지고, 여기서는 톤과 금지사항만 고정한다.
HOUSE_STYLE = (
    "Editorial illustration for a Korean healthcare-marketing publication. "
    "Modern flat vector style with subtle depth: layered geometric shapes, soft long shadows, "
    "delicate 1px outlines, and a restrained grain texture. "
    "Palette strictly limited to deep navy (#1e3a8a), medium blue (#2563eb), sky blue (#93c5fd), "
    "pale blue-grey (#e2e8f0) and off-white (#f8fafc), with a single warm amber (#f59e0b) accent "
    "used sparingly for emphasis. "
    "Balanced composition with generous negative space, clear focal hierarchy, crisp edges. "
    "Professional, calm, trustworthy — not playful, not corporate-stocky."
)

# 이미지 모델이 한글을 자주 깨뜨린다. 글자는 전부 SVG·썸네일 쪽에서 넣는다.
HARD_CONSTRAINTS = (
    "Absolutely no text, no letters, no words, no numbers, no charts with axis labels, "
    "no logos, no watermarks, no signatures. "
    "No human faces, no identifiable people, no medical procedures, no blood, no injuries, "
    "no real brand marks, no national flags."
)


# ==========================================================
# 한글 폰트
# ==========================================================

FONT_CANDIDATES = [
    # GitHub Actions(ubuntu) — 워크플로우에서 fonts-nanum 설치
    ("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
     "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    ("/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf",
     "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf"),
    # macOS
    ("/System/Library/Fonts/AppleSDGothicNeo.ttc",
     "/System/Library/Fonts/AppleSDGothicNeo.ttc"),
    ("/System/Library/Fonts/Supplemental/AppleGothic.ttf",
     "/System/Library/Fonts/Supplemental/AppleGothic.ttf"),
]

_font_cache: dict[tuple[bool, int], object] = {}


def load_font(size: int, bold: bool = False):
    """한글 TTF 로드. 없으면 None (호출부에서 썸네일을 건너뛴다)."""
    key = (bold, size)
    if key in _font_cache:
        return _font_cache[key]

    from PIL import ImageFont

    for bold_path, regular_path in FONT_CANDIDATES:
        path = bold_path if bold else regular_path
        if not Path(path).exists():
            continue
        try:
            # ttc 는 굵기별 인덱스가 다르다 (AppleSDGothicNeo: 0 얇음 … 8 굵음)
            if path.endswith(".ttc"):
                font = ImageFont.truetype(path, size, index=6 if bold else 2)
            else:
                font = ImageFont.truetype(path, size)
            _font_cache[key] = font
            return font
        except Exception:
            continue

    print("  [경고] 한글 폰트를 찾지 못했습니다 — 썸네일 텍스트를 건너뜁니다.")
    _font_cache[key] = None
    return None


# ==========================================================
# AI 일러스트
# ==========================================================

def build_prompt(concept: str, detail: str = "") -> str:
    """기사에서 뽑은 구체 묘사 + 하우스 스타일 + 금지사항."""
    parts = [concept.strip().rstrip(".") + "."]
    if detail.strip():
        parts.append(detail.strip().rstrip(".") + ".")
    parts.append(HOUSE_STYLE)
    parts.append(HARD_CONSTRAINTS)
    return " ".join(parts)


def generate_illustration(concept: str, out_path: Path, detail: str = "",
                          landscape: bool = True) -> bool:
    """일러스트 1장 생성. 성공하면 True."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("  [경고] OPENAI_API_KEY 없음 — 일러스트 건너뜀")
        return False
    if os.getenv("NEWS_ILLUSTRATION", "1") != "1":
        return False

    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    prompt = build_prompt(concept, detail)
    primary = "1536x1024" if landscape else "1024x1024"

    attempts = [{"model": IMAGE_MODEL, "size": primary, "quality": "high"},
                {"model": IMAGE_MODEL, "size": primary},
                {"model": IMAGE_MODEL, "size": "1024x1024"}]
    attempts += [{"model": m, "size": "1024x1024"} for m in FALLBACK_IMAGE_MODELS]

    for opts in attempts:
        try:
            kwargs = {"model": opts["model"], "prompt": prompt, "size": opts["size"], "n": 1}
            if "quality" in opts:
                kwargs["quality"] = opts["quality"]

            resp = client.images.generate(**kwargs)
            raw = _extract_image_bytes(resp.data[0])
            if not raw:
                continue

            out_path.parent.mkdir(parents=True, exist_ok=True)
            saved = _compress(raw, out_path)
            print(f"  일러스트: {out_path.name} "
                  f"({opts['model']}/{opts['size']}{'/high' if 'quality' in opts else ''}, "
                  f"{len(raw) // 1024}KB → {saved // 1024}KB)")
            return True
        except Exception as exc:
            print(f"  [정보] 이미지 실패 ({opts['model']}/{opts['size']}): {type(exc).__name__}: {exc}")
            continue

    return False


def _extract_image_bytes(data) -> bytes | None:
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


def _compress(raw: bytes, out_path: Path) -> int:
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        if img.width > MAX_WIDTH:
            img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)),
                             Image.LANCZOS)
        if out_path.suffix.lower() in (".jpg", ".jpeg"):
            img.save(out_path, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
        else:
            img.save(out_path, "WEBP", quality=WEBP_QUALITY, method=6)
        return out_path.stat().st_size
    except Exception as exc:
        print(f"  [정보] 압축 생략 ({type(exc).__name__}) — 원본 저장")
        out_path.write_bytes(raw)
        return len(raw)


# ==========================================================
# 인포그래픽 SVG
# ==========================================================

def _esc(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _clip(text: str, n: int) -> str:
    text = str(text)
    return text if len(text) <= n else text[:n - 1] + "…"


def _wrap_tspans(text: str, x: int, y: int, width: int, size: int,
                 fill: str, weight: str = "400", line_gap: int = 6) -> tuple[str, int]:
    """SVG 안에서 한글 줄바꿈. (마크업, 사용한 높이) 반환."""
    per_line = max(6, int(width / (size * 0.62)))
    lines = textwrap.wrap(text, width=per_line) or [""]
    out = []
    for i, line in enumerate(lines):
        out.append(
            f'<text x="{x}" y="{y + i * (size + line_gap)}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}">{_esc(line)}</text>'
        )
    return "".join(out), len(lines) * (size + line_gap)


def _figure(svg: str, caption: str = "", plain: bool = False) -> str:
    cap = (f'<figcaption class="text-xs text-slate-500 mt-3 leading-relaxed">{_esc(caption)}</figcaption>'
           if caption else "")
    wrapper = "my-8" if plain else ("my-8 bg-white rounded-2xl border border-slate-200 p-5 shadow-soft")
    return f'<figure class="{wrapper}">{svg}{cap}</figure>'


def render_comparison(spec: dict) -> str:
    """좌/우 대비표. 금지 표현 vs 대안, 개정 전 vs 후 같은 데 쓴다."""
    rows = [r for r in spec.get("rows", []) if r.get("left") and r.get("right")][:5]
    if len(rows) < 2:
        return ""

    left_title = _clip(spec.get("left_title", "이전"), 20)
    right_title = _clip(spec.get("right_title", "이후"), 20)

    W, pad, head_h, row_h = 720, 16, 46, 62
    H = pad * 2 + head_h + row_h * len(rows)
    col_w = (W - pad * 3) / 2

    p = [f'<rect width="{W}" height="{H}" rx="14" fill="#f8fafc"/>']

    for i, (title, color, bg) in enumerate([(left_title, "#991b1b", "#fee2e2"),
                                            (right_title, "#065f46", "#d1fae5")]):
        x = pad + i * (col_w + pad)
        p.append(f'<rect x="{x}" y="{pad}" width="{col_w}" height="{head_h - 8}" rx="9" fill="{bg}"/>')
        p.append(f'<text x="{x + col_w / 2}" y="{pad + 25}" text-anchor="middle" font-size="14" '
                 f'font-weight="700" fill="{color}">{_esc(title)}</text>')

    for r, row in enumerate(rows):
        y = pad + head_h + r * row_h
        for i, (val, color) in enumerate([(row["left"], "#7f1d1d"), (row["right"], "#064e3b")]):
            x = pad + i * (col_w + pad)
            p.append(f'<rect x="{x}" y="{y}" width="{col_w}" height="{row_h - 10}" rx="9" '
                     f'fill="#ffffff" stroke="#e2e8f0"/>')
            markup, _ = _wrap_tspans(_clip(val, 44), int(x + 14), int(y + 22),
                                     int(col_w - 28), 13, color, "600", 4)
            p.append(markup)

    svg = (f'<svg viewBox="0 0 {W} {H}" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg" '
           f'role="img" aria-label="{_esc(spec.get("alt") or f"{left_title} 대 {right_title} 비교표")}">'
           f'{"".join(p)}</svg>')
    return _figure(svg, spec.get("caption", ""), plain=True)


def render_timeline(spec: dict) -> str:
    """시행 일정·단계별 진행 같은 시간축."""
    steps = [s for s in spec.get("steps", []) if s.get("label")][:5]
    if len(steps) < 2:
        return ""

    W, H = 720, 210
    pad = 40
    span = (W - pad * 2) / max(1, len(steps) - 1)
    y = 78

    p = [f'<line x1="{pad}" y1="{y}" x2="{W - pad}" y2="{y}" stroke="#cbd5e1" stroke-width="3"/>']

    for i, step in enumerate(steps):
        x = pad + span * i
        active = i == len(steps) - 1
        p.append(f'<circle cx="{x:.0f}" cy="{y}" r="{11 if active else 9}" '
                 f'fill="{"#2563eb" if active else "#93c5fd"}" stroke="#ffffff" stroke-width="3"/>')
        if step.get("when"):
            p.append(f'<text x="{x:.0f}" y="{y - 26}" text-anchor="middle" font-size="12" '
                     f'font-weight="700" fill="#1e40af">{_esc(_clip(step["when"], 12))}</text>')
        markup, _ = _wrap_tspans(_clip(step["label"], 26), 0, y + 32, int(span * 0.95), 12,
                                 "#334155", "500", 4)
        markup = markup.replace('x="0"', f'x="{x:.0f}"').replace("<text ", '<text text-anchor="middle" ')
        p.append(markup)

    svg = (f'<svg viewBox="0 0 {W} {H}" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg" '
           f'role="img" aria-label="{_esc(spec.get("alt") or "일정 타임라인")}">{"".join(p)}</svg>')
    return _figure(svg, spec.get("caption", ""))


def render_process(spec: dict) -> str:
    """절차 흐름도. 심의 신청 단계 같은 데 쓴다."""
    steps = [s for s in spec.get("steps", []) if s.get("label")][:5]
    if len(steps) < 2:
        return ""

    W = 720
    box_h, gap = 68, 14
    H = 20 + (box_h + gap) * len(steps)

    p = [f'<rect width="{W}" height="{H}" rx="14" fill="#f8fafc"/>']
    for i, step in enumerate(steps):
        y = 10 + (box_h + gap) * i
        p.append(f'<rect x="16" y="{y}" width="{W - 32}" height="{box_h}" rx="11" '
                 f'fill="#ffffff" stroke="#e2e8f0"/>')
        p.append(f'<rect x="16" y="{y}" width="6" height="{box_h}" rx="3" fill="#2563eb"/>')
        p.append(f'<circle cx="52" cy="{y + box_h / 2:.0f}" r="15" fill="#dbeafe"/>')
        p.append(f'<text x="52" y="{y + box_h / 2 + 5:.0f}" text-anchor="middle" font-size="14" '
                 f'font-weight="700" fill="#2563eb">{i + 1}</text>')
        markup, _ = _wrap_tspans(_clip(step["label"], 50), 80, int(y + 27), W - 110, 14,
                                 "#1e293b", "600", 5)
        p.append(markup)
        if step.get("note"):
            p.append(f'<text x="80" y="{y + 50}" font-size="11.5" fill="#64748b">'
                     f'{_esc(_clip(step["note"], 54))}</text>')
        if i < len(steps) - 1:
            p.append(f'<path d="M {W / 2:.0f} {y + box_h + 2} l 0 8 m -5 -5 l 5 5 l 5 -5" '
                     f'stroke="#cbd5e1" stroke-width="2" fill="none"/>')

    svg = (f'<svg viewBox="0 0 {W} {H}" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg" '
           f'role="img" aria-label="{_esc(spec.get("alt") or "절차 흐름도")}">{"".join(p)}</svg>')
    return _figure(svg, spec.get("caption", ""), plain=True)


def render_checklist(spec: dict) -> str:
    items = [i for i in spec.get("items", []) if i][:5]
    if len(items) < 2:
        return ""

    title = _clip(spec.get("title", "실무 체크리스트"), 28)
    W, row_h = 720, 50
    H = 76 + row_h * len(items)

    p = [f'<rect width="{W}" height="{H}" rx="14" fill="#f8fafc"/>',
         f'<path d="M0 14 a14 14 0 0 1 14 -14 h{W - 28} a14 14 0 0 1 14 14 v40 h-{W} z" fill="#2563eb"/>',
         f'<text x="24" y="35" font-size="15" font-weight="700" fill="#ffffff">{_esc(title)}</text>']

    for i, text in enumerate(items):
        y = 68 + row_h * i
        p.append(f'<rect x="16" y="{y}" width="{W - 32}" height="{row_h - 9}" rx="10" fill="#ffffff"/>')
        p.append(f'<circle cx="42" cy="{y + (row_h - 9) / 2:.0f}" r="10" fill="#dbeafe"/>')
        p.append(f'<path d="M37 {y + (row_h - 9) / 2:.0f} l4 4 l7 -8" stroke="#2563eb" '
                 f'stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')
        p.append(f'<text x="64" y="{y + (row_h - 9) / 2 + 5:.0f}" font-size="13.5" fill="#1e293b">'
                 f'{_esc(_clip(text, 48))}</text>')

    svg = (f'<svg viewBox="0 0 {W} {H}" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg" '
           f'role="img" aria-label="{_esc(spec.get("alt") or title)}">{"".join(p)}</svg>')
    return _figure(svg, spec.get("caption", ""), plain=True)


def render_stat_trend(points: list[dict], spec: dict) -> str:
    """우리 심의 DB 실측 추이. 수치는 AI가 만들지 않는다."""
    points = [p for p in points
              if isinstance(p.get("count"), (int, float)) and p["count"] > 0][-14:]
    if len(points) < 3:
        return ""

    W, H = 720, 300
    PAD_L, PAD_R, PAD_T, PAD_B = 46, 16, 30, 44
    plot_w, plot_h = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    y_max = max(10, int(max(p["count"] for p in points) * 1.15))
    n = len(points)
    slot = plot_w / n
    bar_w = min(34, slot * 0.6)

    p = []
    for i in range(5):
        val = round(y_max * i / 4)
        y = PAD_T + plot_h - plot_h * i / 4
        p.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" '
                 f'stroke="#e2e8f0" stroke-width="1"/>')
        p.append(f'<text x="{PAD_L - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="11" '
                 f'fill="#94a3b8">{val}</text>')

    for i, pt in enumerate(points):
        h = plot_h * pt["count"] / y_max
        x = PAD_L + slot * i + (slot - bar_w) / 2
        y = PAD_T + plot_h - h
        last = i == n - 1
        p.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{max(h, 1):.1f}" rx="3" '
                 f'fill="{"#2563eb" if last else "#93c5fd"}">'
                 f'<title>{_esc(pt["date"])}: {pt["count"]}건</title></rect>')
        if last or n <= 10:
            p.append(f'<text x="{x + bar_w / 2:.1f}" y="{y - 6:.1f}" text-anchor="middle" '
                     f'font-size="11" font-weight="700" fill="#1e40af">{pt["count"]}</text>')
        if i % (1 if n <= 8 else 2) == 0 or last:
            p.append(f'<text x="{x + bar_w / 2:.1f}" y="{H - PAD_B + 18}" text-anchor="middle" '
                     f'font-size="10" fill="#64748b">{_esc(pt["date"][5:].replace("-", "/"))}</text>')

    title = spec.get("title") or "일자별 의료광고 심의 통과 건수"
    p.append(f'<line x1="{PAD_L}" y1="{PAD_T + plot_h}" x2="{W - PAD_R}" y2="{PAD_T + plot_h}" '
             f'stroke="#cbd5e1" stroke-width="1.5"/>')
    p.append(f'<text x="{PAD_L}" y="17" font-size="12" font-weight="700" fill="#334155">'
             f'{_esc(title)}</text>')
    p.append(f'<text x="{W - PAD_R}" y="17" text-anchor="end" font-size="10" fill="#94a3b8">'
             f'단위: 건 · 심의 진행일 기준</text>')

    svg = (f'<svg viewBox="0 0 {W} {H}" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg" '
           f'role="img" aria-label="{_esc(spec.get("alt") or title)}">{"".join(p)}</svg>')
    return _figure(svg, spec.get("caption", ""))


def render_infographic(spec: dict, stat_points: list[dict] | None = None) -> str:
    """AI가 고른 도식 유형에 맞춰 렌더. 유형이 안 맞으면 빈 문자열."""
    if not isinstance(spec, dict):
        return ""
    kind = (spec.get("type") or "").strip()
    try:
        if kind == "comparison":
            return render_comparison(spec)
        if kind == "timeline":
            return render_timeline(spec)
        if kind == "process":
            return render_process(spec)
        if kind == "checklist":
            return render_checklist(spec)
        if kind == "stat_trend":
            return render_stat_trend(stat_points or [], spec)
    except Exception as exc:
        print(f"  [정보] 인포그래픽({kind}) 렌더 실패: {type(exc).__name__}: {exc}")
    return ""


def infographic_text(spec: dict) -> str:
    """수치 검증에 함께 넣기 위해 도식 안의 문자열을 모은다."""
    if not isinstance(spec, dict):
        return ""
    chunks = [spec.get("title", ""), spec.get("caption", ""), spec.get("alt", ""),
              spec.get("left_title", ""), spec.get("right_title", "")]
    for row in spec.get("rows", []) or []:
        chunks += [row.get("left", ""), row.get("right", "")]
    for step in spec.get("steps", []) or []:
        chunks += [step.get("label", ""), step.get("when", ""), step.get("note", "")]
    chunks += list(spec.get("items", []) or [])
    return " ".join(c for c in chunks if c)


# ==========================================================
# 썸네일
# ==========================================================

THUMB_W, THUMB_H = 1200, 630


def render_thumbnail(title: str, date_label: str, out_path: Path,
                     cover_path: Path | None = None, tag: str = "의료광고 인사이트") -> bool:
    """
    목록·메인·SNS 공유용 카드. 전 기사 동일한 레이아웃을 쓴다.
    표지 이미지가 있으면 배경으로 깔고 어둡게 덮은 뒤 제목을 얹는다.
    """
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError:
        print("  [경고] Pillow 없음 — 썸네일 건너뜀")
        return False

    f_title = load_font(58, bold=True)
    if f_title is None:
        return False
    f_tag = load_font(24, bold=True)
    f_meta = load_font(22, bold=False)

    canvas = Image.new("RGB", (THUMB_W, THUMB_H), "#1e3a8a")

    # 배경: 표지 이미지를 채우고 블러 + 어둡게
    if cover_path and cover_path.exists():
        try:
            bg = Image.open(cover_path).convert("RGB")
            ratio = max(THUMB_W / bg.width, THUMB_H / bg.height)
            bg = bg.resize((round(bg.width * ratio), round(bg.height * ratio)), Image.LANCZOS)
            left = (bg.width - THUMB_W) // 2
            top = (bg.height - THUMB_H) // 2
            bg = bg.crop((left, top, left + THUMB_W, top + THUMB_H))
            canvas.paste(bg.filter(ImageFilter.GaussianBlur(2)), (0, 0))
        except Exception:
            pass

    # 좌측이 짙어지는 그라디언트 — 제목 가독성 확보
    overlay = Image.new("RGBA", (THUMB_W, THUMB_H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for x in range(THUMB_W):
        alpha = int(232 - 150 * (x / THUMB_W) ** 1.5)
        od.line([(x, 0), (x, THUMB_H)], fill=(15, 23, 42, max(58, alpha)))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")

    d = ImageDraw.Draw(canvas)

    # 좌측 액센트 바 + 라벨
    d.rectangle([0, 0, 10, THUMB_H], fill="#2563eb")
    if f_tag:
        d.rectangle([64, 62, 64 + 14, 62 + 30], fill="#f59e0b")
        d.text((90, 62), tag, font=f_tag, fill="#bfdbfe")

    # 제목 — 폭에 맞춰 줄바꿈, 최대 4줄
    lines: list[str] = []
    for candidate in textwrap.wrap(title, width=17):
        if len(lines) == 4:
            lines[-1] = lines[-1][:-1] + "…"
            break
        lines.append(candidate)

    y = THUMB_H - 150 - len(lines) * 74
    for line in lines:
        d.text((64, y), line, font=f_title, fill="#ffffff")
        y += 74

    # 하단 메타
    if f_meta:
        d.line([(64, THUMB_H - 108), (200, THUMB_H - 108)], fill="#2563eb", width=4)
        d.text((64, THUMB_H - 88), f"{date_label}  ·  admedical.co.kr",
               font=f_meta, fill="#cbd5e1")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=90, optimize=True, progressive=True)
    print(f"  썸네일: {out_path.name} ({out_path.stat().st_size // 1024}KB)")
    return True


# ==========================================================

def safe_filename(slug: str, suffix: str, ext: str = "webp") -> str:
    base = re.sub(r"[^a-z0-9\-]", "", slug.lower())
    return f"{base}-{suffix}.{ext}"
