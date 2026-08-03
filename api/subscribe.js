// 뉴스레터 구독 신청.
// 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY
// 호출: POST /api/subscribe  { email, website? }
//
// website 는 허니팟이다. 사람은 비워두고 봇만 채운다.

import { createClient } from "@supabase/supabase-js";
import nodemailer from "nodemailer";
import crypto from "node:crypto";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const SITE = "https://www.admedical.co.kr";

function esc(s) {
    return String(s ?? "").replace(/[&<>"]/g, (c) =>
        ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function welcomeHtml(token, recent) {
    const unsub = `${SITE}/api/unsubscribe?token=${token}`;
    const items = recent.slice(0, 3).map((p) =>
        `<li style="margin:0 0 10px"><a href="${SITE}/news/${esc(p.slug)}"
            style="color:#2563eb;text-decoration:none;font-size:14px;line-height:1.6">${esc(p.title)}</a></li>`
    ).join("");
    const recentBlock = items ? `
      <div style="margin:24px 0 0;padding:18px 20px;background:#f8fafc;border-radius:12px">
        <div style="color:#334155;font-size:13px;font-weight:700;margin:0 0 12px">최근 발행한 글</div>
        <ul style="margin:0;padding:0 0 0 16px;color:#475569">${items}</ul>
      </div>` : "";

    return `<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Malgun Gothic',sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9">
<tr><td align="center" style="padding:28px 12px">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0"
         style="width:100%;max-width:600px;background:#ffffff;border-radius:16px;overflow:hidden">
    <tr><td style="background:#1e3a8a;padding:26px 28px">
      <div style="color:#bfdbfe;font-size:12px;font-weight:700;letter-spacing:.4px">ADMEDICAL</div>
      <div style="color:#ffffff;font-size:20px;font-weight:800;margin-top:4px">구독해 주셔서 감사합니다</div>
    </td></tr>
    <tr><td style="padding:28px">
      <p style="color:#0f172a;font-size:15px;line-height:1.8;margin:0 0 16px">
        의료광고 인사이트 뉴스레터 구독이 완료되었습니다.</p>
      <p style="color:#475569;font-size:14px;line-height:1.8;margin:0 0 16px">
        매주 월요일 새벽 <b style="color:#0f172a">5시 30분</b>에 병의원 마케터가 알아야 할
        의료광고 규제·정책·시장 변화를 정리해 보내드립니다.
        대한의사협회 의료광고심의위원회 통과 시안 데이터와 함께 읽으실 수 있습니다.</p>
      <p style="color:#475569;font-size:14px;line-height:1.8;margin:0">
        받아보실 내용이 마음에 들지 않으시면 언제든 메일 맨 아래 &lsquo;수신 해지&rsquo; 링크를
        눌러주세요. 한 번 클릭으로 바로 처리됩니다.</p>
      ${recentBlock}
      <div style="margin:26px 0 0">
        <a href="${SITE}/news" style="display:inline-block;padding:13px 24px;background:#2563eb;
           color:#ffffff;border-radius:12px;text-decoration:none;font-weight:700;font-size:14px">
          지난 인사이트 둘러보기</a>
      </div>
    </td></tr>
    <tr><td style="background:#f8fafc;padding:20px 28px;border-top:1px solid #e2e8f0">
      <p style="color:#64748b;font-size:12px;line-height:1.7;margin:0 0 10px">
        본 메일은 admedical.co.kr 에서 뉴스레터 구독을 신청하신 주소로 발송되었습니다.
        신청하신 적이 없다면 아래 링크를 눌러 해지해 주세요.</p>
      <p style="color:#94a3b8;font-size:12px;margin:0">
        <a href="${unsub}" style="color:#94a3b8;text-decoration:underline">수신 해지</a></p>
    </td></tr>
  </table>
</td></tr></table>
</body></html>`;
}

async function sendWelcome(email, token) {
    const user = process.env.SMTP_USER;
    const pass = process.env.SMTP_PASS;
    if (!user || !pass) {
        console.warn("[subscribe] SMTP 미설정 — 환영 메일 생략");
        return false;
    }

    // 최근 글 3건은 사이트의 공개 인덱스에서 읽는다 (실패해도 메일은 나간다).
    let recent = [];
    try {
        const r = await fetch(`${SITE}/assets/data/news-index.json`, { cache: "no-store" });
        if (r.ok) recent = (await r.json()).posts || [];
    } catch { /* 무시 */ }

    const unsub = `${SITE}/api/unsubscribe?token=${token}`;
    const text = [
        "admedical 의료광고 인사이트 뉴스레터 구독이 완료되었습니다.",
        "",
        "매주 월요일 새벽 5시 30분에 병의원 마케터가 알아야 할",
        "의료광고 규제·정책·시장 변화를 정리해 보내드립니다.",
        "",
        `지난 인사이트 보기: ${SITE}/news`,
        "",
        "----------------------------------------",
        "신청하신 적이 없다면 아래 링크로 해지해 주세요.",
        `수신 해지: ${unsub}`,
    ].join("\n");

    const transporter = nodemailer.createTransport({
        service: "gmail",
        auth: { user, pass },
    });

    await transporter.sendMail({
        from: `"admedical 의료광고 인사이트" <${user}>`,
        to: email,
        subject: "[의료광고 인사이트] 뉴스레터 구독이 완료되었습니다",
        text,
        html: welcomeHtml(token, recent),
        headers: {
            "List-Unsubscribe": `<${unsub}>`,
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    });
    return true;
}

export default async function handler(req, res) {
    if (req.method !== "POST") {
        res.setHeader("Allow", "POST");
        return res.status(405).json({ error: "POST only" });
    }

    const { email, website } = req.body || {};

    // 허니팟에 값이 있으면 봇. 성공한 척하고 버린다.
    if (website) {
        return res.status(200).json({ message: "구독 신청이 완료되었습니다." });
    }

    const addr = String(email || "").trim().toLowerCase();
    if (!EMAIL_RE.test(addr) || addr.length > 254) {
        return res.status(400).json({ error: "이메일 주소 형식을 확인해 주세요." });
    }

    const url = process.env.SUPABASE_URL;
    const key = process.env.SUPABASE_SERVICE_KEY;
    if (!url || !key) {
        return res.status(500).json({ error: "서버 설정 오류입니다. 잠시 후 다시 시도해 주세요." });
    }

    try {
        const supabase = createClient(url, key);

        const { data: existing } = await supabase
            .from("newsletter_subscribers")
            .select("email, status, token")
            .eq("email", addr)
            .maybeSingle();

        if (existing && existing.status === "active") {
            return res.status(200).json({ message: "이미 구독 중인 주소입니다." });
        }

        // 해지했다가 다시 신청한 경우 토큰을 새로 발급해 되살린다.
        const token = crypto.randomBytes(24).toString("hex");
        const { error } = await supabase.from("newsletter_subscribers").upsert({
            email: addr,
            status: "active",
            token,
            subscribed_at: new Date().toISOString(),
            unsubscribed_at: null,
        });
        if (error) throw error;

        // 환영 메일. 실패해도 구독 자체는 유효하므로 신청은 성공으로 응답한다.
        try {
            await sendWelcome(addr, token);
        } catch (e) {
            console.error("[subscribe] 환영 메일 실패:", e.message);
        }

        return res.status(200).json({
            message: "구독 신청이 완료되었습니다. 확인 메일을 보내드렸습니다.",
        });
    } catch (err) {
        console.error("[subscribe]", err);
        return res.status(500).json({ error: "등록에 실패했습니다. 잠시 후 다시 시도해 주세요." });
    }
}
