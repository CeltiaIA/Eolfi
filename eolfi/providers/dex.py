"""Analizador DEX (Android) y de contenedores ZIP (APK/AAR/JAR/IPA/XAPK).

- DEX: cabecera, tamaños de tablas, checksum Adler-32 verificado, nombres de
  clases y paquetes principales.
- ZIP: inventario de entradas, tipo de paquete deducido, firmas, librerías
  nativas por ABI y análisis de cada classes*.dex interno (sin extraer a
  disco: se lee en memoria con límites).
"""
from __future__ import annotations

import struct
import zipfile
import zlib
from collections import Counter
from pathlib import Path
from typing import Any

from eolfi.providers.base import Provider
from eolfi.providers.binfmt import ParseError, Reader

MAX_CLASSES = 20000
MAX_DEX_IN_ZIP = 16
MAX_DEX_BYTES = 128 * 1024 * 1024
MAX_ZIP_ENTRIES = 50000


def _uleb128(r: Reader, off: int) -> tuple[int, int]:
    result = shift = 0
    for i in range(5):
        b = r.u8(off + i)
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, off + i + 1
        shift += 7
    raise ParseError("uleb128 demasiado largo")


def _descriptor_to_name(desc: str) -> str:
    if desc.startswith("L") and desc.endswith(";"):
        return desc[1:-1].replace("/", ".")
    return desc


MAX_METHODS_SCANNED = 300_000
MAX_STRINGS_SCANNED = 300_000
# APIs que conviene ver en una auditoría (clase.método → qué indica).
SENSITIVE_APIS = {
    "java.lang.Runtime.exec": "ejecuta comandos (Runtime.exec)",
    "java.lang.ProcessBuilder.start": "ejecuta comandos (ProcessBuilder)",
    "dalvik.system.DexClassLoader.<init>": "carga código en tiempo de ejecución (DexClassLoader)",
    "dalvik.system.InMemoryDexClassLoader.<init>": "carga código desde memoria (InMemoryDexClassLoader)",
    "dalvik.system.PathClassLoader.<init>": "carga código (PathClassLoader)",
    "java.lang.System.loadLibrary": "carga bibliotecas nativas (System.loadLibrary)",
    "java.lang.System.load": "carga bibliotecas nativas desde una ruta (System.load)",
    "java.lang.reflect.Method.invoke": "reflexión (Method.invoke)",
    "java.lang.Class.forName": "reflexión (Class.forName)",
    "javax.crypto.Cipher.getInstance": "criptografía (Cipher)",
    "java.security.MessageDigest.getInstance": "resúmenes criptográficos (MessageDigest)",
    "android.webkit.WebView.addJavascriptInterface": "puente JavaScript en WebView (addJavascriptInterface)",
    "android.webkit.WebSettings.setJavaScriptEnabled": "JavaScript en WebView",
    "android.telephony.SmsManager.sendTextMessage": "envía SMS",
    "android.telephony.TelephonyManager.getDeviceId": "lee el IMEI (getDeviceId)",
    "android.telephony.TelephonyManager.getLine1Number": "lee el número de teléfono",
    "android.location.LocationManager.getLastKnownLocation": "ubicación",
    "android.content.pm.PackageManager.getInstalledPackages": "lista las apps instaladas",
    "android.app.admin.DevicePolicyManager.lockNow": "administración del dispositivo",
    "android.accessibilityservice.AccessibilityService.performGlobalAction": "accesibilidad: acciones globales",
    "javax.net.ssl.HttpsURLConnection.setDefaultHostnameVerifier": "cambia la verificación TLS (HostnameVerifier)",
    "android.util.Base64.decode": "decodifica Base64",
}


