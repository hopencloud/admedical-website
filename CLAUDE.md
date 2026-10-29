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
- GitHub Actions `news-daily.yml` 이 매일 05:30 KST 실행. 맥북과 무관하게 클라우드에서 동작.
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
- **업체 홍보 기사 차단도 파이썬이 한다** (`news_sources.PROMO_PATTERNS`).
  리뉴얼·오픈·출시·제휴·수상·주년·기부·실적 등이 제목에 있으면 후보에서 뺀다.
  단 제도·규제 단어(`POLICY_RESCUE`)가 같이 있으면 살린다 — "심의 대상 확대 시행" 같은 것.
  프롬프트의 "홍보성 소식 제외" 지시만으로는 병원만 걸러지고 업체는 통과했다
  (2026-08-19 에 한 업체의 플랫폼 리뉴얼 보도자료가 기사로 나갔다).
- **중복 주제 차단은 파이썬이 한다**. 최근 10편이 근거로 쓴 기사 링크를 후보에서 제외하고,
  제목 바이그램 유사도 0.28 이상이면 주제를 다시 고른다 (AI 지시만으로는 같은 주제가 반복됐다).
- 검수·수치 정정으로 분량이 줄면 한 번 더 보강한 뒤 재검증한다.
- 킬스위치: Supabase `news_settings.auto_publish` → /admin 에서 토글.
- **발행 편수는 하루 1편**(`news_settings.daily_count`). 주 1회 5편으로 몰아봤다가 되돌렸다.
  사흘에 11편 → 일주일 공백 같은 패턴이 구글에는 대량생산 신호로 읽히고,
  5편을 한 번에 쓰면 넷째 편쯤부터 소재가 떨어져 반려된다.
- **한 편이 반려돼도 다음 편을 시도한다.** 예전엔 `if not post: break` 라서
  첫 편이 걸리면 그날 발행이 통째로 0편이 됐다 (2026-08-10 실제 발생).
  목표 편수를 채울 때까지 최대 `count*3` 회 시도하고, 연속 3회 반려 시 중단한다.
- **제목이 겹치면 기사를 버리지 말고 제목만 다시 짓는다** (`retitle_article`).
  좁은 분야라 제목은 계속 비슷하게 나온다. 원고와 검수를 다 통과한 기사를
  제목 때문에 폐기하면 안 된다.
- **자체 집계 기사는 제목 유사도로 막지 않는다.** 같은 데이터를 다루므로 제목이
  구조적으로 비슷하다. 유사도 0.28 을 그대로 적용했더니 매일 3번 다 걸려
  17일간 0편이 나갔다. 대신 **같은 각도를 최근에 썼는지**로 판정한다
  (`news_data_story` 가 날짜 기준 5종 각도를 돌린다).
- 재시도할 때는 이번 실행에서 손댄 근거 기사를 후보에서 뺀다(`tried_links`).
  안 그러면 같은 주제를 다시 골라 같은 이유로 또 반려된다.

## 뉴스레터
- 구독: `/api/subscribe` → Supabase `newsletter_subscribers` (이메일만 받음, 허니팟으로 봇 차단)
- 해지: 메일 하단 `/api/unsubscribe?token=` 원클릭. `List-Unsubscribe` 헤더도 넣는다.
- **기사는 매일, 메일은 주 1회(월요일) 지난 7일치를 묶어서.** 매일 보내면 구독 해지가
  늘고 Gmail 발송 한도에도 부담이 된다. 워크플로가 요일을 보고 판단하며,
  `mail_only=true` 로 수동 실행하면 요일과 무관하게 나간다.
- 발송: `scripts/news_mailer.py --days 7` — 커밋·푸시 **이후**에 실행 (링크가 살아있어야 함).
  기존 문의 메일과 같은 SMTP(Gmail) 재사용. GitHub Secrets 에 `SMTP_USER`/`SMTP_PASS` 필요.
- Gmail SMTP 는 하루 발송량 제한(대략 500건)이 있다. 구독자가 늘면 전용 발송 서비스로 옮길 것.
- **포트를 하나만 쓰지 않는다.** 2026-10-29 GitHub 러너에서 465/SSL 접속이
  `SMTPServerDisconnected: Connection unexpectedly closed` 로 끊겼다 (자격증명은 정상).
  러너가 Azure 대역이라 Gmail 쪽에서 끊는 것으로 보인다. `connect_smtp()` 가
  465/SSL → 587/STARTTLS 를 번갈아 3회까지 재시도한다. 비밀번호 거부(535)는 재시도 안 한다.
  두 포트 다 막히면 전용 발송 서비스(Resend 등)나 맥북 발송으로 옮길 것.
