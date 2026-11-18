// Renderizador de páginas para «eolfi web --render» (C3).
//
//   node render_driver.mjs request.json      → JSON por stdout
//
// Usa playwright-core (EOLFI_PLAYWRIGHT o resolución normal de Node) con un Chrome/Edge ya instalado
// (EOLFI_BROWSER_CHANNEL, por defecto «chrome», o EOLFI_BROWSER_PATH). No descarga navegadores.
// Solo deja salir peticiones a los hosts de «allow_hosts»; las demás se bloquean y se cuentan. Sin service
// workers, sin descargas, sin permisos. Devuelve el HTML renderizado (recortado a max_html bytes), el título, los
// enlaces resueltos y las rutas que la app cambió con history.pushState.
//
// Interacciones (C3, 18/11/2026; «interact» > 0): pulsa hasta N controles por página (botones que no envían un
// formulario, pestañas, desplegables, menús, <summary>) y anota qué cambia: rutas, URL, texto, enlaces nuevos y
// peticiones fetch/XHR. Nunca envía formularios ni escribe en campos; los controles con nombres de acciones con
// efecto (borrar, comprar, pagar, enviar, cerrar sesión…) se saltan; los diálogos se descartan, las ventanas
// nuevas se cierran y, mientras hay interacciones, solo salen peticiones GET/HEAD: las demás se bloquean y se
// anotan (método y ruta). Los formularios se inventarían (campos, tipos, validación) sin rellenarlos.
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
    const interact = Math.max(0, Math.min(Number(req.interact) || 0, 30));
    const noGet = [];
    let requests = 0;
    // Ventanas que abre la página (window.open, target=_blank): se cierran; las propias no tienen «opener».
    context.on('page', async (p) => { if (await p.opener().catch(() => null)) p.close().catch(() => {}); });
    await context.route('**/*', (route) => {
      const url = route.request().url();
      if (!allowed(url, req.allow_hosts)) { blocked.add(new URL(url).origin); return route.abort('blockedbyclient'); }
      const method = route.request().method();
      if (interact && !['GET', 'HEAD'].includes(method)) {
        if (noGet.length < 50) noGet.push(`${method} ${new URL(url).pathname}`);
        return route.abort('blockedbyclient');
      }
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
      const dialogs = [];
      const fetches = [];
      page.on('pageerror', (e) => errors.push(String(e.message || e).slice(0, 300)));
      page.on('dialog', (d) => { dialogs.push(`${d.type()}: ${d.message().slice(0, 200)}`); d.dismiss().catch(() => {}); });
      page.on('request', (r) => {
        if (['xhr', 'fetch'].includes(r.resourceType()) && fetches.length < 200) fetches.push(`${r.method()} ${r.url()}`);
      });
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
        item.forms = await page.evaluate(FORMS);
        if (interact) item.interactions = await interactuar(page, url, interact, req.settle_ms, fetches);
        item.requests = [...new Set(fetches)].slice(0, 100);
        item.dialogs = dialogs.slice(0, 20);
      } catch (e) {
        item.status = 'error';
        item.error = String(e.message || e).slice(0, 300);
      }
      item.page_errors = errors.slice(0, 20);
      await page.close();
      res.pages.push(item);
    }
    res.blocked_origins = [...blocked].slice(0, 50);
    res.blocked_non_get = [...new Set(noGet)];
    res.requests = requests;
  } catch (e) {
    res.status = 'error';
    res.error = String(e.message || e).slice(0, 300);
  } finally {
    await browser.close();
  }
  out(res);
}

// Inventario de formularios: lo que pide cada uno, sin rellenarlo.
const FORMS = () => [...document.forms].slice(0, 20).map((f) => ({
  action: f.getAttribute('action') || '', method: (f.getAttribute('method') || 'get').toLowerCase(),
  fields: [...f.elements].filter((e) => e.name || e.id).slice(0, 50).map((e) => {
    const label = (e.labels && e.labels[0]?.innerText) || e.getAttribute('aria-label') || e.placeholder || '';
    return { name: e.name || e.id, tag: e.tagName.toLowerCase(), type: e.type || '', required: !!e.required,
      label: label.trim().slice(0, 80), pattern: e.getAttribute('pattern') || undefined,
      minlength: e.minLength > 0 ? e.minLength : undefined, maxlength: e.maxLength > 0 ? e.maxLength : undefined,
      options: e.tagName === 'SELECT' ? [...e.options].slice(0, 20).map((o) => o.value) : undefined };
  }),
}));

