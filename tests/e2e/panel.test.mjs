// Pruebas de extremo a extremo del panel de Eolfi en un navegador real (Chrome/Edge ya instalado, sin
// descargar navegadores) y accesibilidad con axe-core (versión fijada en package.json).
//
//   cd tests/e2e && npm install && npm test
//   EOLFI_E2E_CHANNEL=msedge npm test        # otro navegador
//   EOLFI_E2E_BROWSER=/ruta/al/chrome npm test
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
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
  // Directorio personal propio: sin él, el servidor leía el ~/.eolfi real (puente de chats web, Eolas V2,
  // puente de VS Code) y la prueba fallaba con 502 según lo que estuviera haciendo el equipo. Así ve lo mismo que la CI.
  const home = join(tmp, 'home');
  mkdirSync(home);
  const isolated = { HOME: home, USERPROFILE: home, EOLFI_HOME: join(home, '.eolfi'),
    EOLFI_ACCIONES_FILE: join(home, '.eolfi', 'acciones.jsonl'), EOLFI_BRIDGE_FILE: join(home, '.eolfi', 'bridge.json'),
    EOLFI_VSCODE_BRIDGE_FILE: join(home, '.eolfi', 'vscode-bridge.json') };
  server = spawn(PY, ['-m', 'eolfi', '--db', join(tmp, 'e.db'), 'serve', '--port', String(PORT), '--samples', join(tmp, 's')],
    { cwd: ROOT, stdio: 'ignore', env: { ...process.env, ...isolated, PYTHONIOENCODING: 'utf-8' } });
  await waitHealth();
  browser = await chromium.launch({
    headless: true,
    // Micrófono simulado (un tono) y permiso concedido: para la prueba de dictado, sin audio real.
    args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'],
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

// Desde el 13/11/2026 el chat es la pantalla de inicio y los formularios (crear proyecto, analizar, objetivos y
// casos) están en el panel «Herramientas» que se abre desde él: se usa como lo haría una persona.
async function openTools(section) {
  if (!(await page.isVisible('#tools-drawer'))) {
    await page.click('#open-chat');
    // El botón recibe su listener en eolas-chat.js, que se carga después: un clic anterior se pierde (CI, 17/11).
    await page.waitForSelector('#eolas-chat-form[data-ready]', { state: 'attached' });
    await page.click('#eolas-chat-tools');
    await page.waitForSelector('#tools-drawer:not([hidden])');
  }
  if (section) await page.click(`.tools-switch [data-panel-action="${section}"]`);
}

const ADJUNTOS = [
  { name: 'modelo.gguf', mimeType: 'application/octet-stream', buffer: Buffer.from('GGUF-test') },
  { name: 'pesos.safetensors', mimeType: 'application/octet-stream', buffer: Buffer.from('safetensors-test') },
  { name: 'datos.xyz', mimeType: '', buffer: Buffer.from('unknown-format-test') },
];

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

test('la actividad del agente de VS Code aparece en la franja del panel', async () => {
  await page.route('**/api/vscode/activity*', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ activity: [{ run_id: 'c'.repeat(32), status: 'running', label: '@eolfi /auditar',
      log: [{ t: 1, msg: 'Paso 2 de 10: eolfi_read_file' }] }] }),
  }));
  await page.reload();
  await page.waitForFunction(() => !document.querySelector('#vscode-activity').hidden);
  assert.match(await page.textContent('#vscode-activity'), /@eolfi \/auditar/);
  assert.match(await page.textContent('#vscode-activity'), /eolfi_read_file/);
  await page.unroute('**/api/vscode/activity*');
  await page.reload();
});

test('automejora: tarjeta por propuesta, aprobar solo si está evaluada y la decisión llega al servidor', async () => {
  const prop = (id, estado, extra = {}) => ({ id, regla: 'salida_cortada_v2', superficie: 'eolas_v2.max_tokens', actual: 8192,
    propuesto: 16384, motivo: 'Las respuestas se cortan por longitud.', estado, fecha: '2026-11-16T10:00:00Z', ...extra });
  const posted = [];
  await page.route('**/api/rsi', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
    activo: true, registro: { ok: true, eventos: 5 }, casos_regresion: 1, observaciones: 3, umbrales: {},
    propuestas: [prop('aaaaaaaaaaaa', 'evaluada', { evaluacion: { base: [0.5, 0.5, 0.5], candidata: [1, 1, 1], media_base: 0.5, media_candidata: 1 } }),
      prop('bbbbbbbbbbbb', 'pendiente')] }) }));
  await page.route('**/api/rsi/propuestas/**', (route) => { posted.push(new URL(route.request().url()).pathname);
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }); });
  await page.reload();
  await page.click('summary:has-text("Automejora")');
  const box = page.locator('#eolas-chat-rsi');
  await box.getByText('eolas_v2.max_tokens: 8192 → 16384').first().waitFor();
  assert.match(await box.textContent(), /registro íntegro/);
  assert.match(await box.textContent(), /eolfi rsi evaluar bbbbbbbbbbbb/);       // la pendiente indica cómo evaluarla
  assert.equal(await box.getByRole('button', { name: 'Aprobar y aplicar' }).count(), 1);   // solo la evaluada
  await box.getByRole('button', { name: 'Aprobar y aplicar' }).click();
  await page.waitForFunction(() => true);
  await new Promise((r) => setTimeout(r, 300));
  assert.deepEqual(posted, ['/api/rsi/propuestas/aaaaaaaaaaaa/aprobar']);
  await axe('automejora');
  await page.unroute('**/api/rsi');
  await page.unroute('**/api/rsi/propuestas/**');
  await page.reload();
  assert.deepEqual(errors, []);
});

