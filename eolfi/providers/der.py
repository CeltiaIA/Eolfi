"""DER, X.509 y PKCS#7 mínimos (solo stdlib) para leer firmas: Authenticode, APK y Apple.

Se LEEN los campos (sujeto, emisor, número de serie, validez, huellas y algoritmos). No se valida la cadena
de confianza ni la firma criptográfica: eso exige un almacén de raíces y RSA/ECDSA, fuera de la stdlib. Los
resultados lo dicen siempre en sus limitaciones.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Iterator

from eolfi.providers.binfmt import ParseError

MAX_DEPTH = 64

OID_NAMES = {
    "2.5.4.3": "CN", "2.5.4.6": "C", "2.5.4.7": "L", "2.5.4.8": "ST", "2.5.4.10": "O", "2.5.4.11": "OU",
    "1.2.840.113549.1.9.1": "emailAddress", "0.9.2342.19200300.100.1.1": "UID",
    # algoritmos
    "1.2.840.113549.1.1.1": "rsaEncryption", "1.2.840.113549.1.1.5": "sha1WithRSA",
    "1.2.840.113549.1.1.11": "sha256WithRSA", "1.2.840.113549.1.1.12": "sha384WithRSA",
    "1.2.840.113549.1.1.13": "sha512WithRSA", "1.2.840.10045.2.1": "ecPublicKey",
    "1.2.840.10045.4.3.2": "ecdsaWithSHA256", "1.2.840.10045.4.3.3": "ecdsaWithSHA384",
    "1.3.14.3.2.26": "sha1", "2.16.840.1.101.3.4.2.1": "sha256", "2.16.840.1.101.3.4.2.2": "sha384",
    "2.16.840.1.101.3.4.2.3": "sha512", "1.2.840.113549.2.5": "md5",
    # PKCS#7 / Authenticode
    "1.2.840.113549.1.7.2": "signedData", "1.3.6.1.4.1.311.2.1.4": "spcIndirectDataContent",
    "1.3.6.1.4.1.311.2.1.15": "spcPeImageData",
}
HASHES = {"sha1": "sha1", "sha256": "sha256", "sha384": "sha384", "sha512": "sha512", "md5": "md5"}


class Node:
    __slots__ = ("tag", "start", "hlen", "length", "data")

    def __init__(self, tag: int, start: int, hlen: int, length: int, data: bytes):
        self.tag, self.start, self.hlen, self.length, self.data = tag, start, hlen, length, data

    @property
    def raw(self) -> bytes:
        """El TLV completo (cabecera + contenido), p. ej. para la huella de un certificado."""
        return self.data[self.start:self.start + self.hlen + self.length]

    @property
    def value(self) -> bytes:
        return self.data[self.start + self.hlen:self.start + self.hlen + self.length]

    @property
    def constructed(self) -> bool:
        return bool(self.tag & 0x20)

    def children(self) -> list["Node"]:
        if not self.constructed:
            return []
        return list(iter_tlv(self.data, self.start + self.hlen, self.start + self.hlen + self.length))


def read_tlv(data: bytes, off: int, end: int | None = None) -> Node:
    end = len(data) if end is None else end
    if off + 2 > end:
        raise ParseError("DER truncado")
    tag = data[off]
    if tag & 0x1F == 0x1F:
        raise ParseError("etiquetas DER de varios bytes no admitidas")
    first = data[off + 1]
    if first < 0x80:
        length, hlen = first, 2
    else:
        n = first & 0x7F
        if n == 0 or n > 4 or off + 2 + n > end:
            raise ParseError("longitud DER inválida (o indefinida, que DER no permite)")
        length, hlen = int.from_bytes(data[off + 2:off + 2 + n], "big"), 2 + n
    if off + hlen + length > end:
        raise ParseError("DER: el contenido sale de su contenedor")
    return Node(tag, off, hlen, length, data)


def iter_tlv(data: bytes, off: int, end: int) -> Iterator[Node]:
    count = 0
    while off < end:
        n = read_tlv(data, off, end)
        yield n
        off += n.hlen + n.length
        count += 1
        if count > 100_000:
            raise ParseError("demasiados elementos DER")


def oid(value: bytes) -> str:
    if not value:
        return ""
    parts = [value[0] // 40, value[0] % 40] if value[0] < 80 else [2, value[0] - 80]
    acc = 0
    for b in value[1:]:
        acc = (acc << 7) | (b & 0x7F)
        if not b & 0x80:
            parts.append(acc)
            acc = 0
    return ".".join(map(str, parts))


def oid_name(value: bytes) -> str:
    o = oid(value)
    return OID_NAMES.get(o, o)


def _text(n: Node) -> str:
    v = n.value
    if n.tag == 0x1E:   # BMPString
        return v.decode("utf-16-be", "replace")
    return v.decode("utf-8" if n.tag == 0x0C else "latin-1", "replace")


def name_to_dict(n: Node) -> dict[str, str]:
    out: dict[str, str] = {}
    for rdn in n.children():
        for atv in rdn.children():
            kids = atv.children()
            if len(kids) >= 2 and kids[0].tag == 0x06:
                key = oid_name(kids[0].value)
                out[key] = (out[key] + ", " if key in out else "") + _text(kids[1])[:300]
    return out


def name_to_str(d: dict[str, str]) -> str:
    order = ["CN", "O", "OU", "L", "ST", "C"]
    keys = [k for k in order if k in d] + [k for k in d if k not in order]
    return ", ".join(f"{k}={d[k]}" for k in keys)


def _time(n: Node) -> str | None:
    s = n.value.decode("ascii", "replace")
    try:
        if n.tag == 0x17:   # UTCTime
            t = datetime.strptime(s, "%y%m%d%H%M%SZ")
        else:
            t = datetime.strptime(s, "%Y%m%d%H%M%SZ")
        return t.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return s[:40] or None


def parse_certificate(cert: Node) -> dict[str, Any]:
    """Certificate ::= SEQUENCE { tbsCertificate, signatureAlgorithm, signatureValue }."""
    parts = cert.children()
    if len(parts) < 3:
        raise ParseError("certificado X.509 incompleto")
    tbs = parts[0].children()
    i = 1 if tbs and tbs[0].tag == 0xA0 else 0   # [0] version
    if len(tbs) < i + 6:
        raise ParseError("TBSCertificate incompleto")
    serial, _sigalg, issuer, validity, subject, spki = tbs[i:i + 6]
    vals = validity.children()
    key_alg = spki.children()[0].children()[0].value if spki.children() and spki.children()[0].children() else b""
    sub, iss = name_to_dict(subject), name_to_dict(issuer)
    return {
        "subject": name_to_str(sub), "issuer": name_to_str(iss),
        "subject_cn": sub.get("CN"), "issuer_cn": iss.get("CN"),
        "serial": serial.value.hex(),
        "not_before": _time(vals[0]) if vals else None, "not_after": _time(vals[1]) if len(vals) > 1 else None,
        "signature_algorithm": oid_name(parts[1].children()[0].value) if parts[1].children() else None,
        "key_algorithm": oid_name(key_alg),
        "self_signed": sub == iss,
        "sha256": hashlib.sha256(cert.raw).hexdigest(),
        "sha1": hashlib.sha1(cert.raw).hexdigest(),
    }


def parse_certificate_der(data: bytes) -> dict[str, Any]:
    return parse_certificate(read_tlv(data, 0))


def parse_pkcs7(data: bytes) -> dict[str, Any]:
    """ContentInfo(signedData): algoritmos de resumen, contenido (p. ej. SpcIndirectData), certificados y
    datos de cada firmante (emisor + serie del certificado que firma)."""
    top = read_tlv(data, 0)
    kids = top.children()
    if len(kids) < 2 or oid_name(kids[0].value) != "signedData":
        raise ParseError("no es un PKCS#7 signedData")
    sd = kids[1].children()[0].children()   # [0] EXPLICIT SignedData
    if len(sd) < 3:
        raise ParseError("SignedData incompleto")
    digests = [oid_name(a.children()[0].value) for a in sd[1].children() if a.children()]
    content = sd[2].children()
    content_type = oid_name(content[0].value) if content else None
    content_node = content[1].children()[0] if len(content) > 1 and content[1].children() else None
    certs, signers = [], []
    for n in sd[3:]:
        if n.tag == 0xA0:   # [0] IMPLICIT certificates
            for c in n.children():
                try:
                    certs.append(parse_certificate(c))
                except (ParseError, IndexError):
                    continue
        elif n.tag == 0x31:   # SignerInfos
            for si in n.children():
                f = si.children()
                if len(f) >= 3 and f[1].tag == 0x30:
                    ias = f[1].children()
                    signers.append({"issuer": name_to_str(name_to_dict(ias[0])) if ias else None,
                                    "serial": ias[1].value.hex() if len(ias) > 1 else None,
                                    "digest_algorithm": oid_name(f[2].children()[0].value) if f[2].children() else None})
    return {"digest_algorithms": digests, "content_type": content_type, "content": content_node,
            "certificates": certs, "signers": signers}