- **발송이 0건이면 run 을 실패로 끝낸다.** 메일 단계를 워크플로의 맨 마지막에 두고
  `continue-on-error` 를 뺐다. `news_mailer.py` 는 (보낸 통수, 대상 수) 를 돌려주며
  보낼 기사와 보낼 사람이 둘 다 있는데 0통이면 종료 코드 1 이다.
  구독자 0명이거나 7일치 기사가 없는 건 고장이 아니라 종료 코드 0.
  예전엔 어떤 경우든 0 이어서 2026-10-05·10-12 월요일 발송 누락을 한 달간 몰랐다.
- **기사가 안 나가면 메일도 자동으로 안 나간다.** 월요일 메일은 지난 7일치를 묶는데
  그 창이 비면 발송을 건너뛴다. 2026-10-19·10-26 메일이 안 간 이유가 이것이다
  (10/09~10/26 발행 중단). 즉 발행이 멈추면 메일도 조용히 멈추므로,
  `validate_site.py` 의 기사 신선도 검사가 뉴스레터의 1차 알람 역할도 한다.

## 수집 파일 경로 — 한 곳으로 통일할 것
`collector.py`(저장) · `batch_vision_ocr.py`(OCR) · `prune_images.py`(삭제) 세 곳이
**반드시 같은 폴더**를 봐야 한다. 기본값은 `기존데이터/수집`
(환경변수 `ADMEDICAL_SAVE_DIR` 로 오버라이드, 클라우드 파이프라인은 /tmp).

예전에는 양쪽 다 `~/Desktop/admedical_ads` 를 썼다(파이프라인이 OCR 에 `--src` 로
같은 경로를 넘겼다). 동작은 했지만 바탕화면에 데이터가 쌓이는 구조여서 위치만 옮겼다.
**`daily_pipeline.sh` 에서 `--src` 를 다시 주면 경로가 어긋나므로 주지 말 것.**

## 시안 이미지 자동 삭제
이 사이트는 시안 이미지를 노출하지 않는다. OCR 텍스트만 쓰므로 원본은 중간 재료다.
`prune_images.py` 가 매일 파이프라인 끝에서 정리한다 (`--apply`).
지우는 조건 — 하나라도 어긋나면 남긴다:
  1. `ocr_done = 1` 2. OCR 텍스트가 비어 있지 않음 3. Supabase 동기화 완료
  4. 심의일이 보관 기간(기본 7일)보다 오래됨
동영상·음성(mp4/mp3)은 OCR 대상이 아니라 DB 에 행조차 없다. 기본으로 남기며
`--include-media` 를 줘야 지운다.

## 수집은 왜 맥북에서만 도는가 (2026-08-02 확인)
`admedical.org` 는 **데이터센터 IP 대역을 통째로 차단**한다. 국가 차단이 아니다.
직접 측정한 결과:

| 경로 | 나가는 IP | 결과 |
|---|---|---|
| 맥북 (KT 가정용) | 119.192.246.160 (KR) | 6/6 성공 |
| GitHub Actions (Azure) | 미국 | 0/6 차단 |
| NordVPN 한국 서버 | 187.15.97.43 (KR) | 0/6 차단 (같은 터널로 naver.com 은 2/2) |

→ **클라우드 VM·VPS·VPN 은 전부 같은 이유로 막힌다.** 오라클/국내 VPS 도 마찬가지다.
가정용 회선에 물린 상시 기기(맥북, 라즈베리파이 등)만 가능하다.
재확인이 필요하면 `.github/workflows/probe-admedical.yml`, `probe-nordvpn.yml` 을 수동 실행할 것.

수집이 멈추면 `validate_site.py` 가 4일 기준으로 잡아 Actions 를 실패시킨다.

## macOS git 이 죽는 경우 (2026-10-15 ~ 21, 일주일 무음 실패)
맥북의 `git` 과 `python3` 은 Xcode Command Line Tools 껍데기다.
Xcode 가 업데이트되면 **라이선스에 다시 동의할 때까지 모든 git 명령이 실패**한다.

    You have not agreed to the Xcode license agreements.

이때 파이프라인은 끝까지 돌지만 커밋·푸시만 실패하고, 로그에는 `[git] commit 실패`
한 줄만 남는다. 사이트 통계가 일주일 멈췄는데 아무도 몰랐다.

복구: 터미널에서 `sudo xcodebuild -license accept` (비밀번호 필요, 사람만 가능).

`daily_pipeline.sh` 가 시작할 때 `git --version` 으로 확인하고, 죽어 있으면
로그 맨 위에 복구 명령과 함께 크게 찍는다.
`validate_site.py --live-only` 의 라이브 통계 검사가 이 상황을 잡아낸다.

