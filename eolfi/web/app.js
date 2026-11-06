// Panel de Eolfi. Todo el texto procedente de binarios se pinta con
// textContent: nunca se interpreta como HTML (los binarios son hostiles).
"use strict";

const $ = (sel) => document.querySelector(sel);
const state = { subject: null, subjects: [], kind: "binary", selected: new Set(), req: 0, view: "empty" };
const PLACEHOLDER = {
  binary: "…o ruta local: C:\\ruta\\binario.exe o una carpeta",
  web: "URL (https://…), archivo .html o carpeta del sitio",
  repo: "Carpeta local o URL git (https://github.com/usuario/repo)",
};

function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const c of children) n.append(c instanceof Node ? c : document.createTextNode(String(c ?? "")));
  return n;
}

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (opts.method && opts.method !== "GET") headers["X-Eolfi"] = "1";
  const r = await fetch(path, { ...opts, headers });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

// Trabajo en segundo plano: el servidor no deja la petición colgada minutos (Ghidra, clonar,
// instalar y probar); el panel consulta el progreso y lo muestra mientras tanto.
async function runJob(kind, body, onLog = () => {}) {
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

function setStatus(msg, bad = false) {
  const s = $("#status");
  s.textContent = msg;
  s.classList.toggle("bad", bad);   // clase, no estilo en línea (la CSP lo bloquea)
}

const fmtTime = (t) => new Date(t * 1000).toLocaleString();
const short = (sha) => (sha.startsWith("cmd:") || sha.startsWith("resilience:") ? sha.slice(0, 28) : sha.slice(0, 12));

// -- proveedores -----------------------------------------------------------
async function loadProviders() {
  const { providers } = await api("/api/providers");
  state.providers = providers;
  renderProvidersView();
  const ul = $("#providers");
  ul.replaceChildren(...providers.map((p) =>
    el("li", {}, p.name, " ",
      el("span", { class: "badge " + (p.available ? "ok" : "") }, p.available ? "sí" : "no"),
      el("span", { class: "badge" }, p.mode))));
}

// -- objetivos -------------------------------------------------------------
async function loadSubjects() {
  const { subjects } = await api("/api/subjects");
  state.subjects = subjects;
  const ul = $("#subjects");
  if (!subjects.length) {
    ul.replaceChildren(el("li", { class: "muted" }, "Aún no hay evidencias."));
    return;
  }
  ul.replaceChildren(...subjects.map((s) => {
    const box = el("input", { type: "checkbox", "aria-label": `Seleccionar «${s.names[0] || short(s.subject)}» para crear o comparar`,
      onclick: (e) => e.stopPropagation(),
      onchange: (e) => { e.target.checked ? state.selected.add(s.subject) : state.selected.delete(s.subject); updateCompare(); } });
    box.checked = state.selected.has(s.subject);
    // Botón real (teclado y lector de pantalla) en lugar de un <li> con onclick.
    const li = el("li", {}, box,
      el("button", { type: "button", class: "subject-btn", onclick: () => selectSubject(s.subject),
                     "aria-current": s.subject === state.subject ? "true" : "false" },
        el("div", {}, (s.names[0] || short(s.subject)),
          el("span", { class: "badge" }, s.format || s.kind),
          s.open_incognitas ? el("span", { class: "badge warn" }, `${s.open_incognitas} ?`) : ""),
        el("div", { class: "muted small" }, `${s.evidence} evidencias · ${fmtTime(s.last_seen)}`)));
    if (s.subject === state.subject) li.classList.add("active");
    return li;
  }));
}

function updateCompare() {
  const b = $("#compare-btn");
  b.disabled = state.selected.size !== 2;
  b.textContent = state.selected.size ? `Comparar ${state.selected.size}/2` : "Comparar 2";
}

// -- vistas: análisis (detalle o vacío), chats y proveedores (PLAN_MEJORAS M11) ----------
function showView(view) {
  if (view === "analysis") view = state.subject ? "content" : "empty";
  state.view = view;
  const wasChats = chat.visible;
  chat.visible = view === "chats";
  $("#content").hidden = view !== "content";
  $("#empty").hidden = view !== "empty";
  $("#chats").hidden = view !== "chats";
  $("#providers-view").hidden = view !== "providers";
  $("#jobs-view").hidden = view !== "jobs";
  $("#vscode-view").hidden = view !== "vscode";
  // Cabecera: todas las vistas a la vista, la actual marcada (aria-current).
  const current = { chats: "#open-chats", providers: "#open-providers", jobs: "#open-jobs", content: "#open-analysis", empty: "#open-analysis" }[view];
  for (const id of ["#open-analysis", "#open-chats", "#open-providers", "#open-jobs"]) {
    if (id === current) $(id).setAttribute("aria-current", "page"); else $(id).removeAttribute("aria-current");
  }
  $(".menu")?.removeAttribute("open");
  if (view === "chats" && !wasChats) { renderChatLog(); refreshLive(); pollBridge(); }
  if (view === "providers") $("#providers-view h2")?.focus();
  if (view === "jobs") { $("#jobs-view h2")?.focus(); loadJobs(); }
  if (view === "vscode") showVSCode();
  if (view === "providers") loadClients();
  if (view === "content" || view === "empty") showAnalysisChoice?.();
}
const showChats = (on) => showView(on ? "chats" : "analysis");
const showProviders = (on) => showView(on ? "providers" : "analysis");

// -- detalle ---------------------------------------------------------------
async function selectSubject(subject) {
  state.subject = subject;
  const h = "#objetivo/" + encodeURIComponent(subject);
  if (location.hash !== h) history.pushState(null, "", h);
  const req = ++state.req;   // dos clics rápidos: solo se pinta la respuesta del último (A2)
  showView("content");
  const meta = state.subjects.find((s) => s.subject === subject);
  $("#subject-title").textContent = meta?.names?.join(", ") || short(subject);
  $("#subject-sha").textContent = subject;
  $("#report-html").href = `/api/report?format=html&subject=${encodeURIComponent(subject)}`;
  $("#report-md").href = `/api/report?format=md&subject=${encodeURIComponent(subject)}`;
  await Promise.all([loadEvidence(req), loadIncognitas(req), loadSubjects()]);
}

function tile(k, v) {
  return el("div", { class: "tile" }, el("div", { class: "k" }, k), el("div", { class: "v" }, v));
}

function renderSummary(evs) {
  const by = Object.fromEntries(evs.map((e) => [e.operation, e.result]));
  const tiles = [];
  if (by.detect_format) tiles.push(tile("Formato", by.detect_format.format));
  if (by.hash) tiles.push(tile("Tamaño", `${by.hash.size.toLocaleString()} B`));
  const h = by.pe_headers || by.elf_headers;
  if (h) {
    tiles.push(tile("Arquitectura", h.machine));
    if (by.pe_headers) tiles.push(tile("Subsistema", h.subsystem), tile("DLL", h.is_dll ? "sí" : "no"), tile(".NET", h.dotnet ? "sí" : "no"));
    if (by.elf_headers) tiles.push(tile("Tipo", h.type), tile("Intérprete", h.interpreter || "—"));
  }
  const sec = by.pe_security || by.elf_security;
  if (sec) {
    const on = Object.entries(sec).filter(([, v]) => v === true || v === "full" || v === "partial").map(([k, v]) => (v === true ? k : `${k}:${v}`));
    tiles.push(tile("Mitigaciones", on.join(", ") || "ninguna"));
  }
  if (by.pe_imports) tiles.push(tile("DLLs importadas", Object.keys(by.pe_imports.dlls).length));
  if (by.elf_dynamic) tiles.push(tile("Bibliotecas", by.elf_dynamic.needed.join(", ") || "—"));
  if (by.entropy && by.entropy.file != null) tiles.push(tile("Entropía", by.entropy.file));
  if (by.packing_signals) tiles.push(tile("¿Empaquetado?", by.packing_signals.likely_packed ? `probable ${by.packing_signals.packer_hint || ""}` : "no"));
  const funcs = by.ghidra_functions || by.rizin_functions;
  if (funcs && funcs.count != null) tiles.push(tile("Funciones", funcs.count));
  if (by.detect_capabilities?.rules) tiles.push(tile("Capacidades (capa)", by.detect_capabilities.rules.length));
  const list = (v) => (Array.isArray(v) && v.length ? v.join(", ") : "—");
  // Formatos nuevos (Fase E): firma, .NET, WebAssembly, Java, firma APK e iOS.
  const sig = by.pe_signature;
  if (sig) {
    const who = sig.signer?.subject?.match(/CN=([^,]+)/)?.[1];
    tiles.push(tile("Firma", !sig.present ? "sin firma incrustada"
      : `${who || "firmado"}${sig.digest_matches === false ? " · ¡NO COINCIDE!" : sig.digest_matches ? " · íntegro" : ""}`));
  }
  if (by.pe_metadata?.version_info?.strings?.CompanyName) tiles.push(tile("Empresa", by.pe_metadata.version_info.strings.CompanyName));
  if (by.pe_metadata?.tls?.count) tiles.push(tile("Callbacks TLS", by.pe_metadata.tls.count));
  const net = by.dotnet_metadata;
  if (net?.assembly) {
    tiles.push(tile("Ensamblado .NET", `${net.assembly.name} ${net.assembly.version}`),
      tile("Framework", net.target_framework || net.metadata_version || "—"));
    if (net.ready_to_run) tiles.push(tile("ReadyToRun", "sí (código nativo precompilado)"));
    if (net.obfuscation?.length) tiles.push(tile("Ofuscación", list(net.obfuscation)));
  }
  if (by.dotnet_bundle?.bundle) tiles.push(tile(".NET single-file", `${by.dotnet_bundle.files} archivos incrustados`));
  if (by.wasm_module) {
    const w = by.wasm_module;
    tiles.push(tile("WebAssembly", `${w.import_count} importaciones · ${w.export_count} exportaciones`),
      tile("Compilado con", list(w.toolchain)));
  }
  if (by.java_class) tiles.push(tile("Clase Java", by.java_class.class), tile("Java", by.java_class.java_version));
  const inv = by.archive_inventory;
  if (inv?.jar) {
    tiles.push(tile("Clase principal", inv.jar.main_class || "—"), tile("Java", list(Object.keys(inv.jar.bytecode_versions || {}))));
    if (inv.jar.spring_boot) tiles.push(tile("Spring Boot", inv.jar.spring_boot.version || "sí"));
  }
  if (inv?.signature?.schemes) tiles.push(tile("Firma APK", list(inv.signature.schemes)));
  if (inv?.ios?.info) {
    tiles.push(tile("App iOS", `${inv.ios.info.bundle_id || "?"} ${inv.ios.info.version || ""}`),
      tile("Team ID", inv.ios.signature?.team_id || inv.ios.provisioning?.team_id || "—"));
    if (inv.ios.executable) tiles.push(tile("Cifrado FairPlay", inv.ios.executable.encrypted ? "sí" : "no"));
  }
  if (by.web_blueprint) {
    const b = by.web_blueprint;
    if (by.web_structure?.title) tiles.push(tile("Título", by.web_structure.title));
    tiles.push(tile("Pila", list(b.stack)), tile("Para empezar", b.suggested_scaffold));
    tiles.push(tile("Colores", list(b.design_tokens?.colors?.slice(0, 6))), tile("Fuentes", list(b.design_tokens?.fonts)));
    if (b.component_candidates?.length) tiles.push(tile("Componentes repetidos", list(b.component_candidates.slice(0, 6))));
    if (by.web_sourcemaps) tiles.push(tile("Source maps", `${by.web_sourcemaps.reduce((n, s) => n + (s.sources || 0), 0)} archivos originales`));
    if (b.learning_notes?.length) tiles.push(el("div", { class: "tile wide" }, el("div", { class: "k" }, "Qué aprender"),
      el("ul", {}, ...b.learning_notes.map((n) => el("li", {}, n)))));
  }
  if (by.repo_blueprint) {
    const b = by.repo_blueprint;
    tiles.push(tile("Lenguaje principal", b.primary_language || "—"), tile("Pila", list(b.stack)),
      tile("Gestor de paquetes", b.package_manager || "—"), tile("Licencia", by.repo_docs?.license || "ninguna"));
    if (by.repo_languages) tiles.push(tile("Archivos", by.repo_languages.files_total));
    if (b.how_to_run?.length) tiles.push(el("div", { class: "tile wide" }, el("div", { class: "k" }, "Cómo se ejecuta"),
      el("pre", {}, b.how_to_run.join("\n"))));
    if (b.layout?.length) tiles.push(el("div", { class: "tile wide" }, el("div", { class: "k" }, "Estructura"),
      el("pre", {}, b.layout.join("\n"))));
  }
  // Nombres actuales (project_*) y los de proyectos creados con versiones anteriores (forge_*).
  by.project_generated ??= by.forge_project;
  by.project_assist ??= by.forge_assist;
  by.project_verification ??= by.forge_verification;
  if (by.project_generated) {
    const sp = by.project_generated.spec;
    tiles.push(tile("Tecnología", sp.target), tile("Archivos", by.project_generated.files.length),
      tile("Secciones", list(sp.sections)), tile("Páginas", list(sp.pages)), tile("Fuentes", sp.sources.length));
  }
  if (by.project_assist) {
    const a = by.project_assist;
    tiles.push(tile("IA", a.ok ? `✓ ${a.files_changed.length} archivos` : "✗ deshecho"));
    if (a.summary) tiles.push(el("div", { class: "tile wide" }, el("div", { class: "k" }, "Cambios de la IA"),
      el("p", {}, a.summary), ...(a.notes || []).map((n) => el("p", { class: "muted small" }, "· " + n))));
  }
  if (by.project_verification) {
    const v = by.project_verification;
    tiles.push(tile("Verificación", v.ok ? "✓ funciona" : "✗ falló"));
    if (v.pinned && Object.keys(v.pinned).length) tiles.push(el("div", { class: "tile wide" },
      el("div", { class: "k" }, "Dependencias (versión instalada)"),
      el("pre", {}, Object.entries(v.pinned).map(([k, x]) => `${k}@${x}`).join("\n"))));
  }
  if (by.version_diff) {
    const d = by.version_diff;
    tiles.push(tile("Cambiaron", Object.keys(d.changed).length), tile("Sin cambios", d.unchanged.length));
    if (d.headline?.length) tiles.push(el("div", { class: "tile wide" }, el("div", { class: "k" }, "Resumen"),
      el("ul", {}, ...d.headline.map((h) => el("li", {}, h)))));
  }
  if (by.differential_verification) {
    const d = by.differential_verification;
    tiles.push(tile("Diferencial", `${d.equivalent}/${d.comparable} ${d.passed ? "✓" : "✗"}`));
  }
  $("#summary").replaceChildren(...tiles);
}

let lastEvidence = [];
async function loadEvidence(req = state.req) {
  const { evidence, total } = await api(`/api/evidence?subject=${encodeURIComponent(state.subject)}&limit=5000`);
  if (req !== state.req) return;   // respuesta de un objetivo anterior
  lastEvidence = evidence;
  if (total > evidence.length) setStatus(`Se muestran ${evidence.length} de ${total} evidencias.`);
  try {
    renderSummary(evidence);
  } catch (err) {   // una evidencia con forma inesperada no deja el detalle en blanco sin avisar
    console.error(err);
    setStatus(`No se pudo mostrar el resumen: ${err.message}`, true);
  }
  renderEvidence();
}

function renderEvidence() {
  const f = $("#filter").value.trim().toLowerCase();
  const items = lastEvidence.filter((e) => !f || e.operation.toLowerCase().includes(f) || e.provider.toLowerCase().includes(f));
  $("#evidence").replaceChildren(...items.map((e) => {
    const conf = { high: "ok", medium: "warn", low: "bad" }[e.confidence] || "";
    // El cuerpo (JSON a veces enorme) se construye al ABRIR la evidencia, no al pintar la lista (M4).
    const body = el("div", { class: "body" });
    const d = el("details", { class: "ev" },
      el("summary", {},
        el("span", { class: "op" }, e.operation),
        el("span", { class: "muted" }, `${e.provider} ${e.provider_version}`),
        el("span", { class: "badge " + conf }, e.confidence),
        el("span", { class: "badge" }, e.authority)),
      body);
    d.addEventListener("toggle", () => {
      if (!d.open || body.childElementCount) return;
      body.append(
        e.limitations ? el("p", { class: "muted small" }, "Límites: ", e.limitations) : "",
        Object.keys(e.params || {}).length ? el("pre", {}, JSON.stringify(e.params, null, 2)) : "",
        el("pre", {}, JSON.stringify(e.result, null, 2)),
        el("p", { class: "muted small" }, `id ${e.evidence_id} · ${fmtTime(e.created_at)} · ${e.environment}`));
    });
    return d;
  }));
}

async function loadIncognitas(req = state.req) {
  const showResolved = $("#show-resolved").checked;
  const { incognitas } = await api(`/api/incognitas?subject=${encodeURIComponent(state.subject)}`);
  if (req !== state.req) return;
  const list = incognitas.filter((i) => showResolved || i.status !== "resolved");
  const ul = $("#incognitas");
  if (!list.length) {
    ul.replaceChildren(el("li", { class: "muted" }, "Sin incógnitas abiertas."));
    return;
  }
  const sev = { critical: "bad", high: "bad", medium: "warn" };
  ul.replaceChildren(...list.map((i) => el("li", { class: i.status },
    el("span", { class: "badge " + (sev[i.severity] || "") }, i.severity),
    el("span", { class: "q" }, i.question),
    i.status !== "resolved"
      ? el("button", { "aria-label": `Resolver: ${i.question}`, onclick: async () => {
          try { await api(`/api/incognitas/${i.incognita_id}/resolve`, { method: "POST", body: "{}" }); await selectSubject(state.subject); }
          catch (err) { setStatus(err.message, true); }
        } }, "Resolver")
      : "")));
}

// -- triaje ----------------------------------------------------------------
async function runTriage(promise, label) {
  document.body.classList.add("busy");
  $("#go").disabled = true;
  $("#path-go").disabled = true;   // sin envíos dobles mientras se analiza
  setStatus(`Analizando ${label}…`);
  const t0 = performance.now();
  try {
    const rep = await promise();
    // Binario (proveedores) o web/repositorio/carpeta (otra forma de resultado): sin suponer campos.
    const secs = ((performance.now() - t0) / 1000).toFixed(1);
    const run = rep.providers_run || [], failed = rep.providers_failed || [];
    setStatus(`Listo en ${secs} s` + (run.length ? ` · ${run.length} proveedores` : "") +
      (rep.analyzed_as === "repo" ? " · analizada como carpeta/repositorio" : "") +
      (failed.length ? ` · fallaron: ${failed.join(", ")}` : ""));
    await loadSubjects();
    await selectSubject(rep.subject);
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    document.body.classList.remove("busy");
    $("#go").disabled = false;
    $("#path-go").disabled = false;
  }
}

let uploading = false;
async function uploadFile(file) {
  if (uploading) { setStatus("Ya se está subiendo un archivo: espera a que termine.", true); return; }
  uploading = true;
  const mode = $("#mode").value;
  const sel = analysisSelection();
  try {
    // 1) se guarda en disco por bloques (sin pasar entero por la memoria del servidor);
    // 2) el triaje corre como trabajo, con progreso en vivo.
    await runTriage(async () => {
      setStatus(`Subiendo ${file.name} (${(file.size / 1048576).toFixed(1)} MB)…`);
      const up = await api(`/api/upload?store=1&name=${encodeURIComponent(file.name)}`, {
        method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" } });
      return runJob("triage", { upload: up.upload, name: file.name, mode, ...(sel ? { providers: sel } : {}) }, liveStatus);
    }, file.name);
  } finally { uploading = false; }
}

function wire() {
  const drop = $("#drop");
  const input = $("#file");
  input.addEventListener("change", () => { $("#drop-text").textContent = input.files[0]?.name || "Suelta un archivo o haz clic"; });
  drop.addEventListener("click", (e) => { if (e.target !== input) input.click(); });   // ya no es un <label>
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault(); drop.classList.remove("over");
    if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]);
  });
  $("#upload-form").addEventListener("submit", (e) => {
    e.preventDefault();
    if (input.files[0]) uploadFile(input.files[0]);
    else setStatus("Elige un archivo primero.", true);
  });
  $("#path-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const path = $("#path").value.trim();
    if (!path) {
      setStatus(state.kind === "binary" ? "Escribe la ruta de un archivo o carpeta, o suelta un archivo arriba."
        : state.kind === "web" ? "Escribe una URL (https://…) o la ruta de un .html o de la carpeta del sitio."
          : "Escribe la ruta de una carpeta o una URL git.", true);
      $("#path").focus();
      return;
    }
    if (state.kind === "binary") {
      const sel = analysisSelection();
      runTriage(() => runJob("triage", { path, mode: $("#mode").value, ...(sel ? { providers: sel } : {}) }, liveStatus), path);
    } else if (state.kind === "web") {
      const body = { source: path, max_assets: Number($("#web-max").value) || 40 };
      if ($("#web-cross").checked) body.cross_origin = true;
      if ($("#web-robots").checked) body.ignore_robots = true;
      runTriage(() => runJob("web", body, liveStatus), path);
    } else {
      runTriage(() => runJob(state.kind, { source: path }, liveStatus), path);
    }
  });

  let filterTimer = null;   // sin repintar en cada tecla (M4)
  $("#filter").addEventListener("input", () => { clearTimeout(filterTimer); filterTimer = setTimeout(renderEvidence, 200); });
  $("#show-resolved").addEventListener("change", loadIncognitas);

  document.querySelectorAll(".tabs [data-kind]").forEach((tab) => tab.addEventListener("click", () => {
    state.kind = tab.dataset.kind;
    document.querySelectorAll(".tabs [data-kind]").forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
    const bin = state.kind === "binary";
    $("#upload-form").hidden = !bin;
    $("#web-opts").hidden = state.kind !== "web";
    $("#analysis-active").hidden = !bin || !analysisSelection();
    $("#analyze-panel").setAttribute("aria-labelledby", tab.id);
    $("#path").placeholder = PLACEHOLDER[state.kind];
    $("#path").focus();
  }));

  $("#compare-btn").addEventListener("click", async () => {
    const [a, b] = [...state.selected];
    try {
      const r = await api("/api/compare", { method: "POST", body: JSON.stringify({ a, b }) });
      await loadSubjects();
      if (r.subject) await selectSubject(r.subject);
      setStatus(`Comparación: ${Object.keys(r.changed).length} aspectos cambiaron.`);
    } catch (err) { setStatus(err.message, true); }
  });

  $("#create-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const typed = $("#create-sources").value.split("\n").map((x) => x.trim()).filter(Boolean);
    const sources = [...typed, ...state.selected];
    if (!sources.length) { renderCreate({ error: "Añade al menos una fuente o marca un objetivo." }); return; }
    const body = { sources, name: $("#create-name").value.trim() || "Nuevo proyecto",
      target: $("#create-target").value, verify: $("#create-verify").checked };
    if ($("#create-out").value.trim()) body.out = $("#create-out").value.trim();
    if ($("#create-sqlite").checked) body.db = "sqlite";
    if ($("#create-reanalyze").checked) body.reanalyze = true;
    if ($("#create-ai-model").value.trim()) body.ai_model = $("#create-ai-model").value.trim();
    if ($("#create-ai-base").value.trim()) body.ai_base_url = $("#create-ai-base").value.trim();
    if ($("#create-auth").checked) body.auth = true;
    if ($("#create-ai").value.trim()) {
      body.ai_brief = $("#create-ai").value.trim();
      body.ai_provider = $("#create-ai-provider").value;
    }
    $("#create-go").disabled = true;
    createLines.length = 0;
    renderCreate({ pending: `Analizando ${sources.length} fuente(s) y generando…` + (body.verify ? " (instalar y probar tarda unos minutos)" : "") });
    try {
      let r;
      try {
        r = await runJob("create", body, createLog);
      } catch (err) {
        // Escribir sobre la carpeta de origen exige confirmarlo (se hace copia de seguridad antes).
        if (!err.needsConfirm ||
            !confirm(`${err.message}\n\n¿Continuar? Si marcaste «instalar, compilar y probar», se verifica antes en una carpeta limpia.`)) throw err;
        createLines.length = 0;
        r = await runJob("create", { ...body, force: true }, createLog);
      }
      renderCreate(r);
      await loadSubjects();
      await selectSubject(r.subject);
    } catch (err) { renderCreate({ error: err.message }); }
    finally { $("#create-go").disabled = false; }
  });
}