test('adjuntar GGUF, safetensors y otros formatos desde el chat', async () => {
  await page.goto(BASE + '/#chat');
  await page.waitForSelector('#version:not(:empty)');
  // El módulo del chat se importa aparte: #version puede estar listo antes que él (fallaba a veces en la CI).
  await page.waitForSelector('#eolas-chat-form[data-ready]', { state: 'attached' });
  assert.equal(await page.getAttribute('#eolas-chat-files', 'accept'), null);
  // Con texto pendiente, adjuntar no envía una tarea al motor del equipo.
  await page.fill('#eolas-chat-input', 'Revisar adjuntos sin enviarlos');
  await page.setInputFiles('#eolas-chat-files', ADJUNTOS);
  await page.waitForFunction(() => document.querySelectorAll('#eolas-chat-attachments li').length === 3);
  const names = await page.textContent('#eolas-chat-attachments');
  for (const name of ['modelo.gguf', 'pesos.safetensors', 'datos.xyz']) assert.ok(names.includes(name));
  await axe('adjuntos de cualquier formato en el chat');
  for (let i = 0; i < 3; i++) await page.locator('#eolas-chat-attachments button').first().click();
  await page.fill('#eolas-chat-input', '');
});

// 18/11/2026: con 6 adjuntos el servidor rechazaba el mensaje entero al enviarlo («attachments: hasta 5 archivos»).
// El límite lo da el servidor por la conexión: usuario 5, premium 10, titular (este equipo) sin límite fijo.
const SEIS = Array.from({ length: 6 }, (_, i) => ({ name: `f${i + 1}.png`, mimeType: 'image/png', buffer: Buffer.from(`png-${i}`) }));

async function quitarAdjuntos() {
  while (await page.locator('#eolas-chat-attachments button').count()) await page.locator('#eolas-chat-attachments button').first().click();
}

test('adjuntos por mensaje: un usuario sube 5 y se le avisa del resto; el titular, todos', async () => {
  await page.route('**/api/chat/estado', async (route) => {
    const res = await route.fetch();
    await route.fulfill({ response: res, json: { ...(await res.json()), max_adjuntos: 5 } });
  });
  try {
    await page.goto(BASE + '/#chat');
    await page.reload();
    await page.waitForSelector('#eolas-chat-form[data-ready]', { state: 'attached' });
    await page.waitForFunction(() => !/^Comprobando/.test(document.querySelector('#eolas-chat-engine')?.textContent || 'Comprobando'));
    await page.fill('#eolas-chat-input', 'Revisar adjuntos sin enviarlos');
    await page.setInputFiles('#eolas-chat-files', SEIS);
    await page.waitForFunction(() => document.querySelectorAll('#eolas-chat-attachments li').length === 5);
    const aviso = page.locator('#eolas-chat-log .msg', { hasText: 'No se adjuntaron: f6.png' });
    await aviso.waitFor();
    assert.match(await aviso.textContent(), /Solo se pueden adjuntar 5 archivos por mensaje/);
    assert.equal(await page.locator('#eolas-chat-log .msg.user').count(), 0);   // nada se envió
    await axe('aviso de límite de adjuntos');
    await quitarAdjuntos();
  } finally {
    await page.unroute('**/api/chat/estado');
  }
  // Sin el límite simulado, el servidor ve la conexión desde este equipo (titular): entran los 6.
  await page.reload();
  await page.waitForSelector('#eolas-chat-form[data-ready]', { state: 'attached' });
  // El límite se fija al recibir /api/chat/estado, justo antes de pintar el estado del motor.
  await page.waitForFunction(() => !/^Comprobando/.test(document.querySelector('#eolas-chat-engine')?.textContent || 'Comprobando'));
  assert.equal((await (await page.request.get(BASE + '/api/chat/estado')).json()).max_adjuntos, null);
  await page.fill('#eolas-chat-input', 'Revisar adjuntos sin enviarlos');
  await page.setInputFiles('#eolas-chat-files', SEIS);
  await page.waitForFunction(() => document.querySelectorAll('#eolas-chat-attachments li').length === 6);
  await quitarAdjuntos();
  await page.fill('#eolas-chat-input', '');
  await page.click('#eolas-chat-clear');
});

