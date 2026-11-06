// Arranca un llama-server (llama.cpp) local cuando hace falta el respaldo y no hay ninguno en marcha. Solo escucha en
// 127.0.0.1; se para solo al cerrar VS Code o tras un rato sin uso, y solo para el que arrancó él.
'use strict';
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');

const SERVER_CANDIDATES = [
  path.join(os.homedir(), '.eolfi', 'tools', 'llama', 'llama-server.exe'),
  'D:\\HYDRA-BASE\\llama\\llama-server.exe',
  'D:\\HYDRA\\runtime\\llama-bin\\llama-server.exe',
  'D:\\EOLAS-BASE\\llama\\llama-server.exe',
];
const GGUF_DIRS = [path.join(os.homedir(), '.eolfi', 'models'), 'D:\\HYDRA-BASE\\.hydra\\gguf'];
const GGUF_PREFERRED = [/coder/i, /gemma-?4/i, /qwen3\.5/i, /qwen3/i, /phi-?4/i, /gemma/i, /qwen/i, /llama/i];
const QUANT_PREFERRED = [/q4_k_m/i, /q4_k_s/i, /iq4/i, /q5_k_m/i, /q6_k/i, /q8_0/i];

function findServer(candidates = SERVER_CANDIDATES, which = null) {
  for (const c of candidates) if (c && fs.existsSync(c)) return c;
  const exe = process.platform === 'win32' ? 'llama-server.exe' : 'llama-server';
  for (const dir of String(process.env.PATH || '').split(path.delimiter)) {
    const p = path.join(dir, exe);
    if (dir && fs.existsSync(p)) return p;
  }
  return which;
}

// El GGUF más adecuado para revisar código: por familia preferida y cuantización equilibrada; nada de modelos de
// imagen, vocabularios ni de prueba (< 500 MB).
function findGguf(dirs = GGUF_DIRS, { minBytes = 500 * 1024 * 1024 } = {}) {
  const all = [];
  const walk = (d, depth) => {
    let es;
    try { es = fs.readdirSync(d, { withFileTypes: true }); } catch { return; }
    for (const e of es) {
      const p = path.join(d, e.name);
      if (e.isDirectory() && depth < 3) walk(p, depth + 1);
      else if (e.isFile() && /\.gguf$/i.test(e.name) && !/vocab|mmproj|image|test|draft/i.test(p)) {
        try { const size = fs.statSync(p).size; if (size > minBytes) all.push({ path: p, size }); } catch { /* sin acceso */ }
      }
    }
  };
  for (const d of dirs) walk(d, 0);
  const rank = (f) => {
    const n = path.basename(f.path);
    const fam = GGUF_PREFERRED.findIndex((re) => re.test(n));
    const q = QUANT_PREFERRED.findIndex((re) => re.test(n));
    return [fam < 0 ? 99 : fam, q < 0 ? 99 : q, f.size];
  };
  all.sort((a, b) => { const x = rank(a), y = rank(b); return x[0] - y[0] || x[1] - y[1] || x[2] - y[2]; });
  return all[0]?.path || null;
}

function portFree(port) {
  return new Promise((resolve) => {
    const s = net.createServer().once('error', () => resolve(false)).once('listening', () => s.close(() => resolve(true)));
    s.listen(port, '127.0.0.1');
  });
}

function makeLlamaStarter({ server = '', gguf = '', firstPort = 8080, ctx = 32768, gpuLayers = null, alias: aliasOpt = '', extraArgs = [],
  config = null, idleMs = 15 * 60 * 1000, log = () => {},
  spawnFn = spawn, fetchFn = null, findServerFn = findServer, findGgufFn = findGguf, portFreeFn = portFree, readyMs = 240000 } = {}) {
  let proc = null;
  let url = null;
  let idle = null;
  const get = fetchFn || require('./local-model').httpFetch;

  function touch() {
    clearTimeout(idle);
    idle = setTimeout(() => { log('llama-server: sin uso, lo paro'); stop(); }, idleMs);
    idle.unref?.();
  }

  // Con config(): lo que diga ~/.eolfi/llamacpp.json (se lee al arrancar).
  const cfg = () => (config ? config() : {});
  function plan() {
    const c = cfg();
    const exe = c.server || server || findServerFn();
    const model = c.model || gguf || findGgufFn();
    return { exe, model };
  }

  async function start() {
    if (url && proc && proc.exitCode === null) { touch(); return url; }
    const { exe, model } = plan();
    if (!exe) throw new Error('no encuentro llama-server.exe (ajuste eolfi.fallback.llamaServer)');
    if (!model) throw new Error('no encuentro ningún modelo .gguf para revisar código (ajuste eolfi.fallback.gguf)');
    const c = cfg();
    const first = Number(c.port) || firstPort;
    let port = first;
    while (port < first + 20 && !(await portFreeFn(port))) port++;
    if (port >= first + 20) throw new Error(`no hay puerto libre entre ${first} y ${first + 19}`);
    const alias = c.alias || aliasOpt || path.basename(model).replace(/\.gguf$/i, '');
    const ngl = c.gpu_layers ?? gpuLayers;
    log(`llama-server: arrancando ${alias} en 127.0.0.1:${port}`);
    proc = spawnFn(exe, ['-m', model, '--host', '127.0.0.1', '--port', String(port), '-c', String(c.ctx || ctx), '--alias', alias, '--jinja',
      '--reasoning-format', 'deepseek', ...(ngl !== null && ngl !== undefined ? ['-ngl', String(ngl)] : []), ...(c.extra_args || extraArgs).map(String)],
      { windowsHide: true, stdio: 'ignore' });
    proc.on?.('exit', () => { proc = null; url = null; });
    const u = `http://127.0.0.1:${port}`;
    const t0 = Date.now();
    while (Date.now() - t0 < readyMs) {
      if (!proc) throw new Error('llama-server se cerró al arrancar (¿modelo demasiado grande para la memoria?)');
      try { const r = await get(`${u}/health`); if (r.ok) { url = u; touch(); return url; } } catch { /* aún cargando */ }
      await new Promise((r) => setTimeout(r, 1000));
    }
    stop();
    throw new Error(`llama-server no estuvo listo en ${Math.round(readyMs / 1000)} s`);
  }

  function stop() {
    clearTimeout(idle);
    try { proc?.kill(); } catch { /* ya parado */ }
    proc = null;
    url = null;
  }

  return { plan, start, stop, running: () => !!url, touch };
}

module.exports = { makeLlamaStarter, findServer, findGguf, SERVER_CANDIDATES };
