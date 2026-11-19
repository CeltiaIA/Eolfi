"""Registro encadenado de acciones que cambian estado (B8, PLAN_DEFINITIVO.md).

Cada acción ejecutada (no las vistas previas) añade un evento a ``~/.eolfi/acciones.jsonl`` con el SHA-256 del
evento anterior. Editar, borrar o reordenar una línea rompe la cadena y ``verificar()`` dice dónde.

Qué cubre: las funciones decoradas con ``@registrada`` (adoptar, quitar o recomendar perfil con aplicación,
arrancar, cambiar y parar el motor, retirar, desinstalar o restaurar perfiles, ejecutar una reconstrucción o un
smoke). Las llame la CLI, el panel o un agente, el evento se escribe en el mismo sitio. El puente Node
(``eolfi/bridge/acciones.mjs``) escribe en la misma cadena, con el mismo JSON canónico y el mismo cerrojo, cada
envío a un chat web (aprobado, denegado, caducado o cancelado), comparativa, permiso temporal, revocación y reinicio.

Las acciones del RSI (``eolfi/rsi.py``: proponer, evaluar, decidir, aplicar, revertir, ajustar umbrales) se reflejan
aquí como ``rsi.<tipo>`` con el número y el SHA-256 de su evento en la cadena propia del RSI, que sigue existiendo
porque de ella se reconstruye el estado de las propuestas. ``verificar_rsi`` comprueba las dos cadenas y que cada
reflejo coincide: reescribir el registro del RSI ya no pasa desapercibido.

Firma: ``firmar`` añade un evento ``acciones.firma`` con el HMAC-SHA256 de la cabeza de la cadena, hecho con una clave
de 32 bytes (``generar_clave``) que el titular guarda fuera del alcance de quien escribe el registro (otra unidad,
un medio extraíble) y solo aporta al firmar o verificar. ``verificar_firmas`` recalcula cada HMAC: sin la clave no se
puede reescribir ni recortar lo firmado sin que se note.

Firma automática (18/11/2026): con ``EOLFI_ACCIONES_FIRMA_AUTO=1`` y la clave en ``EOLFI_ACCIONES_CLAVE``, cada evento
que escribe Python va seguido, dentro del mismo cerrojo, de su ``acciones.firma`` (origen «auto»): no queda cola sin
firmar entre una firma a mano y la siguiente. Si la clave falta, no se lee o está junto al registro, la acción no se
bloquea: se escribe un ``acciones.firma`` fallido con el motivo, que ``verificar_firmas`` cuenta aparte.

Límites:
- Lo posterior a la última firma o ancla solo tiene la protección de la cadena: quien escribe el archivo puede
  reescribir esa cola, o quitar los últimos eventos junto con la última firma (``verificar_firmas`` informa de
  cuántos eventos quedan sin firmar; para saber si faltan firmas hay que conservar su número fuera). La firma
  automática acorta esa cola a cero en los eventos de Python, pero no impide recortar el final del registro.
- El puente Node usa el mismo formato y cerrojo para firmar automáticamente cuando tiene configurada la clave.
- Con firma automática la clave tiene que estar disponible para el proceso que escribe el registro: protege contra
  quien puede editar el archivo pero no leer la clave (otra cuenta, otra unidad con permisos), no contra el propio
  proceso.
- HMAC es simétrico: quien tenga la clave puede firmar. Si la clave queda en el mismo equipo y cuenta que el
  registro, la firma no protege más que la cadena.
- ``anclar`` copia la cabeza a un archivo externo y ``verificar_anclas`` detecta una reescritura anterior a la última
  ancla, solo si ese archivo se guarda fuera del alcance de quien escribe el registro.
- Si escribir el evento falla, la acción ya hecha no se deshace: se avisa por stderr y ``verificar()`` no lo verá.
- Solo se guardan los campos declarados para cada operación (nombres, hashes, estados), nunca prompts ni código.
"""
from __future__ import annotations

