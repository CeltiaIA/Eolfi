"""Analizadores PE y ELF con la librería estándar.

Leen cabeceras, secciones, importaciones/exportaciones, mitigaciones de
seguridad y entropía, y devuelven cada bloque como un hallazgo separado.
Todo acceso a bytes pasa por un lector con límites: una entrada malformada
produce un ParseError (registrado como evidencia de baja confianza), nunca
un crash ni una lectura fuera de rango.
"""
from __future__ import annotations

import math
import mmap
import struct
from collections import Counter
from pathlib import Path
from typing import Any

from eolfi.providers.base import Provider

MAX_SECTIONS = 96          # límite del cargador de Windows; también para ELF
MAX_IMPORT_DLLS = 256
MAX_FUNCS_PER_DLL = 2048
MAX_NAMES = 4096
MAX_IMPORTS_TOTAL = 20_000
HIGH_ENTROPY = 7.2


class ParseError(ValueError):
    """Estructura fuera de rango o incoherente."""


class ParseBudget:
    """Presupuesto común de un análisis (bytes leídos y tiempo): cualquier parser que use Reader lo
    respeta sin tener que pasar parámetros. Cada parser conserva además sus topes propios; este es la red
    de seguridad para lo que esos topes no prevén (estructuras repetidas, solapadas, cadenas enormes…)."""

    def __init__(self, max_bytes: int, seconds: float):
        import time as _time

        self.left = max_bytes
        self.deadline = _time.monotonic() + seconds
        self.calls = 0
        self._now = _time.monotonic

    def charge(self, n: int) -> None:
        self.left -= n
        if self.left < 0:
            raise ParseError("presupuesto de lectura agotado: estructura anómala o manipulada")
        self.calls += 1
        if not self.calls & 0x3FF and self._now() > self.deadline:   # el reloj, cada 1024 lecturas
            raise ParseError("presupuesto de tiempo agotado: estructura anómala o manipulada")


import contextvars as _contextvars  # noqa: E402

_BUDGET = _contextvars.ContextVar("eolfi_parse_budget", default=None)


class parse_budget:  # noqa: N801 — se usa como «with parse_budget(...)»
    """with parse_budget(max_bytes=…, seconds=…): todo Reader dentro del bloque comparte el presupuesto."""

    def __init__(self, max_bytes: int, seconds: float):
        self.budget = ParseBudget(max_bytes, seconds)

    def __enter__(self) -> ParseBudget:
        self._token = _BUDGET.set(self.budget)
        return self.budget

    def __exit__(self, *exc) -> None:
        _BUDGET.reset(self._token)


class Reader:
    """Acceso con comprobación de límites a un buffer de bytes."""

    def __init__(self, data: bytes | mmap.mmap, little: bool = True):
        self.data = data
        self.size = len(data)
        self.e = "<" if little else ">"

    def raw(self, off: int, n: int) -> bytes:
        if off < 0 or n < 0 or off + n > self.size:
            raise ParseError(f"lectura fuera de rango: off={off:#x} n={n}")
        b = _BUDGET.get()
        if b is not None:
            b.charge(n)
        return bytes(self.data[off:off + n])

    def _unpack(self, fmt: str, off: int) -> int:
        n = struct.calcsize(fmt)
        return struct.unpack(self.e + fmt, self.raw(off, n))[0]

    def u8(self, off: int) -> int:
        return self._unpack("B", off)

    def u16(self, off: int) -> int:
        return self._unpack("H", off)

    def u32(self, off: int) -> int:
        return self._unpack("I", off)

    def u64(self, off: int) -> int:
        return self._unpack("Q", off)

    def cstr(self, off: int, maxlen: int = 512) -> str:
        if off < 0 or off >= self.size:
            raise ParseError(f"cadena fuera de rango: off={off:#x}")
        end = min(self.size, off + maxlen)
        b = _BUDGET.get()
        if b is not None:
            b.charge(end - off)
        chunk = bytes(self.data[off:end])
        nul = chunk.find(b"\x00")
        if nul >= 0:
            chunk = chunk[:nul]
        return chunk.decode("ascii", "replace")


def shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    n = len(data)
    return -sum(c / n * math.log2(c / n) for c in Counter(data).values())


