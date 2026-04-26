// Supabase 연결 정보 (anon 키만 — 공개되어도 안전)
window.SUPABASE_CONFIG = {
    url: "https://dukwwaehnmsuueuwacgx.supabase.co",
    anonKey: "sb_publishable_G_h9LK2G3XyK0wQGG-vbJw_HicrnOVL",
    table: "ads",
};

window.ADMEDICAL_LINK = "https://www.admedical.org/application/approval_confirm.do";

window.PAGE_SIZE = 5;

// 오류 제보 발송은 서버 측 /api/report 가 처리 (이메일 주소는 Vercel 환경변수에만 존재)
