// Mapa visual de la app (C5, 17/11/2026): dibuja en el panel lo que REA ya deja en las evidencias.
//  - grafo_llamadas: grafo de llamadas por niveles (SVG), con las funciones de otra biblioteca diferenciadas.
//  - mapa_app_android: pantallas (actividades) y componentes, con la superficie exportada sin permiso.
//  - mapa_app_apple: bundles por papel (app, extensiones, ayudantes…) y permisos de privacidad.
// Los nombres salen del objetivo: son datos y se pintan como texto (textContent), nunca como HTML ni Mermaid.
// Cada mapa lleva una alternativa en texto para lectores de pantalla.
import { el } from "./runtime.js";

const SVG = "http://www.w3.org/2000/svg";
let seq = 0;

function svg(tag, attrs = {}, ...children) {
  const n = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
  for (const c of children) n.append(c instanceof Node ? c : document.createTextNode(String(c ?? "")));
  return n;
}

const corto = (s, n = 26) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
// Clase Java («a.b.Main» → «Main») o permiso de Android; para rutas de archivo, archivo().
const ultimo = (s) => String(s ?? "").split(".").filter(Boolean).pop() || String(s ?? "");
const archivo = (s) => String(s ?? "").split(/[/\\]/).filter(Boolean).pop() || String(s ?? "");

function figura(titulo, resumen, ...partes) {
  return el("figure", { class: "mapa" }, el("figcaption", {}, el("strong", {}, titulo), " ", el("span", { class: "muted small" }, resumen)), ...partes);
}

function lista(titulo, items) {
  return el("details", { class: "mapa-lista" }, el("summary", {}, titulo),
    el("ul", { tabindex: "0", "aria-label": titulo }, ...items.map((t) => el("li", {}, t))));
}

// Enlaces del resultado; las evidencias anteriores a C5 solo traen el Mermaid (ids n0, n1… en el orden de «nodos»).
export function enlacesDe(r) {
  const nodos = r.nodos || [];
  if (Array.isArray(r.enlaces)) return r.enlaces.filter((e) => Array.isArray(e) && e.length === 2).map(([a, b]) => [String(a), String(b)]);
  const out = [];
  for (const m of String(r.mermaid || "").matchAll(/^\s*n(\d+) --> n(\d+)\s*$/gm)) {
    const a = nodos[Number(m[1])], b = nodos[Number(m[2])];
    if (a && b) out.push([String(a.direccion), String(b.direccion)]);
  }
  return out;
}

