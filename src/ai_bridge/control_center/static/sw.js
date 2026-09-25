const CACHE = "ai-control-gui0-v1";
const SHELL = [
  "/control/",
  "/control/assets/styles.css",
  "/control/assets/app.js",
  "/control/assets/icon.svg",
  "/control/manifest.webmanifest"
];

self.addEventListener("install", function (event) {
  event.waitUntil(caches.open(CACHE).then(function (cache) {
    return cache.addAll(SHELL);
  }));
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

  // Operational data must always come from Platform API, never from PWA cache.
  if (url.pathname.startsWith("/api/")) return;

  if (request.mode === "navigate" && url.pathname.startsWith("/control/")) {
    event.respondWith(
      fetch(request).catch(function () {
        return caches.match("/control/");
      })
    );
    return;
  }

  if (url.pathname.startsWith("/control/")) {
    event.respondWith(
      caches.match(request).then(function (cached) {
        return cached || fetch(request).then(function (response) {
          const copy = response.clone();
          caches.open(CACHE).then(function (cache) {
            cache.put(request, copy);
          });
          return response;
        });
      })
    );
  }
});
