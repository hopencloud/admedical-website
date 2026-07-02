// 관리자 대시보드에서 GitHub Actions "Daily Pipeline" workflow 를 수동 트리거.
// 환경변수:
//   ADMIN_PASSWORD  — 대시보드 비밀번호
//   GITHUB_TOKEN    — PAT with actions:write (또는 fine-grained)
//   GITHUB_REPO     — 예: "hopencloud/admedical-website" (선택; 미설정 시 아래 기본값)
//
// 호출: POST /api/gha-trigger  (헤더: X-Admin-Password)

const DEFAULT_REPO = "hopencloud/admedical-website";
const WORKFLOW_FILE = "daily-pipeline.yml";

export default async function handler(req, res) {
    if (req.method !== "POST") {
        res.setHeader("Allow", "POST");
        return res.status(405).json({ error: "POST only" });
    }

    const adminPwd = req.headers["x-admin-password"];
    if (!adminPwd || adminPwd !== process.env.ADMIN_PASSWORD) {
        return res.status(401).json({ error: "비밀번호가 틀렸습니다." });
    }

    const token = process.env.GITHUB_TOKEN;
    if (!token) {
        return res.status(500).json({ error: "GITHUB_TOKEN 미설정" });
    }
    const repo = process.env.GITHUB_REPO || DEFAULT_REPO;

    const url = `https://api.github.com/repos/${repo}/actions/workflows/${WORKFLOW_FILE}/dispatches`;
    try {
        const r = await fetch(url, {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${token}`,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ ref: "main" }),
        });
        if (r.status === 204) {
            // GitHub 은 성공 시 204 No Content 반환.
            return res.status(200).json({ ok: true, message: "workflow dispatched" });
        }
        const text = await r.text();
        return res.status(r.status).json({ error: `GitHub ${r.status}: ${text.slice(0, 200)}` });
    } catch (err) {
        console.error("[gha-trigger]", err);
        return res.status(500).json({ error: err.message || "dispatch failed" });
    }
}
