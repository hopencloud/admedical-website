// 뉴스 자동 발행 설정 조회/변경 (킬스위치).
// 환경변수: ADMIN_PASSWORD, SUPABASE_URL, SUPABASE_SERVICE_KEY
// 호출:
//   GET  /api/news-settings                      (헤더: X-Admin-Password)
//   POST /api/news-settings  { auto_publish, daily_count, note }
//
// auto_publish=false 로 바꾸면 다음 GitHub Actions 실행부터 발행이 중단된다.

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

    const supabase = createClient(url, key);

    try {
        if (req.method === "GET") {
            const { data, error } = await supabase
                .from("news_settings")
                .select("*")
                .eq("id", 1)
                .maybeSingle();
            if (error) throw error;

            const { data: recent } = await supabase
                .from("news_posts")
                .select("slug, title, published_date, status")
                .order("published_date", { ascending: false })
                .limit(10);

            // 가장 최근 실행의 진행상황 (테이블이 없으면 조용히 생략)
            let run = null;
            try {
                const { data: runs } = await supabase
                    .from("news_runs")
                    .select("*")
                    .order("started_at", { ascending: false })
                    .limit(1);
                run = (runs && runs[0]) || null;
            } catch (e) {
                console.warn("[news-settings] news_runs 조회 생략:", e.message);
            }

            // 구독자 (테이블이 없으면 조용히 생략)
            let subscribers = { active: 0, unsubscribed: 0, list: [] };
            try {
                const { data: subs } = await supabase
                    .from("newsletter_subscribers")
                    .select("email, status, subscribed_at, send_count")
                    .order("subscribed_at", { ascending: false })
                    .limit(200);
                const rows = subs || [];
                subscribers = {
                    active: rows.filter((r) => r.status === "active").length,
                    unsubscribed: rows.filter((r) => r.status !== "active").length,
                    list: rows.slice(0, 50),
                };
            } catch (e) {
                console.warn("[news-settings] 구독자 조회 생략:", e.message);
            }

            return res.status(200).json({
                settings: data || { auto_publish: true, daily_count: 1 },
                recent: recent || [],
                run,
                subscribers,
            });
        }

        if (req.method === "POST") {
            const { auto_publish, daily_count, note } = req.body || {};
            const patch = { id: 1, updated_at: new Date().toISOString() };

            if (typeof auto_publish === "boolean") patch.auto_publish = auto_publish;
            if (Number.isInteger(daily_count)) {
                patch.daily_count = Math.min(Math.max(daily_count, 1), 5);
            }
            if (typeof note === "string") patch.note = note.slice(0, 500);

            const { data, error } = await supabase
                .from("news_settings")
                .upsert(patch)
                .select()
                .maybeSingle();
            if (error) throw error;

            return res.status(200).json({ ok: true, settings: data });
        }

        res.setHeader("Allow", "GET, POST");
        return res.status(405).json({ error: "GET 또는 POST만 허용" });
    } catch (err) {
        console.error("[news-settings] error:", err);
        return res.status(500).json({ error: err.message || "failed" });
    }
}
