// Prueba e2e EN VIVO: el agente @eolfi y /auditar con el modelo local (Eolas en 127.0.0.1:11435 o llama-server)
// y con «/modelo local». Copilot es un espía: si recibe UNA sola petición, la prueba falla.
// Uso (con Eolas arrancado: «npm start» en D:\celtiaia):  node e2e/local-eolas-live.js
'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-live-local-'));
process.env.EOLFI_AUDIT_DIR = path.join(tmp, 'audits');
const { makeChatHandler } = require('../chat');
const { makeLocalModel, EOLAS_URL, EOLAS_MODEL } = require('../local-model');
const llamacfg = require('../llamacpp-config');

const proj = path.join(tmp, 'proyecto');
fs.mkdirSync(path.join(proj, 'src'), { recursive: true });
fs.writeFileSync(path.join(proj, 'notas.txt'), 'Notas del proyecto.\nLa palabra clave es CALABAZA-42.\n');
fs.writeFileSync(path.join(proj, 'src', 'suma.py'), 'def suma(a, b):\n    return a + b\n');
fs.writeFileSync(path.join(proj, 'src', 'run.js'), "const { exec } = require('child_process');\nexec('ls ' + process.argv[2]);\n");

// Copilot espía: cuenta cualquier petición.
const copilot = [];
const spy = (id) => ({ id, name: id, family: id, maxInputTokens: 100000, sendRequest: async () => { copilot.push(id); throw new Error('Copilot NO debería usarse'); } });
class TextPart { constructor(v) { this.value = v; } }
const vscode = {
  workspace: { workspaceFolders: [{ name: 'proyecto', uri: { fsPath: proj } }] },
  window: { activeTextEditor: null },
  env: {},
  Uri: { file: (p) => ({ fsPath: p, toString: () => p }) },
  LanguageModelTextPart: TextPart, LanguageModelToolCallPart: class {}, LanguageModelToolResultPart: class {},
  LanguageModelChatMessage: { User: (c) => ({ role: 'user', content: c }), Assistant: (c) => ({ role: 'assistant', content: c }) },
  lm: { selectChatModels: async () => [spy('auto'), spy('gpt-4.1'), spy('gpt-4o-mini')] },
};

const inside = (p) => (path.isAbsolute(p) ? p : path.join(proj, p));
const toolsUsed = [];
const actions = {
  read: async ({ path: p }) => { toolsUsed.push(`read ${p}`); return { path: inside(p), text: fs.readFileSync(inside(p), 'utf8') }; },
  list: async () => { toolsUsed.push('list'); return { files: ['notas.txt', 'src/suma.py', 'src/run.js'] }; },
  append: async ({ path: p, content }) => { const f = inside(p); fs.mkdirSync(path.dirname(f), { recursive: true }); fs.appendFileSync(f, `${content}\n\n`); return { appended: f }; },
  open: async () => ({}),
};
const workspaceTools = [
  { name: 'eolfi_read_file', action: 'read', description: 'Lee un archivo de texto del workspace.', inputSchema: { type: 'object', properties: { path: { type: 'string' } }, required: ['path'] } },
  { name: 'eolfi_list_files', action: 'list', description: 'Lista archivos del workspace.', inputSchema: { type: 'object', properties: { glob: { type: 'string' } } } },
];

// Solo Eolas y el modelo exacto: ni otro puerto (8090/8080) ni otro modelo, ni arranque de servidores.
const cfg = llamacfg.loadConfig({});
const url = process.env.EOLFI_LOCAL_URL || EOLAS_URL;
const wanted = process.env.EOLFI_LOCAL_MODEL || EOLAS_MODEL;
const localModel = makeLocalModel({ endpoints: [url], model: wanted, starter: null, allowStart: async () => false,
  options: (o) => llamacfg.requestOptions(cfg, o) });

function stream() {
  const rec = { md: '', progress: [] };
  return [{ markdown: (m) => { rec.md += String(m?.value ?? m); }, progress: (m) => rec.progress.push(String(m)), button: () => {}, reference: () => {}, anchor: () => {} }, rec];
}

