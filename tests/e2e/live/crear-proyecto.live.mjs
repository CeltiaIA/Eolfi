// Prueba e2e EN VIVO (opcional, fuera de la CI): recorrido completo de «Crear proyecto» en el panel REAL que tienes
// arrancado, con Chrome VISIBLE para que lo sigas: fuentes → plan razonado → aprobar → generar → verificar → comparar.
//
//   1. Arranca Eolfi (p. ej. «python -m eolfi up» o «python -m eolfi serve»).
//   2. cd tests/e2e && node live/crear-proyecto.live.mjs
//
//   EOLFI_LIVE_URL=http://127.0.0.1:8777   panel a usar (por defecto)
//   EOLFI_LIVE_HEADLESS=1                   sin ventana (por defecto se ve)
//   EOLFI_E2E_CHANNEL=msedge | EOLFI_E2E_BROWSER=/ruta/al/chrome
//
// Usa solo una muestra sintética propia (un sitio estático generado aquí). Deja en la base del panel un caso
// llamado «e2e en vivo <fecha>» con su proyecto en generated/: así queda la evidencia del recorrido.
import { chromium } from 'playwright-core';
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const BASE = (process.env.EOLFI_LIVE_URL || 'http://127.0.0.1:8777').replace(/\/$/, '');
const EOLAS = process.env.EOLFI_LIVE_EOLAS || 'http://127.0.0.1:11435';
const steps = [];
const ok = (name, detail = '') => { steps.push({ name, ok: true, detail }); console.log(`✓ ${name}${detail ? ` — ${detail}` : ''}`); };
const fail = (name, detail) => { steps.push({ name, ok: false, detail }); console.log(`✗ ${name} — ${detail}`); };
const api = async (path, body) => {
  const r = await fetch(BASE + path, body ? { method: 'POST', headers: { 'content-type': 'application/json', 'X-Eolfi': '1' },
    body: JSON.stringify(body) } : {});
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`${path}: ${d.error || r.status}`);
  return d;
};

async function main() {
  // 0. Servicios reales.
  try { const h = await api('/api/health'); ok('panel en marcha', `Eolfi ${h.version}, base ${h.db}`); }
  catch (e) { fail('panel en marcha', `${BASE} no responde (${e.message}): arranca «python -m eolfi up»`); return; }
  try {
    const r = await fetch(`${EOLAS}/v1/models`, { signal: AbortSignal.timeout(3000) });
    const m = await r.json();
    ok('Eolas (informativo)', (m.data || []).map((x) => x.id).join(', ') || 'sin modelos listados');
  } catch { ok('Eolas (informativo)', 'no responde: este recorrido no lo necesita'); }

  // 1. Muestra sintética propia.
  const tmp = mkdtempSync(join(tmpdir(), 'eolfi-live-'));
  const site = join(tmp, 'catalogo-sintetico');
  mkdirSync(site);
  writeFileSync(join(site, 'index.html'), '<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Catálogo</title></head>'
    + '<body><header><h1>Catálogo sintético</h1><nav><a href="index.html">Inicio</a> <a href="contacto.html">Contacto</a></nav></header>'
    + '<main><section><h2>Libros</h2><ul><li>Uno</li><li>Dos</li></ul></section></main><footer>Prueba en vivo</footer></body></html>');
  writeFileSync(join(site, 'contacto.html'), '<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Contacto</title></head>'
    + '<body><h1>Contacto</h1><form><label>Nombre <input name="n"></label><button>Enviar</button></form></body></html>');
  ok('muestra sintética', site);

  const browser = await chromium.launch({ headless: process.env.EOLFI_LIVE_HEADLESS === '1', slowMo: 120,
    ...(process.env.EOLFI_E2E_BROWSER ? { executablePath: process.env.EOLFI_E2E_BROWSER } : { channel: process.env.EOLFI_E2E_CHANNEL || 'chrome' }) });
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  try {
    // 2. Formulario único → plan razonado.
    const name = `e2e en vivo ${new Date().toISOString().slice(0, 19).replace('T', ' ')}`;
    await page.goto(BASE + '/');
    await page.waitForSelector('#version:not(:empty)');
    await page.click('#panel-create-tab');
    await page.fill('#proj-name', name);
    await page.fill('#proj-desc', 'Una web estática con las mismas secciones. Que tenga modo oscuro.');
    await page.selectOption('#proj-kind', 'web');
    await page.fill('#proj-ref', site);
    await page.click('#proj-add');
    await page.click('#proj-go');
    await page.waitForSelector('#proj-view:not([hidden]) .proj-plan', { timeout: 60000 });
    const plan = await page.textContent('#proj-view');
    if (/Pendiente de tu aprobación/.test(plan) && /nunca se copia código/.test(plan)) ok('plan razonado propuesto, nada ejecutado');
    else fail('plan razonado', plan.slice(0, 300));
    const caseId = await page.evaluate(() => [...document.querySelectorAll('a')].map((a) => a.href).find((h) => /#caso\//.test(h)));

    // 3. Aprobar → analizar → especificar → generar → verificar.
    await page.click('#proj-approve');
    // Termina con un veredicto de verificación o con un paso fallido (no se espera un veredicto que no llegará).
    await page.waitForSelector('.proj-verdict, .proj-step .badge.bad', { timeout: 15 * 60000 });
    if (!(await page.$('.proj-verdict'))) {
      const err = await page.textContent('.proj-step .bad, .proj-result .bad').catch(() => '');
      fail('ejecución del plan', `un paso falló: ${(err || '').trim().slice(0, 300)}`);
      return;
    }
    const verdict = await page.textContent('.proj-verdict');
    const status = await page.textContent('#proj-view .badge');
    if (/^Verificado/.test(verdict)) ok('generado y verificado', verdict.trim());
    else fail('verificación', `${verdict.trim()} (${status.trim()})`);
    const report = await page.getAttribute('#proj-report', 'href');
    const cid = (report || caseId || '').match(/[0-9a-f-]{36}/)?.[0];
    if (!cid) { fail('caso del proyecto', 'no se encontró el identificador'); return; }
    const st = await api(`/api/projects/${cid}`);
    ok('caso con plan, aprobación y pasos', `${st.decisions.length} decisiones, pasos ${Object.keys(st.results).join(', ')}`);

    // 4. Comparar el original con la reconstrucción (análisis estático de ambos, mismo caso).
    const gen = st.results.generar;
    const src = st.results['analizar-1'].subject;
    const learned = await api('/api/web', { source: gen.out, case_id: cid });
    const cmp = await api('/api/compare', { a: src, b: learned.subject, case_id: cid });
    ok('comparación original ↔ reconstrucción', `${cmp.headline || ''} · cambian: ${Object.keys(cmp.changed || {}).slice(0, 8).join(', ') || 'nada'}`
      + ` · iguales: ${(cmp.unchanged || []).length}`);
    await page.goto(`${BASE}${report}`);
    ok('informe del caso abierto', `${BASE}${report}`);
    if (errors.length) fail('errores de JavaScript en el panel', errors.join(' | ').slice(0, 300));
    else ok('sin errores de JavaScript en el panel');
    if (process.env.EOLFI_LIVE_HEADLESS !== '1') await page.waitForTimeout(4000);
  } catch (e) {
    fail('recorrido', e.message.split('\n')[0]);
  } finally {
    await browser.close();
  }
}

await main();
const bad = steps.filter((s) => !s.ok);
console.log(`\n${steps.length - bad.length}/${steps.length} comprobaciones superadas${bad.length ? `; fallan: ${bad.map((s) => s.name).join(', ')}` : ''}`);
process.exit(bad.length ? 1 : 0);
