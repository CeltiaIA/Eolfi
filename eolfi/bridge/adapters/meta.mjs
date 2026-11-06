// Adaptador de Meta AI web (www.meta.ai) portado de Force/metaBrowser.ts.
// Solo interfaz visible: no lee cookies ni llama a endpoints privados.
import { randomUUID } from 'node:crypto';
import { MAX_WIRE, evaluateIn, freshReply, sleep, waitReply, abortCheck, assertOrigin, ensureConversation, unixNewlines, REPLY_TIMEOUT_MS } from './core.mjs';

export const META_ORIGIN = 'https://www.meta.ai';
const EDITOR = '[data-testid="composer-input"][contenteditable="true"][role="textbox"],textarea[data-testid="composer-input"],input[aria-label="Pregunta a Meta AI"],input[aria-label="Ask Meta AI"]';
const ASSISTANT = '[data-message-role="assistant"][data-message-id]';
const USER = '[data-message-role="user"][data-message-id]';
const COMPLETED = '[data-testid="assistant-message"][data-streaming-state="DONE"][data-streaming-complete="true"]';

export function isMetaUrl(value) {
  try { const u = new URL(value); return u.origin === META_ORIGIN && !u.username && !u.password; } catch { return false; }
}

export class MetaAdapter {
  constructor(contents) {
    this.contents = contents;
    this.active = false;
    this.current = null;
    this.urls = new Map();
    this.uncertain = new Set();
    this.label = 'Meta AI';
  }

