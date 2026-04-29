#!/bin/bash
# 전체 파이프라인 — 관리자 대시보드 "전체 파이프라인" 버튼이 트리거.
# (launchd 자동 실행은 폐기됨)
#
# 실행 순서:
#   1. collector.py             — 신규 시안 다운로드
#   2. batch_vision_ocr.py      — 새 이미지 OCR → index.sqlite (OpenAI Vision)
#   3. compute_statistics.py    — 일일 통계 갱신
#   4. sync_to_supabase.py      — 신규 분 Supabase 업로드 (마스킹 포함)
#   5. compute_this_week_top20  — 이번주 TOP 20 (매일 갱신, 누적)
#   6. compute_this_month_top20 — 이번달 TOP 20 (매일 갱신, 누적)
#   7. (월요일만) compute_weekly_top20  — 지난주 TOP 20 (확정)
#   8. (매월 1일만) compute_monthly_top20 — 지난달 TOP 20 (확정)
#   9. SQLite 백업 (7일치 보관)
#  10. git push  — 데이터 JSON만 자동 커밋·푸시 → Vercel 자동 배포
#
# 로그: logs/daily_YYYYMMDD.log

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"
TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/daily_${TS}.log"

# 모든 출력을 로그 파일로 함께 보냄
exec > >(tee -a "$LOG_FILE") 2>&1

echo "================================================================"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 일일 파이프라인 시작"
echo "================================================================"

source "$ROOT/venv/bin/activate"

run_step() {
    local name="$1"
    shift
    echo ""
    echo "--- [$name] $(date '+%H:%M:%S') ---"
    if "$@"; then
        echo "[$name] OK"
    else
        echo "[$name] 실패 (계속 진행)"
    fi
}

# 1. 수집 — admedical.org에서 신규 시안 다운로드 → ~/Desktop/admedical_ads/
run_step "1/4 collector"  python "$ROOT/scripts/collector.py"

# 2. Vision OCR — ~/Desktop/admedical_ads/ 의 신규 이미지 OCR → index.sqlite
#    (OpenAI gpt-4o-mini Vision HIGH detail. EasyOCR보다 한국어 정확)
run_step "2/4 vision ocr" python "$ROOT/scripts/batch_vision_ocr.py" --src "$HOME/Desktop/admedical_ads" --workers 5

# 3. 일일 통계
run_step "3/4 statistics" python "$ROOT/scripts/compute_statistics.py"

# 4. Supabase 동기화 (마스킹 포함)
run_step "4/4 sync"       python "$ROOT/scripts/sync_to_supabase.py"

# 5. 이번주 TOP 20 — 매일 갱신 (월요일~오늘 누적)
run_step "이번주 TOP20" python "$ROOT/scripts/compute_this_week_top20.py"

# 6. 이번달 TOP 20 — 매일 갱신 (1일~오늘 누적)
run_step "이번달 TOP20" python "$ROOT/scripts/compute_this_month_top20.py"

# 7. 지난주 TOP 20 (월요일만 — 새 주 시작 시 직전 주 확정)
DOW=$(date +%u)  # 1=월요일, 7=일요일
if [ "$DOW" = "1" ]; then
    run_step "지난주 TOP20" python "$ROOT/scripts/compute_weekly_top20.py"
fi

# 8. 지난달 TOP 20 (매월 1일만 — 새 달 시작 시 직전 달 확정)
DOM=$(date +%d)
if [ "$DOM" = "01" ]; then
    run_step "지난달 TOP20" python "$ROOT/scripts/compute_monthly_top20.py"
fi

# 7. SQLite 백업 (매일 1부, 7일치 보관)
echo ""
echo "--- [백업] $(date '+%H:%M:%S') ---"
TODAY=$(date +%Y%m%d)
cp "$ROOT/index.sqlite" "$ROOT/_backups/index.sqlite.${TODAY}.bak" 2>/dev/null || echo "백업 실패"
# 7일 지난 백업 정리
find "$ROOT/_backups" -name "index.sqlite.*.bak" -type f -mtime +7 -delete 2>/dev/null

# 8. 데이터 JSON git push — 사이트 자동 갱신
echo ""
echo "--- [git push] $(date '+%H:%M:%S') ---"
cd "$ROOT"

# 데이터 JSON만 골라서 stage (다른 변경분은 건드리지 않음)
DATA_FILES=(
    "website/assets/data/statistics.json"
    "website/assets/data/this_week_top20.json"
    "website/assets/data/this_month_top20.json"
    "website/assets/data/weekly_top20.json"
    "website/assets/data/monthly_top20.json"
)
git add "${DATA_FILES[@]}" 2>/dev/null

# 실제 stage 된 변경이 있을 때만 커밋
if git diff --cached --quiet; then
    echo "[git] 변경 사항 없음 — 커밋 생략"
else
    DATE_LABEL=$(date '+%Y-%m-%d %a')
    if git commit -m "일일 통계 자동 갱신 (${DATE_LABEL})"; then
        if git push origin main; then
            echo "[git] push 성공 — Vercel 자동 배포 트리거됨"
        else
            echo "[git] push 실패 — 다음에 수동으로 'git push' 실행 필요"
        fi
    else
        echo "[git] commit 실패"
    fi
fi

echo ""
echo "================================================================"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 일일 파이프라인 종료"
echo "================================================================"
