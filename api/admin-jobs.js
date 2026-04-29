// 관리자 대시보드에서 최근 작업 목록 + 진행 상태 조회.
// 환경변수: ADMIN_PASSWORD, SUPABASE_URL, SUPABASE_SERVICE_KEY
// 호출: GET /api/admin-jobs  (헤더: X-Admin-Password)
//      ?limit=10            — 최근 N개
//      ?id=123              — 특정 작업 1개

import { createClient } from "@supabase/supabase-js";

export default async function handler(req, res) {
    const adminPwd = req.headers["x-admin-password"];
    if (!adminPwd || adminPwd !== process.env.ADMIN_PASSWORD) {
        return res.status(401).json({ error: "비밀번호가 틀렸습니다." });
    }

    const url = process.env.SUPABASE_URL;
    const key = process.env.SUPABASE_SERVICE_KEY;
    if (!url || !key) {
        return res.status(500).json({ error: "Supabase 환경변수가 설정되지 않았습니다." });
    }

    const limitRaw = parseInt(req.query.limit ?? "10", 10);
    const limit = Math.min(Math.max(Number.isFinite(limitRaw) ? limitRaw : 10, 1), 50);
    const id = req.query.id ? parseInt(req.query.id, 10) : null;

    try {
        const supabase = createClient(url, key);

        if (id) {
            const { data, error } = await supabase
                .from("admin_jobs")
                .select("*")
                .eq("id", id)
                .maybeSingle();
            if (error) throw error;
            if (!data) return res.status(404).json({ error: "해당 작업 없음" });
            // 캐시 끔 — 진행률 실시간 표시용
            res.setHeader("Cache-Control", "no-store");
            return res.status(200).json({ job: data });
        }

        const { data, error } = await supabase
            .from("admin_jobs")
            .select("id, job_type, status, progress, counter, message, error_text, created_at, started_at, finished_at")
            .order("created_at", { ascending: false })
            .limit(limit);
        if (error) throw error;

        res.setHeader("Cache-Control", "no-store");
        return res.status(200).json({ jobs: data || [] });
    } catch (err) {
        console.error("[admin-jobs] error:", err);
        return res.status(500).json({ error: err.message || "fetch failed" });
    }
}