// Progreso en vivo de «Crear»: últimas líneas del registro del trabajo.
const createLines = [];
function createLog(lines, elapsed) {
  createLines.push(...lines.map((l) => l.msg));
  renderCreate({ pending: `Trabajando… ${Math.round(elapsed)} s`, lines: createLines.slice(-8) });
}

// Progreso en vivo de «Analizar», en la línea de estado.
function liveStatus(lines, elapsed) {
  setStatus(`${lines[lines.length - 1].msg} · ${Math.round(elapsed)} s`);
}

function renderCreate(r) {
  const box = $("#create-result");
  if (r.pending) {
    box.replaceChildren(el("p", { class: "muted", role: "status" }, r.pending),
      ...(r.lines?.length ? [el("pre", { class: "small job-log" }, r.lines.join("\n"))] : []));
    return;
  }
  if (r.error) { box.replaceChildren(el("p", { class: "bad", role: "alert" }, r.error)); return; }
  const v = r.verification;
  box.replaceChildren(
    el("p", {}, el("strong", {}, `✓ Proyecto ${r.target}`), ` · ${r.files} archivos`),
    el("code", {}, r.out),
    ...(r.backup ? [el("p", { class: "small" }, "Copia de seguridad del original: ", el("code", {}, r.backup))] : []),
    el("p", {}, el("button", { type: "button", class: "small-btn", onclick: () => openVSCode(r.out) }, "Abrir en VS Code (dentro de Eolfi)")),
    ...(v ? [
      el("p", {}, v.ok ? "Instalado, compilado y probado: funciona." : "La verificación falló:"),
      ...v.steps.map((s) => el("div", { class: "step" }, el("span", { class: "badge " + (s.exit === 0 ? "ok" : "bad") },
        s.exit === 0 ? "OK" : "FALLO"), `${s.step} (${s.seconds} s)`)),
      ...v.steps.filter((s) => s.tail).map((s) => el("pre", {}, s.tail)),
    ] : [el("p", { class: "muted" }, "Sin verificar.")]),
    ...(r.assist ? [
      el("p", {}, el("strong", {}, r.assist.ok ? "✓ IA: " : "✗ IA (deshecho): "), r.assist.summary || ""),
      ...(r.assist.notes || []).map((n) => el("p", { class: "muted" }, "· " + n)),
      el("p", { class: "muted" }, `${r.assist.files_changed.length} archivos · ${r.assist.rounds.length} ronda(s) · `
        + `${r.assist.usage.input_tokens + r.assist.usage.output_tokens} tokens`),
    ] : []));
}

