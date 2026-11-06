"""Analizador Mach-O (macOS/iOS) con la librería estándar.

Soporta binarios delgados de 32/64 bits (ambos endianness) y universales
(fat/fat64): cada arquitectura se analiza por separado. Usa el mismo lector
con límites que PE/ELF, así que una entrada malformada da ParseError.
"""
from __future__ import annotations

import struct
from typing import Any

from eolfi.providers.binfmt import MAX_NAMES, MAX_SECTIONS, EntropyBudget, ParseError, Reader

MAX_LOAD_COMMANDS = 1024
MAX_FAT_ARCHES = 16

_CPU = {
    7: "x86", 0x01000007: "x86_64", 12: "arm", 0x0100000C: "arm64",
    0x0200000C: "arm64_32", 18: "ppc", 0x01000012: "ppc64",
}
_FILETYPE = {
    1: "object", 2: "execute", 3: "fvmlib", 4: "core", 5: "preload", 6: "dylib",
    7: "dylinker", 8: "bundle", 9: "dylib_stub", 10: "dsym", 11: "kext_bundle", 12: "fileset",
}
_PLATFORM = {1: "macos", 2: "ios", 3: "tvos", 4: "watchos", 5: "bridgeos", 6: "maccatalyst",
             7: "ios_simulator", 8: "tvos_simulator", 9: "watchos_simulator", 10: "driverkit",
             11: "visionos", 12: "visionos_simulator"}

LC_SEGMENT, LC_SEGMENT_64 = 0x1, 0x19
LC_SYMTAB = 0x2
LC_LOAD_DYLIB, LC_ID_DYLIB = 0xC, 0xD
LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB, LC_LAZY_LOAD_DYLIB = 0x80000018, 0x8000001F, 0x20
LC_UUID = 0x1B
LC_RPATH = 0x8000001C
LC_CODE_SIGNATURE = 0x1D
LC_ENCRYPTION_INFO, LC_ENCRYPTION_INFO_64 = 0x21, 0x2C
LC_VERSION_MIN_MACOSX, LC_VERSION_MIN_IPHONEOS = 0x24, 0x25
LC_MAIN = 0x80000028
LC_BUILD_VERSION = 0x32

MH_PIE = 0x200000
MH_ALLOW_STACK_EXECUTION = 0x20000
MH_NO_HEAP_EXECUTION = 0x1000000

THIN_MAGICS = {
    b"\xcf\xfa\xed\xfe": (True, True),    # MH_MAGIC_64, little-endian
    b"\xce\xfa\xed\xfe": (False, True),   # MH_MAGIC, little-endian
    b"\xfe\xed\xfa\xcf": (True, False),   # big-endian 64
    b"\xfe\xed\xfa\xce": (False, False),  # big-endian 32
}


def _ver(v: int) -> str:
    return f"{v >> 16}.{(v >> 8) & 0xFF}.{v & 0xFF}"


def is_macho(head: bytes) -> bool:
    if head[:4] in THIN_MAGICS:
        return True
    if head[:4] in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf") and len(head) >= 8:
        n = struct.unpack(">I", head[4:8])[0]
        return 0 < n < 45      # si no, es una clase Java
    return False


def _lc_str(r: Reader, off: int, cmdsize: int) -> str:
    """Cadena de un load command: su desplazamiento y su longitud deben quedar dentro del comando (B10)."""
    rel = r.u32(off + 8)
    if not 12 <= rel < cmdsize:
        raise ParseError("cadena del comando de carga fuera de su cmdsize")
    return r.cstr(off + rel, min(1024, cmdsize - rel))


def parse_macho(data: bytes) -> dict[str, Any]:
    head = bytes(data[:8])
    if head[:4] in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):
        return _parse_fat(data, is64=head[3] == 0xBF)
    if head[:4] not in THIN_MAGICS:
        raise ParseError("sin firma Mach-O")
    return {"universal": False, "slices": [_parse_thin(data, 0, len(data))]}


def _parse_fat(data: bytes, is64: bool) -> dict[str, Any]:
    r = Reader(data, little=False)
    n = r.u32(4)
    if not 0 < n <= MAX_FAT_ARCHES:
        raise ParseError(f"nfat_arch={n} fuera de rango")
    slices = []
    ent = 32 if is64 else 20
    budget = EntropyBudget(data, r.size)   # UN presupuesto para todas las arquitecturas (M13)
    for i in range(n):
        o = 8 + i * ent
        if is64:
            off, size = r.u64(o + 8), r.u64(o + 16)
        else:
            off, size = r.u32(o + 8), r.u32(o + 12)
        if off + size > r.size or size < 28:
            raise ParseError(f"arquitectura {i} fuera del archivo")
        try:
            slices.append(_parse_thin(data, off, size, budget))
        except ParseError as exc:
            slices.append({"error": str(exc), "offset": off})
    return {"universal": True, "slices": slices}