import functools
import hashlib
import hmac
import inspect
import json
import os
import secrets
import sys
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "eolfi-acciones/v1"
CERO = "0" * 64
_MAX_TEXTO = 300


def activo() -> bool:
    return os.environ.get("EOLFI_ACCIONES", "1").strip().lower() not in ("0", "false", "no")


def registro_file() -> Path:
    return Path(os.environ.get("EOLFI_ACCIONES_FILE") or Path.home() / ".eolfi" / "acciones.jsonl")


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(evento: dict[str, Any]) -> str:
    body = {k: v for k, v in evento.items() if k != "sha256"}
    return hashlib.sha256(_canon(body).encode("utf-8")).hexdigest()


def _limpio(value: Any, depth: int = 0) -> Any:
    """Valor acotado y serializable: textos cortados, listas/dicts pequeños, rutas como texto."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (str, Path)):
        text = str(value)
        return text if len(text) <= _MAX_TEXTO else text[:_MAX_TEXTO] + "…"
    if depth >= 3:
        return "…"
    if isinstance(value, dict):
        return {str(k): _limpio(v, depth + 1) for k, v in list(value.items())[:20]}
    if isinstance(value, (list, tuple, set)):
        return [_limpio(v, depth + 1) for v in list(value)[:20]]
    return _limpio(repr(value), depth)


def _ultimo(path: Path) -> dict[str, Any] | None:
    """Última línea no vacía sin leer todo el archivo."""
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            block = b""
            pos = size
            while pos > 0:
                step = min(4096, pos)
                pos -= step
                fh.seek(pos)
                block = fh.read(step) + block
                lines = [ln for ln in block.splitlines() if ln.strip()]
                if len(lines) >= 2 or (pos == 0 and lines):
                    return json.loads(lines[-1].decode("utf-8"))
    except FileNotFoundError:
        return None
    return None


class _Cerrojo:
    """Cerrojo entre procesos con un archivo creado en exclusiva; uno abandonado más de 30 s se retira."""

    def __init__(self, path: Path, timeout: float = 10.0):
        self.path = path.with_name(path.name + ".lock")
        self.timeout = timeout

    def __enter__(self) -> _Cerrojo:  # noqa: PYI034
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fin = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except (FileExistsError, PermissionError) as exc:
                # En Windows, crear el archivo mientras otro proceso lo está borrando da «acceso denegado»
                # (ERROR_DELETE_PENDING), no «ya existe»: también es un cerrojo ocupado. En otros sistemas sí es un error.
                if isinstance(exc, PermissionError) and os.name != "nt":
                    raise
                try:
                    if time.time() - self.path.stat().st_mtime > 30:
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() > fin:
                    raise TimeoutError(f"registro de acciones ocupado: {self.path}")
                time.sleep(0.05)

    def __exit__(self, *exc: object) -> None:
        self.path.unlink(missing_ok=True)


def firma_auto() -> bool:
    return os.environ.get("EOLFI_ACCIONES_FIRMA_AUTO", "").strip().lower() in ("1", "true", "si", "sí", "yes")


def _escribir(path: Path, last: dict[str, Any] | None, operacion: str, *, params: dict[str, Any] | None,
              resultado: Any, ok: bool, error: str | None, origen: str | None) -> dict[str, Any]:
    evento = {"schema": SCHEMA, "seq": (int(last["seq"]) + 1) if last else 1,
              "fecha": datetime.now(timezone.utc).isoformat(), "operacion": operacion,
              "origen": origen or os.environ.get("EOLFI_ACCION_ORIGEN") or "local",
              "pid": os.getpid(), "ok": bool(ok), "params": _limpio(params or {}),
              "resultado": _limpio(resultado), "error": _limpio(error),
              "prev": last["sha256"] if last else CERO}
    evento["sha256"] = _digest(evento)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(_canon(evento) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return evento


def _firma_auto(path: Path, evento: dict[str, Any]) -> dict[str, Any]:
    """Firma ``evento`` (la cabeza recién escrita) con la clave de EOLFI_ACCIONES_CLAVE; nunca lanza."""
    seq, cabeza = evento["seq"], evento["sha256"]
    try:
        archivo = os.environ.get("EOLFI_ACCIONES_CLAVE")
        if archivo and Path(archivo).resolve().parent == path.resolve().parent:
            raise ValueError("la clave está junto al registro: no se firma con ella")
        clave = _leer_clave(archivo)
    except (OSError, ValueError) as exc:
        return _escribir(path, evento, "acciones.firma", params={"hasta_seq": seq, "cabeza": cabeza},
                         resultado=None, ok=False, error=f"firma automática no hecha: {exc}", origen="auto")
    return _escribir(path, evento, "acciones.firma",
                     params={"hasta_seq": seq, "cabeza": cabeza, "clave_id": _clave_id(clave)},
                     resultado={"hmac": _hmac(clave, seq, cabeza)}, ok=True, error=None, origen="auto")


def anotar(operacion: str, *, params: dict[str, Any] | None = None, resultado: Any = None,
           ok: bool = True, error: str | None = None, origen: str | None = None) -> dict[str, Any] | None:
    """Añade un evento a la cadena. Devuelve el evento, o None si el registro está desactivado. Con firma
    automática, el evento va seguido de su ``acciones.firma`` dentro del mismo cerrojo."""
    if not activo():
        return None
    path = registro_file()
    with _Cerrojo(path):
        evento = _escribir(path, _ultimo(path), operacion, params=params, resultado=resultado, ok=ok, error=error,
                           origen=origen)
        if firma_auto() and operacion != "acciones.firma":
            _firma_auto(path, evento)
    return evento


def _lineas(texto: str) -> list[str]:
    """Separa solo por saltos de línea: ``str.splitlines`` también corta en U+2028, U+0085 y otros, que JSON deja
    sin escapar dentro de un texto y romperían un evento legítimo en dos."""
    return [ln.rstrip("\r") for ln in texto.split("\n")]


def eventos(path: Path | None = None) -> list[dict[str, Any]]:
    try:
        lines = _lineas((path or registro_file()).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in lines if line.strip()]


def verificar(path: Path | None = None) -> dict[str, Any]:
    """Recalcula la cadena completa. Una línea ilegible también cuenta como rotura."""
    path = path or registro_file()
    try:
        lines = [ln for ln in _lineas(path.read_text(encoding="utf-8")) if ln.strip()]
    except FileNotFoundError:
        return {"ok": True, "eventos": 0, "archivo": str(path), "nota": "sin registro todavía"}
    prev = CERO
    for i, line in enumerate(lines, 1):
        try:
            e = json.loads(line)
        except ValueError:
            return {"ok": False, "roto_en": i, "motivo": "línea ilegible", "eventos": i - 1, "archivo": str(path)}
        if e.get("schema") != SCHEMA or e.get("seq") != i or e.get("prev") != prev or _digest(e) != e.get("sha256"):
            return {"ok": False, "roto_en": i, "motivo": "cadena rota", "eventos": i - 1, "archivo": str(path)}
        prev = e["sha256"]
    return {"ok": True, "eventos": len(lines), "ultimo": prev, "archivo": str(path)}


def huella(value: Any) -> dict[str, Any] | None:
    """SHA-256 y longitud de un texto que no se guarda (encargos, prompts)."""
    if value is None:
        return None
    data = str(value).encode("utf-8")
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def registrada(operacion: str, *, campos: Iterable[str] = (), huellas: Iterable[str] = (),
               resultado: Iterable[str] | Callable[[Any], Any] = (),
               si: Callable[[dict[str, Any]], bool] | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorador: registra la llamada si ``si(argumentos)`` es verdadero (por defecto, siempre).

    ``campos`` elige qué argumentos se guardan tal cual y ``huellas`` cuáles se guardan solo como SHA-256 y
    longitud. ``resultado`` son las claves de un resultado dict o una función que lo resume; ``ok`` se deduce del
    resultado y, si la función devuelve un dict con ``ok``, de ese resumen. Los fallos se registran con
    ``ok: false`` y se vuelven a lanzar sin cambiarlos."""
    campos, huellas = tuple(campos), tuple(huellas)
    resumir = resultado if callable(resultado) else None
    claves = () if resumir else tuple(resultado)  # type: ignore[arg-type]

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        firma = inspect.signature(fn)

        @functools.wraps(fn)
        def envoltura(*args: Any, **kwargs: Any) -> Any:
            try:
                bound = firma.bind(*args, **kwargs)
                bound.apply_defaults()
                argumentos = dict(bound.arguments)
            except TypeError:
                return fn(*args, **kwargs)
            if si is not None and not si(argumentos):
                return fn(*args, **kwargs)
            params: dict[str, Any] = {k: argumentos.get(k) for k in campos if k in argumentos}
            params.update({k: huella(argumentos.get(k)) for k in huellas if k in argumentos})
            try:
                out = fn(*args, **kwargs)
            except BaseException as exc:
                _seguro(operacion, params=params, ok=False, error=f"{type(exc).__name__}: {exc}")
                raise
            if resumir is not None:
                try:
                    resumen: Any = resumir(out)
                except Exception as exc:  # noqa: BLE001 — un resumen roto no oculta la acción
                    resumen = {"resumen_error": f"{type(exc).__name__}: {exc}"}
            elif isinstance(out, dict):
                resumen = {k: out.get(k) for k in claves if k in out}
            else:
                resumen = out if not claves else None
            ok = _ok(out) and (_ok(resumen) if resumir is not None else True)
            _seguro(operacion, params=params, resultado=resumen, ok=ok)
            return out

        envoltura.__eolfi_accion__ = operacion  # type: ignore[attr-defined]
        return envoltura

    return deco


