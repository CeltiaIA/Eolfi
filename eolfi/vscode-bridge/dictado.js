'use strict';
// Dictado en el chat (A9): el proceso de la extensión no puede grabar, así que pide a Eolfi que grabe del micrófono
// del equipo (POST /api/voz/dictar, MCI de Windows, nada se guarda) y deja el texto en el chat sin enviarlo.

const MIN = 1;
const MAX = 30;
const DEFECTO = 8;

function segundosDictado(valor) {
  const n = Number(valor);
  if (!Number.isFinite(n)) return DEFECTO;
  return Math.min(MAX, Math.max(MIN, Math.round(n)));
}

// Consulta para workbench.action.chat.open: con el participante @eolfi activo va dirigida a él; si no, el texto tal
// cual (lo recibe el agente Eolfi elegido en el selector). Siempre como consulta parcial: el titular la revisa y la envía.
function consultaDictado(texto, participante = true) {
  const limpio = String(texto || '').replace(/\s+/g, ' ').trim();
  if (!limpio) return null;
  return { query: participante ? `@eolfi ${limpio}` : limpio, isPartialQuery: true };
}

async function dictar(client, { segundos, idioma, participante = true, abrirChat }) {
  const seg = segundosDictado(segundos);
  const r = await client.dictar(seg, idioma);
  const consulta = consultaDictado(r && r.texto, participante);
  if (!consulta) return { ok: false, motivo: 'No se reconoció nada en la grabación.', resultado: r };
  await abrirChat(consulta);
  return { ok: true, texto: consulta.query, resultado: r };
}

module.exports = { segundosDictado, consultaDictado, dictar, MIN, MAX, DEFECTO };
