// Adaptador de Gemini web (gemini.google.com) portado de Force/geminiBrowser.ts.
// Solo interfaz visible: no lee cookies de Google ni llama a endpoints privados.
import { MAX_WIRE, evaluateIn, sleep, waitReply, abortCheck, assertOrigin, ensureConversation, unixNewlines, REPLY_TIMEOUT_MS } from './core.mjs';

export const GEMINI_ORIGIN = 'https://gemini.google.com';
const HOME = `${GEMINI_ORIGIN}/app`;
const EDITOR = 'div[contenteditable="true"][role="textbox"][aria-label*="Gemini" i],rich-textarea [contenteditable="true"],textarea[aria-label*="Gemini" i]';
const ASSISTANT = ['model-response', '[data-test-id*="model-response"]', '[data-testid*="model-response"]'];
const USER = ['user-query', '[data-test-id*="user-query"]', '[data-testid*="user-query"]'];
const REF = /\(Referencia técnica de Eolfi, no la menciones: [0-9a-f-]{36}\)$/i;

const normalize = (v) => v.normalize('NFC').replace(/[​﻿]/g, '').replace(/\s+/g, ' ').trim();

export function isGeminiUrl(value) {
  try { const u = new URL(value); return u.origin === GEMINI_ORIGIN && !u.username && !u.password; } catch { return false; }
}

export class GeminiAdapter {
  constructor(contents) {
    this.contents = contents;
    this.active = false;
    this.current = null;
    this.urls = new Map();
    this.uncertain = new Set();
    this.stable = new Map();
    this.sawStop = false;       // ¿se vio el botón "Detener respuesta" durante este envío?
    this.label = 'Gemini';
  }

  async status() {
    const url = this.contents.isDestroyed() ? '' : this.contents.getURL();
    if (!isGeminiUrl(url)) {
      let host = url;
      try { host = new URL(url).host; } catch { /* about:blank */ }
      return { ok: false, detail: `La ventana está en ${host || 'una página vacía'}: inicia sesión allí o vuelve al chat` };
    }
    try {
      const s = await this.readState();
      return s.draft !== null && !s.blocked
        ? await this.withSession({ ok: true, detail: 'Gemini web listo' })
        : { ok: false, detail: 'Inicia sesión en Google o acepta las condiciones en la ventana de Gemini' };
    } catch { return { ok: false, detail: 'Gemini aún carga o necesita iniciar sesión' }; }
  }

  // ¿Hay sesión iniciada? Un botón o enlace visible de "Iniciar sesión" indica modo invitado.
  async withSession(st) {
    const guest = await this.evaluate(`(() => [...document.querySelectorAll('a,button,[role="button"]')].some(el =>
      el.getClientRects().length && /^(iniciar sesión|sign in|log in|acceder|entrar)$/i.test((el.innerText || el.getAttribute('aria-label') || '').trim())))()`).catch(() => false);
    return { ...st, signedIn: !guest, detail: st.detail + (guest ? ' · modo invitado (inicia sesión para usar tu cuenta)' : ' · con sesión') };
  }

  reset(conversation) { return this.uncertain.delete(conversation); }