// 18/11/2026: en el segundo mensaje el modelo solo tenía el nombre del adjunto («que-tal-socio.sh») y las herramientas
// fallaban. El chat reenvía por su huella los adjuntos de mensajes anteriores para que el servidor dé sus rutas.
test('el chat reenvía los adjuntos de mensajes anteriores', async () => {
  const enviados = [];
  await page.route('**/api/jobs**', async (route) => {
    const req = route.request();
    if (req.method() === 'POST') {
      enviados.push(JSON.parse(req.postData()));
      return route.fulfill({ status: 202, json: { job_id: `simulado${enviados.length}` } });
    }
    if (/[?&]id=simulado/.test(req.url())) {
      return route.fulfill({ json: { status: 'done', log: [], next: 0, elapsed: 0,
        result: { text: 'Hecho.', model: 'simulado', tools: [] } } });
    }
    return route.continue();
  });
  try {
    await page.goto(BASE + '/#chat');
    await page.reload();
    await page.waitForSelector('#eolas-chat-form[data-ready]', { state: 'attached' });
    await page.click('#eolas-chat-clear');
    await page.fill('#eolas-chat-input', 'Mira este guion');
    await page.setInputFiles('#eolas-chat-files', [{ name: 'que-tal-socio.sh', mimeType: 'text/x-sh', buffer: Buffer.from('echo hola') }]);
    await page.waitForFunction(() => document.querySelectorAll('#eolas-chat-attachments li').length === 1);
    await page.click('#eolas-chat-send');
    await page.locator('#eolas-chat-log .msg', { hasText: 'Hecho.' }).first().waitFor();
    await page.fill('#eolas-chat-input', 'adelante, analízalo');
    await page.click('#eolas-chat-send');
    await expectEventually(() => enviados.length === 2);
    // Hasta que llega la segunda respuesta el chat sigue consultando /api/jobs: sin la simulación daría 404.
    await page.locator('#eolas-chat-log .msg', { hasText: 'Hecho.' }).nth(1).waitFor();
    const [primero, segundo] = enviados.map((e) => e.body);
    assert.equal(primero.attachments[0].name, 'que-tal-socio.sh');
    assert.equal(primero.adjuntos_previos, undefined);
    assert.deepEqual(segundo.attachments, []);
    assert.deepEqual(segundo.adjuntos_previos, [{ upload: primero.attachments[0].upload, name: 'que-tal-socio.sh' }]);
  } finally {
    await page.unroute('**/api/jobs**');
  }
  await page.click('#eolas-chat-clear');
});

test('adjuntar antes de que cargue el módulo del chat no pierde los archivos', async () => {
  // Reproduce el runner lento: el módulo llega 1,5 s tarde y los archivos se eligen antes de que haya listener.
  await page.route('**/eolas-chat.js', async (route) => { await new Promise((r) => setTimeout(r, 1500)); await route.continue(); });
  try {
    await page.reload();
    await page.waitForSelector('#version:not(:empty)');
    assert.equal(await page.locator('#eolas-chat-form[data-ready]').count(), 0, 'el módulo debería llegar tarde');
    await page.fill('#eolas-chat-input', 'Revisar adjuntos sin enviarlos');
    await page.setInputFiles('#eolas-chat-files', ADJUNTOS);
    await page.waitForFunction(() => document.querySelectorAll('#eolas-chat-attachments li').length === 3);
    for (let i = 0; i < 3; i++) await page.locator('#eolas-chat-attachments button').first().click();
    assert.equal(await page.locator('#eolas-chat-log .msg.user').count(), 0);   // con texto pendiente no se envía
    await page.fill('#eolas-chat-input', '');
  } finally {
    await page.unroute('**/eolas-chat.js');
  }
  await page.reload();
  await page.waitForSelector('#eolas-chat-form[data-ready]', { state: 'attached' });
});