// -- Chats web: vista en directo del puente Electron + escribir desde el panel ----------
const chat = { provider: "meta", since: 0, events: [], timers: [], visible: false, liveBusy: false, conv: {} };
const convFor = (p) => chat.conv[p] || `panel-${p}`;
const CHAT_NAMES = { deepseek: "DeepSeek", gemini: "Gemini", meta: "Meta AI", chatgpt: "ChatGPT", copilot: "Copilot", lechat: "Le Chat" };

// Pestañas de chat según lo que anuncia el puente (los adaptadores declarativos añaden chats sin tocar el panel).
function ensureChatTabs(names) {
  const bar = document.querySelector(".chat-tabs");
  for (const n of names) {
    if (bar.querySelector(`[data-chat="${CSS.escape(n)}"]`)) continue;
    const b = el("button", { type: "button", role: "tab", "data-chat": n, "aria-selected": "false", "aria-controls": "chat-panel" },
      CHAT_NAMES[n] || n, " ", el("span", { class: "dot", "aria-hidden": "true" }), el("span", { class: "visually-hidden state" }));
    b.addEventListener("click", () => selectChat(n));
    bar.append(b);
  }
  const box = $("#compare-choice");
  for (const n of names) {
    if (box.querySelector(`input[value="${CSS.escape(n)}"]`)) continue;
    box.append(el("label", {}, el("input", { type: "checkbox", value: n }), ` ${CHAT_NAMES[n] || n}`));
  }
}

