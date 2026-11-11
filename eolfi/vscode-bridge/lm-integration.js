// Eolfi en el modo agente de VS Code, sin participante de chat (la API de chat participants está obsoleta y el
// harness de Copilot no la soporta):
//  1. Servidor MCP «Eolfi» (python -m eolfi mcp) registrado desde la extensión: triage, evidencias, incógnitas,
//     informe, comparar, web, repo… aparecen como herramientas en el chat con el modelo que elijas.
//  2. Herramientas de la extensión (languageModelTools): auditoría archivo por archivo, carpetas abiertas,
//     historial y REA, con la misma lógica que tenía @eolfi.
//  3. El agente «Eolfi» (agent/agents/eolfi.agent.md) y los prompt files /analizar, /auditar… se copian al .github del
//     workspace con el comando «Eolfi: instalar el agente en este workspace».
'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

// Raíz del proyecto Eolfi (la extensión vive en <raíz>/eolfi/vscode-bridge).
const EOLFI_ROOT = path.resolve(__dirname, '..', '..');

// Herramientas de la extensión: nombre → si escribe (pide confirmación) y el mensaje para el usuario.
const LM_TOOLS = {
  eolfi_carpetas: { writes: false, label: 'Mirando las carpetas abiertas' },
  eolfi_auditar: { writes: true, label: 'Auditoría archivo por archivo',
    confirm: (i) => `Eolfi recorrerá ${i.continuar ? 'la última auditoría' : (i.carpeta || 'la carpeta abierta')} archivo por archivo con el modelo de IA y escribirá el informe en informes/.` },
  eolfi_historial: { writes: false, label: 'Buscando en el historial de Eolfi' },
  eolfi_partir_archivo: { writes: true, label: 'Dividiendo archivo grande',
    confirm: (i) => `Eolfi creará ${i.partes || 4} partes de ${i.archivo || 'un archivo'} y un manifiesto de comprobación. El original se conserva.` },
  eolfi_herramientas_archivo: { writes: true, label: 'Trabajando con archivos',
    confirm: (i) => `Eolfi ejecutará «${i.operacion || 'inspeccionar'}» sobre ${i.archivo || i.izquierdo || 'el archivo indicado'}. Las operaciones que escriben conservan el original.` },
  eolfi_medir_modelo: { writes: true, label: 'Midiendo el modelo local',
    confirm: () => 'Eolfi ejecutará tres mediciones cortas con llama-bench. No iniciará otro servidor ni cambiará el modelo configurado.' },
  rea_herramientas: { writes: false, label: 'Buscando herramientas de REA' },
  rea_usar: { writes: true, label: 'Ejecutando una herramienta de REA',
    confirm: (i) => `REA ejecutará «${i.herramienta}» con ${JSON.stringify(i.argumentos || {}).slice(0, 300)}.` },
};

function pythonCommand(vscode, { platform = process.platform, localAppData = process.env.LOCALAPPDATA, home = os.homedir() } = {}) {
  const set = String(vscode.workspace.getConfiguration('eolfi').get('python') || '').trim();
  if (set) return set;
  if (platform === 'win32') {
    const roots = [...new Set([localAppData, path.join(home, 'AppData', 'Local')].filter(Boolean))];
    for (const root of roots) {
      const installs = path.join(root, 'Programs', 'Python');
      try {
        const versions = fs.readdirSync(installs).filter((name) => /^Python\d+$/.test(name))
          .sort((a, b) => Number(b.slice(6)) - Number(a.slice(6)));
        for (const version of versions) {
          const exe = path.join(installs, version, 'python.exe');
          if (fs.existsSync(exe)) return exe;
        }
      } catch { /* prueba la siguiente ubicación habitual */ }
    }
    return 'python';
  }
  return 'python3';
}