def parse_dex(data: bytes) -> dict[str, Any]:
    r = Reader(data)
    magic = r.raw(0, 8)
    if magic[:4] != b"dex\n" or magic[7:8] != b"\x00":
        raise ParseError("sin firma DEX")
    version = magic[4:7].decode("ascii", "replace")
    checksum = r.u32(8)
    file_size, header_size, endian_tag = r.u32(32), r.u32(36), r.u32(40)
    if endian_tag != 0x12345678:
        raise ParseError(f"endian_tag={endian_tag:#x} no soportado")
    counts = {
        "strings": r.u32(56), "types": r.u32(64), "protos": r.u32(72),
        "fields": r.u32(80), "methods": r.u32(88), "classes": r.u32(96),
    }
    string_ids_off, type_ids_off, class_defs_off = r.u32(60), r.u32(68), r.u32(100)
    computed = zlib.adler32(bytes(data[12:file_size])) if file_size <= r.size else None

    def string_at(idx: int) -> str:
        if idx >= counts["strings"]:
            raise ParseError(f"string_id {idx} fuera de rango")
        sdata = r.u32(string_ids_off + idx * 4)
        _length, start = _uleb128(r, sdata)
        return r.cstr(start, 1024)    # MUTF-8; los nombres de clase son ASCII en la práctica

    classes: list[str] = []
    errors: list[str] = []
    try:
        for i in range(min(counts["classes"], MAX_CLASSES)):
            type_idx = r.u32(class_defs_off + i * 32)
            if type_idx >= counts["types"]:
                raise ParseError(f"class_idx {type_idx} fuera de rango")
            classes.append(_descriptor_to_name(string_at(r.u32(type_ids_off + type_idx * 4))))
    except ParseError as exc:
        errors.append(str(exc))

    # DEX completo (Fase E): métodos referenciados → APIs sensibles; URLs del pool de cadenas; firma SHA-1.
    api_hits: dict[str, int] = {}
    method_ids_off = r.u32(92)
    try:
        type_names: dict[int, str] = {}

        def tname(t: int) -> str:
            if t not in type_names:
                type_names[t] = _descriptor_to_name(string_at(r.u32(type_ids_off + t * 4))) if t < counts["types"] else "?"
            return type_names[t]

        for i in range(min(counts["methods"], MAX_METHODS_SCANNED)):
            m = method_ids_off + i * 8
            cls_idx, name_idx = r.u16(m), r.u32(m + 4)
            key = f"{tname(cls_idx)}.{string_at(name_idx)}"
            label = SENSITIVE_APIS.get(key)
            if label:
                api_hits[label] = api_hits.get(label, 0) + 1
    except ParseError as exc:
        errors.append(f"métodos: {exc}")
    urls: list[str] = []
    try:
        for i in range(min(counts["strings"], MAX_STRINGS_SCANNED)):
            s = string_at(i)
            if s.startswith(("http://", "https://")) and len(urls) < 100:
                urls.append(s[:200])
    except ParseError as exc:
        errors.append(f"cadenas: {exc}")
    import hashlib as _hl

    sha1_ok = _hl.sha1(bytes(data[32:file_size])).digest() == bytes(data[12:32]) if file_size <= r.size else None
    packages = Counter(c.rsplit(".", 1)[0] if "." in c else "(raíz)" for c in classes)
    top = Counter()
    for pkg, n in packages.items():
        top[".".join(pkg.split(".")[:2])] += n
    return {
        "version": version,
        "file_size": file_size,
        "header_size": header_size,
        "checksum_ok": computed == checksum if computed is not None else None,
        "signature_sha1_ok": sha1_ok,
        "sensitive_apis": dict(sorted(api_hits.items())),
        "urls": urls,
        "cleartext_urls": [u for u in urls if u.startswith("http://")][:30],
        "counts": counts,
        "top_packages": [{"package": p, "classes": n} for p, n in top.most_common(25)],
        "class_sample": classes[:200],
        "classes_truncated": counts["classes"] > MAX_CLASSES,
        "obfuscation_hint": _obfuscation_hint(classes),
        "errors": errors,
    }


def _obfuscation_hint(classes: list[str]) -> dict[str, Any]:
    """Proporción de clases con nombre de 1-2 letras (típico de R8/ProGuard)."""
    if not classes:
        return {"short_name_ratio": 0.0, "likely_obfuscated": False}
    short = sum(1 for c in classes if len(c.rsplit(".", 1)[-1].split("$")[0]) <= 2)
    ratio = round(short / len(classes), 3)
    return {"short_name_ratio": ratio, "likely_obfuscated": ratio > 0.4}