function selectChat(name) {
  chat.provider = name;
  document.querySelectorAll(".chat-tabs [data-chat]").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.chat === name)));
  $("#live-caption").textContent = `Vista en directo de la ventana «${CHAT_NAMES[name]}» del puente`;
  const live = $("#chat-live");
  if (live) { live.textContent = ""; delete live.dataset.id; }
  renderChatLog();
  refreshLive(true);
}

function refreshLive(now = false) {
  if (!chat.visible || document.hidden) return;   // pestaña en segundo plano: en pausa (B8)
  if (chat.liveBusy) { if (now) chat.liveAgain = true; return; }   // nunca dos cargas solapadas
  const img = $("#live-img");
  chat.liveBusy = true;
  img.onload = () => { $("#live-caption").textContent = `Vista en directo de «${CHAT_NAMES[chat.provider]}»`; done(); };
  img.onerror = () => {
    // Una sola consulta para mostrar el motivo; y se espera más antes de reintentar.
    fetch(img.src).then((r) => r.json()).then((d) => { if (d.error) $("#live-caption").textContent = d.error; }).catch(() => {});
    done(5000);
  };
  const done = (wait = 1500) => {
    chat.liveBusy = false;
    clearTimeout(chat.liveTimer);
    if (!chat.visible) return;
    if (chat.liveAgain) { chat.liveAgain = false; refreshLive(); return; }
    chat.liveTimer = setTimeout(refreshLive, wait);
  };
  img.src = `/api/bridge/screen?provider=${chat.provider}&t=${Date.now()}`;
}

