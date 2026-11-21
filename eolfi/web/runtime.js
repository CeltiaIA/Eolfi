// Utilidades compartidas por los módulos del panel.
export const $ = (sel) => document.querySelector(sel);

export function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const c of children) n.append(c instanceof Node ? c : document.createTextNode(String(c ?? "")));
  return n;
}

export async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (opts.method && opts.method !== "GET") headers["X-Eolfi"] = "1";
  const r = await fetch(path, { ...opts, headers });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

// Los trabajos largos se consultan en segundo plano para mantener visible el progreso.
// 21/11/2026: `opts.onStart(id)` da el id al llamante (para corregir o parar el trabajo en marcha); un corte de red
// pasajero ya no tira el trabajo (se reintenta) y el estado «interrupted» (servidor reiniciado) termina la espera
// en vez de consultar para siempre.
export async function runJob(kind, body, onLog = () => {}, opts = {}) {
  const { job_id: id } = await api("/api/jobs", { method: "POST", body: JSON.stringify({ kind, body }) });
  opts.onStart?.(id);
  let since = 0;
  let fallos = 0;
  for (;;) {
    let d;
    try {
      d = await api(`/api/jobs?id=${id}&since=${since}`);
      fallos = 0;
    } catch (err) {
      // TypeError = la petición no llegó (red, servidor reiniciándose); un error HTTP del servidor sí es definitivo.
      if (!(err instanceof TypeError) || ++fallos > 10) throw err;
      onLog([{ msg: "Sin conexión con Eolfi un momento; sigo esperando el resultado…" }]);
      await new Promise((r) => setTimeout(r, 1500));
      continue;
    }
    if (d.log.length) onLog(d.log, d.elapsed);
    since = d.next;
    if (d.status === "done") return d.result;
    if (d.status === "error" || d.status === "cancelled" || d.status === "interrupted") {
      const e = new Error(d.error || (d.status === "interrupted" ? "El trabajo se interrumpió al reiniciarse Eolfi" : d.status));
      e.code = d.code; e.status = d.status; e.needsConfirm = !!d.needs_confirm; throw e;
    }
    await new Promise((r) => setTimeout(r, 700));
  }
}

// Mensaje para un trabajo de chat en marcha: entra en su hilo antes del siguiente paso («para» lo cancela).
export const jobMessage = (id, texto) =>
  api(`/api/jobs/${id}/mensaje`, { method: "POST", body: JSON.stringify({ texto }) });
export const cancelJob = (id) => api(`/api/jobs?id=${encodeURIComponent(id)}`, { method: "DELETE" });

export function setStatus(msg, bad = false) {
  const s = $("#status");
  s.textContent = msg;
  s.classList.toggle("bad", bad);
  s.setAttribute("aria-live", bad ? "off" : "polite");
  const alert = $("#workspace-alert");
  alert.textContent = bad ? msg : "";
  alert.hidden = !bad;
}

export const fmtTime = (t) => new Date(t * 1000).toLocaleString();
export const short = (sha) => (sha.startsWith("cmd:") || sha.startsWith("resilience:") ? sha.slice(0, 28) : sha.slice(0, 12));
