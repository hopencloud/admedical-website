#!/bin/bash
# 매일 새벽 5시(KST) 자동 실행되는 전체 파이프라인.
#
# 실행 순서:
#   1. collector.py        — 신규 시안 다운로드
#   2. indexer.py          — 새 이미지 OCR → index.sqlite
#   3. compute_statistics.py — 일일 통계 갱신
#   4. sync_to_supabase.py — 신규 분 Supabase 업로드 (마스킹 포함)
#   5. (월요일만) compute_weekly_top20.py
#   6. (매월 1일만) compute_monthly_top20.py
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

# 1. 수집
run_step "1/4 collector"  python "$ROOT/scripts/collector.py"

# 2. 인덱싱 (OCR)
run_step "2/4 indexer"    python "$ROOT/scripts/indexer.py"

# 3. 일일 통계
run_step "3/4 statistics" python "$ROOT/scripts/compute_statistics.py"

# 4. Supabase 동기화 (마스킹 포함)
run_step "4/4 sync"       python "$ROOT/scripts/sync_to_supabase.py"

# 5. 주간 TOP 20 (월요일만)
DOW=$(date +%u)  # 1=월요일, 7=일요일
if [ "$DOW" = "1" ]; then
    run_step "주간 TOP20" python "$ROOT/scripts/compute_weekly_top20.py"
fi

# 6. 월간 TOP 20 (매월 1일만)
DOM=$(date +%d)
if [ "$DOM" = "01" ]; then
    run_step "월간 TOP20" python "$ROOT/scripts/compute_monthly_top20.py"
fi

# 7. SQLite 백업 (매일 1부, 7일치 보관)
echo ""
echo "--- [백업] $(date '+%H:%M:%S') ---"
TODAY=$(date +%Y%m%d)
cp "$ROOT/index.sqlite" "$ROOT/_backups/index.sqlite.${TODAY}.bak" 2>/dev/null || echo "백업 실패"
# 7일 지난 백업 정리
find "$ROOT/_backups" -name "index.sqlite.*.bak" -type f -mtime +7 -delete 2>/dev/null

echo ""
echo "================================================================"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 일일 파이프라인 종료"
echo "================================================================"
