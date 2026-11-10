// Extensión de VS Code: puente local entre Eolfi y los modelos de IA de VS Code (Language Model API).
// Al activarse escucha en 127.0.0.1 (puerto libre) y escribe ~/.eolfi/vscode-bridge.json con la URL y un token
// nuevo. Eolfi lo lee para usar el proveedor «copilot-vscode».
'use strict';
const vscode = require('vscode');
const http = require('node:http');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { makeHandler } = require('./core');
const { makeActions, TOOL_DEFS, isSecretPath, resolveInside } = require('./workspace');
const { makeClient, summarize } = require('./eolfi-client');
const { makeChatHandler } = require('./chat');
const { reaConfig, McpClient } = require('./rea');
const { readCodexMcpServers } = require('./codex-mcp');
const { makeAgentTools } = require('./agent-tools');
const { makeCaseTools, combineTools } = require('./case-tools');
const { makeHistory } = require('./history');
const { makeLocalModel, EOLAS_URL, EOLAS_MODEL } = require('./local-model');
const { findServer } = require('./llama-starter');
const { makeEolasStarter } = require('./eolas-starter');
const llamacfg = require('./llamacpp-config');
const lmi = require('./lm-integration');
const { splitTextFile, validateParts } = require('./file-splitter');

const FILE = process.env.EOLFI_VSCODE_BRIDGE_FILE || path.join(os.homedir(), '.eolfi', 'vscode-bridge.json');
let server = null;
let status = null;
let out = null;

function allowedTools() {
  const v = vscode.workspace.getConfiguration('eolfi').get('allowedTools');
  return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : [];
}

function writeFile(data) {
  fs.mkdirSync(path.dirname(FILE), { recursive: true });
  const tmp = `${FILE}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data), { mode: 0o600 });
  fs.renameSync(tmp, FILE);   // de una vez: Eolfi nunca lee un archivo a medias
}

function stop() {
  if (server) { server.close(); server = null; }
  try {
    if (JSON.parse(fs.readFileSync(FILE, 'utf8')).pid === process.pid) fs.rmSync(FILE, { force: true });
  } catch { /* ya no está o no es nuestro */ }
}

let panelChatHandler;
let panelChatBusy = false;

function start() {
  stop();
  const token = crypto.randomBytes(32).toString('hex');
  server = http.createServer(makeHandler({ vscode, token, getAllowedTools: allowedTools, log: (m) => out.appendLine(m),
    actions: makeActions(vscode),
    localChat: async ({ prompt, project }, token) => {
      const folders = vscode.workspace.workspaceFolders || [];
      const current = folders.length === 1 ? folders[0].uri.fsPath : null;
      if (!current || project !== current) throw Object.assign(new Error('Abre un solo proyecto y actualiza el panel.'), { status: 409 });
      if (typeof prompt !== 'string' || !prompt.trim() || prompt.length > 4000 || /^\s*\//.test(prompt)) {
        throw Object.assign(new Error('Mensaje inválido para el chat local.'), { status: 400 });
      }
      if (!panelChatHandler || panelChatBusy) throw Object.assign(new Error('Chat local ocupado o no disponible.'), { status: 409 });
      panelChatBusy = true;
      try {
        const answer = await vscode.window.showWarningMessage(
          'Eolfi recibió una tarea del panel para ' + current,
          { modal: true, detail: prompt }, 'Executar'
        );
        if (answer !== 'Executar' || token.isCancellationRequested) return { cancelled: true };
        let text = '';
        const stream = { markdown: (part) => { text += String(part?.value ?? part); }, progress: () => {},
          button: () => {}, reference: () => {}, anchor: () => {}, warning: () => {} };
        const result = await panelChatHandler({ prompt }, { history: [] }, stream, token);
        return { text, model: result?.metadata?.model, cancelled: token.isCancellationRequested };
      } finally { panelChatBusy = false; }
    } }));
  server.listen(0, '127.0.0.1', () => {
    const url = `http://127.0.0.1:${server.address().port}`;
    writeFile({ url, token, pid: process.pid, vscode: vscode.version });
    status.text = '$(comment-discussion) Eolfi';
    status.command = 'eolfi.chatHelp';
    status.tooltip = `Abrir el chat con Eolfi y su ayuda · puente en ${url} (solo este equipo)`;
    status.show();
    out.appendLine(`Puente escuchando en ${url}; credenciales en ${FILE}`);
  });
}

