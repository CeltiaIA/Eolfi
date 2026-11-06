"""Firma de APK (Fase E, grupo 2): esquemas v1 (JAR), v2, v3/v3.1 (bloque de firma) y v4 (.idsig aparte).

Se leen los certificados del firmante (sujeto, emisor, validez y la huella SHA-256 que muestra
`apksigner verify --print-certs`), la rotación de claves de v3 y los SDK mínimos/máximos. NO se verifican las
firmas criptográficas ni los resúmenes del contenido: para eso, `apksigner verify`.
"""
from __future__ import annotations

import struct
import zipfile
from pathlib import Path
from typing import Any

from eolfi.providers.binfmt import ParseError
from eolfi.providers.der import parse_certificate_der, parse_pkcs7

MAGIC = b"APK Sig Block 42"
IDS = {0x7109871A: "v2", 0xF05368C0: "v3", 0x1B93AD61: "v3.1", 0x42726577: "verity_padding",
       0x6DFF800D: "source_stamp", 0x2146444E: "google_play_metadata", 0x504B4453: "dependency_info"}
ROTATION_ATTR = 0x3BA06F8C
MAX_BLOCK = 64 * 1024 * 1024


MAX_SIG_BYTES = 4 * 1024 * 1024   # una firma v1 real ocupa unos KB

def _lp(buf: bytes, off: int, end: int) -> tuple[bytes, int]:
    """Bloque con prefijo de longitud u32 (little endian)."""
    if off + 4 > end:
        raise ParseError("bloque de firma truncado")
    n = struct.unpack_from("<I", buf, off)[0]
    if off + 4 + n > end:
        raise ParseError("bloque de firma fuera de su contenedor")
    return buf[off + 4:off + 4 + n], off + 4 + n


def _seq(buf: bytes) -> list[bytes]:
    out, off = [], 0
    while off < len(buf) and len(out) < 64:
        item, off = _lp(buf, off, len(buf))
        out.append(item)
    return out


def _eocd(fh, size: int) -> tuple[int, int]:
    fh.seek(max(0, size - 65_557))
    tail = fh.read()
    i = tail.rfind(b"PK\x05\x06")
    if i < 0 or i + 22 > len(tail):
        raise ParseError("sin EOCD")
    cd_size, cd_off = struct.unpack_from("<II", tail, i + 12)
    return cd_off, cd_size


def signing_block(path: str | Path) -> dict[int, bytes] | None:
    p = Path(path)
    size = p.stat().st_size
    with open(p, "rb") as fh:
        cd_off, _ = _eocd(fh, size)
        if cd_off < 32 or cd_off > size:
            return None
        fh.seek(cd_off - 24)
        footer = fh.read(24)
        if footer[8:] != MAGIC:
            return None
        bsize = struct.unpack_from("<Q", footer, 0)[0]
        if bsize > MAX_BLOCK or bsize + 8 > cd_off:
            raise ParseError("bloque de firma APK de tamaño inválido")
        fh.seek(cd_off - bsize - 8)
        block = fh.read(bsize + 8)
    if struct.unpack_from("<Q", block, 0)[0] != bsize:
        raise ParseError("los dos tamaños del bloque de firma no coinciden")
    pairs: dict[int, bytes] = {}
    off, end = 8, len(block) - 24
    while off + 12 <= end and len(pairs) < 64:
        ln, pid = struct.unpack_from("<QI", block, off)
        if ln < 4 or off + 8 + ln > end:
            raise ParseError("par ID-valor del bloque de firma inválido")
        pairs[pid] = block[off + 12:off + 8 + ln]
        off += 8 + ln
    return pairs