# Errores al leer UNA entrada del ZIP: no deben tumbar el inventario entero. Los APK maliciosos
# suelen marcar entradas como cifradas (Android lo ignora; zipfile lanza RuntimeError).
ZIP_ENTRY_ERRORS = (ParseError, zipfile.BadZipFile, zipfile.LargeZipFile, zlib.error, RuntimeError,
                    NotImplementedError, EOFError, ValueError, OSError)


def _entry_error(exc: BaseException) -> str:
    if isinstance(exc, RuntimeError) and "encrypt" in str(exc).lower():
        return "entrada marcada como cifrada (truco anti-análisis habitual): no se puede leer"
    if isinstance(exc, NotImplementedError):
        return f"compresión no soportada: {exc}"
    return f"{type(exc).__name__}: {exc}"


def _eocd_entries(path: str | Path) -> int | None:
    """Nº de entradas según el directorio central, leyendo solo el final del archivo: así un ZIP con
    millones de entradas se rechaza ANTES de que zipfile cargue el directorio entero en memoria (B9)."""
    import struct

    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - 65_557))
        tail = fh.read()
    i = tail.rfind(b"PK\x05\x06")
    if i < 0 or i + 22 > len(tail):
        return None
    total = struct.unpack_from("<H", tail, i + 10)[0]
    return None if total == 0xFFFF else total   # 0xFFFF: ZIP64, el recuento real está en otro registro


