// Pruebas de extremo a extremo del panel de Eolfi en un navegador real (Chrome/Edge ya instalado, sin
// descargar navegadores) y accesibilidad con axe-core (versión fijada en package.json).
//
//   cd tests/e2e && npm install && npm test
//   EOLFI_E2E_CHANNEL=msedge npm test        # otro navegador
//   EOLFI_E2E_BROWSER=/ruta/al/chrome npm test
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createRequire } from 'node:module';
import { chromium } from 'playwright-core';

const require = createRequire(import.meta.url);
const AXE = readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const ROOT = resolve(import.meta.dirname, '..', '..');
const PY = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const PORT = 8790 + Math.floor(Math.random() * 200);
const BASE = `http://127.0.0.1:${PORT}`;
let server, browser, page, tmp, errors = [];

async function waitHealth() {
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(`${BASE}/api/health`)).ok) return; } catch { /* aún arranca */ }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error('el servidor no arrancó');
}

before(async () => {
  tmp = mkdtempSync(join(tmpdir(), 'eolfi-e2e-'));
  // Binario de prueba (ELF mínimo generado por las pruebas de Python).
  // La ruta va como argumento (sys.argv), no dentro del código Python.
  execFileSync(PY, ['-c', 'import sys; from tests.elfgen import build_elf64; open(sys.argv[1], "wb").write(build_elf64())',
    join(tmp, 'muestra.elf')], { cwd: ROOT });
  server = spawn(PY, ['-m', 'eolfi', '--db', join(tmp, 'e.db'), 'serve', '--port', String(PORT), '--samples', join(tmp, 's')],
    { cwd: ROOT, stdio: 'ignore', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
  await waitHealth();
  browser = await chromium.launch({
    headless: true,
    ...(process.env.EOLFI_E2E_BROWSER ? { executablePath: process.env.EOLFI_E2E_BROWSER }
      : { channel: process.env.EOLFI_E2E_CHANNEL || 'chrome' }),
  });
  // bypassCSP solo en la prueba: la CSP del panel (correcta) impediría inyectar axe.
  page = await (await browser.newContext({ bypassCSP: true })).newPage();
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto(BASE + '/');
  await page.waitForSelector('#version:not(:empty)');
});

after(async () => {
  await browser?.close();
  server?.kill();
  try { rmSync(tmp, { recursive: true, force: true }); } catch { /* Windows puede tardar en soltar la base */ }
});

async function axe(label) {
  await page.addScriptTag({ content: AXE });
  const r = await page.evaluate(async () => (await window.axe.run(document, {
    resultTypes: ['violations'], runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'best-practice'] },
  })).violations.map((v) => ({ id: v.id, impact: v.impact, n: v.nodes.length, target: v.nodes[0]?.target?.join(' ') })));
  const serious = r.filter((v) => v.impact === 'serious' || v.impact === 'critical');
  assert.deepEqual(serious, [], `${label}: ${JSON.stringify(r, null, 1)}`);
  return r;
}

test('carga sin errores y sin problemas graves de accesibilidad (claro y oscuro)', async () => {
  assert.deepEqual(errors, []);
  await axe('tema claro');
  await page.evaluate(() => { document.documentElement.dataset.theme = 'dark'; });
  await axe('tema oscuro');
  await page.evaluate(() => { delete document.documentElement.dataset.theme; });
});

test('subir un binario: se analiza como trabajo y aparece como objetivo', async () => {
  await page.setInputFiles('#file', join(tmp, 'muestra.elf'));
  await page.click('#go');
  await page.waitForFunction(() => /Listo en/.test(document.querySelector('#status').textContent), null, { timeout: 60000 });
  await page.waitForSelector('#content:not([hidden])');
  assert.match(await page.textContent('#subject-title'), /muestra\.elf/);
  // Las evidencias llegan en otra petición tras mostrar el objetivo: se esperan (antes se contaban de inmediato).
  await page.waitForFunction(() => document.querySelectorAll('#evidence details').length > 3, null, { timeout: 15000 }).catch(() => {});
  const n = await page.locator('#evidence details').count();
  assert.ok(n > 3, `evidencias: ${n}`);
  // El cuerpo de una evidencia se pinta al abrirla.
  const first = page.locator('#evidence details').first();
  assert.equal(await first.locator('.body pre').count(), 0);
  await first.locator('summary').click();
  await first.locator('.body pre').first().waitFor();
  await axe('detalle de un objetivo');
});

