"""Triaje estático con la librería estándar: hash, tamaño y formato por magia."""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import Any

from eolfi.providers.base import Provider

# Orden: de la firma más específica a la más genérica.
_MAGIC = [
    (b"\x7fELF", "elf", "Binario nativo ELF (Linux/Unix)"),
    (b"MZ", "pe", "Ejecutable PE/COFF o DOS (Windows)"),
    (b"\xcf\xfa\xed\xfe", "macho64", "Mach-O 64-bit"),
    (b"\xce\xfa\xed\xfe", "macho32", "Mach-O 32-bit"),
    (b"\xfe\xed\xfa\xcf", "macho64", "Mach-O 64-bit (big-endian)"),
    (b"\xfe\xed\xfa\xce", "macho32", "Mach-O 32-bit (big-endian, PowerPC)"),
    (b"PK\x03\x04", "zip", "Contenedor ZIP (APK/JAR/IPA posible)"),
    (b"dex\n", "dex", "Dalvik DEX (Android)"),
    (b"\x00asm", "wasm", "WebAssembly"),
    (b"!<arch>\n", "ar", "Archivo ar/.a o .deb"),
    (b"\x1f\x8b", "gzip", "Gzip"),
]

_HEAD = 64
_TAIL = 4096


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read_head_tail(path: str | Path, head: int = _HEAD, tail: int = _TAIL) -> tuple[bytes, bytes]:
    """Lee solo el principio y el final (no carga el archivo entero)."""
    p = Path(path)
    size = p.stat().st_size
    with open(p, "rb") as fh:
        h = fh.read(head)
        fh.seek(max(0, size - tail))
        t = fh.read(tail)
    return h, t


def detect_format(head: bytes) -> tuple[str, str]:
    # 0xCAFEBABE es ambiguo: Mach-O universal o clase Java. Se distingue por
    # el siguiente u32 big-endian: nº de arquitecturas (pequeño) frente a
    # versión de clase Java (minor<<16 | major, con major >= 45).
    if head.startswith(b"\xca\xfe\xba\xbf") and len(head) >= 8:
        nxt = struct.unpack(">I", head[4:8])[0]
        if 0 < nxt < 45:
            return "macho_fat", "Mach-O universal (fat64)"
    if head.startswith(b"\xca\xfe\xba\xbe") and len(head) >= 8:
        nxt = struct.unpack(">I", head[4:8])[0]
        if 0 < nxt < 45:
            return "macho_fat", "Mach-O universal (fat)"
        return "java_class", f"Clase Java (major {nxt & 0xFFFF})"
    for magic, name, desc in _MAGIC:
        if head.startswith(magic):
            return name, desc
    return "unknown", "Formato no reconocido por magia"


class FileTriageProvider(Provider):
    name = "eolfi.triage"
    version = "0.2.0"

    def available(self) -> bool:
        return True

    def run(self, target: str) -> list[dict[str, Any]]:
        p = Path(target)
        size = p.stat().st_size
        head, tail = read_head_tail(p)
        fmt, desc = detect_format(head)
        pyinstaller = b"pyi-" in tail or b"PyInstaller" in tail or b"MEI\x0c\x0b\x0a\x0b\x0e" in tail
        return [
            {
                "operation": "hash",
                "result": {"sha256": sha256_file(p), "size": size},
                "authority": "distributed_artifact",
                "confidence": "high",
                "limitations": "",
            },
            {
                "operation": "detect_format",
                "result": {"format": fmt, "description": desc},
                "authority": "distributed_artifact",
                "confidence": "high" if fmt != "unknown" else "low",
                "limitations": "Detección solo por bytes mágicos iniciales.",
            },
            {
                "operation": "detect_pyinstaller",
                "result": {"pyinstaller": bool(pyinstaller)},
                "authority": "analyst_inference",
                "confidence": "medium" if pyinstaller else "low",
                "limitations": "Heurística por cookie/cadenas en la cola del archivo.",
            },
        ]
