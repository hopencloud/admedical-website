-- 요청 횟수 제한을 DB 에서 센다 (2026-11-02)
--
-- 왜 필요한가:
--   lib/guard.js 는 원래 서버 메모리에 세었다. 그런데 Vercel 은 동시 요청마다
--   인스턴스를 새로 띄우므로, 공격자가 동시에 100개를 던지면 카운터도 100개로
--   쪼개진다. 즉 "10분에 8번" 이 "10분에 8 × 동시요청수" 가 된다 — 사실상 무력.
--   DB 에 세면 인스턴스가 몇 개든 한 곳으로 모인다.
--
-- 실행 방법: Supabase 대시보드 → SQL Editor → 아래 전체 붙여넣고 Run.
--   이 파일을 실행하지 않아도 사이트는 정상 동작한다 (메모리 방식으로 후퇴).
--   실행하면 lib/guard.js 가 자동으로 DB 쪽을 쓴다 — 코드 수정 불필요.

CREATE TABLE IF NOT EXISTS rate_limits (
    key           TEXT        PRIMARY KEY,   -- 예: 'admin:1.2.3.4', 'report:1.2.3.4'
    count         INT         NOT NULL DEFAULT 0,
    reset_at      TIMESTAMPTZ NOT NULL,      -- 이 시각이 지나면 카운터 초기화
    blocked_until TIMESTAMPTZ                -- 잠금 해제 시각 (NULL 이면 잠금 아님)
);

-- service_role 만 접근. 공개 키로는 읽기·쓰기 모두 불가.
ALTER TABLE rate_limits ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE rate_limits IS
    '요청 횟수 제한 카운터. lib/guard.js 가 rl_bump/rl_clear 로만 쓴다.';


-- ----------------------------------------------------------------
-- rl_bump: 1회 시도를 기록하고 허용 여부를 돌려준다.
--
-- 한 트랜잭션 안에서 FOR UPDATE 로 행을 잠그므로, 동시 요청이 몇 개든
-- 카운터가 정확히 1씩만 올라간다 (읽고 나서 쓰는 방식은 경합에 새어나간다).
-- ----------------------------------------------------------------
CREATE OR REPLACE FUNCTION rl_bump(
    p_key         TEXT,
    p_limit       INT,
    p_window_sec  INT,
    p_block_sec   INT DEFAULT 0
)
RETURNS TABLE (allowed BOOLEAN, retry_after INT, hits INT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    r rate_limits;
    v_until TIMESTAMPTZ;
BEGIN
    -- 오래된 행 청소 (표가 작아 비용은 무시할 수준)
    DELETE FROM rate_limits
     WHERE reset_at < NOW() - INTERVAL '1 day'
       AND (blocked_until IS NULL OR blocked_until < NOW());

    INSERT INTO rate_limits (key, count, reset_at)
    VALUES (p_key, 0, NOW() + make_interval(secs => p_window_sec))
    ON CONFLICT (key) DO NOTHING;

    SELECT * INTO r FROM rate_limits WHERE key = p_key FOR UPDATE;

    -- 잠겨 있으면 그대로 거절 (카운터를 올리지 않는다)
    IF r.blocked_until IS NOT NULL AND r.blocked_until > NOW() THEN
        RETURN QUERY SELECT FALSE,
            CEIL(EXTRACT(EPOCH FROM (r.blocked_until - NOW())))::INT,
            r.count;
        RETURN;
    END IF;

    IF r.reset_at <= NOW() THEN
        UPDATE rate_limits
           SET count = 1,
               reset_at = NOW() + make_interval(secs => p_window_sec),
               blocked_until = NULL
         WHERE key = p_key
        RETURNING * INTO r;
    ELSE
        UPDATE rate_limits SET count = count + 1 WHERE key = p_key
        RETURNING * INTO r;
    END IF;

    IF r.count > p_limit THEN
        IF p_block_sec > 0 THEN
            UPDATE rate_limits
               SET blocked_until = NOW() + make_interval(secs => p_block_sec)
             WHERE key = p_key
            RETURNING * INTO r;
        END IF;
        v_until := GREATEST(COALESCE(r.blocked_until, r.reset_at), r.reset_at);
        RETURN QUERY SELECT FALSE,
            CEIL(EXTRACT(EPOCH FROM (v_until - NOW())))::INT,
            r.count;
        RETURN;
    END IF;

    RETURN QUERY SELECT TRUE, 0, r.count;
END
$$;


-- rl_clear: 로그인에 성공하면 그 IP 의 실패 기록을 지운다.
-- (지우지 않으면 10초마다 폴링하는 /admin 이 스스로 한도를 채워 잠긴다)
CREATE OR REPLACE FUNCTION rl_clear(p_key TEXT)
RETURNS VOID
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$ DELETE FROM rate_limits WHERE key = p_key $$;


-- 공개 키로는 호출조차 못 하게 한다 (service_role 전용)
REVOKE ALL ON FUNCTION rl_bump(TEXT, INT, INT, INT)  FROM anon, authenticated;
REVOKE ALL ON FUNCTION rl_clear(TEXT)                FROM anon, authenticated;

SELECT 'rate_limits + rl_bump + rl_clear 생성 완료' AS status;