test('vistas coherentes: análisis, proveedores y chats', async () => {
  const visible = () => page.evaluate(() => ['content', 'empty', 'chats', 'providers-view']
    .filter((id) => !document.getElementById(id).hidden));
  await page.click('#open-providers');
  assert.deepEqual(await visible(), ['providers-view']);
  assert.equal(await page.evaluate(() => document.activeElement.tagName), 'H2');
  await axe('proveedores');
  await page.click('#open-chats');
  assert.deepEqual(await visible(), ['chats']);
  await page.click('#open-analysis');
  assert.deepEqual(await visible(), ['content']);
});

test('formularios: avisos claros y selector de carpetas con teclado', async () => {
  // La zona de soltar (ya no es un <label>) sigue abriendo el selector de archivos, con ratón y con teclado.
  // Cada selector se resuelve (sin archivos) antes de abrir el siguiente: Chrome no abre dos a la vez.
  const [fc1] = await Promise.all([page.waitForEvent('filechooser'), page.click('#drop')]);
  await fc1.setFiles([]);
  // Con el teclado: Chrome no siempre abre un segundo diálogo seguido en modo headless, así que se comprueba
  // que Intro llama a input.click() (lo que abre el diálogo) con un espía.
  await page.evaluate(() => { const i = document.getElementById('file'); i.dataset.clicks = '0';
    i.click = () => { i.dataset.clicks = String(Number(i.dataset.clicks) + 1); }; });
  await page.focus('#drop');
  await page.keyboard.press('Enter');
  assert.equal(await page.getAttribute('#file', 'data-clicks'), '1');
  await page.fill('#path', '');
  await page.click('#path-go');
  assert.match(await page.textContent('#status'), /Escribe la ruta/);
  await page.click('.pick[data-pick="path"]');
  await page.waitForSelector('.picker .picker-item, .picker .small-btn');
  await page.waitForFunction(() => !!document.activeElement.closest('.picker'));
  assert.equal(await page.evaluate(() => !!document.activeElement.closest('.picker')), true, 'el foco entra en el selector');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.picker').count(), 0);
  assert.equal(await page.evaluate(() => document.activeElement.dataset.pick), 'path', 'el foco vuelve al botón');
  // Pestañas con flechas.
  await page.focus('#tab-binary');
  await page.keyboard.press('ArrowRight');
  assert.equal(await page.getAttribute('#tab-web', 'aria-selected'), 'true');
  assert.equal(await page.isVisible('#web-opts'), true);
  await page.keyboard.press('ArrowLeft');
  assert.deepEqual(errors, []);
});

test('Trabajos: historial, repetir, botón Atrás y atajos de teclado', async () => {
  await page.keyboard.press('Alt+4');
  await page.waitForSelector('#jobs-view:not([hidden])');
  await page.waitForSelector('#jobs tr td .badge');
  assert.match(await page.textContent('#jobs'), /muestra\.elf/);
  await axe('trabajos');
  // Repetir el análisis del binario: aparece otra fila y termina.
  const before = await page.locator('#jobs tr').count();
  await page.locator('#jobs button', { hasText: 'Repetir' }).first().click();
  await page.waitForFunction((n) => document.querySelectorAll('#jobs tr').length > n, before, { timeout: 20000 });
  await page.waitForFunction(() => !/en marcha|en cola/.test(document.querySelector('#jobs').textContent), null, { timeout: 60000 });
  // «Ver» abre el objetivo; Atrás vuelve a Trabajos.
  await page.locator('#jobs a', { hasText: 'Ver' }).first().click();
  await page.waitForSelector('#content:not([hidden])');
  await page.goBack();
  await page.waitForSelector('#jobs-view:not([hidden])');
  // Atajos: Alt+1 análisis, «/» enfoca el filtro, «?» abre la ayuda (y Esc la cierra).
  await page.keyboard.press('Alt+1');
  await page.waitForSelector('#content:not([hidden])');
  await page.keyboard.press('/');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'filter');
  await page.keyboard.press('Escape');
  await page.evaluate(() => document.activeElement.blur());
  await page.keyboard.press('Shift+?');
  await page.waitForSelector('#help[open]');
  await axe('ayuda de atajos');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#help[open]').count(), 0);
  assert.deepEqual(errors, []);
});