test('subir un binario: se analiza como trabajo y aparece como objetivo', async () => {
  await openTools('analyze');
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
  await openTools('analyze');
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
  await openTools('analyze');
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
  await openTools('cases');
  await page.fill('#case-name', 'Caso e2e');
  await page.click('#case-go');
  await page.waitForSelector('#case-view:not([hidden])');
  assert.match(await page.textContent('#case-active'), /Caso activo: Caso e2e/);
  const caseId = (await page.evaluate(() => location.hash)).slice('#caso/'.length);
  // Con el caso activo, el análisis normal del panel se registra en él.
  await openTools('analyze');
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

test('casos: las sesiones de observación se ven en el caso (alcance, factores no fijados, repetición)', async () => {
  const post = async (path, body) => {
    const r = await fetch(BASE + path, { method: 'POST', headers: { 'content-type': 'application/json', 'X-Eolfi': '1' }, body: JSON.stringify(body) });
    return [r.status, await r.json()];
  };
  const [, kase] = await post('/api/cases', { name: 'Observación e2e' });
  const script = { eolfi_observation_script: 1, name: 'eco', authorization: 'muestra sintética propia de la prueba',
    steps: [{ id: 'eco', action: 'run', argv: ['{python}', '-c', 'print("hola")'] }] };
  assert.equal((await post('/api/observe/run', { script, case_id: kase.case_id }))[0], 403);   // sin authorized=true
  const [st, run] = await post('/api/observe/run', { script, case_id: kase.case_id, authorized: true });
  assert.equal(st, 200, JSON.stringify(run));
  const [st2] = await post('/api/observe/replay', { evidence_id: run.evidence_id, case_id: kase.case_id, authorized: true });
  assert.equal(st2, 200);
  await page.goto(`${BASE}/#caso/${kase.case_id}`);
  await page.waitForFunction(() => /Repetición:/.test(document.querySelector('#case-body')?.textContent || ''), null, { timeout: 15000 });
  const body = await page.textContent('#case-body');
  assert.match(body, /Observación: 1 pasos/);
  assert.match(body, /Cobertura limitada: .*system_calls \(not_available\)/);
  assert.match(body, /Factores no fijados: reloj/);
  assert.match(body, /Repetición: reproducible/);
  assert.match(body, /Paso eco: el proceso terminó con código 0/);
  await axe('caso con observaciones');
  await page.goto(BASE + '/');
  await page.evaluate(() => localStorage.removeItem('eolfi.case'));
});

test('crear proyecto: formulario único, plan razonado, aprobación y modo automático con resultado verificable', async () => {
  const { mkdirSync, writeFileSync } = await import('node:fs');
  const runId = Date.now().toString(36);
  const site = join(tmp, 'sitio-e2e');
  mkdirSync(site, { recursive: true });
  writeFileSync(join(site, 'index.html'), '<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Demo</title></head><body><h1>Hola</h1><p>Sitio sintético.</p></body></html>');
  await page.goto(BASE + '/');
  await page.waitForSelector('#version:not(:empty)');
  await openTools('create');
  await page.fill('#proj-name', `Web e2e ${runId}`);
  await page.fill('#proj-desc', 'Una web estática. Que tenga modo oscuro.');
  await page.selectOption('#proj-kind', 'web');
  await page.fill('#proj-ref', site);
  await page.click('#proj-add');
  await page.selectOption('#proj-kind', 'file');
  await page.setInputFiles('#proj-file', join(tmp, 'muestra.elf'));
  await page.click('#proj-add');
  await page.waitForFunction(() => document.querySelectorAll('#proj-list li').length === 2);
  await page.click('#proj-go');
  await page.waitForSelector('#proj-view:not([hidden]) .proj-plan');
  const plan = await page.textContent('#proj-view');
  assert.match(plan, /Pendiente de tu aprobación/);
  assert.match(plan, /nunca se copia código/);
  assert.match(plan, /estática → tecnología destino: static/);
  assert.match(plan, /No se aplican automáticamente: .*modo oscuro/);
  assert.equal(await page.locator('.proj-step').count(), 4);
  // Rutas largas sin cortes no deben ensanchar el plan (desbordaba el panel en ventanas estrechas).
  await page.setViewportSize({ width: 900, height: 800 });
  assert.ok(await page.evaluate(() => { document.querySelector('.proj-step strong').textContent += 'C:/' + 'x'.repeat(300); const e = document.querySelector('.proj-plan'); return e.scrollWidth <= e.clientWidth + 1; }), 'el plan desborda horizontalmente');
  await page.setViewportSize({ width: 1280, height: 800 });
  await axe('plan del proyecto');
  await page.click('#proj-approve');
  // Desde 00fc409 el plan muestra también la «Evaluación inicial» con la misma clase: se espera el veredicto FINAL
  // de la verificación (Verificado / NO VERIFICADO), no el primer .proj-verdict.
  const finalVerdict = () => [...document.querySelectorAll('.proj-verdict')].find((e) => /^Verificado|NO VERIFICADO/.test(e.textContent))?.textContent;
  await page.waitForFunction(finalVerdict, null, { timeout: 240000 });
  const verdict = await page.evaluate(finalVerdict);
  const status = await page.textContent('#proj-view .badge');
  if (/^Verificado/.test(verdict)) assert.match(status, /Terminado y verificado/);
  else { assert.match(verdict, /NO VERIFICADO/); assert.match(status, /SIN verificación/); }
  assert.equal(await page.locator('.proj-step .badge.bad').count() <= 1, true);
  const report = await page.getAttribute('#proj-report', 'href');
  assert.match(report, /^\/api\/cases\/[0-9a-f-]{36}\/report$/);
  assert.match(await page.textContent('#proj-view details'), /Aprobación · v1/);
  await axe('proyecto terminado');
});

test('crear proyecto: modo guiado se detiene, la instrucción que cambia el plan exige aprobación', async () => {
  const runId = Date.now().toString(36);
  await page.goto(BASE + '/');
  await page.waitForSelector('#version:not(:empty)');
  await openTools('create');
  await page.fill('#proj-name', `Guiado e2e ${runId}`);
  await page.selectOption('#proj-kind', 'web');
  await page.fill('#proj-ref', join(tmp, 'sitio-e2e'));
  await page.press('#proj-ref', 'Enter');
  await page.check('input[name=proj-mode][value=guided]');
  await page.click('#proj-go');
  await page.waitForSelector('#proj-approve');
  await page.selectOption('#proj-target', 'static');                 // edición del plan antes de aprobar
  await page.click('#proj-approve');
  await page.waitForSelector('#proj-continue', { timeout: 60000 });
  let text = await page.textContent('#proj-view');
  assert.match(text, /Plan · versión 2/);
  assert.match(text, /tecnología auto → static/);
  assert.match(text, /En pausa/);
  assert.equal(await page.locator('.proj-step .badge.ok').count(), 1);   // solo el primer paso
  await page.fill('#proj-instruction', 'añade base de datos');
  await page.click('#proj-add-instruction');
  await page.waitForSelector('#proj-change-yes');
  assert.match(await page.textContent('.proj-change'), /requiere aprobar el plan revisado/);
  await axe('cambio de plan propuesto');
  await page.click('#proj-change-yes');
  await page.waitForFunction(() => /versión 3/.test(document.querySelector('#proj-view h3')?.textContent || ''));
  text = await page.textContent('#proj-view');
  assert.match(text, /En pausa/);
  assert.match(text, /Instrucciones añadidas: añade base de datos/);
  await page.click('#proj-continue');
  await page.waitForFunction(() => document.querySelectorAll('.proj-step .badge.ok').length === 2, null, { timeout: 60000 });
  assert.match(await page.textContent('#proj-view'), /Especificación v1/);
});

test('sincronizar un proyecto (D1): propone sin escribir, aplicar pide confirmación y verifica', async () => {
  const site = join(tmp, 'sync-sitio');
  const out = join(tmp, 'sync-proyecto');
  // Proyecto de prueba generado con la plantilla (sin verificación: es un dato de la prueba, no un producto).
  execFileSync(PY, ['-c', [
    'import sys, pathlib',
    'from tests.fixtures import build_site',
    'from eolfi.core.evidence import EvidenceStore',
    'from eolfi.flows.create_flow import create_project',
    'site = build_site(pathlib.Path(sys.argv[1]))',
    'create_project([str(site)], EvidenceStore(":memory:"), sys.argv[2], name="Bicis", target="static", do_verify=False)',
  ].join('\n'), site, out], { cwd: ROOT,
    env: { ...process.env, EOLFI_ACCIONES_FILE: join(tmp, 'acciones-sync.jsonl') } });
  await page.goto(BASE + '/');
  await page.waitForSelector('#version:not(:empty)');
  await openTools('create');
  await page.click('#sync-box summary');
  await page.fill('#sync-project', out);
  await page.click('#sync-go');
  await page.waitForSelector('#sync-result [role="status"] strong', { timeout: 60000 });
  assert.match(await page.textContent('#sync-result'), /Al día/);
  // La fuente cambia: se proponen cambios y nada se escribe hasta aplicar.
  const css = join(site, 'css', 'app.css');
  const { writeFileSync } = await import('node:fs');
  writeFileSync(css, readFileSync(css, 'utf8').replace('#e11d48', '#2563eb'));
  const tokens = join(out, 'css', 'tokens.css');
  await page.click('#sync-go');
  await page.waitForSelector('#sync-result details.step', { timeout: 60000 });
  assert.match(await page.textContent('#sync-result'), /Cambios propuestos/);
  assert.match(readFileSync(tokens, 'utf8'), /#e11d48/);
  await axe('cambios propuestos de la sincronización');
  let dialogo = '';
  page.once('dialog', (d) => { dialogo = d.message(); d.accept(); });
  await page.click('#sync-result button');
  await page.waitForFunction(() => /Verificado|NO VERIFICADO/.test(document.querySelector('#sync-result')?.textContent || ''),
    null, { timeout: 240000 });
  assert.match(dialogo, /\.eolfi-sync/);
  assert.match(await page.textContent('#sync-result'), /✓ Verificado/);
  assert.match(readFileSync(tokens, 'utf8'), /#2563eb/);
  await axe('sincronización aplicada');
});

test('voz: dictar escribe en el chat sin enviar, las órdenes no se escriben y todo es accesible', async () => {
  let recibido = null;
  let texto = 'analiza este archivo';
  await page.route('**/api/voz/estado', (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({
    motor_activo: 'windows', idioma: 'es-ES', voz_a_texto: true, texto_a_voz: true, local: true }) }));
  await page.route('**/api/voz/transcribir', async (route) => {
    const body = route.request().postDataBuffer();
    recibido = { cabecera: body.subarray(0, 4).toString('latin1'), formato: body.readUInt16LE(20), canales: body.readUInt16LE(22),
      hz: body.readUInt32LE(24), bits: body.readUInt16LE(34), bytes: body.length, xeolfi: route.request().headers()['x-eolfi'] };
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ texto, motor: 'windows', confianza: 0.8 }) });
  });
  await page.goto(BASE + '/');
  await page.waitForSelector('#voz-mic:not([hidden])');
  assert.match(await page.textContent('#voz-estado'), /Voz local lista/);
  await axe('chat con voz');
  await page.fill('#eolas-chat-input', 'Hola,');
  await page.click('#voz-mic');
  await page.waitForSelector('#voz-mic[aria-pressed=true]');
  await page.waitForTimeout(700);
  await page.click('#voz-mic');
  await page.waitForFunction(() => /analiza este archivo/.test(document.querySelector('#eolas-chat-input').value));
  assert.equal(await page.inputValue('#eolas-chat-input'), 'Hola, analiza este archivo');
  // Lo que sale del navegador es un WAV PCM de 16 bits, mono, a 16 kHz, y solo hacia el propio servidor.
  assert.deepEqual({ ...recibido, bytes: recibido.bytes > 44 }, { cabecera: 'RIFF', formato: 1, canales: 1, hz: 16000, bits: 16, bytes: true, xeolfi: '1' });
  assert.equal(await page.locator('#eolas-chat-log .msg.user').count(), 0);          // dictar no envía
  assert.match(await page.textContent('#voz-estado'), /motor local «windows»/);
  texto = 'Borra todo.';                                                                // orden, no texto
  await page.keyboard.press('Alt+m');
  await page.waitForSelector('#voz-mic[aria-pressed=true]');
  await page.waitForTimeout(500);
  await page.keyboard.press('Alt+m');
  await page.waitForFunction(() => document.querySelector('#eolas-chat-input').value === '');
  assert.match(await page.textContent('#voz-estado'), /Orden por voz: borrar/);
  // A7: el mismo dictado en otros cuadros del panel; ahí «Borra todo.» es texto, no una orden.
  await openTools('create');
  await page.waitForSelector('#proj-desc + .voz-junto .voz-dictar');
  await page.fill('#proj-desc', 'Una web con');
  await page.click('#proj-desc + .voz-junto .voz-dictar');
  await page.waitForSelector('#proj-desc + .voz-junto .voz-dictar[aria-pressed=true]');
  assert.equal(await page.isDisabled('#voz-mic'), true);                              // un solo dictado a la vez
  await page.waitForTimeout(500);
  await page.click('#proj-desc + .voz-junto .voz-dictar');
  await page.waitForFunction(() => document.querySelector('#proj-desc').value === 'Una web con Borra todo.');
  assert.match(await page.textContent('#proj-desc + .voz-junto .voz-nota'), /motor local «windows»/);
  assert.equal(await page.inputValue('#eolas-chat-input'), '');
  assert.equal(await page.locator('.voz-dictar').count(), 5);
  await axe('dictado en crear proyecto');
  assert.deepEqual(errors, []);
});

