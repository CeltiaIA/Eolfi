""".NET/CLR (Fase E, grupo 2): metadatos ECMA-335 con la stdlib.

- Cabecera CLR: runtime, flags (IL puro, 32 bits), firma de nombre seguro, ReadyToRun.
- Metadatos: versión, Module, Assembly, AssemblyRef (dependencias con versión), ModuleRef + ImplMap (P/Invoke:
  qué DLL nativas y funciones llama), recursos incrustados, recuento de tipos y métodos, framework de destino.
- Pistas de ofuscadores conocidos (ConfuserEx, Dotfuscator, SmartAssembly, .NET Reactor, Babel, Eazfuscator…).
- Apphost «single-file»: detecta el paquete incrustado y lista sus archivos.
"""
from __future__ import annotations

import re
import struct
from typing import Any

from eolfi.providers.binfmt import ParseError, Reader

MAX_ROWS_LISTED = 300

# Índices codificados: (tablas, bits de etiqueta)
_CODED = {
    "TypeDefOrRef": ([0x02, 0x01, 0x1B], 2), "HasConstant": ([0x04, 0x08, 0x17], 2),
    "HasCustomAttribute": ([0x06, 0x04, 0x01, 0x02, 0x08, 0x09, 0x0A, 0x00, 0x0E, 0x17, 0x14, 0x11, 0x1A, 0x1B,
                            0x20, 0x23, 0x26, 0x27, 0x28, 0x2A, 0x2C, 0x2B], 5),
    "HasFieldMarshal": ([0x04, 0x08], 1), "HasDeclSecurity": ([0x02, 0x06, 0x20], 2),
    "MemberRefParent": ([0x02, 0x01, 0x1A, 0x06, 0x1B], 3), "HasSemantics": ([0x14, 0x17], 1),
    "MethodDefOrRef": ([0x06, 0x0A], 1), "MemberForwarded": ([0x04, 0x06], 1),
    "Implementation": ([0x26, 0x23, 0x27], 2), "CustomAttributeType": ([0x06, 0x0A], 3),
    "ResolutionScope": ([0x00, 0x1A, 0x23, 0x01], 2), "TypeOrMethodDef": ([0x02, 0x06], 1),
}
# Columnas de cada tabla: 2/4 = entero; "s" cadena, "g" GUID, "b" blob; ("t", n) índice a tabla; ("c", nombre).
_T = lambda n: ("t", n)  # noqa: E731
_C = lambda n: ("c", n)  # noqa: E731
_SCHEMA: dict[int, tuple[str, list]] = {
    0x00: ("Module", [2, "s", "g", "g", "g"]),
    0x01: ("TypeRef", [_C("ResolutionScope"), "s", "s"]),
    0x02: ("TypeDef", [4, "s", "s", _C("TypeDefOrRef"), _T(0x04), _T(0x06)]),
    0x03: ("FieldPtr", [_T(0x04)]),
    0x04: ("Field", [2, "s", "b"]),
    0x05: ("MethodPtr", [_T(0x06)]),
    0x06: ("MethodDef", [4, 2, 2, "s", "b", _T(0x08)]),
    0x07: ("ParamPtr", [_T(0x08)]),
    0x08: ("Param", [2, 2, "s"]),
    0x09: ("InterfaceImpl", [_T(0x02), _C("TypeDefOrRef")]),
    0x0A: ("MemberRef", [_C("MemberRefParent"), "s", "b"]),
    0x0B: ("Constant", [2, _C("HasConstant"), "b"]),
    0x0C: ("CustomAttribute", [_C("HasCustomAttribute"), _C("CustomAttributeType"), "b"]),
    0x0D: ("FieldMarshal", [_C("HasFieldMarshal"), "b"]),
    0x0E: ("DeclSecurity", [2, _C("HasDeclSecurity"), "b"]),
    0x0F: ("ClassLayout", [2, 4, _T(0x02)]),
    0x10: ("FieldLayout", [4, _T(0x04)]),
    0x11: ("StandAloneSig", ["b"]),
    0x12: ("EventMap", [_T(0x02), _T(0x14)]),
    0x13: ("EventPtr", [_T(0x14)]),
    0x14: ("Event", [2, "s", _C("TypeDefOrRef")]),
    0x15: ("PropertyMap", [_T(0x02), _T(0x17)]),
    0x16: ("PropertyPtr", [_T(0x17)]),
    0x17: ("Property", [2, "s", "b"]),
    0x18: ("MethodSemantics", [2, _T(0x06), _C("HasSemantics")]),
    0x19: ("MethodImpl", [_T(0x02), _C("MethodDefOrRef"), _C("MethodDefOrRef")]),
    0x1A: ("ModuleRef", ["s"]),
    0x1B: ("TypeSpec", ["b"]),
    0x1C: ("ImplMap", [2, _C("MemberForwarded"), "s", _T(0x1A)]),
    0x1D: ("FieldRVA", [4, _T(0x04)]),
    0x1E: ("EncLog", [4, 4]),
    0x1F: ("EncMap", [4]),
    0x20: ("Assembly", [4, 2, 2, 2, 2, 4, "b", "s", "s"]),
    0x21: ("AssemblyProcessor", [4]),
    0x22: ("AssemblyOS", [4, 4, 4]),
    0x23: ("AssemblyRef", [2, 2, 2, 2, 4, "b", "s", "s", "b"]),
    0x24: ("AssemblyRefProcessor", [4, _T(0x23)]),
    0x25: ("AssemblyRefOS", [4, 4, 4, _T(0x23)]),
    0x26: ("File", [4, "s", "b"]),
    0x27: ("ExportedType", [4, 4, "s", "s", _C("Implementation")]),
    0x28: ("ManifestResource", [4, 4, "s", _C("Implementation")]),
    0x29: ("NestedClass", [_T(0x02), _T(0x02)]),
    0x2A: ("GenericParam", [2, 2, _C("TypeOrMethodDef"), "s"]),
    0x2B: ("MethodSpec", [_C("MethodDefOrRef"), "b"]),
    0x2C: ("GenericParamConstraint", [_T(0x2A), _C("TypeDefOrRef")]),
}
OBFUSCATORS = {
    b"ConfusedByAttribute": "ConfuserEx", b"ConfuserEx": "ConfuserEx", b"DotfuscatorAttribute": "Dotfuscator",
    b"SmartAssembly.Attributes": "SmartAssembly", b"PoweredByAttribute": "SmartAssembly",
    b"BabelObfuscatorAttribute": "Babel", b"BabelAttribute": "Babel", b"ObfuscatedByGoliath": "Goliath",
    b"Xenocode.Client.Attributes": "Xenocode", b"CryptoObfuscator": "Crypto Obfuscator",
    b"EazfuscatorNet": "Eazfuscator.NET", b"Agile.NET": "Agile.NET", b"ObfuscatorAttribute": "(atributo de ofuscador)",
    b"__DotNetPatcher": "DotNetPatcher", b"YanoAttribute": "Yano", b"NETGuard": "NETGuard",
}
# Marca del paquete «single-file» (bundle) en el apphost: sha256(".net core bundle").
BUNDLE_SIGNATURE = bytes([0x8b, 0x12, 0x02, 0xb9, 0x6a, 0x61, 0x20, 0x38, 0x72, 0x7b, 0x93, 0x02, 0x14, 0xd7, 0xa0,
                          0x32, 0x13, 0xf5, 0xb9, 0xe6, 0xef, 0xae, 0x33, 0x18, 0xee, 0x3b, 0x2d, 0xce, 0x24, 0xb3,
                          0x6a, 0xae])


