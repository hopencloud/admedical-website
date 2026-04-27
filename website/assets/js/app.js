/* eslint-env browser */
/* global Chart, SUPABASE_CONFIG, ADMEDICAL_LINK, PAGE_SIZE */

const cfg = window.SUPABASE_CONFIG;
const headers = {
    "apikey": cfg.anonKey,
    "Authorization": `Bearer ${cfg.anonKey}`,
};

// ---------- 통계 대시보드 ----------
async function loadStatistics() {
    try {
        const r = await fetch("/assets/data/statistics.json", { cache: "no-store" });
        if (!r.ok) return;
        const data = await r.json();
        document.getElementById("stat-today").textContent = data.today.count.toLocaleString();
        document.getElementById("stat-week").textContent = data.this_week.count.toLocaleString();

        if (data.last_week) {
            document.getElementById("stat-last-week").textContent = data.last_week.count.toLocaleString();
            document.getElementById("stat-last-week-delta").innerHTML = formatDelta(data.last_week.delta, "지지난주");
        }
        if (data.last_month) {
            document.getElementById("stat-last-month").textContent = data.last_month.count.toLocaleString();
            document.getElementById("stat-last-month-delta").innerHTML = formatDelta(data.last_month.delta, "지지난달");
        }

        const ts = new Date(data.generated_at).toLocaleString("ko-KR");
        document.getElementById("last-update").textContent = `마지막 업데이트: ${ts} • 총 누적 ${data.total.count.toLocaleString()}건`;

        renderChart(data.chart_30d);
    } catch (e) {
        console.warn("statistics.json 로드 실패:", e);
    }
}

function formatDelta(delta, refLabel) {
    if (delta === 0) {
        return `<span class="text-slate-400">${refLabel} 대비 동일</span>`;
    }
    const sign = delta > 0 ? "▲" : "▼";
    const color = delta > 0 ? "text-rose-500" : "text-blue-500";
    const abs = Math.abs(delta).toLocaleString();
    return `<span class="${color} font-semibold">${sign} ${abs}</span> <span class="text-slate-400">vs ${refLabel}</span>`;
}

function renderChart(rows) {
    const ctx = document.getElementById("chart-30d");
    if (!ctx || !rows) return;
    const labels = rows.map(r => r.date.slice(5));  // MM-DD
    const counts = rows.map(r => r.count);
    new Chart(ctx, {
        type: "bar",
        data: {
            labels,
            datasets: [{
                label: "통과 건수",
                data: counts,
                backgroundColor: "#3b82f6",
                borderRadius: 4,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { ticks: { font: { size: 10 }, maxRotation: 0 } },
                y: { beginAtZero: true, ticks: { precision: 0 } },
            },
        },
    });
}

// ---------- 검색 ----------
let currentQuery = "";
let currentOffset = 0;

async function search(q, offset = 0) {
    if (!q.trim()) return { rows: [], total: 0 };
    const escaped = q.trim().replace(/[%]/g, "\\%");
    const url = `${cfg.url}/rest/v1/${cfg.table}`
        + `?select=review_no_display,review_date,ocr_text,review_num`
        + `&ocr_text=ilike.*${encodeURIComponent(escaped)}*`
        + `&order=review_date.desc,review_num.desc`
        + `&offset=${offset}&limit=${PAGE_SIZE}`;
    const r = await fetch(url, {
        headers: { ...headers, "Prefer": "count=exact" },
    });
    if (!r.ok) {
        console.error("Supabase search failed:", r.status, await r.text());
        return { rows: [], total: 0 };
    }
    const rows = await r.json();
    const range = r.headers.get("content-range") || "";
    const total = parseInt(range.split("/")[1] || "0", 10);
    return { rows, total };
}

function highlight(text, query) {
    if (!query) return escapeHtml(text);
    const safe = escapeHtml(text);
    const safeQ = escapeHtml(query).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return safe.replace(new RegExp(safeQ, "gi"), m => `<mark class="bg-yellow-200">${m}</mark>`);
}

function escapeHtml(s) {
    return String(s ?? "")
        .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

function renderRow(row, q) {
    const text = row.ocr_text || "(텍스트 없음)";
    const display = row.review_no_display || `중-${row.review_num}`;
    // -중- 뒤 숫자만 추출 (예: "260424-중-211923" → "211923")
    const numberOnly = String(row.review_num ?? display.split("-중-").pop() ?? "");
    const safeDisplay = escapeHtml(display);
    const safeText = escapeHtml(text);
    return `
    <article class="bg-white rounded-2xl p-5 border border-slate-200 hover:border-brand-500 hover:shadow-soft transition">
        <div class="flex items-start justify-between gap-3 mb-3">
            <div class="flex items-center gap-2 flex-wrap">
                <span class="text-xs px-2.5 py-1 bg-brand-50 text-brand-700 rounded-lg font-mono font-medium">${safeDisplay}</span>
                <span class="text-xs text-slate-500 tabular-nums">${escapeHtml(row.review_date || "")}</span>
            </div>
            <button onclick="reportError('${safeDisplay}', \`${safeText.replace(/`/g, "\\`")}\`, '${escapeHtml(numberOnly)}')"
                    title="내용 오류 및 병원명 노출 시 제보해 주세요"
                    class="shrink-0 text-xs px-3 py-1.5 bg-rose-50 text-rose-700 border border-rose-200 rounded-lg hover:bg-rose-100 hover:border-rose-400 font-semibold transition">
                오류 제보
            </button>
        </div>
        <p class="text-[15px] leading-relaxed text-slate-800 whitespace-pre-wrap">${highlight(text, q)}</p>
        <div class="mt-4 pt-3 border-t border-slate-100 flex flex-wrap items-center gap-3 text-xs">
            <button onclick="copyText('${escapeHtml(numberOnly)}')"
                    class="px-3 py-1.5 border border-slate-300 rounded-lg hover:bg-slate-50 hover:border-brand-500 text-slate-700 font-medium transition">
                심의번호 복사
            </button>
            <a href="${ADMEDICAL_LINK}" target="_blank" class="text-brand-600 hover:text-brand-700 hover:underline font-medium">
                원본 시안은 의료광고심의위원회에서 확인하세요 →
            </a>
        </div>
    </article>`;
}

