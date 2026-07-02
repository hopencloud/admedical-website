# 관리자 대시보드 · 클라우드 파이프라인 셋업

## 지금의 구조 (맥북 의존성 0)

```
[매일 새벽 5시 KST]        [수동 실행: /admin 페이지 버튼]
        │                            │
        ▼                            ▼
    GitHub Actions "Daily Pipeline" (Ubuntu 러너)
                    │
        ┌───────────┼───────────────┐
        ▼           ▼               ▼
  admedical.org   OpenAI Vision   Supabase
   (신규 시안)      (OCR)          (ads 테이블 upsert)
                                   │
                                   ▼
                        website/assets/data/*.json 자동 git push
                                   │
                                   ▼
                            Vercel 자동 재배포
```

맥북, launchd, admin_agent, Vercel cron 모두 **불필요**. 사장님이 컴퓨터 끄고 여행 가도 매일 정시에 자동 갱신.

---

## 최초 셋업 (1회, 약 5분)

### 1. GitHub Secrets 등록

브라우저에서:  
`https://github.com/hopencloud/admedical-website/settings/secrets/actions`

**New repository secret** 4개 추가:

| Name | Value |
|------|-------|
| `SUPABASE_URL` | `.env` 의 SUPABASE_URL 값 그대로 |
| `SUPABASE_SERVICE_KEY` | `.env` 의 SUPABASE_SERVICE_KEY |
| `SUPABASE_ANON_KEY` | `.env` 의 SUPABASE_ANON_KEY |
| `OPENAI_API_KEY` | `.env` 의 OPENAI_API_KEY |

터미널에서 `.env` 값 확인:  
```bash
cat /Users/halim/Downloads/아카이브/admedical_website/.env
```

### 2. Vercel Secrets 등록 (관리자 대시보드용)

Vercel 프로젝트 → Settings → Environment Variables → **Add New**

| Name | Value |
|------|-------|
| `GITHUB_TOKEN` | 새로 발급받은 GitHub PAT (아래 방법) |

**PAT 발급 방법**:
1. https://github.com/settings/personal-access-tokens/new  (Fine-grained)
2. Token name: `admedical-workflow-dispatch`
3. Repository access: **Only select repositories** → `hopencloud/admedical-website`
4. Repository permissions:  
   - **Actions**: Read and write
   - **Contents**: Read
5. Generate → `github_pat_...` 복사
6. Vercel 에 `GITHUB_TOKEN` 이름으로 저장 → **Redeploy**

### 3. 첫 실행 테스트

브라우저: `https://admedical.co.kr/admin`  
비밀번호 로그인 → **지금 실행** 버튼 클릭 → 1~2분 뒤 목록에 새 실행 등장 → 상태 배지가 `실행 중` → `완료`로 변화 → 사이트 갱신 확인.

---

## 이제 폐기해도 되는 것들 (선택)

첫 실행이 성공하면 **맥북에서 아래 정리 가능**:

```bash
# admin_agent (로컬 폴러) 중지·제거
launchctl unload ~/Library/LaunchAgents/com.admedical.admin_agent.plist
rm ~/Library/LaunchAgents/com.admedical.admin_agent.plist

# 필요 시 로그도 삭제
rm -f ~/Library/Logs/admedical_admin_agent.log
```

Vercel 환경변수 중 `CRON_SECRET` 도 이제 안 씀 — 지워도 됨.  
`~/Desktop/admedical_ads/` 이미지 폴더 · `index.sqlite` 도 클라우드 파이프라인엔 불필요. 로컬 개발이나 백업 목적으로 남겨두는 건 자유.

---

## 트러블슈팅

**GitHub Actions 실행이 실패로 뜬다**  
→ GitHub Actions 탭에서 실패한 실행 클릭 → 어느 스텝이 죽었는지 확인. 대부분 secret 누락 (SUPABASE_URL 등).

**"지금 실행" 버튼이 401 오류**  
→ Vercel `GITHUB_TOKEN` 미설정 또는 만료. 새 PAT 발급 후 갱신 + Redeploy.

**cron 이 안 도는 것 같다**  
→ GitHub Actions 는 5시 정각에 정확히 안 돌 수 있음 (러너 큐 상황에 따라 몇 분 지연). 최대 15분 정도 지연 정상.

**사이트가 며칠 안 갱신됐다**  
→ 메인 화면 우측 "데이터 N일 전까지" 노란 배지가 뜸 → `/admin` 에서 최근 실행 상태 확인 → 실패했으면 로그 보고 조치.
