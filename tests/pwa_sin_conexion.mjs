// Prueba real de la PWA del destino static: con red, el service worker toma el control; sin red, las páginas
// vuelven a cargar desde su caché. Uso: node pwa_sin_conexion.mjs CARPETA [SEGUNDA]  → JSON por stdout.
// SEGUNDA: la otra página que se visita sin red (por defecto /about.html; en una SPA, una ruta como /about, que el
// servidor responde con index.html igual que un hosting de SPA).
// playwright-core por EOLFI_PLAYWRIGHT y navegador por EOLFI_BROWSER_PATH (o el canal chrome).
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const raiz = path.resolve(process.argv[2]);
const segunda = process.argv[3] || '/about.html';
const MIME = { '.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'text/javascript',
  '.svg': 'image/svg+xml', '.webmanifest': 'application/manifest+json' };
const server = http.createServer(async (req, res) => {
  const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname).replace(/^\/+/, '') || 'index.html';
  const file = path.resolve(raiz, rel);
  if (!file.startsWith(raiz + path.sep)) { res.writeHead(403); return res.end(); }
  try { const b = await fs.readFile(file); res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream' }); res.end(b); }
  catch {
    if (!path.extname(rel)) {   // ruta de una SPA: la portada
      res.writeHead(200, { 'Content-Type': MIME['.html'] }); return res.end(await fs.readFile(path.join(raiz, 'index.html')));
    }
    res.writeHead(404); res.end();
  }
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;
const spec = process.env.EOLFI_PLAYWRIGHT;
const pw = await import(pathToFileURL(path.join(spec, 'index.mjs')).href);
const chromium = pw.chromium || pw.default.chromium;
const browser = await chromium.launch({ headless: true, ...(process.env.EOLFI_BROWSER_PATH
  ? { executablePath: process.env.EOLFI_BROWSER_PATH } : { channel: 'chrome' }) });
const out = { errores: [] };
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  page.on('pageerror', (e) => out.errores.push(String(e.message)));
  await page.goto(base + '/index.html');
  out.manifiesto = await page.evaluate(() => document.querySelector('link[rel="manifest"]')?.getAttribute('href'));
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload();
  out.controlada = await page.evaluate(() => Boolean(navigator.serviceWorker.controller));
  await context.setOffline(true);
  await page.reload();
  out.h1_sin_red = await page.textContent('h1');
  await page.goto(base + segunda);
  out.about_sin_red = await page.textContent('h1');
  const r = await page.evaluate(() => fetch('https://example.invalid/x').then(() => 'ok', () => 'falla'));
  out.terceros_sin_red = r;
} catch (e) { out.error = String(e.message || e).split('\n')[0]; }
finally { await browser.close(); server.close(); }
process.stdout.write(JSON.stringify(out));
