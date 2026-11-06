"""iOS/IPA (Fase E, grupo 2): Info.plist, firma de código (identificador, Team ID, entitlements, certificados),
embedded.mobileprovision y cifrado FairPlay (cryptid). Solo stdlib (plistlib lee plist binarios y XML).

Se LEEN los datos de la firma; NO se verifica criptográficamente (para eso, `codesign -v` en macOS).
"""
from __future__ import annotations

import plistlib
import re
import struct
import zipfile
from datetime import datetime
from typing import Any

from eolfi.providers.binfmt import ParseError
from eolfi.providers.der import parse_pkcs7

CSMAGIC_EMBEDDED = 0xFADE0CC0
CSMAGIC_CODEDIRECTORY = 0xFADE0C02
CSMAGIC_ENTITLEMENTS = 0xFADE7171
CSMAGIC_DER_ENTITLEMENTS = 0xFADE7172
CSMAGIC_BLOBWRAPPER = 0xFADE0B01
HASH_TYPES = {1: "sha1", 2: "sha256", 3: "sha256-truncated", 4: "sha384"}
MAX_EXEC_BYTES = 256 * 1024 * 1024
MAX_META_BYTES = 8 * 1024 * 1024   # Info.plist y perfil de aprovisionamiento: unos KB en la práctica


def _read_capped(zf, name: str, cap: int = MAX_META_BYTES) -> bytes:
    """Lee una entrada del ZIP solo si su tamaño descomprimido es razonable (bomba ZIP)."""
    if zf.getinfo(name).file_size > cap:
        raise ParseError(f"{name}: {zf.getinfo(name).file_size} bytes descomprimidos (máximo {cap})")
    return zf.read(name)
SENSITIVE_ENTITLEMENTS = ("get-task-allow", "com.apple.private.", "platform-application",
                          "com.apple.security.cs.disable-library-validation", "com.apple.security.get-task-allow")


def _plist(data: bytes) -> dict[str, Any]:
    try:
        v = plistlib.loads(data)
    except (plistlib.InvalidFileException, ValueError, OverflowError, struct.error, ExpatError):
        return {}
    return v if isinstance(v, dict) else {}


try:
    from xml.parsers.expat import ExpatError
except ImportError:  # pragma: no cover
    ExpatError = ValueError  # type: ignore[misc,assignment]


def _jsonable(v: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "…"
    if isinstance(v, dict):
        return {str(k)[:120]: _jsonable(x, depth + 1) for k, x in list(v.items())[:200]}
    if isinstance(v, list):
        return [_jsonable(x, depth + 1) for x in v[:200]]
    if isinstance(v, bytes):
        return f"<{len(v)} bytes>"
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, str):
        return v[:500]
    return v


def code_signature(data: bytes, off: int, size: int) -> dict[str, Any]:
    """SuperBlob de la firma de código (big endian) en LC_CODE_SIGNATURE."""
    if off + 12 > len(data) or size < 12:
        raise ParseError("firma de código fuera del ejecutable")
    magic, length, count = struct.unpack_from(">III", data, off)
    if magic != CSMAGIC_EMBEDDED:
        raise ParseError(f"SuperBlob con magia {magic:#x}")
    end = min(off + length, off + size, len(data))
    out: dict[str, Any] = {}
    for k in range(min(count, 64)):
        btype, boff = struct.unpack_from(">II", data, off + 12 + 8 * k)
        b = off + boff
        if b + 8 > end:
            continue
        bmagic, blen = struct.unpack_from(">II", data, b)
        body = bytes(data[b:min(b + blen, end)])
        if bmagic == CSMAGIC_CODEDIRECTORY and "identifier" not in out and len(body) >= 44:
            version, flags = struct.unpack_from(">II", body, 8)
            ident_off = struct.unpack_from(">I", body, 20)[0]
            hash_type = body[37]
            out["identifier"] = body[ident_off:body.find(b"\x00", ident_off)].decode("utf-8", "replace")[:200]
            out["code_directory_version"] = hex(version)
            out["hash_type"] = HASH_TYPES.get(hash_type, str(hash_type))
            out["flags"] = {"adhoc": bool(flags & 0x2), "runtime": bool(flags & 0x10000),
                            "linker_signed": bool(flags & 0x20000)}
            if version >= 0x20200 and len(body) >= 52:
                team_off = struct.unpack_from(">I", body, 48)[0]
                if team_off:
                    out["team_id"] = body[team_off:body.find(b"\x00", team_off)].decode("ascii", "replace")[:40]
        elif bmagic == CSMAGIC_ENTITLEMENTS:
            out["entitlements"] = _jsonable(_plist(body[8:]))
        elif bmagic == CSMAGIC_BLOBWRAPPER and len(body) > 8:
            try:
                p7 = parse_pkcs7(body[8:])
                out["certificates"] = [{k2: c[k2] for k2 in ("subject", "issuer", "not_after", "sha256")}
                                       for c in p7["certificates"][:5]]
            except (ParseError, IndexError, ValueError):
                out["certificates_error"] = "firma CMS ilegible"
    if "certificates" not in out and "identifier" in out:
        out["signed_by"] = "ad-hoc (sin certificado)" if out.get("flags", {}).get("adhoc") else None
    return out