def _off(info: dict[str, Any], rva: int, size: int) -> int:
    for s in info["sections"]:
        span = max(s["virtual_size"], s["raw_size"])
        if s["virtual_address"] <= rva < s["virtual_address"] + span:
            return rva - s["virtual_address"] + s["raw_offset"]
    if rva < info["_layout"]["size_of_headers"]:
        return rva
    raise ParseError(f"RVA {rva:#x} sin sección")


class _Heaps:
    def __init__(self, r: Reader, streams: dict[str, tuple[int, int]]):
        self.r = r
        self.st = streams

    def string(self, idx: int) -> str:
        off, size = self.st.get("#Strings", (0, 0))
        if idx >= size:
            return ""
        return self.r.cstr(off + idx, min(1024, size - idx)) if size else ""

    def blob(self, idx: int) -> bytes:
        off, size = self.st.get("#Blob", (0, 0))
        if not size or idx >= size:
            return b""
        p = off + idx
        b0 = self.r.u8(p)
        if b0 & 0x80 == 0:
            n, h = b0, 1
        elif b0 & 0xC0 == 0x80:
            n, h = ((b0 & 0x3F) << 8) | self.r.u8(p + 1), 2
        else:
            n, h = ((b0 & 0x1F) << 24) | (self.r.u8(p + 1) << 16) | (self.r.u8(p + 2) << 8) | self.r.u8(p + 3), 4
        return self.r.raw(p + h, min(n, size - idx - h, 1 << 16))


