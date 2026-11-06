// Adaptador de DeepSeek web (chat.deepseek.com) portado de Force/deepseekBrowser.ts.
// Usa solo la interfaz visible (editor y DOM): no lee cookies ni llama a endpoints privados.
// El inicio de sesión lo hace el usuario a mano en la ventana del puente.
import { randomUUID } from 'node:crypto';
import { MAX_WIRE, evaluateIn, sleep, waitReply, abortCheck, assertOrigin, ensureConversation, unixNewlines, REPLY_TIMEOUT_MS } from './core.mjs';

export const DEEPSEEK_ORIGIN = 'https://chat.deepseek.com';
// Independiente del idioma de la interfaz: name="search" / #chat-input; los placeholder son solo respaldo.
const EDITOR = 'textarea[name="search"],textarea#chat-input,textarea[placeholder="Mensaje a DeepSeek"],textarea[placeholder="Message DeepSeek"]';

export function isDeepseekUrl(value) {
  try { const u = new URL(value); return u.origin === DEEPSEEK_ORIGIN && !u.username && !u.password; } catch { return false; }
}

export class DeepseekAdapter {
  constructor(contents) {
    this.contents = contents;
    this.active = false;
    this.current = null;
    this.urls = new Map();
    this.uncertain = new Set();
    this.label = 'DeepSeek';
  }

  async status() {
    const url = this.contents.isDestroyed() ? '' : this.contents.getURL();
    if (!isDeepseekUrl(url)) {
      let host = url;
      try { host = new URL(url).host; } catch { /* about:blank */ }
      return { ok: false, detail: `La ventana está en ${host || 'una página vacía'}: inicia sesión allí o vuelve al chat` };
    }
    try {
      const s = await this.readState();
      return s.draft !== null && !s.blocked
        ? await this.withSession({ ok: true, detail: 'DeepSeek web listo' })
        : { ok: false, detail: 'Inicia sesión o cierra los avisos en la ventana de DeepSeek' };
    } catch { return { ok: false, detail: 'DeepSeek aún carga o necesita iniciar sesión' }; }
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
    if (this.active) throw new Error('DeepSeek ya está respondiendo otra petición.');
    if (this.uncertain.has(conversation)) throw new Error('El turno anterior de DeepSeek quedó interrumpido; inicia una conversación nueva para no duplicarlo.');
    const reference = randomUUID();
    const wire = `Referencia de este envío: ${reference}\n${prompt}`;
    if (!prompt.trim() || wire.length > MAX_WIRE) throw new Error(`La petición supera el límite del puente (${MAX_WIRE} caracteres).`);
    this.active = true;
    let submitted = false;
    try {
      const contents = this.contents;
      await contents.focus();   // restaura la ventana si está minimizada: oculta no se pinta
      if (!isDeepseekUrl(contents.getURL()) || new URL(contents.getURL()).pathname.startsWith('/sign_in')) {
        throw new Error('Inicia sesión en DeepSeek en la ventana del puente y vuelve a enviar.');
      }
      await ensureConversation(this, contents, conversation, `${DEEPSEEK_ORIGIN}/`);
      const state = await this.ready(signal);
      if (state.blocked || state.draft === null) throw new Error('Completa el acceso o los avisos de DeepSeek en su ventana.');
      if (state.draft.trim()) throw new Error('Hay un borrador escrito en DeepSeek. Envíalo o vacíalo antes.');
      if (state.rows.some((r) => r.assistant && !r.complete)) throw new Error('DeepSeek aún está generando otra respuesta.');
      await this.evaluate(`(() => { const el=[...document.querySelectorAll(${JSON.stringify(EDITOR)})].find(e=>e.getClientRects().length); if(!el) throw new Error('Editor no disponible'); el.focus(); })()`);
      await contents.focus();
      abortCheck(signal);   // cancelado (p. ej. durante la aprobación): no se escribe nada
      await assertOrigin(contents, DEEPSEEK_ORIGIN);
      await contents.insertText(wire);
      if ((await this.readState()).draft?.trim() !== wire.trim()) throw new Error('DeepSeek no confirmó el texto; no se ha enviado.');
      submitted = true;
      abortCheck(signal);
      await contents.sendInputEvent({ type: 'keyDown', keyCode: 'Enter' });
      await contents.sendInputEvent({ type: 'keyUp', keyCode: 'Enter' });
      const answer = await waitReply(async () => {
        const next = await this.readState();
        if (next.blocked) throw new Error('DeepSeek requiere intervención manual en su ventana.');
        const matching = next.rows.map((row, index) => ({ row, index })).filter(({ row }) => !row.assistant && row.text.includes(reference));
        if (matching.length > 1) throw new Error('DeepSeek muestra la referencia de envío duplicada.');
        if (!matching.length) return [];
        const tail = next.rows.slice(matching[0].index + 1);
        const following = tail.find((r) => r.assistant);
        const otherUser = tail.find((r) => !r.assistant && r.text.trim());
        if (otherUser && (!following || tail.indexOf(otherUser) < tail.indexOf(following))) throw new Error('El turno de DeepSeek se modificó fuera de Eolfi.');
        if (!following) return [];
        return [{ id: following.key, text: following.text, complete: following.complete }];
      }, new Set(), signal, REPLY_TIMEOUT_MS, 250, 'DeepSeek', onPartial);
      const url = contents.getURL();
      this.lastUrl = url;
      if (isDeepseekUrl(url) && new URL(url).pathname.startsWith('/a/chat/s/')) {
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
    throw new Error('No aparece el editor de DeepSeek: inicia sesión en su ventana.');
  }

  evaluate(script) {
    return evaluateIn(this.contents, DEEPSEEK_ORIGIN, script, 'DeepSeek');
  }

  readState() {
    return this.evaluate(`(() => {
      const visible = el => !!el.getClientRects().length;
      const input = [...document.querySelectorAll(${JSON.stringify(EDITOR)})].find(visible);
      return { draft: input ? input.value : null,
        blocked: [...document.querySelectorAll('[role="dialog"],[aria-modal="true"]')].some(visible),
        rows: [...document.querySelectorAll('[data-virtual-list-item-key]')].filter(r => r.querySelector('.ds-message')).map(r => {
          const answer = r.querySelector('.ds-assistant-message-main-content'), message = r.querySelector('.ds-message');
          return { key: r.getAttribute('data-virtual-list-item-key') || '', assistant: !!answer,
            text: answer ? answer.innerText : (message.textContent || ''),
            // Respuesta terminada = aparece su barra de acciones (copiar, regenerar, valorar, leer, compartir…):
            // varios botones de icono juntos. No depende del idioma (antes: aria-label «Leer en voz alta»).
            complete: !!answer && ([...r.querySelectorAll('.ds-button--iconLabelTertiary[role="button"]')]
              .filter(visible).length >= 4 || !!r.querySelector('[aria-label="Leer en voz alta"],[aria-label="Read aloud"]')) };
        }) };
    })()`);
  }
}
