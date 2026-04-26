"""
기존 OCR(EasyOCR/PaddleOCR) vs OpenAI Vision OCR 품질 비교.

~/Desktop/admedical_ads/ 의 이미지 3장을 골라:
  1. 기존 OCR (index.sqlite의 ocr_text)
  2. OpenAI Vision (low detail, 싸지만 작은 글씨 약함)
  3. OpenAI Vision (high detail, 비쌈, 작은 글씨도 잡음)

세 가지를 나란히 보여준다.
"""
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from vision_ocr import vision_ocr  # noqa: E402

load_dotenv(Path(__file__).parent.parent / ".env")

DB_PATH = Path(__file__).parent.parent / "index.sqlite"
ADS_DIR = Path.home() / "Desktop" / "admedical_ads"


SAMPLES = [
    "260324-중-209919.png",  # 비뇨의학과 — 깔끔한 광고
    "260324-중-209929.png",  # 다른 카테고리
    "260324-중-209940.png",  # 다른 카테고리
]


def get_existing_ocr(filename: str) -> str:
    if not DB_PATH.exists():
        return "(DB 없음)"
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT ocr_text FROM files WHERE filename = ?", (filename,)).fetchone()
    conn.close()
    return row[0] if row else "(DB에 없음)"


def main() -> None:
    for fn in SAMPLES:
        path = ADS_DIR / fn
        if not path.exists():
            # 폴더에 없으면 다른 .jpg/.jpeg 도 시도
            alts = list(ADS_DIR.glob(f"{Path(fn).stem}.*"))
            if alts:
                path = alts[0]
            else:
                print(f"[건너뜀] 이미지 없음: {fn}")
                continue

        print("\n" + "=" * 78)
        print(f"파일: {path.name}")
        print("=" * 78)

        # 1. 기존 OCR
        existing = get_existing_ocr(path.name)
        print("\n--- (1) 기존 OCR (DB에 저장된 것) ---")
        print(existing[:600])
        print(f"[{len(existing)}자]")

        # 2. OpenAI Vision low
        print("\n--- (2) OpenAI Vision — low detail (~$0.0004/장) ---")
        try:
            low = vision_ocr(path, detail="low")
            print(low[:600])
            print(f"[{len(low)}자]")
        except Exception as e:
            print(f"[실패] {e}")

        # 3. OpenAI Vision high
        print("\n--- (3) OpenAI Vision — high detail (~$0.005/장) ---")
        try:
            high = vision_ocr(path, detail="high")
            print(high[:600])
            print(f"[{len(high)}자]")
        except Exception as e:
            print(f"[실패] {e}")


if __name__ == "__main__":
    main()
