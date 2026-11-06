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
export async function runJob(kind, body, onLog = () => {}) {
  const { job_id: id } = await api("/api/jobs", { method: "POST", body: JSON.stringify({ kind, body }) });
  let since = 0;
  for (;;) {
    const d = await api(`/api/jobs?id=${id}&since=${since}`);
    if (d.log.length) onLog(d.log, d.elapsed);
    since = d.next;
    if (d.status === "done") return d.result;
    if (d.status === "error" || d.status === "cancelled") {
      const e = new Error(d.error); e.code = d.code; e.needsConfirm = !!d.needs_confirm; throw e;
    }
    await new Promise((r) => setTimeout(r, 700));
  }
}

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
