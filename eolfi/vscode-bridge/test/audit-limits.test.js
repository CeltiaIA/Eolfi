'use strict';
// Casos reales de la auditoría de D:\celtiaia (2026-11-06): se paró en el archivo 13 de 2151 con «Message exceeds token
// limit.» por un JSON de 55 MB en una sola línea, y el inventario incluía runtime/ (ignorado por .gitignore).
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { inventory, pieces, reviewBatch, splitPiece, TOO_BIG, gitignore, runAudit } = require('../audit');
const { isSecretPath } = require('../workspace');

function proyecto() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-audit-lim-'));
  const w = (rel, text) => { const p = path.join(root, rel); fs.mkdirSync(path.dirname(p), { recursive: true }); fs.writeFileSync(p, text); };
  w('.gitignore', 'runtime/\ndocs/audit/rea/*.json\n*.log\nmodels/**\n!keep.log\n');
  w('server.mjs', 'export const a = 1;\n');
  w('runtime/candidato/main/index.js', 'x');
  w('docs/audit/rea/volcado.json', '{"a":1}');
  w('docs/audit/INFORME.json', '{"ok":true}');
  w('models/m/config.json', '{}');
  w('a.log', 'x');
  w('src/datos-grandes.json', `[${'1,'.repeat(1_100_000)}1]`);
  return root;
}

test('el error de Copilot «Message exceeds token limit» se reconoce como lote demasiado grande', () => {
  assert.ok(TOO_BIG.test('Message exceeds token limit.'));
  assert.ok(TOO_BIG.test('Request Entity Too Large'));
  assert.ok(!TOO_BIG.test("you've exceeded your rate limit for utility models"));
});

test('inventario: respeta .gitignore y omite archivos enormes', () => {
  const root = proyecto();
  const { files, skipped } = inventory(root, { isSecretPath });
  const rel = files.map((f) => path.relative(root, f.path).replace(/\\/g, '/')).sort();
  assert.deepStrictEqual(rel, ['docs/audit/INFORME.json', 'server.mjs']);
  assert.ok(skipped.some((s) => /runtime$/.test(s.path) && /\.gitignore/.test(s.why)));
  assert.ok(skipped.some((s) => /volcado\.json$/.test(s.path)));
  assert.ok(skipped.some((s) => /datos-grandes\.json$/.test(s.path) && /demasiado grande/.test(s.why)));
});

test('gitignore: negaciones y patrones habituales', () => {
  const root = proyecto();
  const ig = gitignore(root);
  assert.strictEqual(ig('a.log', false), true);
  assert.strictEqual(ig('keep.log', false), false);
  assert.strictEqual(ig('runtime', true), true);
  assert.strictEqual(ig('src/runtime.js', false), false);
  assert.strictEqual(ig('models/m/config.json', false), true);
});

test('una línea enorme se trocea en partes y no en un solo trozo gigante', () => {
  const line = 'x'.repeat(200000);
  const ps = pieces('f.json', `a\n${line}\nb`);
  assert.ok(ps.length >= 4);
  assert.ok(ps.every((p) => p.text.length <= 60000));
  const halves = splitPiece({ path: 'f.json', text: 'y'.repeat(10000), from: 3 });
  assert.strictEqual(halves.length, 2);
  assert.strictEqual(halves[0].text.length + halves[1].text.length, 10000);
});

test('si un trozo no cabe ni partido, se anota como omitido y la revisión sigue', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-audit-lim-'));
  const p = { path: path.join(root, 'grande.js'), text: 'z'.repeat(1500), from: 1 };
  const out = await reviewBatch([p], root, '', async () => { throw new Error('Message exceeds token limit.'); }, null);
  assert.match(out, /### `grande\.js`/);
  assert.match(out, /Omitido: no cabe en el contexto del modelo/);
});

test('un lote demasiado grande se parte y se revisa por mitades', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-audit-lim-'));
  const p = { path: path.join(root, 'medio.js'), text: Array.from({ length: 400 }, (_, i) => `const v${i} = ${i};`).join('\n'), from: 1 };
  let calls = 0;
  const out = await reviewBatch([p], root, '', async (prompt) => {
    calls++;
    if (prompt.length > 6000) throw new Error('Message exceeds token limit.');
    return '### `medio.js`\n- **Propósito:** x';
  }, null);
  assert.ok(calls > 2);
  assert.ok(!/Omitido/.test(out));
});

test('al continuar, lo pendiente se recalcula con las reglas nuevas y lo hecho se conserva', async () => {
  const root = proyecto();
  const stateDir = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-audit-st-'));
  const report = 'informes/a.md';
  const { stateFile } = require('../audit');
  const viejo = [path.join(root, 'docs/audit/INFORME.json'), path.join(root, 'docs/audit/rea/volcado.json'), path.join(root, 'runtime/candidato/main/index.js'), path.join(root, 'server.mjs')];
  const sf = stateFile(root, report, stateDir);
  fs.mkdirSync(path.dirname(sf), { recursive: true });
  fs.writeFileSync(sf, JSON.stringify({ root, report, files: viejo, skipped: [], next: 1, highlights: [], done: false }));
  const seen = [];
  const said = [];
  const r = await runAudit({ root, report, resume: true, deps: {
    stateDir, isSecretPath, verify: false,
    complete: async (prompt) => {
      const files = [...prompt.matchAll(/===== ARCHIVO: (\S+)/g)].map((m) => m[1]);
      seen.push(...files);
      return files.map((f) => `### \`${f}\`\n- ok`).join('\n\n') || '## Resumen y prioridades\nbien';
    },
    append: async () => {}, open: async () => {}, progress: () => {}, say: (m) => said.push(m),
  } });
  assert.deepStrictEqual(seen, ['server.mjs']);
  assert.strictEqual(r.total, 2);
  assert.ok(said.some((m) => /Inventario actualizado/.test(m)));
});

test('continuar no empieza de cero si la carpeta llega con otra mayúscula de unidad (d:\\ y D:\\ en Windows)', { skip: process.platform !== 'win32' }, async () => {
  const root = proyecto();
  const stateDir = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-audit-st-'));
  const report = 'informes/b.md';
  const { stateFile } = require('../audit');
  const upper = root[0].toUpperCase() + root.slice(1);
  const lower = root[0].toLowerCase() + root.slice(1);
  const sf = stateFile(upper, report, stateDir);
  fs.mkdirSync(path.dirname(sf), { recursive: true });
  fs.writeFileSync(sf, JSON.stringify({ root: upper, report, files: [path.join(upper, 'server.mjs')], skipped: [], next: 1, highlights: [], done: false }));
  const said = [];
  await runAudit({ root: lower, report, resume: true, deps: { stateDir, isSecretPath, verify: false,
    complete: async () => '## Resumen y prioridades\nbien', append: async () => {}, open: async () => {}, progress: () => {}, say: (m) => said.push(m) } });
  assert.ok(said.some((m) => /Sigo la auditoría/.test(m)), said.join('|'));
});
