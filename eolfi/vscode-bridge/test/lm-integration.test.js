'use strict';
// Modo agente sin participante: servidor MCP registrado y herramientas de la extensión.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const lmi = require('../lm-integration');
const { makeChatHandler } = require('../chat');

function fakeVscode(folders, settings = {}) {
  const reg = { tools: {}, mcp: null };
  const vscode = {
    workspace: {
      workspaceFolders: folders.map((f) => ({ name: path.basename(f), uri: { fsPath: f } })),
      getConfiguration: () => ({ get: (k) => settings[k] }),
      onDidChangeWorkspaceFolders: () => ({ dispose() {} }),
      onDidChangeConfiguration: () => ({ dispose() {} }),
    },
    window: { activeTextEditor: null },
    Uri: { file: (p) => ({ fsPath: p }) },
    EventEmitter: class { constructor() { this.event = () => ({ dispose() {} }); } fire() {} dispose() {} },
    McpStdioServerDefinition: class { constructor(label, command, args, env, version) { Object.assign(this, { label, command, args, env, version }); } },
    MarkdownString: class { constructor(v) { this.value = v; } },
    LanguageModelTextPart: class { constructor(v) { this.value = v; } },
    LanguageModelToolResult: class { constructor(c) { this.content = c; } },
    lm: {
      registerMcpServerDefinitionProvider: (id, p) => { reg.mcp = { id, p }; return { dispose() {} }; },
      registerTool: (name, t) => { reg.tools[name] = t; return { dispose() {} }; },
      selectChatModels: async () => [],
    },
  };
  return { vscode, reg };
}

test('registra el servidor MCP de Eolfi limitado a las carpetas abiertas', () => {
  const { vscode, reg } = fakeVscode(['/w/uno']);
  const ctx = { subscriptions: [] };
  assert.equal(lmi.registerMcp(vscode, ctx, '0.6.0'), true);
  assert.equal(reg.mcp.id, 'eolfi.mcp');
  const [def] = reg.mcp.p.provideMcpServerDefinitions();
  assert.deepEqual(def.args.slice(-1), ['mcp']);
  assert.ok(def.args.includes('-m') && def.args.includes('eolfi'));
  assert.equal(def.env.PYTHONPATH, lmi.EOLFI_ROOT);
  assert.ok(def.env.EOLFI_ROOTS.split(path.delimiter).includes('/w/uno'));
  assert.equal(def.version, '0.6.0');
});

test('detecta Python bajo el perfil aunque LOCALAPPDATA apunte a una ubicación virtualizada', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-python-path-'));
  const root = path.join(dir, 'perfil', 'AppData', 'Local');
  const exe = path.join(root, 'Programs', 'Python', 'Python312', 'python.exe');
  fs.mkdirSync(path.dirname(exe), { recursive: true });
  fs.writeFileSync(exe, '');
  try {
    const vscode = { workspace: { getConfiguration: () => ({ get: () => '' }) } };
    assert.equal(lmi.pythonCommand(vscode, { platform: 'win32', localAppData: path.join(dir, 'virtualizado'), home: path.join(dir, 'perfil') }), exe);
    assert.equal(lmi.pythonCommand({ workspace: { getConfiguration: () => ({ get: () => 'python-personal' }) } },
      { platform: 'win32', localAppData: path.join(dir, 'virtualizado'), home: path.join(dir, 'perfil') }), 'python-personal');
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('sin la API de MCP (VS Code antiguo) no falla', () => {
  const { vscode } = fakeVscode([]);
  delete vscode.lm.registerMcpServerDefinitionProvider;
  assert.equal(lmi.registerMcp(vscode, { subscriptions: [] }, '1'), false);
});

test('las herramientas declaradas en package.json coinciden con las registradas', () => {
  const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8'));
  const declared = pkg.contributes.languageModelTools.map((t) => t.name).sort();
  assert.deepEqual(declared, Object.keys(lmi.LM_TOOLS).sort());
  assert.deepEqual(pkg.contributes.mcpServerDefinitionProviders.map((p) => p.id), ['eolfi.mcp']);
});

test('eolfi_carpetas devuelve las carpetas abiertas y la auditoría pide confirmación', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-lmi-'));
  try {
    const { vscode, reg } = fakeVscode([dir]);
    const handler = makeChatHandler({ vscode, getClient: async () => ({}), summarize: () => '', state: {} });
    assert.equal(lmi.registerTools(vscode, { subscriptions: [] }, handler), Object.keys(lmi.LM_TOOLS).length);
    const res = await reg.tools.eolfi_carpetas.invoke({ input: {} });
    const data = JSON.parse(res.content[0].value);
    assert.equal(data.carpetas[0].path, dir);
    const prep = reg.tools.eolfi_auditar.prepareInvocation({ input: { carpeta: 'celtiaia' } });
    assert.match(prep.confirmationMessages.message.value, /celtiaia/);
    assert.equal(reg.tools.eolfi_carpetas.prepareInvocation({ input: {} }).confirmationMessages, undefined);
    // Sin REA configurado, el error vuelve al modelo como texto (no rompe el chat).
    const rea = await reg.tools.rea_usar.invoke({ input: { herramienta: 'x' } });
    assert.match(rea.content[0].value, /Error de Eolfi/);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('instala el agente y los prompt files sin pisar los existentes', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'eolfi-agent-'));
  try {
    fs.mkdirSync(path.join(dir, '.github', 'prompts'), { recursive: true });
    fs.writeFileSync(path.join(dir, '.github', 'prompts', 'auditar.prompt.md'), 'mío');
    const files = await lmi.installAgent({}, dir);
    assert.ok(files.some((f) => f.endsWith('eolfi.agent.md')));
    assert.equal(fs.readFileSync(path.join(dir, '.github', 'prompts', 'auditar.prompt.md'), 'utf8'), 'mío');
    assert.deepEqual(await lmi.installAgent({}, dir), []);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});