class EntropyBudget:
    """Entropía por sección con caché y presupuesto: secciones repetidas o solapadas que apuntan
    a todo el archivo no pueden convertir 1 MB en horas de CPU. Agotado el presupuesto, None."""

    def __init__(self, data, file_size: int):
        self.data, self.size = data, file_size
        self.left = 2 * file_size + 16 * 1024 * 1024
        self.cache: dict[tuple[int, int], float] = {}
        self.exhausted = False

    def of(self, off: int, length: int) -> float | None:
        if off < 0 or off >= self.size or length <= 0:
            return 0.0
        length = min(length, self.size - off)
        key = (off, length)
        if key in self.cache:
            return self.cache[key]
        if length > self.left:
            self.exhausted = True
            return None
        self.left -= length
        value = round(shannon_entropy(bytes(self.data[off:off + length])), 3)
        self.cache[key] = value
        return value


# ---------------------------------------------------------------------------
# PE
# ---------------------------------------------------------------------------
_PE_MACHINE = {
    0x14C: "i386", 0x8664: "amd64", 0x1C0: "arm", 0x1C4: "armnt",
    0xAA64: "arm64", 0x200: "ia64", 0xEBC: "efi_bytecode",
}
_PE_SUBSYSTEM = {
    1: "native", 2: "windows_gui", 3: "windows_cui", 7: "posix_cui",
    9: "windows_ce_gui", 10: "efi_application", 11: "efi_boot_driver",
    12: "efi_runtime_driver", 14: "xbox", 16: "windows_boot_app",
}
_PACKER_SECTIONS = {
    "UPX0": "UPX", "UPX1": "UPX", "UPX2": "UPX", ".aspack": "ASPack",
    ".adata": "ASPack", ".MPRESS1": "MPRESS", ".MPRESS2": "MPRESS",
    ".themida": "Themida", ".vmp0": "VMProtect", ".vmp1": "VMProtect",
    ".petite": "Petite", ".nsp0": "NsPack", ".enigma1": "Enigma",
}


