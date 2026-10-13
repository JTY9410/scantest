// 관리자 공통 동작: 모바일 메뉴, 툴팁, 제출 중 표시, 확인 대화상자.
(() => {
  "use strict";

  // 모바일 메뉴(drawer)
  const sidebar = document.getElementById("sidebar");
  const backdrop = document.getElementById("sidebar-backdrop");
  const toggles = document.querySelectorAll("[data-drawer-toggle]");
  let lastFocus = null;

  function setDrawer(open) {
    if (!sidebar) return;
    sidebar.dataset.open = String(open);
    if (backdrop) backdrop.dataset.open = String(open);
    toggles.forEach((btn) => btn.setAttribute("aria-expanded", String(open)));
    document.body.classList.toggle("overflow-hidden", open);
    if (open) {
      lastFocus = document.activeElement;
      const first = sidebar.querySelector("a, button");
      if (first) first.focus();
    } else if (lastFocus) {
      lastFocus.focus();
      lastFocus = null;
    }
  }

  toggles.forEach((btn) =>
    btn.addEventListener("click", () => setDrawer(sidebar?.dataset.open !== "true")),
  );
  backdrop?.addEventListener("click", () => setDrawer(false));
  window.matchMedia("(min-width: 1024px)").addEventListener("change", (e) => {
    if (e.matches && sidebar?.dataset.open === "true") setDrawer(false);
  });

  // 툴팁
  const tips = Array.from(document.querySelectorAll(".tip"));
  const hoverCapable = window.matchMedia("(hover: hover) and (pointer: fine)").matches;

  function setTip(tip, open) {
    tip.dataset.open = String(open);
    tip.querySelector(".tip-trigger")?.setAttribute("aria-expanded", String(open));
  }

  tips.forEach((tip) => {
    const trigger = tip.querySelector(".tip-trigger");
    if (!trigger) return;
    trigger.addEventListener("click", (event) => {
      event.preventDefault();
      setTip(tip, tip.dataset.open !== "true");
    });
    trigger.addEventListener("focus", () => setTip(tip, true));
    trigger.addEventListener("blur", () => setTip(tip, false));
    if (hoverCapable) {
      tip.addEventListener("pointerenter", (e) => e.pointerType === "mouse" && setTip(tip, true));
      tip.addEventListener("pointerleave", (e) => e.pointerType === "mouse" && setTip(tip, false));
    }
  });

  document.addEventListener("click", (event) => {
    tips.forEach((tip) => {
      if (!tip.contains(event.target)) setTip(tip, false);
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const openTip = tips.find((tip) => tip.dataset.open === "true");
    if (openTip) {
      setTip(openTip, false);
      return;
    }
    if (sidebar?.dataset.open === "true") setDrawer(false);
  });

  // 확인이 필요한 동작(키 폐기 등)
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    });
  });

  // 제출 중 표시와 중복 제출 방지
  document.querySelectorAll("form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (event.defaultPrevented) return;
      const button = event.submitter || form.querySelector("[type=submit]");
      if (!button || form.method.toLowerCase() === "get") return;
      if (form.dataset.submitting === "true") {
        event.preventDefault();
        return;
      }
      form.dataset.submitting = "true";
      button.dataset.busy = "true";
      button.setAttribute("aria-busy", "true");
    });
  });

  // 뒤로 가기로 돌아왔을 때 제출 중 상태 해제
  window.addEventListener("pageshow", () => {
    document.querySelectorAll("form[data-submitting]").forEach((form) => {
      delete form.dataset.submitting;
      form.querySelectorAll("[data-busy]").forEach((b) => {
        delete b.dataset.busy;
        b.removeAttribute("aria-busy");
      });
    });
  });

  // 선택 상자를 바꾸면 바로 검색(필터 폼)
  document.querySelectorAll("form[data-autosubmit] select").forEach((select) => {
    select.addEventListener("change", () => select.form.requestSubmit());
  });
})();
