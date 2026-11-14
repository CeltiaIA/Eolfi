// Chat con Eolfi a través del motor Eolas V2 (12/11/2026): tú le pides a Eolas y Eolas manda hacer a Eolfi.
// Los adjuntos se suben por su huella; el modelo decide qué herramientas de Eolfi usar (triaje, web, repositorio,
// Alejandría, Python en el contenedor) y cada llamada se ve en la conversación. Todo se pinta como texto.
import { $, el, api, runJob } from "./runtime.js";

const STORE_KEY = "eolfi.eolasChat";
const AUTO_PROMPT = "Analiza lo que te adjunto y propón qué se podría generar con Eolfi a partir de ello.";
const KIND_LABEL = { archivo: "archivo", binario: "binario", url: "web", repositorio: "repositorio", repo: "repositorio" };

const chat = { messages: [], attachments: [], busy: false, uploading: 0 };

function save() {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(chat.messages.slice(-40))); } catch { /* sin almacenamiento */ }
}

function load() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORE_KEY) || "[]");
    if (Array.isArray(saved)) chat.messages = saved.filter((m) => m && typeof m.content === "string" && (m.role === "user" || m.role === "assistant"));
  } catch { chat.messages = []; }
}

// Formato mínimo y seguro de las respuestas: **negrita** y `código`. Se construyen nodos; nunca HTML del modelo.
function richText(text) {
  return String(text).split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/).filter(Boolean).map((part) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? el("strong", {}, part.slice(2, -2))
      : part.startsWith("`") && part.endsWith("`") && part.length > 2 ? el("code", {}, part.slice(1, -1))
        : document.createTextNode(part));
}

function bubble(m) {
  const meta = el("span", { class: "meta" }, m.role === "user" ? (m.failed ? "Tú · no se pudo enviar" : "Tú") : `Eolfi${m.model ? ` · ${m.model}` : ""}`);
  const node = el("div", { class: `msg ${m.role}` }, meta, ...(m.role === "assistant" ? richText(m.content) : [m.shown || m.content]));
  for (const t of m.tools || []) {
    node.append(el("span", { class: `analysis-chip${t.ok ? "" : " bad"}`, title: t.args || "" },
      `${t.ok ? "✓" : "✗"} ${t.name.replace(/^eolfi_/, "")}`));
  }
  // Lo que el chat coordina se abre desde aquí: el plan propuesto se REVISA Y APRUEBA en Herramientas (nunca solo).
  const actions = [];
  for (const t of m.tools || []) {
    if (t.proyecto) actions.push(el("button", { type: "button", class: "small-btn", onclick: () => emit("eolfi:open-project", { caseId: t.proyecto }) }, "Revisar y aprobar el plan"));
    if (t.objetivo) actions.push(el("button", { type: "button", class: "small-btn", onclick: () => emit("eolfi:open-subject", { subject: t.objetivo }) }, "Ver informe"));
  }
  if (actions.length) node.append(el("div", { class: "msg-actions" }, ...actions));
  // Autorización por caso (plan REA, punto 2): solo el titular decide, aquí; el modelo nunca puede autorizarse.
  for (const t of m.tools || []) if (t.autorizacion) node.append(authCard(t));
  return node;
}

const activeCase = () => { try { return localStorage.getItem("eolfi.case") || null; } catch { return null; } };
const SCOPE_TEXT = { once: "una vez", case: "en este caso", deny: "rechazado" };

function authCard(t) {
  const card = el("div", { class: "auth-card", role: "group", "aria-label": `Autorización para ${t.herramienta_pedida}` },
    el("strong", {}, `Eolas pide ejecutar «${t.herramienta_pedida}»`),
    el("div", { class: "small" }, "Esta herramienta ejecuta o abre algo vivo (el programa, un proceso, un dispositivo o una página). Solo se usará si lo apruebas."),
    el("code", { class: "auth-args" }, t.args || "{}"));
  if (t.decision) { card.append(el("div", { class: "small" }, `Decidido: ${SCOPE_TEXT[t.decision] || t.decision}`)); return card; }
  const caseId = activeCase();
  const decide = async (decision) => {
    card.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    try {
      await api(`/api/rea/autorizaciones/${encodeURIComponent(t.autorizacion)}`, { method: "POST", body: JSON.stringify({ decision }) });
      t.decision = decision;
      save();
      render();
      loadPermissions();
      if (decision !== "deny") send(`He autorizado «${t.herramienta_pedida}» (${SCOPE_TEXT[decision]}). Continúa con el análisis.`);
    } catch (err) {
      card.append(el("div", { class: "small bad" }, `No se pudo registrar la decisión: ${err.message}`));
      card.querySelectorAll("button").forEach((b) => { b.disabled = false; });
    }
  };
  card.append(el("div", { class: "msg-actions" },
    el("button", { type: "button", class: "small-btn", onclick: () => decide("once") }, "Permitir una vez"),
    el("button", { type: "button", class: "small-btn", disabled: caseId ? null : "disabled",
      title: caseId ? "Para esta herramienta en el caso activo, hasta que lo revoques" : "Activa un caso en Herramientas → Casos",
      onclick: () => decide("case") }, "Permitir en este caso"),
    el("button", { type: "button", class: "ghost-btn", onclick: () => decide("deny") }, "Rechazar")));
  return card;
}

