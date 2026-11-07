// Fase 2: pasos «browser» de una sesión de observación con un navegador real (muestra web sintética propia).
// Comprueba que las peticiones, consola, almacenamiento y texto visible quedan enlazados a la acción que los produjo
// y que las peticiones a hosts no autorizados se bloquean.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const ROOT = resolve(import.meta.dirname, '..', '..');
const PY = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const PAGE = `<!doctype html><html lang="es"><title>Contador</title><body><h1 id="n">0</h1>
<button id="mas">Sumar</button><script>
document.getElementById('mas').onclick = async () => {
  const j = await (await fetch('/api/sumar', { method: 'POST' })).json();
  document.getElementById('n').textContent = j.n; localStorage.setItem('n', String(j.n));
  fetch('http://ejemplo.invalid/rastreo').catch(() => {}); console.log('sumado ' + j.n);
};</script></body></html>`;

test('observación web: trazas enlazadas a la acción, bloqueo y repetición', async () => {
  let n = 0;
  const srv = createServer((req, res) => {
    if (req.method === 'POST') { n += 1; res.writeHead(201, { 'content-type': 'application/json' }); return res.end(JSON.stringify({ n })); }
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' }); res.end(PAGE);
  });
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  const port = String(srv.address().port);
  const tmp = mkdtempSync(join(tmpdir(), 'eolfi-e2e-obs-'));
  const db = join(tmp, 'e.db');
  const guion = join(tmp, 'guion.json');
  writeFileSync(guion, JSON.stringify({
    eolfi_observation_script: 1, name: 'contador web', authorization: 'muestra web sintética propia de la prueba',
    steps: [{ id: 'ui', action: 'browser', url: 'http://127.0.0.1:{var:port}/',
      actions: [{ id: 'pulsar', do: 'click', selector: '#mas' }] }],
  }));
  const pw = require.resolve('playwright-core');
  const env = { ...process.env, PYTHONIOENCODING: 'utf-8',
    ...(process.env.EOLFI_E2E_BROWSER ? { EOLFI_BROWSER_PATH: process.env.EOLFI_E2E_BROWSER }
      : { EOLFI_BROWSER_CHANNEL: process.env.EOLFI_E2E_CHANNEL || 'chrome' }) };
  // Asíncrono: el servidor de la muestra corre en este mismo proceso y no debe quedar bloqueado.
  const cli = async (...a) => {
    try { return JSON.parse((await promisify(execFile)(PY, ['-m', 'eolfi', '--db', db, 'observe', ...a], { cwd: ROOT, env })).stdout); }
    catch (e) { if (e.stdout?.length) return JSON.parse(e.stdout); throw e; }
  };
  try {
    const rep = await cli('run', guion, '--autorizo', '--var', `port=${port}`, '--playwright', pw);
    const step = rep.steps[0];
    assert.equal(step.status, 'ok', JSON.stringify(step).slice(0, 2000));
    assert.equal(rep.coverage.ui_web, 'observed');
    assert.ok(step.browser.version);
    const [inicio, pulsar] = step.actions;
    assert.equal(inicio.id, '_inicio');
    assert.ok(inicio.requests.some((r) => r.resource_type === 'document' && r.status === 200));
    const post = pulsar.requests.find((r) => r.method === 'POST');
    assert.equal(post.status, 201);
    assert.equal(post.action_id, 'pulsar');
    assert.equal(post.url, 'http://127.0.0.1:{var:port}/api/sumar');
    assert.ok(pulsar.requests.some((r) => r.url.startsWith('http://ejemplo.invalid') && r.blocked));
    assert.ok(!inicio.requests.some((r) => r.method === 'POST'));
    assert.ok(pulsar.console.some((m) => m.text === 'sumado 1'));
    assert.ok(pulsar.storage.localStorage.n);
    assert.match(pulsar.visible.text_preview, /^1/);
    assert.notEqual(pulsar.visible.text_sha256, inicio.visible.text_sha256);
    assert.ok(pulsar.aria.preview.includes('Sumar'));
    // Repetición: el servidor conserva el contador (estado externo) → no reproducible, y se marca.
    const r2 = await cli('replay', rep.evidence_id, '--autorizo', '--var', `port=${port}`, '--playwright', pw);
    assert.equal(r2.reproducible, false);
    assert.ok(r2.non_reproducible.some((d) => d.aspect === 'pulsar.texto visible'));
    // Con el estado externo restaurado, la repetición coincide.
    n = 0;
    const r3 = await cli('replay', rep.evidence_id, '--autorizo', '--var', `port=${port}`, '--playwright', pw);
    assert.equal(r3.reproducible, true, JSON.stringify(r3.non_reproducible));
  } finally {
    srv.close();
    try { rmSync(tmp, { recursive: true, force: true }); } catch { /* Windows puede tardar en soltar la base */ }
  }
});

