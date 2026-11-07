'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { inventory, pieces, runAudit, highlights } = require('../audit');
const { isSecretPath } = require('../workspace');

function proyecto() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-audit-'));
  const w = (rel, text) => { const p = path.join(root, rel); fs.mkdirSync(path.dirname(p), { recursive: true }); fs.writeFileSync(p, text); };
  for (let i = 0; i < 12; i++) w(`src/m${String(i).padStart(2, '0')}.py`, `def f${i}():\n    return ${i}\n`);
  w('src/app.js', 'eval(input)\n');
  w('src/main.go', 'package main\n\nfunc main() {}\n');
  w('README.md', '# no es código\n');
  w('.env', 'TOKEN=x');
  w('node_modules/lib/index.js', 'x');
  w('samples/malware.py', 'x');
  w('web/app.min.js', 'x');
  w('package-lock.json', '{}');
  w('img.png', '\x89PNG');
  w('vacio.py', '');
  return root;
}

function deps(log, { failAt = -1, token = null } = {}) {
  let calls = 0;
  const report = [];
  return {
    report,
    deps: {
      stateDir: fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-audit-st-')),
      isSecretPath,
      complete: async (prompt) => {
        calls++;
        if (calls === failAt && token) token.isCancellationRequested = true;
        const files = [...prompt.matchAll(/===== ARCHIVO: (\S+)/g)].map((m) => m[1]);
        log.push(files);
        return files.map((f) => `### \`${f}\`\n- **Propósito:** x\n- **Mejoras:**\n  - [alta] revisar ${f} L1`).join('\n\n');
      },
      append: async (_p, content) => { report.push(content); },
      open: async () => {},
      progress: () => {},
      say: () => {},
    },
  };
}

test('inventario: solo código, sin dependencias, muestras, minificados, locks ni secretos', () => {
  const root = proyecto();
  const { files, skipped } = inventory(root, { isSecretPath });
  const rel = files.map((f) => path.relative(root, f.path).replace(/\\/g, '/'));
  assert.strictEqual(rel.length, 14);
  assert.ok(rel.includes('src/app.js') && rel.includes('src/main.go') && rel.includes('src/m00.py'));
  for (const no of ['README.md', '.env', 'node_modules/lib/index.js', 'samples/malware.py', 'web/app.min.js', 'img.png', 'vacio.py']) {
    assert.ok(!rel.includes(no), no);
  }
  assert.ok(skipped.some((s) => s.why === 'generado o minificado'));
});

test('archivos grandes se revisan por partes con su número de línea', () => {
  const text = Array.from({ length: 5000 }, (_, i) => `linea_${i} = ${'x'.repeat(30)}`).join('\n');
  const ps = pieces('/p/grande.py', text);
  assert.ok(ps.length >= 3);
  assert.strictEqual(ps[0].from, 1);
  assert.strictEqual(ps[1].from, ps[0].text.split('\n').length + 1);
  assert.strictEqual(ps.map((p) => p.text).join('\n'), text);
});

