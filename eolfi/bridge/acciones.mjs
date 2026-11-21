// Registro encadenado de acciones (B8) desde el puente Node: misma cadena que eolfi/acciones.py.
//
// Escribe en EOLFI_ACCIONES_FILE o ~/.eolfi/acciones.jsonl con el mismo esquema, el mismo JSON canónico
// (claves ordenadas, sin espacios, sin escapar lo no ASCII) y el mismo cerrojo «.lock» creado en exclusiva, de
// modo que Python y Node añaden eventos a una sola cadena y `eolfi acciones verificar` la comprueba entera.
// Nunca guarda prompts ni respuestas: solo su SHA-256 y su longitud en bytes. Usa solo enteros (un decimal se
// serializa distinto en Python y en JavaScript y rompería el hash).
import { closeSync, mkdirSync, openSync, readSync, readFileSync, realpathSync, fstatSync, statSync, unlinkSync, writeFileSync, writeSync, fsyncSync } from 'node:fs';
import { createHash, createHmac } from 'node:crypto';
import { homedir } from 'node:os';
import { dirname, join, relative } from 'node:path';

export const SCHEMA = 'eolfi-acciones/v1';
export const CERO = '0'.repeat(64);
const MAX_TEXTO = 300;

export function activo(env = process.env) {
  return !['0', 'false', 'no'].includes(String(env.EOLFI_ACCIONES ?? '1').trim().toLowerCase());
}

export function registroFile(env = process.env) {
  return env.EOLFI_ACCIONES_FILE || join(homedir(), '.eolfi', 'acciones.jsonl');
}

