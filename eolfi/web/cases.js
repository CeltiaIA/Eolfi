// Casos de análisis: lista, caso activo (los análisis del panel se registran en él) y vista de progreso.
// Todo el texto procedente de objetivos se pinta como texto (el.append de nodos de texto).
const STATUS = { done: ["completado", "ok"], partial: ["parcial", "warn"], error: ["error", "bad"],
  cancelled: ["cancelado", "bad"], running: ["en marcha", "warn"], queued: ["en cola", "warn"] };
const CLAIM = { observed: "Observada", derived: "Derivada", hypothesis: "Hipótesis" };
const KEY = "eolfi.case";

export function createCaseView({ $, el, api, fmtTime, setStatus, showView, onChange = () => {} }) {
  const cs = { cases: [], active: null, shown: null, timer: null };
  try { cs.active = localStorage.getItem(KEY) || null; } catch { /* sin almacenamiento: sin caso activo */ }

  const badge = (status) => {
    const [label, cls] = STATUS[status] || [status || "registro", ""];
    return el("span", { class: `badge ${cls}` }, label);
  };

  function setActive(id) {
    cs.active = id;
    try { if (id) localStorage.setItem(KEY, id); else localStorage.removeItem(KEY); } catch { /* solo en memoria */ }
    renderActive();
    renderList();
    onChange(id);
  }

  function renderActive() {
    const box = $("#case-active");
    const c = cs.cases.find((x) => x.case_id === cs.active);
    if (cs.active && !c && cs.cases.length) { cs.active = null; try { localStorage.removeItem(KEY); } catch { /* */ } }
    box.replaceChildren(c
      ? el("span", {}, "Caso activo: ", el("strong", {}, c.name), " — los análisis y proyectos nuevos se registran en él. ",
        el("button", { type: "button", class: "small-btn", onclick: () => setActive(null) }, "Dejar de usar"))
      : el("span", { class: "muted" }, "Sin caso activo: los análisis no se registran en ningún caso."));
  }

  function renderList() {
    const ul = $("#cases");
    if (!cs.cases.length) { ul.replaceChildren(el("li", { class: "muted" }, "Aún no hay casos.")); return; }
    ul.replaceChildren(...cs.cases.map((c) => {
      const li = el("li", {},
        el("button", { type: "button", class: "subject-btn", "aria-current": c.case_id === cs.shown ? "true" : "false",
          onclick: () => openCase(c.case_id) },
          el("div", {}, c.name, c.case_id === cs.active ? el("span", { class: "badge ok" }, "activo") : "",
            c.last_record ? badge(c.last_record.status) : "",
            c.open_incognitas ? el("span", { class: "badge warn" }, `${c.open_incognitas} ?`) : ""),
          el("div", { class: "muted small" }, `${c.artifacts} artefactos · ${c.records} registros · ${fmtTime(c.updated_at)}`)));
      if (c.case_id === cs.shown) li.classList.add("active");
      return li;
    }));
  }

  async function loadCases() {
    try {
      cs.cases = (await api("/api/cases")).cases;
    } catch (err) { $("#cases").replaceChildren(el("li", { class: "bad" }, err.message)); return; }
    renderActive();
    renderList();
  }

  async function openCase(id) {
    cs.shown = id;
    if (location.hash !== `#caso/${id}`) history.pushState(null, "", `#caso/${id}`);
    showView("case");
    await refresh();
    renderList();
  }

  async function refresh() {
    clearTimeout(cs.timer);
    if (!cs.shown) return;
    let c;
    try { c = await api(`/api/cases/${cs.shown}`); } catch (err) {
      $("#case-body").replaceChildren(el("p", { class: "bad" }, err.message)); return;
    }
    render(c);
    // Mientras haya trabajos del caso en marcha, el progreso se actualiza solo.
    if (c.jobs.some((j) => j.status === "running" || j.status === "queued")) cs.timer = setTimeout(refresh, 1500);
  }

  function render(c) {
    $("#case-title").textContent = c.name;
    $("#case-meta").textContent = `${c.case_id} · creado ${fmtTime(c.created_at)} · actualizado ${fmtTime(c.updated_at)}`;
    $("#case-report").href = `/api/cases/${c.case_id}/report`;
    $("#case-export").href = `/api/cases/${c.case_id}/export`;
    $("#case-use").textContent = c.case_id === cs.active ? "Caso activo" : "Usar como caso activo";
    $("#case-use").disabled = c.case_id === cs.active;
    const open = c.incognitas.filter((i) => i.status !== "resolved");
    const parts = [];
    if (c.description) parts.push(el("p", {}, c.description));
    if (c.imports.length) {
      parts.push(el("p", { class: "small warn" }, `Caso importado (${c.imports.map((x) => x.source_name).join(", ")}): `
        + "la autoridad de sus evidencias la declaró el paquete; no se reverificó aquí."));
    }
    parts.push(el("p", { class: "small" }, `${c.artifacts.length} artefactos · ${c.records.length} registros · `
      + `${c.evidence.length} evidencias · ${open.length} incógnitas abiertas`));
    if (c.jobs.length) {
      parts.push(el("h3", {}, "Progreso"), el("ul", { class: "plain" }, ...c.jobs.map((j) => el("li", {},
        badge(j.status), `${j.kind}: ${j.label || ""}`,
        j.error ? el("div", { class: "bad small" }, j.error) : "",
        el("pre", { class: "small" }, (j.log || []).map((l) => `${l.t}s ${l.msg}`).join("\n"))))));
    }
    parts.push(el("h3", {}, "Registros"));
    parts.push(c.records.length ? el("ol", { class: "plain case-records" }, ...[...c.records].reverse().map((r) => {
      const p = r.payload || {};
      return el("li", {},
        el("div", {}, el("strong", {}, p.flow ? `${p.flow}` : r.kind), " ", p.status ? badge(p.status) : el("span", { class: "badge" }, r.kind),
          el("span", { class: "muted small" }, ` ${fmtTime(r.created_at)}`)),
        p.errors?.length ? el("ul", { class: "small bad" }, ...p.errors.slice(0, 10).map((x) => el("li", {}, x))) : "",
        p.tools?.length ? el("div", { class: "muted small" }, "Herramientas: "
          + p.tools.map((t) => `${t.name} ${t.version || ""}${t.status ? ` (${t.status})` : ""}`.trim()).join(", ")) : "",
        p.environment ? el("div", { class: "muted small" }, `Entorno: ${Object.values(p.environment).join(" ")}`) : "",
        ...(p.claims || []).map((x) => el("div", { class: "small" }, el("span", { class: "badge" }, CLAIM[x.status] || x.status), x.text)));
    })) : el("p", { class: "muted small" }, "Sin registros: activa el caso y analiza un objetivo."));
    parts.push(el("h3", {}, "Artefactos"));
    parts.push(c.artifacts.length ? el("table", { class: "jobs" },
      el("thead", {}, el("tr", {}, ...["Subject", "Identidad", "Tamaño", "Formato", "Versión", "Procedencia"].map((h) => el("th", { scope: "col" }, h)))),
      el("tbody", {}, ...c.artifacts.map((a) => el("tr", {},
        el("td", {}, el("code", {}, a.subject.slice(0, 48))),
        el("td", {}, a.identity, a.content_sha256 ? el("div", { class: "muted small" }, a.content_sha256.slice(0, 16)) : ""),
        el("td", {}, a.size == null ? "desconocido" : String(a.size)), el("td", {}, a.format),
        el("td", {}, a.version || "—"), el("td", { class: "small" }, a.provenance))))) : el("p", { class: "muted small" }, "Sin artefactos."));
    parts.push(el("h3", {}, `Incógnitas abiertas (${open.length})`));
    parts.push(open.length ? el("ul", { class: "plain" }, ...open.slice(0, 200).map((i) => el("li", {},
      el("span", { class: "badge warn" }, i.severity || "info"), i.question, " ",
      el("button", { type: "button", class: "small-btn", onclick: async () => {
        try {
          await api(`/api/incognitas/${i.incognita_id}/resolve`, { method: "POST", body: JSON.stringify({ status: "resolved" }) });
          await refresh(); loadCases();
        } catch (err) { setStatus(err.message, true); }
      } }, "Resolver")))) : el("p", { class: "muted small" }, "Ninguna."));
    $("#case-body").replaceChildren(...parts);
  }

  function wire() {
    $("#case-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const name = $("#case-name").value.trim();
      if (!name) { setStatus("Escribe un nombre para el caso.", true); $("#case-name").focus(); return; }
      try {
        const c = await api("/api/cases", { method: "POST", body: JSON.stringify({ name, description: $("#case-desc").value.trim() }) });
        $("#case-name").value = ""; $("#case-desc").value = "";
        await loadCases();
        setActive(c.case_id);
        setStatus(`Caso «${c.name}» creado y activo.`);
        openCase(c.case_id);
      } catch (err) { setStatus(err.message, true); }
    });
    $("#case-import").addEventListener("change", async (e) => {
      const f = e.target.files[0];
      if (!f) return;
      try {
        const pkg = JSON.parse(await f.text());
        const r = await api("/api/cases/import", { method: "POST", body: JSON.stringify({ package: pkg, name: f.name }) });
        setStatus(r.imported ? "Caso importado y validado." : "El caso ya existía idéntico: se completaron sus evidencias.");
        await loadCases();
        if (r.case_id) openCase(r.case_id);
      } catch (err) { setStatus(`No se importó: ${err.message}`, true); }
      e.target.value = "";
    });
    $("#case-use").addEventListener("click", () => { if (cs.shown) { setActive(cs.shown); refresh(); } });
    $("#case-refresh").addEventListener("click", refresh);
    $("#case-link").addEventListener("click", async () => {
      const ref = $("#case-link-ref").value.trim();
      if (!ref || !cs.shown) { setStatus("Escribe el nombre, hash o ruta de un objetivo ya analizado.", true); return; }
      try {
        await api(`/api/cases/${cs.shown}/artifacts`, { method: "POST", body: JSON.stringify({ subject: ref,
          provenance: $("#case-link-prov").value.trim() }) });
        $("#case-link-ref").value = "";
        await refresh(); loadCases();
      } catch (err) { setStatus(err.message, true); }
    });
  }

  return { loadCases, openCase, refresh, wire, active: () => cs.active,
    withCase: (body) => (cs.active ? { ...body, case_id: cs.active } : body) };
}
