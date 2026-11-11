'use strict';
// O14: Eolas como modelo de lenguaje de VS Code (API LanguageModelChatProvider, VS Code ≥ 1.104).
// Sin un modelo registrado, el chat de VS Code no envía nada —tampoco a @eolfi— si no hay sesión de Copilot
// («Language model unavailable»). Este proveedor publica Gemma 4 12B servido por Eolas en este equipo y reutiliza
// el cliente local de Eolfi (local-model.js), con llamadas a herramientas. El código no sale del equipo.
const VENDOR = 'eolas';

const ROLE_USER = 1;
const ROLE_ASSISTANT = 2;

function partText(c) {
  if (c == null) return '';
  if (typeof c === 'string') return c;
  if (typeof c.value === 'string') return c.value;
  try { return JSON.stringify(c); } catch { return String(c); }
}

// Mensajes de VS Code → formato OpenAI que entiende local-model.chatTools (system/user/assistant con tool_calls/tool).
function toOpenAI(vscode, messages) {
  const out = [];
  const callNames = new Map();
  for (const m of messages || []) {
    const role = m.role === ROLE_ASSISTANT ? 'assistant' : m.role === ROLE_USER ? 'user' : 'system';
    let text = '';
    const calls = [];
    const results = [];
    for (const p of m.content || []) {
      if (p instanceof vscode.LanguageModelToolCallPart) {
        callNames.set(p.callId, p.name);
        calls.push({ id: p.callId, type: 'function', function: { name: p.name, arguments: JSON.stringify(p.input ?? {}) } });
      } else if (p instanceof vscode.LanguageModelToolResultPart) {
        results.push({ role: 'tool', tool_call_id: p.callId, name: callNames.get(p.callId) || '', content: (p.content || []).map(partText).join('') });
      } else if (p instanceof vscode.LanguageModelTextPart) {
        text += p.value;
      }
    }
    out.push(...results);
    if (calls.length) out.push({ role: 'assistant', content: text, tool_calls: calls });
    else if (text || !results.length) out.push({ role, content: text });
  }
  return out;
}

function makeEolasProvider({ vscode, localModel, modelId, limits = () => ({ ctx: 32768, maxTokens: 4096 }) }) {
  return {
    async provideLanguageModelChatInformation() {
      const { ctx, maxTokens } = limits();
      return [{ id: modelId, name: 'Gemma 4 12B · Eolas (local)', family: 'gemma', version: modelId, detail: 'en este equipo',
        tooltip: 'Eolas en 127.0.0.1:11435: el código no sale del equipo.', maxInputTokens: Math.max(1024, ctx - maxTokens),
        maxOutputTokens: maxTokens, capabilities: { toolCalling: true, imageInput: false } }];
    },
    async provideLanguageModelChatResponse(_model, messages, options, progress, token) {
      const tools = (options?.tools || []).map((t) => ({ name: t.name, description: t.description, inputSchema: t.inputSchema }));
      const r = await localModel.chatTools(toOpenAI(vscode, messages), tools, token);
      if (r.content) progress.report(new vscode.LanguageModelTextPart(r.content));
      for (const c of r.tool_calls || []) progress.report(new vscode.LanguageModelToolCallPart(c.id, c.name, c.arguments || {}));
    },
    async provideTokenCount(_model, text) {
      const s = typeof text === 'string' ? text : (text?.content || []).map(partText).join('');
      return Math.ceil(s.length / 3.5);   // aproximación: el cliente local no expone el tokenizador
    },
  };
}

// Devuelve false en versiones de VS Code sin la API (la extensión sigue funcionando como antes).
function registerEolasModel(vscode, context, localModel, opts) {
  if (typeof vscode.lm?.registerLanguageModelChatProvider !== 'function') return false;
  context.subscriptions.push(vscode.lm.registerLanguageModelChatProvider(VENDOR, makeEolasProvider({ vscode, localModel, ...opts })));
  return true;
}

module.exports = { VENDOR, toOpenAI, makeEolasProvider, registerEolasModel };
