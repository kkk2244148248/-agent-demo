// CDP screenshot helper — Node >=22 (global WebSocket)
const http = require('http');

const url = process.argv[2];
const out = process.argv[3];
const w = parseInt(process.argv[4] || '1440', 10);
const h = parseInt(process.argv[5] || '900', 10);
const waitMs = parseInt(process.argv[6] || '4000', 10);
const port = parseInt(process.argv[7] || '9333', 10);

function jsonGet(path) {
  return new Promise((resolve, reject) => {
    http.get({ host: '127.0.0.1', port, path }, (res) => {
      let d = '';
      res.on('data', (c) => (d += c));
      res.on('end', () => { try { resolve(JSON.parse(d)); } catch (e) { reject(e); } });
    }).on('error', reject);
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const chrome = spawnChrome([
    `--remote-debugging-port=${port}`,
    '--headless=new', '--disable-gpu', '--no-sandbox', '--no-first-run',
    `--window-size=${w},${h}`, '--user-data-dir=' + process.env.TEMP + '/cdp-chrome-' + Date.now(),
    'about:blank',
  ]);
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
    };
    function send(method, params = {}) {
      return new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
    }

    await send('Page.enable');
    await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
    await send('Page.navigate', { url });
    await sleep(waitMs);
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    require('fs').writeFileSync(out, Buffer.from(shot.result.data, 'base64'));
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

function spawnChrome(args) {
  const { spawn } = require('child_process');
  return spawn('C:/Program Files/Google/Chrome/Application/chrome.exe', args, { stdio: 'ignore' });
}

main();
