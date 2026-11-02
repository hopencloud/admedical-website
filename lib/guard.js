// 공용 보호 장치 — 관리자 인증, 요청 횟수 제한, 입력 길이 검사.
//
// 카운터를 두는 곳이 두 군데다. 되는 쪽을 자동으로 쓴다.
//
//   1순위 DB (Supabase `rate_limits` + `rl_bump`/`rl_clear`)
//     인스턴스가 몇 개 떠도 카운터가 한 곳으로 모인다. 이게 진짜 차단이다.
//
//   2순위 메모리 (이 파일의 Map)
//     DB 함수가 없을 때만 쓴다. **약하다는 것을 알고 쓸 것** —
//     Vercel 은 동시 요청마다 인스턴스를 띄우므로 카운터가 요청 수만큼
//     쪼개진다. "10분에 8번" 이 "10분에 8 × 동시요청수" 가 된다.
//     순차로 찍어보는 공격은 막지만 동시에 몰아치면 뚫린다.
//
//   → DB 쪽을 켜려면 scripts/supabase_ratelimit_schema.sql 을 한 번 실행한다.
//     켜지면 이 파일은 자동으로 DB 를 쓴다 (코드 수정 불필요).
//
// 그리고 분명히: 횟수 제한은 보조 장치다. 무차별 대입을 실제로 막는 것은
// **ADMIN_PASSWORD 의 길이**다. 짧게 바꾸지 말 것.

import crypto from "node:crypto";
// 정적 import 로 둔다. 동적 import 로 하면 Vercel 번들러가 이 패키지를
// report/contact 함수에 포함시키지 않을 수 있고, 그러면 DB 카운터가
// 조용히 메모리로 후퇴한 채 영원히 그대로 남는다.
import { createClient } from "@supabase/supabase-js";

// ---------------------------------------------------------------
// 공통
// ---------------------------------------------------------------

