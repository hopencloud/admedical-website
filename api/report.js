// 오류 제보 → 관리자 Gmail로 발송 (Vercel serverless function).
// 환경변수 필요:
//   SMTP_USER         관리자 Gmail 주소
//   SMTP_PASS         Gmail App Password (16자리, 띄어쓰기 제거)
//   REPORT_TO_EMAIL   (선택) 받는 메일이 다르다면 지정. 없으면 SMTP_USER로.
//   PUBLIC_SITE_URL   (선택) 메일 본문의 수정 링크용 도메인. 없으면 요청 헤더에서 추론.

import nodemailer from "nodemailer";

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

    const { review_no_display, review_num, ocr_text, reason } = req.body || {};

    if (!review_no_display || !review_num) {
        return res.status(400).json({ error: "review_no_display, review_num 필수" });
    }
    if (!reason || String(reason).trim().length < 2) {
        return res.status(400).json({ error: "reason 필수 (2자 이상)" });
    }

    const smtpUser = process.env.SMTP_USER;
    const smtpPass = process.env.SMTP_PASS;
    const toAddr = process.env.REPORT_TO_EMAIL || smtpUser;
    if (!smtpUser || !smtpPass) {
        return res.status(500).json({ error: "SMTP 환경변수가 설정되지 않았습니다." });
    }

    // 수정 링크 (관리자 페이지)
    const proto = (req.headers["x-forwarded-proto"] || "https").split(",")[0].trim();
    const host = req.headers["host"] || "";
    const base = process.env.PUBLIC_SITE_URL || `${proto}://${host}`;
    const editLink = `${base}/admin/edit?review_num=${encodeURIComponent(review_num)}`;

    const subject = `[오류제보] ${review_no_display}`;
    const html = `
<!doctype html>
<html><body style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:640px;margin:0 auto;padding:20px;color:#222;">
    <h2 style="color:#dc2626;">🚨 오류 제보 접수</h2>
    <table style="width:100%;border-collapse:collapse;">
        <tr><td style="padding:6px 0;width:120px;color:#666;">심의번호</td><td><b>${escapeHtml(review_no_display)}</b></td></tr>
        <tr><td style="padding:6px 0;color:#666;">접수 시각</td><td>${new Date().toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })}</td></tr>
    </table>

    <h3 style="margin-top:24px;">제보 사유</h3>
    <pre style="background:#fef2f2;border-left:4px solid #dc2626;padding:12px;border-radius:6px;white-space:pre-wrap;font-family:inherit;font-size:14px;">${escapeHtml(reason)}</pre>

    <h3 style="margin-top:24px;">현재 광고 문구 (Supabase에 저장된 마스킹 결과)</h3>
    <pre style="background:#f5f5f5;padding:12px;border-radius:6px;white-space:pre-wrap;font-family:inherit;font-size:13px;">${escapeHtml(ocr_text || "(없음)")}</pre>

    <h3 style="margin-top:24px;">수정하기</h3>
    <p>아래 링크를 누르면 관리자 페이지에서 광고 문구를 직접 수정할 수 있습니다.<br>
    (관리자 비밀번호 입력 필요)</p>
    <p><a href="${editLink}" style="display:inline-block;padding:10px 20px;background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;font-weight:bold;">광고 문구 수정 페이지 →</a></p>
    <p style="font-size:11px;color:#999;">${escapeHtml(editLink)}</p>
</body></html>`;

    try {
        const transporter = nodemailer.createTransport({
            service: "gmail",
            auth: { user: smtpUser, pass: smtpPass },
        });
        await transporter.sendMail({
            from: `"admedical" <${smtpUser}>`,
            to: toAddr,
            subject,
            html,
        });
        return res.status(200).json({ ok: true });
    } catch (err) {
        console.error("[report] send mail failed:", err);
        return res.status(500).json({ error: "메일 발송 실패" });
    }
}
