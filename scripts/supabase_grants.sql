-- =====================================================
-- ads 테이블 권한 부여 (1번만 실행)
-- =====================================================
-- 사용법:
--   1. Supabase 대시보드 → SQL Editor → + New query
--   2. 이 파일 내용 복사·붙여넣기
--   3. Run 클릭
--   4. 화면 하단에 "Success. No rows returned" 뜨면 성공
-- =====================================================

-- 익명 사용자(웹사이트 검색)는 읽기만 가능
GRANT SELECT ON TABLE public.ads TO anon, authenticated;

-- 서버 스크립트(service_role)는 모든 권한
GRANT ALL ON TABLE public.ads TO service_role;

-- 새로 생기는 함수/시퀀스 등도 자동 권한 부여 (안전망)
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO anon, authenticated;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON TABLES TO service_role;
