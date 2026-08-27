"""IndexNow — 바뀐 URL 을 검색엔진에 즉시 알린다.

왜 있는가:
    구글은 색인 요청 API 를 일반 페이지에 열어주지 않는다. 서치콘솔에서 사람이
    직접 눌러야 한다. 반면 **네이버·빙·Yandex 는 IndexNow 를 지원**하므로
    스크립트로 바로 재수집을 요청할 수 있다.

    이 사이트는 네이버 유입이 특히 약하다. 네이버 쪽만이라도 자동으로
    밀어넣을 수 있으면 크다.

동작:
    사이트 루트에 있는 키 파일(<key>.txt)로 소유권을 증명한다.
    한 번에 최대 10,000개까지 보낼 수 있다.

실행:
    python scripts/indexnow.py                 # 사이트맵 전체
    python scripts/indexnow.py --changed 3     # 최근 3일 안에 바뀐 것만
    python scripts/indexnow.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
WEB = ROOT / "website"
BASE_URL = "https://www.admedical.co.kr"
HOST = "www.admedical.co.kr"

# 어느 한 곳에 보내면 참여 검색엔진끼리 공유한다. 그래도 네이버는 직접 찌른다.
ENDPOINTS = [
    "https://api.indexnow.org/indexnow",
    "https://searchadvisor.naver.com/indexnow",
]


def find_key() -> str | None:
    """website/ 루트의 <32자 hex>.txt 를 키로 본다."""
    for f in WEB.glob("*.txt"):
        if re.fullmatch(r"[0-9a-f]{8,128}", f.stem):
            body = f.read_text(encoding="utf-8").strip()
            if body == f.stem:
                return f.stem
    return None


def sitemap_urls(changed_within_days: int = 0) -> list[str]:
    text = (WEB / "sitemap.xml").read_text(encoding="utf-8")
    out = []
    cutoff = date.today() - timedelta(days=changed_within_days)
    for block in re.findall(r"<url>(.*?)</url>", text, flags=re.S):
        loc = re.search(r"<loc>(.*?)</loc>", block)
        if not loc:
            continue
        if changed_within_days:
            lm = re.search(r"<lastmod>(.*?)</lastmod>", block)
            try:
                if not lm or date.fromisoformat(lm.group(1)[:10]) < cutoff:
                    continue
            except ValueError:
                continue
        out.append(loc.group(1))
    return out


def submit(endpoint: str, key: str, urls: list[str]) -> tuple[int, str]:
    payload = json.dumps({
        "host": HOST,
        "key": key,
        "keyLocation": f"{BASE_URL}/{key}.txt",
        "urlList": urls,
    }).encode()
    req = urllib.request.Request(
        endpoint, data=payload,
        headers={"Content-Type": "application/json; charset=utf-8",
                 "User-Agent": "admedical-indexnow/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, (r.read()[:200].decode("utf-8", "replace") or "OK")
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200].decode("utf-8", "replace")
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--changed", type=int, default=0,
                    help="최근 N일 안에 lastmod 가 바뀐 URL 만 보냄 (0=전체)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    key = find_key()
    if not key:
        print("[오류] website/ 에 IndexNow 키 파일(<key>.txt)이 없습니다.")
        return 1

    urls = sitemap_urls(args.changed)
    if not urls:
        print("보낼 URL 이 없습니다.")
        return 0

    print(f"키: {key}")
    print(f"대상 {len(urls)}개" + (f" (최근 {args.changed}일 변경분)" if args.changed else " (전체)"))
    for u in urls[:5]:
        print(f"  {u}")
    if len(urls) > 5:
        print(f"  … 외 {len(urls) - 5}개")

    if args.dry_run:
        print("\n(dry-run — 실제로 보내지 않음)")
        return 0

    ok = 0
    for ep in ENDPOINTS:
        status, body = submit(ep, key, urls)
        # 200 접수됨 / 202 접수됐고 키 검증 중 — 둘 다 성공이다
        mark = "✓" if status in (200, 202) else "✗"
        print(f"\n{mark} {ep}\n   HTTP {status}  {body.strip()[:120]}")
        if status in (200, 202):
            ok += 1
        time.sleep(1)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
