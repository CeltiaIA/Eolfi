"""Adaptadores opcionales a herramientas externas (graceful si no están).

Envuelven binarios reales (capa, rizin/radare2, Ghidra headless). Si la
herramienta no está instalada, available() es False y no se ejecuta nada:
el triaje sigue funcionando solo con los proveedores de stdlib.

Ninguno ejecuta el objetivo: todos hacen análisis estático. La salida de
las herramientas se parsea como DATO (JSON) y nunca se interpreta.
"""
from __future__ import annotations

import json
import os
import shutil
import contextlib
import hashlib
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from eolfi.providers.base import Provider

MAX_FUNCTIONS = 5000



# Caracteres que cmd.exe interpreta aunque vayan entre comillas (BatBadBut) o que abren opciones.
_CMD_META = set('&|^%<>()"!\r\n')
_SAFE_NAME = re.compile(r"[A-Za-z0-9_.:$@~?-]{1,200}")


def check_cmd_safe(arg: str) -> None:
    if any(c in _CMD_META for c in arg) or arg.startswith("-"):
        raise ValueError(f"argumento no seguro para la línea de comandos: {arg!r}")


def _error(operation: str, msg: str, limitations: str) -> dict[str, Any]:
    return {
        "operation": operation,
        "result": {"error": msg[:2000]},
        "authority": "analyst_inference",
        "confidence": "low",
        "limitations": limitations,
    }


def _last_json(text: str) -> Any:
    """Devuelve el último documento JSON de la salida (las herramientas pueden imprimir avisos antes o
    después, y el JSON puede ocupar varias líneas). B11: antes una línea «{…» rota impedía el respaldo."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    lines = text.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].lstrip().startswith(("{", "[")):
            try:
                return dec.raw_decode("\n".join(lines[i:]).lstrip())[0]
            except json.JSONDecodeError:
                continue
    return json.loads(text)   # sin JSON: el error de siempre


def tools_dir() -> "Path":
    """Carpeta de herramientas propias de Eolfi (capa, rizin, jadx…): EOLFI_TOOLS_DIR o ~/.eolfi/tools.
    Así no hace falta tocar el PATH del sistema."""
    from pathlib import Path

    return Path(os.environ.get("EOLFI_TOOLS_DIR") or Path.home() / ".eolfi" / "tools")


def tools_dir_find(name: str) -> str | None:
    """Busca un ejecutable en la carpeta de herramientas (hasta 3 niveles: tools/capa/capa.exe, tools/rizin/bin/rizin.exe)."""
    base = tools_dir()
    if not base.is_dir():
        return None
    names = {name, f"{name}.exe", f"{name}.bat", f"{name}.cmd"} if os.name == "nt" else {name}
    for depth in ("*", "*/*", "*/*/*", "*/*/*/*"):
        for p in sorted(base.glob(depth)):
            if p.name.lower() in {n.lower() for n in names} and p.is_file():
                return str(p)
    return None


class ExternalCommandProvider(Provider):
    """Base para proveedores que llaman a un ejecutable externo."""
    binaries: tuple[str, ...] = ()
    version_args: tuple[str, ...] = ("--version",)
    operation = "external"
    timeout = 300.0

    def __init__(self) -> None:
        self.version = "0.0.0"
        self._resolved: str | None = None

    def resolve(self) -> str | None:
        if self._resolved is None:
            for b in self.binaries:
                found = shutil.which(b) or tools_dir_find(b)
                if found:
                    self._resolved = found
                    break
        return self._resolved

    def available(self) -> bool:
        return self.resolve() is not None

    def _tool_version(self) -> str:
        try:
            out = subprocess.run(
                [self.resolve(), *self.version_args], capture_output=True, text=True, timeout=20
            )
            return ((out.stdout or out.stderr).strip().splitlines() or ["unknown"])[0][:80]
        except Exception:  # noqa: BLE001
            return "unknown"

    @contextlib.contextmanager
    def _staged(self, target: str):
        """El objetivo se pasa a la herramienta como copia (o enlace duro) con nombre <sha256>.bin
        en una carpeta temporal: así su nombre nunca se interpreta como opción ('-c!cmd' en rizin)
        ni como metacaracteres de cmd.exe ('a&calc.exe' con analyzeHeadless.bat)."""
        src = Path(target).resolve()
        h = hashlib.sha256()
        with open(src, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        tmp = tempfile.mkdtemp(prefix="eolfi-tgt-")
        dst = Path(tmp, f"{h.hexdigest()[:24]}.bin")
        try:
            # Copia, nunca enlace duro: con un enlace, una herramienta que escriba en su entrada (o un
            # análisis que la modifique) cambiaría también el archivo original (B11).
            shutil.copyfile(src, dst)
            if str(self.resolve() or "").lower().endswith((".bat", ".cmd")):
                # Solo los lanzadores .bat pasan por cmd.exe: capa y rizin admiten rutas con «(» o «&».
                check_cmd_safe(str(dst))
            yield str(dst)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _run(self, args: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
        return run_tree(args, timeout or self.timeout)


def run_tree(args: list[str], timeout: float, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Como subprocess.run, pero al agotar el plazo mata el ÁRBOL de procesos (PLAN_MEJORAS A8): los
    lanzadores .bat/.sh (Ghidra, rizin, capa) dejan nietos Java/Python que seguían vivos consumiendo CPU
    y con las tuberías abiertas. stdin vacío: algunos .bat terminan con «pause»."""
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                         text=True, encoding="utf-8", errors="replace", creationflags=flags,
                         start_new_session=os.name != "nt", env=env)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
        else:
            import signal
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
        try:
            p.kill()
        except OSError:
            pass
        try:
            p.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        raise
    return subprocess.CompletedProcess(args, p.returncode, out, err)


