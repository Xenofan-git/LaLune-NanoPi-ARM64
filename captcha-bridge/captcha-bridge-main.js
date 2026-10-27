(function () {
  'use strict';
  if (window.__laluneCaptchaBridgeMainInstalled) return;
  window.__laluneCaptchaBridgeMainInstalled = true;

  function publishToken(token) {
    if (typeof token !== 'string' || !token || token.length > 16384 ||
        /[\r\n]/.test(token)) return;
    // The isolated content script decides whether and where a result may be
    // returned. The page never supplies a redirect URL.
    window.postMessage({
      channel: 'lalune-captcha-bridge',
      type: 'captcha-success',
      token: token
    }, location.origin);
  }

  function inspect(data) {
    try {
      if (data && data.response && typeof data.response.success_token === 'string') {
        publishToken(data.response.success_token);
      }
    } catch (_) {}
  }

  const originalFetch = window.fetch;
  if (originalFetch) {
    window.fetch = function () {
      const args = arguments;
      return originalFetch.apply(this, args).then(function (response) {
        try {
          const request = args[0];
          const url = typeof request === 'string' ? request : (request && request.url) || '';
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
