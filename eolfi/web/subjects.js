// Lista, filtros y selección de objetivos de evidencia.
export function createSubjectView({ $, el, api, fmtTime, short, state, updateCompare, selectSubject }) {
  const subjectFormat = (subject) => String(subject.format || subject.kind || "unknown");
  const foldText = (value) => String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase();

  function renderSubjects() {
    const ul = $("#subjects");
    const subjects = state.subjects || [];
    if (!subjects.length) {
      ul.replaceChildren(el("li", { class: "muted" }, "Aún no hay evidencias."));
      return;
    }
    const query = foldText($("#subject-search").value.trim());
    const format = $("#subject-format").value;
    const unknowns = $("#subject-unknowns").value;
    const filtered = subjects.filter((subject) => {
      const subjectName = (subject.names || []).join(" ");
      const matchesQuery = !query || foldText(`${subjectName} ${subject.subject} ${subjectFormat(subject)}`).includes(query);
      const matchesFormat = !format || subjectFormat(subject) === format;
      const hasOpenUnknowns = Number(subject.open_incognitas || 0) > 0;
      const matchesUnknowns = !unknowns || (unknowns === "open" ? hasOpenUnknowns : !hasOpenUnknowns);
      return matchesQuery && matchesFormat && matchesUnknowns;
    });
    const filterStatus = $("#subject-filter-status");
    filterStatus.textContent = query || format || unknowns ? `Mostrando ${filtered.length} de ${subjects.length} objetivos.` : "";
    if (!filtered.length) {
      ul.replaceChildren(el("li", { class: "muted" }, "No hay objetivos que coincidan con esos filtros."));
      return;
    }
    ul.replaceChildren(...filtered.map((s) => {
      const box = el("input", { type: "checkbox", "aria-label": `Seleccionar «${s.names[0] || short(s.subject)}» para crear o comparar`,
        onclick: (e) => e.stopPropagation(),
        onchange: (e) => { e.target.checked ? state.selected.add(s.subject) : state.selected.delete(s.subject); updateCompare(); } });
      box.checked = state.selected.has(s.subject);
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

  async function loadSubjects() {
    const { subjects } = await api("/api/subjects");
    state.subjects = subjects;
    const formatSelect = $("#subject-format");
    const selectedFormat = formatSelect.value;
    const formats = [...new Set(subjects.map(subjectFormat))].sort((a, b) => a.localeCompare(b, "es"));
    formatSelect.replaceChildren(el("option", { value: "" }, "Todos los formatos"),
      ...formats.map((format) => el("option", { value: format }, format)));
    formatSelect.value = formats.includes(selectedFormat) ? selectedFormat : "";
    renderSubjects();
  }

  return { loadSubjects, renderSubjects };
}
