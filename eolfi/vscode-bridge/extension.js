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
const { makeAgentTools } = require('./agent-tools');
const { makeHistory } = require('./history');
const { makeLocalModel } = require('./local-model');
const { makeLlamaStarter, findServer } = require('./llama-starter');
const llamacfg = require('./llamacpp-config');
const lmi = require('./lm-integration');

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

function start() {
  stop();
  const token = crypto.randomBytes(32).toString('hex');
  server = http.createServer(makeHandler({ vscode, token, getAllowedTools: allowedTools, log: (m) => out.appendLine(m),
    actions: makeActions(vscode) }));
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
      return { terminal: c.get('agent.terminal') !== false, web: c.get('agent.web') !== false };
    },
    ask: async (kind, what) => {
      if (workMode() === 'automatico') return kind === 'delete' ? 'once' : 'session';
      const session = 'Permitir en esta sesión', once = 'Solo esta vez', run = 'Ejecutar';
      if (kind === 'delete') {
        const pick = await vscode.window.showWarningMessage('Eolfi quiere ejecutar una orden que BORRA archivos',
          { modal: true, detail: `${what.cmd}\n\nEn: ${what.cwd}${what.motivo ? `\nPara: ${what.motivo}` : ''}\n\nBorrar no se puede deshacer.` }, run);
        return pick === run ? 'once' : 'no';
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
      detail: 'Trabajará sin pedirte permisos: escribirá archivos, usará la terminal, internet y REA directamente.\n\n'
        + 'Sigue bloqueado lo peligroso para el sistema y tus secretos; todo queda en el registro (~/.eolfi/agent-log.jsonl) '
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
  modeItem.tooltip = auto ? 'Eolfi en modo AUTOMÁTICO: no pide permisos. Clic para pasar a manual.'
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
      const models = await vscode.lm.selectChatModels({ vendor: 'copilot' });
      const tools = (vscode.lm.tools || []).map((t) => t.name);
      out.appendLine(`Modelos de IA: ${models.map((m) => `${m.name} (${m.family})`).join(', ') || 'ninguno'}`);
      out.appendLine(`Herramientas disponibles: ${tools.join(', ') || 'ninguna'}`);
      out.appendLine(`Permitidas para Eolfi (eolfi.allowedTools): ${allowedTools().join(', ') || 'ninguna'}`);
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
  {
    chatHandler = makeChatHandler({
      vscode, summarize, state: chatState, openReport: showReport,
      actions: chatActions, workspaceTools: TOOL_DEFS, rea: reaBridge(context), extraTools: agentTools(),
      maxSteps: () => vscode.workspace.getConfiguration('eolfi').get('agent.maxSteps'),
      workMode, setWorkMode,
      preferLocal: () => vscode.workspace.getConfiguration('eolfi').get('agent.model') === 'local',
      setPreferLocal: async (v) => { await vscode.workspace.getConfiguration('eolfi').update('agent.model', v ? 'local' : 'copilot', vscode.ConfigurationTarget.Global); },
      localConfig: () => llamacfg.loadConfig({ findServer }),
      instructions: () => String(vscode.workspace.getConfiguration('eolfi').get('agent.instructions') || '').trim(),
      showModel: () => vscode.workspace.getConfiguration('eolfi').get('agent.showModel') !== false,
      localModel: (() => {
        const c = vscode.workspace.getConfiguration('eolfi');
        if (c.get('fallback.local') === false) return null;
        const url = String(c.get('fallback.url') || '').trim();
        // Si no hay ninguno en marcha, Eolfi arranca un llama-server (en manual, con permiso una vez por sesión).
        // Servidor, modelo (Gemma 4), puerto, contexto, GPU y parámetros: ~/.eolfi/llamacpp.json (común con Eolfi en Python).
        const starter = c.get('fallback.autoStart') === false ? null : makeLlamaStarter({
          server: String(c.get('fallback.llamaServer') || '').trim(), gguf: String(c.get('fallback.gguf') || '').trim(),
          config: () => llamacfg.loadConfig({ findServer }), log: (m) => out.appendLine(m) });
        let allowed = false;
        const port = llamacfg.loadConfig({ findServer }).port;
        const lm = makeLocalModel({ endpoints: url ? [url] : [`http://127.0.0.1:${port}`, 'http://127.0.0.1:11435', 'http://127.0.0.1:8080'],
          model: String(c.get('fallback.model') || '').trim(), starter,
          options: (o) => llamacfg.requestOptions(llamacfg.loadConfig({ findServer }), o),
          allowStart: async (plan) => {
            // Elegido como modelo principal (/modelo local) o modo automático: sin preguntar.
            if (allowed || workMode() === 'automatico' || vscode.workspace.getConfiguration('eolfi').get('agent.model') === 'local') return true;
            const yes = 'Arrancar llama-server';
            const pick = await vscode.window.showWarningMessage('¿Arranco el modelo local (llama.cpp) para seguir? Copilot no está disponible ahora (límite de peticiones o sin sesión).',
              { modal: true, detail: `Servidor: ${plan.exe}\nModelo: ${plan.model}\n\nSolo en 127.0.0.1; el código no sale del equipo. Se para al cerrar VS Code o tras 15 minutos sin uso.` }, yes);
            allowed = pick === yes;
            return allowed;
          } });
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
  }
  const version = String(context.extension?.packageJSON?.version || '0');
  const mcpOk = lmi.registerMcp(vscode, context, version);
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
