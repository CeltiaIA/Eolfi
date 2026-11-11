'use strict';

// Medición local y reproducible con llama-bench. No inicia servidores, no cambia
// el modelo configurado y usa pocos tokens para que sea una comprobación breve.
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');

function benchExecutable(server) {
  const name = process.platform === 'win32' ? 'llama-bench.exe' : 'llama-bench';
  const candidates = [
    process.env.EOLFI_LLAMA_BENCH,
    server && path.join(path.dirname(String(server)), name),
    process.platform === 'win32' && path.join('D:\\EOLAS-BASE\\llama', name),
  ].filter(Boolean);
  return candidates.find((candidate) => fs.existsSync(candidate)) || candidates[0];
}

function benchmarkPlan(config) {
  if (!config?.model || !fs.existsSync(config.model)) throw new Error('No hay un modelo GGUF local configurado.');
  const executable = benchExecutable(config.server);
  if (!fs.existsSync(executable)) throw new Error(`No se encontró llama-bench local: ${executable || 'configura eolfi.llamacpp.server'}`);
  const gpuLayers = Math.max(0, Number(config.gpu_layers) || 0);
  return {
    executable,
    model: path.resolve(config.model),
    // Tres repeticiones, prefill y generación corta: comparable y sin cargar el
    // sistema durante demasiado tiempo.
    args: ['-m', path.resolve(config.model), '-p', '128', '-n', '32', '-ngl', String(gpuLayers), '-r', '3', '-o', 'json'],
  };
}

function parseBenchmark(text) {
  const trimmed = String(text || '').trim();
  if (!trimmed) throw new Error('llama-bench no devolvió resultados.');
  try { return JSON.parse(trimmed); } catch {
    const start = trimmed.indexOf('{');
    const end = trimmed.lastIndexOf('}');
    if (start >= 0 && end > start) return JSON.parse(trimmed.slice(start, end + 1));
    throw new Error('La salida de llama-bench no contiene JSON válido.');
  }
}

function runBenchmark(plan, { timeoutMs = 10 * 60 * 1000, spawnFn = spawn } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawnFn(plan.executable, plan.args, { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '', stderr = '', done = false;
    let timer;
    const finish = (error, value) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      error ? reject(error) : resolve(value);
    };
    child.stdout?.on('data', (chunk) => { stdout += chunk; });
    child.stderr?.on('data', (chunk) => { stderr += chunk; });
    child.on('error', (error) => finish(error));
    child.on('close', (code) => {
      if (code !== 0) return finish(new Error(`llama-bench terminó con código ${code}: ${stderr.trim().slice(0, 1000)}`));
      try { finish(null, { plan, result: parseBenchmark(stdout), stderr: stderr.trim() || null }); } catch (error) { finish(error); }
    });
    timer = setTimeout(() => {
      try { child.kill(); } catch { /* el cierre reportará el error */ }
      finish(new Error(`llama-bench superó el límite de ${Math.round(timeoutMs / 60000)} minutos.`));
    }, timeoutMs);
  });
}

module.exports = { benchExecutable, benchmarkPlan, parseBenchmark, runBenchmark };