// 18/11/2026: lectura con Piper (voz neuronal local). Contexto propio y CSP real: el audio llega como blob:.
function wavSilencio(segundos, hz = 22050) {
  const datos = Buffer.alloc(Math.round(segundos * hz) * 2);
  const cab = Buffer.alloc(44);
  cab.write('RIFF', 0); cab.writeUInt32LE(36 + datos.length, 4); cab.write('WAVE', 8); cab.write('fmt ', 12);
  cab.writeUInt32LE(16, 16); cab.writeUInt16LE(1, 20); cab.writeUInt16LE(1, 22); cab.writeUInt32LE(hz, 24);
  cab.writeUInt32LE(hz * 2, 28); cab.writeUInt16LE(2, 32); cab.writeUInt16LE(16, 34); cab.write('data', 36);
  cab.writeUInt32LE(datos.length, 40);
  return Buffer.concat([cab, datos]);
}

test('voz: con Piper lee por trozos, elige voz y ajuste, y Esc corta la lectura', async () => {
  const ctx = await browser.newContext();
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', (e) => errs.push(String(e)));
  p.on('console', (m) => { if (m.type() === 'error' && /Content Security Policy/.test(m.text())) errs.push(m.text()); });
  const voces = [{ modelo: 'C:/v/es_ES-davefx-medium.onnx', nombre: 'es_ES-davefx-medium', idioma: 'es-ES', hablantes: 1 },
    { modelo: 'C:/v/es_ES-sharvard-medium.onnx', nombre: 'es_ES-sharvard-medium', idioma: 'es-ES', hablantes: 2 }];
  let piper = { disponible: true, modelo: voces[1].modelo, hablante: 1, ajuste: 'natural', voces };
  const estado = () => ({ motor_activo: 'windows', idioma: 'es-ES', voz_a_texto: true, texto_a_voz: true, local: true,
    lectura_activa: 'piper', ajustes: ['original', 'natural', 'pausada'], piper });
  const pedidos = [], configs = [];
  await p.route('**/api/voz/estado', (r) => r.fulfill({ json: estado() }));
  await p.route('**/api/voz/config', async (r) => {
    const body = JSON.parse(r.request().postData());
    configs.push(body);
    piper = { ...piper, ...body.piper };
    await r.fulfill({ json: estado() });
  });
  await p.route('**/api/voz/hablar', async (r) => {
    pedidos.push(JSON.parse(r.request().postData()).texto);
    await r.fulfill({ contentType: 'audio/wav', body: wavSilencio(1.5) });
  });
  try {
    await p.goto(BASE + '/#chat');
    await p.waitForSelector('#eolas-chat-form[data-ready]', { state: 'attached' });
    await p.waitForSelector('.voz-lectura:not([hidden])');
    const opciones = await p.$$eval('#voz-voz option', (os) => os.map((o) => [o.textContent, o.selected]));
    assert.deepEqual(opciones, [['davefx', false], ['sharvard · hombre', false], ['sharvard · mujer', true]]);
    assert.equal(await p.inputValue('#voz-ajuste'), 'natural');
    // Cambiar el ajuste guarda la voz elegida y la presenta en voz alta.
    await p.selectOption('#voz-ajuste', 'pausada');
    await p.waitForFunction(() => document.querySelector('#voz-ajuste').value === 'pausada');
    assert.deepEqual(configs, [{ piper: { modelo: voces[1].modelo, hablante: 1, ajuste: 'pausada' } }]);
    await expectEventually(() => pedidos.includes('Hola, así sueno con esta voz.'));
    await p.keyboard.press('Escape');
    // Una respuesta larga se lee por trozos (el siguiente se pide mientras suena el actual) y sin el código.
    await p.check('#voz-leer');
    pedidos.length = 0;
    const frase = 'Esta es una frase de prueba bastante larga para que la respuesta tenga varios trozos al leerla. ';
    await p.evaluate((t) => window.dispatchEvent(new CustomEvent('eolfi:chat-reply', { detail: { text: t } })),
      `${frase.repeat(3)}\n\n\`\`\`python\nprint(1)\n\`\`\`\n${frase.repeat(2)}`);
    await expectEventually(() => pedidos.length >= 2);
    assert.ok(pedidos.every((t) => t.length <= 3500 && !t.includes('print(1)')), JSON.stringify(pedidos));
    assert.ok(pedidos[0].length <= 280);
    await p.keyboard.press('Escape');
    await p.waitForFunction(() => /Voz detenida/.test(document.querySelector('#voz-estado').textContent));
    const pedidosAlParar = pedidos.length;
    await p.waitForTimeout(1800);
    assert.ok(pedidos.length <= pedidosAlParar + 1, 'tras Esc no sigue pidiendo audio');
    await p.evaluate(AXE);   // por evaluate: la CSP real del panel (sin bypass) bloquea un <script> inline
    const r = await p.evaluate(async () => (await axe.run(document, { resultTypes: ['violations'] })).violations
      .filter((v) => ['serious', 'critical'].includes(v.impact)).map((v) => v.id));
    assert.deepEqual(r, []);
    assert.deepEqual(errs, []);
  } finally {
    await ctx.close();
  }
});

