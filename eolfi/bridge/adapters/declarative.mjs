// Adaptador DECLARATIVO (Fase E, grupo 3): un chat web se describe con selectores (con alternativas) en
// sites.json, y se puede recalibrar sin tocar código con ~/.eolfi/bridge-sites.json (se fusiona encima).
//
// - selftest(): comprueba en la página real qué selectores responden, SIN escribir ni enviar nada.
// - send(): escribe, comprueba el texto, envía y espera la respuesta nueva con streaming (onPartial).
// Solo interfaz visible: no lee cookies ni llama a endpoints privados.
import { readFileSync, existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { MAX_WIRE, REPLY_TIMEOUT_MS, abortCheck, assertOrigin, ensureConversation, evaluateIn, sleep, unixNewlines, waitReply } from './core.mjs';

const BUILTIN = JSON.parse(readFileSync(new URL('./sites.json', import.meta.url), 'utf8'));
export const OVERRIDES_FILE = process.env.EOLFI_BRIDGE_SITES || join(homedir(), '.eolfi', 'bridge-sites.json');
const GROUPS = ['editor', 'send', 'stop', 'user', 'assistant', 'loggedOut', 'blocked'];
const normalize = (v) => String(v).normalize('NFC').replace(/[​﻿]/g, '').replace(/\s+/g, ' ').trim();

// Configuración efectiva: la incluida + lo que el usuario recalibre (solo claves conocidas y listas de cadenas).
export function loadSites(file = OVERRIDES_FILE) {
  const sites = structuredClone(BUILTIN);
  if (existsSync(file)) {
    let extra = {};
    try { extra = JSON.parse(readFileSync(file, 'utf8')); } catch (e) { console.error(`${file}: JSON inválido (${e.message})`); }
    for (const [name, cfg] of Object.entries(extra || {})) {
      if (!Object.hasOwn(sites, name) || typeof cfg !== 'object' || !cfg) continue;   // no se añaden orígenes nuevos
      for (const g of [...GROUPS, 'idAttr']) {
        if (Array.isArray(cfg[g]) && cfg[g].every((x) => typeof x === 'string' && x.length < 400)) sites[name][g] = cfg[g];
      }
      if (cfg.submit === 'enter' || cfg.submit === 'button') sites[name].submit = cfg.submit;
      if (typeof cfg.completeAttr === 'string' && /^[\w-]{1,60}$/.test(cfg.completeAttr)) sites[name].completeAttr = cfg.completeAttr;
      if (cfg.completeWithin && typeof cfg.completeWithin.container === 'string' && typeof cfg.completeWithin.selector === 'string'
          && cfg.completeWithin.container.length < 300 && cfg.completeWithin.selector.length < 400) {
        sites[name].completeWithin = { container: cfg.completeWithin.container, selector: cfg.completeWithin.selector };
      }
      sites[name].recalibrated = true;
    }
  }
  return sites;
}

export function isSiteUrl(cfg, value) {
  try { const u = new URL(value); return u.origin === cfg.origin && !u.username && !u.password; } catch { return false; }
}

export function makeDeclarativeAdapter(cfg) {
  const J = JSON.stringify;
  const sel = (g) => J((cfg[g] || []).join(','));

  return class DeclarativeAdapter {
    constructor(contents) {
      this.contents = contents;
      this.cfg = cfg;
      this.active = false;
      this.current = null;
      this.urls = new Map();
      this.uncertain = new Set();
      this.label = cfg.title;
    }

    reset(conversation) { return this.uncertain.delete(conversation); }

    evaluate(script) { return evaluateIn(this.contents, cfg.origin, script, cfg.title); }

    // Estado de la página: editor y su texto, mensajes con identidad, ¿respondiendo?, ¿sin sesión?, ¿diálogo?
    readState() {
      return this.evaluate(`(() => {
        const vis = (el) => !!el && !!el.getClientRects().length;
        const first = (q) => q ? [...document.querySelectorAll(q)].find(vis) : null;
        const ed = first(${sel('editor')});
        const idOf = (el, i, kind) => { for (const a of ${J(cfg.idAttr || [])}) { const v = el.getAttribute(a) || el.closest('[' + a + ']')?.getAttribute(a); if (v) return kind + ':' + v; } return kind + '#' + i; };
        const doneQ = ${J(cfg.completeAttr ? `[${cfg.completeAttr}]` : '')};
        const within = ${J(cfg.completeWithin || null)};
        const done = (el) => (!doneQ || el.matches(doneQ) || !!el.querySelector(doneQ) || !!el.closest(doneQ))
          && (!within || !!el.closest(within.container)?.querySelector(within.selector));
        const rows = (q, kind) => q ? [...document.querySelectorAll(q)].filter(vis).map((el, i) => ({ id: idOf(el, i, kind), text: (el.innerText || '').trim(), done: done(el) })) : [];
        const stop = first(${sel('stop')});
        return {
          draft: ed ? ('value' in ed ? ed.value : ed.innerText) : null,
          users: rows(${sel('user')}, 'u'), replies: rows(${sel('assistant')}, 'a'),
          streaming: !!stop,
          loggedOut: !!first(${sel('loggedOut')}),
          blocked: !!first(${sel('blocked')}),
        };
      })()`);
    }

    // Autodiagnóstico: cuántos elementos visibles casan con CADA selector. No escribe nada.
    // Candidatos para recalibrar: editores, botones y atributos «de mensaje», con su recuento. Solo nombres y
    // valores de ATRIBUTOS (data-testid, aria-label, role…), nunca el texto de los mensajes.
    async discover() {
      return this.evaluate(`(() => {
        const vis = (e) => e.getClientRects().length > 0;
        const attrs = (e) => Object.fromEntries([...e.attributes].filter((a) => /^(id|name|role|type|placeholder|aria-label|data-[\\w-]+|contenteditable)$/.test(a.name))
          .map((a) => [a.name, a.value.slice(0, 80)]));
        const editors = [...document.querySelectorAll('textarea, [contenteditable="true"], input[type="text"]')].filter(vis)
          .slice(0, 10).map((e) => ({ tag: e.tagName.toLowerCase(), ...attrs(e) }));
        const buttons = [...document.querySelectorAll('button, [role="button"]')].filter(vis)
          .map((e) => ({ tag: e.tagName.toLowerCase(), ...attrs(e) }))
          .filter((b) => b['data-testid'] || b['aria-label'] || b.id).slice(0, 60);
        const marks = {};
        for (const e of document.querySelectorAll('*')) {
          for (const a of e.attributes) {
            if (/message|author|turn|role|chat|response|answer|conversation/i.test(a.name) && a.name.startsWith('data-')) {
              const key = a.value.length < 40 && !/^[\\w-]{20,}$/.test(a.value) ? a.name + '=' + a.value : a.name;
              marks[key] = (marks[key] || 0) + 1;
            }
          }
          if (Object.keys(marks).length > 200) break;
        }
        return { url: location.pathname, editors, buttons, message_attributes: marks };
      })()`);
    }

    async selftest() {
      const url = this.contents.isDestroyed() ? '' : this.contents.getURL();
      if (!isSiteUrl(cfg, url)) return { ok: false, url, detail: `la pestaña no está en ${cfg.origin}` };
      const groups = await this.evaluate(`(() => {
        const out = {};
        for (const [g, list] of Object.entries(${J(Object.fromEntries(GROUPS.map((g) => [g, cfg[g] || []])))})) {
          out[g] = list.map((q) => { try { return { selector: q, visible: [...document.querySelectorAll(q)].filter((e) => e.getClientRects().length).length }; }
            catch { return { selector: q, error: 'selector inválido' }; } });
        }
        return out;
      })()`);
      const any = (g) => groups[g].some((x) => x.visible > 0);
      const problems = [];
      if (!any('editor')) problems.push('no se encuentra el editor (¿sin sesión o selectores desfasados?)');
      if (cfg.submit === 'button' && !any('send') && !any('stop')) problems.push('no se encuentra el botón de enviar');
      if (any('loggedOut')) problems.push('parece que no hay sesión iniciada');
      if (any('blocked')) problems.push('hay un diálogo abierto que bloquea la página');
      return { ok: problems.length === 0, url, calibrated: !!(cfg.calibrated || cfg.recalibrated), problems, groups,
        overrides: OVERRIDES_FILE };
    }

    async status() {
      const url = this.contents.isDestroyed() ? '' : this.contents.getURL();
      if (!isSiteUrl(cfg, url)) return { ok: false, detail: `La ventana no está en ${cfg.origin}: inicia sesión allí o vuelve al chat` };
      try {
        const s = await this.readState();
        const note = cfg.calibrated || cfg.recalibrated ? '' : ' · selectores sin calibrar: usa «Autodiagnóstico»';
        if (s.blocked) return { ok: false, detail: `Cierra el diálogo abierto en ${cfg.title}${note}` };
        if (s.draft === null) return { ok: false, detail: `No se encuentra el editor de ${cfg.title}: inicia sesión o recalibra${note}` };
        return { ok: true, signedIn: !s.loggedOut, detail: `${cfg.title} listo${s.loggedOut ? ' · modo invitado' : ' · con sesión'}${note}` };
      } catch { return { ok: false, detail: `${cfg.title} aún carga o necesita iniciar sesión` }; }
    }

    async ready(signal) {
      for (let i = 0; i < 80; i++) {
        const s = await this.readState().catch(() => null);
        if (s && (s.blocked || s.draft !== null)) return s;
        await sleep(250, signal);
      }
      throw new Error(`No aparece el editor de ${cfg.title}: inicia sesión en su ventana o recalibra el adaptador.`);
    }

    async send(prompt, signal, conversation = 'default', onPartial = null) {
      prompt = unixNewlines(prompt);
      if (this.active) throw new Error(`${cfg.title} ya está respondiendo otra petición.`);
      if (this.uncertain.has(conversation)) throw new Error(`El turno anterior de ${cfg.title} quedó interrumpido; inicia una conversación nueva para no duplicarlo.`);
      if (!prompt.trim() || prompt.length > MAX_WIRE) throw new Error(`La petición supera el límite del puente (${MAX_WIRE} caracteres).`);
      this.active = true;
      let submitted = false;
      try {
        const contents = this.contents;
        await contents.focus?.();
        if (!isSiteUrl(cfg, contents.getURL())) throw new Error(`Inicia sesión en ${cfg.title} en la ventana del puente y vuelve a enviar.`);
        await ensureConversation(this, contents, conversation, cfg.home);
        const before = await this.ready(signal);
        if (before.blocked) throw new Error(`${cfg.title} requiere intervención manual en su ventana.`);
        if (before.draft.trim()) throw new Error(`Hay un borrador escrito en ${cfg.title}. Envíalo o vacíalo antes.`);
        if (before.streaming) throw new Error(`${cfg.title} todavía está respondiendo.`);
        const replyBaseline = new Set(before.replies.map((r) => r.id));
        const userBaseline = new Set(before.users.map((r) => r.id));
        await this.evaluate(`(() => { const el=[...document.querySelectorAll(${sel('editor')})].find(e=>e.getClientRects().length); if(!el) throw new Error('Editor no disponible'); el.focus(); })()`);
        abortCheck(signal);   // cancelado (p. ej. durante la aprobación): no se escribe nada
        await assertOrigin(contents, cfg.origin);
        await contents.insertText(prompt);
        const typed = await this.readState();
        if (normalize(typed.draft ?? '') !== normalize(prompt)) throw new Error(`${cfg.title} no confirmó el texto; no se ha enviado.`);
        abortCheck(signal);
        submitted = true;
        if (cfg.submit === 'button') {
          await this.evaluate(`(() => { const b=[...document.querySelectorAll(${sel('send')})].find(e=>e.getClientRects().length); if(!b||b.disabled||b.getAttribute('aria-disabled')==='true') throw new Error('Enviar no está disponible'); b.click(); })()`);
        } else {
          await contents.sendInputEvent({ type: 'keyDown', keyCode: 'Enter' });
          await contents.sendInputEvent({ type: 'keyUp', keyCode: 'Enter' });
        }
        const head = normalize(prompt).slice(0, 60);
        const text = await waitReply(async () => {
          const s = await this.readState();
          if (s.blocked) throw new Error(`${cfg.title} requiere intervención manual en su ventana.`);
          const mine = s.users.filter((r) => !userBaseline.has(r.id));
          if (mine.length > 1) throw new Error(`La conversación de ${cfg.title} recibió mensajes fuera de Eolfi.`);
          if (mine.length === 1 && mine[0].text && !normalize(mine[0].text).startsWith(head.slice(0, 30))) {
            throw new Error(`El mensaje visible en ${cfg.title} no es el de esta petición.`);
          }
          // Completa = sin botón de parar; además waitReply exige que el texto no cambie entre lecturas.
          return s.replies.filter((r) => !replyBaseline.has(r.id)).map((r) => ({ ...r, complete: !s.streaming && r.done }));
        }, new Set(), signal, REPLY_TIMEOUT_MS, 300, cfg.title, onPartial);
        const url = contents.getURL();
        this.lastUrl = url;
        if (isSiteUrl(cfg, url) && cfg.conversationPath && new RegExp(cfg.conversationPath).test(new URL(url).pathname)) {
          this.urls.set(conversation, url);
          if (this.urls.size > 64) this.urls.delete(this.urls.keys().next().value);
        }
        return text;
      } catch (error) {
        if (submitted) this.uncertain.add(conversation);
        throw error;
      } finally { this.active = false; }
    }
  };
}