def analyze_zip(path: str | Path) -> dict[str, Any]:
    declared = _eocd_entries(path)
    if declared is not None and declared > MAX_ZIP_ENTRIES:
        raise ParseError(f"{declared} entradas superan {MAX_ZIP_ENTRIES}")
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise ParseError(f"{len(infos)} entradas superan {MAX_ZIP_ENTRIES}")
        names = [i.filename for i in infos]
        nameset = set(names)
        # Entradas repetidas o con rutas peligrosas (tipo Janus): Eolfi lee una copia y Android otra (M20).
        dup = sorted(n for n, c in Counter(names).items() if c > 1)
        unsafe = sorted({n for n in names if n.startswith(("/", "\\")) or "\\" in n or ".." in n.split("/")
                         or (len(n) > 1 and n[1] == ":")})[:50]
        anomalies: list[str] = []
        if dup:
            critical = [n for n in dup if n == "AndroidManifest.xml" or n.endswith(".dex") or n == "resources.arsc"]
            anomalies.append(("Entradas duplicadas en el ZIP: " + ", ".join(dup[:10])
                              + (" (afecta a archivos clave: el analizador y Android pueden leer copias distintas)"
                                 if critical else "")))
        if unsafe:
            anomalies.append("Rutas peligrosas en el ZIP (../, absolutas o con \\): " + ", ".join(unsafe[:10]))
        if "AndroidManifest.xml" in nameset and any(n.startswith("classes") and n.endswith(".dex") for n in names):
            kind = "apk"
        elif "AndroidManifest.xml" in nameset and "classes.jar" in nameset:
            kind = "aar"
        elif any(n.startswith("Payload/") and ".app/" in n for n in names):
            kind = "ipa"
        elif "META-INF/MANIFEST.MF" in nameset or any(n.endswith(".class") for n in names[:2000]):
            kind = "jar"
        elif "manifest.json" in nameset and any(n.endswith(".apk") for n in names):
            kind = "xapk"
        else:
            kind = "zip"

        ext = Counter(Path(n).suffix.lower() or "(sin extensión)" for n in names if not n.endswith("/"))
        native: dict[str, list[str]] = {}
        for n in names:
            parts = n.split("/")
            if len(parts) == 3 and parts[0] == "lib" and parts[2].endswith(".so"):
                native.setdefault(parts[1], []).append(parts[2])
        signatures = [n for n in names if n.startswith("META-INF/") and n.upper().endswith((".RSA", ".DSA", ".EC", ".SF"))]

        total_unc = sum(i.file_size for i in infos)
        total_cmp = sum(i.compress_size for i in infos) or 1
        dex_results = {}
        for n in [n for n in names if n.endswith(".dex")][:MAX_DEX_IN_ZIP]:
            info = zf.getinfo(n)
            if info.file_size > MAX_DEX_BYTES:
                dex_results[n] = {"error": "demasiado grande"}
                continue
            try:
                dex_results[n] = parse_dex(zf.read(n))
            except ZIP_ENTRY_ERRORS as exc:
                dex_results[n] = {"error": _entry_error(exc)}

        manifest = None
        if "AndroidManifest.xml" in nameset:
            info_m = zf.getinfo("AndroidManifest.xml")
            try:
                raw = zf.read("AndroidManifest.xml") if info_m.file_size < 8 * 1024 * 1024 else b""
            except ZIP_ENTRY_ERRORS as exc:
                raw, manifest = b"", {"error": _entry_error(exc)}
            if raw[:2] == b"\x03\x00":
                from eolfi.providers.axml import parse_axml, summarize_manifest
                try:
                    manifest = summarize_manifest(parse_axml(raw))
                except ParseError as exc:
                    manifest = {"error": str(exc)}
                if "error" not in manifest and "resources.arsc" in nameset                         and zf.getinfo("resources.arsc").file_size < 64 * 1024 * 1024:
                    from eolfi.providers.arsc import resolve_refs
                    try:
                        manifest["resources"] = resolve_refs(manifest, zf.read("resources.arsc"))
                        label = manifest["application"].get("label")
                        if isinstance(label, str) and label in manifest["resources"]:
                            manifest["app_label"] = manifest["resources"][label]["value"]
                        elif isinstance(label, str) and not label.startswith("@"):
                            manifest["app_label"] = label
                    except ZIP_ENTRY_ERRORS as exc:
                        manifest["resources_error"] = _entry_error(exc)
            elif raw.lstrip().startswith(b"<"):
                manifest = {"note": "manifiesto en XML de texto (AAR/proyecto fuente)"}
        if anomalies and isinstance(manifest, dict):
            manifest.setdefault("security_findings", []).extend(anomalies)
        signature = None
        if kind == "apk":
            from eolfi.providers.apksig import apk_signature

            try:
                signature = apk_signature(path, zf)
            except (ParseError, OSError, struct.error) as exc:
                signature = {"error": str(exc)}
            if isinstance(manifest, dict) and signature.get("findings"):
                manifest.setdefault("security_findings", []).extend(signature["findings"])
        native_info = _native_libs(zf, names) if kind in ("apk", "aar") and native else None
        if isinstance(manifest, dict) and native_info:
            for abi, libs in native_info.items():
                bad = [n for n, x in libs.items() if abi in ("arm64-v8a", "x86_64") and x.get("aligned_16k") is False]
                if bad:
                    manifest.setdefault("security_findings", []).append(
                        f"Bibliotecas {abi} sin alineación de 16 KB (Android 15+ y Google Play la exigen): {', '.join(bad[:5])}")
        ios = None
        if kind == "ipa":
            from eolfi.providers.apple import analyze_ipa

            try:
                ios = analyze_ipa(zf, names)
            except ZIP_ENTRY_ERRORS as exc:
                ios = {"error": _entry_error(exc)}
        jar = None
        if kind in ("jar", "aar") or (kind == "zip" and any(n.startswith("WEB-INF/") for n in names[:2000])):
            from eolfi.providers.java import analyze_jar

            try:
                jar = analyze_jar(zf, names)
            except ZIP_ENTRY_ERRORS as exc:
                jar = {"error": _entry_error(exc)}
        return {
            "kind": kind,
            "zip_anomalies": {"duplicates": dup[:50], "unsafe_paths": unsafe, "findings": anomalies},
            **({"jar": jar} if jar is not None else {}),
            **({"ios": ios} if ios is not None else {}),
            **({"signature": signature} if signature is not None else {}),
            **({"native_analysis": native_info} if native_info else {}),
            "manifest": manifest,
            "entries": len(infos),
            "uncompressed_size": total_unc,
            "compression_ratio": round(total_unc / total_cmp, 2),
            "zip_bomb_suspect": total_unc > 50 * total_cmp and total_unc > 500 * 1024 * 1024,
            "extensions": dict(ext.most_common(20)),
            "native_libs": native,
            "signature_files": signatures,
            "notable": [n for n in names if n in (
                "AndroidManifest.xml", "resources.arsc", "META-INF/MANIFEST.MF",
                "assets/index.android.bundle", "assets/flutter_assets/AssetManifest.json",
            ) or n.endswith(("libflutter.so", "libapp.so", "libreactnativejni.so", "libunity.so",
                             "libil2cpp.so", "Assembly-CSharp.dll", "libmonodroid.so"))][:50],
            "frameworks": _mobile_frameworks(names) + [
                f for f in _dex_libraries(dex_results) if f not in _mobile_frameworks(names)],
            "dex": dex_results,
        }


