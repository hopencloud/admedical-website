// 관리자 페이지에서 광고 문구 수정 저장.
// 환경변수: ADMIN_PASSWORD, SUPABASE_URL, SUPABASE_SERVICE_KEY
// 호출: POST /api/admin-save  (헤더: X-Admin-Password)
// Body: { review_num: int, ocr_text: string }

import { createClient } from "@supabase/supabase-js";

export default async function handler(req, res) {
    if (req.method !== "POST") {
        res.setHeader("Allow", "POST");
        return res.status(405).json({ error: "POST only" });
    }

    const adminPwd = req.headers["x-admin-password"];
    if (!adminPwd || adminPwd !== process.env.ADMIN_PASSWORD) {
        return res.status(401).json({ error: "비밀번호가 틀렸습니다." });
    }

    const { review_num, ocr_text } = req.body || {};
    if (!review_num) {
        return res.status(400).json({ error: "review_num 필수" });
    }
    if (typeof ocr_text !== "string") {
        return res.status(400).json({ error: "ocr_text 필수 (string)" });
    }

    const url = process.env.SUPABASE_URL;
    const key = process.env.SUPABASE_SERVICE_KEY;
    if (!url || !key) {
        return res.status(500).json({ error: "Supabase 환경변수가 설정되지 않았습니다." });
    }

    try {
        const supabase = createClient(url, key);
        const { data, error } = await supabase
            .from("ads")
            .update({ ocr_text })
            .eq("review_num", parseInt(review_num, 10))
            .select("review_num, review_no_display");

        if (error) throw error;
        if (!data || data.length === 0) {
            return res.status(404).json({ error: "해당 심의번호 없음" });
        }
        return res.status(200).json({ ok: true, updated: data[0] });
    } catch (err) {
        console.error("[admin-save] error:", err);
        return res.status(500).json({ error: err.message || "save failed" });
    }
}
