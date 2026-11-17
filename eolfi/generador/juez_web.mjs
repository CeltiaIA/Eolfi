// Juez funcional de `verify` (PLAN_DEFINITIVO.md, B1): abre el proyecto generado en Chrome y ejecuta los criterios
// declarados en eolfi.juez.json. No lo escribe el modelo ni puede tocarlo.
//
//   node juez_web.mjs peticion.json   → JSON por stdout
//
// playwright-core se resuelve con EOLFI_PLAYWRIGHT (ruta del paquete) o por la resolución normal de Node, con un
// Chrome ya instalado (EOLFI_BROWSER_CHANNEL o EOLFI_BROWSER_PATH). No descarga nada. La página solo puede hablar
// con el servidor local que sirve el proyecto: cualquier otra petición se corta y se anota.
import http from 'node:http';
import fs from 'node:fs/promises';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.ico': 'image/x-icon',
  '.webmanifest': 'application/manifest+json', '.woff2': 'font/woff2' };
const out = (o) => process.stdout.write(JSON.stringify(o));

async function loadPlaywright() {
  const spec = process.env.EOLFI_PLAYWRIGHT;
  if (!spec) return import('playwright-core');
  const file = /\.m?js$/.test(spec) ? spec : path.join(spec, 'index.mjs');
  return import(path.isAbsolute(file) ? pathToFileURL(file).href : file);
}