# ---------------------------------------------------------------------------
# capa
# ---------------------------------------------------------------------------
def parse_capa_json(doc: dict[str, Any]) -> dict[str, Any]:
    """Normaliza el JSON de capa (v4-v9) a reglas, ATT&CK y MBC."""
    rules = doc.get("rules") or {}
    out_rules = []
    attack: set[str] = set()
    mbc: set[str] = set()
    for name, body in rules.items():
        meta = (body or {}).get("meta") or {}
        if meta.get("lib") or meta.get("is_subscope_rule"):
            continue   # reglas auxiliares, no capacidades finales
        ns = meta.get("namespace")
        out_rules.append({"name": name, "namespace": ns if isinstance(ns, str) else None})   # B12: hashable
        for a in meta.get("attack") or meta.get("att&ck") or []:
            if isinstance(a, dict):
                ident = a.get("id") or ""
                label = "::".join(a.get("parts") or [a.get("technique", "")])
                attack.add(f"{label} [{ident}]" if ident else label)
            else:
                attack.add(str(a))
        for m in meta.get("mbc") or []:
            if isinstance(m, dict):
                ident = m.get("id") or ""
                label = "::".join(m.get("parts") or [m.get("behavior", "")])
                mbc.add(f"{label} [{ident}]" if ident else label)
            else:
                mbc.add(str(m))
    analysis = (doc.get("meta") or {}).get("analysis") or {}
    return {
        "rules": sorted(r["name"] for r in out_rules),
        "namespaces": sorted({r["namespace"] for r in out_rules if r["namespace"]}),
        "attack": sorted(attack),
        "mbc": sorted(mbc),
        "format": analysis.get("format"),
        "arch": analysis.get("arch"),
        "os": analysis.get("os"),
    }


class CapaProvider(ExternalCommandProvider):
    name = "mandiant.capa"
    binaries = ("capa",)
    operation = "detect_capabilities"

    def run(self, target: str) -> list[dict[str, Any]]:
        if not self.available():
            return []
        self.version = self._tool_version()
        try:
            with self._staged(target) as staged:
                out = self._run([self.resolve(), "-j", staged])
        except subprocess.TimeoutExpired:
            return [_error(self.operation, "timeout", "capa agotó el tiempo.")]
        except (OSError, ValueError) as exc:
            return [_error(self.operation, str(exc), "No se pudo preparar el objetivo para capa.")]
        if out.returncode != 0:
            return [_error(self.operation, f"exit {out.returncode}: {out.stderr.strip()[-500:]}",
                           "capa no soporta el formato o falló.")]
        try:
            parsed = parse_capa_json(_last_json(out.stdout))
        except (json.JSONDecodeError, AttributeError) as exc:
            return [_error(self.operation, f"JSON inválido: {exc}", "Salida de capa no parseable.")]
        return [{
            "operation": self.operation,
            "result": parsed,
            "authority": "controlled_repro",
            "confidence": "medium",
            "limitations": ("Coincidencia de reglas estáticas: indica presencia de código, "
                            "no que se ejecute. Sin reglas de librería."),
        }]


