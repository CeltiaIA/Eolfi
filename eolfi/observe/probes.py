"""Sondas por plataforma para la observación de caja negra.

Todas usan solo la biblioteca estándar y declaran qué cubren. Lo que una plataforma no permite observar se
devuelve como «not_available» con el motivo; nunca se simula.

- Procesos hijos: muestreo periódico de la tabla de procesos (Windows: ToolHelp32 por ctypes; Linux: /proc;
  macOS/otros POSIX: ``ps``). Un hijo que nace y muere entre dos muestras no se ve.
- Archivos: instantánea (ruta → tamaño + SHA-256) de las carpetas declaradas antes y después de cada paso.
- Registro de Windows: instantánea de las claves declaradas (valores y subclaves), solo lectura.
- Señales/códigos de estado: señal POSIX (código negativo) o NTSTATUS de Windows conocidos.
"""
from __future__ import annotations

import hashlib
import base64
import os
import signal as _signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

MAX_SCOPE_FILES = 20_000
MAX_HASH_BYTES = 64 * 1024 * 1024
MAX_CAPTURE_FILE_BYTES = 256 * 1024
MAX_CAPTURE_SESSION_BYTES = 1024 * 1024
MAX_REGISTRY_VALUES = 5_000

# NTSTATUS frecuentes en códigos de salida de procesos de Windows.
NTSTATUS = {
    0xC0000005: "STATUS_ACCESS_VIOLATION",
    0xC00000FD: "STATUS_STACK_OVERFLOW",
    0xC0000094: "STATUS_INTEGER_DIVIDE_BY_ZERO",
    0xC000001D: "STATUS_ILLEGAL_INSTRUCTION",
    0xC0000409: "STATUS_STACK_BUFFER_OVERRUN",
    0xC0000135: "STATUS_DLL_NOT_FOUND",
    0xC0000139: "STATUS_ENTRYPOINT_NOT_FOUND",
    0xC000013A: "STATUS_CONTROL_C_EXIT",
    0xC0000142: "STATUS_DLL_INIT_FAILED",
    0x80000003: "STATUS_BREAKPOINT",
    0x40010004: "DBG_TERMINATE_PROCESS",
}


def exit_status(returncode: int | None) -> dict[str, Any]:
    """Interpreta el código de salida: señal POSIX, NTSTATUS de Windows o salida normal."""
    if returncode is None:
        return {"kind": "none"}
    if os.name != "nt" and returncode < 0:
        num = -returncode
        try:
            name = _signal.Signals(num).name
        except ValueError:
            name = f"SIG{num}"
        return {"kind": "signal", "signal": num, "signal_name": name}
    if os.name == "nt":
        code = returncode & 0xFFFFFFFF
        if code in NTSTATUS:
            return {"kind": "ntstatus", "code": f"0x{code:08X}", "name": NTSTATUS[code]}
        if code >= 0xC0000000:
            return {"kind": "ntstatus", "code": f"0x{code:08X}", "name": "desconocido (severidad error)"}
    return {"kind": "exit", "code": returncode}


# -- procesos hijos ------------------------------------------------------------------------------------
def _table_windows() -> list[tuple[int, int, str]]:
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)   # TH32CS_SNAPPROCESS
    if snap in (None, wintypes.HANDLE(-1).value):
        return []
    out = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            out.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID), entry.szExeFile))
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return out


def _table_proc() -> list[tuple[int, int, str]]:
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            raw = Path("/proc", d, "stat").read_text(errors="replace")
        except OSError:
            continue
        # pid (comm) state ppid ...  — comm puede contener espacios y paréntesis.
        l, r = raw.find("("), raw.rfind(")")
        if l < 0 or r < 0:
            continue
        fields = raw[r + 2:].split()
        if len(fields) >= 2:
            out.append((int(d), int(fields[1]), raw[l + 1:r]))
    return out


def _table_ps() -> list[tuple[int, int, str]]:
    try:
        raw = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,comm="], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for line in raw.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            out.append((int(parts[0]), int(parts[1]), os.path.basename(parts[2])))
    return out


