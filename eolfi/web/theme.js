// Se carga en <head>, antes de pintar: sin destello del tema contrario (Fase C, B1).
try {
  const t = localStorage.getItem("eolfi.theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
} catch { /* almacenamiento bloqueado: tema del sistema */ }
