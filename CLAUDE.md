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

## 뉴스 게시판 (/news) — 매일 자동 발행
- GitHub Actions `news-daily.yml` 이 매일 04:00 KST 실행. 맥북과 무관하게 클라우드에서 동작.
- 파이프라인: `scripts/news_pipeline.py`
  1. `news_sources.py` — 의료 전문지 RSS 5곳 + 복지부 보도자료 (+OpenAI 웹검색) 수집
  2. `news_writer.py` — 주제 선정 → 초고 → 분량 보강 → 자체 검수 → **수치 검증**
  3. `news_images.py` — AI 일러스트 2장(gpt-image-2 high) + 인포그래픽 SVG + 썸네일(Pillow)
  4. `news_render.py` — 정적 HTML 생성, 목록·사이트맵 갱신
  5. `news_feed.py` — RSS 2.0 피드(`/rss.xml`) 생성
- **원칙**: 기사 본문은 크롤링하지 않는다. RSS 제목/요약만 재료로 쓰고 출처를 명시한다.
- **수치 검증**: 본문의 모든 숫자가 근거 자료나 자체 통계에 실제로 있는지 파이썬이 대조.
  없으면 정정 패스를 돌리고, 그래도 남으면 발행을 포기한다 (`unsupported_numbers`).
- **도표 데이터는 AI가 만들지 않는다**. `statistics.json` 실측값만 사용하며 0건인 날은 제외.
- **도식은 기사마다 유형이 달라야 한다.** AI가 comparison / timeline / process / checklist /
  stat_trend 중에서 고르고 파이썬이 SVG 로 그린다. 한글이 정확해야 하는 텍스트는 전부 SVG·썸네일에 넣고,
  AI 이미지에는 글자를 넣지 않는다(모델이 한글을 깨뜨림).
- **이미지 프롬프트는 기사에서 뽑는다.** `images[].concept` 에 그 기사에서만 나올 장면을 구체적으로 묘사.
  공통 톤은 `news_images.HOUSE_STYLE` 한 곳에서 관리.
- **썸네일**: 1200x630, 표지 이미지 위에 제목을 한글로 얹은 일관 디자인 카드.
  목록·메인·OG 이미지에 모두 이 썸네일을 쓴다. GitHub Actions 는 `fonts-nanum` 설치 필요.
- **정렬은 `published_at`(시각) 기준**. 같은 날 여러 편이면 날짜만으로 순서가 뒤집힌다.
- 진행상황: `news_runs` 테이블에 단계별로 기록 → /admin 이 5초 간격 폴링해 표시.
- **시각자료 3종이 기본**: 사진(photo, 실사) 1 + 일러스트(illustration, 플랫벡터) 1 + 도식 SVG 1.
  셋 중 하나라도 없으면 발행하지 않는다.
- **중복 주제 차단은 파이썬이 한다**. 최근 10편이 근거로 쓴 기사 링크를 후보에서 제외하고,
  제목 바이그램 유사도 0.28 이상이면 주제를 다시 고른다 (AI 지시만으로는 같은 주제가 반복됐다).
- 검수·수치 정정으로 분량이 줄면 한 번 더 보강한 뒤 재검증한다.
- 킬스위치: Supabase `news_settings.auto_publish` → /admin 에서 토글.

## 뉴스레터
- 구독: `/api/subscribe` → Supabase `newsletter_subscribers` (이메일만 받음, 허니팟으로 봇 차단)
- 해지: 메일 하단 `/api/unsubscribe?token=` 원클릭. `List-Unsubscribe` 헤더도 넣는다.
- 발송: `scripts/news_mailer.py` — 커밋·푸시 **이후**에 실행 (링크가 살아있어야 함).
  기존 문의 메일과 같은 SMTP(Gmail) 재사용. GitHub Secrets 에 `SMTP_USER`/`SMTP_PASS` 필요.
- Gmail SMTP 는 하루 발송량 제한(대략 500건)이 있다. 구독자가 늘면 전용 발송 서비스로 옮길 것.

## 자동 검증 (회귀 방지)
- `scripts/validate_site.py` 가 사이트 불변조건을 검사한다. **규칙을 바꾸면 검사도 같이 고칠 것.**
  - 로컬: `python scripts/validate_site.py` / 라이브: `--live-only`
  - GitHub Actions `validate.yml` 이 push 마다(로컬) + 매일 05:00 KST(라이브) 실행
  - `news-daily.yml` 은 커밋 **직전**에 검사 — 규칙을 깨는 기사는 배포되지 않는다
- 검사 항목은 전부 **실제로 났던 버그**다. 새 버그를 고칠 때는 검사 항목을 먼저 추가할 것.
  - 내부 링크·canonical·사이트맵·RSS 에 `.html` 확장자 (308 리다이렉트 → 네이버 수집 실패)
  - JS 주입 헤더 잔존 (Yeti 가 내부 링크를 못 읽음)
  - `<img>` alt 누락/빈 값
  - JSON-LD 파싱 실패
  - **통계 '어제 0건'** — 게시 전 데이터를 0건으로 노출 금지
  - 뉴스 인덱스와 실제 HTML/이미지 파일 불일치
  - 애드센스 스니펫 누락, ads.txt/robots.txt 누락
  - 라이브: 사이트맵 전 URL 200(리다이렉트 없음), 메인 정적 본문 1,000자·내부링크 10개 이상

## SEO/AEO/GEO 규칙
- URL은 **확장자 없이** (`/guide/faq`). vercel.json `cleanUrls: true` 라 `.html` 링크는 308 리다이렉트된다.
  내부 링크·canonical·og:url·JSON-LD·사이트맵 모두 확장자 없이 유지할 것.
- 모든 `<img>`에 의미 있는 `alt` 필수. 뉴스 이미지는 AI가 기사 맥락에 맞춰 alt를 작성한다.
- 기사 페이지는 NewsArticle + BreadcrumbList + FAQPage 스키마 3종을 넣는다.
- `robots.txt` 는 생성형 AI 크롤러(GPTBot/ClaudeBot/PerplexityBot 등)를 명시적으로 허용한다.
- `/llms.txt` 로 AI 검색엔진에 사이트 성격·한계·주요 URL을 제공한다.
- **모든 페이지 공통**: H1 정확히 1개 + H2 1개 이상, canonical, meta description,
  OG 전체(title/description/image/image:alt/url/locale), twitter:card, JSON-LD 스키마 1개 이상.
  `validate_site.py` 가 이걸 검사하므로 새 페이지를 만들 때 반드시 채울 것.
- 기사 페이지는 3줄 요약 박스(`.article-summary`) + 목차 + 본문 키워드 자동 내부링크를 넣는다.
  요약 박스는 `speakable` 스키마 대상이라 AI 검색이 그대로 인용한다.

## 웹사이트 페이지 구조
- 메인: 통계 대시보드 + 검색 + 최신 인사이트 3건
- 검색 결과: 텍스트 + 심의번호 + admedical.org 링크
- 콘텐츠: 심의 신청 절차 / 심의 대상 / 심의 제외 광고 / 지난주·지난달 TOP 20
- 의료광고 인사이트: /news (매일 자동 발행)
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