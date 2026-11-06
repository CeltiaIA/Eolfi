"""Lector de la tabla de recursos de Android (resources.arsc).

Resuelve referencias @0xPPTTEEEE del manifiesto (etiqueta de la app, temas,
configuración de seguridad de red…) a su nombre ("string/app_name") y, si es
texto, a su valor en la configuración por defecto. Solo indexa los
identificadores pedidos. Lector con límites: datos malformados dan ParseError.
"""
from __future__ import annotations

import re

from typing import Any, Iterable

from eolfi.providers.axml import MAX_STRINGS, _string_pool
from eolfi.providers.binfmt import ParseError, Reader

RES_TABLE = 0x0002
RES_STRING_POOL = 0x0001
RES_PACKAGE = 0x0200
RES_TYPE = 0x0201
RES_TYPE_SPEC = 0x0202
NO_ENTRY = 0xFFFFFFFF
FLAG_SPARSE, FLAG_OFFSET16 = 0x01, 0x02
ENTRY_COMPLEX, ENTRY_COMPACT = 0x0001, 0x0008
MAX_CHUNKS = 200_000


def _value(dtype: int, data: int, strings: list[str]) -> Any:
    if dtype == 0x03:
        return strings[data] if data < len(strings) else None
    if dtype == 0x12:
        return data != 0
    if dtype in (0x10,):
        return data - (1 << 32) if data & 0x80000000 else data
    if dtype in (0x11, 0x1C, 0x1D, 0x1E, 0x1F):
        return f"#{data:08x}" if dtype >= 0x1C else hex(data)
    if dtype in (0x01, 0x02):
        return f"@0x{data:08x}"
    return data


def resolve(data: bytes, wanted: Iterable[int]) -> dict[int, dict[str, Any]]:
    """Devuelve {id: {"name": "tipo/nombre", "value": valor|None}} para los ids encontrados."""
    want = {int(w) for w in wanted}
    if not want:
        return {}
    r = Reader(data)
    if r.u16(0) != RES_TABLE:
        raise ParseError("no es una tabla de recursos de Android")
    total = min(r.u32(4), r.size)
    off = r.u16(2)
    values: list[str] = []
    found: dict[int, dict[str, Any]] = {}
    chunks = 0
    budget = [MAX_STRINGS]   # cadenas de TODOS los pools de la tabla (A6)
    while off + 8 <= total:
        ctype, csize = r.u16(off), r.u32(off + 4)
        if csize < 8 or off + csize > total:
            raise ParseError(f"chunk {ctype:#x} de tamaño inválido")
        if ctype == RES_STRING_POOL and not values:
            values = _pool(r, off, budget)
        elif ctype == RES_PACKAGE:
            _package(r, off, csize, values, want, found, budget)
        off += csize
        chunks += 1
        if chunks > MAX_CHUNKS:
            raise ParseError("demasiados bloques")
    return found


def _pool(r: Reader, off: int, budget: list[int]) -> list[str]:
    out = _string_pool(r, off, budget[0])
    budget[0] -= len(out)
    return out


def _package(r: Reader, poff: int, psize: int, values: list[str], want: set[int], found: dict,
             budget: list[int]) -> None:
    hsize = r.u16(poff + 2)
    pkg_id = r.u32(poff + 8)
    if not any((w >> 24) == pkg_id for w in want):
        return
    ts, ks = r.u32(poff + 268), r.u32(poff + 276)
    if not (hsize <= ts < psize and hsize <= ks < psize):
        raise ParseError("pools del paquete fuera de su bloque")
    type_strings = _pool(r, poff + ts, budget)
    key_strings = _pool(r, poff + ks, budget)
    off = poff + hsize
    end = poff + psize
    while off + 8 <= end:
        ctype, chsize, csize = r.u16(off), r.u16(off + 2), r.u32(off + 4)
        if csize < 8 or off + csize > end:
            raise ParseError("bloque de tipo inválido")
        if ctype == RES_TYPE:
            type_id, flags = r.u8(off + 8), r.u8(off + 9)
            prefix = (pkg_id << 24) | (type_id << 16)
            if any((w & 0xFFFF0000) == prefix for w in want):
                _type_chunk(r, off, chsize, csize, flags, type_id, prefix, values, type_strings, key_strings, want, found)
        off += csize


