// 공용 보호 장치 — 관리자 인증, 요청 횟수 제한, 입력 길이 검사.
//
// 왜 메모리에 세는가 (한계를 알고 쓸 것):
//   Vercel 서버리스 함수는 요청이 오면 인스턴스가 뜨고, 한가해지면 사라진다.
//   그래서 아래 카운터는 "그 인스턴스가 살아있는 동안"만 유효하다
//   (바쁜 시간대에는 보통 수 분~수십 분, 한가하면 요청 한 번 만에 초기화).
//   완전한 차단 장치가 아니라 **한 곳에서 몰아치는 공격을 느리게 만드는** 장치다.
//
//   완전하게 하려면 Supabase 에 시도 기록 테이블을 두어야 하는데, 그러면 사람이
//   DDL 을 실행해야 하고 로그인 경로마다 DB 왕복이 생긴다. 관리자가 한 명이고
//   비밀번호가 충분히 길다면 "실패 시 지연 + 메모리 잠금" 으로도 무차별 대입은
//   현실적으로 불가능해진다(초당 1회도 못 찍는다). 그래서 이 조합을 택했다.

import crypto from "node:crypto";

const MAX_KEYS = 5000; // 메모리 폭주 방지

/** key -> { count, resetAt, blockedUntil } */
const buckets = new Map();

function prune(now) {
    for (const [k, v] of buckets) {
        if (v.resetAt <= now && (v.blockedUntil || 0) <= now) buckets.delete(k);
    }
}

/** 요청자 IP. Vercel 은 x-forwarded-for 의 첫 항목이 실제 클라이언트다. */
export function clientIp(req) {
    const xff = req.headers["x-forwarded-for"];
    if (typeof xff === "string" && xff.length > 0) return xff.split(",")[0].trim();
    if (Array.isArray(xff) && xff.length > 0) return String(xff[0]).trim();
    return req.headers["x-real-ip"] || req.socket?.remoteAddress || "unknown";
}

/**
 * 요청 횟수 제한. 창(windowMs) 안에서 limit 을 넘으면 막는다.
 * countOnlyFailures 모드로 쓰려면 성공 시 reset(key) 를 부르면 된다.
 * @returns {{ok: boolean, retryAfter: number}} retryAfter 는 초
 */
export function rateLimit(key, { limit, windowMs, blockMs = 0 }) {
    const now = Date.now();
    if (buckets.size > MAX_KEYS) prune(now);

    let b = buckets.get(key);
    if (!b || b.resetAt <= now) {
        b = { count: 0, resetAt: now + windowMs, blockedUntil: b?.blockedUntil || 0 };
        buckets.set(key, b);
    }

    if (b.blockedUntil > now) {
        return { ok: false, retryAfter: Math.ceil((b.blockedUntil - now) / 1000) };
    }

    b.count += 1;
    if (b.count > limit) {
        if (blockMs > 0) b.blockedUntil = now + blockMs;
        const until = Math.max(b.blockedUntil, b.resetAt);
        return { ok: false, retryAfter: Math.ceil((until - now) / 1000) };
    }
    return { ok: true, retryAfter: 0 };
}

export function reset(key) {
    buckets.delete(key);
}

/**
 * 길이가 달라도 시간이 새지 않게 비교한다.
 * 양쪽을 sha256 으로 고정 길이로 만든 뒤 timingSafeEqual 을 쓴다
 * (timingSafeEqual 은 길이가 다르면 예외를 던지고, 그 자체로 길이가 새어나간다).
 */
export function safeEqual(a, b) {
    const ha = crypto.createHash("sha256").update(String(a ?? ""), "utf8").digest();
    const hb = crypto.createHash("sha256").update(String(b ?? ""), "utf8").digest();
    return crypto.timingSafeEqual(ha, hb);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * 관리자 인증. 통과하면 true, 막혔으면 응답을 이미 보냈으므로 false.
 * 호출부: `if (!(await requireAdmin(req, res))) return;`
 *
 * - 비밀번호 비교는 safeEqual (응답 시간으로 글자를 맞추는 공격 차단)
 * - 틀리면 0.7~1.0초 지연 — 무차별 대입 속도를 바닥으로 떨어뜨린다
 * - 같은 IP 가 10분 안에 8번 틀리면 15분 잠금
 */
export async function requireAdmin(req, res) {
    const expected = process.env.ADMIN_PASSWORD;
    if (!expected) {
        res.status(500).json({ error: "ADMIN_PASSWORD 가 설정되지 않았습니다." });
        return false;
    }

    const key = `admin:${clientIp(req)}`;
    const gate = rateLimit(key, { limit: 8, windowMs: 10 * 60_000, blockMs: 15 * 60_000 });
    if (!gate.ok) {
        res.setHeader("Retry-After", String(gate.retryAfter));
        res.status(429).json({
            error: `비밀번호를 여러 번 틀렸습니다. ${Math.ceil(gate.retryAfter / 60)}분 후 다시 시도하세요.`,
        });
        return false;
    }

    const given = req.headers["x-admin-password"];
    if (!given || !safeEqual(given, expected)) {
        await sleep(700 + Math.floor(Math.random() * 300));
        res.status(401).json({ error: "비밀번호가 틀렸습니다." });
        return false;
    }

    reset(key); // 성공하면 실패 기록을 지운다 — 정상 사용자가 잠기지 않도록
    return true;
}

/**
 * 공개 엔드포인트(문의·제보)용 제한. 막혔으면 응답을 보내고 false.
 * 호출부: `if (!publicLimit(req, res, "report")) return;`
 */
export function publicLimit(req, res, name, { limit = 5, windowMs = 10 * 60_000 } = {}) {
    const gate = rateLimit(`${name}:${clientIp(req)}`, { limit, windowMs });
    if (!gate.ok) {
        res.setHeader("Retry-After", String(gate.retryAfter));
        res.status(429).json({
            error: "요청이 너무 많습니다. 잠시 후 다시 시도해주세요.",
        });
        return false;
    }
    return true;
}

/** 문자열 입력을 자르고 정리한다. 메일 본문이 통째로 밀려드는 것을 막는다. */
export function clamp(value, max) {
    return String(value ?? "").slice(0, max);
}
