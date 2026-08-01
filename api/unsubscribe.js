// 뉴스레터 수신 해지. 메일 하단 링크가 여기로 온다.
// 호출: GET /api/unsubscribe?token=...
//
// 클릭 한 번으로 끝나야 한다 (로그인·확인 절차 없음).

import { createClient } from "@supabase/supabase-js";

function page(title, message, ok = true) {
    return `<!DOCTYPE html>
<html lang="ko"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex,nofollow">
<title>${title} | admedical</title>
<link rel="preconnect" href="https://cdn.jsdelivr.net">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<style>
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       background:#f8fafc;color:#0f172a;
       font-family:"Pretendard Variable",Pretendard,-apple-system,system-ui,sans-serif}
  .card{max-width:460px;margin:24px;padding:36px;background:#fff;border:1px solid #e2e8f0;
        border-radius:20px;box-shadow:0 4px 12px rgba(15,23,42,.04);text-align:center}
  h1{font-size:1.3rem;margin:0 0 12px}
  p{color:#475569;line-height:1.7;font-size:.95rem;margin:0 0 20px}
  a{display:inline-block;padding:12px 22px;background:#2563eb;color:#fff;border-radius:12px;
    text-decoration:none;font-weight:600;font-size:.9rem}
  .mark{font-size:2.2rem;margin-bottom:8px}
</style></head>
<body><div class="card">
  <div class="mark">${ok ? "✓" : "!"}</div>
  <h1>${title}</h1>
  <p>${message}</p>
  <a href="https://www.admedical.co.kr/news">의료광고 인사이트 보러가기</a>
</div></body></html>`;
}

export default async function handler(req, res) {
    res.setHeader("Content-Type", "text/html; charset=utf-8");

    const token = String(req.query.token || "").trim();
    if (!token) {
        return res.status(400).send(page("링크가 올바르지 않습니다",
            "해지 링크가 잘못되었습니다. 메일 하단의 링크를 다시 눌러주세요.", false));
    }

    const url = process.env.SUPABASE_URL;
    const key = process.env.SUPABASE_SERVICE_KEY;
    if (!url || !key) {
        return res.status(500).send(page("처리에 실패했습니다",
            "잠시 후 다시 시도해 주세요.", false));
    }

    try {
        const supabase = createClient(url, key);
        const { data, error } = await supabase
            .from("newsletter_subscribers")
            .update({ status: "unsubscribed", unsubscribed_at: new Date().toISOString() })
            .eq("token", token)
            .select("email")
            .maybeSingle();

        if (error) throw error;
        if (!data) {
            return res.status(404).send(page("이미 해지되었습니다",
                "해당 주소는 이미 수신이 중단된 상태입니다.", true));
        }

        return res.status(200).send(page("수신 해지가 완료되었습니다",
            "앞으로 뉴스레터를 보내드리지 않습니다. 언제든 다시 구독하실 수 있습니다.", true));
    } catch (err) {
        console.error("[unsubscribe]", err);
        return res.status(500).send(page("처리에 실패했습니다",
            "잠시 후 다시 시도해 주세요.", false));
    }
}
