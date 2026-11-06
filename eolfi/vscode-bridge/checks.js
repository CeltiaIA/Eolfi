// Plan de comprobaciones automáticas de una carpeta, dirigido por Eolfi y no por el modelo: encuentra TODOS los
// subproyectos (package.json, go.mod, pyproject…), mira el estado de git y propone las órdenes correctas para cada uno,
// con las carpetas de dependencias y compilados excluidas. Así el agente no inventa opciones (`node --test --json`),
// no audita solo la raíz, no llena el informe con hallazgos de node_modules y puede decir el alcance real.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { SKIP_DIRS } = require('./audit');

const MAX_DEPTH = 6;
const MAX_DIRS = 20000;
// Carpetas que nunca son código propio (además de SKIP_DIRS) para los escáneres.
const SCAN_EXCLUDE = ['node_modules', '.git', '.venv', 'venv', '__pycache__', 'dist', 'build', 'out', 'target', 'vendor',
  'third_party', 'coverage', '.next', '.gocache'];

// Carpetas del .gitignore de la raíz (solo las entradas simples: «runtime/», «projects/», «models/**»).
function gitignoredDirs(root) {
  let text = '';
  try { text = fs.readFileSync(path.join(root, '.gitignore'), 'utf8'); } catch { return []; }
  const out = [];
  for (let line of text.split(/\r?\n/)) {
    line = line.trim();
    if (!line || line.startsWith('#') || line.startsWith('!')) continue;
    line = line.replace(/\/\*\*$/, '/').replace(/^\//, '');
    if (!line.endsWith('/') || /[*?[\]]/.test(line)) continue;
    out.push(line.slice(0, -1).replace(/\\/g, '/'));
  }
  return out;
}

function readJson(file) { try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return null; } }
function exists(p) { try { fs.accessSync(p); return true; } catch { return false; } }

// Estado de git: ¿hay repositorio? ¿la rama actual tiene algún commit?
function gitState(root) {
  const dir = path.join(root, '.git');
  let st;
  try { st = fs.statSync(dir); } catch { return { repo: false }; }
  if (!st.isDirectory()) return { repo: true, branch: null, commits: null };   // worktree o submódulo: no se mira más
  let head = '';
  try { head = fs.readFileSync(path.join(dir, 'HEAD'), 'utf8').trim(); } catch { return { repo: true, branch: null, commits: null }; }
  const m = /^ref:\s*(refs\/heads\/(.+))$/.exec(head);
  if (!m) return { repo: true, branch: null, commits: true };   // HEAD separado: apunta a un commit
  let packed = '';
  try { packed = fs.readFileSync(path.join(dir, 'packed-refs'), 'utf8'); } catch { /* sin packed-refs */ }
  const commits = exists(path.join(dir, ...m[1].split('/'))) || packed.split('\n').some((l) => l.trim().endsWith(` ${m[1]}`));
  return { repo: true, branch: m[2], commits };
}