def process_table_method() -> str:
    if os.name == "nt":
        return "toolhelp32"
    if os.path.isdir("/proc") and os.path.exists("/proc/self/stat"):
        return "procfs"
    return "ps"


def process_table() -> list[tuple[int, int, str]]:
    method = process_table_method()
    return _table_windows() if method == "toolhelp32" else _table_proc() if method == "procfs" else _table_ps()


def _start_windows(pid: int) -> float | None:
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    h = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        c, e, k, u = (wintypes.FILETIME() for _ in range(4))
        if not k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
            return None
        return float((c.dwHighDateTime << 32) | c.dwLowDateTime)
    finally:
        k32.CloseHandle(h)


def _start_proc(pid: int) -> float | None:
    try:
        raw = Path("/proc", str(pid), "stat").read_text(errors="replace")
        return float(raw[raw.rfind(")") + 2:].split()[19])   # campo 22: starttime (ticks desde el arranque)
    except (OSError, ValueError, IndexError):
        return None


def process_start(pid: int) -> float | None:
    """Instante de creación del proceso (unidad propia de la plataforma) o None si no se puede leer.

    Sirve para no confundir un PID reutilizado: en Windows, el PID de un padre ya terminado puede reasignarse a
    nuestro proceso y sus antiguos hijos (p. ej. csrss.exe) parecerían descendientes."""
    method = process_table_method()
    return _start_windows(pid) if method == "toolhelp32" else _start_proc(pid) if method == "procfs" else None


class ChildSampler:
    """Muestrea los descendientes de un PID mientras el proceso vive.

    Un proceso solo cuenta como descendiente si su creación es posterior a la de su padre (cuando la plataforma
    permite leerla): un PID reutilizado no arrastra los hijos huérfanos del proceso anterior."""

    def __init__(self, root_pid: int, interval: float = 0.02):
        self.root, self.interval = root_pid, interval
        self._starts: dict[int, float | None] = {root_pid: process_start(root_pid)}
        self.check_start = process_table_method() != "ps"
        self.seen: dict[int, dict[str, Any]] = {}
        self.samples = 0
        self.errors: list[str] = []
        self._stop = threading.Event()
        self._started = time.monotonic()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> "ChildSampler":
        self._thread.start()
        return self

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.sample()
            self._stop.wait(self.interval)

    def sample(self) -> None:
        try:
            table = process_table()
        except Exception as exc:  # noqa: BLE001 — una sonda no debe tumbar la sesión
            if len(self.errors) < 5:
                self.errors.append(f"{type(exc).__name__}: {exc}")
            return
        self.samples += 1
        children: dict[int, list[tuple[int, str]]] = {}
        for pid, ppid, name in table:
            if pid != ppid:
                children.setdefault(ppid, []).append((pid, name))
        stack, depth = [(self.root, 0)], {self.root: 0}
        while stack:
            pid, d = stack.pop()
            for cpid, name in children.get(pid, []):
                if cpid in depth:
                    continue
                if self.check_start:
                    if cpid not in self._starts:
                        self._starts[cpid] = process_start(cpid)
                    cs, ps = self._starts[cpid], self._starts.get(pid)
                    if cs is None or ps is None or cs < ps:
                        continue        # sin hora de creación verificable o anterior al padre: no es hijo nuestro
                depth[cpid] = d + 1
                stack.append((cpid, d + 1))
                if cpid not in self.seen:
                    self.seen[cpid] = {"name": name, "parent_pid": pid, "depth": d + 1,
                                       "first_seen_ms": round((time.monotonic() - self._started) * 1000),
                                       "start": self._starts.get(cpid)}

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        self._thread.join(timeout=5)
        procs = sorted(self.seen.items(), key=lambda kv: (kv[1]["first_seen_ms"], kv[0]))
        return {"method": process_table_method(), "interval_ms": round(self.interval * 1000),
                "start_time_check": self.check_start,
                "samples": self.samples, "errors": self.errors,
                "processes": [{"pid": pid, **info} for pid, info in procs]}


