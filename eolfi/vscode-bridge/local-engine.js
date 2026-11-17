'use strict';
// Motor local de la extensión (15/11/2026, decisión del titular: trabajar con Eolas V1 o Eolas V2).
//   eolas-v1: Eolas de CELTIAIA (127.0.0.1:11435, API tipo Ollama), con la clave que crea launch-eolas.ps1.
//   eolas-v2: llama-server de Eolfi (127.0.0.1:8090, API de OpenAI), con su propia clave (eolas-v2-starter.js).
// La elección es la misma que en la CLI y el panel (eolfi/local_gpu.py): el ajuste «eolfi.local.engine» si se ha
// fijado; si no, EOLFI_LOCAL_ENGINE; si no, ~/.eolfi/motor-local.json («python -m eolfi motor-local …»); si no,
// eolas-v2.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFile } = require('node:child_process');

const ENGINES = ['eolas-v1', 'eolas-v2'];
const DEFAULT_ENGINE = 'eolas-v2';
const ALIASES = { v1: 'eolas-v1', eolas: 'eolas-v1', 1: 'eolas-v1', v2: 'eolas-v2', 2: 'eolas-v2' };

function normalizeEngine(value) {
  const text = String(value ?? '').trim().toLowerCase().replace(/_/g, '-');
  const name = ALIASES[text] || text;
  return ENGINES.includes(name) ? name : null;
}

function engineFile(env = process.env) {
  if (env.EOLFI_MOTOR_LOCAL_FILE) return env.EOLFI_MOTOR_LOCAL_FILE;
  return path.join(env.EOLFI_HOME || path.join(os.homedir(), '.eolfi'), 'motor-local.json');
}

function localEngine({ setting = '', env = process.env, fsMod = fs } = {}) {
  const fromSetting = normalizeEngine(setting);
  if (fromSetting) return fromSetting;
  const fromEnv = normalizeEngine(env.EOLFI_LOCAL_ENGINE);
  if (fromEnv) return fromEnv;
  try {
    const saved = normalizeEngine(JSON.parse(fsMod.readFileSync(engineFile(env), 'utf8'))?.engine);
    if (saved) return saved;
  } catch { /* sin elección guardada */ }
  return DEFAULT_ENGINE;
}

// Clave de Eolas V1 (auditoría del 15/11/2026, P2-1): EOLAS_API_KEY o runtime\eolas\api.key de CELTIAIA.
function v1KeyFiles(env = process.env, platform = process.platform) {
  const files = [];
  if (env.EOLAS_HOME) files.push(path.join(env.EOLAS_HOME, 'api.key'));
  const celtiaia = env.CELTIAIA_HOME || (platform === 'win32' ? 'D:\\celtiaia' : '');
  if (celtiaia) files.push(path.join(celtiaia, 'runtime', 'eolas', 'api.key'));
  return files;
}

function v1Key({ env = process.env, fsMod = fs, platform = process.platform } = {}) {
  const wanted = String(env.EOLAS_API_KEY || '').trim();
  if (wanted) return wanted;
  for (const file of v1KeyFiles(env, platform)) {
    try {
      const key = fsMod.readFileSync(file, 'utf8').trim();
      if (key) return key;
    } catch { /* siguiente */ }
  }
  return '';
}

// Se lee en cada petición: el archivo aparece la primera vez que launch-eolas.ps1 arranca con clave.
function v1AuthHeaders(opts = {}) {
  const key = v1Key(opts);
  return key ? { Authorization: `Bearer ${key}` } : {};
}

// P1-5: antes de que Eolas V1 cargue su modelo, Eolas V2 ocioso se para con la misma guardia que usa la CLI
// («python -m eolfi.local_gpu free-for-eolas»). Si V2 está respondiendo, devuelve el motivo y no se para.
function makeFreeForEolas({ python = 'python', cwd, env = process.env, execFileFn = execFile, timeoutMs = 60000 } = {}) {
  return () => new Promise((resolve) => {
    execFileFn(python, ['-m', 'eolfi.local_gpu', 'free-for-eolas'], {
      cwd, windowsHide: true, timeout: timeoutMs,
      env: { ...env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', ...(cwd ? { PYTHONPATH: cwd } : {}) },
    }, (error, stdout) => {
      let data = null;
      try { data = JSON.parse(String(stdout || '').trim().split(/\r?\n/).pop() || 'null'); } catch { /* sin JSON */ }
      if (data && !data.error && !error) return resolve({ ok: true, ...data });
      resolve({ ok: false, error: data?.error || error?.message || 'no se pudo liberar Eolas V2' });
    });
  });
}

module.exports = { ENGINES, DEFAULT_ENGINE, normalizeEngine, engineFile, localEngine, v1KeyFiles, v1Key, v1AuthHeaders, makeFreeForEolas };