async function pollBridge() {
  if (!chat.visible || document.hidden) return;
  clearTimeout(chat.pollTimer);
  if (chat.inFlight) { chat.pollAgain = true; return; }   // nunca dos bucles a la vez (A3)
  chat.inFlight = true;
  try {
    const st = await api("/api/bridge/status");
    $("#bridge-state").textContent = st.running ? `Puente activo · ${st.engine || "Electron"}` : (st.detail || "Puente parado");
    ensureChatTabs(Object.keys(st.providers || {}));
    document.querySelectorAll(".chat-tabs [data-chat]").forEach((t) => {
      const p = (st.providers || {})[t.dataset.chat];
      const dot = t.querySelector(".dot");
      dot.className = "dot" + (p?.busy ? " busy" : p?.ok ? (p.signedIn === false ? " guest" : " ok") : "");
      t.title = p ? p.detail : "sin estado";
      const label = t.querySelector(".state");
      if (label) label.textContent = p?.busy ? ": ocupado" : p?.ok ? (p.signedIn === false ? ": modo invitado" : ": listo") : ": sin conexión";
    });
    if (st.running) {
      const ev = await api(`/api/bridge/events?since=${chat.since}`);
      const seen = new Set(chat.events.map((e) => e.id));
      const fresh = ev.events.filter((e) => !seen.has(e.id));
      const partials = ev.partials || [];
      const changed = JSON.stringify(partials.map((p) => [p.provider, p.length])) !== JSON.stringify((chat.partials || []).map((p) => [p.provider, p.length]));
      chat.partials = partials;
      if (fresh.length) {
        chat.events.push(...fresh);
        chat.events = chat.events.slice(-500);
      }
      if (fresh.length || changed) renderChatLog();
      chat.since = Math.max(chat.since, ev.last ?? 0);
    }
  } catch (err) {
    $("#bridge-state").textContent = err.message;
  } finally {
    chat.inFlight = false;
  }
  if (!chat.visible) return;
  // Mientras un chat está escribiendo (texto parcial), se refresca más a menudo: streaming hacia el panel.
  chat.pollTimer = setTimeout(pollBridge, chat.pollAgain ? 0 : (chat.partials?.length ? 600 : 2000));
  chat.pollAgain = false;
}

function renderChatLog() {
  const log = $("#chat-log");
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  const items = chat.events.filter((e) => e.provider === chat.provider);
  if (!items.length) {
    log.replaceChildren(el("p", { class: "muted small" }, "Sin mensajes todavía en esta sesión del puente."));
    return;
  }
  log.replaceChildren(...items.map((e) => {
    const who = e.role === "user" ? (e.source === "panel" ? "Tú (panel)" : "Eolfi (automático)")
      : e.role === "assistant" ? CHAT_NAMES[e.provider] : "Error";
    const meta = el("span", { class: "meta" }, `${who} · ${new Date(e.ts).toLocaleTimeString()}`
      + (e.length && e.length > (e.text || "").length ? ` · ${e.length} caracteres` : ""));
    const long = (e.text || "").length > 1200 && e.source === "eolfi" && e.role === "user";
    const body = long
      ? el("details", {}, el("summary", {}, `Petición de Eolfi (${e.length || e.text.length} caracteres)`), e.text)
      : document.createTextNode(e.text || "");
    return el("div", { class: `msg ${e.role}` }, meta, body);
  }));
  const partial = (chat.partials || []).find((p) => p.provider === chat.provider);
  if (partial) {
    log.append(el("div", { class: "msg assistant partial", "aria-busy": "true" },
      el("span", { class: "meta" }, `${CHAT_NAMES[chat.provider] || chat.provider} · escribiendo… (${partial.length} caracteres)`),
      document.createTextNode(partial.text)));
  }
  if (atBottom) log.scrollTop = log.scrollHeight;
  // El lector de pantalla anuncia solo el último mensaje nuevo, no el historial entero cada 2 s.
  const last = items[items.length - 1];
  const live = $("#chat-live");
  if (live && last && live.dataset.id !== String(last.id)) {
    live.dataset.id = String(last.id);
    live.textContent = last.role === "assistant" ? `${CHAT_NAMES[last.provider]}: ${(last.text || "").slice(0, 300)}` : "";
  }
}

async function sendChat(ev) {
  ev?.preventDefault();
  const text = $("#chat-input").value.trim();
  if (!text) return;
  $("#chat-input").value = "";   // se borra al enviar; si falla, se devuelve
  $("#chat-send").disabled = true;
  $("#chat-status").textContent = `Enviando a ${CHAT_NAMES[chat.provider]}… (la respuesta aparecerá aquí)`;
  try {
    await api("/api/bridge/chat", { method: "POST", body: JSON.stringify({ provider: chat.provider, prompt: text, conversation: convFor(chat.provider) }) });
    $("#chat-status").textContent = "";
  } catch (err) {
    if (!$("#chat-input").value) $("#chat-input").value = text;
    $("#chat-status").textContent = err.message;
  } finally {
    $("#chat-send").disabled = false;
    pollBridge();
  }
}

// -- Vista interactiva: el ratón y el teclado del panel van a la ventana real --------
const LIVE_KEYS = new Set(["Enter", "Backspace", "Tab", "Escape", "Delete", "ArrowUp", "ArrowDown",
  "ArrowLeft", "ArrowRight", "PageDown", "PageUp"]);
let typeBuffer = "", typeTimer = null;

async function sendInput(ev) {
  try {
    await api("/api/bridge/input", { method: "POST", body: JSON.stringify({ provider: chat.provider, ...ev }) });
  } catch (err) {
    $("#chat-status").textContent = err.message;
  }
  setTimeout(() => refreshLive(true), 250);
}

function flushTyping() {
  clearTimeout(typeTimer);
  if (!typeBuffer) return Promise.resolve();
  const text = typeBuffer;
  typeBuffer = "";
  return sendInput({ type: "text", text });
}

function wireLive() {
  const img = $("#live-img");
  const rel = (e) => {
    const r = img.getBoundingClientRect();
    return { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) };
  };
  img.addEventListener("click", async (e) => {
    img.focus();
    await flushTyping();
    sendInput({ type: "click", ...rel(e) });
  });
  img.addEventListener("wheel", (e) => {
    e.preventDefault();
    sendInput({ type: "wheel", ...rel(e), deltaY: Math.round(e.deltaY) });
  }, { passive: false });
  img.addEventListener("keydown", async (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (LIVE_KEYS.has(e.key)) {
      e.preventDefault();
      await flushTyping();
      sendInput({ type: "key", key: e.key });
    } else if (e.key.length === 1) {
      e.preventDefault();
      typeBuffer += e.key;
      clearTimeout(typeTimer);
      typeTimer = setTimeout(flushTyping, 180);
    }
  });
  img.addEventListener("paste", (e) => {
    const text = e.clipboardData?.getData("text");
    if (text) { e.preventDefault(); typeBuffer += text; flushTyping(); }
  });
}

function wireChats() {
  wireLive();
  // Los enlaces de la cabecera cambian el hash; route() muestra la vista (y el botón Atrás vuelve).
  document.querySelectorAll(".chat-tabs [data-chat]").forEach((t) => t.addEventListener("click", () => selectChat(t.dataset.chat)));
  $("#chat-form").addEventListener("submit", sendChat);
  $("#chat-selftest").addEventListener("click", runSelftest);
  $("#compare-form").addEventListener("submit", runCompare);
  $("#chat-new").addEventListener("click", () => {
    chat.conv[chat.provider] = `panel-${chat.provider}-${Date.now()}`;
    $("#chat-status").textContent = `El próximo mensaje abrirá una conversación nueva en ${CHAT_NAMES[chat.provider]}.`;
  });
  $("#chat-input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) sendChat(e); });   // Mayús+Intro: salto de línea
}

const ROUTES = { "#chats": "chats", "#proveedores": "providers", "#trabajos": "jobs", "#vscode": "vscode", "#analisis": "analysis", "": "analysis" };
function route() {
  const h = location.hash;
  if (h.startsWith("#objetivo/")) {
    const subject = decodeURIComponent(h.slice("#objetivo/".length));
    if (subject !== state.subject) selectSubject(subject); else showView("content");
    return;
  }
  showView(ROUTES[h] || "analysis");
}
window.addEventListener("hashchange", route);
window.addEventListener("popstate", route);

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && chat.visible) { refreshLive(true); pollBridge(); }
});