def parse_pe(data: bytes | mmap.mmap) -> dict[str, Any]:
    r = Reader(data)
    ent = EntropyBudget(data, r.size)
    if r.raw(0, 2) != b"MZ":
        raise ParseError("sin firma MZ")
    pe_off = r.u32(0x3C)
    if r.raw(pe_off, 4) != b"PE\x00\x00":
        raise ParseError("sin firma PE (posible ejecutable DOS)")
    coff = pe_off + 4
    machine = r.u16(coff)
    nsect = r.u16(coff + 2)
    timestamp = r.u32(coff + 4)
    opt_size = r.u16(coff + 16)
    chars = r.u16(coff + 18)
    opt = coff + 20
    magic = r.u16(opt)
    if magic == 0x10B:
        pe32plus = False
        image_base = r.u32(opt + 28)
        n_dirs_off, dirs_off = opt + 92, opt + 96
    elif magic == 0x20B:
        pe32plus = True
        image_base = r.u64(opt + 24)
        n_dirs_off, dirs_off = opt + 108, opt + 112
    else:
        raise ParseError(f"OptionalHeader.Magic desconocido {magic:#x}")
    entry = r.u32(opt + 16)
    size_of_headers = r.u32(opt + 60)
    subsystem = r.u16(opt + 68)
    dll_chars = r.u16(opt + 70)
    n_dirs = min(r.u32(n_dirs_off), 16)
    dirs = []
    for i in range(n_dirs):
        dirs.append((r.u32(dirs_off + i * 8), r.u32(dirs_off + i * 8 + 4)))
    while len(dirs) < 16:
        dirs.append((0, 0))

    if nsect > MAX_SECTIONS:
        raise ParseError(f"NumberOfSections={nsect} supera {MAX_SECTIONS}")
    sect_off = opt + opt_size
    sections = []
    for i in range(nsect):
        s = sect_off + i * 40
        name = r.raw(s, 8).rstrip(b"\x00").decode("ascii", "replace")
        vsize, va, rsize, rptr = (r.u32(s + 8), r.u32(s + 12), r.u32(s + 16), r.u32(s + 20))
        sch = r.u32(s + 36)
        sections.append({
            "name": name, "virtual_address": va, "virtual_size": vsize,
            "raw_offset": rptr, "raw_size": rsize,
            "flags": "".join(f for bit, f in ((0x40000000, "r"), (0x80000000, "w"), (0x20000000, "x")) if sch & bit),
            "entropy": ent.of(rptr, rsize),
        })

    rva_cache: dict[int, int] = {}

    def rva_to_off(rva: int) -> int:
        hit = rva_cache.get(rva)
        if hit is not None:
            return hit
        off = _rva_to_off(rva)
        if len(rva_cache) < 65536:
            rva_cache[rva] = off
        return off

    def _rva_to_off(rva: int) -> int:
        for sec in sections:
            span = max(sec["virtual_size"], sec["raw_size"])
            if sec["virtual_address"] <= rva < sec["virtual_address"] + span:
                off = rva - sec["virtual_address"] + sec["raw_offset"]
                if off >= r.size:
                    raise ParseError(f"RVA {rva:#x} apunta fuera del archivo")
                return off
        if rva < size_of_headers:
            return rva
        raise ParseError(f"RVA {rva:#x} sin sección")

    entry_section = next(
        (s["name"] for s in sections
         if s["virtual_address"] <= entry < s["virtual_address"] + max(s["virtual_size"], s["raw_size"])),
        None,
    )

    # Importaciones
    imports: dict[str, list[str]] = {}
    imp_errors: list[str] = []
    imp_rva = dirs[1][0]
    if imp_rva:
        try:
            desc = rva_to_off(imp_rva)
            ord_flag = 1 << 63 if pe32plus else 1 << 31
            # Tope TOTAL de nombres y tablas compartidas leídas una sola vez: 256 descriptores apuntando a
            # la misma tabla daban 366 000 nombres (M15).
            seen_tables: set[int] = set()
            total = 0
            for i in range(MAX_IMPORT_DLLS):
                d = desc + i * 20
                oft, name_rva, ft = r.u32(d), r.u32(d + 12), r.u32(d + 16)
                if not (oft or name_rva or ft):
                    break
                dll = r.cstr(rva_to_off(name_rva), 256)
                funcs: list[str] = []
                t = rva_to_off(oft or ft)
                if t in seen_tables:
                    imports.setdefault(dll, [])
                    imp_errors.append(f"{dll}: comparte la tabla de importación con otra DLL (estructura anómala)")
                    continue
                seen_tables.add(t)
                if total >= MAX_IMPORTS_TOTAL:
                    imp_errors.append(f"tope de {MAX_IMPORTS_TOTAL} funciones importadas alcanzado")
                    break
                for j in range(min(MAX_FUNCS_PER_DLL, MAX_IMPORTS_TOTAL - total)):
                    v = r.u64(t + j * 8) if pe32plus else r.u32(t + j * 4)
                    if v == 0:
                        break
                    if v & ord_flag:
                        funcs.append(f"#{v & 0xFFFF}")
                    else:
                        funcs.append(r.cstr(rva_to_off(v & 0x7FFFFFFF) + 2, 256))
                total += len(funcs)
                bucket = imports.setdefault(dll, [])
                seen = set(bucket)
                bucket.extend(f for f in dict.fromkeys(funcs) if f not in seen)
        except ParseError as exc:
            imp_errors.append(str(exc))

    # Exportaciones
    exports: list[str] = []
    dll_name = None
    exp_errors: list[str] = []
    exp_rva = dirs[0][0]
    if exp_rva:
        try:
            e = rva_to_off(exp_rva)
            dll_name = r.cstr(rva_to_off(r.u32(e + 12)), 256)
            n_names = min(r.u32(e + 24), MAX_NAMES)
            names_tbl = rva_to_off(r.u32(e + 32)) if n_names else 0
            for i in range(n_names):
                exports.append(r.cstr(rva_to_off(r.u32(names_tbl + i * 4)), 256))
        except ParseError as exc:
            exp_errors.append(str(exc))

    raw_end = max((s["raw_offset"] + s["raw_size"] for s in sections), default=size_of_headers)
    cert_off, cert_size = dirs[4]   # en el directorio de seguridad es offset, no RVA
    overlay = max(0, r.size - raw_end)
    if cert_off and cert_off >= raw_end:
        overlay = max(0, overlay - cert_size)

    return {
        "headers": {
            "machine": _PE_MACHINE.get(machine, f"{machine:#x}"),
            "pe32plus": pe32plus,
            "is_dll": bool(chars & 0x2000),
            "subsystem": _PE_SUBSYSTEM.get(subsystem, str(subsystem)),
            "timestamp": timestamp,
            "image_base": image_base,
            "entry_point_rva": entry,
            "entry_section": entry_section,
            "number_of_sections": nsect,
            "dotnet": dirs[14][0] != 0,
        },
        "sections": sections,
        "imports": {"dlls": imports, "errors": imp_errors},
        "exports": {"dll_name": dll_name, "names": exports, "errors": exp_errors},
        "security": {
            # DYNAMIC_BASE sin relocalizaciones (RELOCS_STRIPPED o sin directorio .reloc) no se reubica:
            # el cargador lo deja en su base fija, así que no hay ASLR efectivo (B16).
            "aslr": bool(dll_chars & 0x40) and not (chars & 0x0001) and dirs[5][0] != 0,
            "aslr_flag": bool(dll_chars & 0x40),
            "high_entropy_va": bool(dll_chars & 0x20),
            "dep_nx": bool(dll_chars & 0x100),
            "cfg": bool(dll_chars & 0x4000),
            "no_seh": bool(dll_chars & 0x400),
            "authenticode_present": bool(cert_off and cert_size),
        },
        "overlay_size": overlay,
        # Interno (no se emite como evidencia): lo usan los análisis de pe_extra.
        "_layout": {"dirs": dirs, "checksum_off": opt + 64, "certdir_off": dirs_off + 4 * 8, "pe_off": pe_off,
                    "size_of_headers": size_of_headers, "pe32plus": pe32plus, "image_base": image_base},
    }


