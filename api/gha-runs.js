// 최근 GitHub Actions "Daily Pipeline" 실행 이력 조회.
// 호출: GET /api/gha-runs?limit=10  (헤더: X-Admin-Password)

const DEFAULT_REPO = "hopencloud/admedical-website";
const WORKFLOW_FILE = "daily-pipeline.yml";

export default async function handler(req, res) {
    const adminPwd = req.headers["x-admin-password"];
    if (!adminPwd || adminPwd !== process.env.ADMIN_PASSWORD) {
        return res.status(401).json({ error: "비밀번호가 틀렸습니다." });
    }

    const token = process.env.GITHUB_TOKEN;
    if (!token) {
        return res.status(500).json({ error: "GITHUB_TOKEN 미설정" });
    }
    const repo = process.env.GITHUB_REPO || DEFAULT_REPO;
    const limitRaw = parseInt(req.query.limit ?? "10", 10);
    const perPage = Math.min(Math.max(Number.isFinite(limitRaw) ? limitRaw : 10, 1), 30);

    const url = `https://api.github.com/repos/${repo}/actions/workflows/${WORKFLOW_FILE}/runs?per_page=${perPage}`;
    try {
        const r = await fetch(url, {
            headers: {
                "Authorization": `Bearer ${token}`,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        });
        if (!r.ok) {
            const text = await r.text();
            return res.status(r.status).json({ error: `GitHub ${r.status}: ${text.slice(0, 200)}` });
        }
        const data = await r.json();
        const runs = (data.workflow_runs || []).map(run => ({
            id: run.id,
            status: run.status,           // queued | in_progress | completed
            conclusion: run.conclusion,   // success | failure | cancelled | null
            created_at: run.created_at,
            updated_at: run.updated_at,
            html_url: run.html_url,
            trigger: run.event,           // schedule | workflow_dispatch
            display_title: run.display_title || run.name,
            run_number: run.run_number,
        }));
        res.setHeader("Cache-Control", "no-store");
        return res.status(200).json({ runs });
    } catch (err) {
        console.error("[gha-runs]", err);
        return res.status(500).json({ error: err.message || "fetch failed" });
    }
}