async function loadPermissions() {
  const box = $("#eolas-chat-perms");
  if (!box) return;
  try {
    const caseId = activeCase();
    const d = await api(`/api/rea/autorizaciones${caseId ? `?caso=${encodeURIComponent(caseId)}` : ""}`);
    const list = el("ul", { class: "plain" }, ...(d.permisos || []).map((g) => el("li", {},
      `${g.tool} · ${SCOPE_TEXT[g.scope] || g.scope} · ${g.case_key === "sin-caso" ? "sin caso" : `caso ${g.case_key.slice(0, 8)}`} `,
      el("button", { type: "button", class: "small-btn", onclick: async () => {
        try { await api(`/api/rea/permisos/${encodeURIComponent(g.id)}/revocar`, { method: "POST", body: "{}" }); loadPermissions(); }
        catch (err) { box.append(el("p", { class: "small bad" }, err.message)); }
      } }, "Revocar"))));
    const log = (d.ejecuciones || []).slice(0, 8).map((x) => el("li", { class: "small" },
      `${new Date(x.ts * 1000).toLocaleString()} · ${x.tool} · ${x.ok ? "correcta" : "con error"}`));
    box.replaceChildren(
      (d.permisos || []).length ? list : el("p", { class: "small muted" }, "No hay permisos activos."),
      ...(log.length ? [el("p", { class: "small" }, "Últimas ejecuciones autorizadas:"), el("ul", { class: "plain" }, ...log)] : []));
  } catch (err) {
    box.replaceChildren(el("p", { class: "small muted" }, `No se pudieron cargar los permisos: ${err.message}`));
  }
}

const emit = (name, detail) => window.dispatchEvent(new CustomEvent(name, { detail }));

function render() {
  const log = $("#eolas-chat-log");
  log.replaceChildren(...chat.messages.map(bubble));
  log.scrollTop = log.scrollHeight;
}

function renderAttachments() {
  $("#eolas-chat-attachments").replaceChildren(...chat.attachments.map((a, i) => el("li", {},
    el("span", { title: a.name }, `${a.name} (${(a.size / 1048576).toFixed(a.size < 1048576 ? 2 : 1)} MB)`),
    el("button", { type: "button", "aria-label": `Quitar ${a.name}`, onclick: () => { chat.attachments.splice(i, 1); renderAttachments(); } }, "×"))));
}

function setBusy(busy) {
  chat.busy = busy;
  $("#eolas-chat-send").disabled = busy || chat.uploading > 0;
  $("#eolas-chat-send").textContent = busy ? "Eolfi trabajando…" : "Enviar";
}

function renderProfiles(st) {
  const pick = $("#eolas-chat-profile");
  if (st.remote || !st.profiles?.length) { pick.hidden = true; return; }
  pick.hidden = false;
  if (document.activeElement !== pick) {
    pick.replaceChildren(...st.profiles.map((p) => el("option", { value: p.name }, `${p.name} · ${p.alias}`)));
    pick.value = st.profile;
  }
  pick.disabled = chat.busy || !!st.busy;
}

async function refreshEngine(st) {
  const out = $("#eolas-chat-engine");
  try {
    st = st || await api("/api/chat/estado");
    renderProfiles(st);
    const ok = st.available && !st.busy;
    out.className = ok ? "ok" : "bad";
    out.textContent = st.busy || (st.available ? `Motor Eolas V2: ${st.detail}` : st.detail);
  } catch (err) {
    out.className = "bad";
    out.textContent = `No se pudo consultar Eolas: ${err.message}`;
  }
}