test('informe HTML del objetivo: se descarga, escapa el texto y es accesible', async () => {
  await page.keyboard.press('Alt+1');
  await page.waitForSelector('#content:not([hidden])');
  const href = await page.getAttribute('#report-html', 'href');
  const r = await page.request.get(BASE + href);
  assert.equal(r.status(), 200);
  assert.match(r.headers()['content-disposition'], /attachment; filename="eolfi-.*\.html"/);
  const htmlText = await r.text();
  assert.match(htmlText, /<h1>Informe de Eolfi/);
  assert.doesNotMatch(htmlText, /<script/i);
  const p2 = await page.context().newPage();
  await p2.setContent(htmlText);
  await p2.addScriptTag({ content: AXE });
  const v = await p2.evaluate(async () => (await window.axe.run()).violations.filter((x) => ['serious', 'critical'].includes(x.impact)).map((x) => x.id));
  assert.deepEqual(v, []);
  await p2.close();
});

test('formatos nuevos: un ejecutable firmado muestra firma, empresa e integridad', { skip: process.platform !== 'win32' }, async () => {
  const exe = 'C:/Program Files/dotnet/dotnet.exe';   // barras normales: Windows las acepta
  await page.keyboard.press('Alt+1');
  await page.click('#tab-binary');
  await page.fill('#path', exe);
  await page.click('#path-go');
  await page.waitForFunction(() => document.querySelector('#status').classList.contains('bad') || /Listo en/.test(document.querySelector('#status').textContent), null, { timeout: 120000 });
  assert.match(await page.textContent('#status'), /Listo en/);
  await page.waitForFunction(() => /Firma/.test(document.querySelector('#summary').textContent));
  const summary = await page.textContent('#summary');
  assert.match(summary, /Firma.*\.NET.*íntegro/s);
  assert.match(summary, /Empresa\s*Microsoft Corporation/);
  await axe('resumen de un binario firmado');
});

test('casos: crear, analizar con el caso activo, ver progreso y abrir el informe navegable', async () => {
  await page.goto(BASE + '/');
  await page.waitForSelector('#version:not(:empty)');
  await page.click('#panel-cases-tab');
  await page.fill('#case-name', 'Caso e2e');
  await page.click('#case-go');
  await page.waitForSelector('#case-view:not([hidden])');
  assert.match(await page.textContent('#case-active'), /Caso activo: Caso e2e/);
  const caseId = (await page.evaluate(() => location.hash)).slice('#caso/'.length);
  // Con el caso activo, el análisis normal del panel se registra en él.
  await page.click('#panel-analyze-tab');
  await page.fill('#path', join(tmp, 'muestra.elf'));
  await page.selectOption('#mode', 'local');
  await page.click('#path-go');
  await page.waitForFunction(() => /Listo en/.test(document.querySelector('#status').textContent), null, { timeout: 60000 });
  await page.goto(`${BASE}/#caso/${caseId}`);
  await page.waitForFunction(() => /triage/.test(document.querySelector('#case-body')?.textContent || ''), null, { timeout: 15000 });
  const body = await page.textContent('#case-body');
  assert.match(body, /completado/);
  assert.match(body, /Herramientas: .*eolfi\.triage/);
  assert.match(body, /content/);
  await axe('vista de un caso');
  const report = await page.getAttribute('#case-report', 'href');
  assert.equal(report, `/api/cases/${caseId}/report`);
  await page.goto(BASE + report);
  assert.match(await page.title(), /Caso de Eolfi: Caso e2e/);
  const broken = await page.evaluate(() => [...document.querySelectorAll('a[href^="#"]')]
    .filter((a) => !document.getElementById(a.getAttribute('href').slice(1))).length);
  assert.equal(broken, 0);
  await axe('informe del caso');
  await page.goto(BASE + '/');
  await page.evaluate(() => localStorage.removeItem('eolfi.case'));
});
