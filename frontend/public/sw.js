// Service worker do modo campo: guarda a casca do app para abrir sem rede.
// Dados da API sempre vêm da rede (nunca servidos do cache).
const CACHE = "atalaia-v2";
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(["/", "/campo", "/manifest.webmanifest", "/icone.svg"])));
  self.skipWaiting();
});
self.addEventListener("activate", (e) =>
  e.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  ),
);
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== self.location.origin) return;
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        // Só guarda respostas boas: um erro 404/500 não pode virar a versão "offline"
        if (r.ok) {
          const copia = r.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copia));
        }
        return r;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match("/"))),
  );
});
