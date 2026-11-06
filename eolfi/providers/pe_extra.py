"""Análisis adicional de PE (Fase E, grupo 2): Authenticode, imphash, cabecera Rich, TLS y VERSIONINFO.

Todo con la stdlib y con límites. La firma Authenticode se LEE (firmante, emisor, cadena incluida, algoritmo)
y se comprueba que el resumen firmado coincide con el del archivo (integridad: el archivo no se modificó tras
firmarlo). NO se valida la cadena de confianza ni la firma RSA/ECDSA del firmante.
"""
from __future__ import annotations

import hashlib
import struct
from typing import Any

from eolfi.providers.binfmt import ParseError, Reader
from eolfi.providers.der import HASHES, oid_name, parse_pkcs7

MAX_TLS_CALLBACKS = 64
MAX_RES_ENTRIES = 4096
MAX_VERSION_STRINGS = 64
_TIMESTAMP_OIDS = (bytes.fromhex("2a864886f70d010906"),     # countersignature (1.2.840.113549.1.9.6)
                   bytes.fromhex("2b060104018237030301"))   # RFC 3161 (1.3.6.1.4.1.311.3.3.1)
_NESTED_SIG_OID = bytes.fromhex("2b060104018237020401")     # 1.3.6.1.4.1.311.2.4.1


class _Layout:
    def __init__(self, data, info: dict[str, Any]):
        self.r = Reader(data)
        self.lay = info["_layout"]
        self.secs = info["sections"]

    def off(self, rva: int) -> int:
        for s in self.secs:
            span = max(s["virtual_size"], s["raw_size"])
            if s["virtual_address"] <= rva < s["virtual_address"] + span:
                o = rva - s["virtual_address"] + s["raw_offset"]
                if o >= self.r.size:
                    raise ParseError(f"RVA {rva:#x} fuera del archivo")
                return o
        if rva < self.lay["size_of_headers"]:
            return rva
        raise ParseError(f"RVA {rva:#x} sin sección")


# ---------------------------------------------------------------------------------------------- Authenticode
def authenticode_digest(data, lay: dict[str, Any], algo: str) -> str:
    """Resumen Authenticode: el archivo entero salvo el CheckSum, la entrada del directorio de seguridad y la
    propia tabla de certificados (método de osslsigncode y signify)."""
    h = hashlib.new(algo)
    size = len(data)
    cert_off, cert_size = lay["dirs"][4]
    skips = sorted([(lay["checksum_off"], 4), (lay["certdir_off"], 8)]
                   + ([(cert_off, cert_size)] if cert_off and cert_off + cert_size <= size else []))
    pos = 0
    for start, n in skips:
        if start > pos:
            for i in range(pos, start, 1 << 20):
                h.update(data[i:min(start, i + (1 << 20))])
        pos = max(pos, start + n)
    for i in range(pos, size, 1 << 20):
        h.update(data[i:min(size, i + (1 << 20))])
    return h.hexdigest()


def authenticode(data, info: dict[str, Any]) -> dict[str, Any] | None:
    lay = info["_layout"]
    cert_off, cert_size = lay["dirs"][4]
    if not cert_off or not cert_size:
        return None
    if cert_off + cert_size > len(data) or cert_size < 8:
        return {"present": True, "error": "tabla de certificados fuera del archivo"}
    out: dict[str, Any] = {"present": True, "signatures": []}
    off, end = cert_off, cert_off + cert_size
    while off + 8 <= end and len(out["signatures"]) < 8:
        length, rev, ctype = struct.unpack_from("<IHH", data, off)
        if length < 8 or off + length > end:
            out["error"] = "WIN_CERTIFICATE con longitud inválida"
            break
        blob = bytes(data[off + 8:off + length])
        sig: dict[str, Any] = {"revision": hex(rev), "type": {1: "X509", 2: "PKCS_SIGNED_DATA"}.get(ctype, hex(ctype))}
        if ctype == 2:
            try:
                p7 = parse_pkcs7(blob)
                sig.update(_spc(p7, data, lay))
                sig["timestamped"] = any(o in blob for o in _TIMESTAMP_OIDS)
                sig["nested_signatures"] = _NESTED_SIG_OID in blob
            except (ParseError, IndexError, ValueError) as exc:
                sig["error"] = f"PKCS#7 ilegible: {exc}"
        out["signatures"].append(sig)
        off += (length + 7) & ~7
    first = next((s for s in out["signatures"] if "signer" in s), None)
    if first:
        out["signer"] = first["signer"]
        out["digest_matches"] = first.get("digest_matches")
    return out