function discover(root) {
  const base = path.resolve(root);
  const ignored = new Set(gitignoredDirs(base));
  const projects = [];
  const skippedDirs = new Set();
  let seen = 0;
  const walk = (dir, depth) => {
    if (depth > MAX_DEPTH || ++seen > MAX_DIRS) return;
    let entries;
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    const names = new Set(entries.filter((e) => e.isFile()).map((e) => e.name));
    const rel = path.relative(base, dir).replace(/\\/g, '/') || '.';
    if (names.has('package.json')) {
      const pkg = readJson(path.join(dir, 'package.json')) || {};
      const deps = Object.keys(pkg.dependencies || {}).length + Object.keys(pkg.devDependencies || {}).length
        + Object.keys(pkg.optionalDependencies || {}).length;
      const lock = ['package-lock.json', 'npm-shrinkwrap.json', 'yarn.lock', 'pnpm-lock.yaml', 'bun.lockb'].find((f) => names.has(f)) || null;
      const testScript = pkg.scripts && typeof pkg.scripts.test === 'string' && !/no test specified/i.test(pkg.scripts.test) ? pkg.scripts.test : null;
      projects.push({ kind: 'node', dir: rel, deps, lock, testScript, nodeModules: exists(path.join(dir, 'node_modules')) });
    }
    if (names.has('go.mod')) {
      let mod = '';
      try { mod = (/^module\s+(\S+)/m.exec(fs.readFileSync(path.join(dir, 'go.mod'), 'utf8')) || [])[1] || ''; } catch { /* ilegible */ }
      projects.push({ kind: 'go', dir: rel, module: mod });
    }
    const py = ['pyproject.toml', 'requirements.txt', 'setup.py', 'setup.cfg'].filter((f) => names.has(f));
    if (py.length) projects.push({ kind: 'python', dir: rel, files: py, tests: exists(path.join(dir, 'tests')) || exists(path.join(dir, 'test')) || names.has('pytest.ini') });
    if (names.has('Cargo.toml')) projects.push({ kind: 'rust', dir: rel });
    for (const e of entries) {
      if (!e.isDirectory()) continue;
      const childRel = rel === '.' ? e.name : `${rel}/${e.name}`;
      if (SKIP_DIRS.has(e.name.toLowerCase()) || e.name.endsWith('.egg-info') || ignored.has(childRel)) {
        if (!['.git'].includes(e.name)) skippedDirs.add(childRel);
        continue;
      }
      walk(path.join(dir, e.name), depth + 1);
    }
  };
  walk(base, 0);
  return { projects, skippedDirs: [...skippedDirs].sort(), git: gitState(base), truncated: seen > MAX_DIRS };
}

// Patrones de exclusión para los escáneres (código de terceros, compilados y lo ignorado por git).
function excludes(skippedDirs) {
  const names = new Set(SCAN_EXCLUDE);
  const paths = skippedDirs.filter((d) => !SCAN_EXCLUDE.includes(path.basename(d)));
  return { names: [...names], paths };
}

function plan(root) {
  const d = discover(root);
  const ex = excludes(d.skippedDirs);
  const steps = [];
  const notes = [];
  const add = (herramienta, carpeta, orden, por_que) => steps.push({ herramienta, carpeta, orden, por_que });

  if (!d.git.repo) notes.push('No es un repositorio git: no hay historial para deshacer cambios. Recomienda `git init` y un primer commit.');
  else if (d.git.commits === false) notes.push(`Hay repositorio git pero la rama «${d.git.branch}» NO tiene ningún commit: no hay historial. Es una prioridad alta del informe.`);
  if (d.git.repo) add('git', '.', 'git status --short', 'cambios sin guardar y archivos sin versionar');

  for (const p of d.projects.filter((x) => x.kind === 'node')) {
    if (!p.deps) notes.push(`\`${p.dir}/package.json\` no declara dependencias: no hay nada que auditar con npm ni hace falta lockfile.`);
    else if (p.lock && p.lock !== 'package-lock.json' && p.lock !== 'npm-shrinkwrap.json') add('auditoría de dependencias', p.dir, `${p.lock.split('.')[0].replace('-lock', '')} audit`, `dependencias con ${p.lock}`);
    else if (p.lock) add('auditoría de dependencias', p.dir, 'npm audit --omit=dev', `${p.deps} dependencias declaradas con ${p.lock}`);
    else notes.push(`\`${p.dir}\` tiene ${p.deps} dependencias y no tiene lockfile: genera uno con \`npm install --package-lock-only\` (escribe package-lock.json; pide permiso) y luego \`npm audit\`.`);
    if (p.testScript) add('pruebas JS/TS', p.dir, 'npm test', `script test: ${p.testScript}`);
    else if (exists(path.join(root, p.dir, 'test')) || exists(path.join(root, p.dir, 'tests'))) add('pruebas JS/TS', p.dir, 'node --test', 'carpeta de pruebas sin script test');
    if (p.deps && !p.nodeModules) notes.push(`\`${p.dir}\` no tiene node_modules instalado: sus pruebas fallarán hasta ejecutar \`npm ci\`.`);
  }
  for (const p of d.projects.filter((x) => x.kind === 'go')) add('pruebas Go', p.dir, 'go test ./...', `módulo ${p.module || '(sin nombre)'}`);
  for (const p of d.projects.filter((x) => x.kind === 'rust')) add('pruebas Rust', p.dir, 'cargo test', 'Cargo.toml');
  const pyProjects = d.projects.filter((x) => x.kind === 'python');
  for (const p of pyProjects) {
    if (p.tests) add('pruebas Python', p.dir, 'python -m pytest -q', 'carpeta de pruebas');
    if (p.files.includes('requirements.txt')) add('auditoría de dependencias', p.dir, 'pip-audit -r requirements.txt', 'requirements.txt');
  }
  const globs = [...ex.names.map((n) => `*/${n}/*`), ...ex.paths.map((x) => `./${x}/*`)];
  add('Bandit (seguridad Python)', '.', `bandit -r . -q -x "${globs.join(',')}"`, 'solo código propio: excluye dependencias, compilados y lo ignorado por git');
  add('Ruff (calidad Python)', '.', `ruff check . --extend-exclude "${[...ex.names, ...ex.paths].join(',')}"`, 'solo código propio');
  add('Semgrep (seguridad multilenguaje)', '.', `semgrep scan --config auto --metrics=off ${[...ex.names, ...ex.paths].map((x) => `--exclude ${x}`).join(' ')}`, 'opcional; si no está instalado, anótalo como «no evaluado»');
  return { root: path.resolve(root), git: d.git, projects: d.projects, excluded: d.skippedDirs, steps, notes, truncated: d.truncated };
}