def mobileprovision(data: bytes) -> dict[str, Any]:
    """El perfil es un CMS que envuelve un plist XML: se extrae el plist sin verificar la firma."""
    m = re.search(rb"<\?xml.*?</plist>", data, re.S)
    p = _plist(m.group(0)) if m else {}
    if not p:
        return {"error": "perfil de aprovisionamiento ilegible"}
    ent = p.get("Entitlements") or {}
    devices = p.get("ProvisionedDevices") or []
    kind = ("enterprise" if p.get("ProvisionsAllDevices") else
            "development" if ent.get("get-task-allow") else "ad-hoc" if devices else "app-store")
    return {"name": p.get("Name"), "app_id_name": p.get("AppIDName"), "team_id": (p.get("TeamIdentifier") or [None])[0],
            "team_name": p.get("TeamName"), "expiration": _jsonable(p.get("ExpirationDate")),
            "creation": _jsonable(p.get("CreationDate")), "provisioned_devices": len(devices),
            "distribution": kind, "entitlements": _jsonable(ent)}


def analyze_ipa(zf: zipfile.ZipFile, names: list[str]) -> dict[str, Any]:
    from eolfi.providers.macho import parse_macho

    apps = sorted({m.group(1) for n in names if (m := re.match(r"^(Payload/[^/]+\.app)/", n))})
    if not apps:
        return {"error": "sin Payload/*.app"}
    app = apps[0]
    out: dict[str, Any] = {"app": app.split("/", 1)[1], "findings": []}
    info = _plist(_read_capped(zf, f"{app}/Info.plist")) if f"{app}/Info.plist" in names else {}
    ats = info.get("NSAppTransportSecurity") or {}
    out["info"] = {
        "bundle_id": info.get("CFBundleIdentifier"), "name": info.get("CFBundleDisplayName") or info.get("CFBundleName"),
        "version": info.get("CFBundleShortVersionString"), "build": info.get("CFBundleVersion"),
        "executable": info.get("CFBundleExecutable"), "min_os": info.get("MinimumOSVersion"),
        "platforms": info.get("CFBundleSupportedPlatforms"), "device_family": info.get("UIDeviceFamily"),
        "url_schemes": [s for t in info.get("CFBundleURLTypes") or [] if isinstance(t, dict)
                        for s in t.get("CFBundleURLSchemes") or []][:30],
        "queried_schemes": (info.get("LSApplicationQueriesSchemes") or [])[:50],
        "privacy_usage": sorted(k for k in info if k.startswith("NS") and k.endswith("UsageDescription")),
        "background_modes": info.get("UIBackgroundModes"),
        "ats": _jsonable(ats),
    }
    if ats.get("NSAllowsArbitraryLoads"):
        out["findings"].append("App Transport Security desactivado (NSAllowsArbitraryLoads): permite HTTP sin cifrar")
    if f"{app}/embedded.mobileprovision" in names:
        mp = mobileprovision(_read_capped(zf, f"{app}/embedded.mobileprovision"))
        out["provisioning"] = mp
        if mp.get("distribution") == "enterprise":
            out["findings"].append("Perfil empresarial (se instala en cualquier dispositivo sin App Store)")
        if (mp.get("entitlements") or {}).get("get-task-allow"):
            out["findings"].append("get-task-allow activo: la app se puede depurar (compilación de desarrollo)")
    exe = info.get("CFBundleExecutable")
    path = f"{app}/{exe}" if exe else None
    if path and path in names and zf.getinfo(path).file_size <= MAX_EXEC_BYTES:
        data = zf.read(path)
        try:
            mach = parse_macho(data)
            sl = next((s for s in mach["slices"] if "error" not in s), None)
            if sl:
                out["executable"] = {"archs": [s["headers"]["cpu"] for s in mach["slices"] if "headers" in s],
                                     "encrypted": sl["security"].get("encrypted"),
                                     "pie": sl["security"].get("pie"), "swift": sl["security"].get("swift")}
                if sl["security"].get("encrypted"):
                    out["findings"].append("Ejecutable cifrado con FairPlay (cryptid=1): el código no se puede analizar "
                                           "sin descifrarlo en un dispositivo")
                cs = sl["security"].get("code_signature_range")
                if cs:
                    try:
                        out["signature"] = code_signature(data, cs[0], cs[1])
                    except (ParseError, struct.error) as exc:
                        out["signature"] = {"error": str(exc)}
                    ents = (out["signature"] or {}).get("entitlements") or {}
                    risky = [k for k in ents if any(k.startswith(s) for s in SENSITIVE_ENTITLEMENTS) and ents[k]]
                    if risky:
                        out["findings"].append(f"Entitlements sensibles: {', '.join(risky[:8])}")
                else:
                    out["findings"].append("Ejecutable sin firma de código")
        except ParseError as exc:
            out["executable"] = {"error": str(exc)}
    out["frameworks"] = sorted({m.group(1) for n in names if (m := re.match(re.escape(app) + r"/Frameworks/([^/]+)/", n))})[:100]
    out["app_extensions"] = sorted({m.group(1) for n in names if (m := re.match(re.escape(app) + r"/PlugIns/([^/]+)/", n))})[:50]
    return out