def _signers(value: bytes, scheme: str) -> list[dict[str, Any]]:
    out = []
    for signer in _seq(_lp(value, 0, len(value))[0]):
        signed_data, off = _lp(signer, 0, len(signer))
        info: dict[str, Any] = {}
        if scheme != "v2" and off + 8 <= len(signer):
            info["min_sdk"], info["max_sdk"] = struct.unpack_from("<II", signer, off)
        digests, o = _lp(signed_data, 0, len(signed_data))
        certs, o = _lp(signed_data, o, len(signed_data))
        info["digest_algorithms"] = [hex(struct.unpack_from("<I", d, 0)[0]) for d in _seq(digests) if len(d) >= 4]
        info["certificates"] = []
        for c in _seq(certs):
            try:
                info["certificates"].append(parse_certificate_der(c))
            except (ParseError, IndexError):
                info["certificates"].append({"error": "certificado ilegible"})
        if scheme != "v2" and o + 8 <= len(signed_data):
            o += 8   # min/max SDK firmados
            attrs, _ = _lp(signed_data, o, len(signed_data)) if o + 4 <= len(signed_data) else (b"", o)
            info["key_rotation"] = any(len(a) >= 4 and struct.unpack_from("<I", a, 0)[0] == ROTATION_ATTR
                                       for a in _seq(attrs))
        out.append(info)
    return out


def _brief(cert: dict[str, Any]) -> dict[str, Any]:
    return {k: cert.get(k) for k in ("subject", "issuer", "not_before", "not_after", "sha256", "key_algorithm",
                                     "signature_algorithm", "self_signed")}


def apk_signature(path: str | Path, zf: zipfile.ZipFile | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"schemes": [], "signers": [], "findings": []}
    # v1: firma JAR en META-INF
    if zf is not None:
        for n in zf.namelist():
            if n.startswith("META-INF/") and n.upper().endswith((".RSA", ".DSA", ".EC")) and n.count("/") == 1:
                out["schemes"].append("v1")
                try:
                    if zf.getinfo(n).file_size > MAX_SIG_BYTES:   # bomba ZIP: no se descomprime
                        raise ValueError("demasiado grande")
                    p7 = parse_pkcs7(zf.read(n))
                    out["signers"] += [{"scheme": "v1", **_brief(c)} for c in p7["certificates"][:3]]
                except (ParseError, IndexError, ValueError, zipfile.BadZipFile, RuntimeError, NotImplementedError,
                        OSError, EOFError):   # entradas «cifradas», comprimidas con métodos raros o truncadas
                    out["findings"].append(f"firma v1 ilegible en {n}")
                break
    try:
        pairs = signing_block(path)
    except ParseError as exc:
        pairs = None
        out["findings"].append(f"bloque de firma APK inválido: {exc}")
    if pairs:
        out["block_ids"] = [IDS.get(k, hex(k)) for k in pairs]
        for pid, scheme in ((0x7109871A, "v2"), (0xF05368C0, "v3"), (0x1B93AD61, "v3.1")):
            if pid in pairs:
                out["schemes"].append(scheme)
                try:
                    for s in _signers(pairs[pid], scheme):
                        for c in s.pop("certificates"):
                            out["signers"].append({"scheme": scheme, **s, **_brief(c)})
                except (ParseError, struct.error) as exc:
                    out["findings"].append(f"firma {scheme} ilegible: {exc}")
    if Path(str(path) + ".idsig").is_file():
        out["schemes"].append("v4")
    out["schemes"] = list(dict.fromkeys(out["schemes"]))
    shas = {s.get("sha256") for s in out["signers"] if s.get("sha256")}
    out["certificate_sha256"] = sorted(shas)
    if not out["schemes"]:
        out["findings"].append("APK sin firma: Android no lo instalará")
    elif out["schemes"] == ["v1"]:
        out["findings"].append("Solo firma v1 (JAR): vulnerable a Janus en Android 5–7; usa también v2 o v3")
    if any("Android Debug" in (s.get("subject") or "") for s in out["signers"]):
        out["findings"].append("Firmado con el certificado de depuración de Android (CN=Android Debug)")
    if len(shas) > 1 and not any(s.get("key_rotation") for s in out["signers"]):
        out["findings"].append("Certificados distintos entre esquemas sin rotación de claves declarada")
    return out
