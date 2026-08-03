"""
OCR 이 끝난 시안 이미지 삭제 — 디스크 회수용.

왜 지워도 되는가:
    이 사이트는 시안 이미지를 절대 노출하지 않는다(저작권이 각 의료기관에 있음).
    이미지는 OCR 텍스트를 뽑기 위한 중간 재료일 뿐이고, 텍스트는 index.sqlite 와
    Supabase 양쪽에 남는다. 원본이 필요하면 심의번호로 admedical.org 에서 조회한다.

지우기 전에 확인하는 조건 (하나라도 어긋나면 남긴다):
    1. index.sqlite 에 해당 파일 행이 있고 ocr_done = 1
    2. OCR 텍스트가 비어 있지 않다 (실패분은 재시도 여지를 남긴다)
    3. 그 심의번호가 Supabase 로 이미 동기화되어 있다 (사이트에 실제로 반영됨)
    4. 심의일이 보관 기간(기본 7일)보다 오래됐다 — 갓 받은 건은 남긴다
    · 공지(is_notice=1)는 Supabase 로 보내지 않으므로 3번을 면제한다

기본은 미리보기다. 실제로 지우려면 --apply 를 붙여야 한다.

실행:
    python scripts/prune_images.py                    # 몇 개·몇 GB 지울지만 확인
    python scripts/prune_images.py --apply            # 실제 삭제
    python scripts/prune_images.py --retention-days 30 --apply
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "index.sqlite"
SAVE_DIR = Path(os.environ.get("ADMEDICAL_SAVE_DIR", str(ROOT / "기존데이터" / "수집")))
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".webp"}

# 동영상·음성 시안. OCR 대상이 아니라 DB 에 행조차 없고, 사이트에서도 쓰지 않는다.
# 용량은 이쪽이 압도적이라(한 개에 400MB 넘는 것도 있다) 따로 다룬다.
MEDIA_EXTS = {".mp4", ".mp3", ".mov", ".avi", ".wmv", ".m4a", ".wav"}

load_dotenv(ROOT / ".env")

# 260305-중-208759_1.JPG → 208759
NUM_RE = re.compile(r"중[-_](\d+)")


def log(msg: str) -> None:
    print(f"[prune] {msg}", flush=True)


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.1f}{unit}" if unit != "B" else f"{n:,}B"
        n /= 1024
    return f"{n:.1f}GB"


def review_num_of(path: Path) -> int | None:
    # macOS 는 한글 파일명을 분해형(NFD)으로 저장한다. 정규화하지 않으면
    # '중' 이 ㅈ+ㅜ+ㅇ 으로 들어와 정규식이 하나도 안 맞는다.
    stem = unicodedata.normalize("NFC", path.stem)
    m = NUM_RE.search(stem)
    return int(m.group(1)) if m else None


def load_db() -> dict[int, dict]:
    """심의번호별 OCR 상태. 페이지가 여러 장이면 전부 성공해야 지운다."""
    if not DB_PATH.exists():
        raise SystemExit("index.sqlite 가 없습니다.")

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT review_num,
               MIN(COALESCE(ocr_done, 0))                                   AS all_done,
               MIN(CASE WHEN ocr_text IS NOT NULL AND TRIM(ocr_text) != ''
                        THEN 1 ELSE 0 END)                                  AS all_text,
               MAX(COALESCE(is_notice, 0))                                  AS notice,
               MAX(review_date)                                             AS review_date
        FROM files GROUP BY review_num
    """).fetchall()
    conn.close()

    return {r[0]: {"done": r[1], "text": r[2], "notice": r[3], "date": r[4]} for r in rows}


def load_synced() -> set[int] | None:
    """Supabase 에 올라간 심의번호. 연결이 안 되면 None (그 경우 삭제를 중단한다)."""
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        client = create_client(url, key)
    except Exception as exc:
        log(f"Supabase 연결 실패: {exc}")
        return None

    synced: set[int] = set()
    page, size = 0, 1000
    while True:
        res = client.table("ads").select("review_num").range(page * size, page * size + size - 1).execute()
        rows = res.data or []
        synced.update(r["review_num"] for r in rows)
        if len(rows) < size:
            break
        page += 1
    return synced


