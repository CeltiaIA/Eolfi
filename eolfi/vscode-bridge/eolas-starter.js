'use strict';
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const { httpFetch } = require('./local-model');

const DEFAULT_LAUNCHER = 'D:\\celtiaia\\launch-eolas.ps1';
const DEFAULT_URL = 'http://127.0.0.1:11435';
const DEFAULT_MODEL = 'gemma-4-12b-it:latest';

function makeEolasStarter({ launcher = DEFAULT_LAUNCHER, powershell = 'powershell.exe', endpoint = DEFAULT_URL,
  model = DEFAULT_MODEL, spawnFn = spawn, fetchFn = httpFetch, launchMs = 135000, readyMs = 30000, pollMs = 500 } = {}) {
  let active = false;
  let starting = null;

  function plan() { return { exe: launcher, model }; }

  async function hasModel() {
    try {
      const r = await fetchFn(`${endpoint}/api/tags`);
      if (!r?.ok) return false;
      const data = await r.json();
      return Array.isArray(data?.models) && data.models.some((m) => (m?.name || m?.model) === model);
    } catch { return false; }
  }

  async function waitForModel() {
    const deadline = Date.now() + readyMs;
    while (Date.now() < deadline) {
      if (await hasModel()) { active = true; return endpoint; }
      await new Promise((resolve) => setTimeout(resolve, pollMs));
    }
    throw new Error(`Eolas no anuncia ${model} en ${endpoint} tras el autoarranque`);
  }

  async function start() {
    if (starting) return starting;
    starting = (async () => {
      if (!launcher || !fs.existsSync(launcher)) throw new Error(`no encuentro el lanzador Eolas: ${launcher}`);
      await new Promise((resolve, reject) => {
        let child;
        let settled = false;
        const finish = (error) => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          error ? reject(error) : resolve();
        };
        const timer = setTimeout(() => {
          try { child?.kill(); } catch { /* el proceso pudo terminar */ }
          finish(new Error(`el lanzador Eolas no terminó en ${Math.round(launchMs / 1000)} s`));
        }, launchMs);
        timer.unref?.();
        try {
          child = spawnFn(powershell, ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', launcher,
            '-Backend', 'llama', '-EolasPort', new URL(endpoint).port || '11435', '-NoBrowser', '-Detach'],
          { windowsHide: true, stdio: 'ignore' });
          child.once('error', (e) => finish(new Error(`no se pudo ejecutar el lanzador Eolas: ${e.message}`)));
          child.once('close', (code) => finish(code === 0 ? null : new Error(`el lanzador Eolas terminó con código ${code}`)));
        } catch (e) { finish(new Error(`no se pudo ejecutar el lanzador Eolas: ${e.message}`)); }
      });
      return waitForModel();
    })();
    try { return await starting; }
    finally { starting = null; }
  }

  // CELTIAIA owns the detached supervisor; closing/reloading VS Code must not stop Eolas.
  return { plan, start, running: () => active, touch: () => {}, stop: () => { active = false; } };
}

module.exports = { makeEolasStarter, DEFAULT_LAUNCHER, DEFAULT_URL, DEFAULT_MODEL };