function serve(root) {
  const base = path.resolve(root);
  return new Promise((resolve) => {
    const server = http.createServer(async (req, res) => {
      let rel;
      try { rel = decodeURIComponent(new URL(req.url, 'http://x').pathname).replace(/^\/+/, '') || 'index.html'; }
      catch { res.writeHead(400); return res.end(); }
      const file = path.resolve(base, rel);
      if (file !== base && !file.startsWith(base + path.sep)) { res.writeHead(403); return res.end(); }
      try {
        const data = await fs.readFile(file);
        res.writeHead(200, { 'Content-Type': MIME[path.extname(file).toLowerCase()] || 'application/octet-stream' });
        res.end(data);
      } catch { res.writeHead(404); res.end(); }
    });
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}

// Texto propio de un elemento: el de sus nodos de texto directos (o todo, si es una hoja). Se define dentro de cada
// función evaluada en la página: la CSP de los sitios generados prohíbe eval.
const conTexto = (t) => {
  const propio = (el) => (el.children.length === 0 ? el.textContent
    : [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join('')).trim();
  return [...document.querySelectorAll('body *')]
    .filter((el) => !['SCRIPT', 'STYLE', 'TEMPLATE'].includes(el.tagName) && propio(el) === t);
};

async function main() {
  const req = JSON.parse(readFileSync(process.argv[2], 'utf8'));
  const total = req.pasos.filter((p) => 'comprobar' in p).length;
  let pw;
  try { pw = await loadPlaywright(); } catch (e) {
    return out({ status: 'unavailable', error: `playwright-core no disponible: ${String(e.message || e).slice(0, 200)}` });
  }
  const chromium = pw.chromium || pw.default?.chromium;
  let browser;
  try {
    browser = await chromium.launch({ headless: true, ...(process.env.EOLFI_BROWSER_PATH
      ? { executablePath: process.env.EOLFI_BROWSER_PATH } : { channel: process.env.EOLFI_BROWSER_CHANNEL || 'chrome' }) });
  } catch (e) {
    return out({ status: 'unavailable', error: `no se pudo abrir el navegador: ${String(e.message || e).slice(0, 200)}` });
  }
  const server = await serve(req.raiz);
  const origen = `http://127.0.0.1:${server.address().port}`;
  const checks = [];
  const errores = [];
  const bloqueadas = [];
  let fallo = null;
  try {
    const context = await browser.newContext({ serviceWorkers: 'block', acceptDownloads: false });
    context.setDefaultTimeout(req.espera_ms);
    await context.route('**/*', (route) => {
      const url = route.request().url();
      if (url.startsWith(origen + '/') || /^(data|blob|about):/.test(url)) return route.continue();
      bloqueadas.push(url.slice(0, 200));
      return route.abort();
    });
    const page = await context.newPage();
    page.on('pageerror', (e) => errores.push(String(e.message).slice(0, 300)));
    page.on('dialog', (d) => d.dismiss().catch(() => {}));
    const asentar = () => page.waitForTimeout(req.asentar_ms);
    const enPagina = (cuerpo) => new Function('t', `const conTexto = ${conTexto.toString()}; ${cuerpo}`);
    const propios = (texto) => page.evaluate(enPagina('return conTexto(t).length;'), texto);
    // Estado visible de lo que contiene un texto: marcado y tachado, para detectar «marcada como hecha».
    const estado = (texto) => page.evaluate(enPagina(`
      const el = conTexto(t).pop();
      if (!el) return null;
      const caja = el.closest('li, tr, article, [role=listitem]') || el.parentElement || el;
      return caja.outerHTML.replace(/\\s+/g, ' ') + [caja, ...caja.querySelectorAll('*')]
        .map((c) => getComputedStyle(c).textDecorationLine + (c.checked ? '1' : '')).join();`), texto);
    const clicTexto = (texto) => page.evaluate(enPagina(`
      const el = conTexto(t).pop();
      if (!el) throw new Error('no hay ningún elemento con el texto «' + t + '»');
      el.click();`), texto);

    // axe-core (C4): se evalúa desde Playwright, no como <script>, para no relajar la CSP de la app juzgada.
    const accesibilidad = async () => {
      if (!req.axe) throw new Error('axe-core no disponible (EOLFI_AXE o tests/e2e/node_modules): NO VERIFICADO');
      if (!(await page.evaluate(() => typeof window.axe === 'object'))) await page.evaluate(readFileSync(req.axe, 'utf8'));
      const r = await page.evaluate(async () => (await window.axe.run(document, {
        resultTypes: ['violations'], runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'best-practice'] },
      })).violations.map((v) => ({ id: v.id, impact: v.impact, n: v.nodes.length, target: (v.nodes[0]?.target || []).join(' ') })));
      return r.filter((v) => v.impact === 'serious' || v.impact === 'critical');
    };

    await page.goto(`${origen}/${req.pagina}`, { waitUntil: 'load' });
    for (const paso of req.pasos) {
      if ('comprobar' in paso) {
        const c = { nombre: paso.comprobar, ok: false };
        try {
          if ('presente' in paso) c.ok = (await propios(paso.presente)) > 0;
          else if ('ausente' in paso) c.ok = (await propios(paso.ausente)) === 0;
          else if ('patron' in paso) {
            const texto = await page.locator(paso.selector).first().innerText();
            c.ok = new RegExp(paso.patron).test(texto);
            if (!c.ok) c.detalle = `«${texto.slice(0, 120)}» no coincide con /${paso.patron}/`;
          } else if ('cuenta' in paso) {
            const n = await page.locator(paso.selector).count();
            c.ok = n === paso.cuenta;
            if (!c.ok) c.detalle = `hay ${n}, se esperaban ${paso.cuenta}`;
          } else if ('cambia_al_clic' in paso) {
            const antes = await estado(paso.cambia_al_clic);
            await clicTexto(paso.cambia_al_clic);
            await asentar();
            c.ok = antes !== null && antes !== await estado(paso.cambia_al_clic);
            if (!c.ok) c.detalle = 'el clic no cambió nada visible';
          } else if (paso.sin_problemas_accesibilidad) {
            const graves = await accesibilidad();
            c.ok = graves.length === 0;
            if (!c.ok) c.detalle = graves.slice(0, 5).map((v) => `${v.id} (${v.impact}, ${v.n}): ${v.target}`).join(' | ');
          } else if (paso.sin_errores_js) {
            c.ok = errores.length === 0;
            if (!c.ok) c.detalle = errores.slice(0, 3).join(' | ');
          }
        } catch (e) { c.detalle = String(e.message || e).split('\n')[0].slice(0, 200); }
        checks.push(c);
        continue;
      }
      try {
        if (paso.escribir) {
          const campo = page.locator(paso.escribir.selector).first();
          await campo.fill(paso.escribir.texto);
          if (paso.escribir.intro) await campo.press('Enter');
        } else if (paso.clic) {
          if (paso.clic.en) {   // el último «selector» dentro de lo que contiene ese texto
            await page.locator('li, tr, article, [role=listitem], div').filter({ hasText: paso.clic.en })
              .filter({ has: page.locator(paso.clic.selector) }).last().locator(paso.clic.selector).last().click();
          } else if (paso.clic.texto) await clicTexto(paso.clic.texto);
          else await page.locator(paso.clic.selector).first().click();
        } else if (paso.recargar) await page.reload({ waitUntil: 'load' });
        await asentar();
      } catch (e) {
        // Una acción que no se puede hacer no detiene al juez: las comprobaciones siguientes dirán qué falta.
        fallo = fallo || `${Object.keys(paso)[0]}: ${String(e.message || e).split('\n')[0].slice(0, 200)}`;
      }
    }
  } catch (e) {
    fallo = fallo || String(e.message || e).split('\n')[0].slice(0, 300);
  } finally {
    await browser.close().catch(() => {});
    server.close();
  }
  out({ status: 'ok', total, passed: checks.filter((c) => c.ok).length, ejecutadas: checks.length, checks,
    errores_js: errores.slice(0, 10), peticiones_bloqueadas: [...new Set(bloqueadas)].slice(0, 10),
    ...(fallo ? { accion_fallida: fallo } : {}) });
}

main().catch((e) => out({ status: 'error', error: String(e.message || e).slice(0, 300) }));
