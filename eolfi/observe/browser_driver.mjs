// Controlador de navegador para los pasos «browser» de una sesión de observación de Eolfi.
//
//   node browser_driver.mjs request.json      → JSON por stdout
//
// Usa playwright-core (EOLFI_PLAYWRIGHT = ruta del paquete, o resolución normal de Node) con un Chrome/Edge ya
// instalado (EOLFI_BROWSER_CHANNEL, por defecto «chrome», o EOLFI_BROWSER_PATH). No descarga navegadores.
// Cada acción abre una ventana de observación: las peticiones, mensajes de consola, errores y diálogos que
// empiezan mientras la acción se ejecuta y se asienta se atribuyen a esa acción (atribución temporal). Las
// peticiones a hosts no autorizados se bloquean y se registran. Los valores de cookies y almacenamiento se
// guardan como SHA-256, no en claro.
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { isAbsolute } from 'node:path';

const sha = (s) => createHash('sha256').update(s ?? '').digest('hex');
const out = (o) => { process.stdout.write(JSON.stringify(o)); };

async function loadPlaywright() {
  const spec = process.env.EOLFI_PLAYWRIGHT;
  if (spec) {
    const target = isAbsolute(spec) ? pathToFileURL(spec.endsWith('.js') || spec.endsWith('.mjs') ? spec
      : spec.replace(/[\\/]$/, '') + '/index.mjs').href : spec;
    return import(target);
  }
  return import('playwright-core');
}

function allowed(url, hosts) {
  try {
    const u = new URL(url);
    if (u.protocol === 'data:' || u.protocol === 'blob:' || u.protocol === 'about:') return true;
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return false;
    const h = u.hostname.toLowerCase();
    return hosts.includes(h) || hosts.includes(`[${h}]`) || hosts.includes(h.replace(/^\[|\]$/g, ''));
  } catch { return false; }
}

