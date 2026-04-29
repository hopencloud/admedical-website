# 의료광고 심의 통과 시안 검색 사이트

## 프로젝트 목적
병의원 마케터를 위한 의료광고 심의 통과 시안 검색 서비스. 사용자가 키워드를 입력하면 통과된 광고 텍스트와 심의번호를 보여주고, 원본은 대한의사협회 의료광고심의위원회 사이트에서 직접 확인하도록 안내한다.

## 핵심 원칙
- **이미지 노출 금지**: OCR 추출 텍스트만 표시. 저작권은 해당 병원 소유이므로 이미지 재배포 안 함.
- **개인정보 마스킹**: 병원명/의원명/클리닉명, 의사명, 전화번호, 주소는 자동 마스킹 처리.
- **레퍼런스 모델**: 인덱스 역할만. 원본은 admedical.org에서 심의번호로 조회 안내.
- **카테고리 미사용**: 진료과 분류는 사용하지 않음. 키워드 검색만으로 충분.

## 데이터 흐름
[수집] collector.py → 신규 시안 다운로드
  ↓
[인덱싱] indexer.py → index.sqlite 에 OCR 텍스트 추가
  ↓
[통계] compute_statistics.py / compute_weekly_top20.py / compute_monthly_top20.py
  ↓
[업로드] sync_to_supabase.py → Supabase로 마스킹된 데이터 전송
  ↓
[배포] Vercel 정적 사이트 (Supabase API 호출)

## 데이터 구조
- **SQLite (로컬)**: 페이지별 1행
- **Supabase (목표)**: 심의번호별 1행 (모든 페이지 OCR 텍스트 결합)

## 콘텐츠 - 시간 기반 통계
- 메인: 오늘/이번주/이번달 통과 건수, 일자별 그래프, 마지막 업데이트 시각
- 지난주 TOP 20 통과 표현 (매주 월요일 갱신, AI 정제)
- 지난달 TOP 20 통과 표현 (매월 1일 갱신, AI 정제)

## TOP 20 추출 방식
1. N-gram (2~4단어) 추출 + 빈도수 카운트
2. 불용어 사전으로 1차 필터링 (정형구, OCR 오류)
3. 상위 50~100개 후보 → OpenAI gpt-4o-mini로 정제
4. AI가 마케팅 가치 있는 20개 선별
5. AI 호출 실패 시 빈도수 기반 결과로 fallback

## 실행 (수동, 관리자 대시보드 /admin)
- 일일 자동(launchd)은 폐기. 사장님이 /admin 에서 버튼으로 트리거.
- 맥북의 admin_agent.py 가 Supabase admin_jobs 큐를 5초마다 polling 하여 subprocess 로 실행.
- 작업 종류: collector / indexer (OCR+sync) / pipeline(전체 = daily_pipeline.sh)
- 매주 월요일·매월 1일에는 pipeline 작업이 weekly/monthly TOP20 도 함께 갱신 (스크립트 내부 로직).

## 웹사이트 페이지 구조
- 메인: 통계 대시보드 + 검색
- 검색 결과: 텍스트 + 심의번호 + admedical.org 링크
- 콘텐츠: 심의 신청 절차 / 심의 대상 / 심의 제외 광고 / 지난주·지난달 TOP 20
- 필수: 이용약관 / 개인정보처리방침 / 문의(이메일)

## 기술 스택
- 수집/인덱싱: Python + PaddleOCR
- AI 정제: OpenAI gpt-4o-mini (주/월 1회만 호출)
- DB: Supabase (PostgreSQL, Seoul region)
- 프론트: 정적 HTML + Tailwind CSS + Vanilla JS + Chart.js
- 호스팅: Vercel (무료)
- 도메인: 카페24 또는 가비아

## 비용
- Vercel: 무료
- Supabase: 무료 (월 500MB DB)
- OpenAI: 월 약 100~300원 (주/월 1회만 호출)
- 도메인: 연 1.5~2만원
- 합계: 연 약 2만원

## 수익 모델
- Google AdSense (사이트 안정 운영 + 콘텐츠 충실 후 신청)
- 향후: 의료광고 대행/마케팅 에이전시 직접 광고