async function expectEventually(cond, ms = 8000) {
  const t0 = Date.now();
  while (!cond()) {
    if (Date.now() - t0 > ms) throw new Error('la condición no se cumplió a tiempo');
    await new Promise((r) => setTimeout(r, 50));
  }
}

test('idioma: el panel en inglés con ?lang=en, sin tocar el contenido, y vuelta al castellano (C1)', async () => {
  // Contexto propio: la elección se guarda en localStorage y no debe afectar a las otras pruebas.
  const ctx = await browser.newContext({ bypassCSP: true, locale: 'en-US' });
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', (e) => errs.push(String(e)));
  await p.goto(BASE + '/');                                                        // sin elegir: castellano
  await p.waitForSelector('#version:not(:empty)');
  assert.equal(await p.textContent('#open-analysis'), 'Análisis');
  await p.goto(BASE + '/?lang=en');
  await p.waitForFunction(() => document.querySelector('#open-analysis').textContent === 'Analysis');
  assert.equal(await p.getAttribute('html', 'lang'), 'en');
  assert.equal(await p.title(), 'Eolfi — evidence panel');
  assert.equal(await p.getAttribute('#eolas-chat-input', 'placeholder'), 'Write to Eolfi… (Ctrl+Enter to send)');
  assert.equal(await p.getAttribute('#chat-log', 'aria-label'), 'Chat history');
  // Lo que añade el JS después también se traduce; el contenido marcado (evidencias), no.
  const r = await p.evaluate(async () => {
    const a = document.createElement('span'); a.textContent = 'Exportar'; document.querySelector('.tools').append(a);
    const b = document.createElement('p'); b.textContent = 'Exportar'; document.getElementById('evidence').append(b);
    await new Promise((ok) => setTimeout(ok, 50));
    return [a.textContent, b.textContent];
  });
  assert.deepEqual(r, ['Export', 'Exportar']);
  // Textos con partes variables (plantillas con «{}»): los huecos pasan tal cual o traducidos si son un texto
  // entero del diccionario; las llaves de un dato no se confunden con un hueco.
  const dinamicos = await p.evaluate(async () => {
    const textos = ['Listo en 3.2 s', 'Repetición: NO reproducible', 'Mostrando 3 de 10 objetivos.',
      'Caso «x {y}» creado y activo.', 'Proyecto go sin verificación satisfactoria', 'Sin incógnitas abiertas.'];
    const nodos = textos.map((t) => { const n = document.createElement('p'); n.textContent = t; return n; });
    document.querySelector('.tools').append(...nodos);
    const enEvidencia = document.createElement('p'); enEvidencia.textContent = 'Listo en 9 s';
    document.getElementById('evidence').append(enEvidencia);
    await new Promise((ok) => setTimeout(ok, 50));
    const out = nodos.map((n) => n.textContent).concat(enEvidencia.textContent, window.eolfiT('Listo en 1 s'));
    nodos.forEach((n) => n.remove()); enEvidencia.remove();
    return out;
  });
  assert.deepEqual(dinamicos, ['Done in 3.2 s', 'Repetition: NOT reproducible', 'Showing 3 of 10 targets.',
    'Case "x {y}" created and active.', 'go project without a successful verification', 'No open unknowns.',
    'Listo en 9 s', 'Done in 1 s']);
  assert.match(await p.evaluate(() => document.cookie), /eolfi_idioma=en/);
  // Volver al castellano con el selector: se guarda y la página se recarga.
  await p.selectOption('#idioma', 'es');
  await p.waitForFunction(() => document.querySelector('#open-analysis').textContent === 'Análisis');
  assert.equal(await p.evaluate(() => localStorage.getItem('eolfi.idioma')), 'es');
  assert.deepEqual(errs, []);
  await ctx.close();
});