def _type_chunk(r, off, chsize, csize, flags, type_id, prefix, values, type_strings, key_strings, want, found) -> None:
    count, entries_start = r.u32(off + 12), r.u32(off + 16)
    # Configuración por defecto = sin idioma ni país (bytes 8..11 de ResTable_config).
    config = off + 20
    default_cfg = r.u32(config) >= 12 and r.raw(config + 8, 4) == b"\x00\x00\x00\x00"
    targets = {w & 0xFFFF for w in want if (w & 0xFFFF0000) == prefix}
    index = off + chsize
    pairs: list[tuple[int, int]] = []
    # La tabla de índices debe caber DENTRO de su bloque (PLAN_MEJORAS A5): si no, un «count» enorme
    # leería fuera del bloque. Como los bloques no se solapan, el total de iteraciones de todo resolve()
    # queda acotado por el tamaño del archivo / 2.
    width = 2 if (flags & FLAG_OFFSET16) and not (flags & FLAG_SPARSE) else 4
    if chsize < 20 or index + width * count > off + csize or entries_start > csize:
        raise ParseError("tabla de índices fuera de su bloque")
    if flags & FLAG_SPARSE:
        for i in range(count):
            idx, o16 = r.u16(index + 4 * i), r.u16(index + 4 * i + 2)
            if idx in targets:
                pairs.append((idx, o16 * 4))
    else:
        for idx in targets:
            if idx >= count:
                continue
            o = r.u16(index + 2 * idx) if flags & FLAG_OFFSET16 else r.u32(index + 4 * idx)
            if (flags & FLAG_OFFSET16 and o == 0xFFFF) or o == NO_ENTRY:
                continue
            pairs.append((idx, o * 4 if flags & FLAG_OFFSET16 else o))
    for idx, eoff in pairs:
        e = off + entries_start + eoff
        if e + 8 > off + csize:
            continue
        size, eflags = r.u16(e), r.u16(e + 2)
        if eflags & ENTRY_COMPACT:
            key, dtype, data = size, eflags >> 8, r.u32(e + 4)
        else:
            key = r.u32(e + 4)
            if eflags & ENTRY_COMPLEX:
                dtype, data = None, None
            else:
                v = e + size
                dtype, data = r.u8(v + 3), r.u32(v + 4)
        rid = prefix | idx
        tname = type_strings[type_id - 1] if 0 < type_id <= len(type_strings) else f"type{type_id}"
        kname = key_strings[key] if key < len(key_strings) else f"0x{rid:08x}"
        value = _value(dtype, data, values) if dtype is not None else None
        current = found.get(rid)
        if current is None or (default_cfg and not current.get("default")):
            found[rid] = {"name": f"{tname}/{kname}", "value": value, "default": default_cfg}


def resolve_refs(obj: Any, arsc: bytes) -> dict[str, dict[str, Any]]:
    """Busca cadenas "@0x…" en un objeto (manifiesto resumido) y las resuelve."""
    refs: set[str] = set()

    def walk(o: Any) -> None:
        if isinstance(o, str) and re.fullmatch(r"@0x[0-9a-fA-F]{8}", o):
            refs.add(o)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    if not refs:
        return {}
    ids = {int(x[1:], 16): x for x in refs}
    res = resolve(arsc, ids)
    out = {ids[i]: {"name": v["name"], "value": v["value"]} for i, v in res.items()}
    # Seguir alias (@string/a -> @string/b) hasta 5 saltos.
    for _ in range(5):
        pending = {e["value"] for e in out.values()
                   if isinstance(e["value"], str) and e["value"].startswith("@0x") and len(e["value"]) == 11}
        if not pending:
            break
        nxt = resolve(arsc, {int(x[1:], 16) for x in pending if re.fullmatch(r"@0x[0-9a-fA-F]{8}", x)})
        alias = {f"@0x{i:08x}": v["value"] for i, v in nxt.items()}
        changed = False
        for e in out.values():
            if e["value"] in alias:
                e["alias_of"] = e["value"]
                e["value"] = alias[e["value"]]
                changed = True
        if not changed:
            break
    return out
