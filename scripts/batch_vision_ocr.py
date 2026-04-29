"""
폴더의 모든 이미지를 OpenAI Vision으로 OCR 후 index.sqlite에 저장.

특징:
  - 재시작 안전: vision_ocr_done=1인 파일은 건너뜀
  - 병렬 처리: 기본 5 워커 (OpenAI rate limit 안전 범위)
  - 배치 커밋: 매 10건마다 SQLite commit
  - 진행률 표시: tqdm
  - 비용/시간 추정: 시작 시 표시

스키마:
  files(filename PK, review_date, review_num, page, ocr_text, ocr_done, vision_ocr_done, ...)

실행:
    source venv/bin/activate
    python scripts/batch_vision_ocr.py                 # 기본: 기존데이터/수집/
    python scripts/batch_vision_ocr.py --src 다른경로
    python scripts/batch_vision_ocr.py --limit 5       # 5장만 (테스트)
    python scripts/batch_vision_ocr.py --workers 3     # 동시 처리 워커 수
"""
from __future__ import annotations
import argparse
import logging
import os
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))
from vision_ocr import vision_ocr  # noqa: E402

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DB_PATH = ROOT / "index.sqlite"
DEFAULT_SRC = ROOT / "기존데이터" / "수집"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif"}
FILENAME_PATTERN = re.compile(r"^(\d{6})-중-(\d+)(?:_(\d+))?$")
NOTICE_MARKERS = ("직권승인 안내", "[직권승인", "직권 승인 안내")


def setup_logging() -> logging.Logger:
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = log_dir / f"vision_ocr_{ts}.log"
    logger = logging.getLogger("vision_ocr_batch")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stderr)
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
        return {
            "review_date": f"{year:04d}-{month:02d}-{day:02d}",
            "review_num": int(review_num),
            "page": int(page) if page else 0,
        }
    except ValueError:
        return None


def is_notice_text(text: str) -> bool:
    head = text[:200]
    return any(marker in head for marker in NOTICE_MARKERS)


def scan_images(src_dir: Path) -> list[Path]:
    files: list[Path] = []
    for p in src_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        if not parse_filename(p.name):
            continue
        files.append(p)
    return files


def load_done_filenames(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute(
        "SELECT filename FROM files WHERE vision_ocr_done = 1"
    )}


# Thread-safe DB writer
_db_lock = threading.Lock()


def process_one(path: Path, log: logging.Logger) -> tuple[Path, dict | None, str | None, str | None]:
    """OCR 1장. (path, meta, text, error) 반환."""
    meta = parse_filename(path.name)
    if not meta:
        return (path, None, None, "filename_parse_error")
    try:
        text = vision_ocr(path, detail="high")
        return (path, meta, text, None)
    except Exception as e:
        return (path, meta, None, f"{type(e).__name__}: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()

    log = setup_logging()

    if not DB_PATH.exists():
        log.error(f"index.sqlite 없음: {DB_PATH}")
        sys.exit(1)
    if not args.src.exists():
        log.error(f"이미지 폴더 없음: {args.src}")
        sys.exit(1)

    # 기존 vision_ocr_done 확인
    conn = sqlite3.connect(DB_PATH, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    done = load_done_filenames(conn)
    log.info(f"DB에 이미 vision_ocr_done=1인 파일: {len(done):,}개")

    log.info(f"이미지 스캔 시작: {args.src}")
    all_images = scan_images(args.src)
    log.info(f"발견된 이미지: {len(all_images):,}개")

    pending = [p for p in all_images if p.name not in done]
    if args.limit:
        pending = pending[: args.limit]

    if not pending:
        log.info("처리할 신규 이미지 없음. 종료.")
        return

    est_cost = len(pending) * 0.005
    log.info(f"처리 대상: {len(pending):,}장")
    log.info(f"추정 비용: ${est_cost:.2f} (~{int(est_cost*1500):,}원)")
    log.info(f"동시 워커: {args.workers}")

    success = 0
    failures: list[tuple[str, str]] = []
    started = time.time()

    pbar = tqdm(total=len(pending), desc="Vision OCR", unit="장")

    def commit_one(path: Path, meta: dict, text: str):
        nonlocal success
        notice = 1 if is_notice_text(text) else 0
        try:
            stat = path.stat()
        except OSError:
            stat = None
        with _db_lock:
            conn.execute(
                """
                INSERT OR REPLACE INTO files
                    (filename, review_date, review_num, page, mtime, size, is_notice,
                     ocr_text, ocr_done, vision_ocr_done)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 1)
                """,
                (
                    path.name,
                    meta["review_date"],
                    meta["review_num"],
                    meta["page"],
                    stat.st_mtime if stat else 0,
                    stat.st_size if stat else 0,
                    notice,
                    text,
                ),
            )
        success += 1

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        future_to_path = {ex.submit(process_one, p, log): p for p in pending}
        for fut in as_completed(future_to_path):
            path, meta, text, err = fut.result()
            if err or text is None or meta is None:
                failures.append((path.name, err or "no_text"))
                pbar.set_postfix({"성공": success, "실패": len(failures)})
                pbar.update(1)
                continue
            commit_one(path, meta, text)
            pbar.set_postfix({"성공": success, "실패": len(failures)})
            pbar.update(1)

    pbar.close()
    conn.close()

    elapsed = time.time() - started
    log.info(f"[완료] 성공 {success:,} / 실패 {len(failures):,} / 소요 {elapsed/60:.1f}분")
    if failures:
        log.info(f"[실패 샘플 10] {failures[:10]}")


if __name__ == "__main__":
    main()
