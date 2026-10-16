// 对话助手截图：先发一条真实消息，等回答渲染后再截图
const http = require('http');
const fs = require('fs');
const { spawn } = require('child_process');

const PORT = 9339;
const BASE = 'http://127.0.0.1:5173';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function jsonGet(path) {
  return new Promise((resolve, reject) => {
    http.get({ host: '127.0.0.1', port: PORT, path }, (res) => {
      let d = ''; res.on('data', (c) => (d += c));
      res.on('end', () => { try { resolve(JSON.parse(d)); } catch (e) { reject(e); } });
    }).on('error', reject);
  });
}

(async () => {
  const chrome = spawn('C:/Program Files/Google/Chrome/Application/chrome.exe', [
    `--remote-debugging-port=${PORT}`, '--headless=new', '--disable-gpu', '--no-sandbox', '--no-first-run',
    '--window-size=1600,1100',
    '--user-data-dir=' + process.env.TEMP + '/cdp-asst-' + Date.now(), 'about:blank',
  ], { stdio: 'ignore' });

  let targets;
  for (let i = 0; i < 60; i++) { try { targets = await jsonGet('/json/list'); if (targets && targets.length) break; } catch {} await sleep(200); }
  const page = targets.find((t) => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  let id = 0; const pending = new Map();
  ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
  const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1100, deviceScaleFactor: 1, mobile: false });

  // 登录
  await send('Page.navigate', { url: BASE + '/login' });
  await sleep(2500);
  const loginRes = await send('Runtime.evaluate', {
    awaitPromise: true, returnByValue: true,
    expression: `(async () => {
      const r = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'liht', password: '123456' }) });
      return JSON.stringify(await r.json());
    })()`,
  });
  const raw = loginRes.result?.result?.value || '';
  if (!raw.includes('token')) { console.error('LOGIN FAIL', raw.slice(0, 200)); chrome.kill(); process.exit(1); }

  await send('Page.addScriptToEvaluateOnNewDocument', {
    source: `try {
      const d = ${raw};
      localStorage.setItem('trade_desk_token', d.token);
      localStorage.setItem('trade_desk_user', JSON.stringify(d.user));
    } catch (e) {}`,
  });

  await send('Page.navigate', { url: BASE + '/assistant' });
  await sleep(5000);

  // 在输入框打字并发送（走真实 UI，确保渲染路径一致）
  const typed = await send('Runtime.evaluate', {
    awaitPromise: true, returnByValue: true,
    expression: `(async () => {
      const ta = document.querySelector('.composer textarea');
      if (!ta) return 'NO_TEXTAREA';
      const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(ta, '只要找能做 500ml 保温杯激光 LOGO 的厂');
      ta.dispatchEvent(new Event('input', { bubbles: true }));
      await new Promise(r => setTimeout(r, 400));
      const btn = document.querySelector('.composer button[type=submit]');
      if (!btn) return 'NO_BUTTON';
      btn.click();
      return 'SENT';
    })()`,
  });
  console.log('send:', typed.result?.result?.value);

  // 等回答渲染（含工具执行，最长 90s）
  let ready = false;
  for (let i = 0; i < 45; i++) {
    await sleep(2000);
    const st = await send('Runtime.evaluate', {
      awaitPromise: true, returnByValue: true,
      expression: `(() => {
        const box = document.querySelector('.process-box');
        const bubble = document.querySelectorAll('.msg.assistant .msg-text');
        return JSON.stringify({ hasProcess: !!box, bubbles: bubble.length, loading: !!document.querySelector('.msg.assistant .composer') || !!document.querySelector('.msg-bubble') });
      })()`,
    });
    const s = JSON.parse(st.result?.result?.value || '{}');
    if (s.hasProcess) { ready = true; console.log('process panel rendered after', (i + 1) * 2, 's'); break; }
  }
  if (!ready) console.log('WARN: process panel not detected, screenshotting anyway');

  await sleep(1500);
  await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1100, deviceScaleFactor: 1, mobile: false });
  const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  fs.writeFileSync(process.argv[2] || 'shot.png', Buffer.from(shot.result.data, 'base64'));
  console.log('saved', process.argv[2]);
  ws.close(); chrome.kill(); process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