def _ok(out: Any) -> bool:
    if isinstance(out, dict):
        estado = str(out.get("estado") or out.get("status") or "").lower()
        if estado in ("fallido", "error", "interrumpido"):
            return False
        if out.get("ok") is False:
            return False
    return True


def _seguro(operacion: str, **kw: Any) -> None:
    try:
        anotar(operacion, **kw)
    except Exception as exc:  # noqa: BLE001 — la acción ya ocurrió: se avisa, no se oculta ni se deshace
        print(f"[eolfi] AVISO: no se pudo registrar la acción {operacion}: {exc}", file=sys.stderr)


anotar_seguro = _seguro   # para otros módulos (RSI, instalador): registra o avisa por stderr, nunca lanza


# ── Unión con la cadena del RSI ───────────────────────────────────────────────────────────────────────────────────

def verificar_rsi() -> dict[str, Any]:
    """Las dos cadenas íntegras y cada reflejo ``rsi.<tipo>`` presente en la del RSI con el mismo SHA-256.

    Los eventos reflejables del RSI anteriores al primer reflejo son de antes de unir los registros y se cuentan
    aparte; uno posterior sin reflejo indica que escribir aquí falló (o que se borró su reflejo)."""
    from eolfi import rsi

    estado = verificar()
    rsi_estado = rsi.verificar_registro()
    out: dict[str, Any] = {**estado, "rsi": rsi_estado}
    if not estado["ok"] or not rsi_estado["ok"]:
        return {**out, "ok": False}
    rsi_eventos = rsi.eventos()
    por_seq = {e["seq"]: e for e in rsi_eventos}
    reflejos = [e for e in eventos() if str(e.get("operacion", "")).startswith("rsi.")]
    for r in reflejos:
        params = r.get("params") or {}
        original = por_seq.get(params.get("rsi_seq"))
        if not original or original["sha256"] != params.get("rsi_sha256") or r["operacion"] != f"rsi.{original['tipo']}":
            return {**out, "ok": False, "reflejo_roto": r["seq"],
                    "motivo": f"el evento {r['seq']} refleja el {params.get('rsi_seq')} del RSI, que ya no coincide: "
                              "registro del RSI reescrito o truncado"}
    reflejados = {(r.get("params") or {}).get("rsi_seq") for r in reflejos}
    primero = min(reflejados) if reflejados else None
    reflejables = [e["seq"] for e in rsi_eventos if e["tipo"] in rsi.TIPOS_REFLEJADOS]
    previos = [s for s in reflejables if primero is None or s < primero]
    sin_reflejo = [s for s in reflejables if primero is not None and s > primero and s not in reflejados]
    return {**out, "reflejos": len(reflejos), "rsi_anteriores_a_la_union": len(previos),
            "rsi_sin_reflejo": sin_reflejo[:50], "ok": not sin_reflejo}


