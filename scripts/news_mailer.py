"""
뉴스레터 발송 — 그날 발행한 기사를 구독자에게 메일로 보낸다.

발송 경로는 기존 문의/제보 메일과 같은 SMTP(Gmail)를 재사용한다.
환경변수: SMTP_USER, SMTP_PASS (GitHub Actions 시크릿)

주의:
    Gmail SMTP 는 하루 발송량 제한이 있다(계정 유형에 따라 대략 500건 안팎).
    구독자가 수백 명을 넘어가면 전용 발송 서비스로 옮겨야 한다.
    지금은 한 통씩 개별 발송한다 — 수신자끼리 주소가 노출되지 않고,
    수신 해지 링크를 사람마다 다르게 넣어야 하기 때문이다.

실행:
    python scripts/news_mailer.py            # 오늘 발행분 발송
    python scripts/news_mailer.py --dry-run  # 발송 없이 대상·본문만 확인
"""
from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from html import escape
from pathlib import Path

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent.parent
INDEX_JSON = ROOT / "website" / "assets" / "data" / "news-index.json"
BASE_URL = "https://www.admedical.co.kr"

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SEND_INTERVAL_SEC = float(os.getenv("NEWSLETTER_INTERVAL", "0.4"))


def log(msg: str) -> None:
    print(f"[mail] {msg}", flush=True)


def get_supabase():
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        return None
    from supabase import create_client
    return create_client(url, key)


def todays_posts(date_str: str) -> list[dict]:
    if not INDEX_JSON.exists():
        return []
    data = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
    return [p for p in data.get("posts", []) if p.get("date") == date_str]


def build_html(posts: list[dict], date_str: str, token: str) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    unsub = f"{BASE_URL}/api/unsubscribe?token={token}"

    items = []
    for p in posts:
        url = f"{BASE_URL}/news/{p['slug']}"
        thumb = p.get("thumb") or p.get("cover")
        img = (f'<a href="{url}"><img src="{BASE_URL}{thumb}" width="560" alt="{escape(p["title"])}" '
               f'style="width:100%;max-width:560px;height:auto;border-radius:10px;'
               f'border:1px solid #e2e8f0;display:block;margin:0 0 12px"></a>') if thumb else ""
        items.append(f"""
        <tr><td style="padding:0 0 28px">
          {img}
          <a href="{url}" style="color:#0f172a;font-size:18px;font-weight:700;
             text-decoration:none;line-height:1.4;display:block;margin:0 0 8px">{escape(p['title'])}</a>
          <p style="color:#475569;font-size:14px;line-height:1.7;margin:0 0 10px">{escape(p.get('summary', ''))}</p>
          <a href="{url}" style="color:#2563eb;font-size:14px;font-weight:600;text-decoration:none">
             기사 읽기 →</a>
        </td></tr>""")

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f1f5f9;
             font-family:-apple-system,BlinkMacSystemFont,'Malgun Gothic',sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9">
<tr><td align="center" style="padding:28px 12px">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0"
         style="width:100%;max-width:600px;background:#ffffff;border-radius:16px;overflow:hidden">

    <tr><td style="background:#1e3a8a;padding:24px 28px">
      <div style="color:#bfdbfe;font-size:12px;font-weight:700;letter-spacing:.4px">ADMEDICAL</div>
      <div style="color:#ffffff;font-size:20px;font-weight:800;margin-top:4px">의료광고 인사이트</div>
      <div style="color:#93c5fd;font-size:13px;margin-top:6px">{dt:%Y년 %-m월 %-d일}</div>
    </td></tr>

    <tr><td style="padding:28px">
      <p style="color:#475569;font-size:14px;line-height:1.7;margin:0 0 24px">
        병의원 마케터가 알아야 할 오늘의 규제·정책·시장 변화입니다.
      </p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        {''.join(items)}
      </table>
    </td></tr>

    <tr><td style="background:#f8fafc;padding:20px 28px;border-top:1px solid #e2e8f0">
      <p style="color:#64748b;font-size:12px;line-height:1.7;margin:0 0 10px">
        본 메일은 공개된 언론 보도와 정부 보도자료, admedical이 수집한 의료광고 심의 통과 데이터를
        바탕으로 AI 도구의 도움을 받아 작성되었습니다. 정보 제공 목적이며 법적 자문이 아닙니다.
      </p>
      <p style="color:#94a3b8;font-size:12px;margin:0">
        <a href="{BASE_URL}/news" style="color:#2563eb;text-decoration:none">지난 인사이트 보기</a>
        &nbsp;·&nbsp;
        <a href="{unsub}" style="color:#94a3b8;text-decoration:underline">수신 해지</a>
      </p>
    </td></tr>

  </table>