(async () => {
  const res = [];
  const step = (name, ok, detail = '') => { res.push({ name, ok: !!ok }); console.log(`${ok ? '✓' : '✗'} ${name}${detail ? ` — ${String(detail).replace(/\s+/g, ' ').slice(0, 300)}` : ''}`); };
  const token = { isCancellationRequested: false, onCancellationRequested: () => ({ dispose() {} }) };
  const fail = (where) => { console.log(`\nRESULTADO: FALLA en «${where}». Carpeta de la prueba: ${tmp}`); process.exit(1); };
  const at = await localModel.locate().catch(() => null);
  step('API: Eolas responde y anuncia el modelo esperado', at && at.api === 'eolas' && at.model === wanted,
    at ? `${at.url} · ${at.model} (${at.api})` : localModel.diagnose().error);
  if (!at || at.api !== 'eolas' || at.model !== wanted) fail(at ? 'selección del modelo' : 'API');

  const h = makeChatHandler({ vscode, summarize: () => '', state: {}, getClient: async () => ({}), actions, workspaceTools,
    localModel, preferLocal: () => true, workMode: () => 'automatico', maxSteps: () => 8, localConfig: () => cfg });

  // 0) Respuesta directa (sin herramientas): la carga del modelo y la primera generación.
  let t0 = Date.now();
  let [s, rec] = stream();
  try {
    const r = await h({ prompt: 'Responde únicamente con la palabra: PONG' }, { history: [] }, s, token);
    step('chat: respuesta directa visible', /PONG/i.test(rec.md), `${Math.round((Date.now() - t0) / 1000)} s · ${rec.md.slice(-160)}`);
    step('chat: modelo/proveedor registrados', String(r?.metadata?.model || '').includes(wanted), r?.metadata?.model);
  } catch (e) { step('chat: respuesta directa sin errores', false, e.message); }
  if (!res.every((x) => x.ok)) fail('chat');

  // 1) Agente con herramientas: tiene que LEER notas.txt para saber la palabra clave.
  t0 = Date.now();
  [s, rec] = stream();
  try {
    const r = await h({ prompt: 'Lee el archivo notas.txt con la herramienta eolfi_read_file y dime cuál es la palabra clave. Responde solo con la palabra clave.' }, { history: [] }, s, token);
    step('agente: usó la herramienta de leer archivos', toolsUsed.some((x) => /notas\.txt/.test(x)), toolsUsed.join(', '));
    step('agente: respondió con el contenido real (CALABAZA-42)', /CALABAZA-42/.test(rec.md), rec.md.slice(-200));
    step('agente: lo hizo el modelo de Eolas', String(r?.metadata?.model || '').includes(wanted),`${r?.metadata?.model} · ${Math.round((Date.now() - t0) / 1000)} s`);
  } catch (e) { step('agente: sin errores', false, e.message); }

  // 2) /auditar de una carpeta pequeña: revisión archivo a archivo, verificación y resumen, todo en local.
  t0 = Date.now();
  [s, rec] = stream();
  try {
    await h({ command: 'auditar', prompt: proj }, { history: [] }, s, token);
    const reports = fs.existsSync(path.join(proj, 'informes')) ? fs.readdirSync(path.join(proj, 'informes')) : [];
    const text = reports.length ? fs.readFileSync(path.join(proj, 'informes', reports[0]), 'utf8') : '';
    step('auditoría: terminó', /Auditoría terminada/.test(rec.md), `${Math.round((Date.now() - t0) / 1000)} s · ${rec.md.slice(-200)}`);
    step('auditoría: una sección por archivo', /`src\/suma\.py`/.test(text) && /`src\/run\.js`/.test(text), reports[0] || 'sin informe');
    step('auditoría: con resumen y prioridades', /## Resumen y prioridades/.test(text));
  } catch (e) { step('auditoría: sin errores', false, e.message); }

  step('Copilot: 0 peticiones', copilot.length === 0, copilot.length ? `recibió ${copilot.length}: ${copilot.join(', ')}` : '');
  const ok = res.every((x) => x.ok);
  console.log(`\nRESULTADO: ${ok ? 'OK' : 'FALLA'} (${res.filter((x) => x.ok).length}/${res.length}). Carpeta de la prueba: ${tmp}`);
  process.exit(ok ? 0 : 1);
})();