test('mapa de la app (C5): grafo de llamadas y componentes de REA dibujados y accesibles', async () => {
  // Resultados con la forma real: las funciones de Eolfi con los dobles de REA de las pruebas de Python.
  const res = JSON.parse(execFileSync(PY, ['-c', [
    'import json, sys, tempfile, zipfile', 'from pathlib import Path', 'from eolfi import rea_compuestas as rc',
    'from tests.rea_fakes import FakeAndroid, FakeApple, FakeCallGraph, _info_plist',
    'd = Path(tempfile.mkdtemp()); apk = d / "a.apk"; apk.write_bytes(b"PK"); z = d / "X.app.zip"',
    'zipfile.ZipFile(z, "w").writestr("X.app/Contents/Info.plist", _info_plist())',
    'g = rc.grafo_llamadas(FakeCallGraph(), "x.exe", "entry"); v = dict(g); v.pop("enlaces")',
    'print(json.dumps({"grafo": g, "antiguo": v, "android": rc.mapa_app_android(FakeAndroid(), str(apk)),',
    '                  "apple": rc.mapa_app_apple(FakeApple(), str(z))}))'].join('\n')],
  { cwd: ROOT, encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }));
  const ev = (operation, result, id) => ({ evidence_id: id.repeat(64), subject: 'mapa-demo', provider: 'rea', provider_version: 'prueba',
    operation, params: {}, result, authority: 'distributed_artifact', confidence: 'medium', limitations: result.aviso,
    environment: 'e2e', created_at: '2026-11-17T20:00:00Z' });
  const evidencias = [ev('grafo_llamadas', res.grafo, 'a'), ev('mapa_app_android', res.android, 'b'),
    ev('mapa_app_apple', res.apple, 'c'), ev('grafo_llamadas', res.antiguo, 'd')];
  await page.route('**/api/evidence?subject=mapa-demo*', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ evidence: evidencias, total: evidencias.length }) }));
  try {
    await page.goto(BASE + '/#objetivo/mapa-demo');
    await page.waitForSelector('#evidence details.ev');
    for (const d of await page.locator('#evidence details.ev').all()) await d.locator('summary').click();
    // Grafo: 5 funciones por niveles, 4 llamadas, las importaciones diferenciadas y la alternativa en texto.
    const grafo = page.locator('figure.mapa').first();
    assert.match(await grafo.locator('figcaption').textContent(), /5 funciones y 4 llamadas desde «entry»/);
    assert.equal(await grafo.locator('.mapa-nodo').count(), 5);
    assert.equal(await grafo.locator('.mapa-nodo.externa').count(), 2);
    assert.equal(await grafo.locator('.mapa-nodo.raiz').count(), 1);
    assert.equal(await grafo.locator('.mapa-arista').count(), 4);
    assert.match(await grafo.locator('svg').getAttribute('aria-label'), /^Grafo de llamadas: 5 funciones/);
    assert.deepEqual(await grafo.locator('.mapa-lista li').allTextContents(),
      ['entry → FUN_20', 'entry → raro"[x]', 'FUN_20 → KERNEL32.DLL::Sleep', 'FUN_20 → MSVCRT.DLL::exit']);
    // Un nombre del binario con comillas y corchetes es texto, no marcado.
    assert.equal(await grafo.locator('.mapa-nodo text', { hasText: 'raro"[x]' }).count(), 1);
    // Android: pantallas y componentes, la de inicio y lo exportado sin permiso, cada componente una vez.
    const app = page.locator('figure.mapa').nth(1);
    assert.match(await app.locator('figcaption').textContent(), /a 1\.0 · SDK 26–33/);
    const pantallas = app.locator('section[aria-label="Pantallas (actividades)"]');
    assert.deepEqual(await pantallas.locator('li').allTextContents(), ['Main inicio exportado sin permiso']);
    assert.match(await pantallas.textContent(), /2 en total · 1 exportados · 1 sin permiso/);
    assert.match(await app.textContent(), /Permisos peligrosos: CAMERA/);
    // Apple: bundles por papel, con su nombre de archivo.
    const apple = page.locator('figure.mapa').nth(2);
    assert.deepEqual(await apple.locator('li').allTextContents(), ['X.app firmado', 'H.xpc sin firma']);
    // Una evidencia anterior a C5 (solo Mermaid) se dibuja igual.
    assert.equal(await page.locator('figure.mapa').nth(3).locator('.mapa-arista').count(), 4);
    await axe('mapa de la app');
    await page.evaluate(() => { document.documentElement.dataset.theme = 'dark'; });
    await axe('mapa de la app (oscuro)');
    await page.evaluate(() => { delete document.documentElement.dataset.theme; });
  } finally {
    await page.unroute('**/api/evidence?subject=mapa-demo*');
  }
  await page.goto(BASE + '/');
  assert.deepEqual(errors, []);
});
