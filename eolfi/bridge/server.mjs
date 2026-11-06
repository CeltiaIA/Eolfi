// Pasarela local del puente: Eolfi (Python) -> adaptadores de chat web.
// Independiente de Electron para poder probarla con `node --test`.
//
// Seguridad:
// - Solo escucha en 127.0.0.1 y exige Host de loopback (frena DNS rebinding).
// - Dos credenciales aleatorias (Authorization: Bearer, en bridge.json):
//   · token: Eolfi automático; solo /v1/status, /v1/events y /v1/chat CON aprobación.
//   · panelToken: el panel; además /v1/screen, /v1/input y mensajes tecleados sin aprobación.
// - Un proveedor ocupado responde 409; la aprobación caduca a los 2 minutos (= denegada).
// - Cada envío necesita aprobación del usuario (approve) salvo permiso temporal.
// - Cuerpo máximo 128 KB; si el cliente corta la conexión, el envío se cancela.
// - Los mensajes que escribe el usuario desde el panel (source: "panel") no piden
//   aprobación: los ha tecleado él. Los automáticos de Eolfi sí.
//
// Además expone, para el panel web de Eolfi:
// - GET /v1/events?since=N  historial de mensajes (envíos, respuestas, errores).
// - GET /v1/screen?provider=X  captura JPEG de la ventana de ese chat.
// - POST /v1/input  clic / rueda / tecla / texto del usuario sobre esa captura.
import { createServer } from 'node:http';
import { timingSafeEqual } from 'node:crypto';

const MAX_BODY = 128 * 1024;
const MAX_EVENTS = 200;   // con textos de hasta 20-50 KB: unos 6 MB como mucho
const LOOPBACK = new Set(['127.0.0.1', 'localhost', '[::1]']);
const APPROVE_TIMEOUT_MS = 120_000;

function json(res, status, obj) {
  const body = Buffer.from(JSON.stringify(obj));
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': body.length, 'Cache-Control': 'no-store' });
  res.end(body);
}

function sameToken(given, token) {
  const a = Buffer.from(String(given || '')), b = Buffer.from(token);
  return a.length === b.length && timingSafeEqual(a, b);
}