  async status() {
    const url = this.contents.isDestroyed() ? '' : this.contents.getURL();
    if (!isMetaUrl(url)) {
      let host = url;
      try { host = new URL(url).host; } catch { /* about:blank */ }
      return { ok: false, detail: `La ventana está en ${host || 'una página vacía'}: inicia sesión allí o vuelve al chat` };
    }
    try {
      const s = await this.readState(false);   // consultar el estado no debe pulsar «Raw» ni nada (B5)
      return s.draft !== null && !s.blocked
        ? await this.withSession({ ok: true, detail: 'Meta AI web listo' })
        : { ok: false, detail: 'Inicia sesión o acepta las condiciones en la ventana de Meta AI' };
    } catch { return { ok: false, detail: 'Meta AI aún carga o necesita iniciar sesión' }; }
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
    if (this.active) throw new Error('Meta AI ya tiene una petición activa.');
    if (this.uncertain.has(conversation)) throw new Error('El turno de Meta AI quedó interrumpido; inicia una conversación nueva para no duplicarlo.');
    const requestId = randomUUID();
    const wire = `${prompt}\n\n(id técnico de Eolfi, no lo menciones: ${requestId})`;
    if (!prompt.trim() || wire.length > MAX_WIRE) throw new Error(`La petición supera el límite del puente (${MAX_WIRE} caracteres).`);
    this.active = true;
    let submitted = false;
    try {
      const contents = this.contents;
      await contents.focus();   // restaura la ventana si está minimizada: oculta no se pinta
      if (!isMetaUrl(contents.getURL())) throw new Error('Inicia sesión en Meta AI en la ventana del puente y vuelve a enviar.');
      await ensureConversation(this, contents, conversation, META_ORIGIN);
      const previous = await this.ready(signal);
      if (previous.blocked || previous.draft === null) throw new Error('Completa el acceso a Meta AI en su ventana.');
      if (previous.draft.trim()) throw new Error('Hay un borrador escrito en Meta AI. Envíalo o vacíalo antes.');
      const baseline = new Set(previous.replies.map((r) => r.id));
      freshReply(baseline, previous.replies);
      if (previous.replies.some((r) => !r.complete)) throw new Error('Meta AI todavía está respondiendo.');
      await this.evaluate(`(() => { const el=[...document.querySelectorAll(${JSON.stringify(EDITOR)})].find(e=>e.getClientRects().length); if(!el) throw new Error('Editor no disponible'); el.focus(); })()`);
      await contents.focus();
      abortCheck(signal);   // cancelado (p. ej. durante la aprobación): no se escribe nada
      await assertOrigin(contents, META_ORIGIN);
      await contents.insertText(wire);
      const inserted = await this.readState();
      if (inserted.blocked || inserted.draft?.trim() !== wire.trim()) throw new Error('Meta AI no confirmó el texto; no se ha enviado.');
      const userBaseline = new Set(previous.users.map((r) => r.id));
      // «Enviado» solo tras el clic: si Enviar está deshabilitado no se ha mandado nada.
      await this.evaluate(`(() => { if (document.querySelector('[role="dialog"],[aria-modal="true"]')) throw new Error('Meta requiere intervención manual'); const b=document.querySelector('button[data-testid="composer-send-button"],button[aria-label="Enviar"],button[aria-label="Send"]'); if(!b||b.disabled||!b.getClientRects().length) throw new Error('Meta no ha habilitado Enviar'); b.click(); })()`);
      submitted = true;
      let turn = null;
      const text = await waitReply(async () => {
        const s = await this.readState();
        if (s.blocked) throw new Error('Meta AI requiere intervención manual en su ventana.');
        const fresh = s.users.filter((r) => !userBaseline.has(r.id));
        if (fresh.length > 1) throw new Error('La conversación de Meta AI recibió mensajes fuera de Eolfi.');
        if (fresh.length === 1 && !fresh[0].text.trim()) return [];
        if (fresh.length === 1 && !fresh[0].text.includes(requestId)) throw new Error('El mensaje visible en Meta AI no es el de esta petición.');
        if (!turn && fresh.length === 1) {
          if (!fresh[0].turn) throw new Error('Meta AI cambió la identidad de los turnos: recalibrar adaptador.');
          turn = fresh[0].turn;
        }
        return turn ? s.replies.filter((r) => r.turn === turn) : [];
      }, baseline, signal, REPLY_TIMEOUT_MS, 250, 'Meta AI', onPartial);
      const url = contents.getURL();
      this.lastUrl = url;
      if (isMetaUrl(url) && new URL(url).pathname.startsWith('/prompt/')) {
        this.urls.set(conversation, url);
        if (this.urls.size > 64) this.urls.delete(this.urls.keys().next().value);
      }
      return text;
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
    throw new Error('No aparece el editor de Meta AI: inicia sesión en su ventana.');
  }

  evaluate(script) {
    return evaluateIn(this.contents, META_ORIGIN, script, 'Meta AI');
  }

  readState(allowClick = true) {
    return this.evaluate(`(() => {
      const allowClick = ${allowClick ? 'true' : 'false'};
      const visible = el => !!el.getClientRects().length;
      const input = [...document.querySelectorAll(${JSON.stringify(EDITOR)})].find(visible);
      const uiLabels = ['mostrar razonamiento','ocultar razonamiento','show reasoning','hide reasoning','pensando','pensando…','pensando...','thinking','thinking…','thinking...','razonando','razonando…','json','tree','raw','▶','▼','copiar','copy','copiar código','copy code'];
      const reasoning = 'details,[data-testid*="reason" i],[data-testid*="thinking" i],[aria-label*="razonamiento" i],[aria-label*="reasoning" i]';
      const clean = node => (node.innerText || '').split('\\n').filter(l => !uiLabels.includes(l.trim().toLowerCase())).join('\\n').trim();
      // Meta muestra los bloques JSON en un visor (pestañas JSON / Tree / Raw) que pliega el
      // contenido. Si está en vista de árbol, se pulsa "Raw" y la respuesta se da por no lista
      // hasta que el texto crudo esté visible (el sondeo siguiente lo lee).
      const showRaw = el => {
        if (!allowClick) return false;
        const tabs = [...el.querySelectorAll('button,[role="tab"]')].filter(b => visible(b) && /^raw$/i.test((b.innerText || '').trim()));
        const tree = [...el.querySelectorAll('button,[role="tab"]')].some(b => visible(b) && /^tree$/i.test((b.innerText || '').trim()));
        if (!tabs.length || !tree) return false;
        const raw = tabs[0];
        const active = raw.getAttribute('aria-selected') === 'true' || raw.getAttribute('data-state') === 'active' || raw.getAttribute('aria-pressed') === 'true';
        if (active) return false;
        if (/^\\s*JSON\\s*\\n\\s*Tree\\s*\\n\\s*Raw/i.test(el.innerText || '') && el.dataset.eolfiRaw !== '1') {
          el.dataset.eolfiRaw = '1';
          raw.click();
          return true;
        }
        return false;
      };
      const replyText = el => {
        if (showRaw(el)) return '';
        const parts = [...el.querySelectorAll('.markdown-content')].filter(n => !n.closest(reasoning) && !n.parentElement?.closest('.markdown-content'));
        if (!parts.length) return '';
        const whole = parts.map(clean).filter(Boolean).join('\\n\\n');
        const blocks = parts.length === 1 ? parts[0].querySelectorAll('pre code') : [];
        if (blocks.length === 1) {
          const code = blocks[0], literal = code.textContent || '';
          const outside = whole.replace(code.innerText || literal, '').trim();
          if (/^(?:(?:json|Copiar(?: código)?|Copy(?: code)?|Código|Code)\\s*)*$/i.test(outside)) return literal;
        }
        return whole;
      };
      return {
        draft: input ? ('value' in input ? input.value : input.innerText) : null,
        blocked: [...document.querySelectorAll('[role="dialog"],[aria-modal="true"]')].some(visible),
        replies: [...document.querySelectorAll(${JSON.stringify(ASSISTANT)})].map(el => ({
          id: el.getAttribute('data-message-id') || '', turn: el.getAttribute('data-turn-id') || '',
          text: replyText(el), complete: !!el.querySelector(${JSON.stringify(COMPLETED)}) })),
        users: [...document.querySelectorAll(${JSON.stringify(USER)})].map(el => ({
          id: el.getAttribute('data-message-id') || '', turn: el.getAttribute('data-turn-id') || '',
          text: el.querySelector('[data-message-type="user"] [data-slot="text"]')?.textContent || '' }))
      };
    })()`);
  }
}
