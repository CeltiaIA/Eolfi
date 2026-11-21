// Voz en el panel (PLAN_DEFINITIVO.md, bloque A, 16/11/2026): dictado, lectura en voz alta y modo conversación.
// El audio se graba aquí, se convierte a WAV de 16 kHz y se envía SOLO al servidor local de Eolfi
// (/api/voz/transcribir). La lectura usa Piper (voz neuronal local, vía /api/voz/hablar) si está instalado y, si no,
// las voces del sistema del navegador; nada sale del equipo.
import { $, api } from "./runtime.js";

const HZ = 16000;
const MAX_MS = 110000;            // el servidor admite 120 s
const SILENCIO_MS = 1600;         // silencio que cierra un turno en modo conversación
const UMBRAL = 0.012;             // RMS a partir del cual cuenta como voz
const PREF_KEY = "eolfi.voz";
// Órdenes por voz: solo cuando son TODO lo dictado.
const ORDENES = [
  [/^(env[ií]a(lo)?|enviar|manda(lo)?)$/, "enviar"],
  [/^(borra(lo)?|borrar|limpia)( todo)?$/, "borrar"],
  [/^(para|parar|detente|silencio|c[aá]llate)$/, "parar"],
  [/^nueva conversaci[oó]n$/, "nueva"],
  [/^(lee|leer|repite) (la )?[uú]ltima( respuesta)?$/, "leer"],
];

const voz = { estado: null, grabando: null, ocupado: false, conversacion: false, prefs: { leer: false }, hooks: null,
  destinos: [], destino: null };
// Otros cuadros del panel donde también se puede dictar (A7). Ahí solo se escribe: sin órdenes ni conversación.
const OTROS = ["#proj-desc", "#create-ai", "#case-desc", "#chat-input", "#compare-input"];

function prefs() {
  try { Object.assign(voz.prefs, JSON.parse(localStorage.getItem(PREF_KEY) || "{}")); } catch { /* sin almacenamiento */ }
}

function aviso(msg, bad = false) {
  const n = voz.destino?.estado || $("#voz-estado");
  if (!n) return;
  n.textContent = msg;
  n.classList.toggle("bad", bad);
}

export function ordenDe(texto) {
  const t = String(texto).trim().toLowerCase().replace(/[.,;:!¡?¿]/g, "").replace(/\s+/g, " ");
  for (const [re, nombre] of ORDENES) if (re.test(t)) return nombre;
  return null;
}