// -- Eolfi como herramienta de ingeniería inversa dentro de VS Code -------------------------------
let lastSubject = null;
let secrets = null;
const SECRET = 'eolfi.clientToken';

async function sessionToken() { return secrets ? secrets.get(SECRET) : undefined; }

function baseUrl() {
  const url = String(vscode.workspace.getConfiguration('eolfi').get('serverUrl') || 'http://127.0.0.1:8777');
  let u;
  try { u = new URL(url); } catch { throw new Error(`eolfi.serverUrl inválida: ${url}`); }
  if (u.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(u.hostname)) {
    throw new Error('eolfi.serverUrl debe ser una dirección de este equipo (http://127.0.0.1:…)');
  }
  return u.origin;
}

// Sin sesión no se usa nada de la extensión (ni el análisis ni el puente).
async function eolfiClient() {
  const t = await sessionToken();
  if (!t) {
    const pick = await vscode.window.showWarningMessage('Eolfi: inicia sesión para usar la extensión.', 'Iniciar sesión');
    if (pick) await vscode.commands.executeCommand('eolfi.login');
    const again = await sessionToken();
    if (!again) throw new Error('sin sesión de Eolfi');
    return makeClient(baseUrl(), again);
  }
  return makeClient(baseUrl(), t);
}

async function login(given) {
  const code = /^\d{6}$/.test(String(given || '')) ? String(given) : await vscode.window.showInputBox({
    title: 'Eolfi: iniciar sesión',
    prompt: 'Código de vinculación: en el panel de Eolfi, Proveedores → «Vincular VS Code»',
    placeHolder: '6 cifras', ignoreFocusOut: true, password: true,   // no se ve en pantalla
    validateInput: (v) => (/^\d{6}$/.test(v.trim()) ? null : 'Son 6 cifras'),
  });
  if (!code) { out.appendLine('Inicio de sesión cancelado.'); return false; }
  out.appendLine(`Canjeando el código en ${baseUrl()}…`);
  const r = await makeClient(baseUrl()).exchange(code.trim(), `VS Code (${os.hostname()})`);
  await secrets.store(SECRET, r.token);
  out.appendLine(`Sesión iniciada como «${r.name}».`);
  vscode.window.showInformationMessage('Eolfi: sesión iniciada. La extensión ya está activa.');
  start();
  showMode();
  openChat(true);
  return true;
}

async function logout() {
  await secrets.delete(SECRET);
  stop();
  showLoggedOut();
  vscode.window.showInformationMessage('Eolfi: sesión cerrada. La extensión queda inactiva hasta que vuelvas a iniciarla.');
}

// REA: el agente lo usa por MCP con tu configuración (o eolfi.rea.command / eolfi.rea.args).
function reaBridge(context) {
  const c = vscode.workspace.getConfiguration('eolfi');
  const cfg = reaConfig({ command: c.get('rea.command') || undefined, args: c.get('rea.args') });
  if (!cfg || c.get('rea.enabled') === false) return null;
  // jadx para APK: si está en la carpeta de herramientas de Eolfi, se le pasa a REA (sin tocar tu configuración).
  const toolsDir = process.env.EOLFI_TOOLS_DIR || path.join(os.homedir(), '.eolfi', 'tools');
  if (!cfg.env.REA_JADX_MCP_JAR && !process.env.REA_JADX_MCP_JAR) {
    const jar = path.join(toolsDir, 'jadx-headless-mcp-0.7.1-all.jar');
    if (fs.existsSync(jar)) cfg.env = { ...cfg.env, REA_JADX_MCP_JAR: jar };
  }
  const client = new McpClient(cfg, { log: (m) => out.appendLine(m) });
  context.subscriptions.push({ dispose: () => client.dispose() });
  return {
    client,
    confirm: async (tool, args) => {
      if (workMode() === 'automatico') { out.appendLine(`REA (automático): ${tool.name}`); return true; }
      const yes = 'Permitir';
      const pick = await vscode.window.showWarningMessage(`Eolfi quiere usar la herramienta de REA «${tool.name}»`,
        { modal: true, detail: `Ejecuta algo o toca procesos, dispositivos o el sistema (depuración, Frida, adb…).\n\n${String(tool.description || '').split('\n')[0].slice(0, 300)}\n\nArgumentos: ${JSON.stringify(args).slice(0, 600)}` }, yes);
      return pick === yes;
    },
  };
}

