'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { plan, formatPlan, gitState, gitignoredDirs } = require('../checks');

// Réplica reducida de D:\celtiaia: package.json raíz sin dependencias, subproyecto Fios con lockfile y node_modules
// (con frida dentro), dos módulos Go, runtime/ ignorado por git y un repositorio sin commits.
function celtiaia() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-checks-'));
  const w = (rel, text) => { const p = path.join(root, rel); fs.mkdirSync(path.dirname(p), { recursive: true }); fs.writeFileSync(p, text); };
  w('package.json', JSON.stringify({ name: 'raiz', scripts: { test: 'node --test' } }));
  w('test/a.test.mjs', '');
  w('.gitignore', 'node_modules/\nruntime/\nmodels/**\n*.log\n!.env.example\n');
  w('go.mod', 'module celtiaia\n\ngo 1.22\n');
  w('Eolas Base/go.mod', 'module eolas-base\n');
  w('scripts/fios/package.json', JSON.stringify({ name: 'fios', dependencies: { electron: '^45' } }));
  w('scripts/fios/package-lock.json', '{}');
  w('scripts/fios/node_modules/frida/package.json', JSON.stringify({ dependencies: { x: '1' } }));
  w('runtime/candidato/package.json', JSON.stringify({ dependencies: { y: '1' } }));
  w('runtime/candidato/bridge/x.py', 'import os');
  w('.git/HEAD', 'ref: refs/heads/main\n');
  return root;
}

test('comprobaciones: encuentra subproyectos y no entra en node_modules ni en lo ignorado por git', () => {
  const p = plan(celtiaia());
  const dirs = p.projects.map((x) => `${x.kind}:${x.dir}`).sort();
  assert.deepStrictEqual(dirs, ['go:.', 'go:Eolas Base', 'node:.', 'node:scripts/fios']);
  assert.ok(p.excluded.includes('runtime'));
  assert.ok(p.excluded.includes('scripts/fios/node_modules'));
});

test('comprobaciones: npm audit solo donde hay dependencias; sin pedir lockfile a un package.json vacío', () => {
  const p = plan(celtiaia());
  const audits = p.steps.filter((s) => s.herramienta === 'auditoría de dependencias');
  assert.deepStrictEqual(audits.map((s) => [s.carpeta, s.orden]), [['scripts/fios', 'npm audit --omit=dev']]);
  assert.ok(p.notes.some((n) => /`\.\/package\.json` no declara dependencias/.test(n)));
  assert.ok(!p.notes.some((n) => /lockfile: genera/.test(n)));
});

test('comprobaciones: órdenes de pruebas válidas (npm test, go test por módulo) y nunca «--json»', () => {
  const p = plan(celtiaia());
  const tests = p.steps.filter((s) => /pruebas/.test(s.herramienta)).map((s) => [s.carpeta, s.orden]);
  assert.deepStrictEqual(tests, [['.', 'npm test'], ['.', 'go test ./...'], ['Eolas Base', 'go test ./...']]);
  assert.ok(p.steps.every((s) => !/--json/.test(s.orden)));
});

test('comprobaciones: bandit, ruff y semgrep excluyen dependencias y carpetas ignoradas', () => {
  const p = plan(celtiaia());
  const bandit = p.steps.find((s) => s.herramienta.startsWith('Bandit')).orden;
  assert.match(bandit, /\*\/node_modules\/\*/);
  assert.match(bandit, /\.\/runtime\/\*/);
  assert.match(p.steps.find((s) => s.herramienta.startsWith('Ruff')).orden, /--extend-exclude "[^"]*runtime/);
  assert.match(p.steps.find((s) => s.herramienta.startsWith('Semgrep')).orden, /--exclude node_modules/);
});

test('comprobaciones: avisa de un repositorio git sin commits y lo reconoce cuando los hay', () => {
  const root = celtiaia();
  assert.deepStrictEqual(gitState(root), { repo: true, branch: 'main', commits: false });
  const text = formatPlan(plan(root));
  assert.match(text, /SIN commits/);
  assert.match(text, /NO EVALUADA/);
  fs.mkdirSync(path.join(root, '.git/refs/heads'), { recursive: true });
  fs.writeFileSync(path.join(root, '.git/refs/heads/main'), 'abc\n');
  assert.strictEqual(gitState(root).commits, true);
  fs.rmSync(path.join(root, '.git/refs'), { recursive: true });
  fs.writeFileSync(path.join(root, '.git/packed-refs'), '# pack-refs\nabc refs/heads/main\n');
  assert.strictEqual(gitState(root).commits, true);
  assert.deepStrictEqual(gitState(fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-nogit-'))), { repo: false });
});

test('comprobaciones: lee solo las carpetas simples del .gitignore', () => {
  const root = celtiaia();
  assert.deepStrictEqual(gitignoredDirs(root), ['node_modules', 'runtime', 'models']);
});

test('comprobaciones: subproyecto con dependencias y sin lockfile ni node_modules', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-checks-'));
  fs.writeFileSync(path.join(root, 'package.json'), JSON.stringify({ dependencies: { a: '1' }, scripts: { test: 'echo "Error: no test specified" && exit 1' } }));
  const p = plan(root);
  assert.ok(p.notes.some((n) => /no tiene lockfile/.test(n)));
  assert.ok(p.notes.some((n) => /no tiene node_modules/.test(n)));
  assert.ok(!p.steps.some((s) => s.orden === 'npm test'));
});
