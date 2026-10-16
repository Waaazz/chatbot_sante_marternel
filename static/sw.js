/* MamaBot BF — service worker
   - Pages HTML : réseau d'abord, page hors-ligne en secours (jamais mises en cache,
     elles contiennent des données personnelles).
   - Ressources statiques (CSS, icônes, polices, CDN) : cache d'abord.
   - Requêtes POST / API : jamais interceptées. */

const VERSION = 'v1';
const STATIC_CACHE = `mamabot-static-${VERSION}`;
const OFFLINE_URL = '/offline';

const PRECACHE = [
  OFFLINE_URL,
  '/static/style.css',
  '/static/images/favicon.svg',
  '/static/images/logo.svg',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

const CDN_HOSTS = [
  'cdn.jsdelivr.net',
  'cdnjs.cloudflare.com',
  'fonts.googleapis.com',
  'fonts.gstatic.com',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k.startsWith('mamabot-') && k !== STATIC_CACHE)
            .map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

function isStaticAsset(url) {
  if (url.origin === self.location.origin) {
    return url.pathname.startsWith('/static/');
  }
  return CDN_HOSTS.includes(url.hostname);
}

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok || response.type === 'opaque') {
    const cache = await caches.open(STATIC_CACHE);
    cache.put(request, response.clone());
  }
  return response;
}

async function networkWithOfflineFallback(request) {
  try {
    return await fetch(request);
  } catch (err) {
    return (await caches.match(OFFLINE_URL)) || Response.error();
  }
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  if (request.mode === 'navigate') {
    event.respondWith(networkWithOfflineFallback(request));
    return;
  }

  if (isStaticAsset(url)) {
    event.respondWith(cacheFirst(request));
  }
});
