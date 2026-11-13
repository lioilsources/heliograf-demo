/* pwa.js — registers sw.js from the site root (plan 02 A). The root is derived from this script's own
   URL (…/shared/pwa.js), so it works on a custom domain and under user.github.io/<repo>/ alike. */
(function () {
  var s = document.currentScript;
  if (!s || !('serviceWorker' in navigator)) return;
  var root = s.src.replace(/shared\/pwa\.js(\?.*)?$/, '');
  window.addEventListener('load', function () {
    navigator.serviceWorker.register(root + 'sw.js', { scope: root }).catch(function () {});
  });
})();
