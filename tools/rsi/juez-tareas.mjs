// Juez funcional del banco «tareas» del RSI (PLAN_REA.md, punto 12): carga el proyecto generado en Chrome y comprueba
// añadir, marcar, contar, borrar, recargar (localStorage) y que no haya errores de JavaScript. El RSI no puede
// modificar este archivo: es parte del evaluador. Uso: node juez-tareas.mjs <carpeta> [...más carpetas]
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'tests', 'e2e', 'package.json'));
const { chromium } = require('playwright-core');
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml' };

function serve(root) {
  return new Promise((resolve) => {
    const server = http.createServer(async (req, res) => {
      const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname).replace(/^\/+/, '') || 'index.html';
      const file = path.resolve(root, rel);
      if (!file.startsWith(path.resolve(root))) { res.writeHead(403); return res.end(); }
      try { const data = await fs.readFile(file); res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream' }); res.end(data); }
      catch { res.writeHead(404); res.end(); }
    });
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}

const browser = await chromium.launch({ headless: true, channel: process.env.EOLFI_E2E_CHANNEL || 'chrome' });
// Siempre las mismas 9 comprobaciones: si la página falla antes, las no ejecutadas cuentan como no superadas
// (16/11/2026: un proyecto roto puntuaba 1/4 = 0,25 en vez de 1/9 = 0,11).
const TOTAL = 9;
const results = {};
for (const dir of process.argv.slice(2)) {
  const name = path.basename(dir);
  const checks = [];
  const errors = [];
  const server = await serve(dir);
  const base = `http://127.0.0.1:${server.address().port}/`;
  const page = await (await browser.newContext()).newPage();
  page.on('pageerror', (e) => errors.push(String(e.message)));
  const check = async (label, fn) => { try { checks.push([label, Boolean(await fn())]); } catch (e) { checks.push([label, false, String(e.message).slice(0, 120)]); } };
  try {
    await page.goto(base, { waitUntil: 'load' });
    // Formulario de tareas: el que tiene un campo de texto y no es el de contacto (sin email ni textarea).
    const formIndex = await page.evaluate(() => [...document.forms].findIndex((f) => f.querySelector('input[type=text],input:not([type])') && !f.querySelector('input[type=email],textarea')));
    await check('hay un formulario de tareas', async () => formIndex >= 0);
    const form = page.locator('form').nth(formIndex);
    const input = form.locator('input[type=text],input:not([type])').first();
    const add = async (text) => { await input.fill(text); await input.press('Enter'); await page.waitForTimeout(200); };
    // La tarea: el elemento más profundo con ese texto, y su contenedor con botón (o li).
    const item = (text) => page.locator('li, [class*=task], [class*=tarea], [class*=todo], div').filter({ hasText: text }).filter({ has: page.locator('button') }).last();
    const present = (text) => page.evaluate((t) => [...document.querySelectorAll('body *')].some((el) => (el.children.length === 0 ? el.textContent.trim() : [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join('').trim()) === t), text);
    const resumen = () => page.locator('#resumen').innerText();
    await add('comprar pan'); await add('llamar a Ana');
    await check('añade dos tareas', async () => (await present('comprar pan')) && (await present('llamar a Ana')));
    await check('el resumen cuenta 2 pendientes', async () => /\b2\b/.test(await resumen()));
    const state = () => item('comprar pan').evaluate((el) => el.outerHTML.replace(/\s+/g, ' ') + getComputedStyle(el).textDecorationLine + [...el.querySelectorAll('*')].map((c) => getComputedStyle(c).textDecorationLine).join());
    const before = await state();
    await page.evaluate(() => { const el = [...document.querySelectorAll('body *')].filter((e) => (e.children.length === 0 ? e.textContent.trim() : [...e.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join('').trim()) === 'comprar pan').pop(); el.click(); });
    await page.waitForTimeout(200);
    await check('clic marca la tarea como hecha', async () => before !== await state());
    await check('el resumen pasa a 1 pendiente', async () => /\b1\b/.test(await resumen()));
    const del = item('llamar a Ana').locator('button').last();
    await check('cada tarea tiene un botón de borrar', async () => (await del.count()) >= 1);
    if (await del.count()) await del.click();
    await page.waitForTimeout(200);
    await check('borrar quita la tarea', async () => !(await present('llamar a Ana')) && (await present('comprar pan')));
    await page.reload({ waitUntil: 'load' });
    await check('localStorage conserva las tareas al recargar', async () => (await present('comprar pan')) && !(await present('llamar a Ana')));
    await check('sin errores de JavaScript', async () => errors.length === 0);
  } catch (e) {
    checks.push(['carga de la página', false, String(e.message).slice(0, 120)]);
  }
  server.close();
  const passed = checks.filter((c) => c[1]).length;
  const ejecutadas = checks.filter((c) => c[0] !== 'carga de la página').length;
  results[name] = { passed, total: TOTAL, ejecutadas, checks, errors: errors.slice(0, 3) };
}
await browser.close();
console.log(JSON.stringify(results, null, 1));
