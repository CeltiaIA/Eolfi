// Renderizador de páginas para «eolfi web --render» (C3).
//
//   node render_driver.mjs request.json      → JSON por stdout
//
// Usa playwright-core (EOLFI_PLAYWRIGHT o resolución normal de Node) con un Chrome/Edge ya instalado
// (EOLFI_BROWSER_CHANNEL, por defecto «chrome», o EOLFI_BROWSER_PATH). No descarga navegadores.
// Solo deja salir peticiones a los hosts de «allow_hosts»; las demás se bloquean y se cuentan. Sin service
// workers, sin descargas, sin permisos. Devuelve el HTML renderizado (recortado a max_html bytes), el título, los
// enlaces resueltos y las rutas que la app cambió con history.pushState.
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { isAbsolute } from 'node:path';

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
    return hosts.includes(u.hostname.toLowerCase().replace(/^\[|\]$/g, ''));
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
  const res = { status: 'ok', browser: browser.version(), pages: [] };
  try {
    const context = await browser.newContext({ serviceWorkers: 'block', acceptDownloads: false,
      javaScriptEnabled: true, viewport: { width: 1280, height: 800 } });
    context.setDefaultTimeout(req.timeout_ms);
    const blocked = new Set();
    let requests = 0;
    await context.route('**/*', (route) => {
      const url = route.request().url();
      if (!allowed(url, req.allow_hosts)) { blocked.add(new URL(url).origin); return route.abort('blockedbyclient'); }
      requests += 1;
      if (requests > req.max_requests) return route.abort('blockedbyclient');
      return route.continue();
    });
    await context.addInitScript(() => {
      const seen = [];
      for (const k of ['pushState', 'replaceState']) {
        const orig = history[k].bind(history);
        history[k] = (s, t, u) => { try { if (u) seen.push(new URL(u, location.href).href); } catch {} return orig(s, t, u); };
      }
      Object.defineProperty(window, '__eolfiRoutes', { get: () => seen.slice(0, 200) });
    });
    for (const url of req.urls) {
      const page = await context.newPage();
      const item = { url, status: 'ok' };
      const errors = [];
      page.on('pageerror', (e) => errors.push(String(e.message || e).slice(0, 300)));
      try {
        const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: req.timeout_ms });
        item.http = resp ? resp.status() : null;
        try { await page.waitForLoadState('networkidle', { timeout: req.settle_ms }); } catch { item.settled = false; }
        const data = await page.evaluate(() => ({
          title: document.title,
          html: document.documentElement.outerHTML,
          links: [...document.querySelectorAll('a[href]')].map((a) => a.href).slice(0, 2000),
          routes: window.__eolfiRoutes || [],
          text_chars: (document.body?.innerText || '').length,
          final_url: location.href,
        }));
        item.title = data.title;
        item.final_url = data.final_url;
        item.links = data.links;
        item.routes = data.routes;
        item.text_chars = data.text_chars;
        item.html_bytes = Buffer.byteLength(data.html, 'utf8');
        item.html = item.html_bytes > req.max_html ? data.html.slice(0, req.max_html) : data.html;
        item.truncated = item.html_bytes > req.max_html;
      } catch (e) {
        item.status = 'error';
        item.error = String(e.message || e).slice(0, 300);
      }
      item.page_errors = errors.slice(0, 20);
      await page.close();
      res.pages.push(item);
    }
    res.blocked_origins = [...blocked].slice(0, 50);
    res.requests = requests;
  } catch (e) {
    res.status = 'error';
    res.error = String(e.message || e).slice(0, 300);
  } finally {
    await browser.close();
  }
  out(res);
}

main().catch((e) => out({ status: 'error', error: String(e.message || e).slice(0, 300) }));