// Controles que se pueden pulsar sin efectos: ni envíos de formulario ni nombres de acciones con efecto.
const EFECTO = 'borr|elimin|delet|remov|quitar|compr|buy|purchase|checkout|pagar|\\bpago\\b|\\bpay|enviar|send|submit|'
  + 'publica|publish|\\bpost\\b|cerrar sesi|log ?out|sign ?out|salir|suscri|subscri|darse de baja|unsubscr|reset|'
  + 'restablec|confirm|acept|accept|instal|descarg|download|vaciar|cancel';
const MARCAR = (efecto) => {
  const re = new RegExp(efecto, 'i');
  const sel = 'button, [role=button], [role=tab], [role=menuitem], [aria-expanded], summary, input[type=button]';
  const out = [];
  let i = 0;
  for (const e of document.querySelectorAll(sel)) {
    e.removeAttribute('data-eolfi-i');
    const r = e.getBoundingClientRect();
    if (!r.width || !r.height || e.disabled || e.closest('[inert], [aria-hidden=true]')) continue;
    if (e.type === 'submit' && e.form) continue;                       // enviaría un formulario
    const name = (e.getAttribute('aria-label') || e.innerText || e.value || e.title || '').trim().replace(/\s+/g, ' ');
    if (!name || re.test(name)) { if (name) out.push({ skip: true, name: name.slice(0, 60) }); continue; }
    e.setAttribute('data-eolfi-i', String(i));
    out.push({ i, name: name.slice(0, 60), role: e.getAttribute('role') || e.tagName.toLowerCase() });
    i += 1;
  }
  return out;
};
const ESTADO = () => ({ url: location.href, routes: (window.__eolfiRoutes || []).length,
  text: (document.body?.innerText || '').length, links: [...document.querySelectorAll('a[href]')].map((a) => a.href) });

async function interactuar(page, url, max, settleMs, fetches) {
  const res = { pulsados: [], saltados: [] };
  const lista = await page.evaluate(MARCAR, EFECTO);
  res.saltados = lista.filter((c) => c.skip).map((c) => c.name).slice(0, 30);
  const controles = lista.filter((c) => !c.skip).slice(0, max);
  for (const c of controles) {
    const antes = await page.evaluate(ESTADO);
    const nPeticiones = fetches.length;
    const paso = { control: c.name, rol: c.role };
    try {
      await page.locator(`[data-eolfi-i="${c.i}"]`).first().click({ timeout: 2000 });
      try { await page.waitForLoadState('networkidle', { timeout: Math.min(settleMs, 2000) }); } catch { /* sigue */ }
      const despues = await page.evaluate(ESTADO);
      const vistos = new Set(antes.links);
      if (despues.url !== antes.url) paso.url = despues.url;
      paso.texto = despues.text - antes.text;
      paso.enlaces_nuevos = [...new Set(despues.links.filter((l) => !vistos.has(l)))].slice(0, 20);
      paso.rutas_nuevas = (await page.evaluate(() => window.__eolfiRoutes || [])).slice(antes.routes, antes.routes + 20);
      paso.peticiones = fetches.slice(nPeticiones, nPeticiones + 20);
      if (despues.url.split('#')[0] !== url.split('#')[0]) {
        // Cambió de página: se vuelve a la original para seguir con los demás controles.
        await page.goto(url, { waitUntil: 'domcontentloaded' });
        try { await page.waitForLoadState('networkidle', { timeout: settleMs }); } catch { /* sigue */ }
      }
      await page.evaluate(MARCAR, EFECTO);   // el DOM puede haberse rehecho: se vuelven a marcar
    } catch (e) {
      paso.error = String(e.message || e).split('\n')[0].slice(0, 200);
    }
    res.pulsados.push(paso);
  }
  return res;
}

main().catch((e) => out({ status: 'error', error: String(e.message || e).slice(0, 300) }));