test('revisa TODOS los archivos uno a uno, con sección por archivo, resumen y prioridades', async () => {
  const root = proyecto();
  const log = [];
  const d = deps(log);
  const r = await runAudit({ root, report: 'informes/a.md', deps: d.deps });
  assert.strictEqual(r.done, true);
  assert.strictEqual(r.total, 14);
  const reviewed = log.flat();
  assert.strictEqual(new Set(reviewed).size, 14);           // ninguno se queda sin revisar
  assert.ok(reviewed.includes('src/main.go'));
  assert.ok(log.every((b) => b.length <= 5));              // por lotes
  const all = d.report.join('\n');
  assert.match(all, /# Auditoría archivo por archivo/);
  assert.match(all, /Archivos a revisar: 14/);
  assert.strictEqual((all.match(/^### `/gm) || []).length, 14);
  assert.match(all, /## Resumen y prioridades/);
  assert.match(all, /pruebas ni un escáner de dependencias; esos resultados quedan NO VERIFICADOS/);
  assert.doesNotMatch(all, /Todo bastante bien/);
  assert.match(all, /## Omitidos/);
  assert.strictEqual(r.highlights, 14);
  assert.strictEqual(highlights(['### `a.py`\n- [alta] x L1\n- [baja] y']).length, 1);
});

test('se puede pausar y continuar sin repetir ni saltarse archivos', async () => {
  const root = proyecto();
  const log = [];
  const token = { isCancellationRequested: false };
  const d = deps(log, { failAt: 1, token });
  const r1 = await runAudit({ root, report: 'informes/b.md', token, deps: d.deps });
  assert.strictEqual(r1.paused, true);
  assert.ok(r1.next > 0 && r1.next < 14);
  token.isCancellationRequested = false;
  const r2 = await runAudit({ root, report: 'informes/b.md', token, deps: d.deps });
  assert.strictEqual(r2.done, true);
  const reviewed = log.flat();
  assert.strictEqual(reviewed.length, 14);                 // sin repetir
  assert.strictEqual(new Set(reviewed).size, 14);          // sin saltarse
  assert.strictEqual((d.report.join('\n').match(/# Auditoría archivo por archivo/g) || []).length, 1);
});

test('un estado de auditoría manipulado (archivos fuera de la carpeta) se descarta y se empieza de cero', async () => {
  const root = proyecto();
  const log = [];
  const d = deps(log);
  const { stateFile } = require('../audit');
  const sf = stateFile(root, 'informes/c.md', d.deps.stateDir);
  fs.mkdirSync(path.dirname(sf), { recursive: true });
  fs.writeFileSync(sf, JSON.stringify({ root, report: 'informes/c.md', files: ['C:/Windows/win.ini', path.join(root, '.env')], next: 0, highlights: [], done: false }));
  const r = await runAudit({ root, report: 'informes/c.md', deps: d.deps });
  assert.strictEqual(r.total, 14);
  assert.ok(!log.flat().some((f) => /win\.ini|\.env/.test(f)));
});

test('verificación: cada [alta] contra el código citado; el resumen solo usa las reales y el resto va a descartadas', async () => {
  const root = proyecto();
  fs.mkdirSync(path.join(root, '.eolfi'));
  fs.writeFileSync(path.join(root, '.eolfi', 'auditoria.md'), 'Los títulos ya se sanean con safe_title.');
  const prompts = [];
  const report = [];
  const deps = {
    stateDir: fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-audit-st-')), isSecretPath,
    complete: async (prompt) => {
      prompts.push(prompt);
      if (/VERIFICADOR/.test(prompt)) {
        const n = (prompt.match(/### Hallazgo \d+/g) || []).length;
        return JSON.stringify(Array.from({ length: n }, (_, k) => ({ id: k + 1, veredicto: k % 3 === 0 ? 'REAL' : k % 3 === 1 ? 'FALSO' : 'DISEÑO', motivo: `motivo ${k + 1}` })));
      }
      const files = [...prompt.matchAll(/===== ARCHIVO: (\S+)/g)].map((m) => m[1]);
      return files.map((f) => `### \`${f}\`\n- **Mejoras:**\n  - [alta] revisar ${f} L1`).join('\n\n');
    },
    append: async (_p, c) => { report.push(c); }, open: async () => {}, progress: () => {}, say: () => {},
  };
  const r = await runAudit({ root, report: 'informes/v.md', deps });
  assert.strictEqual(r.highlights, 14);
  assert.strictEqual(r.real + r.falsos + r.diseno + r.no_verificado, 14);
  assert.ok(r.real >= 4 && r.falsos >= 4 && r.diseno >= 4);
  const all = report.join('\n');
  assert.match(all, /## Verificación de las mejoras de prioridad alta/);
  assert.match(all, /\*\*\d+ reales\*\*, \d+ falsos positivos, \d+ decisiones de diseño y \d+ no verificados/);
  assert.match(all, /### Descartadas al verificar[\s\S]*Falso positivo[\s\S]*Motivo: motivo/);
  assert.ok(prompts.find((p) => /===== ARCHIVO/.test(p)).includes('safe_title'));     // contexto en cada lote
  const ver = prompts.find((p) => /VERIFICADOR/.test(p));
  assert.match(ver, /safe_title/);                                                     // y en la verificación
  assert.match(ver, /\s+1\| /);                                                         // con el código real citado
  assert.ok(!prompts.some((p) => /Resumen y prioridades/.test(p))); // el resumen es determinista, no otra salida libre del modelo
});

test('verificación: veredictos ilegibles o ausentes quedan NO VERIFICADO', async () => {
  const { verifyHighlights, parseVerdicts } = require('../audit');
  assert.deepStrictEqual(parseVerdicts('bla [{"id":1,"veredicto":"FALSO","motivo":"x"}] bla'), [{ id: 1, veredicto: 'FALSO', motivo: 'x' }]);
  assert.deepStrictEqual(parseVerdicts('sin json'), []);
  const out = await verifyHighlights({ root: os.tmpdir(), items: ['`a.py`: [alta] x L1', '`b.py`: [alta] y'], complete: async () => 'no sé' });
  assert.deepStrictEqual(out.map((v) => v.veredicto), ['NO_VERIFICADO', 'NO_VERIFICADO']);
});

test('auditorías pausadas invalidan veredictos guardados con reglas antiguas', async () => {
  const root = proyecto();
  const report = 'informes/antigua.md';
  const log = [];
  const d = deps(log);
  const { stateFile } = require('../audit');
  const files = inventory(root, { isSecretPath }).files.map((f) => f.path);
  const sf = stateFile(root, report, d.deps.stateDir);
  fs.mkdirSync(path.dirname(sf), { recursive: true });
  fs.writeFileSync(sf, JSON.stringify({ root, report, files, skipped: [], next: files.length, highlights: ['`src/app.js`: [alta] exposición de secreto L1'], verified: [{ h: '`src/app.js`: [alta] exposición de secreto L1', veredicto: 'REAL', motivo: 'regla antigua' }], verificationVersion: 1, done: false }));
  d.deps.complete = async (prompt) => /VERIFICADOR/.test(prompt) ? 'respuesta inválida' : '';
  const result = await runAudit({ root, report, deps: d.deps });
  assert.strictEqual(result.real, 0);
  assert.strictEqual(result.no_verificado, 1);
  assert.match(d.report.join('\n'), /NO VERIFICADO/);
});

test('encabezados sin comillas invertidas del modelo se normalizan a «### `ruta`»', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-audit-h-'));
  fs.mkdirSync(path.join(root, 'src'));
  fs.writeFileSync(path.join(root, 'src', 'run.js'), 'exec(x)\n');
  const d = deps([]);
  d.deps.complete = async () => '### src/run.js\n- **Propósito:** x';
  await runAudit({ root, report: 'informes/h.md', deps: d.deps });
  assert.match(d.report.join('\n'), /### `src\/run\.js`/);
});
