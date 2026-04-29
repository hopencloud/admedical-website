# 의료광고 심의 통과 시안 검색 사이트

병의원 마케터를 위한 의료광고 심의 통과 시안 검색 서비스.
키워드를 입력하면 통과된 광고 문구와 심의번호를 보여주고,
원본 시안은 대한의사협회 의료광고심의위원회 사이트에서 확인하도록 안내합니다.

> 프로젝트 전체 맥락은 [CLAUDE.md](CLAUDE.md) 파일을 참고하세요.

---

## 폴더 구조

```
admedical_website/
├── CLAUDE.md             프로젝트 컨텍스트 (AI에게 주는 안내서)
├── README.md             이 파일
├── index.sqlite          OCR 데이터 원본 (절대 직접 수정 금지)
├── .env                  비밀키 (직접 입력 필요, GitHub 안 올라감)
├── .env.example          .env 작성 예시
├── requirements.txt      Python 패키지 목록
│
├── _backups/             index.sqlite 자동 백업
├── logs/                 매일 자동화 실행 로그
├── config/
│   └── stopwords.txt     통계 계산 시 제외할 단어 (직접 편집 가능)
├── scripts/              Python 스크립트들 (단계별로 추가됨)
└── website/              Vercel 배포용 정적 사이트
```

---

## 사장님이 직접 해야 하는 일

### 1. .env 파일에 키 입력
1. 이 폴더의 `.env` 파일을 메모장(또는 텍스트 편집기)으로 엽니다.
2. 각 `=` 뒤에 키를 붙여넣고 저장합니다.
   ```
   SUPABASE_URL=https://xxxxxxxx.supabase.co
   SUPABASE_ANON_KEY=eyJhbGc...
   SUPABASE_SERVICE_KEY=eyJhbGc...
   OPENAI_API_KEY=sk-proj-...
   ```
3. 저장만 하면 끝. 따옴표나 공백은 넣지 마세요.

### 2. OpenAI 사용량 한도 설정 (안전장치)
1. https://platform.openai.com/account/limits 접속
2. **Monthly budget**을 **$5**로 설정
3. 이렇게 해두면 어떤 경우에도 월 5달러(약 7,000원) 이상 안 나갑니다.

---

## 실행 방식 — 관리자 대시보드 /admin
- 사장님이 /admin 페이지에서 버튼으로 수동 트리거 (다운로드 / 인덱싱 / 전체 파이프라인).
- 자세한 셋업은 [ADMIN_DASHBOARD.md](ADMIN_DASHBOARD.md) 참고.

---

## 작업 현황
- [x] 단계 1: 환경 준비 + 백업
- [x] 단계 2: 마스킹 모듈 (OpenAI gpt-4o-mini)
- [x] 단계 3: Supabase 스키마 (ads 테이블)
- [x] 단계 4: 일괄 마이그레이션 (진행 중 — 백그라운드)
- [x] 단계 5: 일일 통계 (statistics.json)
- [x] 단계 6: 주/월 TOP 20 + AI 정제
- [x] 단계 7: 신규 수집/인덱싱 (수동 트리거 — 관리자 대시보드)
- [x] 단계 8: 정적 사이트 (website/) — 사장님이 [DEPLOY.md](DEPLOY.md) 따라 배포

## 다음 사장님이 할 일
1. [ADMIN_DASHBOARD.md](ADMIN_DASHBOARD.md): 관리자 대시보드 셋업 (SQL 1번 + agent 등록)
2. [DEPLOY.md](DEPLOY.md) B: GitHub + Vercel 배포 (15분)
3. (선택) [DEPLOY.md](DEPLOY.md) C: 도메인 연결