function mcpDefinition(vscode, version) {
  const c = vscode.workspace.getConfiguration('eolfi');
  // Sin ajuste, Eolfi elige la base (EOLFI_DB o ~/.eolfi/eolfi.db, la misma que el panel y la CLI).
  const db = String(c.get('mcp.db') || '').trim();
  const roots = (vscode.workspace.workspaceFolders || []).map((f) => f.uri.fsPath);
  const env = { PYTHONPATH: EOLFI_ROOT, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' };
  const library = String(c.get('mcp.library') || '').trim();
  if (library) env.EOLFI_LIBRARY = library;
  // Solo las carpetas abiertas (y samples/ de Eolfi) salvo que se desactive.
  if (c.get('mcp.restrictToWorkspace') !== false && roots.length) {
    env.EOLFI_ROOTS = [...roots, path.join(EOLFI_ROOT, 'samples')].join(path.delimiter);
  }
  const def = new vscode.McpStdioServerDefinition('Eolfi', pythonCommand(vscode), ['-m', 'eolfi', ...(db ? ['--db', db] : []), 'mcp'], env, version);
  try { def.cwd = vscode.Uri.file(EOLFI_ROOT); } catch { /* versiones sin cwd */ }
  return def;
}

function registerMcp(vscode, context, version) {
  if (!vscode.lm?.registerMcpServerDefinitionProvider || !vscode.McpStdioServerDefinition) return false;
  const changed = new vscode.EventEmitter();
  context.subscriptions.push(changed,
    vscode.workspace.onDidChangeWorkspaceFolders(() => changed.fire()),
    vscode.workspace.onDidChangeConfiguration((e) => { if (e.affectsConfiguration('eolfi.python') || e.affectsConfiguration('eolfi.mcp')) changed.fire(); }),
    vscode.lm.registerMcpServerDefinitionProvider('eolfi.mcp', {
      onDidChangeMcpServerDefinitions: changed.event,
      provideMcpServerDefinitions: () => (vscode.workspace.getConfiguration('eolfi').get('mcp.enabled') === false ? [] : [mcpDefinition(vscode, version)]),
    }));
  return true;
}

function registerTools(vscode, context, handler) {
  if (!vscode.lm?.registerTool || !handler?.lmTool) return 0;
  const result = (text) => new vscode.LanguageModelToolResult([new vscode.LanguageModelTextPart(String(text))]);
  let n = 0;
  for (const [name, meta] of Object.entries(LM_TOOLS)) {
    context.subscriptions.push(vscode.lm.registerTool(name, {
      prepareInvocation: (options) => ({
        invocationMessage: meta.label,
        ...(meta.confirm && vscode.workspace.getConfiguration('eolfi').get('agent.mode') !== 'automatico'
          ? { confirmationMessages: { title: meta.label, message: new vscode.MarkdownString(meta.confirm(options.input || {})) } } : {}),
      }),
      invoke: async (options, token) => {
        try { return result(await handler.lmTool(name, options.input || {}, token)); } catch (e) {
          // El error vuelve al modelo como texto: así puede explicarlo o probar otra cosa.
          return result(`Error de Eolfi: ${e.message || e}`);
        }
      },
    }));
    n++;
  }
  return n;
}

// Copia el agente y los prompt files al .github del workspace (sin pisar los que el usuario haya cambiado).
async function installAgent(vscode, folder) {
  // Plantillas sin punto inicial (las carpetas ocultas no siempre viajan al copiar o sincronizar).
  const src = path.join(__dirname, 'agent');
  const files = [];
  for (const sub of ['agents', 'prompts']) {
    const dir = path.join(src, sub);
    if (!fs.existsSync(dir)) continue;
    for (const f of fs.readdirSync(dir)) {
      const from = path.join(dir, f);
      const to = path.join(folder, '.github', sub, f);
      if (path.resolve(from) === path.resolve(to)) continue;
      if (fs.existsSync(to)) continue;
      fs.mkdirSync(path.dirname(to), { recursive: true });
      fs.copyFileSync(from, to);
      files.push(path.relative(folder, to));
    }
  }
  return files;
}

module.exports = { registerMcp, registerTools, installAgent, mcpDefinition, pythonCommand, LM_TOOLS, EOLFI_ROOT };