export function startBridgeServer({ adapters, approve, token, panelToken, port = 0, host = '127.0.0.1', log = () => {}, screens = {}, info = () => ({}), inputs = {}, approveTimeoutMs = APPROVE_TIMEOUT_MS, revoke = null }) {
  if (!token || token.length < 32) throw new Error('token demasiado corto');
  // B1: sin modo heredado. Las dos credenciales son obligatorias y distintas.
  if (!panelToken || panelToken.length < 32 || panelToken === token) throw new Error('panelToken inválido u omitido');
  const events = [];
  const partials = new Map();   // «proveedor|conversación» → { text, ts }: lo que el chat lleva escrito
  let nextId = 1;
  const busy = new Set();
  const record = (evt) => {
    events.push({ id: nextId++, ts: Date.now(), ...evt });
    if (events.length > MAX_EVENTS) events.shift();
  };
  const server = createServer((req, res) => {
    const rawHost = String(req.headers.host || '').toLowerCase();
    const hostName = rawHost.startsWith('[') ? rawHost.slice(0, rawHost.indexOf(']') + 1) : rawHost.split(':')[0];
    if (!LOOPBACK.has(hostName)) return json(res, 421, { error: 'Host no permitido' });
    const given = (req.headers.authorization || '').replace(/^Bearer\s+/i, '');
    const isPanel = sameToken(given, panelToken);
    if (!isPanel && !sameToken(given, token)) return json(res, 401, { error: 'token inválido' });
    const url = new URL(req.url, 'http://127.0.0.1');

    if (req.method === 'GET' && url.pathname === '/v1/status') {
      Promise.all(Object.entries(adapters).map(async ([name, get]) => {
        try { return [name, { ...(await (await get({ peek: true })).status()), busy: busy.has(name) }]; }
        catch (e) { return [name, { ok: false, detail: String(e.message || e), busy: busy.has(name) }]; }
      })).then((rows) => json(res, 200, { ok: true, ...info(), providers: Object.fromEntries(rows) }));
      return;
    }

    if (req.method === 'GET' && url.pathname === '/v1/events') {
      const since = Number(url.searchParams.get('since') || 0);
      if (!Number.isFinite(since) || since < 0) return json(res, 400, { error: 'since inválido' });
      return json(res, 200, { events: events.filter((e) => e.id > since), last: nextId - 1,
        partials: [...partials.entries()].map(([k, v]) => ({ provider: k.split('|')[0], conversation: k.split('|')[1], ...v })) });
    }

    if ((url.pathname === '/v1/screen' || url.pathname === '/v1/input') && !isPanel) {
      return json(res, 403, { error: 'solo el panel puede ver o controlar la ventana' });
    }

    if (req.method === 'GET' && url.pathname === '/v1/screen') {
      const name = url.searchParams.get('provider');
      if (!Object.hasOwn(screens, name)) return json(res, 404, { error: 'sin captura para ese proveedor' });
      Promise.resolve().then(() => screens[name]()).then((jpeg) => {
        res.writeHead(200, { 'Content-Type': 'image/jpeg', 'Content-Length': jpeg.length, 'Cache-Control': 'no-store' });
        res.end(jpeg);
      }).catch((e) => json(res, e?.status || 502, { error: String(e?.message || e) }));   // 404: ventana cerrada (M1)
      return;
    }

    // Autodiagnóstico de selectores (no escribe nada): qué partes de la página encuentra el adaptador.
    if (req.method === 'GET' && url.pathname === '/v1/selftest') {
      const name = url.searchParams.get('provider');
      if (!Object.hasOwn(adapters, name)) return json(res, 404, { error: `proveedor desconocido: ${name}` });
      Promise.resolve().then(() => adapters[name]({ peek: true })).then(async (a) => {
        if (typeof a.selftest === 'function') {
          const out = { provider: name, declarative: true, ...(await a.selftest()) };
          if (url.searchParams.get('discover') === '1' && typeof a.discover === 'function') out.discover = await a.discover();
          return json(res, 200, out);
        }
        const st = await a.status();   // adaptadores clásicos: su comprobación de estado
        return json(res, 200, { provider: name, declarative: false, ok: !!st.ok, problems: st.ok ? [] : [st.detail], detail: st.detail });
      }).catch((e) => json(res, e?.status || 502, { error: String(e?.message || e) }));
      return;
    }

    // Comparativa: el MISMO mensaje a varios chats en paralelo, con UNA sola aprobación.
    if (req.method === 'POST' && url.pathname === '/v1/compare') {
      const chunks = [];
      let size = 0;
      req.on('data', (c) => { size += c.length; if (size <= MAX_BODY) chunks.push(c); });
      req.on('end', async () => {
        if (size > MAX_BODY) return json(res, 413, { error: 'petición demasiado grande' });
        let body;
        try { body = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { return json(res, 400, { error: 'JSON inválido' }); }
        const names = Array.isArray(body?.providers) ? [...new Set(body.providers)].filter((p) => typeof p === 'string') : [];
        const prompt = body?.prompt;
        if (names.length < 2 || names.length > 6 || !names.every((p) => Object.hasOwn(adapters, p))) {
          return json(res, 400, { error: 'providers debe tener entre 2 y 6 chats conocidos' });
        }
        if (typeof prompt !== 'string' || !prompt.trim()) return json(res, 400, { error: 'falta prompt' });
        const conv = typeof body.conversation === 'string' && /^[\w-]{1,64}$/.test(body.conversation) ? body.conversation : 'compare';
        const source = body?.source === 'panel' && isPanel ? 'panel' : 'eolfi';
        const free = names.filter((p) => !busy.has(p));
        if (free.length < 2) return json(res, 409, { error: 'menos de dos de esos chats están libres' });
        free.forEach((p) => busy.add(p));
        const controller = new AbortController();
        res.on('close', () => { if (!res.writableEnded) controller.abort(new Error('Eolfi canceló la comparativa')); });
        const approval = new AbortController();
        const expire = setTimeout(() => approval.abort(new Error('aprobación caducada')), approveTimeoutMs);
        expire.unref?.();
        try {
          const allowed = source === 'panel' || await Promise.race([
            Promise.resolve(approve(free.join('+'), prompt, approval.signal, conv)).then((ok) => ok === true && !approval.signal.aborted),
            new Promise((r) => approval.signal.addEventListener('abort', () => r(false), { once: true })),
          ]);
          if (!allowed) return json(res, approval.signal.aborted ? 408 : 403, { error: 'Comparativa no aprobada en el puente' });
          log(`→ comparativa ${free.join(', ')}: ${prompt.length} caracteres`);
          const results = await Promise.all(free.map(async (p) => {
            record({ provider: p, conversation: conv, source, role: 'user', text: prompt.slice(0, 20000), length: prompt.length, compare: true });
            const key = `${p}|${conv}`;
            const t0 = Date.now();
            try {
              const adapter = await adapters[p]();
              const text = await adapter.send(prompt, controller.signal, conv,
                (t) => partials.set(key, { text: t.slice(-30000), length: t.length, ts: Date.now() }));
              record({ provider: p, conversation: conv, source, role: 'assistant', text: text.slice(0, 30000), length: text.length, compare: true });
              return [p, { text, seconds: Math.round((Date.now() - t0) / 100) / 10 }];
            } catch (e) {
              record({ provider: p, conversation: conv, source, role: 'error', text: String(e?.message || e), compare: true });
              return [p, { error: String(e?.message || e) }];
            } finally { partials.delete(key); }
          }));
          json(res, 200, { conversation: conv, results: Object.fromEntries(results),
            skipped_busy: names.filter((p) => !free.includes(p)) });
        } catch (e) {
          if (!res.writableEnded) json(res, 502, { error: String(e?.message || e) });
        } finally {
          clearTimeout(expire);
          if (!approval.signal.aborted) approval.abort(new Error('comparativa terminada'));
          free.forEach((p) => busy.delete(p));
        }
      });
      return;
    }

    // Levantar el estado «dudoso» de una conversación (turno interrumpido) o revocar permisos temporales.
    if (req.method === 'POST' && (url.pathname === '/v1/reset' || url.pathname === '/v1/revoke')) {
      const chunks = [];
      req.on('data', (c) => { if (chunks.reduce((n, x) => n + x.length, 0) < 4096) chunks.push(c); });
      req.on('end', async () => {
        let body;
        try { body = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}'); } catch { return json(res, 400, { error: 'JSON inválido' }); }
        const { provider } = body || {};
        const conv = typeof body?.conversation === 'string' && /^[\w-]{1,64}$/.test(body.conversation) ? body.conversation : null;
        if (!Object.hasOwn(adapters, provider)) return json(res, 404, { error: `proveedor desconocido: ${provider}` });
        if (url.pathname === '/v1/revoke') return json(res, 200, { ok: true, revoked: revoke ? revoke(provider, conv) : 0 });
        try {
          const adapter = await adapters[provider]({ peek: true });
          return json(res, 200, { ok: true, reset: !!adapter.reset?.(conv || 'default') });
        } catch (e) { return json(res, 502, { error: String(e?.message || e) }); }
      });
      return;
    }

    if (req.method === 'POST' && url.pathname === '/v1/input') {
      const chunks = [];
      let got = 0;   // contador acumulado (antes se sumaban todos los trozos en cada uno: O(n²); B2)
      req.on('data', (c) => { if (got < 64 * 1024) { chunks.push(c); got += c.length; } });
      req.on('end', async () => {
        let ev;
        try { ev = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { return json(res, 400, { error: 'JSON inválido' }); }
        if (!Object.hasOwn(inputs, ev?.provider)) return json(res, 404, { error: 'sin entrada para ese proveedor' });
        const inRange = (v) => typeof v === 'number' && v >= 0 && v <= 1;
        if ((ev.type === 'click' || ev.type === 'wheel') && !(inRange(ev.x) && inRange(ev.y))) return json(res, 400, { error: 'coordenadas fuera de rango' });
        if (ev.type === 'wheel' && !(Number.isFinite(ev.deltaY) && Math.abs(ev.deltaY) <= 5000)) return json(res, 400, { error: 'deltaY inválido' });
        if (ev.type === 'text' && !(typeof ev.text === 'string' && ev.text.length > 0 && ev.text.length <= 2000)) return json(res, 400, { error: 'texto inválido' });
        if (!['click', 'wheel', 'key', 'text'].includes(ev.type)) return json(res, 400, { error: 'tipo de entrada no soportado' });
        if (busy.has(ev.provider)) return json(res, 409, { error: `${ev.provider} está enviando un mensaje: espera a que termine` });
        try {
          await inputs[ev.provider](ev);
          json(res, 200, { ok: true });
        } catch (e) { json(res, e?.status || 502, { error: String(e?.message || e) }); }
      });
      return;
    }

    if (req.method === 'POST' && url.pathname === '/v1/chat') {
      const chunks = [];
      let size = 0;
      req.on('data', (c) => {
        size += c.length;
        if (size > MAX_BODY) {
          // Se responde 413 y se DESCARTA el resto del cuerpo (antes se destruía la conexión y el cliente
          // solo veía un corte; M7). Si el cuerpo es desmesurado, entonces sí se corta.
          if (!res.headersSent) {
            res.setHeader('Connection', 'close');
            json(res, 413, { error: 'petición demasiado grande' });
          }
          if (size > 64 * MAX_BODY) req.destroy();
          return;
        }
        chunks.push(c);
      });
      req.on('end', async () => {
        if (res.writableEnded) return;
        let body;
        try { body = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { return json(res, 400, { error: 'JSON inválido' }); }
        const { provider, prompt, conversation } = body || {};
        const source = body?.source === 'panel' && isPanel ? 'panel' : 'eolfi';
        if (!Object.hasOwn(adapters, provider)) return json(res, 404, { error: `proveedor desconocido: ${provider}` });
        if (typeof prompt !== 'string' || !prompt.trim()) return json(res, 400, { error: 'falta prompt' });
        const conv = typeof conversation === 'string' && /^[\w-]{1,64}$/.test(conversation) ? conversation : 'default';
        if (busy.has(provider)) return json(res, 409, { error: `${provider} está ocupado con otro mensaje` });
        busy.add(provider);
        const controller = new AbortController();
        res.on('close', () => { if (!res.writableEnded) controller.abort(new Error('Eolfi canceló la petición')); });
        // La aprobación recibe su propia señal (plazo + cancelación de Eolfi): al caducar se CIERRA el
        // diálogo y una respuesta tardía («Permitir 30 minutos») ya no concede nada (PLAN_MEJORAS A1).
        const approval = new AbortController();
        const expire = setTimeout(() => approval.abort(new Error('aprobación caducada')), approveTimeoutMs);
        expire.unref?.();
        const onCancel = () => approval.abort(new Error('Eolfi canceló la petición'));
        controller.signal.addEventListener('abort', onCancel, { once: true });
        try {
          const allowed = source === 'panel' || await Promise.race([
            Promise.resolve(approve(provider, prompt, approval.signal, conv)).then((ok) => ok === true && !approval.signal.aborted),
            new Promise((r) => approval.signal.addEventListener('abort', () => r(false), { once: true })),
          ]);
          clearTimeout(expire);
          controller.signal.removeEventListener('abort', onCancel);
          // Si Eolfi canceló mientras el diálogo estaba abierto, no se envía nada.
          if (controller.signal.aborted) {
            record({ provider, conversation: conv, source, role: 'error', text: 'Cancelado antes de enviar' });
            return;
          }
          if (!allowed) {
            const expired = approval.signal.aborted && /caducada/.test(String(approval.signal.reason?.message));
            record({ provider, conversation: conv, source, role: 'error', text: expired ? 'Aprobación caducada' : 'Envío denegado en el puente' });
            // 408: nadie respondió a tiempo (no es lo mismo que un «Denegar» explícito; M7).
            return expired ? json(res, 408, { error: 'La aprobación caducó sin respuesta en el puente' })
              : json(res, 403, { error: 'El usuario denegó el envío en el puente' });
          }
          log(`→ ${provider} (${source}): ${prompt.length} caracteres`);
          record({ provider, conversation: conv, source, role: 'user', text: prompt.slice(0, 20000), length: prompt.length });
          const adapter = await adapters[provider]();
          const key = `${provider}|${conv}`;
          const onPartial = (t) => partials.set(key, { text: t.slice(-30000), length: t.length, ts: Date.now() });
          let text;
          try { text = await adapter.send(prompt, controller.signal, conv, onPartial); } finally { partials.delete(key); }
          log(`← ${provider}: ${text.length} caracteres`);
          record({ provider, conversation: conv, source, role: 'assistant', text: text.slice(0, 30000), length: text.length });
          json(res, 200, { text, provider, conversation: conv });
        } catch (e) {
          record({ provider, conversation: conv, source, role: 'error', text: String(e?.message || e) });
          if (!res.writableEnded) json(res, 502, { error: String(e?.message || e) });
        } finally {
          clearTimeout(expire);
          if (!approval.signal.aborted) approval.abort(new Error('petición terminada'));   // cierra un diálogo huérfano
          busy.delete(provider);
        }
      });
      return;
    }
    json(res, 404, { error: 'ruta no encontrada' });
  });
  return new Promise((resolve) => server.listen(port, host, () => resolve({ server, port: server.address().port })));
}