export function grafoLlamadas(r) {
  const nodos = (r.nodos || []).filter((n) => n && n.direccion != null);
  if (!nodos.length) return null;
  const W = 190, H = 32, GX = 70, GY = 12, P = 16;
  const columnas = new Map();
  for (const n of nodos) {
    const k = Number(n.nivel) || 0;
    if (!columnas.has(k)) columnas.set(k, []);
    columnas.get(k).push(n);
  }
  const niveles = [...columnas.keys()].sort((a, b) => a - b);
  const pos = new Map();
  niveles.forEach((nivel, ci) => columnas.get(nivel).forEach((n, ri) => {
    pos.set(String(n.direccion), { x: P + ci * (W + GX), y: P + 22 + ri * (H + GY), n });
  }));
  const alto = Math.max(...niveles.map((k) => columnas.get(k).length));
  const ancho = P * 2 + niveles.length * W + (niveles.length - 1) * GX;
  const total = P * 2 + 22 + alto * (H + GY);
  const flecha = `mapa-flecha-${++seq}`;
  const enlaces = enlacesDe(r).filter(([a, b]) => pos.has(a) && pos.has(b));
  const nombre = (d) => String(pos.get(d).n.nombre ?? d);
  const raiz = String(r.direccion ?? nodos[0].direccion);
  const resumen = `${nodos.length} funciones y ${enlaces.length} llamadas desde «${r.funcion ?? raiz}» (${r.hacia === "atras" ? "quién la llama" : "a quién llama"})`
    + (r.nodos_omitidos ? `; ${r.nodos_omitidos} fuera del recorte` : "");
  const g = svg("svg", { class: "mapa-svg", viewBox: `0 0 ${ancho} ${total}`, width: ancho, height: total, role: "img", "aria-label": `Grafo de llamadas: ${resumen}` },
    svg("defs", {}, svg("marker", { id: flecha, viewBox: "0 0 10 10", refX: 10, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" },
      svg("path", { d: "M0,0 L10,5 L0,10 z", class: "mapa-punta" }))),
    ...niveles.map((nivel, ci) => svg("text", { x: P + ci * (W + GX), y: P + 8, class: "mapa-nivel" }, nivel === 0 ? "función" : `nivel ${nivel}`)));
  for (const [a, b] of enlaces) {
    const pa = pos.get(a), pb = pos.get(b);
    const derecha = pb.x >= pa.x;
    const x1 = derecha ? pa.x + W : pa.x, x2 = pb.x === pa.x ? pb.x + W : (derecha ? pb.x : pb.x + W);
    const y1 = pa.y + H / 2, y2 = pb.y + H / 2;
    const c = pb.x === pa.x ? 40 : Math.max(24, Math.abs(x2 - x1) / 2);
    const d = pb.x === pa.x ? `M${x1},${y1} C${x1 + c},${y1} ${x2 + c},${y2} ${x2},${y2}`
      : `M${x1},${y1} C${x1 + (derecha ? c : -c)},${y1} ${x2 - (derecha ? c : -c)},${y2} ${x2},${y2}`;
    g.append(svg("path", { d, class: "mapa-arista", "marker-end": `url(#${flecha})` }, svg("title", {}, `${nombre(a)} → ${nombre(b)}`)));
  }
  for (const [d, { x, y, n }] of pos) {
    const clase = d === raiz ? "raiz" : n.externa ? "externa" : "interna";
    g.append(svg("g", { class: `mapa-nodo ${clase}` },
      svg("title", {}, `${n.nombre ?? d} · ${d}${n.externa ? " · de otra biblioteca" : ""}`),
      svg("rect", { x, y, width: W, height: H, rx: 6 }),
      svg("text", { x: x + 10, y: y + H / 2 + 4 }, corto(String(n.nombre ?? d)))));
  }
  const leyenda = el("p", { class: "mapa-leyenda small" },
    el("span", { class: "mapa-marca raiz" }), "función analizada ",
    el("span", { class: "mapa-marca interna" }), "del programa ",
    el("span", { class: "mapa-marca externa" }), "de otra biblioteca (importación)");
  const texto = enlaces.map(([a, b]) => `${nombre(a)} → ${nombre(b)}`);
  // Zona con desplazamiento: enfocable con el teclado y con nombre (axe: scrollable-region-focusable).
  return figura("Mapa de llamadas", resumen, leyenda,
    el("div", { class: "mapa-scroll", tabindex: "0", role: "group", "aria-label": "Grafo de llamadas (desplazable)" }, g),
    lista(`Llamadas como lista (${texto.length})`, texto.length ? texto : ["Sin llamadas resueltas en el recorte."]));
}

const TIPOS_ANDROID = [
  ["activity", "Pantallas (actividades)"], ["activity-alias", "Alias de pantallas"], ["service", "Servicios"],
  ["receiver", "Receptores"], ["provider", "Proveedores de datos"],
];

export function mapaAndroid(r) {
  const comps = r.componentes || {};
  if (!Object.keys(comps).length) return null;
  const abiertos = r.exportados_sin_permiso || [];
  const lanzadores = (r.lanzadores || []).map(String);
  const conocidos = new Set(TIPOS_ANDROID.map(([k]) => k));
  const tipos = [...TIPOS_ANDROID.filter(([k]) => comps[k]), ...Object.keys(comps).filter((k) => !conocidos.has(k)).map((k) => [k, k])];
  const tarjetas = tipos.map(([k, titulo]) => {
    const c = comps[k];
    // Un componente, una línea: la pantalla de inicio puede ser también una exportada sin permiso.
    const marcas = new Map();
    const marcar = (nombre, badge) => { const n = String(nombre); if (!marcas.has(n)) marcas.set(n, []); marcas.get(n).push(badge); };
    if (k === "activity") for (const l of lanzadores) marcar(l, el("span", { class: "badge ok" }, "inicio"));
    for (const a of abiertos.filter((x) => x.tipo === k)) marcar(a.nombre, el("span", { class: "badge bad" }, "exportado sin permiso"));
    const items = [...marcas].map(([n, badges]) => el("li", { title: n }, ultimo(n), ...badges.flatMap((b) => [" ", b])));
    return el("section", { class: `mapa-tarjeta${c.exportados_sin_permiso ? " abierta" : ""}`, "aria-label": titulo },
      el("h4", {}, titulo),
      el("p", { class: "small muted" }, `${c.total} en total · ${c.exportados} exportados · ${c.exportados_sin_permiso} sin permiso`),
      items.length ? el("ul", {}, ...items) : "");
  });
  const p = r.paquete || {};
  const resumen = `${p.nombre || "app"}${p.version ? ` ${p.version}` : ""} · SDK ${p.sdk_minimo ?? "?"}–${p.sdk_objetivo ?? "?"}`;
  const peligrosos = r.permisos_peligrosos || [];
  return figura("Mapa de la app", resumen,
    el("div", { class: "mapa-grid" }, ...tarjetas),
    peligrosos.length ? el("p", { class: "small" }, el("strong", {}, "Permisos peligrosos: "), peligrosos.map(ultimo).join(", ")) : "",
    r.exportados_sin_permiso_omitidos ? el("p", { class: "small muted" }, `${r.exportados_sin_permiso_omitidos} componentes abiertos más fuera del límite.`) : "");
}

export function mapaApple(r) {
  const bundles = r.bundles || [];
  if (!bundles.length) return null;
  const papeles = new Map();
  for (const b of bundles) {
    const k = String(b.papel || "otro");
    if (!papeles.has(k)) papeles.set(k, []);
    papeles.get(k).push(b);
  }
  const tarjetas = [...papeles].map(([papel, lista]) => el("section", { class: "mapa-tarjeta", "aria-label": papel },
    el("h4", {}, papel),
    el("ul", {}, ...lista.map((b) => el("li", { title: String(b.ruta) }, archivo(b.ruta), " ",
      el("span", { class: `badge ${b.firmado ? "ok" : "warn"}` }, b.firmado ? "firmado" : "sin firma"))))));
  const perms = r.permisos_privacidad || [];
  return figura("Mapa de la app", `${bundles.length} de ${r.bundles_total ?? bundles.length} bundles · ${(r.plataformas || []).join(", ") || "plataforma desconocida"}`,
    el("div", { class: "mapa-grid" }, ...tarjetas),
    perms.length ? el("p", { class: "small" }, el("strong", {}, "Permisos de privacidad declarados: "), perms.join(", ")) : "");
}

const MAPAS = { grafo_llamadas: grafoLlamadas, mapa_app_android: mapaAndroid, mapa_app_apple: mapaApple };

// Un mapa para la evidencia, o null si no es de REA o no trae datos que dibujar.
export function mapaDeEvidencia(e) {
  const fn = e && e.provider === "rea" && MAPAS[e.operation];
  if (!fn || !e.result || typeof e.result !== "object" || e.result.recortado) return null;
  try { return fn(e.result); } catch (err) { console.warn("mapa no dibujado", err); return null; }
}
