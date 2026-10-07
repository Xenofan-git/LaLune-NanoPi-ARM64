(function () {
  'use strict';
  const base = '/api';
  const cache = {
    configs: '[]', settings: '{}', logs: '[]', status: '{"connected":false}', selected: '{}',
    coreUpdate: '{"update":false,"version":""}', laluneUpdate: '{"update":false,"version":""}',
    vk: '{"hasToken":false,"fetcherOk":false,"fetching":false,"message":"","progress":0}',
    deployLog: '', deploying: false, coreDownloading: false
  };
  const req = (path, options) => fetch(base + path, options || {}).then(r => r.text());
  const json = (path, options) => req(path, options).then(x => { try { return JSON.parse(x); } catch (_) { return x; } });
  async function refresh() {
    try { cache.configs = await req('/configs'); } catch (_) {}
    try { cache.settings = await req('/settings'); } catch (_) {}
    try { cache.logs = await req('/logs'); } catch (_) {}
    try { cache.status = await req('/vpn/status'); } catch (_) {}
    try { cache.selected = await req('/configs/selected'); } catch (_) {}
    try { cache.deployLog = await json('/deploy/log'); } catch (_) {}
    try { const x = await json('/deploy/status'); cache.deploying = !!x.deploying; } catch (_) {}
  }
  setInterval(refresh, 1200);
  setTimeout(refresh, 50);
  const post = (path, body) => { fetch(base + path, {method:'POST', headers:{'Content-Type':'application/json'}, body: body === undefined ? undefined : JSON.stringify(body)}).catch(()=>{}); return true; };
  window.api = {
    GetConfigsJson: () => cache.configs,
    SaveConfig: (link, protocol) => post('/configs', {link, protocol: protocol || 'CSQTT'}),
    DeleteConfig: id => { fetch(base + '/configs/' + encodeURIComponent(id), {method:'DELETE'}).catch(()=>{}); return true; },
    GetSettingsJson: () => cache.settings,
    SaveSettings: j => post('/settings', JSON.parse(j)),
    GetLogsJson: () => cache.logs,
    ClearLogs: () => post('/logs/clear'),
    GetStatusJson: () => cache.status,
    Connect: id => post('/vpn/connect', {id}),
    Disconnect: () => post('/vpn/disconnect'),
    CheckCoreUpdate: () => { fetch(base + "/updates/core/check").then(r=>r.text()).then(x=>cache.coreUpdate=x).catch(()=>{}); return cache.coreUpdate; },
    UpdateCore: () => post("/updates/core"),
    UpdateCoreAndWait: () => post("/updates/core/wait"),
    CheckLaLuneUpdate: () => { fetch(base + "/updates/lalune").then(r=>r.text()).then(x=>cache.laluneUpdate=x).catch(()=>{}); return cache.laluneUpdate; },
    OpenLaLuneReleases: () => { window.open('https://github.com/Endlad2/LaLune/releases/latest','_blank'); return true; },
    GetVKTokenState: () => { fetch(base + "/vk/state").then(r=>r.text()).then(x=>cache.vk=x).catch(()=>{}); return cache.vk; },
    VkLogin: () => post("/vk/login"),
    DeleteVKToken: () => post("/vk/delete"),
    ValidateVKToken: () => cache.vk,
    RunVkAutoApiCalls: () => { post("/vk/auto"); return "{\"pending\":true}"; },
    PollAutoApiResult: () => '{"pending":false,"error":"not supported"}',
    FinishVkCalls: callIdsJson => { try { post("/vk/finish", JSON.parse(callIdsJson)); return true; } catch (_) { return false; } },
    GetDeviceId: () => { try { return JSON.parse(cache.settings).deviceId || ''; } catch (_) { return ''; } },
    RegenerateDeviceId: () => '',
    SetSelectedConfigJson: j => post('/configs/selected', JSON.parse(j)),
    GetSelectedConfigJson: () => cache.selected,
    IsCoreDownloading: () => cache.coreDownloading,
    DeployProtocol: j => post('/deploy', JSON.parse(j)),
    DeployLog: () => cache.deployLog,
    IsDeploying: () => cache.deploying
  };
})();