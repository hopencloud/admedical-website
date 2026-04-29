-- =====================================================
-- 관리자 대시보드 — 작업 큐 테이블
-- =====================================================
-- 사용법:
--   1. Supabase 대시보드 → SQL Editor → New query
--   2. 이 파일 내용 전체 복사·붙여넣기
--   3. Run 클릭
-- =====================================================

CREATE TABLE IF NOT EXISTS admin_jobs (
    id           BIGSERIAL    PRIMARY KEY,
    job_type     TEXT         NOT NULL,                          -- 'collector' | 'indexer' | 'pipeline'
    status       TEXT         NOT NULL DEFAULT 'pending',         -- 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
    progress     INTEGER      NOT NULL DEFAULT 0,                 -- 0~100 (인디케이터용)
    counter      INTEGER      NOT NULL DEFAULT 0,                 -- 처리한 건수 (예: 다운로드된 시안 수)
    message      TEXT,                                            -- 마지막 상태 메시지
    log_tail     TEXT,                                            -- 최근 로그 라인 (50줄 누적)
    error_text   TEXT,                                            -- 실패 사유
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ
);

COMMENT ON TABLE  admin_jobs IS '관리자 대시보드에서 트리거한 백엔드 작업 큐';
COMMENT ON COLUMN admin_jobs.job_type IS 'collector=신규 시안 다운로드, indexer=OCR 인덱싱, pipeline=전체 일일 파이프라인';
COMMENT ON COLUMN admin_jobs.status   IS 'pending → running → done|failed|cancelled';

CREATE INDEX IF NOT EXISTS idx_admin_jobs_status_created
    ON admin_jobs (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_admin_jobs_created_desc
    ON admin_jobs (created_at DESC);

-- RLS: anon/authenticated 모두 차단. service_role 키만 사용.
ALTER TABLE admin_jobs ENABLE ROW LEVEL SECURITY;
-- 별도 정책 미생성 → 일반 키로는 SELECT/INSERT 모두 불가.
-- Vercel 서버리스 함수와 로컬 agent 모두 service_role 키로 접근.

-- 확인
SELECT 'admin_jobs 테이블 생성 완료' AS status,
       (SELECT COUNT(*) FROM admin_jobs) AS row_count;