def _parse_thin(data: bytes, base: int, length: int, ent: EntropyBudget | None = None) -> dict[str, Any]:
    magic = bytes(data[base:base + 4])
    if magic not in THIN_MAGICS:
        raise ParseError("sin firma Mach-O en la arquitectura")
    is64, little = THIN_MAGICS[magic]
    r = Reader(data, little=little)
    ent = ent or EntropyBudget(data, r.size)
    cputype, filetype, ncmds, sizeofcmds, flags = (
        r.u32(base + 4), r.u32(base + 12), r.u32(base + 16), r.u32(base + 20), r.u32(base + 24))
    if ncmds > MAX_LOAD_COMMANDS:
        raise ParseError(f"ncmds={ncmds} excesivo")
    hdr = 32 if is64 else 28
    if hdr + sizeofcmds > length:
        raise ParseError("sizeofcmds supera el tamaño de la arquitectura")

    segments, sections, dylibs, rpaths = [], [], [], []
    uuid = entry = min_os = platform = sdk = id_dylib = None
    code_signature = False
    cs_range = None
    encrypted = None
    symtab = None
    off = base + hdr
    end = off + sizeofcmds
    for _ in range(ncmds):
        if off + 8 > end:
            raise ParseError("comando de carga truncado")
        cmd, cmdsize = r.u32(off), r.u32(off + 4)
        if cmdsize < 8 or off + cmdsize > end:
            raise ParseError(f"cmdsize={cmdsize} inválido")
        need = _MIN_CMDSIZE.get(cmd, 8)
        if cmdsize < need:
            raise ParseError(f"comando {cmd:#x} con cmdsize={cmdsize} menor que su estructura ({need})")
        if cmd in (LC_SEGMENT, LC_SEGMENT_64):
            seg64 = cmd == LC_SEGMENT_64
            name = r.raw(off + 8, 16).rstrip(b"\x00").decode("ascii", "replace")
            if seg64:
                vmaddr, vmsize, fileoff, filesize = r.u64(off + 24), r.u64(off + 32), r.u64(off + 40), r.u64(off + 48)
                initprot, nsects, s_off, s_ent = r.u32(off + 60), r.u32(off + 64), off + 72, 80
            else:
                vmaddr, vmsize, fileoff, filesize = r.u32(off + 24), r.u32(off + 28), r.u32(off + 32), r.u32(off + 36)
                initprot, nsects, s_off, s_ent = r.u32(off + 44), r.u32(off + 48), off + 56, 68
            prot = "".join(f for bit, f in ((1, "r"), (2, "w"), (4, "x")) if initprot & bit)
            segments.append({"name": name, "vmaddr": vmaddr, "vmsize": vmsize,
                             "fileoff": fileoff, "filesize": filesize, "prot": prot})
            hdr = 72 if seg64 else 56
            if nsects * s_ent > cmdsize - (hdr - 0):
                raise ParseError(f"nsects={nsects} no cabe en cmdsize={cmdsize}")
            if len(sections) + nsects > MAX_SECTIONS * 8:
                raise ParseError("demasiadas secciones en total")
            for j in range(min(nsects, MAX_SECTIONS)):
                so = s_off + j * s_ent
                sname = r.raw(so, 16).rstrip(b"\x00").decode("ascii", "replace")
                if seg64:
                    size, foff = r.u64(so + 40), r.u32(so + 48)
                else:
                    size, foff = r.u32(so + 36), r.u32(so + 40)
                entropy = ent.of(base + foff, min(size, length, max(0, length - foff))) if foff else 0.0
                sections.append({"name": f"{name},{sname}", "size": size, "flags": prot, "entropy": entropy})
        elif cmd in (LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB, LC_LAZY_LOAD_DYLIB, LC_ID_DYLIB):
            name = _lc_str(r, off, cmdsize)
            if cmd == LC_ID_DYLIB:
                id_dylib = name
            else:
                kind = {LC_LOAD_WEAK_DYLIB: "weak", LC_REEXPORT_DYLIB: "reexport",
                        LC_LAZY_LOAD_DYLIB: "lazy"}.get(cmd, "load")
                dylibs.append({"name": name, "kind": kind, "current_version": _ver(r.u32(off + 16))})
        elif cmd == LC_RPATH:
            rpaths.append(_lc_str(r, off, cmdsize))
        elif cmd == LC_UUID:
            uuid = r.raw(off + 8, 16).hex()
        elif cmd == LC_MAIN:
            entry = r.u64(off + 8)
        elif cmd == LC_CODE_SIGNATURE:
            code_signature = True
            if cmdsize >= 16:
                cs_range = (base + r.u32(off + 8), r.u32(off + 12))   # dataoff es relativo a la arquitectura
        elif cmd in (LC_ENCRYPTION_INFO, LC_ENCRYPTION_INFO_64):
            encrypted = r.u32(off + 16) != 0
        elif cmd == LC_BUILD_VERSION:
            p = r.u32(off + 8)
            platform, min_os, sdk = _PLATFORM.get(p, str(p)), _ver(r.u32(off + 12)), _ver(r.u32(off + 16))
        elif cmd in (LC_VERSION_MIN_MACOSX, LC_VERSION_MIN_IPHONEOS) and platform is None:
            platform = "macos" if cmd == LC_VERSION_MIN_MACOSX else "ios"
            min_os, sdk = _ver(r.u32(off + 8)), _ver(r.u32(off + 12))
        elif cmd == LC_SYMTAB:
            symtab = (r.u32(off + 8), r.u32(off + 12), r.u32(off + 16), r.u32(off + 20))
        off += cmdsize

    imported: list[str] = []
    sym_errors: list[str] = []
    if symtab:
        symoff, nsyms, stroff, strsize = symtab
        ent = 16 if is64 else 12
        try:
            for i in range(min(nsyms, MAX_NAMES * 4)):
                so = base + symoff + i * ent
                strx, ntype = r.u32(so), r.u8(so + 4)
                if (ntype & 0xE0) == 0 and (ntype & 0x0E) == 0 and (ntype & 0x01) and strx < strsize:
                    imported.append(r.cstr(base + stroff + strx, 256))
                    if len(imported) >= MAX_NAMES:
                        break
        except ParseError as exc:
            sym_errors.append(str(exc))

    return {
        "headers": {
            "cpu": _CPU.get(cputype, f"{cputype:#x}"),
            "cpusubtype": r.u32(base + 8) & 0x00FFFFFF,
            "bits": 64 if is64 else 32,
            "endianness": "little" if little else "big",
            "filetype": _FILETYPE.get(filetype, str(filetype)),
            "number_of_load_commands": ncmds,
            "entry_offset": entry,
            "uuid": uuid,
            "platform": platform,
            "min_os": min_os,
            "sdk": sdk,
            "install_name": id_dylib,
            "offset": base,
        },
        "segments": segments,
        "sections": sections,
        "dylibs": dylibs,
        "rpaths": rpaths,
        "imported_symbols": imported,
        "symbol_errors": sym_errors,
        "security": {
            # Ejecutables: flag MH_PIE. dylib/bundle siempre son reubicables ("dso").
            "pie": bool(flags & MH_PIE) if filetype == 2 else ("dso" if filetype in (6, 8) else False),
            "stack_executable": bool(flags & MH_ALLOW_STACK_EXECUTION),
            "heap_nx": bool(flags & MH_NO_HEAP_EXECUTION),
            "code_signature": code_signature,
            "code_signature_range": cs_range,
            "encrypted": encrypted,
            "stack_canary": "___stack_chk_fail" in imported or "___stack_chk_guard" in imported,
            "arc": any(s in imported for s in ("_objc_release", "_objc_retain", "_swift_release")),
            "swift": any(s.startswith("_swift_") for s in imported),
        },
    }


# Tamaño mínimo de cada load command que se lee (B10): uno más corto leería el comando siguiente.
_MIN_CMDSIZE = {
    LC_UUID: 24, LC_MAIN: 24, LC_RPATH: 12, LC_BUILD_VERSION: 24,
    LC_VERSION_MIN_MACOSX: 16, LC_VERSION_MIN_IPHONEOS: 16,
    LC_ENCRYPTION_INFO: 20, LC_ENCRYPTION_INFO_64: 24,
    LC_LOAD_DYLIB: 24, LC_LOAD_WEAK_DYLIB: 24, LC_REEXPORT_DYLIB: 24, LC_LAZY_LOAD_DYLIB: 24, LC_ID_DYLIB: 24,
    LC_SEGMENT: 56, LC_SEGMENT_64: 72,
}
