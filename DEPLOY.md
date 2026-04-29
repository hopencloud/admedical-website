# 배포 가이드 (사장님이 직접 따라 하는 안내서)

이 문서는 한 번만 따라하면 됩니다. **약 30~45분 소요.**

> ⚠ 계정 확인: 사장님이 **GitHub 계정**과 **Vercel 계정** 모두 있어야 합니다.
> 없으면 [github.com](https://github.com), [vercel.com](https://vercel.com)에서 먼저 가입하세요.
> Vercel 가입은 "Continue with GitHub"로 하시면 편합니다.

---

## 전체 흐름 (한눈에)

```
┌──────────────┐    ┌──────────┐    ┌────────┐    ┌─────────┐
│  맥북 폴더   │ →  │  GitHub  │ →  │ Vercel │ →  │ 인터넷  │
│ (사장님 코드)│    │ (저장소) │    │  (호스팅)│    │ (배포됨)│
└──────────────┘    └──────────┘    └────────┘    └─────────┘
```

1. 맥북 폴더 → GitHub로 코드 업로드 (15분)
2. GitHub → Vercel에 연결해서 배포 (10분)
3. Vercel에 환경변수(키) 입력 (10분)
4. Vercel에서 다시 배포 → 완성 (5분)

---

## 1단계 — 맥북에서 Git 준비 (5분)

### 1-1. Git이 깔려있는지 확인

터미널 앱 열기 (`Cmd + Space` → "terminal" 입력 → Enter), 아래 명령 입력:

```bash
git --version
```

**결과 보고 분기:**
- `git version 2.x.x` 같은 게 나오면 ✓ 다음 단계로
- `xcode-select` 어쩌고 하는 팝업이 뜨면 → "설치" 클릭 → 설치 완료까지 10분 대기 → 다시 위 명령 실행
- "command not found"면 → `xcode-select --install` 입력 → 설치 → 다시 위 명령

### 1-2. Git에 본인 이름과 이메일 등록 (한 번만)

```bash
git config --global user.name "사장님이름"
git config --global user.email "사장님 GitHub에 등록한 이메일"
```

예: `git config --global user.email "gkfla2@gmail.com"`

확인:
```bash
git config --global user.name
git config --global user.email
```

---

## 2단계 — GitHub에 새 저장소 만들기 (3분)

1. https://github.com/new 접속 (로그인 필요)
2. 입력란:
   - **Repository name**: `admedical-website` (다른 이름 OK)
   - **Description**: 비워두기
   - **Public** 선택 (Vercel 무료 플랜용)
   - 아래쪽 **Add a README file**, **Add .gitignore**, **Add a license** 모두 **체크하지 마세요** (이미 폴더에 있음)
3. **Create repository** 버튼 클릭

화면이 바뀌면 위쪽에 이런 URL이 보입니다:
```
https://github.com/사장님계정/admedical-website.git
```
이 URL 전체 복사해두세요 (다음 단계에서 사용).

---

## 3단계 — 맥북 코드를 GitHub로 업로드 (5분)

터미널에서 한 줄씩 차례로 붙여넣고 Enter:

### 3-1. 프로젝트 폴더로 이동
```bash
cd ~/Desktop/admedical_website
```

### 3-2. Git 저장소 초기화
```bash
git init
```
"Initialized empty Git repository..." 메시지 나오면 OK.

### 3-3. 파일 추가
```bash
git add CLAUDE.md README.md DEPLOY.md .gitignore .env.example requirements.txt vercel.json package.json scripts/ website/ config/ api/
```

> 💡 `.env`, `index.sqlite`, `_backups/`, `logs/`, `기존데이터/`, `venv/`는 자동 제외됩니다.

### 3-4. 첫 커밋
```bash
git commit -m "초기 배포"
```
파일 추가됐다는 긴 출력이 나오면 OK.

### 3-5. GitHub 저장소 연결 (2단계에서 복사한 URL 사용)
```bash
git remote add origin https://github.com/사장님계정/admedical-website.git
```
> ⚠ `사장님계정` 부분을 실제 본인 GitHub 아이디로 바꾸세요.

### 3-6. 업로드
```bash
git branch -M main
git push -u origin main
```

처음 push할 때 GitHub 로그인 팝업이 뜰 수 있습니다:
- **Username**: GitHub 아이디
- **Password**: GitHub 비밀번호가 아니라 **Personal Access Token** 필요. 발급 안내:
  1. https://github.com/settings/tokens 접속
  2. **Generate new token** → **Generate new token (classic)**
  3. **Note**에 `mac-cli` 입력, **Expiration** `90 days`
  4. **Select scopes**에서 `repo` 전체 체크
  5. **Generate token** 클릭
  6. 표시된 `ghp_...` 토큰 복사 (이 화면 닫으면 다시 못 봄)
  7. 터미널 password 입력란에 그 토큰 붙여넣기

업로드 성공하면 GitHub 저장소 페이지 새로고침 시 파일들이 보입니다.

---

## 4단계 — Vercel에서 GitHub 저장소 가져오기 (5분)

1. https://vercel.com/new 접속 (GitHub로 로그인)
2. **Import Git Repository** 영역에 GitHub 저장소 목록이 나옵니다.
3. 처음이면 "Adjust GitHub App Permissions" 같은 안내가 나올 수 있어요. 이 경우:
   - **Configure GitHub App** 클릭
   - GitHub로 이동해서 Vercel에 권한 부여 (전체 저장소 또는 특정 저장소만 선택)
   - Vercel로 돌아옴
4. 목록에서 `admedical-website` 옆 **Import** 버튼 클릭

설정 화면(Configure Project)이 뜹니다:

| 항목 | 값 | 설명 |
|---|---|---|
| **Project Name** | 자동 채워짐 그대로 (`admedical-website`) | URL 접두사가 됨 |
| **Framework Preset** | **Other** 선택 | (자동 감지될 수도 있음) |
| **Root Directory** | 그대로 두기 (`./`) | 변경 X |
| **Build and Output Settings** | 펼치지 않아도 됨 | `vercel.json`이 알아서 처리 |
| **Environment Variables** | 펼쳐서 다음 단계 진행 | ★ 필수 |

### 4-1. 환경변수 입력 (이 화면에서 같이!)

**Environment Variables** 영역을 펼치고, 아래 6개를 하나씩 추가합니다.
입력란에 Name과 Value를 채우고 **Add** 클릭, 다음 항목 반복:

| Name (그대로) | Value (사장님이 채울 것) |
|---|---|
| `SUPABASE_URL` | `https://dukwwaehnmsuueuwacgx.supabase.co` |
| `SUPABASE_SERVICE_KEY` | (`.env` 파일의 SUPABASE_SERVICE_KEY 값 그대로) |
| `OPENAI_API_KEY` | (`.env` 파일의 OPENAI_API_KEY 값 그대로) |
| `SMTP_USER` | 사장님 Gmail 주소 (예: `gkfla2@gmail.com`) |
| `SMTP_PASS` | (5단계에서 발급할 Gmail App Password — 일단 빈칸 두고 나중에 추가) |
| `ADMIN_PASSWORD` | 직접 정한 긴 비번 (예: `xK29mLp7vQ2026`, 대소문자+숫자 16자 이상 권장) |

> 💡 `SMTP_PASS`는 다음 5단계에서 발급받아 추가하시면 됩니다. 일단 비워두고 진행 OK.

### 4-2. 배포 실행

**Deploy** 버튼 클릭 → 1~2분 빌드 진행 → 🎉 페이지가 뜨면 성공.

화면에 **Visit** 버튼이나 `https://admedical-website-xxx.vercel.app` URL이 보입니다. 클릭하면 사이트가 바로 뜹니다.

> ⚠ 검색은 정상 동작하지만 오류제보는 아직 안 됨 (SMTP_PASS 미설정).

---

## 5단계 — Gmail App Password 발급 + 추가 (5분)

1. https://myaccount.google.com/security 접속
2. **"2단계 인증"** 항목이 **사용 중**인지 확인
   - 안 켜져 있으면 → **2단계 인증** 클릭 → 휴대폰으로 인증 → 켜기
3. https://myaccount.google.com/apppasswords 접속
   - 화면이 안 열리면 검색창에 "앱 비밀번호" 검색 후 클릭
4. **앱 이름** 입력란에 `admedical website` 입력 → **만들기**
5. 화면에 16자리 비밀번호가 나옴 (예: `abcd efgh ijkl mnop`)
6. **띄어쓰기 모두 제거**해서 메모: `abcdefghijklmnop`
7. **이 화면 닫기 전에** Vercel로 돌아가서 환경변수 추가:
   - Vercel 프로젝트 → **Settings → Environment Variables**
   - `SMTP_PASS` 항목 (없으면 새로 추가) → Value에 위 16자리 붙여넣기 → **Save**

---

## 6단계 — 환경변수 변경 후 재배포 (3분)

환경변수를 추가/변경했으면 **반드시 재배포해야 적용**됩니다.

1. Vercel 프로젝트 → 상단 **Deployments** 탭
2. 가장 최근 배포 항목 우측 **... (점 3개)** 클릭 → **Redeploy** 클릭
3. 다이얼로그에서 **Use existing Build Cache** 체크 그대로, **Redeploy** 클릭
4. 1분 대기 → 새 배포 완료

---

## 7단계 — 동작 테스트 (5분)

### 7-1. 일반 사용자 테스트

1. Vercel URL 접속 (예: `https://admedical-website-xxx.vercel.app`)
2. 검색창에 "스마일" 입력 → 결과가 5개 나오는지 확인
3. 검색 결과 카드 우측 상단 **🚨 오류제보하기** 클릭
4. 모달에서 사유 입력 (예: "테스트") → **제보 보내기**
5. **"✓ 제보 완료"** 메시지 뜨면 OK
6. 사장님 Gmail 받은편지함 확인 → 메일 도착 확인

### 7-2. 관리자 테스트

1. 받은 메일 안의 **광고 문구 수정 페이지 →** 링크 클릭
2. 관리자 페이지가 열림 → 4단계에서 정한 `ADMIN_PASSWORD` 입력 → **불러오기**
3. 광고 문구가 표시되면 살짝 수정 → **저장**
4. **"✓ 저장 완료"** 뜨면 OK
5. 사이트로 돌아가서 같은 키워드 다시 검색 → 수정한 내용 즉시 반영되는지 확인

---

## 8단계 — 관리자 대시보드 셋업

매일 자동 갱신은 폐기되었습니다. 사장님이 `/admin` 페이지에서 버튼으로 직접 다운로드·OCR·전체 파이프라인을 트리거합니다.

셋업 가이드: [ADMIN_DASHBOARD.md](ADMIN_DASHBOARD.md) 참고.

---

## ✅ 완료 체크리스트

- [ ] 1단계: Git 깔리고 본인 정보 등록
- [ ] 2단계: GitHub 저장소 만들기
- [ ] 3단계: 코드 GitHub에 업로드
- [ ] 4단계: Vercel 가져오기 + 환경변수 5개 입력 + 배포
- [ ] 5단계: Gmail App Password 발급 + Vercel에 SMTP_PASS 추가
- [ ] 6단계: 재배포
- [ ] 7단계: 일반 검색 + 오류제보 + 관리자 수정 모두 테스트 통과
- [ ] 8단계: 관리자 대시보드 셋업 (ADMIN_DASHBOARD.md)

---

## 9단계 — Google AdSense 활성화 (정식 오픈 + 트래픽 확보 후)

> ⚠ **신청 시점**: 사이트 정식 오픈 후 **1~3개월** 이상 운영 + 일정 트래픽(월 1,000+) 확보된 후. 그 전에 신청하면 거절됩니다.

### 9-1. AdSense 가입 및 사이트 등록
1. https://adsense.google.com 접속 (구글 계정으로)
2. **시작하기** → 사이트 URL `https://www.admedical.co.kr` 입력
3. 결제 정보·세금 정보 입력
4. AdSense가 안내하는 한 줄 `<script>`를 복사 (이 코드는 이미 `ads.js`에서 자동 처리되므로 별도 삽입 불필요 — 다음 단계 9-2에서 바로 활성화)
5. 사이트 검토 신청 → 1~14일 대기

### 9-2. publisher ID 입력 + 코드 활성화
승인되면 AdSense 콘솔 우측 상단에 `pub-XXXXXXXXXXXXXXXX` 형태의 ID가 보입니다.

**파일 1: `website/assets/js/ads.js`** 수정
```js
const ADSENSE_ENABLED = true;                              // false → true
const ADSENSE_PUBLISHER_ID = "ca-pub-1234567890123456";    // 실제 publisher ID
```

**파일 2: `website/ads.txt`** 수정 (AdSense 콘솔 → 사이트 → "ads.txt 추가" 안내 그대로 복사)
```
google.com, pub-1234567890123456, DIRECT, f08c47fec0942fa0
```

### 9-3. 광고 단위 만들고 슬롯 ID 입력
AdSense 콘솔 → **광고 → 광고 단위별** → **새 광고 단위 만들기**:

| 광고 단위 이름 | 광고 형식 | 사이트 위치 |
|---|---|---|
| `search-results-bottom` | 디스플레이 (반응형) | 검색 결과 하단 |
| `top20-top` | 디스플레이 (반응형) | TOP 20 리스트 위 |
| `article-end` | 인-아티클 또는 디스플레이 | 가이드 본문 끝 |

각 광고 단위 만들 때마다 발급되는 슬롯 ID(예: `1234567890`)를 `ads.js`의 `SLOT_IDS`에 입력:
```js
const SLOT_IDS = {
    "search-results-bottom": "1234567890",
    "top20-top":             "2345678901",
    "article-end":           "3456789012",
};
```

### 9-4. 배포
```
cd ~/Desktop/admedical_website
git add website/assets/js/ads.js website/ads.txt
git commit -m "AdSense 활성화"
git push
```

1~2분 후 광고 노출 시작. 사이트 새로고침하면 광고가 보임 (AdSense는 페이지 첫 노출까지 약간 시간 소요 — 최대 24시간).

### 9-5. 광고 표시 위치 (사이트에 미리 잡혀 있음)
| 페이지 | 슬롯 위치 |
|---|---|
| 메인 (검색 페이지) | 검색 결과 5개 다음, 통계 카드 위 |
| TOP 20 | 탭 아래, 1위 위 |
| 심의 가이드 7개 페이지 | 본문 끝, "관련 페이지" 카드 위 |
| 서비스 소개·문의·약관·정책 | 광고 X (UX 우선) |

### 9-6. AdSense 정책 점검 (의료광고 사이트 특수성)
- ❌ 처방의약품 직접 광고 게재 X
- ❌ 검증되지 않은 치료법 광고 X
- ✅ 의료광고심의 안내·정보 서비스 = 정책 적합
- 검색 결과에 부적절 광고가 자동 매칭되면 AdSense 콘솔에서 **광고 차단** 가능

### 9-7. 수익 모니터링
- AdSense 콘솔 → **보고서** 메뉴
- 페이지별 RPM(1,000회 노출당 수익), 슬롯별 CTR 비교
- 잘 안 클릭되는 슬롯은 위치 조정

### 9-8. 비활성화 (다시 끄고 싶을 때)
`ads.js`의 `ADSENSE_ENABLED`를 다시 `false`로 → push → 광고 즉시 사라짐 (`.ad-slot`이 CSS로 숨겨져 빈 공간 노출 X).

---

## 10단계 — 도메인 연결 (선택 — 도메인 사고 나서)

1. 카페24 또는 가비아에서 도메인 구매
2. Vercel 프로젝트 → **Settings → Domains** → 도메인 입력 → **Add**
3. Vercel이 알려주는 DNS 레코드(보통 `A` 또는 `CNAME` 또는 nameserver)를 카페24/가비아 DNS 설정에 입력
4. 5분~1시간 후 도메인으로 접속 가능
5. Vercel 환경변수 `PUBLIC_SITE_URL`에 도메인 추가 (예: `https://admedical.co.kr`) → 재배포
   - 이래야 오류제보 메일의 수정 링크가 신 도메인으로 발송됨

---

## 운영 중 자주 만나는 상황

### 데이터/통계 자동 갱신
- 사이트의 검색 결과는 Supabase에서 실시간으로 옵니다 → **재배포 없이 즉시 반영**
- 통계 그래프는 `website/assets/data/statistics.json`에서 옵니다 → 매일 자동 푸시 설정 안 했으면 사이트 그래프는 안 갱신됨. 자동 푸시 설정은 별도 안내 가능 (필요하시면 요청)

### 환경변수 바꿨는데 적용 안 돼요
→ 6단계 재배포 필수.

### 메일이 안 옴
- Vercel 대시보드 → **Functions** 탭 → `/api/report` 클릭 → 로그 확인
- 가장 흔한 원인: SMTP_PASS 띄어쓰기 안 지움 / 2단계 인증 안 켬 / Gmail 주소 오타

### 관리자 비밀번호 잊어버림
- Vercel 환경변수 `ADMIN_PASSWORD` 다시 설정 → 재배포

### 깃 push 했는데 사이트 안 바뀜
- Vercel 자동 빌드 트리거됨 → Deployments 탭에서 진행 상황 확인
- 1분 정도 걸림

### Vercel URL 너무 길어
- 9단계 도메인 연결 OR Vercel 대시보드 → Settings → Domains 에서 `admedical-website.vercel.app` 같은 짧은 별칭 추가 가능
