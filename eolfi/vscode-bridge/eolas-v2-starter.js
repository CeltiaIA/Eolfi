'use strict';
// Eolas V2 para la extensión (15/11/2026, decisión del titular: todo Eolas pasa a V2 y Eolas V1, el runtime de
// CeltIA en 11435, queda parado hasta que se repare). V2 es el llama-server que gestiona Eolfi
// («python -m eolfi eolas-v2»): API de OpenAI en 127.0.0.1:<port>, con clave en un archivo junto a su
// configuración y un vigilante que lo para tras 15 minutos sin uso.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

// Alias de los perfiles Gemma por defecto (eolfi/eolas_v2.py DEFAULT_PROFILES), por si el JSON no los repite.
const DEFAULT_ALIASES = { gemma_q4: 'gemma-4-12b-it-q4_k_m:latest', gemma: 'gemma-4-12b-it-q5_k_m:latest' };
const DEFAULT_PROFILE = 'gemma';
const DEFAULT_PORT = 8090;

function v2Files(env = process.env) {
  const config = env.EOLFI_EOLAS_V2_CONFIG || path.join(os.homedir(), '.eolfi', 'eolas-v2.json');
  const base = config.replace(/\.json$/i, '');
  return { config, runtime: `${base}.runtime.json`, key: path.join(path.dirname(config), 'eolas-v2.key') };
}

function readJson(file, fsMod = fs) {
  try { return JSON.parse(fsMod.readFileSync(file, 'utf8')); } catch { return null; }
}

// Perfil, alias y URL que usará la extensión: el perfil activo de eolas-v2.json salvo que se pida otro.
function v2Target({ profile = '', env = process.env, fsMod = fs } = {}) {
  const cfg = readJson(v2Files(env).config, fsMod) || {};
  const name = String(profile || cfg.active_profile || DEFAULT_PROFILE);
  const alias = String(cfg.profiles?.[name]?.alias || DEFAULT_ALIASES[name] || '');
  const port = Number(cfg.port) || DEFAULT_PORT;
  return { profile: name, alias, url: `http://127.0.0.1:${port}` };
}

// Clave de API: EOLAS_V2_API_KEY o el archivo que crea Eolfi al arrancar V2. Se lee en cada petición, porque el
// archivo puede aparecer después (primer arranque).
function v2Key({ env = process.env, fsMod = fs } = {}) {
  const wanted = String(env.EOLAS_V2_API_KEY || '').trim();
  if (wanted) return wanted;
  try { return fsMod.readFileSync(v2Files(env).key, 'utf8').trim(); } catch { return ''; }
}

function v2AuthHeaders(opts = {}) {
  const key = v2Key(opts);
  return key ? { Authorization: `Bearer ${key}` } : {};
}

function pidAlive(pid) {
  try { process.kill(pid, 0); return true; } catch (e) { return e.code === 'EPERM'; }
}

function v2Running({ env = process.env, fsMod = fs, alive = pidAlive } = {}) {
  const record = readJson(v2Files(env).runtime, fsMod);
  const pid = Number(record?.pid) || 0;
  return pid > 0 && alive(pid);
}

// Arranca V2 con la CLI de Eolfi: «eolas-v2 start» espera a que el modelo esté listo (ready_timeout) y deja el
// vigilante de inactividad armado. No se para al cerrar VS Code: lo para el vigilante o «eolas-v2 stop».
function makeEolasV2Starter({ python = 'python', cwd, env = process.env, profile = '', spawnFn = spawn, log = () => {},
  launchMs = 330000, fsMod = fs, alive = pidAlive } = {}) {
  let active = false;
  let starting = null;
  const target = () => v2Target({ profile, env, fsMod });

  function plan() { return { exe: python, model: target().alias }; }

  async function start() {
    if (starting) return starting;
    starting = (async () => {
      const t = target();
      const args = ['-m', 'eolfi', 'eolas-v2', 'start', '--profile', t.profile];
      log(`Arrancando Eolas V2 (perfil ${t.profile}, ${t.alias}) con ${python} ${args.join(' ')}`);
      const out = await new Promise((resolve, reject) => {
        let child;
        let settled = false;
        let stdout = '';
        let stderr = '';
        const finish = (error, value) => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          error ? reject(error) : resolve(value);
        };
        const timer = setTimeout(() => {
          try { child?.kill(); } catch { /* el proceso pudo terminar */ }
          finish(new Error(`Eolas V2 no arrancó en ${Math.round(launchMs / 1000)} s`));
        }, launchMs);
        timer.unref?.();
        try {
          child = spawnFn(python, args, { cwd, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
            env: { ...env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', ...(cwd ? { PYTHONPATH: cwd } : {}) } });
          child.stdout?.on('data', (c) => { stdout += c; });
          child.stderr?.on('data', (c) => { stderr += c; });
          child.once('error', (e) => finish(new Error(`no se pudo ejecutar ${python}: ${e.message}`)));
          child.once('close', (code) => (code === 0 ? finish(null, stdout)
            : finish(new Error(`Eolas V2 no arrancó (código ${code}): ${String(stderr || stdout).trim().slice(-400)}`))));
        } catch (e) { finish(new Error(`no se pudo ejecutar ${python}: ${e.message}`)); }
      });
      let r = {};
      try { r = JSON.parse(out); } catch { /* salida sin JSON: se usa la URL configurada */ }
      active = true;
      return String(r.url || t.url);
    })();
    try { return await starting; } finally { starting = null; }
  }

  return { plan, start, running: () => active && v2Running({ env, fsMod, alive }), touch: () => {}, stop: () => { active = false; } };
}

module.exports = { makeEolasV2Starter, v2Target, v2Key, v2AuthHeaders, v2Running, v2Files, DEFAULT_ALIASES };
