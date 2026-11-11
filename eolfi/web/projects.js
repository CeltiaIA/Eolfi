// Crear proyecto con plan razonado: formulario único (nombre, descripción, fuentes), plan propuesto con su
// justificación, aprobación o edición, ejecución automática o guiada con progreso y cancelación, y resultado
// que solo sale en verde si la verificación pasa. Todo el estado vive en el caso (servidor), no en el navegador.
// El texto que viene del servidor o de las fuentes se pinta siempre como texto.
const KIND = { file: "Archivo o binario", web: "Web", repo: "Repositorio" };
const PLACEHOLDER = { web: "https://ejemplo.org/", repo: "https://github.com/usuario/proyecto.git o C:\\ruta\\del\\repo" };
const STATE = {
  awaiting_approval: ["Pendiente de tu aprobación", "warn"], ready: ["Aprobado, listo para ejecutar", "ok"],
  awaiting_continue: ["En pausa: revisa el paso y continúa", "warn"], change_proposed: ["Cambio de plan pendiente", "warn"],
  failed: ["Un paso falló", "bad"], done: ["Terminado y verificado", "ok"],
  done_unverified: ["Terminado SIN verificación superada", "bad"],
};
const STEP = { done: ["hecho", "ok"], partial: ["parcial", "warn"], error: ["error", "bad"], cancelled: ["cancelado", "bad"] };
const TARGETS = [["auto", "Auto (según las fuentes)"], ["static", "Web estática"], ["react", "React"], ["vue", "Vue"],
  ["svelte", "Svelte"], ["next", "Next.js"], ["fastapi", "FastAPI"], ["express", "Express"], ["django", "Django"],
  ["expo", "Móvil (Expo)"], ["desktop", "Escritorio (Electron)"], ["tauri", "Escritorio (Tauri)"],
  ["dotnet", "Escritorio .NET (Avalonia)"], ["cli", "Línea de comandos (Python)"]];