(async function init() {
  wire();
  wireChats();
  wireJobs();
  route();
  try {
    const h = await api("/api/health");
    $("#version").textContent = `v${h.version} · ${h.db}`;
    await Promise.all([loadProviders(), loadSubjects()]);
  } catch (err) {
    setStatus(`No se pudo conectar con la API: ${err.message}`, true);
  }
})();


// -- Selector de carpetas: desplegable navegable para cualquier campo de ruta -------------
let picker = null, pickerBtn = null;
function closePicker(focusBack = false) {
  const btn = pickerBtn;
  picker?.remove(); picker = null; pickerBtn = null;
  document.removeEventListener("click", outsidePicker, true);
  document.removeEventListener("keydown", pickerKeys, true);
  if (focusBack) btn?.focus();
}
// En «click» y en fase de captura: si se cerrara en mousedown, el contenido subiría y el clic caería en
// otro sitio («Crear» no hacía nada). El clic sigue su camino normal hasta el botón pulsado.
function outsidePicker(e) { if (picker && !picker.contains(e.target) && !e.target.closest(".pick")) closePicker(); }
function pickerKeys(e) { if (e.key === "Escape" && picker) { e.preventDefault(); closePicker(true); } }

async function openPicker(btn) {
  const field = $("#" + btn.dataset.pick);
  const append = !!btn.dataset.append;
  closePicker();
  pickerBtn = btn;
  picker = el("div", { class: "picker", role: "dialog", "aria-label": "Elegir carpeta" });
  (btn.closest(".row") || btn).after(picker);
  document.addEventListener("click", outsidePicker, true);
  document.addEventListener("keydown", pickerKeys, true);
  const choose = (path) => {
    field.value = append ? (field.value.trim() ? field.value.trim() + "\n" : "") + path : path;
    closePicker();
    field.focus();
  };
  const show = async (path) => {
    let r;
    try { r = await api("/api/fs/list?path=" + encodeURIComponent(path)); }
    catch (err) {
      if (path) return show("");
      picker?.replaceChildren(el("p", { class: "small bad", role: "alert" }, err.message));
      return;
    }
    if (!picker) return;
    const head = el("code", { class: "small picker-head" }, r.path || "Unidades y carpeta personal");
    const actions = el("div", { class: "row" });
    if (r.parent !== null) {
      const up = el("button", { type: "button", class: "small-btn" }, "⬆ Subir");
      up.addEventListener("click", () => show(r.parent));
      actions.append(up);
    }
    if (r.path) {
      const ok = el("button", { type: "button" }, "Elegir esta carpeta");
      ok.addEventListener("click", () => choose(r.path));
      actions.append(ok);
    }
    const cancel = el("button", { type: "button", class: "small-btn" }, "Cancelar");
    cancel.addEventListener("click", closePicker);
    actions.append(cancel);
    const list = el("ul", { class: "plain picker-list" }, ...r.dirs.map((d) => {
      const b = el("button", { type: "button", class: "picker-item", title: "Abrir · doble clic para elegir" },
        el("span", { "aria-hidden": "true" }, "📁 "), d.name);
      b.addEventListener("click", () => show(d.path));
      b.addEventListener("dblclick", () => choose(d.path));
      return el("li", {}, b);
    }));
    if (!r.dirs.length) list.append(el("li", { class: "small muted" }, "(sin subcarpetas)"));
    picker.replaceChildren(head, actions, list);
    (list.querySelector("button") || actions.querySelector("button"))?.focus();   // el foco entra en el selector
  };
  // Empieza en la carpeta escrita (o su carpeta padre si es un archivo); si no existe, en las unidades.
  const typed = append ? "" : field.value.trim();
  await show(typed);
}
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".pick");
  if (!btn) return;
  e.preventDefault();
  if (picker && pickerBtn === btn) closePicker(); else openPicker(btn);
});


// -- Accesibilidad: zona de soltar con teclado y pestañas con flechas ---------------------
(() => {
  const drop = document.getElementById("drop");
  drop?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); document.getElementById("file").click(); }
  });
  document.addEventListener("keydown", (e) => {
    const tab = e.target.closest?.('[role="tab"]');
    if (!tab || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
    const tabs = [...tab.closest('[role="tablist"]').querySelectorAll('[role="tab"]')];
    const i = tabs.indexOf(tab);
    const next = e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1
      : (i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    e.preventDefault();
    tabs[next].focus();
    tabs[next].click();
  });
})();


// -- Pestaña «Proveedores»: IA, proveedores de análisis y tema ---------------------------
const STORE = { ai: "eolfi.ai", analysis: "eolfi.analysis", theme: "eolfi.theme" };
const MODE_SETS = {
  local: (p) => p.mode === "local",
  default: (p) => p.mode === "local" || p.mode === "default",
  deep: (p) => p.mode !== "ia",
};

function analysisSelection() {
  try {
    let v = JSON.parse(localStorage.getItem(STORE.analysis) || "null");
    if (!Array.isArray(v) || !v.length) return null;
    // Nombres que ya no existen (proveedor renombrado o quitado): se descartan en vez de dar 400 (B3).
    if (state.providers) {
      const known = new Set(state.providers.filter((p) => p.mode !== "ia").map((p) => p.name));
      const kept = v.filter((n) => known.has(n));
      if (kept.length !== v.length) {
        if (kept.length) localStorage.setItem(STORE.analysis, JSON.stringify(kept)); else localStorage.removeItem(STORE.analysis);
        v = kept;
      }
    }
    return v.length ? v : null;
  } catch { return null; }
}

function showAnalysisChoice() {
  const sel = analysisSelection();
  const p = $("#analysis-active");
  if (!p) return;
  p.hidden = !sel || state.kind !== "binary";
  if (!sel) return;
  const reset = el("button", { type: "button", class: "small-btn" }, "usar el modo");
  reset.addEventListener("click", () => { localStorage.removeItem(STORE.analysis); renderProvidersView(); });
  p.replaceChildren(`Proveedores elegidos en «Proveedores» (${sel.length}): ${sel.join(", ")} · `, reset);
}

function applyAiChoice(name) {
  const sel = $("#create-ai-provider");
  if (![...sel.options].some((o) => o.value === name)) sel.append(el("option", { value: name }, `IA: ${name}`));
  sel.value = name;
}

