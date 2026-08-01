// 뉴스레터 구독 신청.
// 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY
// 호출: POST /api/subscribe  { email, website? }
//
// website 는 허니팟이다. 사람은 비워두고 봇만 채운다.

import { createClient } from "@supabase/supabase-js";
import crypto from "node:crypto";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

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
            .select("email, status")
            .eq("email", addr)
            .maybeSingle();

        if (existing && existing.status === "active") {
            return res.status(200).json({ message: "이미 구독 중인 주소입니다." });
        }

        // 해지했다가 다시 신청한 경우 토큰을 새로 발급해 되살린다.
        const { error } = await supabase.from("newsletter_subscribers").upsert({
            email: addr,
            status: "active",
            token: crypto.randomBytes(24).toString("hex"),
            subscribed_at: new Date().toISOString(),
            unsubscribed_at: null,
        });
        if (error) throw error;

        return res.status(200).json({
            message: "구독 신청이 완료되었습니다. 매일 아침 메일로 보내드립니다.",
        });
    } catch (err) {
        console.error("[subscribe]", err);
        return res.status(500).json({ error: "등록에 실패했습니다. 잠시 후 다시 시도해 주세요." });
    }
}