window.reportError = function (display, text, reviewNum) {
    openReportModal({ display, text, reviewNum });
};

function openReportModal({ display, text, reviewNum }) {
    const modal = document.getElementById("report-modal");
    document.getElementById("report-display").textContent = display;
    document.getElementById("report-text-preview").textContent = text || "(없음)";
    document.getElementById("report-reason").value = "";
    document.getElementById("report-status").textContent = "";
    document.getElementById("report-status").className = "text-sm";
    modal.dataset.reviewNum = reviewNum;
    modal.dataset.display = display;
    modal.dataset.text = text;
    modal.classList.remove("hidden");
    setTimeout(() => document.getElementById("report-reason").focus(), 50);
}

function closeReportModal() {
    document.getElementById("report-modal").classList.add("hidden");
}

document.addEventListener("click", e => {
    if (e.target.id === "report-modal-close" || e.target.id === "report-modal-cancel"
        || e.target.dataset?.modalBackdrop === "true") {
        closeReportModal();
    }
});

document.getElementById("report-submit").addEventListener("click", async () => {
    const modal = document.getElementById("report-modal");
    const reason = document.getElementById("report-reason").value.trim();
    const statusEl = document.getElementById("report-status");

    if (reason.length < 2) {
        statusEl.textContent = "오류 사유를 2자 이상 입력해주세요.";
        statusEl.className = "text-sm text-red-700";
        return;
    }

    statusEl.textContent = "전송 중...";
    statusEl.className = "text-sm text-gray-600";

    try {
        const r = await fetch("/api/report", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                review_no_display: modal.dataset.display,
                review_num: parseInt(modal.dataset.reviewNum, 10),
                ocr_text: modal.dataset.text,
                reason,
            }),
        });
        if (r.ok) {
            statusEl.textContent = "✓ 제보 완료. 빠르게 검토하겠습니다.";
            statusEl.className = "text-sm text-green-700 font-semibold";
            setTimeout(closeReportModal, 1800);
        } else {
            const data = await r.json().catch(() => ({}));
            statusEl.textContent = "전송 실패: " + (data.error || r.status);
            statusEl.className = "text-sm text-red-700";
        }
    } catch (e) {
        statusEl.textContent = "네트워크 오류: " + e.message;
        statusEl.className = "text-sm text-red-700";
    }
});

window.copyText = async function (text) {
    try {
        await navigator.clipboard.writeText(text);
        // 토스트로 무음 복사 피드백
        const old = document.activeElement;
        const toast = document.createElement("div");
        toast.textContent = `복사됨: ${text}`;
        toast.className = "fixed bottom-6 left-1/2 -translate-x-1/2 bg-gray-900 text-white text-sm px-4 py-2 rounded-lg shadow-lg z-50";
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 1600);
    } catch {
        prompt("복사하세요:", text);
    }
};

async function runSearch(q) {
    const resultsEl = document.getElementById("results");
    const sectionEl = document.getElementById("results-section");
    const countEl = document.getElementById("result-count");
    const shownEl = document.getElementById("result-shown");
    const noteEl = document.getElementById("results-note");

    currentQuery = q;
    currentOffset = 0;
    resultsEl.innerHTML = `<p class="text-center text-gray-500 py-6">검색 중...</p>`;
    sectionEl.classList.remove("hidden");

    const { rows, total } = await search(q, 0);
    resultsEl.innerHTML = "";

    // GA4 검색 이벤트 트래킹 (사장님이 어떤 키워드가 인기인지 분석 가능)
    if (window.gtag) {
        window.gtag("event", "search", {
            search_term: q,
            results_count: total,
        });
    }

    if (rows.length === 0) {
        resultsEl.innerHTML = `<p class="text-center text-gray-500 py-6">검색 결과가 없습니다. 다른 키워드로 시도해보세요.</p>`;
        countEl.textContent = "0";
        shownEl.textContent = "0";
        noteEl.classList.add("hidden");
        return;
    }

    countEl.textContent = total.toLocaleString();
    shownEl.textContent = rows.length.toLocaleString();
    resultsEl.insertAdjacentHTML("beforeend", rows.map(r => renderRow(r, q)).join(""));

    // 5건 다 채워졌고 전체가 5건보다 많으면 안내 표시
    noteEl.classList.toggle("hidden", !(rows.length >= 5 && total > 5));
}

document.getElementById("search-form").addEventListener("submit", e => {
    e.preventDefault();
    const q = document.getElementById("q").value.trim();
    if (q) runSearch(q);
});

document.getElementById("clear-search").addEventListener("click", () => {
    document.getElementById("q").value = "";
    document.getElementById("results-section").classList.add("hidden");
    currentQuery = "";
    currentOffset = 0;
});

// ---------- 시작 ----------
loadStatistics();
