// 관리자 대시보드에서 새 작업(다운로드/인덱싱/전체 파이프라인) 등록.
// 환경변수: ADMIN_PASSWORD, SUPABASE_URL, SUPABASE_SERVICE_KEY
// 호출: POST /api/admin-job  (헤더: X-Admin-Password)
// Body: { job_type: "collector" | "indexer" | "pipeline" }

import { createClient } from "@supabase/supabase-js";

const ALLOWED_JOB_TYPES = new Set(["collector", "indexer", "pipeline"]);

export default async function handler(req, res) {
    if (req.method !== "POST") {
        res.setHeader("Allow", "POST");
        return res.status(405).json({ error: "POST only" });
    }

    const adminPwd = req.headers["x-admin-password"];
    if (!adminPwd || adminPwd !== process.env.ADMIN_PASSWORD) {
        return res.status(401).json({ error: "비밀번호가 틀렸습니다." });
    }

    const { job_type } = req.body || {};
    if (!job_type || !ALLOWED_JOB_TYPES.has(job_type)) {
        return res.status(400).json({ error: "job_type은 collector|indexer|pipeline 중 하나" });
    }

    const url = process.env.SUPABASE_URL;
    const key = process.env.SUPABASE_SERVICE_KEY;
    if (!url || !key) {
        return res.status(500).json({ error: "Supabase 환경변수가 설정되지 않았습니다." });
    }

    try {
        const supabase = createClient(url, key);

        // 이미 pending/running 작업이 있으면 거부 (큐 단일화).
        const { data: existing, error: existingErr } = await supabase
            .from("admin_jobs")
            .select("id, job_type, status")
            .in("status", ["pending", "running"])
            .order("created_at", { ascending: false })
            .limit(1);
        if (existingErr) throw existingErr;
        if (existing && existing.length > 0) {
            const j = existing[0];
            return res.status(409).json({
                error: `이미 ${j.status} 상태인 작업(${j.job_type}, id=${j.id})이 있습니다. 끝난 뒤 다시 눌러주세요.`,
            });
        }

        const { data, error } = await supabase
            .from("admin_jobs")
            .insert({ job_type, status: "pending", message: "작업 등록됨, 맥북 agent 대기 중..." })
            .select("id, job_type, status, created_at")
            .single();
        if (error) throw error;

        return res.status(200).json({ ok: true, job: data });
    } catch (err) {
        console.error("[admin-job] error:", err);
        return res.status(500).json({ error: err.message || "job creation failed" });
    }
}