// MCP stdio declarados en ~/.codex/config.toml. Solo arranca un servidor tras confirmación de VS Code.
function codexMcpBridge(context, { skipRea = false } = {}) {
  const c = vscode.workspace.getConfiguration('eolfi');
  if (c.get('mcp.codex.enabled') === false) return null;
  const selectedConfig = String(c.get('mcp.codex.config') || '').trim();
  const configFile = selectedConfig
    ? path.resolve(selectedConfig.replace(/^~(?=[\\/])/, os.homedir()))
    : path.join(os.homedir(), '.codex', 'config.toml');
  let configs;
  try { configs = readCodexMcpServers({ python: lmi.pythonCommand(vscode), configFile }); }
  catch (e) { out.appendLine(`MCP Codex: ${e.message}`); configs = {}; }
  const clients = new Map();
  const approved = new Set();
  const names = () => Object.keys(configs).filter((name) => !(skipRea && name === 'rea')).sort();

  async function connect(name) {
    const cfg = configs[name];
    if (!cfg) throw new Error(`No existe un servidor stdio «${name}» en la configuración MCP de Codex.`);
    if (!approved.has(name)) {
      const yes = 'Conectar';
      const pick = await vscode.window.showWarningMessage(`Eolfi quiere iniciar el servidor MCP «${name}»`,
        { modal: true, detail: `Ejecutará el programa configurado por Codex en este equipo: ${path.basename(cfg.command)}.\n\nEl servidor recibirá solo las variables de entorno declaradas en su propia configuración. Eolfi no muestra sus valores al modelo.` }, yes);
      if (pick !== yes) throw new Error(`No se autorizó iniciar «${name}».`);
      approved.add(name);
    }
    if (!clients.has(name)) {
      const client = new McpClient(cfg, { log: (m) => out.appendLine(`${name}: ${m}`) });
      clients.set(name, client);
      context.subscriptions.push({ dispose: () => client.dispose() });
    }
    return clients.get(name);
  }

  async function confirm(name, tool, args, client) {
    if (tool?.annotations?.readOnlyHint === true && tool?.annotations?.destructiveHint !== true) return true;
    const yes = 'Permitir esta llamada';
    const pick = await vscode.window.showWarningMessage(`Eolfi quiere llamar ${name}.${tool.name}`,
      { modal: true, detail: `${client.redact(String(tool.description || '').split('\n')[0]).slice(0, 400)}\n\nArgumentos: ${client.redact(JSON.stringify(args)).slice(0, 700)}\n\nAl no estar marcada como solo lectura, requiere permiso para cada llamada.` }, yes);
    return pick === yes;
  }

  return { names, connect, confirm };
}

// Terminal e internet para el agente: un permiso por sesión (o solo esta vez), borrar siempre se confirma, y todo
// queda en el canal «Eolfi» y en ~/.eolfi/agent-log.jsonl.
// Ejecuta en la terminal integrada «Eolfi» con la integración de shell de VS Code: el usuario la ve en directo y
// el agente recibe la salida y el código. Devuelve null si la shell no tiene integración (se usa el proceso aparte).
async function runInVsTerminal(cmd, cwd, seconds, token) {
  if (!vscode.window.onDidChangeTerminalShellIntegration) return null;
  let term = vscode.window.terminals.find((t) => t.name === 'Eolfi' && t.exitStatus === undefined && t.creationOptions?.cwd === cwd);
  if (!term) {
    for (const t of vscode.window.terminals) if (t.name === 'Eolfi') t.dispose();
    term = vscode.window.createTerminal({ name: 'Eolfi', cwd, iconPath: new vscode.ThemeIcon('search') });
  }
  term.show(true);
  const si = term.shellIntegration || await new Promise((res) => {
    const d = vscode.window.onDidChangeTerminalShellIntegration((e) => { if (e.terminal === term) { d.dispose(); res(e.shellIntegration); } });
    setTimeout(() => { d.dispose(); res(null); }, 10000);
  });
  if (!si) return null;
  const exec = si.executeCommand(cmd);
  let out = '';
  const reading = (async () => { for await (const d of exec.read()) if (out.length < 100000) out += d; })().catch(() => {});
  const code = await new Promise((res) => {
    // Antes, al acabar bien, el temporizador seguía vivo y a los N s mandaba Ctrl+C a la terminal «Eolfi»
    // (aunque ya estuviera ejecutando otra orden). Ahora todo se limpia al terminar, por la vía que sea.
    let timer = null;
    let cancel = null;
    let d = null;
    const finish = (v, interrupt = false) => {
      clearTimeout(timer);
      d?.dispose();
      cancel?.dispose?.();
      if (interrupt) term.sendText('\u0003', false);
      res(v);
    };
    d = vscode.window.onDidEndTerminalShellExecution((e) => { if (e.execution === exec) finish(e.exitCode); });
    timer = setTimeout(() => finish(`cortado a los ${seconds} s`, true), seconds * 1000);
    cancel = token?.onCancellationRequested?.(() => finish('cancelado', true));
  });
  await Promise.race([reading, new Promise((r) => setTimeout(r, 1500))]);
  const clean = out.replace(/\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)/g, '').replace(/\r/g, '');
  return { code: code ?? '(desconocido)', out: clean.slice(0, 100000) };
}