// PCM de 16 bits, mono, 16 kHz, a partir de las muestras en coma flotante.
export function wavDe(muestras, hz = HZ) {
  const buf = new ArrayBuffer(44 + muestras.length * 2);
  const v = new DataView(buf);
  const txt = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  txt(0, "RIFF"); v.setUint32(4, 36 + muestras.length * 2, true); txt(8, "WAVE"); txt(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, hz, true);
  v.setUint32(28, hz * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); txt(36, "data");
  v.setUint32(40, muestras.length * 2, true);
  for (let i = 0; i < muestras.length; i++) {
    const s = Math.max(-1, Math.min(1, muestras[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

async function aWav(blob) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  const ctx = new Ctx();
  try {
    const audio = await ctx.decodeAudioData(await blob.arrayBuffer());
    const off = new OfflineAudioContext(1, Math.max(1, Math.ceil(audio.duration * HZ)), HZ);
    const src = off.createBufferSource();
    src.buffer = audio;
    src.connect(off.destination);
    src.start();
    return wavDe((await off.startRendering()).getChannelData(0));
  } finally { ctx.close(); }
}

export async function transcribir(wav) {
  const r = await fetch("/api/voz/transcribir", { method: "POST", headers: { "X-Eolfi": "1", "Content-Type": "audio/wav" }, body: wav });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

function pintar() {
  if (!$("#voz-mic")) return;
  for (const d of voz.destinos) {
    const g = !!voz.grabando && voz.destino === d;
    d.boton.setAttribute("aria-pressed", String(g));
    d.boton.textContent = g ? "Parar dictado" : "Dictar";
    d.boton.classList.toggle("grabando", g);
    d.boton.disabled = (voz.ocupado || !!voz.grabando) && !g;
  }
  $("#voz-conversar").setAttribute("aria-pressed", String(voz.conversacion));
  $("#voz-conversar").textContent = voz.conversacion ? "Salir de conversación" : "Conversación";
}

async function empezar(destino = voz.destinos[0]) {
  if (voz.grabando || voz.ocupado) return;
  voz.destino = destino;
  if (!destino.chat) voz.conversacion = false;
  callar();
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  } catch (err) {
    voz.conversacion = false;
    pintar();
    aviso(`No se pudo usar el micrófono: ${err.name === "NotAllowedError" ? "permiso denegado en el navegador" : err.message}`, true);
    return;
  }
  const rec = new MediaRecorder(stream);
  const trozos = [];
  const g = { rec, stream, trozos, timers: [], ctx: null };
  rec.addEventListener("dataavailable", (e) => { if (e.data.size) trozos.push(e.data); });
  rec.addEventListener("stop", () => terminar(g));
  g.timers.push(setTimeout(() => parar(), MAX_MS));
  if (voz.conversacion) vigilarSilencio(g);
  voz.grabando = g;
  rec.start();
  pintar();
  // 19/11/2026: se dice de qué micrófono se graba (el titular no sabía si Eolfi detectaba el de la torre).
  const mic = stream.getAudioTracks()[0]?.label;
  const con = mic ? ` Micrófono: ${mic}.` : "";
  aviso((voz.conversacion ? "Te escucho… (Esc para salir)" : "Grabando… pulsa otra vez para terminar.") + con);
}

// En modo conversación el turno se cierra solo tras hablar y callar SILENCIO_MS.
function vigilarSilencio(g) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  g.ctx = new Ctx();
  const an = g.ctx.createAnalyser();
  an.fftSize = 1024;
  g.ctx.createMediaStreamSource(g.stream).connect(an);
  const datos = new Float32Array(an.fftSize);
  let hablo = false;
  let ultimo = performance.now();
  g.timers.push(setInterval(() => {
    an.getFloatTimeDomainData(datos);
    let suma = 0;
    for (const x of datos) suma += x * x;
    const ahora = performance.now();
    if (Math.sqrt(suma / datos.length) > UMBRAL) { hablo = true; ultimo = ahora; }
    else if (hablo && ahora - ultimo > SILENCIO_MS) parar();
    else if (!hablo && ahora - ultimo > 15000) { voz.conversacion = false; parar(); }   // nadie habla: se sale
  }, 100));
}

function parar() {
  const g = voz.grabando;
  if (g && g.rec.state !== "inactive") g.rec.stop();
}

async function terminar(g) {
  for (const t of g.timers) { clearTimeout(t); clearInterval(t); }
  for (const t of g.stream.getTracks()) t.stop();
  if (g.ctx) g.ctx.close();
  voz.grabando = null;
  voz.ocupado = true;
  pintar();
  aviso("Transcribiendo en este equipo…");
  try {
    const r = await transcribir(await aWav(new Blob(g.trozos, { type: g.rec.mimeType })));
    recibir(r);
  } catch (err) {
    aviso(`No se pudo transcribir: ${err.message}`, true);
    voz.conversacion = false;
  } finally {
    voz.ocupado = false;
    pintar();
  }
}

function recibir(r) {
  const texto = (r.texto || "").trim();
  const input = voz.destino.input;
  const chat = voz.destino.chat;
  if (!texto) {
    aviso("No se entendió nada. Prueba otra vez, más cerca del micrófono.", true);
    if (voz.conversacion) empezar();
    return;
  }
  const orden = chat ? ordenDe(texto) : null;
  if (orden) return ejecutar(orden);
  input.value = (input.value.trim() ? `${input.value.trim()} ` : "") + texto;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  const conf = typeof r.confianza === "number" ? ` · confianza ${Math.round(r.confianza * 100)} %` : "";
  aviso(`Dictado con el motor local «${r.motor}»${conf}. Revisa el texto antes de enviar.`);
  if (chat && voz.conversacion) voz.hooks.enviar(input.value.trim());
  else input.focus();
}

function ejecutar(orden) {
  const input = $("#eolas-chat-input");
  aviso(`Orden por voz: ${orden}.`);
  if (orden === "enviar") voz.hooks.enviar(input.value.trim());
  else if (orden === "borrar") { input.value = ""; if (voz.conversacion) empezar(); }
  else if (orden === "parar") { voz.conversacion = false; callar(); pintar(); }
  else if (orden === "nueva") voz.hooks.nueva();
  else if (orden === "leer") decir(voz.hooks.ultima());
}

// ── Texto a voz: voces del sistema, sin conexión ───────────────────────────────────────────────────────────────
function limpio(texto) {
  return String(texto).replace(/```[\s\S]*?```/g, " (bloque de código) ").replace(/[*_`#>]/g, "").replace(/\s+/g, " ").trim();
}

// 18/11/2026: con Piper (voz neuronal local) el servidor genera el audio y prepara el texto para el oído. Se lee por
// trozos de pocas frases y el siguiente se pide mientras suena el actual: la primera frase empieza en ~1 s aunque la
// respuesta sea larga. Si Piper falla, se sigue con las voces del navegador.
const lectura = { turno: 0, audio: null };

export function trozos(texto, max = 280) {
  const sinCodigo = String(texto).replace(/```[\s\S]*?```/g, "\n(bloque de código)\n");
  const frases = sinCodigo.split(/(?<=[.!?…:])\s+|\n+/).map((f) => f.trim()).filter(Boolean);
  const out = [];
  for (const f of frases) {
    if (out.length && (out[out.length - 1] + " " + f).length <= max) out[out.length - 1] += "\n" + f;
    else out.push(f.slice(0, 3500));
  }
  return out;
}

async function audioDe(texto) {
  const r = await fetch("/api/voz/hablar", { method: "POST", headers: { "X-Eolfi": "1", "Content-Type": "application/json" },
    body: JSON.stringify({ texto }) });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `HTTP ${r.status}`);
  return URL.createObjectURL(await r.blob());
}

async function decirConPiper(texto, alAcabar) {
  const turno = ++lectura.turno;
  const partes = trozos(texto);
  let siguiente = partes.length ? audioDe(partes[0]) : null;
  for (let i = 0; i < partes.length; i++) {
    let url;
    try { url = await siguiente; } catch (err) {
      if (turno !== lectura.turno) return;
      aviso(`Piper no pudo leer (${err.message}); sigo con la voz del navegador.`, true);
      decirNavegador(partes.slice(i).join(" "), alAcabar);
      return;
    }
    siguiente = i + 1 < partes.length ? audioDe(partes[i + 1]) : null;
    if (turno !== lectura.turno) { URL.revokeObjectURL(url); return; }
    await new Promise((fin) => {
      const a = new Audio(url);
      lectura.audio = a;
      a.addEventListener("ended", fin);
      a.addEventListener("error", fin);
      a.play().catch(fin);
    });
    URL.revokeObjectURL(url);
    if (turno !== lectura.turno) return;
  }
  lectura.audio = null;
  alAcabar();
}

export function decir(texto, alAcabar = () => {}) {
  if (!String(texto || "").trim()) { alAcabar(); return; }
  callar();
  if (voz.estado?.lectura_activa === "piper") { decirConPiper(texto, alAcabar); return; }
  decirNavegador(texto, alAcabar);
}

function decirNavegador(texto, alAcabar) {
  const t = limpio(texto || "");
  if (!t || !("speechSynthesis" in window)) { alAcabar(); return; }
  const u = new SpeechSynthesisUtterance(t.slice(0, 4000));
  const idioma = voz.estado?.idioma || "es-ES";
  u.lang = idioma;
  // Solo voces locales: una voz en línea enviaría el texto fuera del equipo.
  const local = speechSynthesis.getVoices().find((v) => v.localService && v.lang === idioma)
    || speechSynthesis.getVoices().find((v) => v.localService && v.lang.startsWith(idioma.slice(0, 2)));
  if (local) u.voice = local;
  u.addEventListener("end", alAcabar);
  u.addEventListener("error", alAcabar);
  speechSynthesis.speak(u);
}

export function callar() {
  lectura.turno += 1;
  if (lectura.audio) { lectura.audio.pause(); lectura.audio = null; }
  if ("speechSynthesis" in window) speechSynthesis.cancel();
}

const hablando = () => !!lectura.audio || !!globalThis.speechSynthesis?.speaking;
const puedeLeer = () => voz.estado?.lectura_activa === "piper" || "speechSynthesis" in window;

// Voz de lectura: Piper (cada voz y hablante) con su ajuste. Se guarda en ~/.eolfi/voz.json (solo en este equipo).
function pintarVoces() {
  const sel = $("#voz-voz"), aj = $("#voz-ajuste");
  const p = voz.estado?.piper;
  const caja = sel?.closest(".voz-lectura");
  if (!sel || !caja) return;
  caja.hidden = !p?.disponible;
  if (!p?.disponible) return;
  sel.replaceChildren(...p.voces.flatMap((v) => Array.from({ length: v.hablantes }, (_, h) => {
    const o = document.createElement("option");
    o.value = JSON.stringify({ modelo: v.modelo, hablante: h });
    o.textContent = v.nombre.replace(/^[a-z]{2}_[A-Z]{2}-/, "").replace(/-(medium|low|high|x_low)$/, "")
      + (v.hablantes > 1 ? ` · ${h === 0 ? "hombre" : h === 1 ? "mujer" : `voz ${h + 1}`}` : "");
    o.selected = v.modelo === p.modelo && h === p.hablante;
    return o;
  })));
  aj.replaceChildren(...(voz.estado.ajustes || []).map((a) => {
    const o = document.createElement("option");
    o.value = a; o.textContent = a; o.selected = a === p.ajuste;
    return o;
  }));
}

async function guardarVoz() {
  const elegido = JSON.parse($("#voz-voz").value);
  try {
    voz.estado = await api("/api/voz/config", { method: "POST",
      body: JSON.stringify({ piper: { ...elegido, ajuste: $("#voz-ajuste").value } }) });
    pintarVoces();
    decir("Hola, así sueno con esta voz.");
  } catch (err) { aviso(`No se pudo cambiar la voz: ${err.message}`, true); }
}

// El chat avisa de cada respuesta nueva: se lee si está activado o en modo conversación, y se vuelve a escuchar.
function alResponder(e) {
  const texto = e.detail?.text || "";
  if (voz.conversacion) decir(texto, () => { if (voz.conversacion) empezar(); });
  else if (voz.prefs.leer) decir(texto);
}

// Botón «Dictar» y línea de estado junto a un cuadro de texto del panel.
function anadirDictado(sel) {
  const input = $(sel);
  if (!input) return;
  const nombre = input.getAttribute("aria-label") || input.closest("label")?.querySelector("span")?.textContent || "este cuadro";
  const boton = document.createElement("button");
  boton.type = "button";
  boton.className = "small-btn voz-dictar";
  boton.setAttribute("aria-pressed", "false");
  boton.setAttribute("aria-label", `Dictar en «${nombre.trim()}»`);
  boton.title = "Dictar con el micrófono (Alt+M con el cursor en el cuadro). El audio se transcribe en este equipo.";
  boton.textContent = "Dictar";
  const estado = document.createElement("span");
  estado.className = "muted small voz-nota";
  estado.setAttribute("role", "status");
  const caja = document.createElement("span");
  caja.className = "voz-junto";
  caja.append(boton, estado);
  input.insertAdjacentElement("afterend", caja);
  voz.destinos.push({ input, boton, estado, chat: false });
}

export async function initVoz(hooks) {
  if (!$("#voz-mic")) return;
  voz.hooks = hooks;
  prefs();
  const puede = !!(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
  try { voz.estado = await api("/api/voz/estado"); } catch { voz.estado = null; }
  const stt = puede && voz.estado?.voz_a_texto;
  $("#voz-mic").hidden = !stt;
  $("#voz-conversar").hidden = !stt || !puedeLeer();
  $("#voz-leer").checked = !!voz.prefs.leer;
  $("#voz-leer").closest("label").hidden = !puedeLeer();
  pintarVoces();
  $("#voz-voz")?.addEventListener("change", guardarVoz);
  $("#voz-ajuste")?.addEventListener("change", guardarVoz);
  voz.destinos = [{ input: $("#eolas-chat-input"), boton: $("#voz-mic"), estado: $("#voz-estado"), chat: true }];
  voz.destino = voz.destinos[0];
  if (stt) for (const sel of OTROS) anadirDictado(sel);
  if (!stt) {
    // En el móvil por http://IP el navegador oculta el micrófono (no es un contexto seguro): se dice cómo arreglarlo.
    if (!window.isSecureContext) aviso("El micrófono necesita HTTPS: arranca Eolfi con «serve --cert» o ábrelo en este equipo (localhost).");
    else aviso(puede ? "Voz a texto no disponible: no hay motor local (mira «eolfi voz estado»)." : "Este navegador no permite grabar audio.");
  }
  else aviso(`Voz local lista (motor «${voz.estado.motor_activo}», ${voz.estado.idioma}). Alt+M para dictar.`);
  for (const d of voz.destinos) d.boton.addEventListener("click", () => (voz.grabando ? parar() : empezar(d)));
  $("#voz-conversar").addEventListener("click", () => {
    voz.conversacion = !voz.conversacion;
    if (voz.conversacion) empezar(); else { parar(); callar(); aviso("Conversación terminada."); }
    pintar();
  });
  $("#voz-leer").addEventListener("change", (e) => {
    voz.prefs.leer = e.currentTarget.checked;
    try { localStorage.setItem(PREF_KEY, JSON.stringify(voz.prefs)); } catch { /* sin almacenamiento */ }
    if (!voz.prefs.leer) callar();
  });
  window.addEventListener("eolfi:chat-reply", alResponder);
  window.addEventListener("keydown", (e) => {
    if (e.altKey && e.key.toLowerCase() === "m" && stt) {
      // Alt+M dicta en el cuadro que tiene el foco; si no es ninguno de los conocidos, en el chat.
      e.preventDefault();
      const d = voz.destinos.find((x) => x.input === document.activeElement) || voz.destinos[0];
      if (voz.grabando) parar(); else empezar(d);
    }
    else if (e.key === "Escape" && (voz.conversacion || voz.grabando || hablando())) {
      voz.conversacion = false; parar(); callar(); pintar(); aviso("Voz detenida.");
    }
  });
  pintar();
}