# -- archivos ----------------------------------------------------------------------------------------
def _sha_file(p: Path, size: int) -> tuple[str, bool]:
    h = hashlib.sha256()
    read, truncated = 0, False
    with p.open("rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            if read + len(chunk) > MAX_HASH_BYTES:
                h.update(chunk[:MAX_HASH_BYTES - read])
                truncated = True
                break
            h.update(chunk)
            read += len(chunk)
    return h.hexdigest(), truncated


NORMALIZE_MAX_BYTES = 1024 * 1024


def snapshot_files(roots: list[tuple[str, Path]], normalize: Any = None) -> dict[str, Any]:
    """{"files": {"etiqueta/ruta": {"size", "sha256"[, "sha256_normalized"]}}, "truncated", "errors"}.

    No sigue enlaces. ``normalize(bytes) -> bytes`` (opcional) se aplica a archivos de hasta 1 MB; si cambia el
    contenido (p. ej. rutas del sandbox escritas en el archivo), se guarda también ``sha256_normalized``."""
    files: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    truncated = False
    for label, root in roots:
        if not root.exists():
            continue
        stack = [root]
        while stack:
            d = stack.pop()
            try:
                entries = sorted(os.scandir(d), key=lambda e: e.name)
            except OSError as exc:
                if len(errors) < 50:
                    errors.append(f"{label}: {type(exc).__name__}")
                continue
            for e in entries:
                try:
                    if e.is_symlink():
                        rel = Path(e.path).relative_to(root).as_posix()
                        files[f"{label}/{rel}"] = {"size": None, "sha256": "symlink:" + os.readlink(e.path)}
                    elif e.is_dir(follow_symlinks=False):
                        stack.append(Path(e.path))
                    elif e.is_file(follow_symlinks=False):
                        if len(files) >= MAX_SCOPE_FILES:
                            truncated = True
                            break
                        size = e.stat(follow_symlinks=False).st_size
                        sha, partial = _sha_file(Path(e.path), size)
                        rel = Path(e.path).relative_to(root).as_posix()
                        entry: dict[str, Any] = {"size": size, "sha256": sha}
                        if partial:
                            entry["hash_truncated"] = True
                        if normalize is not None and size <= NORMALIZE_MAX_BYTES:
                            raw = Path(e.path).read_bytes()
                            norm = normalize(raw)
                            if norm != raw:
                                entry["sha256_normalized"] = hashlib.sha256(norm).hexdigest()
                        files[f"{label}/{rel}"] = entry
                except OSError as exc:
                    if len(errors) < 50:
                        errors.append(f"{label}: {type(exc).__name__}")
            if truncated:
                break
    return {"files": files, "truncated": truncated, "errors": errors}


def capture_file_contents(roots: list[tuple[str, Path]], paths: list[str], remaining: int) -> tuple[dict[str, Any], int]:
    """Captura bytes solo de rutas exactas elegidas en el guion, con límites y sin seguir enlaces."""
    captured: dict[str, Any] = {}
    for key in paths:
        for label, root in roots:
            prefix = label.rstrip("/") + "/"
            if not key.startswith(prefix):
                continue
            rel = key[len(prefix):]
            if not rel or any(part in ("", ".", "..") for part in rel.split("/")):
                captured[key] = {"status": "invalid_path"}
                break
            path = root.joinpath(*rel.split("/"))
            try:
                # Reject links/reparse points in every component. Checking only the leaf would
                # allow sandbox/link/file to read through a directory link outside the scope.
                current = root
                components = rel.split("/")
                blocked = False
                for index, component in enumerate(components):
                    current = current / component
                    link_info = os.lstat(current)
                    reparse = bool(getattr(link_info, "st_file_attributes", 0) &
                                   getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
                    if stat.S_ISLNK(link_info.st_mode) or reparse:
                        captured[key] = {"status": "symlink_not_captured"}
                        blocked = True
                        break
                    if index < len(components) - 1 and not stat.S_ISDIR(link_info.st_mode):
                        captured[key] = {"status": "not_directory"}
                        blocked = True
                        break
                if blocked:
                    break
                flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(path, flags)
                try:
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode):
                        captured[key] = {"status": "not_regular_file"}
                        break
                    if info.st_size > MAX_CAPTURE_FILE_BYTES:
                        captured[key] = {"status": "too_large", "size": info.st_size,
                                         "limit": MAX_CAPTURE_FILE_BYTES}
                        break
                    if info.st_size > remaining:
                        captured[key] = {"status": "session_budget_exceeded", "size": info.st_size,
                                         "remaining": remaining}
                        break
                    chunks = []
                    left = MAX_CAPTURE_FILE_BYTES + 1
                    while left:
                        chunk = os.read(fd, min(left, 64 * 1024))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        left -= len(chunk)
                    data = b"".join(chunks)
                    if len(data) != info.st_size or len(data) > MAX_CAPTURE_FILE_BYTES:
                        captured[key] = {"status": "changed_during_capture"}
                        break
                    captured[key] = {"status": "captured", "size": len(data),
                                     "sha256": hashlib.sha256(data).hexdigest(),
                                     "data_base64": base64.b64encode(data).decode("ascii")}
                    remaining -= len(data)
                finally:
                    os.close(fd)
            except OSError as exc:
                captured[key] = {"status": "unavailable", "reason": type(exc).__name__}
            break
        else:
            captured[key] = {"status": "not_found_in_scope"}
    return captured, remaining


def diff_mapping(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """Cambios entre dos mapas clave → valor: created/modified/deleted, ordenados por clave."""
    out = []
    for k in sorted(set(before) | set(after)):
        if k not in before:
            out.append({"path": k, "change": "created", "after": after[k]})
        elif k not in after:
            out.append({"path": k, "change": "deleted", "before": before[k]})
        elif before[k] != after[k]:
            out.append({"path": k, "change": "modified", "before": before[k], "after": after[k]})
    return out


# -- registro de Windows -------------------------------------------------------------------------------
_HIVES = {"HKCU": "HKEY_CURRENT_USER", "HKEY_CURRENT_USER": "HKEY_CURRENT_USER",
          "HKLM": "HKEY_LOCAL_MACHINE", "HKEY_LOCAL_MACHINE": "HKEY_LOCAL_MACHINE"}


def registry_available() -> bool:
    return sys.platform == "win32"


def parse_registry_key(key: str) -> tuple[str, str]:
    hive, _, sub = key.replace("/", "\\").partition("\\")
    if hive.upper() not in _HIVES or not sub.strip("\\"):
        raise ValueError(f"clave de registro no admitida: {key!r} (usa HKCU\\... o HKLM\\...)")
    return _HIVES[hive.upper()], sub.strip("\\")


def _reg_value(data: Any, typ: int) -> str:
    if isinstance(data, bytes):
        return f"type{typ}:bytes:" + hashlib.sha256(data).hexdigest()
    return f"type{typ}:" + (repr(data) if not isinstance(data, str) else data)[:2000]


def snapshot_registry(keys: list[str]) -> dict[str, Any]:
    """{"values": {"CLAVE\\sub::nombre": "tipo:valor"}, "missing": [...], "truncated": bool}. Solo lectura."""
    if not registry_available():
        return {"values": {}, "missing": [], "truncated": False, "status": "not_available"}
    import winreg

    values: dict[str, str] = {}
    missing: list[str] = []
    truncated = False
    for key in keys:
        hive_name, sub = parse_registry_key(key)
        hive = getattr(winreg, hive_name)
        stack = [sub]
        while stack and not truncated:
            path = stack.pop()
            try:
                h = winreg.OpenKey(hive, path, 0, winreg.KEY_READ)
            except OSError:
                if path == sub:
                    missing.append(key)
                continue
            with h:
                info = winreg.QueryInfoKey(h)
                label = f"{hive_name}\\{path}"
                values[label + "::"] = "key"
                for i in range(info[1]):
                    if len(values) >= MAX_REGISTRY_VALUES:
                        truncated = True
                        break
                    name, data, typ = winreg.EnumValue(h, i)
                    values[f"{label}::{name}"] = _reg_value(data, typ)
                for i in range(info[0]):
                    stack.append(path + "\\" + winreg.EnumKey(h, i))
    return {"values": values, "missing": missing, "truncated": truncated, "status": "observed"}
