// Utilidades comunes de los adaptadores de chat web (portadas de Force/metaCore.mjs).
export function abortCheck(signal) {
  if (signal?.aborted) throw signal.reason ?? new DOMException('Cancelado', 'AbortError');
}

function freshRows(baseline, rows) {
  const ids = rows.map((row) => row.id);
  if (ids.some((id) => !id) || new Set(ids).size !== ids.length) throw new Error('Identidad DOM ausente o duplicada. Recalibrar adaptador.');
  const fresh = rows.filter((row) => !baseline.has(row.id));
  if (fresh.length > 1) throw new Error('Hay varias respuestas nuevas: la conversación se modificó fuera de Eolfi.');
  return fresh;
}

export function freshReply(baseline, rows) {
  const fresh = freshRows(baseline, rows);
  return fresh.length === 1 && fresh[0].complete && fresh[0].text.trim() ? fresh[0].text : null;
}

// Tope absoluto de una respuesta, aunque siga creciendo (EOLFI_BRIDGE_MAX_REPLY_MS, 30 min por defecto).
export const MAX_REPLY_MS = Math.max(Number(process.env.EOLFI_BRIDGE_MAX_REPLY_MS) || 30 * 60 * 1000, 60000);

// Espera la respuesta nueva. Grupo 3 de la Fase E:
// - onPartial(texto) recibe el texto mientras se escribe (streaming hacia Eolfi y el panel).
// - El plazo es de INACTIVIDAD: mientras el texto crece, no caduca (DeepThink y similares), con un tope total.
// - «Completa» exige además que el texto no cambie entre dos lecturas seguidas: una sola señal del DOM
//   (botón de parar retirado, clase CSS…) ya no basta para cortar una respuesta a medias (M4).
export async function waitReply(read, baseline, signal, timeoutMs = 180000, intervalMs = 500, label = 'El chat', onPartial = null) {
  const start = Date.now();
  let lastProgress = start, lastText = null, stableHits = 0;
  while (Date.now() - lastProgress < timeoutMs && Date.now() - start < MAX_REPLY_MS) {
    abortCheck(signal);
    const rows = await read();
    abortCheck(signal);
    const fresh = freshRows(baseline, rows);
    const row = fresh.length === 1 ? fresh[0] : null;
    const text = row?.text ?? '';
    if (text !== lastText) {
      lastProgress = Date.now();
      stableHits = 0;
      lastText = text;
      if (text.trim() && onPartial) { try { onPartial(text, !!row?.complete); } catch { /* el oyente no corta la espera */ } }
    } else if (row?.complete && text.trim()) {
      stableHits += 1;
      if (stableHits >= 1) return text;   // completa y sin cambios en la lectura anterior
    }
    await sleep(intervalMs, signal);
  }
  throw new Error(Date.now() - start >= MAX_REPLY_MS
    ? `${label} sigue escribiendo tras ${Math.round(MAX_REPLY_MS / 60000)} min: se corta la espera.`
    : `${label} no ha confirmado una respuesta completa dentro del tiempo límite.`);
}

export function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    const done = () => { clearTimeout(timer); signal?.removeEventListener('abort', cancelled); resolve(); };
    const cancelled = () => { clearTimeout(timer); signal?.removeEventListener('abort', cancelled); reject(signal.reason ?? new DOMException('Cancelado', 'AbortError')); };
    const timer = setTimeout(done, ms);
    signal?.addEventListener('abort', cancelled, { once: true });
    if (signal?.aborted) cancelled();
  });
}

// Ejecuta un script en la página solo si sigue en el origen esperado (nunca en otro sitio).
export async function evaluateIn(contents, origin, script, label) {
  if (!contents || contents.isDestroyed()) throw new Error(`${label}: la ventana está cerrada.`);
  let timer;
  try {
    return await Promise.race([
      contents.executeJavaScript(`(() => { if (location.origin !== ${JSON.stringify(origin)}) throw new Error('Origen inesperado'); return (${script}); })()`, true),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`${label}: la página no respondió.`)), 10000); }),
    ]);
  } finally { clearTimeout(timer); }
}

export const MAX_WIRE = 32000;

// Justo antes de escribir: la pestaña sigue en el sitio esperado (no en una página de acceso
// u otra web a la que haya redirigido entretanto). Si no, no se escribe nada.
export async function assertOrigin(contents, origin) {
  const here = await contents.executeJavaScript('location.origin', true).catch(() => null);
  if (here !== origin) throw new Error(`La pestaña ya no está en ${origin} (está en ${here ?? 'desconocido'}): no se envía`);
}

// Saltos de línea de Windows: el editor del chat guarda LF, así que la comparación exacta del texto
// escrito fallaba con CRLF (PLAN_MEJORAS A3).
export const unixNewlines = (text) => String(text).replace(/\r\n?/g, '\n');

const sansHash = (u) => { try { const x = new URL(u); x.hash = ''; return x.href; } catch { return String(u || ''); } };

// Antes de cada envío la pestaña debe estar en la conversación pedida (PLAN_MEJORAS A2): si el usuario
// cerró la pestaña o navegó a otro chat desde la vista en directo, «current» ya no dice la verdad.
// Se espera la URL guardada de esa conversación o, si sigue siendo la activa, la última URL vista
// tras el envío anterior; si no coincide, se carga la conversación (o un chat nuevo).
export async function ensureConversation(adapter, contents, conversation, fallback) {
  const saved = adapter.urls.get(conversation);
  const expected = saved || (adapter.current === conversation ? adapter.lastUrl : null);
  if (!expected || sansHash(contents.getURL()) !== sansHash(expected)) {
    const url = saved || fallback;
    if (sansHash(contents.getURL()) !== sansHash(url)) await contents.loadURL(url);
  }
  adapter.current = conversation;
  adapter.lastUrl = contents.getURL();
}

// Plazo máximo de una respuesta (DeepThink y similares superan los 4 min): EOLFI_BRIDGE_REPLY_MS (M3).
export const REPLY_TIMEOUT_MS = Math.min(Math.max(Number(process.env.EOLFI_BRIDGE_REPLY_MS) || 240000, 30000), 3600000);