MAX_NATIVE_LIBS = 40
MAX_NATIVE_BYTES = 64 * 1024 * 1024


def _native_libs(zf: zipfile.ZipFile, names: list[str]) -> dict[str, dict[str, Any]]:
    """lib/<abi>/*.so: JNI (exports Java_* y JNI_OnLoad), alineación de 16 KB, build-id y dependencias."""
    from eolfi.providers.binfmt import parse_elf

    out: dict[str, dict[str, Any]] = {}
    budget = 4 * MAX_NATIVE_BYTES
    for n in names:
        parts = n.split("/")
        if len(parts) != 3 or parts[0] != "lib" or not parts[2].endswith(".so"):
            continue
        if sum(len(v) for v in out.values()) >= MAX_NATIVE_LIBS:
            break
        info = zf.getinfo(n)
        entry: dict[str, Any] = {"size": info.file_size}
        if info.file_size > MAX_NATIVE_BYTES or info.file_size > budget:
            entry["error"] = "demasiado grande para analizarla"
        else:
            budget -= info.file_size
            try:
                elf = parse_elf(zf.read(n))
                exported = elf["dynamic"]["exported_symbols"]
                align = elf["headers"].get("load_alignment")
                entry.update({
                    "jni_exports": [s for s in exported if s.startswith("Java_")][:50],
                    "jni_onload": "JNI_OnLoad" in exported,
                    "load_alignment": hex(align) if align else None,
                    "aligned_16k": (align or 0) >= 0x4000,
                    "build_id": elf["headers"].get("build_id"),
                    "needed": elf["dynamic"]["needed"][:30],
                    "stripped": elf["security"].get("stripped"),
                    "relro": elf["security"].get("relro"), "stack_canary": elf["security"].get("stack_canary"),
                })
            except ZIP_ENTRY_ERRORS as exc:
                entry["error"] = _entry_error(exc)
        out.setdefault(parts[1], {})[parts[2]] = entry
    return out


def _mobile_frameworks(names: list[str]) -> list[str]:
    s = "\n".join(names)
    found = []
    for marker, fw in (
        ("libflutter.so", "Flutter"), ("flutter_assets", "Flutter"),
        ("index.android.bundle", "React Native"), ("libreactnativejni.so", "React Native"),
        ("libhermes.so", "React Native (Hermes)"), ("libunity.so", "Unity"),
        ("libil2cpp.so", "Unity IL2CPP"), ("libmonodroid.so", "Xamarin/.NET MAUI"),
        ("assets/www/cordova.js", "Cordova"), ("capacitor.config.json", "Capacitor"),
        ("kotlin/", "Kotlin"), ("libgodot_android.so", "Godot"),
    ):
        if marker in s and fw not in found:
            found.append(fw)
    return found


_DEX_LIBS = (
    ("androidx.compose", "Jetpack Compose"), ("androidx.room", "Room"), ("androidx.work", "WorkManager"),
    ("io.ktor", "Ktor"), ("okhttp3", "OkHttp"), ("retrofit2", "Retrofit"), ("dagger.hilt", "Hilt"),
    ("dagger", "Dagger"), ("com.google.firebase", "Firebase"), ("io.reactivex", "RxJava"),
    ("kotlinx.coroutines", "Kotlin Coroutines"), ("com.squareup.moshi", "Moshi"), ("com.google.gson", "Gson"),
    ("coil", "Coil"), ("com.bumptech.glide", "Glide"), ("io.realm", "Realm"), ("org.bouncycastle", "Bouncy Castle"),
    ("com.facebook.react", "React Native"), ("io.flutter", "Flutter"), ("com.unity3d", "Unity"),
)


