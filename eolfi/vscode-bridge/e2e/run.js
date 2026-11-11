// Prueba e2e DENTRO de un VS Code real (code --extensionTestsPath): activa la extensión, inicia sesión con un
// código del servidor de Eolfi y usa el manejador del chat con un stream CONGELADO como el de VS Code, con la API
// real (sin modelo de IA: en un perfil temporal no hay sesión del asistente, y el Chat no envía nada sin modelo).
'use strict';
const vscode = require('vscode');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');

const OUT = process.env.EOLFI_E2E_OUT || path.join(os.tmpdir(), 'eolfi-e2e.json');
const TARGET = process.env.EOLFI_E2E_TARGET || '';

function panel(method, p) {
  return new Promise((resolve, reject) => {
    const r = http.request({ host: '127.0.0.1', port: 8777, path: p, method, headers: { 'X-Eolfi': '1', 'Content-Type': 'application/json' } },
      (s) => { let b = ''; s.on('data', (d) => (b += d)); s.on('end', () => { try { resolve(JSON.parse(b)); } catch { resolve(b); } }); });
    r.on('error', reject);
    r.end('{}');
  });
}

// Como el ChatResponseStream de VS Code: métodos de solo lectura, no configurables, objeto congelado.
function frozenStream() {
  const rec = { md: '', progress: [], buttons: [], refs: [] };
  const s = {};
  const fns = { markdown: (t) => { rec.md += typeof t === 'string' ? t : t.value; }, progress: (t) => rec.progress.push(t),
    button: (b) => rec.buttons.push(b), reference: (u) => rec.refs.push(String(u)), anchor: () => {} };
  for (const [k, fn] of Object.entries(fns)) Object.defineProperty(s, k, { value: fn, writable: false, configurable: false, enumerable: true });
  return [Object.freeze(s), rec];
}

async function run() {
  const res = { steps: [] };
  const step = (name, ok, detail = '') => { res.steps.push({ name, ok: !!ok, detail: String(detail).slice(0, 500) }); };
  const started = Date.now();
  const token = { isCancellationRequested: false, onCancellationRequested: () => ({ dispose() {} }) };
  try {
    const ext = vscode.extensions.getExtension('eolfi.eolfi-vscode-bridge');
    const api = await ext.activate();
    step('extensión activa', ext.isActive, ext.extensionPath);
    const cmds = await vscode.commands.getCommands(true);
    step('comandos registrados', ['eolfi.login', 'eolfi.chatHelp', 'eolfi.toggleMode', 'eolfi.undoJournal'].every((c) => cmds.includes(c)));
    const h = api && api.chatHandler;
    step('manejador del chat expuesto', typeof h === 'function');

    const [s0, r0] = frozenStream();
    await h({ command: 'ayuda', prompt: '' }, { history: [] }, s0, token);
    step('sin sesión: pide iniciar sesión (stream congelado)', /inicia sesión/.test(r0.md), r0.md);

    const before = new Set(((await panel('GET', '/api/clients')).clients || []).map((c) => c.id));
    const { code } = await panel('POST', '/api/clients/pair');
    await vscode.commands.executeCommand('eolfi.login', code);
    step('sesión iniciada con el código', true);

    const [s1, r1] = frozenStream();
    await h({ command: 'ayuda', prompt: '' }, { history: [] }, s1, token);
    step('/ayuda responde', /tu agente de ingeniería inversa/.test(r1.md) && /Modos de trabajo/.test(r1.md), `${r1.md.length} caracteres`);
    step('/ayuda: botón del panel', r1.buttons.some((b) => b.command === 'eolfi.openPanel'));

    if (TARGET) {
      const [s2, r2] = frozenStream();
      const t0 = Date.now();
      await h({ command: 'analizar', prompt: TARGET }, { history: [] }, s2, token);
      step('/analizar con el servidor real', /Objetivo:/.test(r2.md), `${((Date.now() - t0) / 1000).toFixed(1)} s · ${r2.md.slice(0, 300)}`);
      const [s3, r3] = frozenStream();
      await h({ command: 'incognitas', prompt: '' }, { history: [] }, s3, token);
      step('/incognitas tras analizar', r3.md.length > 0 && !/Aún no hay análisis/.test(r3.md), r3.md.slice(0, 200));
    }

    const [s4, r4] = frozenStream();
    await h({ prompt: '¿qué hicimos?' }, { history: [] }, s4, token);
    // Sin Copilot: responde el modelo local (Eolas / llama.cpp, O14) o, si no hay ninguno, avisa; nunca un error.
    step('pregunta libre sin Copilot: responde el modelo local o avisa, sin romperse',
      /modelo de IA|modelo local/.test(r4.md) || (r4.md.trim().length > 20 && !/⚠️|Error:|excepción/i.test(r4.md)), r4.md);

    const [s5, r5] = frozenStream();
    await h({ command: 'historial', prompt: 'ayuda' }, { history: [] }, s5, token);
    step('/historial encuentra lo de esta prueba', /Historial/.test(r5.md) && /\/ayuda/.test(r5.md), r5.md.slice(0, 300));

    const [s6, r6] = frozenStream();
    await h({ command: 'analizar', prompt: path.join(os.homedir(), '.eolfi', '.env') }, { history: [] }, s6, token);
    step('secretos: /analizar de un .env bloqueado (exista o no)', /guarda secretos/.test(r6.md), r6.md);

    await vscode.commands.executeCommand('eolfi.logout');
    // La vinculación de la prueba no se queda en el servidor.
    const { clients } = await panel('GET', '/api/clients');
    // Solo el cliente que creó ESTA prueba: no estaba antes y se creó después de empezar.
    const mine = clients.filter((c) => !before.has(c.id) && c.created * 1000 >= started - 5000);
    for (const c of mine) await panel('DELETE', `/api/clients?id=${c.id}`);
    step('cierre de sesión y vinculación de prueba revocada', mine.length === 1, `${mine.length} revocadas`);
  } catch (e) {
    step('excepción', false, e.stack || e.message);
  }
  fs.writeFileSync(OUT, JSON.stringify(res, null, 2));
}

module.exports = { run };
