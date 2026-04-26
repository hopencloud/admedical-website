// 관리자 페이지에서 특정 광고 정보 가져오기.
// 환경변수: ADMIN_PASSWORD, SUPABASE_URL, SUPABASE_SERVICE_KEY
// 호출: GET /api/admin-load?review_num=XXX  (헤더: X-Admin-Password)

import { createClient } from "@supabase/supabase-js";

export default async function handler(req, res) {
    const adminPwd = req.headers["x-admin-password"];
    if (!adminPwd || adminPwd !== process.env.ADMIN_PASSWORD) {
        return res.status(401).json({ error: "비밀번호가 틀렸습니다." });
    }

    const reviewNum = req.query.review_num;
    if (!reviewNum) {
        return res.status(400).json({ error: "review_num required" });
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
            .select("review_num, review_no_display, review_date, ocr_text, page_count")
            .eq("review_num", parseInt(reviewNum, 10))
            .maybeSingle();

        if (error) throw error;
        if (!data) return res.status(404).json({ error: "해당 심의번호 없음" });

        return res.status(200).json(data);
    } catch (err) {
        console.error("[admin-load] error:", err);
        return res.status(500).json({ error: err.message || "load failed" });
    }
}