function agentTools() {
  const LOG = path.join(os.homedir(), '.eolfi', 'agent-log.jsonl');
  return makeAgentTools({
    vscode, isSecretPath, resolveInside, runInTerminal: runInVsTerminal,
    log: (m) => out.appendLine(m),
    record: (e) => {
      try { fs.mkdirSync(path.dirname(LOG), { recursive: true }); fs.appendFileSync(LOG, `${JSON.stringify({ t: new Date().toISOString(), ...e })}\n`); } catch { /* sin registro */ }
    },
    enabled: () => {
      const c = vscode.workspace.getConfiguration('eolfi');
      return { terminal: c.get('agent.terminal') !== false, web: c.get('agent.web') !== false,
        privateNetwork: c.get('agent.privateNetwork') !== false };
    },
    ask: async (kind, what) => {
      if (workMode() === 'automatico' && kind !== 'privateWeb' && kind !== 'delete') return 'session';
      const session = 'Permitir en esta sesión', once = 'Solo esta vez', run = 'Ejecutar';
      if (kind === 'delete') {
        const pick = await vscode.window.showWarningMessage('Eolfi quiere ejecutar una orden que BORRA archivos',
          { modal: true, detail: `${what.cmd}\n\nEn: ${what.cwd}${what.motivo ? `\nPara: ${what.motivo}` : ''}\n\nBorrar no se puede deshacer.` }, run);
        return pick === run ? 'once' : 'no';
      }
      if (kind === 'privateWeb') {
        const pick = await vscode.window.showWarningMessage('Eolfi quiere conectarse a una dirección de tu equipo o red privada',
          { modal: true, detail: `${what.url}\nIP fijada: ${what.address}\n\nEsta conexión puede consultar un servicio local (incluidos otros equipos de tu LAN). Solo se permite esta petición; el permiso no se guarda ni se amplía aunque esté activo el modo automático.` }, once);
        return pick === once ? 'once' : 'no';
      }
      const [msg, detail] = kind === 'terminal'
        ? ['Eolfi quiere usar la terminal', `${what.cmd}\n\nEn: ${what.cwd}${what.motivo ? `\nPara: ${what.motivo}` : ''}\n\n«Permitir en esta sesión» deja ejecutar más órdenes sin preguntar hasta que cierres VS Code (borrar archivos se confirma siempre; lo peligroso para el sistema está bloqueado).`]
        : ['Eolfi quiere acceder a internet', `${what.search ? `Buscar: ${what.search}` : `Leer: ${what.url}`}\n\n«Permitir en esta sesión» deja leer y buscar sin preguntar hasta que cierres VS Code.`];
      const pick = await vscode.window.showWarningMessage(msg, { modal: true, detail }, session, once);
      return pick === session ? 'session' : pick === once ? 'once' : 'no';
    },
  });
}

// Modo de trabajo del agente: «manual» (pide permiso para ciertos cambios) o «automatico» (no pide permisos).
const workMode = () => (vscode.workspace.getConfiguration('eolfi').get('agent.mode') === 'automatico' ? 'automatico' : 'manual');
let modeItem = null;