# ---------------------------------------------------------------------------
# ELF
# ---------------------------------------------------------------------------
_ELF_MACHINE = {
    3: "x86", 62: "x86_64", 40: "arm", 183: "aarch64", 243: "riscv",
    8: "mips", 20: "ppc", 21: "ppc64", 2: "sparc", 43: "sparcv9", 22: "s390",
}
_ELF_TYPE = {0: "none", 1: "rel", 2: "exec", 3: "dyn", 4: "core"}
PT_DYNAMIC, PT_INTERP, PT_GNU_STACK, PT_GNU_RELRO = 2, 3, 0x6474E551, 0x6474E552
SHT_SYMTAB, SHT_DYNAMIC, SHT_DYNSYM = 2, 6, 11
DT_NEEDED, DT_SONAME, DT_RPATH, DT_BIND_NOW, DT_RUNPATH, DT_FLAGS = 1, 14, 15, 24, 29, 30
DT_FLAGS_1 = 0x6FFFFFFB


def _gnu_build_id(r: Reader, off: int, size: int) -> str | None:
    end = off + min(size, 64 * 1024)
    while off + 12 <= end:
        namesz, descsz, ntype = r.u32(off), r.u32(off + 4), r.u32(off + 8)
        name_end = off + 12 + ((namesz + 3) & ~3)
        if name_end + descsz > end:
            return None
        if ntype == 3 and r.raw(off + 12, min(namesz, 4)) == b"GNU\x00":
            return r.raw(name_end, min(descsz, 64)).hex()
        off = name_end + ((descsz + 3) & ~3)
    return None