def parse_clr(data, info: dict[str, Any]) -> dict[str, Any] | None:
    rva, size = info["_layout"]["dirs"][14]
    if not rva:
        return None
    r = Reader(data)
    h = _off(info, rva, size)
    cb, major, minor = r.u32(h), r.u16(h + 4), r.u16(h + 6)
    md_rva, md_size, flags = r.u32(h + 8), r.u32(h + 12), r.u32(h + 16)
    sn_rva = r.u32(h + 32)
    mnh_rva, mnh_size = (r.u32(h + 64), r.u32(h + 68)) if cb >= 72 else (0, 0)
    out: dict[str, Any] = {
        "runtime_header": f"{major}.{minor}",
        "il_only": bool(flags & 0x1), "requires_32bit": bool(flags & 0x2), "prefers_32bit": bool(flags & 0x20000),
        "strong_name_signed": bool(flags & 0x8) and bool(sn_rva),
        "native_entry_point": bool(flags & 0x10),
    }
    if mnh_rva and mnh_size:
        try:
            out["ready_to_run"] = r.u32(_off(info, mnh_rva, mnh_size)) == 0x00525452   # «RTR»
        except ParseError:
            out["ready_to_run"] = False
    else:
        out["ready_to_run"] = False
    m = _off(info, md_rva, md_size)
    if r.u32(m) != 0x424A5342:   # «BSJB»
        raise ParseError("raíz de metadatos .NET sin firma BSJB")
    vlen = r.u32(m + 12)
    if vlen > 256:
        raise ParseError("versión de metadatos demasiado larga")
    out["metadata_version"] = r.raw(m + 16, vlen).split(b"\x00", 1)[0].decode("ascii", "replace")
    p = m + 16 + vlen
    nstreams = r.u16(p + 2)
    p += 4
    streams: dict[str, tuple[int, int]] = {}
    for _ in range(min(nstreams, 16)):
        so, ss = r.u32(p), r.u32(p + 4)
        name = r.cstr(p + 8, 32)
        streams[name] = (m + so, ss)
        p += 8 + ((len(name) + 4) & ~3)
    heaps = _Heaps(r, streams)
    tables_key = "#~" if "#~" in streams else "#-" if "#-" in streams else None
    if tables_key:
        out.update(_tables(r, heaps, streams[tables_key][0]))
    out.update(_heap_hints(r, streams))
    return out


def _tables(r: Reader, heaps: _Heaps, t: int) -> dict[str, Any]:
    heap_sizes = r.u8(t + 6)
    valid = r.u64(t + 8)
    rows: dict[int, int] = {}
    p = t + 24
    for i in range(64):
        if valid >> i & 1:
            rows[i] = r.u32(p)
            if rows[i] > 50_000_000:
                raise ParseError("número de filas de metadatos absurdo")
            p += 4
    si = 4 if heap_sizes & 1 else 2
    gi = 4 if heap_sizes & 2 else 2
    bi = 4 if heap_sizes & 4 else 2

    def coded(name: str) -> int:
        tabs, bits = _CODED[name]
        return 2 if max(rows.get(x, 0) for x in tabs) < (1 << (16 - bits)) else 4

    def width(col) -> int:
        if col in (2, 4):
            return col
        if col == "s":
            return si
        if col == "g":
            return gi
        if col == "b":
            return bi
        kind, arg = col
        if kind == "t":
            return 2 if rows.get(arg, 0) < 1 << 16 else 4
        return coded(arg)

    layout: dict[int, tuple[int, list[int]]] = {}
    for i in sorted(rows):
        if i not in _SCHEMA:
            raise ParseError(f"tabla de metadatos desconocida {i:#x}")
        ws = [width(c) for c in _SCHEMA[i][1]]
        layout[i] = (p, ws)
        p += rows[i] * sum(ws)

    def row(table: int, k: int) -> list[int]:
        start, ws = layout[table]
        q = start + k * sum(ws)
        vals = []
        for w in ws:
            vals.append(r.u16(q) if w == 2 else r.u32(q))
            q += w
        return vals

    def iter_rows(table: int):
        for k in range(min(rows.get(table, 0), MAX_ROWS_LISTED)):
            yield row(table, k)

    out: dict[str, Any] = {"counts": {_SCHEMA[i][0]: n for i, n in rows.items() if i in (0x01, 0x02, 0x06, 0x0A, 0x23, 0x28)}}
    if rows.get(0x00):
        out["module"] = heaps.string(row(0x00, 0)[1])
    if rows.get(0x20):
        a = row(0x20, 0)
        out["assembly"] = {"name": heaps.string(a[7]), "version": f"{a[1]}.{a[2]}.{a[3]}.{a[4]}",
                           "culture": heaps.string(a[8]) or None, "public_key": bool(heaps.blob(a[6]))}
    out["assembly_refs"] = [{"name": heaps.string(a[6]), "version": f"{a[0]}.{a[1]}.{a[2]}.{a[3]}"}
                            for a in iter_rows(0x23)]
    modrefs = [heaps.string(m[0]) for m in iter_rows(0x1A)]
    pinvoke: dict[str, list[str]] = {}
    for im in iter_rows(0x1C):
        dll = modrefs[im[3] - 1] if 0 < im[3] <= len(modrefs) else "?"
        pinvoke.setdefault(dll, []).append(heaps.string(im[2]))
    out["pinvoke"] = {k: sorted(set(v))[:100] for k, v in pinvoke.items()}
    out["resources"] = [heaps.string(m[2]) for m in iter_rows(0x28)][:100]
    return out


