/* sw.js — offline layer (plan 02 A). Copied to the site root by scripts/pwa.py, which fills in
   __BUILD_ID__ and __ASSETS_ORIGIN__. Pages: network-first (offline → last copy → offline.html),
   CSS/JS: stale-while-revalidate, images: cache-first with a size limit. Nothing from foreign hosts. */
'use strict';
var BUILD = '__BUILD_ID__';
var ASSETS = '__ASSETS_ORIGIN__';
var PAGES = 'pages-' + BUILD, STATIC = 'static-' + BUILD, IMAGES = 'images-v1';
var LIMIT = { pages: 60, images: 150 };

// → 'network-first' | 'swr' | 'cache-first' | null (= leave to the browser)
function strategyFor(url, method, navigate, origin, assets) {
  if (method !== 'GET') return null;
  var u = new URL(url);
  var own = u.origin === origin, asset = !!assets && u.origin === assets;
  if (!own && !asset) return null;
  var m = /\.([a-z0-9]{1,12})$/i.exec(u.pathname), ext = m ? m[1].toLowerCase() : '';
  if (/^(jpe?g|png|gif|webp|avif|svg)$/.test(ext)) return 'cache-first';
  if (!own) return null;                                   // big downloads (mp4, zip, pdf) straight through
  if (navigate || ext === '' || ext === 'html' || ext === 'htm') return 'network-first';
  if (/^(css|js|json|webmanifest|woff2?)$/.test(ext)) return 'swr';
  return null;
}

// oldest entries over the limit (Cache.keys() keeps insertion order)
function overflow(keys, max) { return keys.length > max ? keys.slice(0, keys.length - max) : []; }

if (typeof module !== 'undefined') module.exports = { strategyFor: strategyFor, overflow: overflow };

if (typeof self !== 'undefined' && self.registration) {
  var OFFLINE = new URL('offline.html', self.registration.scope).href;

  var trim = function (name, max) {
    return caches.open(name).then(function (c) {
      return c.keys().then(function (k) { return Promise.all(overflow(k, max).map(function (r) { return c.delete(r); })); });
    });
  };
  var put = function (name, req, res, max) {
    if (!res || !(res.ok || res.type === 'opaque')) return;
    var copy = res.clone();
    caches.open(name).then(function (c) { return c.put(req, copy); }).then(function () { if (max) trim(name, max); });
  };

  self.addEventListener('install', function (e) {
    e.waitUntil(caches.open(PAGES).then(function (c) { return c.add(OFFLINE); }).then(function () { return self.skipWaiting(); }));
  });
  self.addEventListener('activate', function (e) {
    e.waitUntil(caches.keys().then(function (names) {
      return Promise.all(names.filter(function (n) { return [PAGES, STATIC, IMAGES].indexOf(n) < 0; })
        .map(function (n) { return caches.delete(n); }));
    }).then(function () { return self.clients.claim(); }));
  });
  self.addEventListener('fetch', function (e) {
    var req = e.request;
    var s = strategyFor(req.url, req.method, req.mode === 'navigate', self.location.origin, ASSETS);
    if (s === 'network-first') {
      e.respondWith(fetch(req).then(function (r) { put(PAGES, req, r, LIMIT.pages); return r; }).catch(function () {
        return caches.match(req, { ignoreSearch: true }).then(function (hit) { return hit || caches.match(OFFLINE); });
      }));
    } else if (s === 'swr') {
      e.respondWith(caches.match(req).then(function (hit) {
        var net = fetch(req).then(function (r) { put(STATIC, req, r); return r; });
        return hit ? (net.catch(function () {}), hit) : net;
      }));
    } else if (s === 'cache-first') {
      e.respondWith(caches.match(req).then(function (hit) {
        return hit || fetch(req).then(function (r) { put(IMAGES, req, r, LIMIT.images); return r; });
      }));
    }
  });
}
