// CDP screenshot with auto-login — Node >=22
const http = require('http');
const fs = require('fs');

let targetPath = String(process.argv[2] || 'home').replace(/^\/+/, '');
if (['home', 'root', 'index', 'dashboard'].includes(targetPath)) targetPath = '';
targetPath = targetPath ? '/' + targetPath : '/';
const out = process.argv[3] || 'shot.png';
const w = parseInt(process.argv[4] || '1440', 10);
const h = parseInt(process.argv[5] || '900', 10);
const waitMs = parseInt(process.argv[6] || '4500', 10);
const port = parseInt(process.argv[7] || '9336', 10);
const BASE = 'http://127.0.0.1:5173';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function jsonGet(path) {
  return new Promise((resolve, reject) => {
    http.get({ host: '127.0.0.1', port, path }, (res) => {
      let d = '';
      res.on('data', (c) => (d += c));
      res.on('end', () => { try { resolve(JSON.parse(d)); } catch (e) { reject(e); } });
    }).on('error', reject);
  });
}

async function main() {
  const { spawn } = require('child_process');
  const chrome = spawn('C:/Program Files/Google/Chrome/Application/chrome.exe', [
    `--remote-debugging-port=${port}`,
    '--headless=new', '--disable-gpu', '--no-sandbox', '--no-first-run',
    `--window-size=${w},${h}`,
    '--user-data-dir=' + process.env.TEMP + '/cdp-chrome-' + Date.now(),
    'about:blank',
  ], { stdio: 'ignore' });

  try {
    let targets;
    for (let i = 0; i < 50; i++) {
      try { targets = await jsonGet('/json/list'); if (targets && targets.length) break; } catch {}
      await sleep(200);
    }
    const page = targets.find((t) => t.type === 'page');
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

    let id = 0;
    const pending = new Map();
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
      else if (m.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(m.params.type)) {
        console.log('[console]', m.params.type, m.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 300));
      }
      else if (m.method === 'Network.responseReceived') {
        const r = m.params.response;
        if (r.url.includes('/api/')) console.log('[api]', r.status, r.url.replace('http://127.0.0.1:5173', ''));
      }
      else if (m.method === 'Page.frameNavigated') {
        console.log('[nav]', m.params.frame.url);
      }
    };
    const send = (method, params = {}) =>
      new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });

    await send('Page.enable');
    await send('Runtime.enable');
    await send('Network.enable');
    await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });

    // 1) 登录拿 token
    await send('Page.navigate', { url: BASE + '/login' });
    await sleep(2500);
    const loginRes = await send('Runtime.evaluate', {
      awaitPromise: true,
      returnByValue: true,
      expression: `(async () => {
        const r = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'liht', password: '123456' }) });
        const d = await r.json();
        if (!d.token) return 'LOGIN_FAIL: ' + JSON.stringify(d).slice(0, 200);
        return JSON.stringify(d);
      })()`,
    });
    const raw = loginRes.result?.result?.value || '';
    console.log('login:', raw.slice(0, 60));
    if (raw.startsWith('LOGIN_FAIL')) { chrome.kill(); process.exit(1); }

    // 2) 新文档加载前注入会话（保证早于应用启动）
    const reg = await send('Page.addScriptToEvaluateOnNewDocument', {
      source: `try {
        const d = ${raw};
        localStorage.setItem('trade_desk_token', d.token);
        localStorage.setItem('trade_desk_user', JSON.stringify(d.user));
        console.warn('[seed] token set', (d.token||'').slice(0,6));
      } catch (e) { console.error('seed fail', e); }`,
    });

    console.log('seed registered:', JSON.stringify(reg.result || reg.error || reg).slice(0, 100));
    // 3) 进目标页
    const finalUrl = BASE + targetPath;
    console.log('goto:', JSON.stringify(finalUrl));
    const navRes = await send('Page.navigate', { url: finalUrl });
    console.log('navigate:', JSON.stringify(navRes.result || navRes.error || navRes).slice(0, 150));
    await sleep(waitMs);
    const loc = await send('Runtime.evaluate', {
      awaitPromise: true, returnByValue: true,
      expression: `(async () => {
        const t = localStorage.getItem('trade_desk_token');
        const r = await fetch('/api/auth/me', { headers: { Authorization: 'Bearer ' + t } });
        return location.href + ' | me=' + r.status + ' | token=' + (t||'').slice(0,8);
      })()`,
    });
    console.log('now at:', loc.result?.result?.value);
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(out, Buffer.from(shot.result.data, 'base64'));
    console.log('saved', out);
    ws.close();
    chrome.kill();
    process.exit(0);
  } catch (e) {
    console.error(e);
    chrome.kill();
    process.exit(1);
  }
}

main();