def parse_elf(data: bytes | mmap.mmap) -> dict[str, Any]:
    probe = Reader(data)
    if probe.raw(0, 4) != b"\x7fELF":
        raise ParseError("sin firma ELF")
    cls, endian = probe.u8(4), probe.u8(5)
    if cls not in (1, 2) or endian not in (1, 2):
        raise ParseError(f"EI_CLASS={cls} EI_DATA={endian} no válidos")
    is64 = cls == 2
    r = Reader(data, little=endian == 1)
    ent = EntropyBudget(data, r.size)
    addr = r.u64 if is64 else r.u32
    e_type, e_machine = r.u16(16), r.u16(18)
    if is64:
        entry, phoff, shoff = r.u64(24), r.u64(32), r.u64(40)
        phentsize, phnum, shentsize, shnum, shstrndx = (r.u16(54), r.u16(56), r.u16(58), r.u16(60), r.u16(62))
    else:
        entry, phoff, shoff = r.u32(24), r.u32(28), r.u32(32)
        phentsize, phnum, shentsize, shnum, shstrndx = (r.u16(42), r.u16(44), r.u16(46), r.u16(48), r.u16(50))

    # Segmentos
    segments = []
    build_id = None
    interp = None
    nx = None
    relro = False
    dyn_seg = None
    if phnum and phentsize < (56 if is64 else 32):
        raise ParseError(f"e_phentsize={phentsize} demasiado pequeño")
    for i in range(min(phnum, 512)):
        p = phoff + i * phentsize
        p_type = r.u32(p)
        if is64:
            p_flags, p_off, p_vaddr, p_filesz = r.u32(p + 4), r.u64(p + 8), r.u64(p + 16), r.u64(p + 32)
            p_align = r.u64(p + 48)
        else:
            p_off, p_vaddr, p_filesz, p_flags = r.u32(p + 4), r.u32(p + 8), r.u32(p + 16), r.u32(p + 24)
            p_align = r.u32(p + 28)
        segments.append({"type": p_type, "offset": p_off, "vaddr": p_vaddr, "filesz": p_filesz, "flags": p_flags,
                         "align": p_align})
        if p_type == 4 and build_id is None:   # PT_NOTE: NT_GNU_BUILD_ID
            build_id = _gnu_build_id(r, p_off, p_filesz)
        if p_type == PT_INTERP:
            interp = r.cstr(p_off, min(p_filesz, 4096) or 1)
        elif p_type == PT_GNU_STACK:
            nx = not (p_flags & 1)
        elif p_type == PT_GNU_RELRO:
            relro = True
        elif p_type == PT_DYNAMIC:
            dyn_seg = (p_off, p_filesz)

    # Secciones
    sections = []
    shdrs = []
    if shnum and shoff:
        if shnum > MAX_SECTIONS * 4:
            raise ParseError(f"e_shnum={shnum} excesivo")
        if shentsize < (64 if is64 else 40):
            raise ParseError(f"e_shentsize={shentsize} demasiado pequeño")
        for i in range(shnum):
            s = shoff + i * shentsize
            if is64:
                sh = dict(name=r.u32(s), type=r.u32(s + 4), flags=r.u64(s + 8), addr=r.u64(s + 16),
                          offset=r.u64(s + 24), size=r.u64(s + 32), link=r.u32(s + 40), entsize=r.u64(s + 56))
            else:
                sh = dict(name=r.u32(s), type=r.u32(s + 4), flags=r.u32(s + 8), addr=r.u32(s + 12),
                          offset=r.u32(s + 16), size=r.u32(s + 20), link=r.u32(s + 24), entsize=r.u32(s + 36))
            shdrs.append(sh)
        strtab_off = shdrs[shstrndx]["offset"] if shstrndx < len(shdrs) else None
        for sh in shdrs:
            try:
                nm = r.cstr(strtab_off + sh["name"], 128) if strtab_off is not None else ""
            except ParseError:
                nm = "?"
            sh["sname"] = nm
            sections.append({
                "name": nm, "type": sh["type"], "address": sh["addr"], "offset": sh["offset"],
                "size": sh["size"],
                "flags": "".join(f for bit, f in ((2, "a"), (1, "w"), (4, "x")) if sh["flags"] & bit),
                "entropy": 0.0 if sh["type"] == 8 else ent.of(sh["offset"], sh["size"]),   # 8 = SHT_NOBITS
            })
    stripped = bool(shdrs) and not any(sh["type"] == SHT_SYMTAB for sh in shdrs)

    # Dinámico: bibliotecas necesarias y flags de enlazado
    needed: list[str] = []
    soname = runpath = None
    bind_now = False
    pie_flag = False
    dyn_errors: list[str] = []
    dyn_sh = next((sh for sh in shdrs if sh["type"] == SHT_DYNAMIC), None)
    try:
        if dyn_sh is not None and dyn_sh["link"] < len(shdrs):
            d_off, d_size = dyn_sh["offset"], dyn_sh["size"]
            dynstr = shdrs[dyn_sh["link"]]["offset"]
        elif dyn_seg is not None:
            d_off, d_size = dyn_seg
            dynstr = None
        else:
            d_off = d_size = 0
            dynstr = None
        ent = 16 if is64 else 8
        pending_strs: list[tuple[int, int]] = []
        strtab_vaddr = None
        for i in range(min(d_size // ent, 4096)):
            o = d_off + i * ent
            tag, val = addr(o), addr(o + ent // 2)
            if tag == 0:
                break
            if tag in (DT_NEEDED, DT_SONAME, DT_RPATH, DT_RUNPATH):
                pending_strs.append((tag, val))
            elif tag == 5:   # DT_STRTAB
                strtab_vaddr = val
            elif tag == DT_BIND_NOW:
                bind_now = True
            elif tag == DT_FLAGS and val & 0x8:
                bind_now = True
            elif tag == DT_FLAGS_1:
                bind_now = bind_now or bool(val & 0x1)
                pie_flag = bool(val & 0x08000000)
        if dynstr is None and strtab_vaddr is not None:
            for seg in segments:
                if seg["type"] == 1 and seg["vaddr"] <= strtab_vaddr < seg["vaddr"] + seg["filesz"]:
                    dynstr = strtab_vaddr - seg["vaddr"] + seg["offset"]
                    break
        if dynstr is not None:
            for tag, val in pending_strs:
                sv = r.cstr(dynstr + val, 512)
                if tag == DT_NEEDED:
                    needed.append(sv)
                elif tag == DT_SONAME:
                    soname = sv
                else:
                    runpath = sv
    except ParseError as exc:
        dyn_errors.append(str(exc))

    # Símbolos dinámicos importados (no definidos)
    imported: list[str] = []
    exported: list[str] = []
    dynsym = next((sh for sh in shdrs if sh["type"] == SHT_DYNSYM), None)
    if dynsym is not None and dynsym["link"] < len(shdrs):
        try:
            symstr = shdrs[dynsym["link"]]["offset"]
            ent = 24 if is64 else 16
            for i in range(1, min(dynsym["size"] // ent, MAX_NAMES)):
                s = dynsym["offset"] + i * ent
                st_name = r.u32(s)
                shndx = r.u16(s + 6) if is64 else r.u16(s + 14)
                if not st_name:
                    continue
                name = r.cstr(symstr + st_name, 256)
                (imported if shndx == 0 else exported).append(name)
        except ParseError as exc:
            dyn_errors.append(str(exc))

    # PIE: ejecutable ET_DYN con intérprete (o DF_1_PIE). Un ET_DYN sin
    # intérprete es una biblioteca compartida: siempre reubicable ("dso").
    if e_type == 3:
        pie: bool | str = True if (interp is not None or pie_flag) else "dso"
    else:
        pie = False
    return {
        "headers": {
            "class": 64 if is64 else 32,
            "endianness": "little" if endian == 1 else "big",
            "osabi": probe.u8(7),
            "type": _ELF_TYPE.get(e_type, str(e_type)),
            "machine": _ELF_MACHINE.get(e_machine, str(e_machine)),
            "entry_point": entry,
            "interpreter": interp,
            "number_of_sections": len(sections),
            "number_of_segments": len(segments),
            "build_id": build_id,
            # Alineación mínima de los PT_LOAD: Android 15+ exige 16 KB (0x4000) en arm64-v8a y x86_64.
            "load_alignment": min((s["align"] for s in segments if s["type"] == 1), default=None),
        },
        "sections": sections,
        "dynamic": {
            "needed": needed, "soname": soname, "runpath": runpath,
            "imported_symbols": imported[:MAX_NAMES], "exported_symbols": exported[:MAX_NAMES],
            "errors": dyn_errors,
        },
        "security": {
            "nx": nx,                       # None = sin PT_GNU_STACK (pila ejecutable por defecto)
            "pie": pie,
            "relro": ("full" if relro and bind_now else "partial") if relro else "none",
            "stack_canary": "__stack_chk_fail" in imported,
            "fortify": any(n.endswith("_chk") and n.startswith("__") for n in imported),
            "stripped": stripped,
        },
    }


# ---------------------------------------------------------------------------
# Proveedor
# ---------------------------------------------------------------------------
def _packing_signals(sections: list[dict[str, Any]], file_entropy: float, imports_count: int | None) -> dict[str, Any]:
    signals = []
    packer = None
    for s in sections:
        if s["name"] in _PACKER_SECTIONS:
            packer = _PACKER_SECTIONS[s["name"]]
            signals.append(f"sección '{s['name']}' típica de {packer}")
        if (s["entropy"] or 0.0) >= HIGH_ENTROPY and s.get("raw_size", s.get("size", 0)) > 512:
            signals.append(f"sección '{s['name']}' con entropía {s['entropy']}")
        if "w" in s["flags"] and "x" in s["flags"]:
            signals.append(f"sección '{s['name']}' escribible y ejecutable")
    if file_entropy >= HIGH_ENTROPY:
        signals.append(f"entropía global {file_entropy}")
    if imports_count is not None and imports_count <= 3:
        signals.append(f"solo {imports_count} importaciones (típico de stub de empaquetador)")
    return {"likely_packed": bool(packer) or len(signals) >= 2, "packer_hint": packer, "signals": signals}


class BinaryFormatProvider(Provider):
    """Parser estructural PE/ELF/Mach-O. Devuelve [] para otros formatos."""
    name = "eolfi.binfmt"
    version = "0.3.0"   # Fase E: Authenticode, imphash, Rich, TLS, VERSIONINFO, .NET y WebAssembly
    max_size = 512 * 1024 * 1024

    def available(self) -> bool:
        return True

    def run(self, target: str) -> list[dict[str, Any]]:
        p = Path(target)
        size = p.stat().st_size
        if size == 0:
            return []
        with open(p, "rb") as fh:
            head = fh.read(8)
        magic = head[:4]
        from eolfi.providers.macho import is_macho, parse_macho

        if magic == b"\x00asm":
            return self._wasm(p, size)
        if magic.startswith(b"MZ"):
            kind, parser = "pe", parse_pe
        elif magic == b"\x7fELF":
            kind, parser = "elf", parse_elf
        elif is_macho(head):
            kind, parser = "macho", parse_macho
        else:
            return []
        if size > self.max_size:
            return [self._fail(kind, f"archivo de {size} bytes supera el límite de análisis")]
        with open(p, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            try:
                info = parser(mm)
            except ParseError as exc:
                return [self._fail(kind, str(exc))]
            file_entropy = round(shannon_entropy(mm[:]), 3) if size <= 64 * 1024 * 1024 else None
            extra: list[dict[str, Any]] = []
            if kind == "pe":
                extra = self._pe_extra(mm, info)

        art = "distributed_artifact"
        if kind == "macho":
            return self._macho_findings(info, file_entropy)
        out = [
            self._f(f"{kind}_headers", info["headers"], art, "high", "Campos leídos de las cabeceras."),
            self._f(f"{kind}_sections", info["sections"], art, "high",
                    "Entropía calculada sobre bytes en disco, no en memoria."),
            self._f(f"{kind}_security", info["security"], art, "high",
                    "Flags declarados en el binario; el SO puede imponer otra política."),
        ]
        if kind == "pe":
            imp = info["imports"]
            out.append(self._f("pe_imports", imp, art, "high" if not imp["errors"] else "medium",
                               "Solo importaciones estáticas; no ve carga dinámica (LoadLibrary/GetProcAddress)."))
            if info["exports"]["names"] or info["exports"]["errors"]:
                out.append(self._f("pe_exports", info["exports"], art, "high", ""))
            out.append(self._f("pe_overlay", {"overlay_size": info["overlay_size"]}, art, "high",
                               "Bytes tras la última sección, excluyendo la firma Authenticode."))
            out.extend(extra)
            n_imports = sum(len(v) for v in imp["dlls"].values())
        else:
            dyn = info["dynamic"]
            out.append(self._f("elf_dynamic", dyn, art, "high" if not dyn["errors"] else "medium",
                               "Solo dependencias declaradas; no ve dlopen() en runtime."))
            n_imports = len(dyn["imported_symbols"]) if info["headers"]["interpreter"] else None
        out.append(self._f("entropy", {"file": file_entropy}, art, "high",
                           "" if file_entropy is not None else "Archivo grande: entropía global omitida."))
        out.append(self._f("packing_signals",
                           _packing_signals(info["sections"], file_entropy or 0.0, n_imports),
                           "analyst_inference", "medium",
                           "Heurística: entropía alta también aparece en recursos comprimidos legítimos."))
        return out

    def _wasm(self, p: Path, size: int) -> list[dict[str, Any]]:
        from eolfi.providers.wasm import parse_wasm

        if size > self.max_size:
            return [self._fail("wasm", f"archivo de {size} bytes supera el límite de análisis")]
        with open(p, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            try:
                info = parse_wasm(mm)
            except ParseError as exc:
                return [self._fail("wasm", str(exc))]
        return [self._f("wasm_module", info, "distributed_artifact", "high",
                        "Estructura del módulo (secciones, importaciones, exportaciones y metadatos personalizados); "
                        "no se desensambla el código. La cadena de herramientas es una deducción por marcas.")]

    def _pe_extra(self, mm, info: dict[str, Any]) -> list[dict[str, Any]]:
        """Firma Authenticode, imphash, Rich, TLS, VERSIONINFO y .NET (Fase E, grupo 2)."""
        from eolfi.providers import dotnet, pe_extra

        art = "distributed_artifact"
        x = pe_extra.analyze(mm, info)
        out = []
        sig = x.pop("authenticode")
        out.append(self._f("pe_signature", sig or {"present": False}, art, "high" if sig else "medium",
                           "Se leen firmante, emisor y cadena, y se comprueba que el resumen firmado coincide con el "
                           "del archivo (integridad). NO se valida la cadena de confianza ni la firma criptográfica. "
                           "Sin firma incrustada el archivo aún puede estar firmado por catálogo (Windows)."))
        out.append(self._f("pe_metadata", x, art, "high",
                           "imphash como pefile pero sin su tabla de ordinales conocidos; TLS y VERSIONINFO tal "
                           "como los declara el archivo."))
        if info["headers"]["dotnet"]:
            try:
                clr = dotnet.parse_clr(mm, info)
                out.append(self._f("dotnet_metadata", clr, art, "high",
                                   "Metadatos ECMA-335 (tablas #~); no se descompila el IL. Las pistas de ofuscación "
                                   "son marcas conocidas y una heurística de nombres."))
            except (ParseError, IndexError, struct.error) as exc:
                out.append(self._fail("dotnet", str(exc)))
        try:
            bundle = dotnet.single_file_bundle(mm)
        except (ParseError, struct.error) as exc:
            bundle = {"bundle": None, "error": str(exc)}
        if bundle and bundle.get("bundle"):
            out.append(self._f("dotnet_bundle", bundle, art, "high",
                               "Apphost de .NET «single-file»: archivos incrustados según su manifiesto."))
        return out

    def _macho_findings(self, info: dict[str, Any], file_entropy: float | None) -> list[dict[str, Any]]:
        art = "distributed_artifact"
        slices = [s for s in info["slices"] if "error" not in s]
        # Clave única por arquitectura: arm64 + arm64e comparten «cpu» y una pisaba a la otra (M12).
        cpus = [s["headers"]["cpu"] for s in slices]
        for i, s in enumerate(slices):
            h = s["headers"]
            key = h["cpu"]
            if cpus.count(h["cpu"]) > 1:
                key = f"{h['cpu']}/{h.get('cpusubtype', 0)}"
                if sum(1 for t in slices if t["headers"]["cpu"] == h["cpu"]
                       and t["headers"].get("cpusubtype") == h.get("cpusubtype")) > 1:
                    key += f"#{i}"
            h["key"] = key
        errors = [s["error"] for s in info["slices"] if "error" in s]
        out = [
            self._f("macho_headers", {"universal": info["universal"],
                                      "slices": [s["headers"] for s in slices], "errors": errors},
                    art, "high" if not errors else "medium", "Campos de mach_header y load commands."),
            self._f("macho_sections", {s["headers"]["key"]: s["sections"] for s in slices}, art, "high",
                    "Entropía sobre bytes en disco."),
            self._f("macho_security", {s["headers"]["key"]: s["security"] for s in slices}, art, "high",
                    "Flags del binario; la firma no se valida criptográficamente."),
            self._f("macho_dylibs", {s["headers"]["key"]: {"dylibs": s["dylibs"], "rpaths": s["rpaths"],
                                                           "imported_symbols": s["imported_symbols"][:2000],
                                                           "symbol_errors": s.get("symbol_errors", [])}
                                     for s in slices}, art,
                    "medium" if any(s.get("symbol_errors") for s in slices) else "high",
                    "Solo dependencias declaradas; no ve dlopen() en runtime."),
            self._f("entropy", {"file": file_entropy}, art, "high", ""),
        ]
        if slices:
            first = slices[0]
            n_imp = len(first["imported_symbols"]) if first["headers"]["filetype"] == "execute" else None
            out.append(self._f("packing_signals",
                               _packing_signals(first["sections"], file_entropy or 0.0, n_imp),
                               "analyst_inference", "medium",
                               "Heurística: entropía alta también aparece en recursos comprimidos legítimos."))
        return out

    @staticmethod
    def _f(op: str, result: Any, authority: str, confidence: str, limitations: str) -> dict[str, Any]:
        return {"operation": op, "result": result, "authority": authority,
                "confidence": confidence, "limitations": limitations}

    def _fail(self, kind: str, msg: str) -> dict[str, Any]:
        return self._f(f"{kind}_parse_error", {"error": msg}, "analyst_inference", "low",
                       "Estructura malformada o truncada; los demás campos no se leyeron.")