def _spc(p7: dict[str, Any], data, lay) -> dict[str, Any]:
    res: dict[str, Any] = {"content_type": p7["content_type"], "certificates": [
        {k: c[k] for k in ("subject", "issuer", "not_before", "not_after", "sha256", "self_signed")}
        for c in p7["certificates"][:10]]}
    content = p7["content"]
    if p7["content_type"] == "spcIndirectDataContent" and content is not None:
        kids = content.children()
        if len(kids) >= 2:
            digest_info = kids[1].children()
            algo = oid_name(digest_info[0].children()[0].value) if digest_info and digest_info[0].children() else None
            signed = digest_info[1].value.hex() if len(digest_info) > 1 else None
            res["digest_algorithm"], res["signed_digest"] = algo, signed
            if algo in HASHES and signed:
                actual = authenticode_digest(data, lay, HASHES[algo])
                res["file_digest"] = actual
                res["digest_matches"] = actual == signed
    signer = p7["signers"][0] if p7["signers"] else None
    if signer:
        cert = next((c for c in p7["certificates"] if c["serial"] == signer["serial"]), None)
        res["signer"] = {"subject": cert["subject"] if cert else None, "issuer": signer["issuer"],
                         "serial": signer["serial"], "not_before": cert and cert["not_before"],
                         "not_after": cert and cert["not_after"], "sha256": cert and cert["sha256"]}
    return res


# ---------------------------------------------------------------------------------------------- imphash
def imphash(imports: dict[str, list[str]]) -> str | None:
    """Mismo cálculo que pefile (sin su tabla de ordinales conocidos: los ordinales quedan como «ordN»)."""
    parts = []
    for dll, funcs in imports.items():
        lib = dll.lower()
        for ext in (".dll", ".ocx", ".sys"):
            if lib.endswith(ext):
                lib = lib[: -len(ext)]
        for f in funcs:
            fn = f"ord{f[1:]}" if f.startswith("#") else f.lower()
            parts.append(f"{lib}.{fn}")
    return hashlib.md5(",".join(parts).encode()).hexdigest() if parts else None


# ---------------------------------------------------------------------------------------------- Rich
_RICH_PRODUCTS = {0x0001: "Import0", 0x0093: "Linker 6", 0x0104: "Utc1900 C", 0x0105: "Utc1900 C++",
                  0x0102: "Linker 14", 0x0103: "Cvtres 14", 0x00FF: "Masm 14"}


def rich_header(data, info: dict[str, Any]) -> dict[str, Any] | None:
    pe_off = info["_layout"]["pe_off"]
    stub = bytes(data[0x40:min(pe_off, 0x1000)])
    i = stub.find(b"Rich")
    if i < 0 or i + 8 > len(stub):
        return None
    key = struct.unpack_from("<I", stub, i + 4)[0]
    entries = []
    j = i - 8
    while j >= 0 and len(entries) < 512:
        a, b = struct.unpack_from("<II", stub, j)
        a ^= key
        b ^= key
        if a == 0x536E6144:   # «DanS»
            break
        if a or b:
            entries.append({"product_id": a >> 16, "build": a & 0xFFFF, "count": b,
                            "product": _RICH_PRODUCTS.get(a >> 16)})
        j -= 8
    else:
        return {"present": True, "error": "cabecera Rich sin marca DanS"}
    entries.reverse()
    body = bytes(stub[j:i])
    return {"present": True, "key": f"{key:08x}", "entries": [e for e in entries if e["product_id"] or e["build"]],
            "rich_hash": hashlib.md5(bytes(b ^ ((key >> (8 * (k % 4))) & 0xFF) for k, b in enumerate(body))).hexdigest()}


# ---------------------------------------------------------------------------------------------- TLS
def tls_callbacks(data, info: dict[str, Any]) -> dict[str, Any] | None:
    lay = info["_layout"]
    rva = lay["dirs"][9][0]
    if not rva:
        return None
    L = _Layout(data, info)
    pe32plus = lay["pe32plus"]
    base = lay["image_base"]
    try:
        t = L.off(rva)
        cb_va = L.r.u64(t + 24) if pe32plus else L.r.u32(t + 12)
        callbacks = []
        if cb_va:
            o = L.off(cb_va - base)
            for k in range(MAX_TLS_CALLBACKS):
                v = L.r.u64(o + 8 * k) if pe32plus else L.r.u32(o + 4 * k)
                if not v:
                    break
                callbacks.append(f"{v:#x}")
        return {"callbacks": callbacks, "count": len(callbacks),
                "note": "Las callbacks TLS se ejecutan ANTES del punto de entrada (técnica anti-depuración habitual)."
                if callbacks else None}
    except ParseError as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------------------------- VERSIONINFO
