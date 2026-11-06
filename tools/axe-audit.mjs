// Auditoría de accesibilidad del panel con axe-core, usando el motor CDP del propio puente
// (Chrome con perfil temporal, control por tubería).
//
//   npm install --prefix tools axe-core          (una vez)
//   node tools/axe-audit.mjs [URL] [js-de-vista ...]       DARK=1 para el tema oscuro
//
// Imprime las infracciones por vista en JSON; sale con código 1 si hay alguna.
import { readFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const engineUrl = new URL('../eolfi/bridge/engine/chrome.mjs', import.meta.url).href;
const { ChromeEngine, findBrowser } = await import(engineUrl);
const axe = readFileSync(process.env.AXE_PATH || new URL('./node_modules/axe-core/axe.min.js', import.meta.url), 'utf8');
const profile = mkdtempSync(join(tmpdir(), 'eolfi-axe-'));
const engine = new ChromeEngine({ browser: findBrowser(''), profile });
const url = process.argv[2] || 'http://127.0.0.1:8777/';
try {
  const c = await engine.page('panel', url, new URL(url).origin);
  await new Promise((r) => setTimeout(r, 2500));
  if (process.env.DARK === '1') await c.cdp.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'dark' }] });
  const views = process.argv.slice(3);
  const results = {};
  for (const view of ['inicial', ...views]) {
    if (view !== 'inicial') await c.executeJavaScript(view);
    await new Promise((r) => setTimeout(r, 800));
    await c.executeJavaScript(axe + ';0');
    const out = await c.executeJavaScript(`(async () => { const r = await axe.run(document, { resultTypes: ['violations'] });
        return r.violations.map(v => ({ id: v.id, impact: v.impact, help: v.help,
          nodes: v.nodes.slice(0, 4).map(n => n.target.join(' ') + ' :: ' + (n.failureSummary || '').split(String.fromCharCode(10))[1]) })); })()`);
    results[view.slice(0, 40)] = out;
  }
  console.log(JSON.stringify(results, null, 2));
  process.exitCode = Object.values(results).some((v) => v.length) ? 1 : 0;
} finally {
  await engine.close();
  await new Promise((r) => setTimeout(r, 1200));
  rmSync(profile, { recursive: true, force: true });
}
