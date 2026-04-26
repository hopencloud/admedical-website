// 문의 폼 → 관리자 Gmail로 발송 (Vercel serverless function).
// 기존 /api/report.js 와 동일한 SMTP 환경변수(SMTP_USER / SMTP_PASS / REPORT_TO_EMAIL) 재사용.
//
// 봇 방지:
//   1. Honeypot — `website` 필드가 채워져 있으면 차단 (사람에게는 안 보이는 함정 필드).
//   2. 작성 시간 — 페이지 로드 후 3초 이내 제출은 차단 (자동 봇은 즉시 제출하는 경향).

import nodemailer from "nodemailer";

const MIN_FILL_TIME_MS = 3000;

function escapeHtml(s) {
    return String(s ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

export default async function handler(req, res) {
    if (req.method !== "POST") {
        res.setHeader("Allow", "POST");
        return res.status(405).json({ error: "POST only" });
    }

    const { name, email, phone, message, website, loaded_at } = req.body || {};

    // ---------- 봇 방지 ----------
    // 1) Honeypot: 사람은 못 보는 필드. 봇이 모든 필드를 자동 채우면 여기서 걸림.
    if (website && String(website).trim().length > 0) {
        // 봇으로 판정 — 사용자에게는 성공처럼 응답 (봇이 재시도 못 하도록)
        return res.status(200).json({ ok: true });
    }
    // 2) 작성 시간이 너무 빠르면 봇
    const loadedAtNum = Number(loaded_at);
    if (Number.isFinite(loadedAtNum) && loadedAtNum > 0) {
        const elapsed = Date.now() - loadedAtNum;
        if (elapsed < MIN_FILL_TIME_MS) {
            return res.status(200).json({ ok: true });
        }
    }

    // ---------- 입력 검증 ----------
    if (!name || String(name).trim().length < 1) {
        return res.status(400).json({ error: "이름을 입력해주세요." });
    }
    if (!phone || String(phone).replace(/\D/g, "").length < 8) {
        return res.status(400).json({ error: "연락처를 정확히 입력해주세요." });
    }
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(email))) {
        return res.status(400).json({ error: "올바른 이메일 주소를 입력해주세요." });
    }
    if (!message || String(message).trim().length < 5) {
        return res.status(400).json({ error: "문의 내용을 5자 이상 입력해주세요." });
    }
    if (String(message).length > 5000) {
        return res.status(400).json({ error: "문의 내용이 너무 깁니다 (5000자 이하)." });
    }

    const smtpUser = process.env.SMTP_USER;
    const smtpPass = process.env.SMTP_PASS;
    const toAddr = process.env.REPORT_TO_EMAIL || smtpUser;
    if (!smtpUser || !smtpPass) {
        return res.status(500).json({ error: "SMTP 환경변수가 설정되지 않았습니다." });
    }

    const subject = "admedical 문의 접수";
    const html = `
<!doctype html>
<html><body style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:640px;margin:0 auto;padding:20px;color:#222;">
    <h2 style="color:#2563eb;">📩 새 문의 도착</h2>
    <table style="width:100%;border-collapse:collapse;">
        <tr><td style="padding:6px 0;width:120px;color:#666;">이름</td><td><b>${escapeHtml(name)}</b></td></tr>
        <tr><td style="padding:6px 0;color:#666;">이메일</td><td><a href="mailto:${escapeHtml(email)}">${escapeHtml(email)}</a></td></tr>
        <tr><td style="padding:6px 0;color:#666;">연락처</td><td>${escapeHtml(phone)}</td></tr>
        <tr><td style="padding:6px 0;color:#666;">접수 시각</td><td>${new Date().toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })}</td></tr>
    </table>

    <h3 style="margin-top:24px;">문의 내용</h3>
    <pre style="background:#f1f5f9;border-left:4px solid #2563eb;padding:12px;border-radius:6px;white-space:pre-wrap;font-family:inherit;font-size:14px;">${escapeHtml(message)}</pre>

    <p style="margin-top:24px;color:#888;font-size:12px;">
        답신: 위 이메일 주소로 직접 회신하시면 문의자에게 전달됩니다.
    </p>
</body></html>`;

    try {
        const transporter = nodemailer.createTransport({
            service: "gmail",
            auth: { user: smtpUser, pass: smtpPass },
        });
        await transporter.sendMail({
            from: `"admedical" <${smtpUser}>`,
            to: toAddr,
            replyTo: String(email),
            subject,
            html,
        });
        return res.status(200).json({ ok: true });
    } catch (err) {
        console.error("[contact] send mail failed:", err);
        return res.status(500).json({ error: "메일 발송 실패" });
    }
}
