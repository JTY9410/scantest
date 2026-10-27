// PWA: service worker 등록과 설치 안내.
// OS가 로그인만으로 자동 설치하진 않는다. 설치 가능해지면 안내를 바로 띄우고,
// 사용자가 '설치하기'를 누르면 브라우저 설치 창(바탕화면·홈 화면)을 연다.
(() => {
  "use strict";

  const DISMISS_KEY = "wecarscan.install.dismissedAt";
  const PENDING_KEY = "wecarscan.install.pending";
  const hint = document.getElementById("install-hint");
  const ua = navigator.userAgent || "";
  let deferredPrompt = null;

  function registerWorker() {
    if (!("serviceWorker" in navigator) || !window.isSecureContext) return;
    navigator.serviceWorker.register("/service-worker.js", { scope: "/admin/" }).catch(() => {});
  }

  if (document.readyState === "complete") registerWorker();
  else window.addEventListener("load", registerWorker);

  if (!hint) return;

  const isStandalone =
    window.matchMedia("(display-mode: standalone)").matches ||
    window.matchMedia("(display-mode: window-controls-overlay)").matches ||
    window.navigator.standalone === true;
  const isIOS = /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  const isAndroid = /Android/i.test(ua);
  const isDesktop = !isIOS && !isAndroid && !/Mobile/i.test(ua);
  const isInApp = /KAKAOTALK|NAVER\(inapp|Line\/|Instagram|FBAN|FBAV|DaumApps|everytimeApp|; wv\)/i.test(ua);

  function storage(fn) {
    try {
      return fn();
    } catch {
      return null;
    }
  }

  function variant() {
    if (isStandalone) return "installed";
    if (isInApp) return isAndroid ? "inapp-android" : "inapp";
    if (deferredPrompt) return "prompt";
    if (isIOS) return "ios";
    return "unsupported";
  }

  function show(force) {
    const v = variant();
    if (!force) {
      if (v === "installed" || v === "unsupported") return;
      if (storage(() => localStorage.getItem(DISMISS_KEY))) return;
      // Chrome/Edge 설치 가능 시점·로그인 직후 안내는 PENDING 없이도 바로 표시
      const pending = storage(() => sessionStorage.getItem(PENDING_KEY)) === "1";
      if (v !== "prompt" && !pending) return;
    }
    hint.dataset.variant = v;
    hint.dataset.state = "visible";
    if (isDesktop) hint.dataset.surface = "desktop";
    else if (isIOS || isAndroid) hint.dataset.surface = "mobile";
    else hint.dataset.surface = "";
    if (v === "prompt") {
      hint.querySelector("[data-install-accept]")?.focus({ preventScroll: true });
    }
  }

  function hide(remember) {
    hint.dataset.state = "hidden";
    storage(() => sessionStorage.removeItem(PENDING_KEY));
    if (remember) storage(() => localStorage.setItem(DISMISS_KEY, String(Date.now())));
  }

  // 로그인 직후 첫 화면: 설치 안내를 이번 세션에서 연다.
  if (hint.dataset.firstLogin === "true") {
    storage(() => sessionStorage.setItem(PENDING_KEY, "1"));
    storage(() => localStorage.removeItem(DISMISS_KEY));
  }

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt = event;
    // 설치 가능해지는 순간 안내를 띄운다(거절·나중에 기억은 유지).
    show(false);
  });

  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    hide(true);
  });

  hint.querySelector("[data-install-accept]")?.addEventListener("click", async () => {
    if (!deferredPrompt) return;
    const prompt = deferredPrompt;
    deferredPrompt = null;
    prompt.prompt();
    const choice = await prompt.userChoice.catch(() => null);
    hide(choice?.outcome !== "accepted");
  });

  hint.querySelectorAll("[data-install-later]").forEach((btn) =>
    btn.addEventListener("click", () => hide(true)),
  );

  hint.querySelector("[data-open-external]")?.addEventListener("click", () => {
    const url = new URL(window.location.href);
    const fallback = encodeURIComponent(url.href);
    window.location.href =
      `intent://${url.host}${url.pathname}${url.search}#Intent;scheme=https;` +
      `S.browser_fallback_url=${fallback};end`;
  });

  hint.querySelector("[data-copy-url]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const status = hint.querySelector("[data-copy-status]");
    try {
      await navigator.clipboard.writeText(window.location.origin + "/admin/");
      if (status) status.textContent = "주소를 복사했습니다. 기본 브라우저 주소창에 붙여넣으세요.";
    } catch {
      if (status) status.textContent = `복사하지 못했습니다. 주소: ${window.location.origin}/admin/`;
    }
    button.blur();
  });

  document.querySelectorAll("[data-install-reopen]").forEach((btn) =>
    btn.addEventListener("click", () => {
      storage(() => localStorage.removeItem(DISMISS_KEY));
      storage(() => sessionStorage.setItem(PENDING_KEY, "1"));
      show(true);
      hint.focus();
    }),
  );

  // iOS·인앱·이미 프롬프트가 있는 경우 즉시 안내
  show(false);
})();
