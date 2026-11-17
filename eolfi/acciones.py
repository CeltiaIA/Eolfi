"""Registro encadenado de acciones que cambian estado (B8, PLAN_DEFINITIVO.md).

Cada acción ejecutada (no las vistas previas) añade un evento a ``~/.eolfi/acciones.jsonl`` con el SHA-256 del
evento anterior. Editar, borrar o reordenar una línea rompe la cadena y ``verificar()`` dice dónde.

Qué cubre: las funciones decoradas con ``@registrada`` (adoptar, quitar o recomendar perfil con aplicación,
arrancar, cambiar y parar el motor, retirar, desinstalar o restaurar perfiles, ejecutar una reconstrucción o un
smoke). Las llame la CLI, el panel o un agente, el evento se escribe en el mismo sitio.

Límites:
- La cadena detecta cambios de un registro que se conserva, pero quien puede escribir el archivo puede
  reescribirlo entero con una cadena nueva; no es un registro firmado ni externo.
- Si escribir el evento falla, la acción ya hecha no se deshace: se avisa por stderr y ``verificar()`` no lo verá.
- Solo se guardan los campos declarados para cada operación (nombres, hashes, estados), nunca prompts ni código.
- El registro RSI de la rama ``vas-b1-b2`` (``eolfi/rsi.py``) es otra cadena; unificarlas queda pendiente.
"""
from __future__ import annotations

import functools
import hashlib
import inspect
import json
import os
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
            except FileExistsError:
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


def anotar(operacion: str, *, params: dict[str, Any] | None = None, resultado: Any = None,
           ok: bool = True, error: str | None = None, origen: str | None = None) -> dict[str, Any] | None:
    """Añade un evento a la cadena. Devuelve el evento, o None si el registro está desactivado."""
    if not activo():
        return None
    path = registro_file()
    with _Cerrojo(path):
        last = _ultimo(path)
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


def eventos(path: Path | None = None) -> list[dict[str, Any]]:
    try:
        lines = (path or registro_file()).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in lines if line.strip()]


def verificar(path: Path | None = None) -> dict[str, Any]:
    """Recalcula la cadena completa. Una línea ilegible también cuenta como rotura."""
    path = path or registro_file()
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
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


def registrada(operacion: str, *, campos: Iterable[str] = (), resultado: Iterable[str] = (),
               si: Callable[[dict[str, Any]], bool] | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorador: registra la llamada si ``si(argumentos)`` es verdadero (por defecto, siempre).

    ``campos`` elige qué argumentos se guardan y ``resultado`` qué claves de un resultado dict. Los fallos se
    registran con ``ok: false`` y se vuelven a lanzar sin cambiarlos."""
    campos, claves = tuple(campos), tuple(resultado)

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
            params = {k: argumentos.get(k) for k in campos if k in argumentos}
            try:
                out = fn(*args, **kwargs)
            except BaseException as exc:
                _seguro(operacion, params=params, ok=False, error=f"{type(exc).__name__}: {exc}")
                raise
            if isinstance(out, dict):
                resumen: Any = {k: out.get(k) for k in claves if k in out}
            else:
                resumen = out if not claves else None
            _seguro(operacion, params=params, resultado=resumen, ok=_ok(out))
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


def listar(n: int = 20) -> list[dict[str, Any]]:
    return eventos()[-max(1, n):]
