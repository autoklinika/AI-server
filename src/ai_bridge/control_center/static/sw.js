const CACHE = "ai-control-shell-v2";
const SHELL = [
  "/control/",
  "/control/assets/styles.css",
  "/control/assets/app.js",
  "/control/assets/icon.svg",
  "/control/manifest.webmanifest"
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) {
      return Promise.all(SHELL.map(function (url) {
        return fetch(url, { cache: "reload" }).then(function (response) {
          if (!response.ok) throw new Error("shell_fetch_failed");
          return cache.put(url, response);
        });
      }));
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (key) {
        return key !== CACHE;
      }).map(function (key) {
        return caches.delete(key);
      }));
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", function (event) {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Platform API data is always live and never enters the PWA cache.
  if (url.pathname.startsWith("/control/api/") || url.pathname.startsWith("/api/")) return;

  if (!url.pathname.startsWith("/control/")) return;

  // UI shell/assets are network-first so every Stage O rollout is visible
  // without manual cache clearing. Cached content is only an offline fallback.
  event.respondWith(
    fetch(request, { cache: "no-cache" }).then(function (response) {
      if (response.ok) {
        const copy = response.clone();
        caches.open(CACHE).then(function (cache) {
          cache.put(request, copy);
        });
      }
      return response;
    }).catch(function () {
      return caches.match(request).then(function (cached) {
        return cached || caches.match("/control/");
      });
    })
  );
});