/** 요청자 IP. Vercel 은 x-forwarded-for 의 첫 항목이 실제 클라이언트다. */
export function clientIp(req) {
    const xff = req.headers["x-forwarded-for"];
    if (typeof xff === "string" && xff.length > 0) return xff.split(",")[0].trim();
    if (Array.isArray(xff) && xff.length > 0) return String(xff[0]).trim();
    return req.headers["x-real-ip"] || req.socket?.remoteAddress || "unknown";
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 길이가 달라도 시간이 새지 않게 비교한다 (sha256 으로 길이를 고정한 뒤 비교). */
export function safeEqual(a, b) {
    const ha = crypto.createHash("sha256").update(String(a ?? ""), "utf8").digest();
    const hb = crypto.createHash("sha256").update(String(b ?? ""), "utf8").digest();
    return crypto.timingSafeEqual(ha, hb);
}

/** 문자열 입력을 자른다. 메일 본문이 통째로 밀려드는 것을 막는다. */
export function clamp(value, max) {
    return String(value ?? "").slice(0, max);
}

// ---------------------------------------------------------------
// 2순위: 메모리 카운터 (DB 가 없을 때만)
// ---------------------------------------------------------------

const MAX_KEYS = 5000;
/** key -> { count, resetAt, blockedUntil } */
const buckets = new Map();

function prune(now) {
    for (const [k, v] of buckets) {
        if (v.resetAt <= now && (v.blockedUntil || 0) <= now) buckets.delete(k);
    }
}

export function memoryBump(key, { limit, windowMs, blockMs = 0 }) {
    const now = Date.now();
    if (buckets.size > MAX_KEYS) prune(now);

    let b = buckets.get(key);
    if (!b || b.resetAt <= now) {
        b = { count: 0, resetAt: now + windowMs, blockedUntil: b?.blockedUntil || 0 };
        buckets.set(key, b);
    }
    if (b.blockedUntil > now) {
        return { ok: false, retryAfter: Math.ceil((b.blockedUntil - now) / 1000), hits: b.count };
    }
    b.count += 1;
    if (b.count > limit) {
        if (blockMs > 0) b.blockedUntil = now + blockMs;
        const until = Math.max(b.blockedUntil, b.resetAt);
        return { ok: false, retryAfter: Math.ceil((until - now) / 1000), hits: b.count };
    }
    return { ok: true, retryAfter: 0, hits: b.count };
}

export function memoryClear(key) {
    buckets.delete(key);
}

// ---------------------------------------------------------------
// 1순위: DB 카운터
// ---------------------------------------------------------------

let supabase = null;
/** null = 아직 모름, true = DB 사용 가능, false = 없음(메모리로 후퇴) */
let dbUsable = null;

function db() {
    if (supabase) return supabase;
    const url = process.env.SUPABASE_URL;
    const key = process.env.SUPABASE_SERVICE_KEY;
    if (!url || !key) return null;
    supabase = createClient(url, key, { auth: { persistSession: false } });
    return supabase;
}

/** @returns {Promise<{ok:boolean, retryAfter:number, hits:number}|null>} null = DB 못 씀 */
async function dbBump(key, { limit, windowMs, blockMs = 0 }) {
    if (dbUsable === false) return null;
    const client = db();
    if (!client) { dbUsable = false; return null; }

    try {
        const { data, error } = await client.rpc("rl_bump", {
            p_key: key,
            p_limit: limit,
            p_window_sec: Math.round(windowMs / 1000),
            p_block_sec: Math.round(blockMs / 1000),
        });
        if (error) throw new Error(error.message);
        const row = Array.isArray(data) ? data[0] : data;
        if (!row) throw new Error("빈 응답");
        dbUsable = true;
        return { ok: row.allowed === true, retryAfter: row.retry_after || 0, hits: row.hits || 0 };
    } catch (e) {
        // 함수가 없으면(스키마 미적용) 이 인스턴스에서는 다시 시도하지 않는다.
        dbUsable = false;
        console.warn("[guard] DB 횟수 제한 사용 불가 — 메모리로 후퇴:", e.message);
        return null;
    }
}

async function dbClear(key) {
    if (dbUsable !== true) return;
    try {
        await db().rpc("rl_clear", { p_key: key });
    } catch (e) {
        console.warn("[guard] rl_clear 실패:", e.message);
    }
}

/** DB 를 먼저 쓰고, 안 되면 메모리로. */
async function bump(key, opts) {
    const viaDb = await dbBump(key, opts);
    if (viaDb) return { ...viaDb, backend: "db" };
    return { ...memoryBump(key, opts), backend: "memory" };
}

async function clear(key) {
    await dbClear(key);
    memoryClear(key);
}

/** 지금 어느 쪽으로 세고 있는지 — 운영 점검용. */
export function limiterBackend() {
    return dbUsable === true ? "db" : dbUsable === false ? "memory" : "unknown";
}

// ---------------------------------------------------------------
// 관리자 인증
// ---------------------------------------------------------------

const ADMIN_LIMIT = 8;
const ADMIN_WINDOW_MS = 10 * 60_000;
const ADMIN_BLOCK_MS = 15 * 60_000;

/**
 * 관리자 인증. 통과하면 true, 막혔으면 응답을 이미 보냈으므로 false.
 * 호출부: `if (!(await requireAdmin(req, res))) return;`
 *
 * - 비밀번호 비교는 safeEqual (응답 시간으로 글자를 맞추는 공격 차단)
 * - 틀리면 0.7~1.0초 지연
 * - 같은 IP 가 10분에 8번 틀리면 15분 잠금
 * - 맞으면 실패 기록을 지운다 (10초마다 폴링하는 /admin 이 스스로 잠기지 않도록)
 */
export async function requireAdmin(req, res) {
    const expected = process.env.ADMIN_PASSWORD;
    if (!expected) {
        res.status(500).json({ error: "ADMIN_PASSWORD 가 설정되지 않았습니다." });
        return false;
    }

    const key = `admin:${clientIp(req)}`;
    const gate = await bump(key, {
        limit: ADMIN_LIMIT, windowMs: ADMIN_WINDOW_MS, blockMs: ADMIN_BLOCK_MS,
    });
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

    // 이번 요청 자체가 1 을 올렸으므로, hits 가 1 이면 지울 것이 없다.
    if (gate.hits > 1) await clear(key);
    return true;
}

// ---------------------------------------------------------------
// 공개 엔드포인트 (문의·제보)
// ---------------------------------------------------------------

/**
 * 막혔으면 응답을 보내고 false.
 * 호출부: `if (!(await publicLimit(req, res, "report"))) return;`
 */
export async function publicLimit(req, res, name, { limit = 5, windowMs = 10 * 60_000 } = {}) {
    const gate = await bump(`${name}:${clientIp(req)}`, { limit, windowMs });
    if (!gate.ok) {
        res.setHeader("Retry-After", String(gate.retryAfter));
        res.status(429).json({ error: "요청이 너무 많습니다. 잠시 후 다시 시도해주세요." });
        return false;
    }
    return true;
}