async function setWorkMode(want) {
  if (want === workMode()) return true;
  if (want === 'automatico') {
    const yes = 'Activar modo automático';
    const pick = await vscode.window.showWarningMessage('¿Pasar el agente @eolfi a modo AUTOMÁTICO?', { modal: true,
      detail: 'Trabajará sin pedirte permiso para las operaciones normales: escribirá archivos, usará la terminal, internet público y REA directamente.\n\n'
        + 'Cada borrado y cada conexión a localhost/LAN siguen pidiendo confirmación. Lo peligroso para el sistema y tus secretos permanece bloqueado; todo queda en el registro (~/.eolfi/agent-log.jsonl) '
        + 'y los cambios de cada petición se pueden deshacer. Vuelves al modo manual cuando quieras.' }, yes);
    if (pick !== yes) return false;
  }
  await vscode.workspace.getConfiguration('eolfi').update('agent.mode', want, vscode.ConfigurationTarget.Global);
  showMode();
  out.appendLine(`Modo de trabajo: ${want}`);
  return true;
}

function showMode() {
  if (!modeItem) return;
  const auto = workMode() === 'automatico';
  modeItem.text = auto ? '$(rocket) Auto' : '$(shield) Manual';
  modeItem.tooltip = auto ? 'Eolfi en modo AUTOMÁTICO: operaciones normales sin preguntar; cada borrado y URL privada pide confirmación. Clic para pasar a manual.'
    : 'Eolfi en modo MANUAL: pide permiso para ciertos cambios. Clic para pasar a automático.';
  modeItem.backgroundColor = auto ? new vscode.ThemeColor('statusBarItem.warningBackground') : undefined;
  modeItem.show();
}

// Abre el Chat de VS Code con «@eolfi » escrito.
function openChat(help = false) {
  // Los @participantes solo están en el modo «Ask» del chat (no en «Agent»). Con la ayuda, se envía sola.
  const q = help === true ? { query: '@eolfi /ayuda', isPartialQuery: false } : { query: '@eolfi ', isPartialQuery: true };
  vscode.commands.executeCommand('workbench.action.chat.open', { mode: 'ask', ...q })
    .then(undefined, () => vscode.commands.executeCommand('workbench.action.chat.open', q))
    .then(undefined, () => vscode.commands.executeCommand('workbench.action.chat.open'));
}

async function splitFileCommand(uri) {
  const target = uri?.fsPath || vscode.window.activeTextEditor?.document?.uri?.fsPath;
  if (!target) return vscode.window.showWarningMessage('Eolfi: elige un archivo en el explorador.');
  if (isSecretPath(target)) return vscode.window.showWarningMessage('Eolfi: no divide archivos de secretos.');
  const value = await vscode.window.showInputBox({
    prompt: `¿En cuántas partes dividir ${path.basename(target)}?`,
    value: '4',
    validateInput: (v) => { try { validateParts(v); return null; } catch (e) { return e.message; } },
  });
  if (value === undefined) return;
  const count = validateParts(value);
  const output = `${target}.eolfi-parts`;
  const create = 'Crear partes';
  const pick = await vscode.window.showWarningMessage(
    `Eolfi creará ${count} partes y un manifiesto SHA-256.`,
    { modal: true, detail: `El original no se modifica. Destino: ${output}` }, create);
  if (pick !== create) return;
  return vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: `Eolfi: dividiendo ${path.basename(target)}` }, async () => {
    const result = splitTextFile(target, count, { outputDir: output });
    vscode.window.showInformationMessage(`Eolfi: ${result.parts.length} partes creadas junto al archivo original.`);
    return result;
  });
}

// Botón «Eolfi»: sin sesión pide iniciarla; con sesión abre el chat con la ayuda del agente.
async function chatButton() {
  if (!(await sessionToken())) {
    await vscode.commands.executeCommand('eolfi.login');
    if (!(await sessionToken())) return;
  }
  openChat(true);
}

function showLoggedOut() {
  modeItem?.hide();
  status.text = '$(lock) Eolfi: iniciar sesión';
  status.tooltip = 'La extensión de Eolfi necesita vincularse con tu Eolfi (código en Proveedores → Vincular VS Code)';
  status.command = 'eolfi.login';
  status.show();
}