export function canon(value) {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'number') {
    if (!Number.isInteger(value)) throw new TypeError('el registro de acciones solo admite enteros');
    return String(value);
  }
  if (typeof value === 'boolean' || typeof value === 'string') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canon).join(',')}]`;
  const keys = Object.keys(value).filter((k) => value[k] !== undefined).sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${canon(value[k])}`).join(',')}}`;
}

export function digest(evento) {
  const { sha256: _omit, ...body } = evento;
  return createHash('sha256').update(canon(body), 'utf8').digest('hex');
}

export function huella(text) {
  if (text === null || text === undefined) return null;
  const data = Buffer.from(String(text), 'utf8');
  return { sha256: createHash('sha256').update(data).digest('hex'), bytes: data.length };
}

export function limpio(value, depth = 0) {
  if (value === null || value === undefined) return null;
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return Number.isInteger(value) ? value : Math.round(value);
  if (typeof value === 'string') {
    const cps = Array.from(value);   // como len() de Python: puntos de código, no unidades UTF-16
    return cps.length <= MAX_TEXTO ? value : cps.slice(0, MAX_TEXTO).join('') + '…';
  }
  if (depth >= 3) return '…';
  if (Array.isArray(value)) return value.slice(0, 20).map((v) => limpio(v, depth + 1));
  if (typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).slice(0, 20).map(([k, v]) => [String(k), limpio(v, depth + 1)]));
  }
  return limpio(String(value), depth);
}

const pausa = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);

function conCerrojo(path, fn, timeoutMs = 10_000) {
  const lock = `${path}.lock`;
  mkdirSync(dirname(path), { recursive: true });
  const fin = Date.now() + timeoutMs;
  for (;;) {
    try {
      const fd = openSync(lock, 'wx');
      writeSync(fd, String(process.pid));
      closeSync(fd);
      break;
    } catch (e) {
      // En Windows, crear el cerrojo mientras otro proceso lo borra da EPERM/EACCES (borrado pendiente): también está ocupado.
      const ocupado = e.code === 'EEXIST' || (process.platform === 'win32' && (e.code === 'EPERM' || e.code === 'EACCES'));
      if (!ocupado) throw e;
      try {
        if (Date.now() - statSync(lock).mtimeMs > 30_000) { unlinkSync(lock); continue; }
      } catch { /* lo retiró otro proceso */ }
      if (Date.now() > fin) throw new Error(`registro de acciones ocupado: ${lock}`);
      pausa(50);
    }
  }
  try { return fn(); } finally { try { unlinkSync(lock); } catch { /* ya no está */ } }
}

function ultimo(path) {
  let fd;
  try { fd = openSync(path, 'r'); } catch (e) { if (e.code === 'ENOENT') return null; throw e; }
  try {
    let pos = fstatSync(fd).size;
    let block = Buffer.alloc(0);
    while (pos > 0) {
      const step = Math.min(4096, pos);
      pos -= step;
      const buf = Buffer.alloc(step);
      readSync(fd, buf, 0, step, pos);
      block = Buffer.concat([buf, block]);
      const lines = block.toString('utf8').split(/\r?\n/).filter((l) => l.trim());
      if (lines.length >= 2 || (pos === 0 && lines.length)) return JSON.parse(lines[lines.length - 1]);
    }
    return null;
  } finally { closeSync(fd); }
}

function escribir(path, evento) {
  evento.sha256 = digest(evento);
  const fd = openSync(path, 'a');
  try { writeFileSync(fd, canon(evento) + '\n'); fsyncSync(fd); } finally { closeSync(fd); }
}

function firmarEvento(path, evento, archivo) {
  const params = { hasta_seq: evento.seq, cabeza: evento.sha256 };
  const firma = { ...evento, seq: evento.seq + 1, fecha: new Date().toISOString(), operacion: 'acciones.firma',
    origen: 'auto', prev: evento.sha256, params, ok: false, resultado: null, error: null };
  try {
    if (!archivo) throw new Error('falta la clave');
    const ruta = realpathSync(archivo);
    if (!relative(dirname(realpathSync(path)), dirname(ruta))) throw new Error('la clave está junto al registro');
    const texto = readFileSync(ruta, 'utf8').trim();
    if (!/^(?:[0-9a-f]{2}[ \t\r\n\f\v]*){32,}$/i.test(texto)) throw new Error('clave hexadecimal inválida');
    const clave = Buffer.from(texto.replace(/\s/g, ''), 'hex');
    params.clave_id = createHash('sha256').update('eolfi-acciones-clave|').update(clave).digest('hex').slice(0, 16);
    firma.resultado = { hmac: createHmac('sha256', clave).update(`${SCHEMA}|${evento.seq}|${evento.sha256}`).digest('hex') };
    firma.ok = true;
  } catch (error) {
    firma.error = limpio(`firma automática no hecha: ${error.message}`);
  }
  escribir(path, firma);
}

// Añade un evento a la cadena. Devuelve el evento o null si el registro está desactivado.
export function anotar(operacion, { params = {}, resultado = null, ok = true, error = null, origen = null, env = process.env } = {}) {
  if (!activo(env)) return null;
  const path = registroFile(env);
  return conCerrojo(path, () => {
    const last = ultimo(path);
    const evento = {
      schema: SCHEMA, seq: last ? Number(last.seq) + 1 : 1, fecha: new Date().toISOString(), operacion,
      origen: origen || env.EOLFI_ACCION_ORIGEN || 'puente', pid: process.pid, ok: !!ok,
      params: limpio(params || {}), resultado: limpio(resultado), error: limpio(error),
      prev: last ? last.sha256 : CERO,
    };
    escribir(path, evento);
    if (operacion !== 'acciones.firma' && ['1', 'true', 'si', 'sí', 'yes'].includes(String(env.EOLFI_ACCIONES_FIRMA_AUTO).trim().toLowerCase())) {
      firmarEvento(path, evento, env.EOLFI_ACCIONES_CLAVE);
    }
    return evento;
  });
}

// Como anotar, pero un fallo al escribir no interrumpe al puente: la acción ya ocurrió y se avisa.
export function anotarSeguro(operacion, datos, warn = (m) => console.error(m)) {
  try { return anotar(operacion, datos); } catch (e) {
    warn(`[eolfi] AVISO: no se pudo registrar la acción ${operacion}: ${e?.message || e}`);
    return null;
  }
}