function renderProvidersView() {
  const all = state.providers || [];
  // IA
  const ias = all.filter((p) => p.mode === "ia");
  // Sin elección guardada: la primera IA disponible (no una que no está instalada).
  const current = localStorage.getItem(STORE.ai)
    || (ias.find((p) => p.available) || ias.find((p) => p.name === "ia:claude") || { name: "ia:claude" }).name.slice(3);
  $("#ai-choice").replaceChildren(...ias.map((p) => {
    const name = p.name.slice(3);
    const input = el("input", { type: "radio", name: "ai", value: name });
    input.checked = name === current;
    input.addEventListener("change", () => { localStorage.setItem(STORE.ai, name); applyAiChoice(name); });
    return el("label", { class: "choice" }, input, ` ${name} `,
      el("span", { class: "badge " + (p.available ? "ok" : "") }, p.available ? "sí" : "no"),
      el("span", { class: "muted small" }, ` ${p.version || ""}`));
  }));
  applyAiChoice(current);
  // Análisis
  const saved = analysisSelection();
  const mode = $("#mode").value;
  $("#analysis-choice").replaceChildren(...all.filter((p) => p.mode !== "ia").map((p) => {
    const input = el("input", { type: "checkbox", value: p.name });
    input.checked = saved ? saved.includes(p.name) : MODE_SETS[mode](p);
    input.addEventListener("change", saveAnalysis);
    return el("label", { class: "choice" + (p.available ? "" : " unavailable") }, input, ` ${p.name} `,
      el("span", { class: "badge " + (p.available ? "ok" : "") }, p.available ? "sí" : "no"),
      el("span", { class: "badge" }, p.mode),
      p.available ? "" : el("span", { class: "muted small" }, " (no instalado: se omitirá)"));
  }));
  showAnalysisChoice();
  $("#analysis-note").textContent = saved
    ? `Se usará esta selección (${saved.length}) en lugar del modo «${mode}» del formulario Analizar.`
    : `Sin selección propia: se usa el modo «${mode}» del formulario Analizar.`;
  // Tema
  const theme = localStorage.getItem(STORE.theme) || "auto";
  document.querySelectorAll('input[name="theme-radio"]').forEach((r) => { r.checked = r.value === theme; });
  $("#theme").value = theme;
}

function saveAnalysis() {
  const names = [...document.querySelectorAll("#analysis-choice input:checked")].map((i) => i.value);
  if (names.length) localStorage.setItem(STORE.analysis, JSON.stringify(names));
  else localStorage.removeItem(STORE.analysis);
  renderProvidersView();
}

function setTheme(value) {
  if (value === "light" || value === "dark") {
    document.documentElement.dataset.theme = value;
    localStorage.setItem(STORE.theme, value);
  } else {
    delete document.documentElement.dataset.theme;
    localStorage.removeItem(STORE.theme);
  }
  renderProvidersView();
}

(() => {
  $("#theme").addEventListener("change", (e) => setTheme(e.target.value));
  document.addEventListener("change", (e) => { if (e.target.name === "theme-radio") setTheme(e.target.value); });
  document.querySelectorAll("[data-preset]").forEach((b) => b.addEventListener("click", () => {
    const names = (state.providers || []).filter((p) => p.mode !== "ia" && MODE_SETS[b.dataset.preset](p)).map((p) => p.name);
    localStorage.setItem(STORE.analysis, JSON.stringify(names));
    renderProvidersView();
  }));
  $("#create-ai-provider").addEventListener("change", (e) => { localStorage.setItem(STORE.ai, e.target.value); renderProvidersView(); });
  $("#analysis-reset").addEventListener("click", () => { localStorage.removeItem(STORE.analysis); renderProvidersView(); });
  $("#mode").addEventListener("change", () => { if (!analysisSelection()) renderProvidersView(); });
})();


// -- Pestaña «Trabajos»: cola, progreso, cancelar y repetir ----------------------------------
const JOB_STATE = { queued: ["en cola", "warn"], running: ["en marcha", "warn"], done: ["hecho", "ok"],
  error: ["error", "bad"], cancelled: ["cancelado", ""] };
const JOB_KIND = { triage: "binario", web: "web", repo: "repositorio", create: "crear" };
var jobsTimer = null;   // var: init() puede llamar a loadJobs() antes de llegar aquí

async function loadJobs() {
  clearTimeout(jobsTimer);
  let data;
  try { data = await api("/api/jobs"); } catch (err) { $("#jobs-state").textContent = err.message; return; }
  const active = data.jobs.filter((j) => j.status === "running" || j.status === "queued").length;
  const badge = $("#jobs-badge");
  badge.hidden = !active;
  badge.textContent = active ? String(active) : "";
  if (state.view === "jobs") {
    $("#jobs-state").textContent = `${active} en marcha o en cola · como mucho ${data.max_running} a la vez`;
    renderJobs(data.jobs);
  }
  // Mientras haya trabajos activos (o la vista esté abierta) se refresca; si no, cada 15 s para el contador.
  if (!document.hidden) jobsTimer = setTimeout(loadJobs, active || state.view === "jobs" ? 1500 : 15000);
}

function renderJobs(jobs) {
  const fmtDur = (j) => (j.finished || j.started) ? `${Math.round(((j.finished || Date.now() / 1000) - j.started))} s` : "";
  const rows = jobs.map((j) => {
    const [label, cls] = JOB_STATE[j.status] || [j.status, ""];
    const actions = el("td", {});
    if (j.status === "running" || j.status === "queued") {
      actions.append(el("button", { type: "button", class: "small-btn", "aria-label": `Cancelar «${j.label || j.id}»`,
        onclick: async () => { try { await api(`/api/jobs?id=${j.id}`, { method: "DELETE" }); loadJobs(); } catch (e) { setStatus(e.message, true); } } }, "Cancelar"));
    } else {
      actions.append(el("button", { type: "button", class: "small-btn", "aria-label": `Repetir «${j.label || j.id}»`,
        onclick: async () => { try { await api(`/api/jobs/${j.id}/repeat`, { method: "POST", body: "{}" }); loadJobs(); } catch (e) { setStatus(e.message, true); } } }, "Repetir"));
      if (j.subject) actions.append(" ", el("a", { href: "#objetivo/" + encodeURIComponent(j.subject) }, "Ver"));
    }
    const what = el("td", { class: "what" }, j.label || "—");
    if (j.error) what.append(el("div", { class: "small bad" }, j.error.slice(0, 300)));
    return el("tr", {}, el("td", {}, el("span", { class: "badge " + cls }, label)), el("td", {}, JOB_KIND[j.kind] || j.kind),
      what, el("td", { class: "small" }, fmtTime(j.started)), el("td", { class: "small" }, fmtDur(j)), actions);
  });
  $("#jobs").replaceChildren(...(rows.length ? rows : [el("tr", {}, el("td", { colspan: "6", class: "muted" }, "Aún no hay trabajos."))]));
}

function wireJobs() {
  document.addEventListener("visibilitychange", () => { if (!document.hidden) loadJobs(); });
  loadJobs();
}

// -- Atajos de teclado ------------------------------------------------------------------------
document.addEventListener("keydown", (e) => {
  const t = e.target;
  const typing = t.closest?.("input, textarea, select, [contenteditable='true'], #live-img");
  if (e.altKey && !e.ctrlKey && !e.metaKey && /^[1-4]$/.test(e.key)) {
    e.preventDefault();
    location.hash = ["#analisis", "#chats", "#proveedores", "#trabajos"][Number(e.key) - 1];
    return;
  }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "/") {
    e.preventDefault();
    (state.view === "content" ? $("#filter") : $("#path")).focus();
  } else if (e.key === "?") {
    e.preventDefault();
    $("#help").showModal();
  }
});
document.getElementById("open-help").addEventListener("click", () => $("#help").showModal());


