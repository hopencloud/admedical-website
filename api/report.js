// 오류 제보 → 관리자 Gmail로 발송 (Vercel serverless function).
// 환경변수 필요:
//   SMTP_USER         관리자 Gmail 주소
//   SMTP_PASS         Gmail App Password (16자리, 띄어쓰기 제거)
//   REPORT_TO_EMAIL   (선택) 받는 메일이 다르다면 지정. 없으면 SMTP_USER로.
//   PUBLIC_SITE_URL   (선택) 메일 본문의 수정 링크용 도메인. 없으면 아래 기본값.
//
// 보안 (2026-11-02):
//   · 인증이 없는 엔드포인트다. 같은 IP 가 10분에 5번까지만 보낼 수 있다.
//     안 막아두면 누구나 이 주소를 반복 호출해 관리자 Gmail 로 메일을 쏟아부을 수
//     있고, 하루 발송 한도(약 500건)를 태우거나 계정이 제한된다.
//   · 수정 링크의 도메인을 **요청 헤더에서 뽑지 않는다**. 예전에는 Host 헤더를
//     그대로 썼는데, 그러면 공격자가 Host 를 바꿔 보내 관리자가 받는 메일에
//     공격자 사이트 링크를 박을 수 있다(피싱). 상수나 환경변수만 쓴다.

import nodemailer from "nodemailer";
import { publicLimit, clamp } from "../lib/guard.js";

// 메일 본문 링크에 쓸 도메인. 요청 헤더는 신뢰하지 않는다.
const SITE_ORIGIN = process.env.PUBLIC_SITE_URL || "https://www.admedical.co.kr";

// 메일 한 통에 들어갈 수 있는 최대 길이
const MAX_REASON = 2000;
const MAX_OCR = 20000;
const MAX_DISPLAY = 100;

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

    if (!(await publicLimit(req, res, "report"))) return;

    const body = req.body || {};
    const reviewNum = Number(body.review_num);
    const display = clamp(body.review_no_display, MAX_DISPLAY).trim();
    const reason = clamp(body.reason, MAX_REASON).trim();
    const ocrText = clamp(body.ocr_text, MAX_OCR);

    if (!display || !Number.isInteger(reviewNum)) {
        return res.status(400).json({ error: "review_no_display, review_num 필수" });
    }
    if (reason.length < 2) {
        return res.status(400).json({ error: "reason 필수 (2자 이상)" });
    }

    const smtpUser = process.env.SMTP_USER;
    const smtpPass = process.env.SMTP_PASS;
    const toAddr = process.env.REPORT_TO_EMAIL || smtpUser;
    if (!smtpUser || !smtpPass) {
        return res.status(500).json({ error: "SMTP 환경변수가 설정되지 않았습니다." });
    }

    // 수정 링크 (관리자 페이지). 도메인은 상수/환경변수에서만 온다.
    const editLink = `${SITE_ORIGIN}/admin/edit?review_num=${encodeURIComponent(reviewNum)}`;

    const subject = `[오류제보] ${display}`;
    const html = `
<!doctype html>
<html><body style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:640px;margin:0 auto;padding:20px;color:#222;">
    <h2 style="color:#dc2626;">🚨 오류 제보 접수</h2>
    <table style="width:100%;border-collapse:collapse;">
        <tr><td style="padding:6px 0;width:120px;color:#666;">심의번호</td><td><b>${escapeHtml(display)}</b></td></tr>
        <tr><td style="padding:6px 0;color:#666;">접수 시각</td><td>${new Date().toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })}</td></tr>
    </table>

    <h3 style="margin-top:24px;">제보 사유</h3>
    <pre style="background:#fef2f2;border-left:4px solid #dc2626;padding:12px;border-radius:6px;white-space:pre-wrap;font-family:inherit;font-size:14px;">${escapeHtml(reason)}</pre>

    <h3 style="margin-top:24px;">현재 광고 문구 (Supabase에 저장된 마스킹 결과)</h3>
    <pre style="background:#f5f5f5;padding:12px;border-radius:6px;white-space:pre-wrap;font-family:inherit;font-size:13px;">${escapeHtml(ocrText || "(없음)")}</pre>

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