export function createProjectView({ $, el, api, setStatus }) {
  const sources = [];   // {kind, ref, label}
  let current = null;   // estado del proyecto (respuesta de /api/projects/…)
  let job = null;

  const badge = ([text, cls]) => el("span", { class: `badge ${cls}` }, text);
  const view = $("#proj-view");

  function syncKind() {
    const kind = $("#proj-kind").value;
    $("#proj-ref").hidden = kind === "file";
    $("#proj-file-label").hidden = kind !== "file";
    $("#proj-ref").placeholder = PLACEHOLDER[kind] || "";
    $("#proj-add").textContent = kind === "file" ? "Adjuntar" : "Añadir";
  }

  function renderSources() {
    const list = $("#proj-list");
    list.replaceChildren(...sources.map((s, i) => el("li", { class: "proj-source" },
      el("span", { class: "badge" }, KIND[s.kind]), el("span", { class: "proj-ref" }, s.label),
      el("button", { type: "button", class: "small-btn", "aria-label": `Quitar ${s.label}`,
        onclick: () => { sources.splice(i, 1); renderSources(); } }, "Quitar"))));
    $("#proj-hint").textContent = sources.length ? `${sources.length} fuente(s) adjunta(s)` : "Puedes empezar solo con el texto.";
  }

  async function addSource() {
    const kind = $("#proj-kind").value;
    if (kind === "file") {
      const files = [...$("#proj-file").files];
      if (!files.length) { setStatus("Elige uno o varios archivos para adjuntar", true); return; }
      $("#proj-add").disabled = true;
      try {
        for (const f of files) {
          setStatus(`Adjuntando ${f.name}…`);
          const r = await fetch(`/api/projects/upload?name=${encodeURIComponent(f.name)}`, {
            method: "POST", headers: { "X-Eolfi": "1", "Content-Type": "application/octet-stream" }, body: f });
          const d = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
          sources.push({ kind, ref: d.path, label: `${f.name} · ${d.sha256.slice(0, 12)}` });
        }
        $("#proj-file").value = "";
        setStatus("Archivos adjuntados (se analizarán al ejecutar el plan)");
      } catch (err) { setStatus(err.message, true); } finally { $("#proj-add").disabled = false; }
    } else {
      const ref = $("#proj-ref").value.trim();
      if (!ref) { setStatus("Escribe la URL o la ruta de la fuente", true); $("#proj-ref").focus(); return; }
      if (sources.some((s) => s.ref === ref)) { setStatus("Esa fuente ya está en la lista", true); return; }
      sources.push({ kind, ref, label: ref });
      $("#proj-ref").value = "";
    }
    renderSources();
  }

  async function propose(e) {
    e.preventDefault();
    const name = $("#proj-name").value.trim();
    if (!name) { setStatus("El proyecto necesita un nombre", true); $("#proj-name").focus(); return; }
    $("#proj-go").disabled = true;
    setStatus("Eolfi está leyendo las fuentes y la descripción para proponer un plan…");
    try {
      current = await api("/api/projects/plan", { method: "POST", body: JSON.stringify({
        name, description: $("#proj-desc").value, sources: sources.map((s) => s.ref),
        mode: document.querySelector("input[name=proj-mode]:checked").value }) });
        setStatus("Caso creado y plan propuesto: revisa la evaluación y apruébalo para empezar");
      render();
      view.querySelector("h3")?.focus();
    } catch (err) { setStatus(err.message, true); } finally { $("#proj-go").disabled = false; }
  }

  const post = async (path, body) => { current = await api(`/api/projects/${current.case_id}/${path}`, { method: "POST", body: JSON.stringify(body) }); render(); };

  function planBlock(plan, editable) {
    const parts = [];
    parts.push(el("div", { class: "row between" },
      el("h3", { tabindex: "-1" }, `Plan · versión ${plan.version}`), badge(STATE[current.status] || [current.status, ""])));
    if (plan.assessment) parts.push(el("div", { class: `proj-verdict proj-assessment ${plan.assessment.verdict === "favorable" ? "ok" : "bad"}` },
      `${plan.assessment.verdict === "favorable" ? "Evaluación inicial favorable" : "Evaluación inicial no favorable"}: ${plan.assessment.summary}`,
      el("div", { class: "small" }, plan.assessment.limits)));
    if (plan.changes?.length) parts.push(el("p", { class: "small warn" }, `Cambios respecto a la versión ${plan.revised_from}: ${plan.changes.join("; ")}`));
    parts.push(el("h4", {}, "Razonamiento"), el("ul", { class: "small" }, ...plan.reasoning.map((r) => el("li", {}, r))));
    const it = plan.interpretation;
    parts.push(el("h4", {}, "Qué se entendió de la descripción"),
      it.directives.length ? el("ul", { class: "plain small" }, ...it.directives.map((d) => el("li", {}, el("span", { class: "badge ok" }, d.text), ` → ${d.effect}`)))
        : el("p", { class: "small muted" }, "Ninguna directiva reconocida: tecnología y opciones según las fuentes."),
      it.uninterpreted.length ? el("div", { class: "small" }, el("strong", { class: "warn" }, "No se aplican automáticamente: "),
        el("ul", {}, ...it.uninterpreted.map((u) => el("li", {}, u)))) : "");
    if (plan.instructions?.length) parts.push(el("p", { class: "small" }, `Instrucciones añadidas: ${plan.instructions.join(" · ")}`));
    parts.push(el("h4", {}, "Pasos"), el("ol", { class: "proj-steps" }, ...plan.steps.map((s) => {
      const res = current.results[s.id];
      return el("li", { class: "proj-step" },
        el("div", { class: "row between" }, el("strong", {}, s.title), res ? badge(STEP[res.status] || [res.status, ""]) : el("span", { class: "badge" }, "pendiente")),
        el("dl", { class: "small proj-dl" },
          el("dt", {}, "Qué hace"), el("dd", {}, s.what), el("dt", {}, "Produce"), el("dd", {}, s.produces),
          el("dt", {}, "Verificación"), el("dd", {}, s.verification), el("dt", {}, "Por qué"), el("dd", {}, s.rationale),
          ...(s.risks.length ? [el("dt", {}, "Riesgos"), el("dd", { class: "warn" }, s.risks.join(" · "))] : [])),
        res ? stepResult(res) : "");
    })));
    if (editable) parts.push(editForm(plan));
    return parts;
  }

  function stepResult(r) {
    const bits = [];
    if (r.error) bits.push(el("div", { class: "bad small" }, r.error));
    if (r.subject) bits.push(el("div", { class: "small muted" }, `Objetivo: ${r.subject}`));
    if (r.spec_version) bits.push(el("div", { class: "small" }, `Especificación v${r.spec_version}: ${r.requirements} requisitos, ${r.artifacts} artefactos, ${r.contradictions} contradicciones, ${r.open_incognitas} incógnitas abiertas`));
    if (r.out) {
      bits.push(el("div", { class: `proj-verdict ${r.verified ? "ok" : "bad"}`, role: "status" },
        r.verified ? `Verificado: instalación, compilación y pruebas superadas (${r.target}, ${r.files} archivos)`
          : `NO VERIFICADO: ${r.verification?.error || "la verificación no se superó"} — no es un producto listo`),
        el("div", { class: "small" }, "Carpeta: ", el("code", {}, r.out)));
      if (r.verification?.steps?.length) bits.push(el("ul", { class: "plain small" }, ...r.verification.steps.map((s) => el("li", {}, `${s.exit === 0 ? "✓" : "✗"} ${s.step} (${s.seconds ?? "?"} s)`))));
    }
    return el("div", { class: "proj-result" }, ...bits);
  }

  function editForm(plan) {
    const target = el("select", { id: "proj-target", "aria-label": "Tecnología destino" },
      ...TARGETS.map(([v, l]) => { const o = el("option", { value: v }, l); if (v === plan.target) o.selected = true; return o; }));
    const box = (id, label, on) => { const i = el("input", { type: "checkbox", id }); i.checked = !!on; return el("label", { class: "small" }, i, ` ${label}`); };
    const mode = el("select", { id: "proj-mode-edit", "aria-label": "Modo de ejecución" },
      ...[["auto", "Automático"], ["guided", "Guiado (paso a paso)"]].map(([v, l]) => { const o = el("option", { value: v }, l); if (v === plan.mode) o.selected = true; return o; }));
    const note = el("textarea", { id: "proj-note", rows: "2", "aria-label": "Instrucciones o correcciones para el plan", placeholder: "Correcciones o instrucciones adicionales (opcional)" });
    return el("form", { class: "stack proj-edit", onsubmit: async (e) => {
      e.preventDefault();
      const edits = {};
      if (target.value !== plan.target) edits.target = target.value;
      const opts = { sqlite: $("#proj-sqlite").checked, auth: $("#proj-auth").checked };
      if (opts.sqlite !== plan.options.sqlite || opts.auth !== plan.options.auth) edits.options = opts;
      if (mode.value !== plan.mode) edits.mode = mode.value;
      if (note.value.trim()) edits.instructions = [note.value.trim()];
      try {
        await post("approve", { version: plan.version, edits: Object.keys(edits).length ? edits : null, note: note.value.trim() });
        setStatus(Object.keys(edits).length ? `Plan revisado (versión ${current.plan.version}) y aprobado` : "Plan aprobado");
        run();
      } catch (err) { setStatus(err.message, true); }
    } },
      el("h4", {}, "Revisar antes de aprobar"),
      el("div", { class: "row" }, target, mode),
      el("div", { class: "row" }, box("proj-sqlite", "base de datos SQLite", plan.options.sqlite), box("proj-auth", "inicio de sesión", plan.options.auth)),
      note,
      el("div", { class: "row between" }, el("span", { class: "small muted" }, "No se ejecuta nada hasta que apruebes."),
        el("button", { type: "submit", id: "proj-approve" }, "Aprobar y ejecutar")));
  }

  function controls() {
    const st = current.status;
    const out = [];
    if (job) {
      out.push(el("div", { class: "row between" }, el("span", { class: "small" }, job === "starting" ? "Iniciando el plan…" : "Ejecutando el plan…"),
        ...(job === "starting" ? [] : [el("button", { type: "button", class: "small-btn", id: "proj-cancel", onclick: cancel }, "Cancelar")])));
      out.push(el("pre", { class: "small proj-log", id: "proj-log", "aria-live": "polite" }, ""));
    } else if (st === "ready" || st === "awaiting_continue") {
      out.push(el("div", { class: "row between" },
        el("span", { class: "small" }, st === "ready" ? "Plan aprobado." : `Siguiente paso: ${current.next_step}.`),
        el("button", { type: "button", id: "proj-continue", onclick: run }, st === "ready" ? "Ejecutar" : "Continuar")));
      if (current.plan.mode === "guided") out.push(instructionForm());
    } else if (st === "change_proposed") {
      const ch = current.pending_change;
      out.push(el("div", { class: "proj-change", role: "alert" },
        el("strong", {}, "Cambio de plan propuesto"), el("p", { class: "small" }, `«${ch.text}» — ${ch.reason}`),
        el("div", { class: "row" },
          el("button", { type: "button", id: "proj-change-yes", onclick: () => post("change", { accept: true }).catch((e) => setStatus(e.message, true)) }, "Aprobar el cambio"),
          el("button", { type: "button", class: "small-btn", id: "proj-change-no", onclick: () => post("change", { accept: false }).catch((e) => setStatus(e.message, true)) }, "Rechazar y seguir el plan"))));
    } else if (st === "failed") {
      out.push(el("p", { class: "bad small" }, "Un paso falló. Corrige la fuente o el plan (crea un proyecto nuevo con los cambios) y vuelve a intentarlo."));
    }
    if (current.status.startsWith("done")) {
      out.push(el("p", {}, el("a", { href: `/api/cases/${current.case_id}/report`, target: "_blank", rel: "noopener", id: "proj-report" }, "Abrir el informe del caso"),
        " · ", el("a", { href: `#caso/${current.case_id}` }, "Ver el caso")));
    }
    return out;
  }

  function instructionForm() {
    const ta = el("textarea", { id: "proj-instruction", rows: "2", "aria-label": "Instrucción para los pasos siguientes", placeholder: "Añade una instrucción para lo que queda (p. ej. «añade inicio de sesión»)" });
    return el("form", { class: "stack", onsubmit: async (e) => {
      e.preventDefault();
      if (!ta.value.trim()) return;
      try { await post("instruction", { text: ta.value.trim() }); setStatus(current.status === "change_proposed" ? "La instrucción cambia el plan: apruébala o recházala" : "Instrucción guardada en el caso"); }
      catch (err) { setStatus(err.message, true); }
    } }, ta, el("div", { class: "row" }, el("button", { type: "submit", class: "small-btn", id: "proj-add-instruction" }, "Añadir instrucción")));
  }

  function decisions() {
    const ds = current.decisions;
    if (!ds.length) return "";
    const label = { approval: "Aprobación", instruction: "Instrucción", change_proposal: "Cambio propuesto", change_decision: "Decisión de cambio" };
    return el("details", { class: "small" }, el("summary", {}, `Hilo de decisiones (${ds.length})`),
      el("ol", {}, ...ds.map((d) => el("li", {}, `${label[d.type] || d.type} · v${d.plan_version}`
        + (d.text ? ` · «${d.text}»` : "") + (d.note ? ` · ${d.note}` : "") + (d.accepted !== undefined ? (d.accepted ? " · aceptado" : " · rechazado") : "")))));
  }

  function render() {
    if (!current) { view.hidden = true; return; }
    view.hidden = false;
    view.replaceChildren(el("section", { class: "card proj-plan", "aria-label": "Plan del proyecto" },
      ...planBlock(current.plan, current.status === "awaiting_approval"), ...controls(), decisions()));
  }

  async function run() {
    try {
      // Oculta «Continuar/Ejecutar» desde que empieza el POST; si esperamos a
      // recibir el job_id, el usuario puede avanzar otra vez durante esa carrera.
      job = "starting";
      render();
      const { job_id: id } = await api("/api/jobs", { method: "POST", body: JSON.stringify({ kind: "project", body: { case_id: current.case_id } }) });
      job = id; render();
      let since = 0;
      for (;;) {
        const d = await api(`/api/jobs?id=${id}&since=${since}`);
        since = d.next;
        const log = $("#proj-log");
        if (log && d.log.length) log.textContent += d.log.map((l) => `${l.t}s ${l.msg}`).join("\n") + "\n";
        if (!["queued", "running"].includes(d.status)) {
          if (d.status === "error") setStatus(d.error, true);
          else if (d.status === "cancelled") setStatus("Ejecución cancelada: el paso en curso quedó registrado como cancelado");
          break;
        }
        await new Promise((r) => setTimeout(r, 700));
      }
    } catch (err) { setStatus(err.message, true); }
    job = null;
    current = await api(`/api/projects/${current.case_id}`).catch(() => current);
    const [text] = STATE[current.status] || [current.status];
    setStatus(text, current.status === "failed" || current.status === "done_unverified");
    render();
  }

  async function cancel() {
    if (!job) return;
    try { await api(`/api/jobs?id=${job}`, { method: "DELETE" }); setStatus("Cancelando…"); } catch (err) { setStatus(err.message, true); }
  }

  $("#proj-kind").addEventListener("change", syncKind);
  $("#proj-add").addEventListener("click", addSource);
  $("#proj-ref").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addSource(); } });
  $("#proj-form").addEventListener("submit", propose);
  syncKind();
  renderSources();
  return { open: async (caseId) => { current = await api(`/api/projects/${caseId}`); render(); } };
}
