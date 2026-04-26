-- =====================================================
-- 의료광고 심의 통과 시안 검색 — Supabase 스키마
-- =====================================================
-- 사용법:
--   1. Supabase 대시보드 좌측 메뉴 → SQL Editor 클릭
--   2. "+ New query" 클릭
--   3. 이 파일 내용 전체를 복사해서 붙여넣기
--   4. 우측 하단 "Run" 버튼 클릭 (또는 Ctrl/Cmd + Enter)
--   5. 좌측 "Table Editor"에서 ads 테이블 생성됐는지 확인
-- =====================================================

-- 1. 한국어 부분 일치 검색을 위한 trigram 확장 활성화
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. 메인 테이블: 광고 (심의번호 단위)
CREATE TABLE IF NOT EXISTS ads (
    review_num         INTEGER     PRIMARY KEY,
    review_date        DATE        NOT NULL,
    review_no_display  TEXT        NOT NULL,
    ocr_text           TEXT        NOT NULL DEFAULT '',
    page_count         INTEGER     NOT NULL DEFAULT 1,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  ads                    IS '의료광고 심의 통과 시안 (심의번호 단위 1행)';
COMMENT ON COLUMN ads.review_num         IS '심의번호 일련번호 (예: 211923)';
COMMENT ON COLUMN ads.review_date        IS '심의 통과일';
COMMENT ON COLUMN ads.review_no_display  IS '표시용 심의번호 (예: 260424-중-211923)';
COMMENT ON COLUMN ads.ocr_text           IS '마스킹된 광고 문구 (검색 대상)';
COMMENT ON COLUMN ads.page_count         IS '시안 페이지 수';

-- 3. 인덱스
-- 3-1. 심의일 정렬/필터링용 (최신순 표시)
CREATE INDEX IF NOT EXISTS idx_ads_review_date_desc
    ON ads (review_date DESC);

-- 3-2. 한국어 부분 일치 검색용 GIN 인덱스
CREATE INDEX IF NOT EXISTS idx_ads_ocr_text_trgm
    ON ads USING GIN (ocr_text gin_trgm_ops);

-- 4. updated_at 자동 갱신 트리거
CREATE OR REPLACE FUNCTION trg_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_ads_updated_at ON ads;
CREATE TRIGGER set_ads_updated_at
    BEFORE UPDATE ON ads
    FOR EACH ROW
    EXECUTE FUNCTION trg_set_updated_at();

-- 5. Row Level Security (RLS) 활성화 — 보안 필수
ALTER TABLE ads ENABLE ROW LEVEL SECURITY;

-- 5-1. 누구나 읽기 가능 (검색 결과 노출용)
DROP POLICY IF EXISTS "ads_public_read" ON ads;
CREATE POLICY "ads_public_read"
    ON ads
    FOR SELECT
    TO anon, authenticated
    USING (true);

-- 참고: 쓰기(INSERT/UPDATE/DELETE)는 service_role 키를 가진
--       서버 스크립트만 가능. service_role은 RLS를 자동 우회하므로
--       별도 정책 불필요.

-- =====================================================
-- 확인 쿼리 (실행 후 결과 보고 잘 만들어졌는지 확인)
-- =====================================================
SELECT
    'ads 테이블 생성 완료' AS status,
    (SELECT COUNT(*) FROM ads) AS row_count;
