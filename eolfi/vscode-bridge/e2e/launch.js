// Lanza la prueba e2e en un VS Code real con un perfil temporal (no toca el tuyo) y muestra el resultado.
// Uso: node e2e/launch.js [archivo-a-analizar]     (necesita «python -m eolfi serve» arrancado)
'use strict';
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const ext = path.resolve(__dirname, '..');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-e2e-'));
const out = path.join(tmp, 'resultado.json');
// Historial, puente y auditorías temporales: la prueba no toca los tuyos.
const env = { ...process.env, EOLFI_E2E_OUT: out, EOLFI_E2E_TARGET: process.argv[2] || '', EOLFI_HISTORY_FILE: path.join(tmp, 'historial.jsonl'),
  // Su propio archivo del puente: la prueba no pisa ni borra el de tu VS Code.
  EOLFI_VSCODE_BRIDGE_FILE: path.join(tmp, 'vscode-bridge.json'), EOLFI_AUDIT_DIR: path.join(tmp, 'audits') };
const args = ['--user-data-dir', path.join(tmp, 'ud'), `--extensionDevelopmentPath=${ext}`,
  `--extensionTestsPath=${path.join(__dirname, 'run.js')}`, '--disable-workspace-trust', '--skip-welcome', '--skip-release-notes',
  path.resolve(ext, '..', '..')];
const q = (a) => (/[\s"]/.test(a) ? `"${a.replace(/"/g, '\\"')}"` : a);
spawn(process.platform === 'win32' ? `code.cmd ${args.map(q).join(' ')}` : 'code', process.platform === 'win32' ? [] : args,
  { env, stdio: 'ignore', shell: process.platform === 'win32' }).unref();

// El perfil temporal de VS Code (~30 MB) se borra al acabar; la instancia de prueba tarda un poco en soltarlo.
function cleanup() {
  for (let i = 0; i < 20; i++) {
    try { fs.rmSync(tmp, { recursive: true, force: true }); return; } catch { const end = Date.now() + 500; while (Date.now() < end) { /* espera */ } }
  }
  console.error(`No se pudo borrar ${tmp} (VS Code aún lo usa): bórralo a mano si quieres.`);
}

const t0 = Date.now();
const timer = setInterval(() => {
  if (fs.existsSync(out)) {
    clearInterval(timer);
    const { steps } = JSON.parse(fs.readFileSync(out, 'utf8'));
    for (const s of steps) console.log(`${s.ok ? 'OK   ' : 'FALLO'} ${s.name}${s.detail ? ` · ${s.detail.replace(/\s+/g, ' ').slice(0, 120)}` : ''}`);
    const bad = steps.filter((s) => !s.ok).length;
    console.log(bad ? `\n${bad} fallos` : `\nTodo bien (${steps.length} pasos)`);
    cleanup();
    process.exit(bad ? 1 : 0);
  }
  if (Date.now() - t0 > 300000) { console.error('Sin resultado en 5 minutos'); cleanup(); process.exit(2); }
}, 2000);