const RULES = [
  'CÓMO INFORMAR (obligatorio):',
  '- Usa EXACTAMENTE estas órdenes, cada una en su carpeta (parámetro «carpeta» de eolfi_terminal). No añadas opciones que no existen (p. ej. «node --test --json» no existe).',
  '- Cada sección del informe dice su alcance real: qué carpetas o módulos, cuántas pruebas (pasan/fallan) y qué quedó sin ejecutar.',
  '- Si una herramienta no está instalada o falla, la parte que cubría queda «NO EVALUADA». Nunca concluyas «sin vulnerabilidades» sin haber ejecutado la auditoría de dependencias y un escáner sobre el código propio.',
  '- Si eolfi_terminal responde «No ejecutado: bloqueado…», lo bloqueó Eolfi (di el motivo); si es un error de Windows/SmartScreen/AppLocker, dilo así. No los confundas.',
  '- Los hallazgos en dependencias de terceros (node_modules, vendor…) no son del proyecto: no los mezcles con los del código propio.',
  '- Pon al principio del informe los AVISOS de arriba (git sin commits, pruebas que fallan, dependencias sin auditar).',
];

function formatPlan(p) {
  const kinds = { node: 'Node', go: 'Go', python: 'Python', rust: 'Rust' };
  return [
    `PLAN DE COMPROBACIONES de ${p.root}`,
    `Git: ${!p.git.repo ? 'no es repositorio' : p.git.commits === false ? `repositorio SIN commits (rama ${p.git.branch})` : `repositorio${p.git.branch ? ` (rama ${p.git.branch})` : ''}`}`,
    `Subproyectos (${p.projects.length}): ${p.projects.map((x) => `${kinds[x.kind]} en ${x.dir}${x.kind === 'node' ? ` (${x.deps} deps, lock: ${x.lock || 'no'})` : ''}`).join('; ') || 'ninguno'}`,
    `Excluido de los escáneres: ${p.excluded.slice(0, 40).join(', ') || 'nada'}${p.excluded.length > 40 ? '…' : ''}`,
    ...(p.truncated ? ['(La carpeta es muy grande: el recorrido se cortó; puede haber más subproyectos.)'] : []),
    '', 'AVISOS:', ...(p.notes.length ? p.notes.map((n) => `- ${n}`) : ['- ninguno']),
    '', 'ÓRDENES:', ...p.steps.map((s, i) => `${i + 1}. [${s.herramienta}] en «${s.carpeta}»: ${s.orden}  — ${s.por_que}`),
    '', ...RULES,
  ].join('\n');
}

module.exports = { discover, plan, formatPlan, gitState, gitignoredDirs, RULES };