async function main() {
  const req = JSON.parse(readFileSync(process.argv[2], 'utf8'));
  let pw;
  try { pw = await loadPlaywright(); } catch (e) {
    return out({ status: 'unavailable', error: `playwright-core no disponible: ${String(e.message || e).slice(0, 300)}` });
  }
  const chromium = pw.chromium || pw.default?.chromium;
  let browser;
  try {
    browser = await chromium.launch({ headless: true, ...(process.env.EOLFI_BROWSER_PATH
      ? { executablePath: process.env.EOLFI_BROWSER_PATH } : { channel: process.env.EOLFI_BROWSER_CHANNEL || 'chrome' }) });
  } catch (e) {
    return out({ status: 'unavailable', error: `no se pudo abrir el navegador: ${String(e.message || e).slice(0, 300)}` });
  }
  const result = { status: 'ok', browser: { name: 'chromium', version: browser.version() }, actions: [] };
  try {
    const context = await browser.newContext({ viewport: req.viewport || { width: 1280, height: 800 },
      serviceWorkers: 'block', acceptDownloads: false });
    context.setDefaultTimeout(Math.min(req.timeout_ms, 30000));
    let bucket = null;
    const pending = [];
    const byReq = new Map();
    await context.route('**/*', (route) => {
      const url = route.request().url();
      if (allowed(url, req.allow_hosts)) return route.continue();
      bucket?.requests.push({ method: route.request().method(), url, resource_type: route.request().resourceType(),
        blocked: 'host no autorizado por el guion' });
      return route.abort('blockedbyclient');
    });
    const page = await context.newPage();
    page.on('request', (r) => {
      if (!bucket || !allowed(r.url(), req.allow_hosts)) return;
      const post = r.postDataBuffer();
      const e = { method: r.method(), url: r.url(), resource_type: r.resourceType(),
        ...(post ? { body: { size: post.length, sha256: sha(post) } } : {}) };
      bucket.requests.push(e);
      byReq.set(r, e);
    });
    page.on('response', (resp) => {
      const e = byReq.get(resp.request());
      if (!e) return;
      e.status = resp.status();
      if (['document', 'xhr', 'fetch'].includes(e.resource_type)) {
        pending.push(resp.body().then((b) => { e.response_body = { size: b.length, sha256: sha(b) }; }).catch(() => {}));
      }
    });
    page.on('requestfailed', (r) => { const e = byReq.get(r); if (e && !e.blocked) e.failure = r.failure()?.errorText || 'fallo'; });
    page.on('console', (m) => bucket?.console.push({ type: m.type(), text: m.text().slice(0, 1000) }));
    page.on('pageerror', (e) => bucket?.page_errors.push(String(e.message || e).slice(0, 1000)));
    page.on('dialog', async (d) => { bucket?.dialogs.push({ type: d.type(), message: d.message().slice(0, 1000) }); await d.dismiss(); });

    const actions = [{ id: '_inicio', do: 'goto', url: req.url }, ...req.actions];
    for (const a of actions) {
      bucket = { id: a.id, do: a.do, ...(a.selector ? { selector: a.selector } : {}), url_before: page.url(),
        requests: [], console: [], page_errors: [], dialogs: [] };
      const t0 = Date.now();
      try {
        if (a.do === 'goto') await page.goto(a.url, { waitUntil: 'load' });
        else if (a.do === 'reload') await page.reload({ waitUntil: 'load' });
        else if (a.do === 'click') await page.locator(a.selector).click();
        else if (a.do === 'fill') await page.locator(a.selector).fill(a.value);
        else if (a.do === 'press') await page.locator(a.selector).press(a.value);
        else if (a.do === 'check') await page.locator(a.selector).check();
        else if (a.do === 'select') await page.locator(a.selector).selectOption(a.value);
        else if (a.do === 'wait_for') await page.locator(a.selector).waitFor();
        bucket.status = 'ok';
      } catch (e) {
        bucket.status = 'error';
        bucket.error = String(e.message || e).split('\n')[0].slice(0, 500);
        result.status = 'partial';
      }
      await page.waitForLoadState('networkidle', { timeout: 3000 }).catch(() => {});
      await page.waitForTimeout(100);
      await Promise.all(pending.splice(0));
      bucket.url_after = page.url();
      try {
        const st = await page.evaluate(() => {
          const dump = (s) => { const o = {}; try { for (let i = 0; i < s.length; i++) { const k = s.key(i); o[k] = s.getItem(k); } } catch { /* sin acceso */ } return o; };
          return { title: document.title, text: (document.body?.innerText || '').replace(/[ \t]+/g, ' ').trim(),
            local: dump(localStorage), session: dump(sessionStorage) };
        });
        const hashMap = (o) => Object.fromEntries(Object.keys(o).sort().map((k) => [k, sha(o[k]).slice(0, 16)]));
        bucket.visible = { title: st.title, text_sha256: sha(st.text), text_preview: st.text.slice(0, 4000) };
        bucket.storage = { localStorage: hashMap(st.local), sessionStorage: hashMap(st.session),
          cookies: (await context.cookies()).map((c) => ({ domain: c.domain, path: c.path, name: c.name,
            value_sha256: sha(c.value).slice(0, 16) })).sort((x, y) => (x.domain + x.name).localeCompare(y.domain + y.name)) };
      } catch (e) { bucket.state_error = String(e.message || e).slice(0, 300); }
      try {
        const aria = await page.locator('body').ariaSnapshot();
        bucket.aria = { sha256: sha(aria), preview: aria.slice(0, 8000) };
      } catch (e) { bucket.aria = { error: String(e.message || e).slice(0, 300) }; }
      bucket.duration_ms = Date.now() - t0;
      result.actions.push(bucket);
    }
    bucket = null;
  } catch (e) {
    result.status = 'error';
    result.error = String(e.message || e).slice(0, 500);
  } finally {
    await browser.close().catch(() => {});
  }
  out(result);
}

main().catch((e) => out({ status: 'error', error: String(e?.message || e).slice(0, 500) }));
