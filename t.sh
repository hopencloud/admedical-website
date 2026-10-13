STEP_TIMEOUT_DEFAULT=${STEP_TIMEOUT_DEFAULT:-3600}
run_step() {
    local name="$1"; shift
    local limit="${STEP_TIMEOUT:-$STEP_TIMEOUT_DEFAULT}"
    echo "--- [$name] $(date '+%H:%M:%S') ---"
    "$@" &
    local pid=$!
    local waited=0
    while kill -0 "$pid" 2>/dev/null; do
        if [ "$waited" -ge "$limit" ]; then
            echo "[$name] ⏱ ${limit}초 초과 — 강제 종료"
            pkill -9 -P "$pid" 2>/dev/null; kill -9 "$pid" 2>/dev/null
            wait "$pid" 2>/dev/null
            return 1
        fi
        sleep 1
        waited=$((waited + 1))
    done
    if wait "$pid"; then echo "[$name] OK"; else echo "[$name] 실패 (계속 진행)"; fi
}
echo "① 정상 종료:"; run_step "정상" sleep 2
echo "② 실패 종료:"; run_step "실패" bash -c "exit 3"
echo "③ 타임아웃:";  STEP_TIMEOUT=3 run_step "행" sleep 60
echo "④ 자식까지 죽는지:"; STEP_TIMEOUT=3 run_step "자식" bash -c 'sleep 60 & wait'
echo "완료 — 모든 단계 통과"