# ---------------------------------------------------------------------------
# rizin / radare2
# ---------------------------------------------------------------------------
class RizinProvider(ExternalCommandProvider):
    name = "rizin"
    binaries = ("rizin", "radare2", "r2")
    version_args = ("-v",)
    operation = "rizin_functions"

    def run(self, target: str) -> list[dict[str, Any]]:
        if not self.available():
            return []
        exe = self.resolve()
        # rizin y radare2 no son iguales: la versión registrada dice cuál se usó de verdad.
        self.version = f"{Path(exe).stem} {self._tool_version()}"
        findings: list[dict[str, Any]] = []
        base = [exe, "-q", "-2", "-e", "scr.color=0", "-e", "scr.interactive=false"]
        try:
            staging = self._staged(target)
            target = staging.__enter__()
        except (OSError, ValueError) as exc:
            return [_error("rizin_info", str(exc), "No se pudo preparar el objetivo para rizin.")]
        try:
            return self._run_staged(base, exe, target, findings)
        finally:
            staging.__exit__(None, None, None)

    def _run_staged(self, base: list[str], exe: str, target: str, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            info = self._run(base + ["-c", "ij", target], timeout=60)
            findings.append({
                "operation": "rizin_info",
                "result": _slim_info(_as_dict(_last_json(info.stdout))),
                "authority": "distributed_artifact",
                "confidence": "high",
                "limitations": f"Según {Path(exe).stem}.",
            })
        except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError) as exc:
            findings.append(_error("rizin_info", str(exc), "rizin no pudo leer la cabecera."))
        try:
            fl = self._run(base + ["-c", "aaa;aflj", target])
            funcs = _last_json(fl.stdout) or []
            if not isinstance(funcs, list):
                raise ValueError("aflj no devolvió una lista")
            findings.append({
                "operation": self.operation,
                "result": _slim_functions(funcs),
                "authority": "controlled_repro",
                "confidence": "medium",
                "limitations": ("Análisis automático (aaa): puede partir o fusionar funciones, "
                                "y no ve código ofuscado o generado en runtime."),
            })
        except subprocess.TimeoutExpired:
            findings.append(_error(self.operation, "timeout", "El análisis aaa agotó el tiempo."))
        except (json.JSONDecodeError, ValueError) as exc:
            findings.append(_error(self.operation, str(exc), "Salida aflj no parseable."))
        return findings


def _as_dict(doc: Any) -> dict[str, Any]:
    if not isinstance(doc, dict):
        raise ValueError("ij no devolvió un objeto JSON")
    return doc


def _slim_info(doc: dict[str, Any]) -> dict[str, Any]:
    b = (doc or {}).get("bin") or {}
    keys = ("arch", "bits", "os", "class", "lang", "compiler", "machine", "endian",
            "canary", "nx", "pic", "relro", "stripped", "static", "signed")
    return {k: b[k] for k in keys if k in b}