</td></tr></table>
</body></html>"""


def build_text(posts: list[dict], date_str: str, token: str) -> str:
    lines = [f"admedical 의료광고 인사이트 — {date_str}", ""]
    for p in posts:
        lines += [f"■ {p['title']}", f"  {p.get('summary', '')}",
                  f"  {BASE_URL}/news/{p['slug']}", ""]
    lines += ["-" * 40,
              "정보 제공 목적이며 법적 자문이 아닙니다.",
              f"수신 해지: {BASE_URL}/api/unsubscribe?token={token}"]
    return "\n".join(lines)


def creds() -> tuple[str, str]:
    """Gmail 앱 비밀번호는 'abcd efgh ijkl mnop' 형태로 표시돼 공백째로 붙여넣기 쉽다.
    공백이 들어가면 로그인이 실패하므로 여기서 제거한다."""
    user = (os.getenv("SMTP_USER") or "").strip()
    password = re.sub(r"\s+", "", os.getenv("SMTP_PASS") or "")
    return user, password


def send_all(posts: list[dict], date_str: str, dry_run: bool = False) -> int:
    client = get_supabase()
    if client is None:
        log("Supabase 연결 정보가 없어 발송을 건너뜁니다.")
        return 0

    rows = client.table("newsletter_subscribers").select(
        "email, token, send_count").eq("status", "active").execute().data or []
    if not rows:
        log("활성 구독자가 없습니다.")
        return 0

    subject = f"[의료광고 인사이트] {posts[0]['title']}" if len(posts) == 1 else \
              f"[의료광고 인사이트] {datetime.strptime(date_str, '%Y-%m-%d'):%-m월 %-d일} · {len(posts)}건"

    log(f"대상 {len(rows)}명 / 기사 {len(posts)}건")
    if dry_run:
        log(f"제목: {subject}")
        print(build_text(posts, date_str, "SAMPLE-TOKEN"))
        return 0

    user, password = creds()
    if not user or not password:
        log("SMTP_USER/SMTP_PASS 가 없어 발송을 건너뜁니다.")
        return 0

    sent = 0
    context = ssl.create_default_context()
    try:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=30)
        server.login(user, password)
    except smtplib.SMTPAuthenticationError as exc:
        log("SMTP 로그인 실패 — 앱 비밀번호를 확인하세요. "
            "Gmail 계정 비밀번호가 아니라 2단계 인증 후 발급받는 16자리입니다.")
        log(f"  서버 응답: {exc}")
        return 0
    except Exception as exc:
        log(f"SMTP 접속 실패: {type(exc).__name__}: {exc}")
        return 0

    with server:
        for row in rows:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = Header(subject, "utf-8")
            msg["From"] = formataddr((str(Header("admedical 의료광고 인사이트", "utf-8")), user))
            msg["To"] = row["email"]
            msg["List-Unsubscribe"] = f"<{BASE_URL}/api/unsubscribe?token={row['token']}>"
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
            msg.attach(MIMEText(build_text(posts, date_str, row["token"]), "plain", "utf-8"))
            msg.attach(MIMEText(build_html(posts, date_str, row["token"]), "html", "utf-8"))

            try:
                server.send_message(msg)
                sent += 1
                client.table("newsletter_subscribers").update({
                    "last_sent_at": datetime.now(timezone.utc).isoformat(),
                    "send_count": (row.get("send_count") or 0) + 1,
                }).eq("email", row["email"]).execute()
            except Exception as exc:
                log(f"발송 실패 {row['email']}: {type(exc).__name__}: {exc}")
            time.sleep(SEND_INTERVAL_SEC)

    log(f"발송 완료: {sent}/{len(rows)}명")

    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"## 뉴스레터 발송\n\n- 대상 **{len(rows)}명** 중 **{sent}명** 발송\n"
                    f"- 기사 **{len(posts)}건** ({date_str})\n")
    return sent


def main() -> int:
    ap = argparse.ArgumentParser(description="뉴스레터 발송")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--date", default=f"{datetime.now(KST):%Y-%m-%d}")
    args = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    posts = todays_posts(args.date)
    if not posts:
        log(f"{args.date} 발행분이 없습니다. 발송하지 않습니다.")
        return 0

    try:
        send_all(posts, args.date, dry_run=args.dry_run)
    except Exception as exc:
        # 메일이 안 나가는 것과 기사가 안 올라가는 것은 별개다.
        # 여기서 죽으면 워크플로우 전체가 실패로 보인다.
        log(f"발송 중 오류: {type(exc).__name__}: {exc}")
        import traceback; traceback.print_exc()
    return 0


if __name__ == "__main__":
    sys.exit(main())
