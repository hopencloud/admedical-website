// Vercel Cron — 매일 새벽 5시(KST) admin_jobs 큐에 pipeline 작업 INSERT.
// 실제 실행은 맥북의 admin_agent.py 가 픽업해서 처리.
//
// 스케줄: vercel.json 의 "crons" 항목 참고 (UTC 기준 20:00 = KST 05:00).
//
// 보안: Vercel 이 자동으로 보내는 Authorization: Bearer ${CRON_SECRET} 헤더 검증.
//   Vercel 환경변수에 CRON_SECRET 등록 필요 (Settings → Environment Variables).
//   외부에서 이 endpoint 를 호출해도 secret 없으면 401.
//
// 중복 방지:
//   admin_jobs 에 pending/running 작업이 이미 있으면 새로 만들지 않음.
//   (전날 작업이 아직 안 끝났을 경우 — 맥북 며칠 꺼져 있다 깨어난 직후 등)

import { createClient } from "@supabase/supabase-js";

export default async function handler(req, res) {
    // Vercel Cron 인증
    const auth = req.headers["authorization"];
    const expected = process.env.CRON_SECRET;
    if (!expected) {
        return res.status(500).json({ error: "CRON_SECRET 환경변수 미설정" });
    }
    if (auth !== `Bearer ${expected}`) {
        return res.status(401).json({ error: "unauthorized" });
    }

    const url = process.env.SUPABASE_URL;
    const key = process.env.SUPABASE_SERVICE_KEY;
    if (!url || !key) {
        return res.status(500).json({ error: "Supabase 환경변수 미설정" });
    }

    try {
        const supabase = createClient(url, key);

        // 이미 처리 중/대기 작업 있는지
        const { data: pending, error: pErr } = await supabase
            .from("admin_jobs")
            .select("id, job_type, status")
            .in("status", ["pending", "running"])
            .order("created_at", { ascending: false })
            .limit(1);
        if (pErr) throw pErr;
        if (pending && pending.length > 0) {
            const j = pending[0];
            return res.status(200).json({
                skipped: true,
                reason: `이미 ${j.status} 작업 존재 (id=${j.id}, type=${j.job_type})`,
            });
        }

        const { data, error } = await supabase
            .from("admin_jobs")
            .insert({
                job_type: "pipeline",
                status: "pending",
                message: "Vercel Cron 자동 등록 (매일 새벽 5시 KST)",
            })
            .select("id, created_at")
            .single();
        if (error) throw error;

        return res.status(200).json({ ok: true, job: data });
    } catch (err) {
        console.error("[cron-daily-pipeline] error:", err);
        return res.status(500).json({ error: err.message || "queue failed" });
    }
}