def _heap_hints(r: Reader, streams: dict[str, tuple[int, int]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    s_off, s_size = streams.get("#Strings", (0, 0))
    strings = r.raw(s_off, min(s_size, 16 * 1024 * 1024)) if s_size else b""
    b_off, b_size = streams.get("#Blob", (0, 0))
    blob = r.raw(b_off, min(b_size, 16 * 1024 * 1024)) if b_size else b""
    found = sorted({name for marker, name in OBFUSCATORS.items() if marker in strings})
    # Nombres ilegibles en masa (renombrado): muchos identificadores con caracteres de control o no ASCII.
    names = [n for n in strings.split(b"\x00") if n]
    weird = sum(1 for n in names if any(c < 0x20 or c > 0x7E for c in n))
    if names and weird > 50 and weird / len(names) > 0.3:
        found.append(f"identificadores renombrados ({weird} de {len(names)} no legibles)")
    out["obfuscation"] = found
    m = re.search(rb"(\.NET(?:CoreApp|Framework|Standard|),Version=v[\d.]+)", blob)
    out["target_framework"] = m.group(1).decode("ascii") if m else None
    return out


def single_file_bundle(data) -> dict[str, Any] | None:
    """Apphost con el paquete «single-file» de .NET: offset de la cabecera justo antes de la marca."""
    i = data.find(BUNDLE_SIGNATURE)
    if i < 8:
        return None
    hdr = struct.unpack_from("<q", data, i - 8)[0]
    if hdr <= 0 or hdr + 12 > len(data):
        return {"bundle": False}
    r = Reader(data)
    major, minor, count = r.u32(hdr), r.u32(hdr + 4), r.u32(hdr + 8)
    p = hdr + 12

    def s7(q: int) -> tuple[str, int]:
        n, shift = 0, 0
        while True:
            b = r.u8(q)
            q += 1
            n |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80 or shift > 28:
                break
        return r.raw(q, min(n, 1024)).decode("utf-8", "replace"), q + n

    bundle_id, p = s7(p)
    if major >= 2:
        p += 8 * 4 + 8   # deps.json y runtimeconfig.json (offset, tamaño) + flags
    files = []
    for _ in range(min(count, 2000)):
        p += 8 + 8 + (8 if major >= 6 else 0)
        ftype = r.u8(p)
        name, p = s7(p + 1)
        files.append({"path": name, "type": {1: "assembly", 2: "native", 3: "deps.json", 4: "runtimeconfig", 5: "symbols"}
                      .get(ftype, str(ftype))})
    return {"bundle": True, "format": f"{major}.{minor}", "bundle_id": bundle_id, "files": len(files),
            "assemblies": [f["path"] for f in files if f["type"] == "assembly"][:100],
            "native": [f["path"] for f in files if f["type"] == "native"][:50]}
