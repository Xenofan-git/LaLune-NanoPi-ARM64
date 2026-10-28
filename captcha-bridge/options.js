(function () {
  'use strict';
  const input = document.getElementById('origin');
  const status = document.getElementById('status');
  const storage = (globalThis.browser && globalThis.browser.storage &&
    globalThis.browser.storage.local) || (globalThis.chrome && globalThis.chrome.storage &&
    globalThis.chrome.storage.local);

  function report(message, error) {
    status.textContent = message;
    status.style.color = error ? '#b3261e' : '#137333';
  }

  function getValue() {
    if (globalThis.browser && globalThis.browser.storage && globalThis.browser.storage.local === storage) {
      return storage.get('trustedPanelOrigin');
    }
    return new Promise((resolve, reject) => {
      if (!storage) { reject(new Error('Хранилище расширения недоступно')); return; }
      try {
        storage.get('trustedPanelOrigin', value => {
          const lastError = globalThis.chrome && globalThis.chrome.runtime &&
            globalThis.chrome.runtime.lastError;
          if (lastError) reject(new Error(lastError.message));
          else resolve(value || {});
        });
      } catch (error) { reject(error); }
    });
  }

  function setValue(value) {
    if (globalThis.browser && globalThis.browser.storage && globalThis.browser.storage.local === storage) {
      return storage.set(value);
    }
    return new Promise((resolve, reject) => {
      try {
        storage.set(value, () => {
          const lastError = globalThis.chrome && globalThis.chrome.runtime &&
            globalThis.chrome.runtime.lastError;
          if (lastError) reject(new Error(lastError.message));
          else resolve();
        });
      } catch (error) { reject(error); }
    });
  }

  document.getElementById('save').addEventListener('click', async () => {
    const normalized = globalThis.LaluneCaptchaOriginPolicy.normalizeTrustedPanelOrigin(input.value);
    if (!normalized) {
      report('Адрес отклонён. Нужен точный HTTPS origin или HTTP-адрес локальной сети.', true);
      return;
    }
    try {
      await setValue({ trustedPanelOrigin: normalized });
      input.value = normalized;
      report('Доверенный адрес панели сохранён.');
    } catch (error) { report('Не удалось сохранить настройку: ' + error.message, true); }
  });

  document.getElementById('clear').addEventListener('click', async () => {
    try {
      await setValue({ trustedPanelOrigin: '' });
      input.value = '';
      report('Настройка удалена. Возврат CAPTCHA отключён.', false);
    } catch (error) { report('Не удалось удалить настройку: ' + error.message, true); }
  });

  getValue().then(value => {
    input.value = globalThis.LaluneCaptchaOriginPolicy.normalizeTrustedPanelOrigin(
      value.trustedPanelOrigin
    );
  }).catch(error => report('Не удалось прочитать настройки: ' + error.message, true));
})();