async function runAnalysis(kind, body, label) {
  const client = await eolfiClient();
  await client.health();
  return vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: `Eolfi: analizando ${label}`, cancellable: true },
    async (progress, token) => {
      const rep = await client.analyze(kind, body, (msg) => { progress.report({ message: msg.slice(0, 120) }); out.appendLine(msg); }, token);
      lastSubject = rep.subject;
      const incs = rep.subject ? (await client.incognitas(rep.subject).catch(() => ({ incognitas: [] }))).incognitas : [];
      out.appendLine('');
      out.appendLine(`=== Eolfi: ${label} ===`);
      out.appendLine(summarize(rep, incs));
      out.show(true);
      const open = incs.filter((i) => i.status !== 'resolved').length;
      const pick = await vscode.window.showInformationMessage(
        `Eolfi: ${label} analizado · ${open} incógnitas abiertas`, 'Ver en el panel', 'Informe');
      if (pick === 'Ver en el panel') openPanel(`#objetivo/${encodeURIComponent(rep.subject)}`);
      if (pick === 'Informe') showReport(rep.subject);
      return rep;
    });
}

function openPanel(hash = '') {
  const base = baseUrl();
  // Simple Browser de VS Code (pestaña dentro del editor); si no está, el navegador del sistema.
  vscode.commands.executeCommand('simpleBrowser.show', `${base}/${hash}`)
    .then(undefined, () => vscode.env.openExternal(vscode.Uri.parse(`${base}/${hash}`)));
}

async function showReport(subject) {
  if (!subject) return vscode.window.showWarningMessage('Eolfi: todavía no has analizado nada en esta sesión.');
  const md = await (await eolfiClient()).report(subject, 'md');
  const doc = await vscode.workspace.openTextDocument({ content: String(md), language: 'markdown' });
  await vscode.window.showTextDocument(doc, { preview: false });
}

const guard = (fn) => async (...args) => {
  try { return await fn(...args); } catch (e) {
    if (e.status === 401) {   // vinculación revocada en el panel: se cierra la sesión aquí también
      await secrets.delete(SECRET);
      stop();
      showLoggedOut();
      return vscode.window.showErrorMessage('Eolfi: la vinculación ya no es válida (revocada). Vuelve a iniciar sesión.');
    }
    vscode.window.showErrorMessage(`Eolfi: ${e.message || e}`);
  }
};

