// Aprobación de envíos del puente, separada de Electron para poder probarla (Fase D).
// Cada envío automático de Eolfi pide permiso; «Permitir 30 minutos» vale solo para esa conversación.
const GRANT_MS = 30 * 60 * 1000;

export function createApprover({ showMessageBox, titleOf = (p) => p, beforeShow = () => null, now = () => Date.now() }) {
  const allowUntil = {};
  const grantKey = (provider, conversation) => `${provider}|${conversation || 'default'}`;

  function grants() {
    const t = now(), out = {};
    for (const [k, until] of Object.entries(allowUntil)) {
      if (until <= t) { delete allowUntil[k]; continue; }
      const [p, c] = k.split('|');
      (out[p] ||= []).push({ conversation: c, until });
    }
    return out;
  }

  function revoke(provider, conversation) {
    let n = 0;
    for (const k of Object.keys(allowUntil)) {
      if (k.startsWith(`${provider}|`) && (!conversation || k === grantKey(provider, conversation))) { delete allowUntil[k]; n++; }
    }
    return n;
  }

  // Vista previa: principio Y final (una instrucción podría esconderse al final de un texto largo).
  function preview(prompt) {
    const hidden = Math.max(0, prompt.length - 1000);
    return hidden ? `${prompt.slice(0, 600)}\n\n[… ${hidden.toLocaleString('es')} caracteres ocultos …]\n\n${prompt.slice(-400)}` : prompt;
  }

  async function approve(provider, prompt, signal, conversation) {
    if ((allowUntil[grantKey(provider, conversation)] || 0) > now()) return true;
    if (signal?.aborted) return false;
    const many = provider.includes('+');
    const win = many ? null : beforeShow(provider);
    const title = many ? provider.split('+').map((p) => titleOf(p)).join(', ') : titleOf(provider);
    const options = {
      type: 'question',
      title: 'Eolfi quiere enviar una petición',
      message: `Eolfi quiere enviar ${prompt.length.toLocaleString('es')} caracteres a ${title}.`,
      detail: preview(prompt),
      buttons: ['Permitir', `Permitir 30 minutos (solo esta conversación de ${title})`, 'Denegar'],
      defaultId: 0, cancelId: 2, noLink: true,
      signal,   // al caducar o cancelarse, Electron cierra el diálogo (responde cancelId)
    };
    const { response } = await showMessageBox(win, options);
    if (signal?.aborted) return false;   // respuesta tardía: no concede nada, tampoco los 30 minutos
    if (response === 1) allowUntil[grantKey(provider, conversation)] = now() + GRANT_MS;
    return response !== 2;
  }

  return { approve, grants, revoke, preview };
}