test('comparación de interfaces: navegación, contenido y accesibilidad con tolerancias declaradas', async () => {
  const page = (label, callsApi) => `<!doctype html><html lang="es"><title>Contador</title><body><h1 id="n">0</h1>
<button id="mas">${label}</button><script>
document.getElementById('mas').onclick = async () => {
  ${callsApi ? "const j = await (await fetch('/api/sumar', { method: 'POST' })).json(); document.getElementById('n').textContent = j.n;"
    : "document.getElementById('n').textContent = 1;"}
};</script></body></html>`;
  const serve = (html) => {
    let n = 0;
    const s = createServer((req, res) => {
      if (req.method === 'POST') { n += 1; res.writeHead(201, { 'content-type': 'application/json' }); return res.end(JSON.stringify({ n })); }
      res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' }); res.end(html);
    });
    return new Promise((r) => s.listen(0, '127.0.0.1', () => r(s)));
  };
  const original = await serve(page('Sumar', true));
  const renamed = await serve(page('Añadir', true));          // solo cambia el texto del botón
  const broken = await serve(page('Sumar', false));           // no llama a la API: diferencia funcional
  const tmp = mkdtempSync(join(tmpdir(), 'eolfi-e2e-ui-'));
  const db = join(tmp, 'e.db');
  const guion = join(tmp, 'guion.json');
  writeFileSync(guion, JSON.stringify({
    eolfi_observation_script: 1, name: 'interfaz', authorization: 'muestra web sintética propia de la prueba',
    steps: [{ id: 'ui', action: 'browser', url: 'http://127.0.0.1:{var:port}/',
      actions: [{ id: 'pulsar', do: 'click', selector: '#mas' }] }],
  }));
  const pw = require.resolve('playwright-core');
  const env = { ...process.env, PYTHONIOENCODING: 'utf-8',
    ...(process.env.EOLFI_E2E_BROWSER ? { EOLFI_BROWSER_PATH: process.env.EOLFI_E2E_BROWSER }
      : { EOLFI_BROWSER_CHANNEL: process.env.EOLFI_E2E_CHANNEL || 'chrome' }) };
  const cli = async (...a) => {
    try { return JSON.parse((await promisify(execFile)(PY, ['-m', 'eolfi', '--db', db, 'observe', ...a], { cwd: ROOT, env })).stdout); }
    catch (e) { if (e.stdout?.length) return JSON.parse(e.stdout); throw e; }
  };
  try {
    const run = (srv) => cli('run', guion, '--autorizo', '--var', `port=${srv.address().port}`, '--playwright', pw);
    const a = await run(original), b = await run(renamed), c = await run(broken);
    for (const s of [a, b, c]) assert.equal(s.steps[0].status, 'ok', JSON.stringify(s.steps[0]).slice(0, 1500));
    const strict = await cli('compare', a.evidence_id, b.evidence_id);
    assert.equal(strict.identical, false);
    assert.match(strict.first_change.aspect, /texto visible|accesibilidad/);
    const tolerant = await cli('compare', a.evidence_id, b.evidence_id, '--tolerate', '*.texto visible', '--tolerate', '*.accesibilidad');
    assert.equal(tolerant.identical, true, JSON.stringify(tolerant.differences));
    assert.ok(tolerant.tolerated_total >= 2);
    assert.ok(tolerant.tolerated.every((d) => d.tolerated));
    // La diferencia funcional (sin petición a la API) no se oculta con esas tolerancias.
    const functional = await cli('compare', a.evidence_id, c.evidence_id, '--tolerate', '*.texto visible', '--tolerate', '*.accesibilidad');
    assert.equal(functional.identical, false);
    assert.equal(functional.first_change.aspect, 'pulsar.peticiones');
  } finally {
    for (const s of [original, renamed, broken]) s.close();
    try { rmSync(tmp, { recursive: true, force: true }); } catch { /* Windows puede tardar en soltar la base */ }
  }
});