def _slim_functions(funcs: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for f in funcs[:MAX_FUNCTIONS]:
        items.append({
            "name": f.get("name"),
            "offset": f.get("offset", f.get("addr")),
            "size": f.get("size", f.get("realsz")),
            "blocks": f.get("nbbs"),
            "complexity": f.get("cc"),
        })
    # Tamaños de herramientas distintas pueden venir como texto o faltar: nunca TypeError al ordenar.
    items.sort(key=lambda x: x["size"] if isinstance(x["size"], (int, float)) else 0, reverse=True)
    return {"count": len(funcs), "truncated": len(funcs) > MAX_FUNCTIONS, "functions": items}


# ---------------------------------------------------------------------------
# Ghidra headless
# ---------------------------------------------------------------------------
_SCRIPTS = Path(__file__).with_name("ghidra_scripts")


class GhidraProvider(ExternalCommandProvider):
    """Ghidra en modo headless con un script propio que exporta JSON.

    Busca analyzeHeadless en $GHIDRA_INSTALL_DIR/support o en el PATH.
    """
    name = "ghidra.headless"
    operation = "ghidra_functions"
    timeout = 1800.0

    def __init__(self, decompile: list[str] | None = None) -> None:
        super().__init__()
        # Nombres o direcciones a decompilar; "entry" = puntos de entrada.
        # Solo nombres/direcciones con caracteres seguros: analyzeHeadless.bat pasa por cmd.exe.
        self.decompile = [d.strip() for d in (decompile or []) if _SAFE_NAME.fullmatch(d.strip())]

    def resolve(self) -> str | None:
        if self._resolved is None:
            exe = "analyzeHeadless.bat" if os.name == "nt" else "analyzeHeadless"
            home = os.environ.get("GHIDRA_INSTALL_DIR")
            cand = Path(home, "support", exe) if home else None
            if cand and cand.is_file():
                self._resolved = str(cand)
            else:
                self._resolved = shutil.which("analyzeHeadless") or shutil.which(exe)
        return self._resolved

    def _tool_version(self) -> str:
        props = Path(self.resolve()).parents[1] / "Ghidra" / "application.properties"
        try:
            for line in props.read_text(encoding="utf-8").splitlines():
                if line.startswith("application.version="):
                    return line.split("=", 1)[1].strip()
        except OSError:
            pass
        return "unknown"

    def run(self, target: str) -> list[dict[str, Any]]:
        if not self.available():
            return []
        self.version = self._tool_version()
        try:
            for d in self.decompile:
                check_cmd_safe(d)
            staging = self._staged(target)
            staged = staging.__enter__()
        except (OSError, ValueError) as exc:
            return [_error(self.operation, str(exc), "Objetivo o nombres de función no aptos para Ghidra.")]
        try:
            return self._run_ghidra(staged)
        finally:
            staging.__exit__(None, None, None)

    def _run_ghidra(self, staged: str) -> list[dict[str, Any]]:
        with tempfile.TemporaryDirectory(prefix="eolfi-ghidra-") as tmp:
            check_cmd_safe(tmp)
            out_json = Path(tmp, "export.json")
            args = [
                self.resolve(), tmp, "eolfi", "-import", staged,
                "-scriptPath", str(_SCRIPTS), "-postScript", "EolfiExport.java", str(out_json),
                ",".join(self.decompile),
                "-deleteProject", "-analysisTimeoutPerFile", str(int(self.timeout * 0.8)),
            ]
            try:
                proc = self._run(args)
            except subprocess.TimeoutExpired:
                return [_error(self.operation, "timeout", "Ghidra agotó el tiempo.")]
            if not out_json.is_file():
                return [_error(self.operation, f"exit {proc.returncode}: {proc.stdout.strip()[-800:]}",
                               "Ghidra no produjo exportación (¿formato no soportado?).")]
            try:
                doc = json.loads(out_json.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                return [_error(self.operation, str(exc), "Exportación de Ghidra corrupta.")]
            if not isinstance(doc, dict):   # B12
                return [_error(self.operation, "la exportación no es un objeto JSON", "Exportación de Ghidra corrupta.")]
        funcs = doc.get("functions", [])
        extra = []
        if self.decompile:
            extra.append({
                "operation": "ghidra_decompilation",
                "params": {"functions": self.decompile},
                "result": {"requested": self.decompile, "functions": doc.get("decompiled", [])},
                "authority": "controlled_repro",
                "confidence": "medium",
                "limitations": ("Pseudo-C del decompilador: nombres y tipos inferidos; puede diferir "
                                "del código fuente original."),
            })
        return extra + [
            {
                "operation": "ghidra_program",
                "result": doc.get("program", {}),
                "authority": "distributed_artifact",
                "confidence": "high",
                "limitations": "Según el cargador de Ghidra.",
            },
            {
                "operation": self.operation,
                "result": {
                    "count": doc.get("function_count", len(funcs)),
                    "truncated": doc.get("truncated", False),
                    "functions": sorted(funcs, key=lambda f: f.get("size") or 0, reverse=True),
                },
                "authority": "controlled_repro",
                "confidence": "medium",
                "limitations": "Auto-análisis de Ghidra; límites de funciones heurísticos.",
            },
            {
                "operation": "ghidra_external_symbols",
                "result": {"symbols": doc.get("external_symbols", [])},
                "authority": "distributed_artifact",
                "confidence": "high",
                "limitations": "",
            },
        ]