def main() -> int:
    ap = argparse.ArgumentParser(description="OCR 완료된 시안 이미지 삭제")
    ap.add_argument("--apply", action="store_true",
                    help="실제로 삭제한다 (기본은 미리보기)")
    ap.add_argument("--retention-days", type=int, default=7,
                    help="이 기간 안에 심의된 건은 남긴다 (기본 7일)")
    ap.add_argument("--include-media", action="store_true",
                    help="동영상·음성 시안도 함께 삭제한다. 이들은 OCR 대상이 아니라 "
                         "DB 에 기록이 없고 사이트에서도 쓰지 않는다. 용량은 가장 크다.")
    args = ap.parse_args()

    if not SAVE_DIR.exists():
        log(f"수집 폴더가 없습니다: {SAVE_DIR}")
        return 0

    db = load_db()
    synced = load_synced()
    if synced is None:
        log("Supabase 확인이 불가능해 삭제를 중단합니다. "
            "동기화 여부를 확인하지 않고 지우면 데이터가 사라질 수 있습니다.")
        return 1

    log(f"대상 폴더: {SAVE_DIR}")
    log(f"DB 심의번호 {len(db):,}건 · Supabase 동기화 {len(synced):,}건 · "
        f"보관 기간 {args.retention_days}일")

    cutoff = date.today() - timedelta(days=args.retention_days)
    victims: list[tuple[Path, int]] = []
    media: list[tuple[Path, int]] = []
    kept = Counter()
    kept_bytes = Counter()

    for path in sorted(SAVE_DIR.rglob("*")):
        if not path.is_file():
            continue
        ext = path.suffix.lower()

        if ext in MEDIA_EXTS:
            # 동영상·음성은 OCR 파이프라인이 처리하지 못한다. 텍스트를 뽑을 방법이
            # 없으므로 보관해도 쓸 데가 없다. --include-media 면 조건 없이 지운다.
            # (수집기도 더 이상 내려받지 않는다 — collector.DOWNLOAD_IMAGES_ONLY)
            media.append((path, path.stat().st_size))
            continue

        if ext not in IMAGE_EXTS:
            continue

        size = path.stat().st_size
        num = review_num_of(path)

        if num is None:
            kept["파일명에서 심의번호를 못 읽음"] += 1
            kept_bytes["파일명에서 심의번호를 못 읽음"] += size
            continue

        info = db.get(num)
        if info is None:
            kept["DB에 기록 없음"] += 1
            kept_bytes["DB에 기록 없음"] += size
            continue
        if not info["done"]:
            kept["OCR 미완료"] += 1
            kept_bytes["OCR 미완료"] += size
            continue
        if not info["text"] and not info["notice"]:
            kept["OCR 텍스트 비어 있음 (재시도 여지)"] += 1
            kept_bytes["OCR 텍스트 비어 있음 (재시도 여지)"] += size
            continue
        if not info["notice"] and num not in synced:
            kept["Supabase 미동기화"] += 1
            kept_bytes["Supabase 미동기화"] += size
            continue

        try:
            reviewed = date.fromisoformat(info["date"]) if info["date"] else None
        except ValueError:
            reviewed = None
        if reviewed and reviewed > cutoff:
            kept[f"최근 {args.retention_days}일 이내"] += 1
            kept_bytes[f"최근 {args.retention_days}일 이내"] += size
            continue

        victims.append((path, size))

    if args.include_media:
        victims.extend(media)
    elif media:
        log(f"\n동영상·음성 {len(media):,}개 · {human(sum(s for _, s in media))} — "
            f"기본적으로 남깁니다. 함께 지우려면 --include-media 를 붙이세요.")

    total = sum(s for _, s in victims)
    log(f"\n삭제 대상: {len(victims):,}개 · {human(total)}")
    if kept:
        log("남기는 파일:")
        for reason, cnt in kept.most_common():
            log(f"   {reason}: {cnt:,}개 ({human(kept_bytes[reason])})")

    if not victims:
        log("\n지울 파일이 없습니다.")
        return 0

    if not args.apply:
        log("\n미리보기입니다. 실제로 지우려면 --apply 를 붙이세요.")
        for path, size in victims[:5]:
            log(f"   예: {path.name} ({human(size)})")
        return 0

    freed = 0
    failed = 0
    for path, size in victims:
        try:
            path.unlink()
            freed += size
        except Exception as exc:
            log(f"   삭제 실패 {path.name}: {exc}")
            failed += 1

    log(f"\n삭제 완료: {len(victims) - failed:,}개 · {human(freed)} 회수"
        + (f" · 실패 {failed}개" if failed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