# ── Firma (HMAC-SHA256 con una clave guardada fuera) ──────────────────────────────────────────────────────────────

def generar_clave(destino: str | Path) -> dict[str, Any]:
    """Crea una clave aleatoria de 32 bytes (hex) en ``destino``; nunca sustituye una existente."""
    destino = Path(destino)
    if destino.exists():
        raise ValueError(f"{destino} ya existe: no se sustituye una clave")
    if destino.resolve().parent == registro_file().resolve().parent:
        raise ValueError("la clave no puede guardarse junto al registro: guárdala fuera de su alcance")
    destino.parent.mkdir(parents=True, exist_ok=True)
    clave = secrets.token_hex(32)
    fd = os.open(destino, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(clave + "\n")
    return {"clave": str(destino), "clave_id": _clave_id(bytes.fromhex(clave))}


def _clave_id(clave: bytes) -> str:
    return hashlib.sha256(b"eolfi-acciones-clave|" + clave).hexdigest()[:16]


def _leer_clave(archivo: str | Path | None) -> bytes:
    archivo = archivo or os.environ.get("EOLFI_ACCIONES_CLAVE")
    if not archivo:
        raise ValueError("falta la clave: --clave ARCHIVO o EOLFI_ACCIONES_CLAVE")
    texto = Path(archivo).read_text(encoding="ascii").strip()
    try:
        clave = bytes.fromhex(texto)
    except ValueError:
        raise ValueError(f"{archivo} no contiene una clave hexadecimal") from None
    if len(clave) < 32:
        raise ValueError(f"{archivo}: la clave debe tener al menos 32 bytes")
    return clave


def _hmac(clave: bytes, seq: int, sha: str) -> str:
    return hmac.new(clave, f"{SCHEMA}|{seq}|{sha}".encode(), hashlib.sha256).hexdigest()


def firmar(clave_archivo: str | Path | None = None) -> dict[str, Any]:
    """Firma la cabeza de una cadena íntegra con un evento ``acciones.firma``."""
    clave = _leer_clave(clave_archivo)
    estado = verificar()
    if not estado["ok"]:
        raise ValueError(f"no se firma una cadena rota (evento {estado['roto_en']})")
    if not estado["eventos"]:
        raise ValueError("no hay eventos que firmar")
    seq, cabeza = estado["eventos"], estado["ultimo"]
    evento = anotar("acciones.firma", params={"hasta_seq": seq, "cabeza": cabeza, "clave_id": _clave_id(clave)},
                    resultado={"hmac": _hmac(clave, seq, cabeza)}, origen="titular")
    if evento is None:
        raise ValueError("el registro de acciones está desactivado (EOLFI_ACCIONES=0)")
    return {"ok": True, "firmado_hasta": seq, "cabeza": cabeza, "evento": evento["seq"], "clave_id": _clave_id(clave)}


def verificar_firmas(clave_archivo: str | Path | None = None) -> dict[str, Any]:
    """Cadena íntegra y cada firma hecha con esta clave válida para el evento que firmó."""
    clave = _leer_clave(clave_archivo)
    kid = _clave_id(clave)
    estado = verificar()
    if not estado["ok"]:
        return {**estado, "firmas": 0}
    todos = eventos()
    por_seq = {e["seq"]: e["sha256"] for e in todos}
    validas, otras, fallidas, firmado = 0, 0, 0, 0
    for e in todos:
        if e.get("operacion") != "acciones.firma":
            continue
        if not e.get("ok", True):
            fallidas += 1          # firma automática que no pudo hacerse: no firma nada
            continue
        p, r = e.get("params") or {}, e.get("resultado") or {}
        if p.get("clave_id") != kid:
            otras += 1
            continue
        seq, cabeza = p.get("hasta_seq"), p.get("cabeza")
        if (not isinstance(seq, int) or por_seq.get(seq) != cabeza
                or not hmac.compare_digest(str(r.get("hmac", "")), _hmac(clave, seq, str(cabeza)))):
            return {**estado, "ok": False, "firma_rota": e["seq"], "firmas": validas,
                    "motivo": f"la firma del evento {e['seq']} no corresponde al evento {seq}: registro reescrito "
                              "o firma falsificada"}
        validas += 1
        firmado = max(firmado, seq)
    cola = [e for e in todos if e["seq"] > firmado and e.get("operacion") != "acciones.firma"]
    return {**estado, "firmas": validas, "firmas_de_otra_clave": otras, "firmas_fallidas": fallidas,
            "firmado_hasta": firmado, "sin_firmar_al_final": len(cola), "clave_id": kid,
            **({"aviso": "ninguna firma con esta clave"} if not validas else {})}


def anclar(destino: str | Path) -> dict[str, Any]:
    """Copia la cabeza actual de la cadena (seq y SHA-256) a ``destino``, un archivo que el titular conserva
    fuera del alcance de quien escribe el registro (otra unidad, otra cuenta, un medio extraíble).

    Solo ancla una cadena íntegra. Reescribir después el registro entero con una cadena nueva ya no coincide con
    las anclas guardadas antes; lo posterior a la última ancla sigue sin esa protección."""
    estado = verificar()
    if not estado["ok"]:
        raise ValueError(f"no se ancla una cadena rota (evento {estado['roto_en']})")
    if not estado["eventos"]:
        raise ValueError("no hay eventos que anclar")
    destino = Path(destino)
    if destino.resolve() == registro_file().resolve():
        raise ValueError("el ancla no puede ser el propio registro")
    ancla = {"schema": SCHEMA + "#ancla", "fecha": datetime.now(timezone.utc).isoformat(),
             "registro": str(registro_file()), "seq": estado["eventos"], "sha256": estado["ultimo"]}
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(_canon(ancla) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return {**ancla, "destino": str(destino)}


def verificar_anclas(ancla: str | Path) -> dict[str, Any]:
    """Cadena íntegra y cada ancla guardada presente en ella con el mismo SHA-256 y número de evento."""
    estado = verificar()
    try:
        lineas = [ln for ln in _lineas(Path(ancla).read_text(encoding="utf-8")) if ln.strip()]
    except FileNotFoundError:
        return {**estado, "ok": False, "anclas": 0, "motivo": f"no existe el archivo de anclas {ancla}"}
    if not estado["ok"]:
        return {**estado, "anclas": len(lineas)}
    por_seq = {e["seq"]: e["sha256"] for e in eventos()}
    for i, linea in enumerate(lineas, 1):
        try:
            a = json.loads(linea)
            seq, sha = int(a["seq"]), str(a["sha256"])
        except (ValueError, KeyError, TypeError):
            return {**estado, "ok": False, "anclas": i - 1, "motivo": f"ancla {i} ilegible"}
        if por_seq.get(seq) != sha:
            return {**estado, "ok": False, "anclas": i - 1, "ancla_rota": i,
                    "motivo": f"el evento {seq} no coincide con el ancla {i}: registro reescrito o truncado"}
    return {**estado, "anclas": len(lineas)}


def listar(n: int = 20) -> list[dict[str, Any]]:
    return eventos()[-max(1, n):]
