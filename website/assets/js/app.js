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

        const ts = new Date(data.generated_at).toLocaleString("ko-KR");
        document.getElementById("last-update").textContent = `마지막 업데이트: ${ts} • 총 누적 ${data.total.count.toLocaleString()}건`;

        renderChart(data.chart_30d);
    } catch (e) {
        console.warn("statistics.json 로드 실패:", e);
    }
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
    <article class="bg-white rounded-lg p-4 border border-gray-200 hover:border-blue-300 transition">
        <div class="flex items-center justify-between gap-2 mb-2">
            <div class="flex items-center gap-2">
                <span class="text-xs px-2 py-1 bg-gray-100 rounded text-gray-700 font-mono">${safeDisplay}</span>
                <span class="text-xs text-gray-500">${escapeHtml(row.review_date || "")}</span>
            </div>
            <button onclick="reportError('${safeDisplay}', \`${safeText.replace(/`/g, "\\`")}\`, '${escapeHtml(numberOnly)}')"
                    title="내용 오류 및 병원명 노출 시 제보해 주세요"
                    class="text-xs px-3 py-1.5 bg-red-50 text-red-700 border border-red-200 rounded-lg hover:bg-red-100 hover:border-red-400 font-semibold">
                🚨 오류제보하기
            </button>
        </div>
        <p class="text-sm leading-relaxed text-gray-800 whitespace-pre-wrap">${highlight(text, q)}</p>
        <div class="mt-3 pt-3 border-t border-gray-100 flex flex-wrap items-center gap-3 text-xs">
            <button onclick="copyText('${escapeHtml(numberOnly)}')"
                    class="px-2 py-1 border border-gray-300 rounded hover:bg-gray-100 hover:border-blue-300 text-gray-700">
                📋 심의번호 복사
            </button>
            <a href="${ADMEDICAL_LINK}" target="_blank" class="text-blue-700 hover:underline">
                → 심의 시안은 의료광고심의위원회에서 확인하세요
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
        // 사장님 요청: 알림창 대신 무음 복사
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
