(function () {
  'use strict';

  function isPrivateIPv4(host) {
    const parts = host.split('.');
    if (parts.length !== 4 || parts.some(p => !/^\d{1,3}$/.test(p) || Number(p) > 255)) return false;
    const [a, b] = parts.map(Number);
    return a === 10 || a === 127 || (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127);
  }

  function isLocalHttpHost(hostname) {
    const host = hostname.toLowerCase().replace(/^\[|\]$/g, '');
    if (host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local')) return true;
    if (isPrivateIPv4(host)) return true;
    return host === '::1' || /^f[cd][0-9a-f:]*$/i.test(host);
  }

  function normalizeTrustedPanelOrigin(value) {
    if (typeof value !== 'string' || !value.trim() || value.length > 2048) return '';
    try {
      const url = new URL(value.trim());
      if (url.username || url.password || url.pathname !== '/' || url.search || url.hash) return '';
      if (url.protocol === 'https:') return url.origin;
      if (url.protocol === 'http:' && isLocalHttpHost(url.hostname)) return url.origin;
    } catch (_) {}
    return '';
  }

  globalThis.LaluneCaptchaOriginPolicy = Object.freeze({ normalizeTrustedPanelOrigin });
})();