def _dex_libraries(dex_results: dict[str, Any]) -> list[str]:
    """Librerías conocidas según los paquetes de clases presentes en los DEX."""
    pkgs = set()
    for d in dex_results.values():
        for tp in d.get("top_packages", []):
            pkgs.add(tp["package"])
        for c in d.get("class_sample", []):
            pkgs.add(".".join(c.split(".")[:3]))
    found = []
    for prefix, name in _DEX_LIBS:
        if any(p == prefix or p.startswith(prefix + ".") for p in pkgs) and name not in found:
            if name == "Dagger" and "Hilt" in found:
                continue
            found.append(name)
    return found


class AndroidJavaProvider(Provider):
    """DEX sueltos y contenedores ZIP (APK, AAR, JAR, IPA, XAPK)."""
    name = "eolfi.archive"
    version = "0.3.0"   # Fase E: firma APK, .so, DEX completo, Java/JAR e IPA

    def available(self) -> bool:
        return True

    def run(self, target: str) -> list[dict[str, Any]]:
        p = Path(target)
        with open(p, "rb") as fh:
            head = fh.read(8)
        if head.startswith(b"dex\n"):
            if p.stat().st_size > MAX_DEX_BYTES:   # no cargar en memoria un «DEX» de varios GB
                return [_fail("dex_parse_error", f"DEX de {p.stat().st_size} bytes: supera {MAX_DEX_BYTES}")]
            try:
                res = parse_dex(p.read_bytes())
            except ParseError as exc:
                return [_fail("dex_parse_error", str(exc))]
            return [{
                "operation": "dex_structure", "result": res, "authority": "distributed_artifact",
                "confidence": "high" if not res["errors"] else "medium",
                "limitations": "Solo cabecera y nombres de clase; no desensambla bytecode.",
            }]
        if head[:4] == b"\xca\xfe\xba\xbe" and int.from_bytes(head[4:8], "big") >= 45:   # clase Java suelta
            from eolfi.providers.java import parse_class

            if p.stat().st_size > 64 * 1024 * 1024:
                return [_fail("java_class_parse_error", "clase de más de 64 MB")]
            try:
                res = parse_class(p.read_bytes())
            except ParseError as exc:
                return [_fail("java_class_parse_error", str(exc))]
            return [{"operation": "java_class", "result": res, "authority": "distributed_artifact", "confidence": "high",
                     "limitations": "Pool de constantes y firmas; no se desensambla el bytecode."}]
        if head[:4] == b"\x03\x00\x08\x00":
            from eolfi.providers.axml import parse_axml, summarize_manifest
            try:
                with open(p, "rb") as fh:
                    els = parse_axml(fh.read(16 * 1024 * 1024))   # lee solo lo que se analiza
                res = summarize_manifest(els) if els and els[0]["tag"] == "manifest" else {
                    "elements": [{"tag": e["tag"], "attrs": e["attrs"]} for e in els[:500]]}
            except ParseError as exc:
                return [_fail("axml_parse_error", str(exc))]
            return [{"operation": "android_manifest" if "package" in res else "android_xml", "result": res,
                     "authority": "distributed_artifact", "confidence": "high",
                     "limitations": ("Manifiesto suelto: sus referencias @0x7f... no se resuelven porque no hay "
                                     "resources.arsc al lado (dentro de un APK sí se resuelven).")}]
        if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
            try:
                res = analyze_zip(p)
            except (ParseError, zipfile.BadZipFile, zipfile.LargeZipFile, OSError, ValueError, NotImplementedError) as exc:
                return [_fail("archive_parse_error", str(exc))]
            return [{
                "operation": "archive_inventory", "result": res, "authority": "distributed_artifact",
                "confidence": "high",
                "limitations": ("Inventario, manifiesto, DEX internos y referencias @0x7f... del manifiesto "
                                "resueltas contra resources.arsc (configuración por defecto); no se descompila "
                                "el código ni se validan las firmas."),
            }]
        return []


def _fail(op: str, msg: str) -> dict[str, Any]:
    return {"operation": op, "result": {"error": msg}, "authority": "analyst_inference",
            "confidence": "low", "limitations": "Estructura malformada o truncada."}