def _res_dir(L: _Layout, base: int, off: int) -> list[tuple[int, int, bool]]:
    named, ids = L.r.u16(base + off + 12), L.r.u16(base + off + 14)
    out = []
    for k in range(min(named + ids, MAX_RES_ENTRIES)):
        e = base + off + 16 + 8 * k
        name, target = L.r.u32(e), L.r.u32(e + 4)
        out.append((name, target & 0x7FFFFFFF, bool(target & 0x80000000)))
    return out


def version_info(data, info: dict[str, Any]) -> dict[str, Any] | None:
    rva = info["_layout"]["dirs"][2][0]
    if not rva:
        return None
    L = _Layout(data, info)
    try:
        base = L.off(rva)
        # Árbol de recursos: tipo (RT_VERSION = 16) → nombre → idioma → entrada de datos.
        names = next((t for n, t, sub in _res_dir(L, base, 0) if n == 16 and sub), None)
        langs = next((t for _n, t, sub in _res_dir(L, base, names) if sub), None) if names is not None else None
        node = next((t for _n, t, sub in _res_dir(L, base, langs) if not sub), None) if langs is not None else None
        if node is None:
            return None
        drva, dsize = L.r.u32(base + node), L.r.u32(base + node + 4)
        blob = L.r.raw(L.off(drva), min(dsize, 64 * 1024))
    except ParseError as exc:
        return {"error": str(exc)}
    return _parse_vs(blob)


def _block(b: bytes, off: int):
    if off + 6 > len(b):
        raise ParseError("bloque de versión truncado")
    length, vlen, vtype = struct.unpack_from("<HHH", b, off)
    end = min(off + max(length, 6), len(b))
    k = off + 6
    key_end = k
    while key_end + 1 < end and b[key_end:key_end + 2] != b"\x00\x00":
        key_end += 2
    key = b[k:key_end].decode("utf-16-le", "replace")
    v = (key_end + 2 + 3) & ~3
    return key, vlen, vtype, v, end


def _parse_vs(b: bytes) -> dict[str, Any]:
    key, vlen, _t, v, end = _block(b, 0)
    if key != "VS_VERSION_INFO":
        return {"error": "VS_VERSION_INFO no encontrado"}
    out: dict[str, Any] = {"strings": {}}
    if vlen >= 52 and struct.unpack_from("<I", b, v)[0] == 0xFEEF04BD:
        ms, ls, pms, pls = struct.unpack_from("<IIII", b, v + 8)
        out["file_version"] = f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
        out["product_version"] = f"{pms >> 16}.{pms & 0xFFFF}.{pls >> 16}.{pls & 0xFFFF}"
    off = (v + vlen + 3) & ~3
    guard = 0
    while off < end and guard < 32:
        guard += 1
        k, _vl, _ty, cv, cend = _block(b, off)
        if k == "StringFileInfo":
            t_off = cv
            while t_off < cend:
                _lang, _a, _b, s_off, t_end = _block(b, t_off)
                while s_off < t_end and len(out["strings"]) < MAX_VERSION_STRINGS:
                    sk, svl, sty, sv, send = _block(b, s_off)
                    raw = b[sv:send]
                    out["strings"][sk[:64]] = raw.decode("utf-16-le", "replace").split("\x00", 1)[0][:300] if sty == 1 \
                        else raw[:svl].hex()
                    s_off = (send + 3) & ~3
                t_off = (t_end + 3) & ~3
        off = (cend + 3) & ~3
    return out


def analyze(data, info: dict[str, Any]) -> dict[str, Any]:
    """Todos los extras; cada uno aislado (un fallo en uno no oculta los demás)."""
    out: dict[str, Any] = {}
    for key, fn in (("authenticode", lambda: authenticode(data, info)),
                    ("imphash", lambda: imphash(info["imports"]["dlls"])),
                    ("rich_header", lambda: rich_header(data, info)),
                    ("tls", lambda: tls_callbacks(data, info)),
                    ("version_info", lambda: version_info(data, info))):
        try:
            out[key] = fn()
        except (ParseError, ValueError, IndexError, struct.error) as exc:
            out[key] = {"error": f"{type(exc).__name__}: {exc}"}
    return out