## 한 단계가 전체를 막지 않게 (2026-10-09 / 10-21)
OpenAI 호출에 **타임아웃을 반드시 준다**. 안 주면 소켓이 반쯤 끊겼을 때
(맥북 절전 복귀 등) 끝없이 기다린다. 실제로 두 번 났다.
  · `vision_ocr.py` — OCR 호출이 4일간 매달려 파이프라인이 5일 안 끝남
  · `news_writer.py` — 진료과 페이지 생성이 2시간 매달림
둘 다 `timeout=` + `max_retries=2` 를 준다 (`OPENAI_TIMEOUT_SEC` 로 조절).

`daily_pipeline.sh` 의 `run_step` 에 단계별 하드 타임아웃이 있다
(기본 1시간, 수집·OCR 2시간). 넘으면 자식까지 죽이고 다음 단계로 간다.
launchd 는 같은 작업이 돌고 있으면 다음 실행을 **띄우지 않으므로**,
한 단계가 매달리면 그날 이후 전부 멈춘다.

**주의**: bash 는 `VAR=값 함수명` 의 할당을 함수 호출 뒤에도 남긴다(외부 명령과 다름).
`run_step` 안에서 `unset STEP_TIMEOUT` 을 하지 않으면 앞 단계에 준 값이
그 뒤 모든 단계에 계속 적용된다.

## 자동 검증 (회귀 방지)
- `scripts/validate_site.py` 가 사이트 불변조건을 검사한다. **규칙을 바꾸면 검사도 같이 고칠 것.**
  - 로컬: `python scripts/validate_site.py` / 라이브: `--live-only`
  - GitHub Actions `validate.yml` 이 push 마다(로컬) + 매일 07:00 KST(라이브) 실행
  - `news-daily.yml` 은 커밋 **직전**에 검사 — 규칙을 깨는 기사는 배포되지 않는다
- 검사 항목은 전부 **실제로 났던 버그**다. 새 버그를 고칠 때는 검사 항목을 먼저 추가할 것.
  - 내부 링크·canonical·사이트맵·RSS 에 `.html` 확장자 (308 리다이렉트 → 네이버 수집 실패)
  - JS 주입 헤더 잔존 (Yeti 가 내부 링크를 못 읽음)
  - `<img>` alt 누락/빈 값
  - JSON-LD 파싱 실패
  - **통계 '어제 0건'** — 게시 전 데이터를 0건으로 노출 금지
  - 뉴스 인덱스와 실제 HTML/이미지 파일 불일치
  - 애드센스 스니펫 누락, ads.txt/robots.txt 누락
  - `<title>` 이 문서에 2개 이상 (SVG 툴팁용 `<title>` 을 넣었다가 네이버 진단에 걸렸다)
  - prerender 블록이 비어 있음 (알맹이가 다시 JS 전용이 되는 것 차단)
  - 페이지 설명 80자 초과 — 경고 (네이버가 그 이상은 잘라낸다)
  - **라이브 기사 신선도** — 3일 넘게 신규 기사가 없으면 실패.
    워크플로가 success 로 끝나도 발행이 0편일 수 있다. "실패" 가 아니라
    "조용히 아무것도 안 함" 은 알림이 오지 않아서 17일을 몰랐다 (2026-10-09~26).
  - 라이브: 사이트맵 전 URL 200(리다이렉트 없음), 메인 정적 본문 1,000자·내부링크 10개 이상

## 알맹이를 JS 로만 그리지 말 것 (2026-08-10 애드센스 반려)
`/top20` 은 순위표 전체가, 메인은 통계 숫자 전체가 JS 렌더였다. 크롤러가 받는
HTML 에는 `로딩 중...`, `- 건` 만 있었고 `/top20` 의 정적 본문은 559자였다.
구글 애드센스가 **'가치가 별로 없는 콘텐츠'** 로 사이트를 반려한 직접 원인이다.

`scripts/prerender_static.py` 가 같은 JSON 데이터를 HTML 에도 박아 넣는다.
JS 는 그대로 둬서 탭 전환은 계속 동작하고, JS 가 처음 그릴 때 정적 블록을 치운다.
`daily_pipeline.sh` 가 통계 갱신 직후 호출하며 `top20.html`·`index.html` 을 함께 커밋한다.
`validate_site.py` 가 "prerender 블록이 비면 실패" 로 잡는다.

**새 데이터 화면을 만들 때는 정적 렌더를 같이 만들 것.** 지금 남은 것:
검색 결과가 여전히 JS + Supabase API 라 색인이 안 된다.

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