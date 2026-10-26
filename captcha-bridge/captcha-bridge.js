(function () {
  'use strict';
  if (window.__laluneCaptchaBridgeInstalled) return;
  window.__laluneCaptchaBridgeInstalled = true;

  function panelOrigin() {
    try {
      const hash = location.hash || '';
      const m = hash.match(/(?:^|[#&])lalune_panel=([^&]+)/);
      if (m) return decodeURIComponent(m[1]);
    } catch (_) {}
    try {
      if (document.referrer) return new URL(document.referrer).origin;
    } catch (_) {}
    return '';
  }

  let sent = false;
  function sendToken(token) {
    if (!token || sent) return;
    const origin = panelOrigin();
    if (!origin) return;
    const sessionToken = (function () {
      try {
        const hash = location.hash || '';
        const match = hash.match(/(?:^|[#&])lalune_session=([^&]+)/);
        return match ? decodeURIComponent(match[1]) :
          (new URL(location.href).searchParams.get('session_token') || '');
      } catch (_) { return ''; }
    })();
    if (!sessionToken) return;
    // Return to the panel instead of making a cross-origin POST from VK.
    // The fragment is never sent in the HTTP request; the authenticated panel
    // consumes it and submits the result through its own same-origin API.
    const target = new URL('/', origin);
    target.hash = new URLSearchParams({
      lalune_captcha_session: sessionToken,
      lalune_captcha_result: String(token)
    }).toString();
    sent = true;
    location.replace(target.toString());
  }

  function inspect(data) {
    try {
      if (data && data.response && data.response.success_token) {
        sendToken(data.response.success_token);
      }
    } catch (_) {}
  }

  const originalFetch = window.fetch;
  if (originalFetch) {
    window.fetch = function () {
      return originalFetch.apply(this, arguments).then(function (response) {
        try {
          const url = typeof arguments[0] === 'string' ? arguments[0] : (arguments[0] && arguments[0].url) || '';
          if (String(url).includes('captchaNotRobot.check')) {
            response.clone().json().then(inspect).catch(function () {});
          }
        } catch (_) {}
        return response;
      });
    };
  }

  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__laluneCaptchaUrl = String(url || '');
    return originalOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function () {
    if (this.__laluneCaptchaUrl.includes('captchaNotRobot.check')) {
      this.addEventListener('load', function () {
        try { inspect(JSON.parse(this.responseText)); } catch (_) {}
      });
    }
    return originalSend.apply(this, arguments);
  };
})();