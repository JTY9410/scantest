// PWA: service worker 등록과 사용자가 선택하는 설치 안내.
// - 설치는 사용자가 버튼을 눌렀을 때만 브라우저 프롬프트를 띄운다.
// - '나중에'를 고르면 기억하고, 메뉴의 '앱 설치 안내'에서 다시 연다.
// - 카카오톡·네이버 등 인앱 브라우저는 기본 브라우저로 열기와 URL 복사를 안내한다.
(() => {
  "use strict";

  const DISMISS_KEY = "wecarscan.install.dismissedAt";
  const PENDING_KEY = "wecarscan.install.pending";
  const hint = document.getElementById("install-hint");
  const ua = navigator.userAgent || "";
  let deferredPrompt = null;

  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/service-worker.js", { scope: "/admin/" }).catch(() => {});
    });
  }

  if (!hint) return;

  const isStandalone =
    window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  const isIOS = /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  const isAndroid = /Android/i.test(ua);
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
      if (storage(() => sessionStorage.getItem(PENDING_KEY)) !== "1") return;
    }
    hint.dataset.variant = v;
    hint.dataset.state = "visible";
  }

  function hide(remember) {
    hint.dataset.state = "hidden";
    storage(() => sessionStorage.removeItem(PENDING_KEY));
    if (remember) storage(() => localStorage.setItem(DISMISS_KEY, String(Date.now())));
  }

  // 로그인 직후 첫 화면에서만 서버가 data-first-login 을 단다.
  if (hint.dataset.firstLogin === "true") storage(() => sessionStorage.setItem(PENDING_KEY, "1"));

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt = event;
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
      show(true);
      hint.focus();
    }),
  );

  // 이미 설치 프롬프트 없이도 안내가 가능한 경우(iOS, 인앱)
  show(false);
})();
