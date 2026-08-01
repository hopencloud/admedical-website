-- =====================================================
-- 뉴스 게시판 — 설정 + 발행 이력 테이블
-- =====================================================
-- 사용법:
--   1. Supabase 대시보드 → SQL Editor → New query
--   2. 이 파일 내용 전체 복사·붙여넣기
--   3. Run 클릭
-- =====================================================

-- ---------- 1. 설정 (킬스위치) ----------
-- 행 1개만 존재. /admin 에서 자동 발행을 껐다 켤 수 있게 하는 스위치.
CREATE TABLE IF NOT EXISTS news_settings (
    id             SMALLINT     PRIMARY KEY DEFAULT 1,
    auto_publish   BOOLEAN      NOT NULL DEFAULT TRUE,   -- FALSE 면 워크플로우가 아무것도 안 하고 종료
    daily_count    SMALLINT     NOT NULL DEFAULT 1,      -- 하루에 발행할 글 수
    note           TEXT,                                  -- 껐다면 왜 껐는지 메모
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT news_settings_singleton CHECK (id = 1)
);

INSERT INTO news_settings (id, auto_publish, daily_count)
VALUES (1, TRUE, 1)
ON CONFLICT (id) DO NOTHING;

COMMENT ON TABLE  news_settings IS '뉴스 자동 발행 제어 (행 1개 고정)';
COMMENT ON COLUMN news_settings.auto_publish IS 'FALSE 로 바꾸면 다음 실행부터 발행 중단 — /admin 킬스위치';


-- ---------- 2. 발행 이력 ----------
-- 정적 HTML 파일이 실제 콘텐츠의 원본이고, 이 테이블은 중복 방지 + /admin 목록용 미러.
CREATE TABLE IF NOT EXISTS news_posts (
    slug           TEXT         PRIMARY KEY,             -- 2026-08-01-의료광고-규제-개편
    title          TEXT         NOT NULL,
    summary        TEXT,
    published_date DATE         NOT NULL,
    topic_key      TEXT,                                  -- 중복 주제 판별용 정규화 키
    source_links   JSONB        NOT NULL DEFAULT '[]'::jsonb,
    tags           JSONB        NOT NULL DEFAULT '[]'::jsonb,
    cover_image    TEXT,                                  -- /assets/news/....png
    status         TEXT         NOT NULL DEFAULT 'published',  -- 'published' | 'retracted'
    model_used     TEXT,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_posts_date_desc
    ON news_posts (published_date DESC);

CREATE INDEX IF NOT EXISTS idx_news_posts_topic
    ON news_posts (topic_key);

COMMENT ON TABLE  news_posts IS '자동 발행된 뉴스 글 이력 (원본은 website/news/*.html)';
COMMENT ON COLUMN news_posts.topic_key IS '같은 주제 재발행 방지용 키';
COMMENT ON COLUMN news_posts.status IS 'retracted 로 바꾸면 다음 렌더링 때 목록에서 제외';


-- ---------- RLS ----------
-- 두 테이블 모두 service_role 키로만 접근 (Vercel 함수 / GitHub Actions).
ALTER TABLE news_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE news_posts    ENABLE ROW LEVEL SECURITY;


-- 확인
SELECT 'news_settings / news_posts 생성 완료' AS status;


-- ---------- 3. 발행 진행상황 ----------
-- /admin 이 폴링해 "지금 몇 건 중 몇 건, 어느 단계인지" 를 보여준다.
CREATE TABLE IF NOT EXISTS news_runs (
    id             BIGSERIAL    PRIMARY KEY,
    status         TEXT         NOT NULL DEFAULT 'running',  -- running | done | failed | skipped
    total          SMALLINT     NOT NULL DEFAULT 1,          -- 이번 실행에서 발행할 목표 편수
    done           SMALLINT     NOT NULL DEFAULT 0,          -- 완료한 편수
    stage          TEXT,                                      -- 뉴스 수집 / 원고 작성 / 이미지 제작 …
    detail         TEXT,                                      -- 단계 상세
    current_title  TEXT,                                      -- 지금 쓰고 있는 기사 제목
    started_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_news_runs_started_desc ON news_runs (started_at DESC);

ALTER TABLE news_runs ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE news_runs IS '뉴스 자동 발행 실행별 진행상황 (관리자 대시보드 표시용)';

SELECT 'news_runs 생성 완료' AS status;


-- ---------- 4. 뉴스레터 구독자 ----------
CREATE TABLE IF NOT EXISTS newsletter_subscribers (
    email           TEXT         PRIMARY KEY,
    token           TEXT         NOT NULL UNIQUE,      -- 수신 해지 링크용 (추측 불가한 난수)
    status          TEXT         NOT NULL DEFAULT 'active',  -- active | unsubscribed | bounced
    subscribed_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    unsubscribed_at TIMESTAMPTZ,
    last_sent_at    TIMESTAMPTZ,
    send_count      INTEGER      NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_newsletter_status ON newsletter_subscribers (status);

ALTER TABLE newsletter_subscribers ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE  newsletter_subscribers IS '뉴스레터 구독자. service_role 키로만 접근.';
COMMENT ON COLUMN newsletter_subscribers.token IS '메일 하단 수신 해지 링크에 쓰는 난수 토큰';

SELECT 'newsletter_subscribers 생성 완료' AS status;