async function upload(files) {
  for (const file of files) {
    chat.uploading += 1;
    setBusy(chat.busy);
    try {
      const up = await api(`/api/upload?store=1&name=${encodeURIComponent(file.name)}`, {
        method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" } });
      chat.attachments.push({ upload: up.upload, name: file.name, size: file.size });
    } catch (err) {
      chat.messages.push({ role: "assistant", content: `No se pudo adjuntar ${file.name}: ${err.message}`, local: true });
      render();
    } finally {
      chat.uploading -= 1;
      setBusy(chat.busy);
    }
  }
  renderAttachments();
}

async function send(text) {
  if (chat.busy || chat.uploading) return;
  const kind = $("#eolas-chat-kind").value;
  const target = $("#eolas-chat-target").value.trim();
  const attachments = chat.attachments.slice();
  if (kind && !target) { $("#eolas-chat-target").focus(); return; }
  const prompt = text || ((attachments.length || kind) ? AUTO_PROMPT : "");
  if (!prompt) { $("#eolas-chat-input").focus(); return; }
  const extras = [...attachments.map((a) => `📎 ${a.name}`), ...(kind ? [`🔎 ${KIND_LABEL[kind]}: ${target}`] : [])];
  const user = { role: "user", content: prompt, shown: extras.length ? `${prompt}\n\n${extras.join("\n")}` : prompt };
  chat.messages.push(user);
  render();
  const progress = el("div", { class: "msg progress" }, "Enviando a Eolas…");
  const steps = [];
  $("#eolas-chat-log").append(progress);
  setBusy(true);
  try {
    const asBinary = $("#eolas-chat-as-binary").checked;
    const history = chat.messages.filter((m) => !m.local && !m.failed).map(({ role, content }) => ({ role, content }));
    const result = await runJob("chat", {
      name: `Chat · ${prompt.slice(0, 60)}`,
      messages: history,
      attachments: attachments.map((a) => ({ upload: a.upload, name: a.name, kind: asBinary ? "binario" : "archivo" })),
      ...(kind ? { analyze: { kind, target } } : {}),
      ...(activeCase() ? { case_id: activeCase() } : {}),
    }, (lines) => {
      steps.push(...lines.map((l) => l?.msg || String(l)));
      progress.textContent = steps.slice(-8).join(String.fromCharCode(10));
      $("#eolas-chat-log").scrollTop = $("#eolas-chat-log").scrollHeight;
    });
    chat.messages.push({ role: "assistant", content: result.text, model: result.model, tools: result.tools });
    chat.attachments = [];
    $("#eolas-chat-input").value = "";
    $("#eolas-chat-kind").value = "";
    $("#eolas-chat-target").value = "";
    $("#eolas-chat-target").hidden = true;
    renderAttachments();
    save();
  } catch (err) {
    // 14/11/2026: antes se quitaba la pregunta y solo se veía el error. Ahora se queda a la vista, marcada como no
    // enviada; no entra en el historial que se manda al modelo y el texto vuelve al editor para reenviarlo.
    user.failed = true;
    chat.messages.push({ role: "assistant", content: `No se pudo completar: ${err.message}`, local: true });
    $("#eolas-chat-input").value = text;
  } finally {
    progress.remove();
    setBusy(false);
    render();
    refreshEngine();
  }
}

export function initEolasChat() {
  if (!$("#eolas-chat-form")) return;
  load();
  loadPermissions();
  render();
  refreshEngine();
  setInterval(() => { if (!$("#local-chat").hidden && !chat.busy) refreshEngine(); }, 30000);
  $("#eolas-chat-form").addEventListener("submit", (e) => { e.preventDefault(); send($("#eolas-chat-input").value.trim()); });
  $("#eolas-chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(e.currentTarget.value.trim()); }
  });
  $("#eolas-chat-files").addEventListener("change", async (e) => {
    const files = [...e.currentTarget.files];
    e.currentTarget.value = "";
    if (!files.length) return;
    await upload(files);
    // Al adjuntar, Eolfi analiza y propone sin esperar a que se escriba nada.
    if (!$("#eolas-chat-input").value.trim() && chat.attachments.length) send("");
  });
  $(".eolas-chat-attach").addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#eolas-chat-files").click(); }
  });
  $("#eolas-chat-kind").addEventListener("change", (e) => {
    const target = $("#eolas-chat-target");
    target.hidden = !e.currentTarget.value;
    target.placeholder = { archivo: "C:\\ruta\\archivo", binario: "C:\\ruta\\programa.exe", url: "https://…",
      repositorio: "Carpeta local o https://github.com/usuario/repo" }[e.currentTarget.value] || "";
    if (!target.hidden) target.focus();
  });
  $("#eolas-chat-tools").addEventListener("click", () => emit("eolfi:open-tools", {}));
  // El motor elegido aquí pasa a ser el de Eolas V2 en todo Eolfi; el modelo se cambia en la siguiente petición.
  $("#eolas-chat-profile").addEventListener("change", async (e) => {
    const pick = e.currentTarget;
    pick.disabled = true;
    try { await refreshEngine(await api("/api/chat/motor", { method: "POST", body: JSON.stringify({ profile: pick.value }) })); }
    catch (err) { $("#eolas-chat-engine").textContent = `No se pudo cambiar el motor: ${err.message}`; refreshEngine(); }
  });
  $("#eolas-chat-clear").addEventListener("click", () => {
    if (chat.busy) return;
    chat.messages = [];
    chat.attachments = [];
    renderAttachments();
    save();
    render();
  });
}
