"""
~/Desktop/admedical_ads/ 의 신규 이미지를 OCR해 index.sqlite에 추가.

기존 schema 그대로 유지:
  files(filename PK, review_date, review_num, page, mtime, size, is_notice, ocr_text, ocr_done)

처리 규칙:
  - 파일명 패턴: YYMMDD-중-NNNNNN[_P].(png|jpg|jpeg|gif)
  - 이미 DB에 있는 filename은 건너뜀
  - EasyOCR(한국어+영어)로 텍스트 추출
  - 첫 200자에 "직권승인" 마커 있으면 is_notice=1

실행:
    source venv/bin/activate
    python scripts/indexer.py            # 모든 신규 파일 처리
    python scripts/indexer.py --limit 10 # 10개만 (테스트)
"""
from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "index.sqlite"
SAVE_DIR = Path.home() / "Desktop" / "admedical_ads"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif"}
FILENAME_PATTERN = re.compile(r"^(\d{6})-중-(\d+)(?:_(\d+))?$")
NOTICE_MARKERS = ("직권승인 안내", "[직권승인", "직권 승인 안내")


def setup_logging() -> logging.Logger:
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = log_dir / f"indexer_{ts}.log"

    logger = logging.getLogger("indexer")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", datefmt="%H:%M:%S")
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


def parse_filename(filename: str) -> dict | None:
    stem = Path(filename).stem
    m = FILENAME_PATTERN.match(stem)
    if not m:
        return None
    yymmdd, review_num, page = m.groups()
    try:
        year = 2000 + int(yymmdd[:2])
        month = int(yymmdd[2:4])
        day = int(yymmdd[4:6])
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return None
        review_date = f"{year:04d}-{month:02d}-{day:02d}"
    except ValueError:
        return None
    return {
        "review_date": review_date,
        "review_num": int(review_num),
        "page": int(page) if page else 0,
    }


def is_notice_text(text: str) -> bool:
    head = text[:200]
    return any(marker in head for marker in NOTICE_MARKERS)


def init_db_if_missing(conn: sqlite3.Connection) -> None:
    """기존 schema와 호환되는 files 테이블 보장."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS files (
            filename TEXT PRIMARY KEY,
            review_date TEXT,
            review_num INTEGER,
            page INTEGER,
            mtime REAL,
            size INTEGER,
            is_notice INTEGER DEFAULT 0,
            ocr_text TEXT,
            ocr_done INTEGER DEFAULT 0
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_num ON files(review_num DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_date ON files(review_date)")
    conn.commit()


def load_done_filenames(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT filename FROM files WHERE ocr_done = 1")}


def scan_pending(done: set[str]) -> list[Path]:
    if not SAVE_DIR.exists():
        return []
    files: list[Path] = []
    for p in SAVE_DIR.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        if p.name in done:
            continue
        if not parse_filename(p.name):
            continue
        files.append(p)
    # 최신 review_num 우선 처리 (사용자가 최근 데이터를 빨리 볼 수 있도록)
    files.sort(key=lambda p: parse_filename(p.name)["review_num"], reverse=True)
    return files


_ocr_singleton = None


def get_ocr(log: logging.Logger):
    global _ocr_singleton
    if _ocr_singleton is None:
        log.info("EasyOCR 모델 로딩 시작 (최초 1~2분, 모델 다운로드 포함)...")
        t0 = time.time()
        import easyocr
        # gpu=False: CPU 모드. M1/M2 Mac에서도 안정적.
        _ocr_singleton = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
        log.info("EasyOCR 모델 로딩 완료 (%.1fs)", time.time() - t0)
    return _ocr_singleton


def ocr_image(path: Path, log: logging.Logger) -> str:
    ocr = get_ocr(log)
    result = ocr.readtext(str(path), detail=1, paragraph=False)
    # result는 [(bbox, text, confidence), ...] 형태
    lines: list[str] = []
    for item in result:
        if not item or len(item) < 2:
            continue
        text = str(item[1]).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="처리할 최대 파일 수 (테스트용)")
    args = parser.parse_args()

    log = setup_logging()

    if not DB_PATH.exists():
        log.error("index.sqlite를 찾을 수 없음: %s", DB_PATH)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    init_db_if_missing(conn)

    done = load_done_filenames(conn)
    pending = scan_pending(done)
    log.info("DB 완료 %d개, 신규 대상 %d개", len(done), len(pending))

    if args.limit:
        pending = pending[: args.limit]
        log.info("--limit %d 적용 → %d개만 처리", args.limit, len(pending))

    if not pending:
        log.info("처리할 신규 파일 없음. 종료.")
        return

    success = 0
    failures: list[str] = []
    for i, path in enumerate(pending, 1):
        meta = parse_filename(path.name)
        if not meta:
            continue
        try:
            text = ocr_image(path, log)
        except Exception as e:
            log.warning("[%d/%d] OCR 실패 %s: %s", i, len(pending), path.name, e)
            failures.append(path.name)
            continue
        notice = 1 if is_notice_text(text) else 0
        try:
            stat = path.stat()
            conn.execute(
                """
                INSERT OR REPLACE INTO files
                    (filename, review_date, review_num, page, mtime, size, is_notice, ocr_text, ocr_done)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    path.name,
                    meta["review_date"],
                    meta["review_num"],
                    meta["page"],
                    stat.st_mtime,
                    stat.st_size,
                    notice,
                    text,
                ),
            )
            conn.commit()
            success += 1
            log.info("[%d/%d] OK %s (review_num=%d, %d자)",
                     i, len(pending), path.name, meta["review_num"], len(text))
        except Exception as e:
            log.warning("[%d/%d] DB insert 실패 %s: %s", i, len(pending), path.name, e)
            failures.append(path.name)

    conn.close()
    log.info("[완료] 성공 %d / 실패 %d", success, len(failures))
    if failures:
        log.info("[실패 파일 샘플] %s", failures[:5])


if __name__ == "__main__":
    main()