// -- Puente: autodiagnóstico de selectores (no escribe nada en el chat) ------------------------
async function runSelftest() {
  const box = $("#chat-diag");
  box.hidden = false;
  box.replaceChildren(el("p", { class: "muted", role: "status" }, `Comprobando ${CHAT_NAMES[chat.provider] || chat.provider}…`));
  let r;
  try { r = await api(`/api/bridge/selftest?provider=${encodeURIComponent(chat.provider)}&discover=1`); }
  catch (err) { box.replaceChildren(el("p", { class: "bad", role: "alert" }, err.message)); return; }
  const head = el("p", {}, el("strong", {}, r.ok ? "✓ El adaptador encuentra lo necesario" : "✗ Hay problemas"),
    r.declarative && !r.calibrated ? " · selectores sin calibrar todavía" : "");
  const parts = [head, ...(r.problems || []).map((p) => el("p", { class: "bad" }, "· " + p))];
  if (r.groups) {
    const rows = Object.entries(r.groups).flatMap(([g, list]) => list.map((x) => el("tr", {},
      el("td", {}, g), el("td", {}, el("code", {}, x.selector)), el("td", {}, x.error || String(x.visible)))));
    parts.push(el("table", {}, el("thead", {}, el("tr", {}, el("th", { scope: "col" }, "Parte"), el("th", { scope: "col" }, "Selector"),
      el("th", { scope: "col" }, "Visibles"))), el("tbody", {}, ...rows)));
    parts.push(el("p", { class: "muted" }, "Para recalibrar, copia en ", el("code", {}, r.overrides),
      ` los selectores corregidos de «${chat.provider}» (mismas claves que adapters/sites.json) y reinicia el puente.`));
  }
  if (r.discover) {
    parts.push(el("details", {}, el("summary", {}, "Candidatos encontrados en la página (atributos, sin texto de mensajes)"),
      el("pre", {}, JSON.stringify(r.discover, null, 1))));
  }
  box.replaceChildren(...parts);
}

// -- Puente: comparativa multi-chat --------------------------------------------------------
async function runCompare(ev) {
  ev.preventDefault();
  const providers = [...document.querySelectorAll("#compare-choice input:checked")].map((i) => i.value);
  const prompt = $("#compare-input").value.trim();
  if (providers.length < 2) { $("#compare-status").textContent = "Marca al menos dos chats."; return; }
  if (!prompt) { $("#compare-status").textContent = "Escribe el mensaje."; return; }
  $("#compare-go").disabled = true;
  $("#compare-status").textContent = `Enviando a ${providers.map((p) => CHAT_NAMES[p] || p).join(", ")}…`;
  const t0 = performance.now();
  try {
    const r = await api("/api/bridge/compare", { method: "POST", body: JSON.stringify({ providers, prompt,
      conversation: `panel-compare-${Date.now()}` }) });
    $("#compare-status").textContent = `Listo en ${((performance.now() - t0) / 1000).toFixed(1)} s` +
      (r.skipped_busy?.length ? ` · ocupados: ${r.skipped_busy.join(", ")}` : "");
    $("#compare-results").replaceChildren(...Object.entries(r.results).map(([p, x]) => el("article", {},
      el("h4", {}, `${CHAT_NAMES[p] || p}${x.seconds != null ? ` · ${x.seconds} s` : ""}`),
      x.error ? el("p", { class: "bad" }, x.error) : document.createTextNode(x.text))));
  } catch (err) { $("#compare-status").textContent = err.message; }
  finally { $("#compare-go").disabled = false; }
}


// -- VS Code dentro de Eolfi (code serve-web) -------------------------------------------------
const vsc = { folder: null };

async function openVSCode(folder) {
  vsc.folder = folder || null;
  if (location.hash !== "#vscode") location.hash = "#vscode"; else showVSCode();
}

async function showVSCode() {
  let st;
  try { st = await api("/api/vscode/status"); } catch (err) { $("#vscode-state").textContent = err.message; return; }
  if (!st.available) { $("#vscode-state").textContent = "No se encuentra el comando «code» de VS Code."; return; }
  $("#vscode-license-link").href = st.license_url;
  if (!st.license_accepted) {
    $("#vscode-license").hidden = false;
    $("#vscode-frame").hidden = true;
    $("#vscode-state").textContent = "Falta aceptar la licencia del servidor de VS Code.";
    return;
  }
  await startVSCode(false);
}

async function startVSCode(accept) {
  $("#vscode-license").hidden = true;
  $("#vscode-state").textContent = "Arrancando VS Code… (la primera vez descarga el servidor y tarda un poco)";
  try {
    const r = await api("/api/vscode/start", { method: "POST", body: JSON.stringify({
      ...(vsc.folder ? { folder: vsc.folder } : {}), ...(accept ? { accept_license: true } : {}) }) });
    const frame = $("#vscode-frame");
    if (frame.src !== r.url) frame.src = r.url;
    frame.hidden = false;
    $("#vscode-external").href = r.url;
    $("#vscode-external").hidden = false;
    $("#vscode-state").textContent = r.folder ? `Carpeta: ${r.folder}` : "Sin carpeta: ábrela desde VS Code";
  } catch (err) {
    $("#vscode-state").textContent = err.message;
    if (/licencia/.test(err.message)) $("#vscode-license").hidden = false;
  }
}

$("#vscode-accept").addEventListener("change", (e) => { $("#vscode-go").disabled = !e.target.checked; });
$("#vscode-go").addEventListener("click", () => startVSCode(true));
$("#vscode-stop").addEventListener("click", async () => {
  await api("/api/vscode/stop", { method: "POST", body: "{}" }).catch(() => {});
  $("#vscode-frame").removeAttribute("src");
  $("#vscode-frame").hidden = true;
  $("#vscode-external").hidden = true;
  $("#vscode-state").textContent = "VS Code detenido.";
});
$("#create-vscode").addEventListener("click", () => openVSCode($("#create-out").value.trim() || null));

// -- Vincular VS Code (la extensión exige iniciar sesión con un código) ---------------------------
async function loadClients() {
  let r;
  try { r = await api("/api/clients"); } catch { return; }
  $("#clients").replaceChildren(...(r.clients.length ? r.clients.map((c) => el("li", {},
    `${c.name} · vinculado ${fmtTime(c.created)}${c.last_used ? ` · último uso ${fmtTime(c.last_used)}` : ""} `,
    el("button", { type: "button", class: "small-btn", "aria-label": `Revocar ${c.name}`,
      onclick: async () => { await api(`/api/clients?id=${encodeURIComponent(c.id)}`, { method: "DELETE" }); loadClients(); } }, "Revocar")))
    : [el("li", { class: "muted" }, "Ningún VS Code vinculado.")]));
}

// Vinculación directa: el código nunca se muestra; viaja solo en el enlace vscode:// que abre VS Code.
$("#pair-auto").addEventListener("click", async () => {
  try {
    const r = await api("/api/clients/pair", { method: "POST", body: "{}" });
    location.href = `vscode://eolfi.eolfi-vscode-bridge/login?code=${r.code}`;
    $("#pair-code").textContent = "Abriendo VS Code… (si pregunta, permite abrir el enlace)";
    setTimeout(loadClients, 6000);
  } catch (err) { $("#pair-code").textContent = err.message; }
});

$("#pair-go").addEventListener("click", async () => {
  try {
    const r = await api("/api/clients/pair", { method: "POST", body: "{}" });
    $("#pair-code").textContent = r.code;
    setTimeout(() => { if ($("#pair-code").textContent === r.code) $("#pair-code").textContent = ""; loadClients(); }, r.expires_in * 1000);
  } catch (err) { $("#pair-code").textContent = err.message; }
});

// Menú «Exportar»: se cierra al hacer clic fuera, con Esc o al elegir un formato.
document.addEventListener("click", (e) => {
  const m = document.querySelector(".menu[open]");
  if (m && (!m.contains(e.target) || e.target.closest(".menu-list a"))) m.removeAttribute("open");
});
document.addEventListener("keydown", (e) => {
  const m = document.querySelector(".menu[open]");
  if (e.key === "Escape" && m) { m.removeAttribute("open"); m.querySelector("summary")?.focus(); }
});