  async send(prompt, signal, conversation = 'default', onPartial = null) {
    prompt = unixNewlines(prompt);
    if (this.active) throw new Error('Gemini ya tiene una petición activa.');
    if (this.uncertain.has(conversation)) throw new Error('El turno de Gemini quedó interrumpido; inicia una conversación nueva para no duplicarlo.');
    // Sin texto añadido: una "referencia técnica" en el mensaje hace que Gemini rechace
    // peticiones normales. El mensaje propio se reconoce por posición (el único turno de
    // usuario nuevo tras enviar) y por contenido (empieza igual que lo enviado).
    const wire = prompt.trim();
    if (!prompt.trim() || wire.length > MAX_WIRE) throw new Error(`La petición supera el límite del puente (${MAX_WIRE} caracteres).`);
    this.active = true;
    let submitted = false;
    try {
      const contents = this.contents;
      await contents.focus();   // restaura la ventana si está minimizada: oculta no se pinta
      if (!isGeminiUrl(contents.getURL())) throw new Error('Inicia sesión en Google en la ventana de Gemini y vuelve a enviar.');
      await ensureConversation(this, contents, conversation, HOME);
      await this.ready(signal);
      const previous = await this.settle(signal);
      if (previous.blocked || previous.draft === null) throw new Error('Completa el acceso a Gemini en su ventana.');
      if (previous.draft.trim()) {
        const own = REF.test(previous.draft.trim()) || (this.lastWire && normalize(previous.draft) === normalize(this.lastWire));
        if (!own) throw new Error('Hay un borrador escrito en Gemini. Envíalo o vacíalo antes.');
        await this.clearOwnDraft(signal);
      }
      if (previous.rows.some((r) => r.assistant && !r.complete)) throw new Error('Gemini todavía está respondiendo.');
      const baseline = new Set(previous.rows.filter((r) => r.assistant).map((r) => r.id));
      const usersBefore = previous.rows.filter((r) => !r.assistant).length;
      const head = normalize(wire).slice(0, 60);
      await this.evaluate(`(() => { const el=[...document.querySelectorAll(${JSON.stringify(EDITOR)})].find(e=>e.getClientRects().length); if(!el) throw new Error('Editor no disponible'); el.focus(); })()`);
      await contents.focus();
      abortCheck(signal);   // cancelado (p. ej. durante la aprobación): no se escribe nada
      await assertOrigin(contents, GEMINI_ORIGIN);
      await contents.insertText(wire);
      let inserted = await this.waitForDraft(wire, signal);
      if (inserted.draft !== null && !inserted.draft.trim()) {
        await this.evaluate(`(() => { const el=[...document.querySelectorAll(${JSON.stringify(EDITOR)})].find(e=>e.getClientRects().length); if(!el) throw new Error('Editor no disponible'); el.focus(); document.execCommand('insertText', false, ${JSON.stringify(wire)}); })()`);
        inserted = await this.waitForDraft(wire, signal);
      }
      if (inserted.blocked || inserted.draft === null || normalize(inserted.draft) !== normalize(wire)) {
        if (inserted.draft && normalize(inserted.draft).startsWith(head)) await this.clearOwnDraft(signal);
        throw new Error('Gemini no confirmó el texto; no se ha enviado.');
      }
      submitted = true;
      this.sawStop = false;
      this.lastWire = wire;
      abortCheck(signal);
      await contents.sendInputEvent({ type: 'keyDown', keyCode: 'Enter' });
      await contents.sendInputEvent({ type: 'keyUp', keyCode: 'Enter' });
      const answer = await waitReply(async () => {
        const s = await this.readState();
        if (s.blocked) throw new Error('Gemini requiere intervención manual en su ventana.');
        const users = s.rows.map((row, index) => ({ row, index })).filter(({ row }) => !row.assistant);
        const fresh = users.slice(usersBefore).filter(({ row }) => {
          const shown = normalize(row.text);
          // Gemini antepone una etiqueta ("Has dicho", "You said") y puede repetir el texto:
          // basta con que lo enviado aparezca dentro.
          return shown && shown.includes(head);
        });
        if (!fresh.length) return [];
        if (fresh.length > 1) throw new Error('Aparecieron varios mensajes iguales nuevos en Gemini; no se atribuye una respuesta ambigua.');
        const mine = fresh[0];
        const following = s.rows[mine.index + 1];
        if (!following) return [];
        if (!following.assistant) throw new Error('El turno de Gemini se modificó fuera de Eolfi.');
        return [following];
      }, baseline, signal, REPLY_TIMEOUT_MS, 250, 'Gemini', onPartial);
      // Gemini a veces vuelve a poner el texto enviado en el editor tras responder:
      // si el borrador es exactamente lo que enviamos, es nuestro y se limpia.
      const after = await this.readState().catch(() => null);
      if (after?.draft && normalize(after.draft) === normalize(wire)) await this.clearOwnDraft(signal).catch(() => {});
      const url = contents.getURL();
      this.lastUrl = url;
      if (isGeminiUrl(url) && /^\/app\/[\w-]{6,}/.test(new URL(url).pathname)) {   // «/app» a secas es un chat nuevo
        this.urls.set(conversation, url);
        if (this.urls.size > 64) this.urls.delete(this.urls.keys().next().value);
      }
      return answer;
    } catch (error) {
      if (submitted) this.uncertain.add(conversation);
      throw error;
    } finally { this.active = false; }
  }

