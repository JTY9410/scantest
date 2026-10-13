// 공개 정적 파일(/static/)만 버전별로 캐시한다.
// 로그인 응답·관리자 화면·API는 가로채지 않고 항상 네트워크로 보낸다.
const VERSION = "__ASSET_VERSION__";
const CACHE = `wecarscan-static-${VERSION}`;
const PRECACHE = [
  `/static/dist/app.css?v=${VERSION}`,
  `/static/js/app.js?v=${VERSION}`,
  `/static/js/components/pwa.js?v=${VERSION}`,
  "/static/brand/wecar-logo.png",
  "/static/brand/icon-192.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((key) => key.startsWith("wecarscan-static-") && key !== CACHE).map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || !url.pathname.startsWith("/static/")) return;

  event.respondWith(
    caches.open(CACHE).then(async (cache) => {
      const cached = await cache.match(request);
      if (cached) return cached;
      const response = await fetch(request);
      if (response.ok && response.type === "basic") cache.put(request, response.clone());
      return response;
    }),
  );
});
