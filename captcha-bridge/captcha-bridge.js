(function () {
  'use strict';
  if (globalThis.__laluneCaptchaBridgeIsolatedInstalled) return;
  globalThis.__laluneCaptchaBridgeIsolatedInstalled = true;

  const VK_ORIGINS = new Set(['https://id.vk.com', 'https://id.vk.ru']);
  const policy = globalThis.LaluneCaptchaOriginPolicy;
  if (!policy || typeof policy.normalizeTrustedPanelOrigin !== 'function') return;

  function getTrustedPanelOrigin(callback) {
    const storage = (globalThis.browser && globalThis.browser.storage &&
      globalThis.browser.storage.local) || (globalThis.chrome && globalThis.chrome.storage &&
      globalThis.chrome.storage.local);
    if (!storage || typeof storage.get !== 'function') { callback(''); return; }
    let completed = false;
    const done = value => {
      if (completed) return;
      completed = true;
      const configured = value && value.trustedPanelOrigin;
      callback(policy.normalizeTrustedPanelOrigin(configured));
    };
    try {
      if (globalThis.browser && globalThis.browser.storage && globalThis.browser.storage.local === storage) {
        storage.get('trustedPanelOrigin').then(done).catch(() => done(null));
      } else {
        storage.get('trustedPanelOrigin', done);
      }
    } catch (_) { done(null); }
  }

  function getSessionToken() {
    try {
      const hash = new URLSearchParams(location.hash.slice(1));
      const fromHash = hash.get('lalune_session');
      const fromQuery = new URL(location.href).searchParams.get('session_token');
      const value = (fromHash || fromQuery || '').trim();
      return value && value.length <= 1024 && !/[\r\n]/.test(value) ? value : '';
    } catch (_) { return ''; }
  }

  let sent = false;
  window.addEventListener('message', function (event) {
    if (event.source !== window || event.origin !== location.origin ||
        !VK_ORIGINS.has(location.origin)) return;
    const data = event.data;
    if (!data || data.channel !== 'lalune-captcha-bridge' ||
        data.type !== 'captcha-success' || typeof data.token !== 'string') return;
    const token = data.token.trim();
    if (!token || token.length > 16384 || /[\r\n]/.test(token) || sent) return;

    const sessionToken = getSessionToken();
    if (!sessionToken) return;
    getTrustedPanelOrigin(function (trustedOrigin) {
      if (!trustedOrigin || sent) return;
      // Ignore lalune_panel fragments and document.referrer entirely. The only
      // redirect target is the exact origin explicitly configured in extension
      // options and normalized by the shared origin policy.
      const target = new URL('/', trustedOrigin);
      target.hash = new URLSearchParams({
        lalune_captcha_session: sessionToken,
        lalune_captcha_result: token
      }).toString();
      sent = true;
      location.replace(target.toString());
    });
  });
})();
