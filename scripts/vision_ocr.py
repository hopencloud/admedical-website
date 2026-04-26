"""
OpenAI Vision (gpt-4o-mini)을 이용한 의료광고 이미지 OCR.

EasyOCR/PaddleOCR보다 한국어 OCR 정확도가 훨씬 높음.
대신 비용 발생: low detail 약 $0.0004/장, high detail 약 $0.005/장.

사용:
    from vision_ocr import vision_ocr
    text = vision_ocr("/path/to/image.png", detail="high")
"""
import base64
import os
import time
from pathlib import Path

from openai import OpenAI, APIError, RateLimitError

_client = None

OCR_PROMPT = """이 이미지는 의료광고 시안입니다. 이미지에 보이는 모든 한글/영문/숫자 텍스트를 정확히 추출해주세요.

규칙:
- 시각적으로 보이는 텍스트만 그대로 옮겨 적으세요. 의미를 해석하거나 요약하지 마세요.
- 줄바꿈은 이미지의 자연스러운 구획에 따라 유지하세요.
- 작은 글씨(주의사항, 심의번호 등)도 빠짐없이 포함하세요.
- 표·표지·로고 안의 텍스트도 모두 포함하세요.
- 추출된 텍스트만 출력하세요. 설명/머리말/JSON 사용 금지."""


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


def vision_ocr(image_path: str | Path, detail: str = "high", max_retries: int = 3) -> str:
    """이미지에서 텍스트 추출. detail은 'low' (싸지만 작은 글씨 약함) 또는 'high'."""
    p = Path(image_path)
    if not p.exists():
        raise FileNotFoundError(p)

    # base64 인코딩
    raw = p.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    ext = p.suffix.lower().lstrip(".")
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/jpeg")

    client = _get_client()

    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": OCR_PROMPT},
                        {"type": "image_url", "image_url": {
                            "url": f"data:{mime};base64,{b64}",
                            "detail": detail,
                        }},
                    ],
                }],
                temperature=0.0,
                max_tokens=2000,
            )
            return (resp.choices[0].message.content or "").strip()
        except RateLimitError:
            time.sleep(2 ** attempt)
        except APIError as e:
            if attempt == max_retries - 1:
                print(f"[vision_ocr] APIError 최종 실패 ({p.name}): {e}")
                return ""
            time.sleep(2 ** attempt)
        except Exception as e:
            print(f"[vision_ocr] 예외 ({p.name}): {type(e).__name__}: {e}")
            return ""
    return ""


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")

    if len(sys.argv) < 2:
        print("사용: python vision_ocr.py <image_path> [low|high]")
        sys.exit(1)

    detail = sys.argv[2] if len(sys.argv) > 2 else "high"
    print(f"OCR 시작 (detail={detail}): {sys.argv[1]}")
    t0 = time.time()
    text = vision_ocr(sys.argv[1], detail=detail)
    print(f"완료 ({time.time()-t0:.1f}s, {len(text)}자)")
    print("=" * 60)
    print(text)
