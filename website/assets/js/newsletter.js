/* eslint-env browser */
/*
 * 뉴스레터 구독 폼.
 *
 * 페이지 어디에 있든 .newsletter-form 을 찾아 동작을 붙인다.
 * 서버는 /api/subscribe 하나만 쓴다.
 */
(function () {
    "use strict";

    function show(form, message, ok) {
        var el = form.parentElement.querySelector(".newsletter-msg");
        if (!el) return;
        el.textContent = message;
        el.className = "newsletter-msg mt-3 text-sm " +
                       (ok ? "text-emerald-700" : "text-rose-700");
    }

    function bind(form) {
        form.addEventListener("submit", async function (e) {
            e.preventDefault();

            var input = form.querySelector('input[name="email"]');
            var button = form.querySelector('button[type="submit"]');
            var email = (input.value || "").trim();

            if (!email || email.indexOf("@") < 1 || email.indexOf(".") < 0) {
                show(form, "이메일 주소를 확인해 주세요.", false);
                input.focus();
                return;
            }

            button.disabled = true;
            var original = button.textContent;
            button.textContent = "등록 중…";

            try {
                var res = await fetch("/api/subscribe", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        email: email,
                        website: (form.querySelector('input[name="website"]') || {}).value || "",
                    }),
                });
                var data = await res.json().catch(function () { return {}; });

                if (res.ok) {
                    show(form, data.message || "구독 신청이 완료되었습니다. 내일 아침부터 보내드립니다.", true);
                    form.reset();
                } else {
                    show(form, data.error || "등록에 실패했습니다. 잠시 후 다시 시도해 주세요.", false);
                }
            } catch (err) {
                show(form, "네트워크 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.", false);
            } finally {
                button.disabled = false;
                button.textContent = original;
            }
        });
    }

    document.querySelectorAll(".newsletter-form").forEach(bind);
})();