  async ready(signal) {
    for (let i = 0; i < 60; i++) {
      const s = await this.readState();
      if (s.blocked || s.draft !== null) return s;
      await sleep(250, signal);
    }
    throw new Error('No aparece el editor de Gemini: inicia sesión en su ventana.');
  }

  // Espera a que el número de turnos deje de cambiar (la conversación terminó de pintarse).
  async settle(signal) {
    let last = await this.readState();
    let same = 0;
    for (let i = 0; i < 25 && same < 3; i++) {
      await sleep(200, signal);
      const s = await this.readState();
      same = s.rows.length === last.rows.length && s.draft !== null ? same + 1 : 0;
      last = s;
    }
    return last;
  }

  async waitForDraft(expected, signal) {
    let s = { rows: [], draft: null, blocked: false };
    for (let i = 0; i < 20; i++) {
      s = await this.readState();
      if (s.blocked || s.draft === null || normalize(s.draft) === normalize(expected)) return s;
      await sleep(100, signal);
    }
    return s;
  }

  async clearOwnDraft(signal) {
    await this.evaluate(`(() => { const el=[...document.querySelectorAll(${JSON.stringify(EDITOR)})].find(e=>e.getClientRects().length); if(!el) throw new Error('Editor no disponible'); el.focus(); document.execCommand('selectAll', false); document.execCommand('delete', false); })()`);
    const cleared = await this.waitForDraft('', signal);
    if (cleared.draft === null || cleared.draft.trim()) throw new Error('No se pudo limpiar el borrador técnico de Gemini; vacíalo a mano.');
  }

  evaluate(script) {
    return evaluateIn(this.contents, GEMINI_ORIGIN, script, 'Gemini');
  }

  async readState() {
    const raw = await this.evaluate(`(() => {
      const visible = el => !!el.getClientRects().length;
      const input = [...document.querySelectorAll(${JSON.stringify(EDITOR)})].find(visible);
      const choose = sels => { for (const s of sels) { const n = [...document.querySelectorAll(s)].filter(visible); if (n.length) return n; } return []; };
      const assistants = new Set(choose(${JSON.stringify(ASSISTANT)}));
      const users = new Set(choose(${JSON.stringify(USER)}));
      const rows = [...new Set([...assistants, ...users])].sort((a, b) => a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1);
      const stop = [...document.querySelectorAll('button,[role="button"]')].some(el => visible(el) && /^(stop|detener|parar)/i.test((el.getAttribute('aria-label') || el.getAttribute('title') || '').trim()));
      return { draft: input ? ('value' in input ? input.value : input.innerText) : null,
        blocked: [...document.querySelectorAll('[role="dialog"],[aria-modal="true"]')].some(visible), stop,
        rows: rows.map((el, i) => ({ id: el.getAttribute('data-turn-id') || el.getAttribute('data-message-id') || el.id || 'gemini-' + i,
          assistant: assistants.has(el),
          text: (el.querySelector('message-content,.markdown,.markdown-main-panel') || el).innerText || el.textContent || '' })) };
    })()`);
    const now = Date.now();
    if (raw.stop) this.sawStop = true;
    // Si Gemini mostró "Detener respuesta", su desaparición marca el final: basta un margen
    // corto. Si nunca apareció (respuesta instantánea u otra interfaz), texto estable 2,5 s.
    const settle = this.sawStop ? 600 : 2500;
    const rows = raw.rows.map((row) => {
      if (!row.assistant || !row.text.trim()) return { ...row, complete: false };
      const prev = this.stable.get(row.id);
      if (!prev || prev.text !== row.text) this.stable.set(row.id, { text: row.text, since: now });
      return { ...row, complete: !raw.stop && now - this.stable.get(row.id).since >= settle };
    });
    if (this.stable.size > 100) this.stable.delete(this.stable.keys().next().value);
    return { rows, draft: raw.draft, blocked: raw.blocked };
  }
}
