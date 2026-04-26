/* eslint-env browser */
/*
 * Google AdSense 광고 매니저.
 *
 * 사용법:
 *   1. AdSense 승인 받으면 아래 ADSENSE_PUBLISHER_ID 와 SLOT_IDS 채우기.
 *   2. ADSENSE_ENABLED를 true로 변경.
 *   3. git push → 자동 배포 → 광고 활성화.
 *
 * 광고 슬롯은 페이지 안의 <div class="ad-slot" data-slot-name="..."></div> 자리에 자동 삽입됨.
 *
 * 활성화 전에는 .ad-slot이 CSS로 숨겨져 있어 사용자에게 안 보임 (UX 영향 없음).
 */
(function () {
    "use strict";

    // ============================================================
    // ⚙ AdSense 설정 (승인 후 사장님이 수정할 부분)
    // ============================================================
    const ADSENSE_ENABLED = false;  // 승인 후 true로 변경
    const ADSENSE_PUBLISHER_ID = "ca-pub-XXXXXXXXXXXXXXXX";  // AdSense 콘솔에서 받은 ca-pub-... 값

    // 페이지별 광고 슬롯 ID. AdSense 콘솔에서 광고 단위 만들 때마다 발급받아 입력.
    const SLOT_IDS = {
        // 메인 검색 페이지
        "search-results-bottom": "0000000000",   // 검색 결과 5개 다음, 통계 위

        // TOP 20 페이지
        "top20-top":             "0000000000",   // 탭 아래, 리스트 위

        // 가이드 페이지 (7개 페이지 공통 슬롯 1개)
        "article-end":           "0000000000",   // 본문 끝, 관련 페이지 위
    };

    // ============================================================
    // 이하 자동 처리 (수정 불필요)
    // ============================================================

    if (!ADSENSE_ENABLED) {
        // 미활성 상태: .ad-slot은 CSS에서 display:none 이므로 그냥 종료
        return;
    }

    function loadAdSenseScript() {
        if (window.adsbygoogle) return;  // 이미 로드됨
        const s = document.createElement("script");
        s.async = true;
        s.crossOrigin = "anonymous";
        s.src = "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=" +
                encodeURIComponent(ADSENSE_PUBLISHER_ID);
        document.head.appendChild(s);
    }

    function injectAdSlot(slotEl) {
        const slotName = slotEl.dataset.slotName;
        const slotId = SLOT_IDS[slotName];
        if (!slotId || slotId.startsWith("0000")) {
            // 미발급 슬롯은 스킵
            return;
        }

        // 이미 주입된 경우 중복 방지
        if (slotEl.querySelector("ins.adsbygoogle")) return;

        const ins = document.createElement("ins");
        ins.className = "adsbygoogle";
        ins.style.display = "block";
        ins.style.minHeight = "100px";
        ins.setAttribute("data-ad-client", ADSENSE_PUBLISHER_ID);
        ins.setAttribute("data-ad-slot", slotId);
        ins.setAttribute("data-ad-format", slotEl.dataset.adFormat || "auto");
        ins.setAttribute("data-full-width-responsive", "true");

        slotEl.appendChild(ins);
        slotEl.classList.add("ad-slot--active");

        try {
            (window.adsbygoogle = window.adsbygoogle || []).push({});
        } catch (e) {
            console.warn("[ads] push failed:", e);
        }
    }

    function init() {
        loadAdSenseScript();
        document.querySelectorAll(".ad-slot").forEach(injectAdSlot);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
