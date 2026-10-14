/**
 * Service Worker de StrikeHub: hace instalable la app (requisito para
 * `beforeinstallprompt`) y da un respaldo sin conexiÃ³n.
 *
 * Estrategia:
 * - App shell (HTML/CSS/JS/logo/iconos): cache-first, precacheado al instalar.
 * - /api/*: network-first (los marcadores nunca deben salir rancios);
 *   si no hay red, se sirve lo Ãºltimo guardado.
 * - NavegaciÃ³n sin red: cae a index.html cacheado.
 *
 * Al desplegar con cambios en dist/*, sube CACHE_VERSION (mismo nÃºmero
 * que el ?v= de index.html) para que los clientes tomen lo nuevo.
 *
 * IMPORTANTE â€” no interceptar otros orÃ­genes (lÃ­nea `url.origin`):
 * la CSP del sitio declara `connect-src 'self'`, y el `fetch()` de un
 * service worker SÃ se evalÃºa contra connect-src (a diferencia del
 * <img> del navegador, que usa img-src y sÃ­ admite https:). Sin este
 * `return`, interceptar los logos de mlbstatic.com los rompÃ­a todos:
 *Images servidas por otros dominios (logos de MLB en mlbstatic.com,
 * imÃ¡genes de noticias) las deja pasar al navegador, que las resuelve
 * con img-src. AdemÃ¡s nunca se cacheaban aquÃ­: una request no-cors
 * devuelve response opaca y `res.ok` es false.
 */
const CACHE_VERSION = '20261018';
const CACHE = `strikehub-v${CACHE_VERSION}`;

const SHELL = [
  './',
  'index.html',
  'manifest.json',
  'dist/app.bundle.min.js',
  'dist/styles.min.css',
  'assets/logos/strikehub-logo.svg',
  'assets/icons/icon-192.png',
  'assets/icons/icon-512.png',
  'assets/icons/favicon.svg',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  // Otros orÃ­genes: que los resuelva el navegador (ver nota de cabecera).
  if (url.origin !== self.location.origin) return;
  if (url.pathname.includes('/api/')) {
    // API: red primero, cachÃ© como respaldo sin conexiÃ³n.
    event.respondWith(
      fetch(request)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((cache) => cache.put(request, copy));
          }
          return res;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // EstÃ¡ticos: cachÃ© primero.
  event.respondWith(
    caches.match(request).then((hit) => {
      if (hit) return hit;
      return fetch(request).then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return res;
      }).catch(() => {
        if (request.mode === 'navigate') return caches.match('index.html');
        throw new Error('offline');
      });
    })
  );
});
