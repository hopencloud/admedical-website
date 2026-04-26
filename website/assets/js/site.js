/* eslint-env browser */
/*
 * 공통 사이트 스크립트 (모든 페이지가 1줄로 로드해서 공유).
 *
 * 책임:
 *   1. 공통 헤더(메뉴) HTML 주입  → <div id="site-header"></div> 자리에 삽입
 *   2. 현재 페이지에 active 표시
 *   3. 모바일 햄버거 토글
 *   4. 네이버 웹사이트 애널리틱스(WCS) 초기화 — 페이지뷰 1회 호출
 *
 * 페이지에서 추가할 것은 단 두 줄:
 *     <div id="site-header"></div>             <!-- body 시작 직후 -->
 *     <script src="/assets/js/site.js"></script>  <!-- body 끝 직전 -->
 *
 * 서치콘솔/애널리틱스 키 변경은 이 파일 한 곳만 수정.
 */
(function () {
    "use strict";

    // ---------- 1. 공통 헤더 HTML ----------
    const HEADER_HTML = `
<header class="bg-white border-b border-slate-200 sticky top-0 z-20">
    <div class="max-w-5xl mx-auto px-4 py-3.5 flex items-center justify-between gap-3">
        <a href="/" class="text-base md:text-xl font-bold text-brand-600 truncate tracking-tight">의료광고 심의 통과 시안</a>

        <nav class="hidden md:flex items-center gap-1 text-sm font-medium text-slate-700 shrink-0">
            <a data-nav="/about.html" href="/about.html" class="px-3 py-2 rounded-lg hover:text-brand-600 hover:bg-slate-50 transition">서비스 소개</a>

            <div class="nav-dropdown" data-nav-group="/guide/">
                <button type="button" class="nav-trigger px-3 py-2 rounded-lg hover:text-brand-600 hover:bg-slate-50 transition inline-flex items-center" aria-haspopup="true">심의 가이드<span class="nav-caret">▾</span></button>
                <div class="nav-dropdown__panel" role="menu">
                    <a href="/guide/about-review.html" class="nav-dropdown__item">의료광고심의란?</a>
                    <a href="/guide/application.html" class="nav-dropdown__item">심의 신청 방법</a>
                    <a href="/guide/target-media.html" class="nav-dropdown__item">심의 대상 매체</a>
                    <a href="/guide/exempt.html" class="nav-dropdown__item">심의 면제 광고</a>
                    <a href="/guide/forbidden-expressions.html" class="nav-dropdown__item">의료광고 금지 표현</a>
                    <a href="/guide/review-number.html" class="nav-dropdown__item">심의번호 읽는 법</a>
                    <a href="/guide/faq.html" class="nav-dropdown__item">자주 묻는 질문</a>
                </div>
            </div>

            <div class="nav-dropdown" data-nav-group="/top20">
                <button type="button" class="nav-trigger px-3 py-2 rounded-lg hover:text-brand-600 hover:bg-slate-50 transition inline-flex items-center" aria-haspopup="true">심의통과 TOP 20 키워드<span class="nav-caret">▾</span></button>
                <div class="nav-dropdown__panel" role="menu">
                    <a href="/top20.html?period=this-week" class="nav-dropdown__item">이번주</a>
                    <a href="/top20.html?period=this-month" class="nav-dropdown__item">이번달</a>
                    <a href="/top20.html?period=last-week" class="nav-dropdown__item">지난주</a>
                    <a href="/top20.html?period=last-month" class="nav-dropdown__item">지난달</a>
                </div>
            </div>

            <a data-nav="/contact.html" href="/contact.html" class="px-3 py-2 rounded-lg hover:text-brand-600 hover:bg-slate-50 transition">문의</a>
        </nav>

        <button id="mobile-menu-btn" class="md:hidden text-2xl text-slate-700 px-2" aria-label="메뉴 열기" aria-expanded="false">☰</button>
    </div>

    <nav id="mobile-menu" class="hidden md:hidden border-t border-slate-100 px-4 py-2 text-sm">
        <a data-nav="/about.html" href="/about.html" class="block py-2 text-slate-700 hover:text-brand-600">서비스 소개</a>
        <details class="mobile-group" data-nav-group="/guide/">
            <summary>심의 가이드</summary>
            <div class="mobile-group__items">
                <a href="/guide/about-review.html">의료광고심의란?</a>
                <a href="/guide/application.html">심의 신청 방법</a>
                <a href="/guide/target-media.html">심의 대상 매체</a>
                <a href="/guide/exempt.html">심의 면제 광고</a>
                <a href="/guide/forbidden-expressions.html">의료광고 금지 표현</a>
                <a href="/guide/review-number.html">심의번호 읽는 법</a>
                <a href="/guide/faq.html">자주 묻는 질문</a>
            </div>
        </details>
        <details class="mobile-group" data-nav-group="/top20">
            <summary>심의통과 TOP 20 키워드</summary>
            <div class="mobile-group__items">
                <a href="/top20.html?period=this-week">이번주</a>
                <a href="/top20.html?period=this-month">이번달</a>
                <a href="/top20.html?period=last-week">지난주</a>
                <a href="/top20.html?period=last-month">지난달</a>
            </div>
        </details>
        <a data-nav="/contact.html" href="/contact.html" class="block py-2 text-slate-700 hover:text-brand-600">문의</a>
    </nav>
</header>
`;

    // ---------- 2. 헤더 주입 + active 표시 ----------
    function mountHeader() {
        const slot = document.getElementById("site-header");
        if (!slot) return;
        slot.outerHTML = HEADER_HTML;

        const path = location.pathname.replace(/\/index\.html$/, "/");

        // 단일 메뉴 (data-nav)
        document.querySelectorAll("[data-nav]").forEach(el => {
            const target = el.getAttribute("data-nav");
            if (target === path) {
                if (el.classList.contains("block")) {
                    el.classList.add("text-brand-600", "font-semibold");
                    el.classList.remove("text-slate-700");
                } else {
                    el.classList.add("text-brand-600", "bg-brand-50");
                    el.classList.remove("hover:text-brand-600", "hover:bg-slate-50");
                }
            }
        });

        // 그룹(드롭다운) 활성화
        document.querySelectorAll("[data-nav-group]").forEach(el => {
            const prefix = el.getAttribute("data-nav-group");
            if (path.startsWith(prefix)) {
                if (el.classList.contains("nav-dropdown")) {
                    const trigger = el.querySelector(".nav-trigger");
                    trigger?.classList.add("text-brand-600", "bg-brand-50");
                    trigger?.classList.remove("hover:text-brand-600", "hover:bg-slate-50");
                } else if (el.tagName === "DETAILS") {
                    el.setAttribute("open", "");
                    const summary = el.querySelector("summary");
                    summary?.classList.add("text-brand-600", "font-semibold");
                }
            }
        });

        // 모바일 토글
        const btn = document.getElementById("mobile-menu-btn");
        const menu = document.getElementById("mobile-menu");
        btn?.addEventListener("click", () => {
            const open = menu.classList.toggle("hidden") === false;
            btn.setAttribute("aria-expanded", String(open));
        });
    }

    // ---------- 3. 네이버 웹사이트 애널리틱스 (WCS) ----------
    // 키 변경 시 이 한 줄만 수정.
    const NAVER_WA_ID = "9bb3451085cce8";

    function loadNaverAnalytics() {
        if (!window.wcs_add) window.wcs_add = {};
        window.wcs_add["wa"] = NAVER_WA_ID;

        if (window.wcs) {
            window.wcs_do();
            return;
        }
        const s = document.createElement("script");
        s.src = "//wcs.pstatic.net/wcslog.js";
        s.async = true;
        s.onload = () => { if (window.wcs) window.wcs_do(); };
        document.head.appendChild(s);
    }

    // ---------- 부팅 ----------
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => {
            mountHeader();
            loadNaverAnalytics();
        });
    } else {
        mountHeader();
        loadNaverAnalytics();
    }
})();