function activate(context) {
  secrets = context.secrets;
  out = vscode.window.createOutputChannel('Eolfi');
  status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 50);
  status.command = 'eolfi.bridge.status';
  context.subscriptions.push(out, status,
    vscode.commands.registerCommand('eolfi.bridge.restart', guard(async () => { if (await sessionToken()) start(); else showLoggedOut(); })),
    vscode.commands.registerCommand('eolfi.login', guard(login)),
    vscode.commands.registerCommand('eolfi.logout', guard(logout)),
    vscode.commands.registerCommand('eolfi.bridge.status', async () => {
      out.appendLine('Modelo principal @eolfi: llama.cpp local; Copilot desconectado.');
      out.appendLine(`Herramientas permitidas para Eolfi: ${allowedTools().join(', ') || 'ninguna'}`);
      out.show(true);
    }),
    { dispose: stop },
    vscode.commands.registerCommand('eolfi.analyzeFile', guard(async (uri) => {
      const target = uri?.fsPath || vscode.window.activeTextEditor?.document?.uri?.fsPath;
      if (!target) return vscode.window.showWarningMessage('Eolfi: elige un archivo en el explorador.');
      const mode = vscode.workspace.getConfiguration('eolfi').get('analysisMode') || 'default';
      return runAnalysis('triage', { path: target, mode }, path.basename(target));
    })),
    vscode.commands.registerCommand('eolfi.analyzeFolder', guard(async (uri) => {
      const target = uri?.fsPath || vscode.workspace.workspaceFolders?.[0]?.uri?.fsPath;
      if (!target) return vscode.window.showWarningMessage('Eolfi: elige una carpeta.');
      return runAnalysis('repo', { source: target }, path.basename(target));
    })),
    vscode.commands.registerCommand('eolfi.analyzeWeb', guard(async () => {
      const url = await vscode.window.showInputBox({ prompt: 'URL que analizar (https://…)', validateInput: (v) => (/^https?:\/\//.test(v) ? null : 'Debe empezar por http:// o https://') });
      if (url) return runAnalysis('web', { source: url }, url);
    })),
    vscode.commands.registerCommand('eolfi.splitFile', guard(splitFileCommand)),
    vscode.commands.registerCommand('eolfi.openPanel', guard(async () => { await eolfiClient(); openPanel(lastSubject ? `#objetivo/${encodeURIComponent(lastSubject)}` : ''); })),
    vscode.commands.registerCommand('eolfi.lastReport', guard(async () => showReport(lastSubject))),
    vscode.commands.registerCommand('eolfi.openChat', () => openChat(false)),
    vscode.commands.registerCommand('eolfi.chatHelp', guard(chatButton)),
    vscode.commands.registerCommand('eolfi.configureLocalModel', guard(async () => {
      llamacfg.loadConfig({ findServer });   // la crea con Gemma 4 si no existe
      const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(llamacfg.configFile()));
      await vscode.window.showTextDocument(doc, { preview: false });
      vscode.window.showInformationMessage('Eolfi: configuración del modelo local (la misma que usa Eolfi en Python). Temperatura, longitud, razonamiento e instrucciones valen al momento; servidor, modelo, puerto, contexto y GPU, al reiniciar llama-server.');
    })),
    vscode.commands.registerCommand('eolfi.chatAuditContinue', () => vscode.commands.executeCommand('workbench.action.chat.open',
      { mode: 'ask', query: '@eolfi /auditar continuar', isPartialQuery: false })),
    vscode.commands.registerCommand('eolfi.chatContinue', () => vscode.commands.executeCommand('workbench.action.chat.open',
      { mode: 'ask', query: '@eolfi continúa donde lo dejaste, con lo que falta del resumen anterior', isPartialQuery: false })));
  // Enlaces vscode://eolfi.eolfi-vscode-bridge/login?code=123456 y …/chat (los abre el panel o la CLI de Eolfi).
  context.subscriptions.push(vscode.window.registerUriHandler({
    handleUri: guard(async (uri) => {
      out.appendLine(`Enlace recibido: ${uri.path}`);
      if (uri.path === '/login') return login(new URLSearchParams(uri.query).get('code'));
      if (uri.path === '/chat') return openChat();
    }),
  }));
  // Chat «@eolfi»: comparte el último análisis con los comandos.
  const chatState = { get lastSubject() { return lastSubject; }, set lastSubject(v) { lastSubject = v; }, lastLabel: null };
  // Un solo juego de acciones para el chat: el diario de cambios de cada petición sirve para «Deshacer estos cambios».
  const chatActions = makeActions(vscode);
  context.subscriptions.push(vscode.commands.registerCommand('eolfi.undoJournal', guard(async (journal) => {
    const r = await chatActions.undo({ journal });
    vscode.window.showInformationMessage(`Eolfi: deshechos ${r.restored.length} archivos.`);
  })));
  let chatHandler = null;
  let primaryLocalModel = null;
  {
    const rea = reaBridge(context);
    const reaDisabled = vscode.workspace.getConfiguration('eolfi').get('rea.enabled') === false;
    const codexMcp = codexMcpBridge(context, { skipRea: !!rea || reaDisabled });
    chatHandler = makeChatHandler({
      vscode, summarize, state: chatState, openReport: showReport,
      actions: chatActions, workspaceTools: TOOL_DEFS, rea, codexMcp,
      extraTools: combineTools(agentTools(), makeCaseTools({ client: eolfiClient, log: (m) => out.appendLine(m) })),
      maxSteps: () => vscode.workspace.getConfiguration('eolfi').get('agent.maxSteps'),
      autoExecuteMeta: () => vscode.workspace.getConfiguration('eolfi').get('meta.autoExecute') !== false,
      workMode, setWorkMode,
      preferLocal: () => true,
      setPreferLocal: async (v) => { if (!v) return false; await vscode.workspace.getConfiguration('eolfi').update('agent.model', 'local', vscode.ConfigurationTarget.Global); return true; },
      localConfig: () => llamacfg.loadConfig({ findServer }),
      instructions: () => String(vscode.workspace.getConfiguration('eolfi').get('agent.instructions') || '').trim(),
      showModel: () => vscode.workspace.getConfiguration('eolfi').get('agent.showModel') !== false,
      localModel: (() => {
        const c = vscode.workspace.getConfiguration('eolfi');
        const endpoint = EOLAS_URL;
        const model = EOLAS_MODEL;
        // El único proveedor local es Eolas/Gemma 12B; el autoarranque nunca usa un GGUF externo ni 8090.
        const autoStart = c.get('fallback.autoStart') === true;
        const launcher = String(c.get('fallback.eolasLauncher') || '').trim();
        const starter = autoStart ? makeEolasStarter({ launcher: launcher || undefined, endpoint, model }) : null;
        const lm = makeLocalModel({ endpoints: [endpoint], model, starter,
          options: (o) => llamacfg.requestOptions(llamacfg.loadConfig({ findServer }), o),
          allowStart: async () => autoStart });
        out.appendLine(`Modelo local: ${model} en ${endpoint}; autoarranque Eolas ${autoStart ? 'activado' : 'desactivado'}.`);
        primaryLocalModel = lm;
        context.subscriptions.push({ dispose: () => lm.stop() });
        return lm;
      })(),
      memory: vscode.workspace.getConfiguration('eolfi').get('agent.history') === false ? null
        : makeHistory({ keepDays: () => vscode.workspace.getConfiguration('eolfi').get('agent.historyDays') }),
      mode: () => vscode.workspace.getConfiguration('eolfi').get('analysisMode') || 'default',
      getClient: async () => {
        const t = await sessionToken();
        if (!t) throw new Error('sin sesión');
        return makeClient(baseUrl(), t);
      },
    });
    // @eolfi (obsoleto: el harness de Copilot ya no admite participantes). Se mantiene una versión para la
    // transición; «eolfi.chatParticipant»: false lo quita. Lo nuevo es el agente «Eolfi» + MCP + herramientas.
    if (vscode.chat?.createChatParticipant && vscode.workspace.getConfiguration('eolfi').get('chatParticipant') !== false) {
      const p = vscode.chat.createChatParticipant('eolfi.chat', chatHandler);
      p.iconPath = new vscode.ThemeIcon('search');
      context.subscriptions.push(p);
    }
    if (primaryLocalModel) {
      void primaryLocalModel.locate().then((at) => {
        out.appendLine(at ? `Modelo local primario listo: ${at.model} en ${at.url}` : 'No se encontró servidor local activo.');
      }).catch((e) => out.appendLine(`No se pudo iniciar el modelo local primario: ${e.message || e}`));
    }
  }
  const version = String(context.extension?.packageJSON?.version || '0');
  const mcpOk = lmi.registerMcp(vscode, context, version);
  panelChatHandler = chatHandler;
  const nTools = lmi.registerTools(vscode, context, chatHandler);
  if (out) out.appendLine(`Modo agente: servidor MCP ${mcpOk ? 'registrado' : 'no disponible (VS Code < 1.101)'}; ${nTools} herramientas de Eolfi.`);
  context.subscriptions.push(vscode.commands.registerCommand('eolfi.installAgent', guard(async () => {
    const folders = vscode.workspace.workspaceFolders || [];
    if (!folders.length) return vscode.window.showWarningMessage('Eolfi: abre primero una carpeta.');
    const pick = folders.length === 1 ? folders[0]
      : await vscode.window.showWorkspaceFolderPick({ placeHolder: '¿En qué carpeta instalo el agente Eolfi?' });
    if (!pick) return;
    const files = await lmi.installAgent(vscode, pick.uri.fsPath);
    vscode.window.showInformationMessage(files.length
      ? `Eolfi: agente instalado en ${pick.name} (${files.length} archivos en .github). Elígelo en el selector de agentes del chat.`
      : `Eolfi: el agente ya estaba instalado en ${pick.name}.`);
  })));
  // Interruptor de modo en la barra de estado (junto al botón «Eolfi»).
  modeItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 49);
  modeItem.command = 'eolfi.toggleMode';
  context.subscriptions.push(modeItem,
    vscode.commands.registerCommand('eolfi.toggleMode', guard(() => setWorkMode(workMode() === 'automatico' ? 'manual' : 'automatico'))),
    vscode.commands.registerCommand('eolfi.modeAuto', guard(() => setWorkMode('automatico'))),
    vscode.commands.registerCommand('eolfi.modeManual', guard(() => setWorkMode('manual'))),
    vscode.workspace.onDidChangeConfiguration((e) => { if (e.affectsConfiguration('eolfi.agent.mode')) showMode(); }));
  // El puente solo arranca con la sesión iniciada.
  sessionToken().then((t) => { if (t) { start(); showMode(); } else showLoggedOut(); });
  // Para las pruebas e2e dentro de un VS Code real (e2e/run.js): el mismo manejador que usa el Chat.
  return { chatHandler };
}

function deactivate() { stop(); }

module.exports = { activate, deactivate };
