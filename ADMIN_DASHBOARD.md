# 관리자 대시보드 설정 가이드

브라우저(폰/PC 어디서든) → `https://<도메인>/admin` → 비밀번호 입력 →
**다운로드 / 인덱싱 / 전체 파이프라인** 버튼으로 맥북 작업을 원격 트리거.

## 동작 구조

```
[브라우저 admin 페이지]   ←─ 폴링 2초 ─→  Vercel API
                                              │
                                              ▼
                                      [Supabase admin_jobs]
                                              ▲
                                              │ 폴링 5초
                                              │
                                      [맥북 admin_agent.py]
                                              │ subprocess
                                              ▼
                                  collector / OCR / pipeline
```

맥북이 꺼져 있으면 작업은 `pending` 상태로 큐에 쌓여 있다가, 켜지면 자동 실행됩니다.

---

## 1. Supabase 테이블 생성 (1번만)

1. Supabase 대시보드 → SQL Editor → New query
2. [scripts/supabase_admin_jobs.sql](scripts/supabase_admin_jobs.sql) 내용 전체 복사·붙여넣기
3. Run

## 2. Vercel 환경변수 추가 (1번만)

이미 등록되어 있으면 건너뛰기.

Vercel 프로젝트 → Settings → Environment Variables 에서:

| 키 | 값 |
|----|----|
| `ADMIN_PASSWORD` | 사장님이 정한 비밀번호 (강력하게) |
| `SUPABASE_URL` | (이미 등록됨) |
| `SUPABASE_SERVICE_KEY` | (이미 등록됨) |

추가/변경 후 **Redeploy** 해야 반영됩니다.

## 3. 맥북 agent 등록 (1번만)

```bash
cd /Users/halim/Downloads/아카이브/admedical_website

# 기존 등록되어 있을 수 있으니 먼저 unload
launchctl unload ~/Library/LaunchAgents/com.admedical.admin_agent.plist 2>/dev/null

cp scripts/com.admedical.admin_agent.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.admedical.admin_agent.plist

# 잘 떴는지 확인
launchctl list | grep com.admedical.admin_agent

# 로그 살펴보기 (Ctrl+C 로 빠져나오기)
tail -f logs/admin_agent.log
```

`logs/admin_agent.log` 에 `[agent] 시작. polling 주기=5s` 가 보이면 OK.

## 4. 일일 자동 파이프라인 plist도 다시 등록 (경로 수정됨)

기존 plist는 `/Users/halim/Desktop/...` 잘못된 경로를 가리키고 있어서 **매일 새벽 자동 실행이 작동 안 했습니다**. 수정된 새 plist로 다시 등록하세요.

```bash
launchctl unload ~/Library/LaunchAgents/com.admedical.daily.plist 2>/dev/null
cp scripts/com.admedical.daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.admedical.daily.plist
launchctl list | grep com.admedical.daily
```

## 5. 사용

브라우저에서 `/admin` 접속 → 비밀번호 입력 → 버튼 클릭.

- **다운로드 시작**: `collector.py` (신규 시안만 받음, 약 1~2분)
- **인덱싱 시작**: `batch_vision_ocr.py` + 통계 + Supabase 동기화 (시안 수에 따라 2~5분)
- **전체 파이프라인**: 위 둘 + TOP20 갱신 + git push (5~15분)

진행 중인 작업은 화면 가운데 진행바·상태 메시지·로그 꼬리로 확인. 완료/실패 시 자동 갱신됩니다.

---

## 트러블슈팅

**Q. 버튼 누르면 "이미 실행 중인 작업이 있습니다" 오류**  
A. 먼저 끝나기 기다리거나, Supabase 대시보드 → admin_jobs 테이블에서 해당 row의 status를 `cancelled` 로 직접 바꿔주세요.

**Q. agent가 안 돌고 있는 것 같다**  
```bash
launchctl list | grep com.admedical.admin_agent      # PID 보여야 정상
tail -50 logs/admin_agent.log                          # 마지막 로그
launchctl unload ~/Library/LaunchAgents/com.admedical.admin_agent.plist
launchctl load ~/Library/LaunchAgents/com.admedical.admin_agent.plist
```

**Q. 비밀번호 변경하고 싶다**  
Vercel `ADMIN_PASSWORD` 환경변수 갱신 → Redeploy. 맥북 agent에는 비밀번호 정보가 없으므로 영향 없음.

**Q. 맥북 슬립 모드에서도 5시에 깨어나서 자동 실행되게 하려면?**  
시스템 설정 → 배터리/전원 어댑터 → "연결되어 있을 때 디스플레이 끄기 시 컴퓨터를 자동으로 잠자게 두지 않기" 활성화하거나, Amphetamine 같은 앱 사용. 또는 매일 새벽 5시 직전에 `pmset schedule wake` 로 wake 일정 등록.
