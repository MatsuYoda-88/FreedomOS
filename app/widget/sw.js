// FreedomOS phone app helper v1.3.1. Doesn't save anything - always shows the live crew, never an old copy.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET" || e.request.url.includes("/events")) return;
  const fresh = e.request.mode === "navigate" || /\.(html|js)(\?|$)/.test(e.request.url) || new URL(e.request.url).pathname === "/";
  e.respondWith(fetch(fresh ? new Request(e.request.url, {cache: "no-store", credentials: "include"}) : e.request).catch(() => new Response(
    "<body style='background:#121722;color:#ddd;font:18px sans-serif;padding:30px'>Can't reach the shop. Is the desktop on with FreedomOS running, and Tailscale on?</body>",
    {headers: {"Content-Type": "text/html"}})));
});
