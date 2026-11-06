"""Decodificador de XML binario de Android (AXML), p. ej. AndroidManifest.xml.

Lee el pool de cadenas (UTF-8/UTF-16), el mapa de recursos y los nodos de
elemento, y resume el manifiesto: paquete, versiones, SDK, permisos,
componentes (exportados o no), filtros de intent, deep links y flags de
seguridad de la aplicación. Lector con límites: una entrada malformada da
ParseError, nunca un crash.
"""
from __future__ import annotations

from typing import Any

from eolfi.providers.binfmt import ParseError, Reader

RES_XML_TYPE, RES_STRING_POOL, RES_XML_RESOURCE_MAP = 0x0003, 0x0001, 0x0180
START_NS, END_NS, START_EL, END_EL, CDATA = 0x0100, 0x0101, 0x0102, 0x0103, 0x0104
UTF8_FLAG = 0x100
MAX_STRINGS = 200_000
MAX_NODES = 100_000
MAX_ATTR_READS = 500_000

# Ids de atributos android:* (útiles cuando el nombre del atributo está ofuscado).
ANDROID_ATTRS = {
    0x01010003: "name", 0x0101021B: "versionCode", 0x0101021C: "versionName",
    0x0101020C: "minSdkVersion", 0x01010270: "targetSdkVersion", 0x01010010: "exported",
    0x0101000F: "debuggable", 0x01010280: "allowBackup", 0x010104EC: "usesCleartextTraffic",
    0x01010001: "label", 0x01010006: "permission", 0x01010027: "scheme", 0x01010028: "host",
    0x01010029: "port", 0x0101002A: "path", 0x0101002B: "pathPrefix", 0x0101002C: "pathPattern",
    0x01010002: "icon", 0x01010527: "networkSecurityConfig", 0x010104EA: "extractNativeLibs",
    0x0101057A: "appComponentFactory", 0x01010000: "theme", 0x0101000E: "allowTaskReparenting",
    0x0101001E: "process", 0x01010020: "enabled", 0x0101000D: "protectionLevel",
}
DANGEROUS = {
    "READ_CONTACTS", "WRITE_CONTACTS", "GET_ACCOUNTS", "READ_CALENDAR", "WRITE_CALENDAR", "CAMERA",
    "RECORD_AUDIO", "ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION", "ACCESS_BACKGROUND_LOCATION",
    "READ_PHONE_STATE", "READ_PHONE_NUMBERS", "CALL_PHONE", "READ_CALL_LOG", "WRITE_CALL_LOG",
    "SEND_SMS", "RECEIVE_SMS", "READ_SMS", "RECEIVE_MMS", "BODY_SENSORS", "READ_EXTERNAL_STORAGE",
    "WRITE_EXTERNAL_STORAGE", "READ_MEDIA_IMAGES", "READ_MEDIA_VIDEO", "READ_MEDIA_AUDIO",
    "POST_NOTIFICATIONS", "NEARBY_WIFI_DEVICES", "BLUETOOTH_SCAN", "BLUETOOTH_CONNECT", "ACTIVITY_RECOGNITION",
}
SPECIAL = {"SYSTEM_ALERT_WINDOW", "REQUEST_INSTALL_PACKAGES", "BIND_ACCESSIBILITY_SERVICE",
           "BIND_DEVICE_ADMIN", "MANAGE_EXTERNAL_STORAGE", "QUERY_ALL_PACKAGES", "PACKAGE_USAGE_STATS",
           "BIND_NOTIFICATION_LISTENER_SERVICE", "READ_PRIVILEGED_PHONE_STATE"}
COMPONENTS = ("activity", "activity-alias", "service", "receiver", "provider")


def _string_pool(r: Reader, off: int, limit: int = MAX_STRINGS) -> list[str]:
    """«limit» es lo que queda del presupuesto de cadenas del DOCUMENTO entero: varios pools seguidos
    no pueden sumar más de MAX_STRINGS entradas (PLAN_MEJORAS A6)."""
    header_size, size = r.u16(off + 2), r.u32(off + 4)
    count, flags, strings_start = r.u32(off + 8), r.u32(off + 16), r.u32(off + 20)
    if count > min(limit, MAX_STRINGS):
        raise ParseError(f"pool de {count} cadenas excesivo")
    if off + size > r.size or header_size < 28:
        raise ParseError("pool de cadenas fuera de rango")
    # La tabla de desplazamientos debe caber entre la cabecera y el comienzo de las cadenas.
    if count and not (header_size + 4 * count <= strings_start <= size):
        raise ParseError("tabla de desplazamientos del pool fuera de rango")
    utf8 = bool(flags & UTF8_FLAG)
    base = off + strings_start
    end = off + size
    out: list[str] = []
    memo: dict[int, str] = {}
    # Presupuesto: entradas que se solapan o repiten la misma cadena enorme no pueden
    # multiplicar la memoria (bomba de cadenas). Lo decodificado no supera 4× el pool.
    budget = 4 * size + 65536
    for i in range(count):
        p = base + r.u32(off + header_size + 4 * i)
        if p in memo:
            out.append(memo[p])
            continue
        start = p
        if not (base <= p < end):
            raise ParseError("cadena fuera del pool")
        if utf8:
            n = r.u8(p)
            p += 2 if n & 0x80 else 1
            blen = r.u8(p)
            if blen & 0x80:
                blen = ((blen & 0x7F) << 8) | r.u8(p + 1)
                p += 2
            else:
                p += 1
            nbytes = blen
        else:
            n = r.u16(p)
            p += 2
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | r.u16(p)
                p += 2
            nbytes = n * 2
        if p + nbytes > end:
            raise ParseError("cadena fuera del pool")
        budget -= nbytes
        if budget < 0:
            raise ParseError("pool de cadenas con solapamientos excesivos")
        raw = r.raw(p, nbytes)
        text = raw.decode("utf-8", "replace") if utf8 else raw.decode("utf-16-le", "replace")
        memo[start] = text
        out.append(text)
    return out


def _typed(dtype: int, data: int, strings: list[str]) -> Any:
    if dtype == 0x03:
        return strings[data] if data < len(strings) else ""
    if dtype == 0x12:
        return data != 0
    if dtype in (0x10,):
        return data - (1 << 32) if data & 0x80000000 else data
    if dtype == 0x11:
        return hex(data)
    if dtype in (0x01, 0x02):
        return f"@{data:#010x}"
    if dtype == 0x00:
        return None
    return data


def _value(dtype: int, data: int, raw: int, strings: list[str], mismatches: list[str] | None = None,
           name: str = "") -> Any:
    """Android usa el valor TIPADO; el texto «raw» es solo informativo. Antes se prefería raw, y un
    manifiesto manipulado podía enseñar debuggable="false" en raw con el valor real true (A7)."""
    value = _typed(dtype, data, strings)
    if dtype != 0x03 and raw != 0xFFFFFFFF and raw < len(strings) and mismatches is not None:
        text = strings[raw].strip().lower()
        expected = {str(value).lower(), hex(data), f"{data:#010x}"}
        if isinstance(value, bool):
            expected |= {"true" if value else "false", "-1" if value else "0"}
        if text and text not in expected and not text.startswith(("@", "?", "#")):
            mismatches.append(f"{name or 'atributo'}: texto «{strings[raw][:60]}» ≠ valor real {value!r}")
    return value


def parse_axml(data: bytes) -> list[dict[str, Any]]:
    """Devuelve la lista plana de elementos: {tag, attrs, depth}."""
    r = Reader(data)
    if r.u16(0) != RES_XML_TYPE:
        raise ParseError("no es XML binario de Android")
    total = min(r.u32(4), r.size)
    strings: list[str] = []
    res_ids: list[int] = []
    elements: list[dict[str, Any]] = []
    depth = 0
    off = r.u16(2)
    attr_budget = MAX_ATTR_READS
    string_budget = MAX_STRINGS
    mismatches: list[str] = []
    for _ in range(MAX_NODES):
        if off + 8 > total:
            break
        ctype, chsize, csize = r.u16(off), r.u16(off + 2), r.u32(off + 4)
        if csize < 8 or off + csize > total:
            raise ParseError(f"chunk {ctype:#x} de tamaño inválido {csize}")
        if ctype == RES_STRING_POOL:
            strings = _string_pool(r, off, string_budget)
            string_budget -= len(strings)
        elif ctype == RES_XML_RESOURCE_MAP:
            res_ids = [r.u32(off + chsize + 4 * i) for i in range((csize - chsize) // 4)]
        elif ctype == START_EL:
            ext = off + chsize
            name_i = r.u32(ext + 4)
            attr_start, attr_size, attr_count = r.u16(ext + 8), r.u16(ext + 10), r.u16(ext + 12)
            if attr_size < 20 or attr_count > 512:
                raise ParseError("atributos inválidos")
            if chsize + attr_start + attr_count * attr_size > csize:
                raise ParseError("atributos fuera de su elemento")
            attr_budget -= attr_count
            if attr_budget < 0:
                raise ParseError("demasiados atributos en total (manifiesto anómalo)")
            attrs: dict[str, Any] = {}
            for i in range(attr_count):
                a = ext + attr_start + i * attr_size
                an, raw, dtype, dval = r.u32(a + 4), r.u32(a + 8), r.u8(a + 15), r.u32(a + 16)
                aname = strings[an] if an < len(strings) else ""
                if (not aname or aname.isspace()) and an < len(res_ids):
                    aname = ANDROID_ATTRS.get(res_ids[an], f"attr_{res_ids[an]:#x}")
                elif an < len(res_ids) and res_ids[an] in ANDROID_ATTRS:
                    aname = ANDROID_ATTRS[res_ids[an]]
                attrs[aname] = _value(dtype, dval, raw, strings, mismatches, aname)
            elements.append({"tag": strings[name_i] if name_i < len(strings) else "?", "attrs": attrs,
                             "depth": depth})
            depth += 1
        elif ctype == END_EL:
            depth = max(0, depth - 1)
        off += csize
    else:
        if off + 8 <= total:
            # Antes se cortaba en silencio con confianza «high»: ahora se avisa.
            raise ParseError(f"más de {MAX_NODES} nodos: manifiesto anómalo o manipulado")
    if mismatches and elements:
        elements[0]["mismatches"] = mismatches[:50]
    return elements


def summarize_manifest(elements: list[dict[str, Any]]) -> dict[str, Any]:
    if not elements or elements[0]["tag"] != "manifest":
        raise ParseError("el documento no empieza por <manifest>")
    m = elements[0]["attrs"]
    pkg = m.get("package")
    out: dict[str, Any] = {
        "package": pkg, "version_code": m.get("versionCode"), "version_name": m.get("versionName"),
        "min_sdk": None, "target_sdk": None, "permissions": [], "custom_permissions": [],
        "features": [], "application": {}, "components": [], "deep_links": [], "launcher": None,
        "launchers": [],
    }
    current: dict[str, Any] | None = None
    filt: dict[str, Any] | None = None
    for el in elements[1:]:
        t, a = el["tag"], el["attrs"]
        if t == "uses-sdk":
            out["min_sdk"], out["target_sdk"] = a.get("minSdkVersion"), a.get("targetSdkVersion")
        elif t in ("uses-permission", "uses-permission-sdk-23") and a.get("name"):
            out["permissions"].append(a["name"])
        elif t == "permission" and a.get("name"):
            out["custom_permissions"].append({"name": a["name"], "protection": a.get("protectionLevel")})
        elif t == "uses-feature" and a.get("name"):
            out["features"].append(a["name"])
        elif t == "application":
            out["application"] = {k: a.get(k) for k in ("name", "label", "debuggable", "allowBackup",
                                                       "usesCleartextTraffic", "networkSecurityConfig",
                                                       "extractNativeLibs", "appComponentFactory", "theme",
                                                       "icon") if k in a}
        elif t in COMPONENTS:
            name = a.get("name") or "?"
            if pkg and isinstance(name, str) and name.startswith("."):
                name = pkg + name
            current = {"type": t, "name": name, "exported": a.get("exported"), "permission": a.get("permission"),
                       "enabled": a.get("enabled", True), "intent_filters": [], "depth": el["depth"]}
            out["components"].append(current)
            filt = None
        elif t == "intent-filter" and current is not None and el["depth"] > current["depth"]:
            filt = {"actions": [], "categories": [], "data": []}
            current["intent_filters"].append(filt)
        elif filt is not None and current is not None and el["depth"] > current["depth"]:
            if t == "action" and a.get("name"):
                filt["actions"].append(a["name"])
            elif t == "category" and a.get("name"):
                filt["categories"].append(a["name"])
            elif t == "data":
                d = {k: a[k] for k in ("scheme", "host", "port", "path", "pathPrefix", "pathPattern") if a.get(k)}
                if d:
                    filt["data"].append(d)

    target = out["target_sdk"] if isinstance(out["target_sdk"], int) else 0
    findings = []
    for c in out["components"]:
        has_filter = bool(c["intent_filters"])
        if isinstance(c["exported"], bool):
            exported = c["exported"]
        elif c["type"] == "provider":
            exported = target < 17   # un <provider> sin android:exported era público hasta targetSdk 16 (B16)
        else:
            exported = has_filter and target < 31
        c["exported_effective"] = exported
        for f in c["intent_filters"]:
            if "android.intent.action.MAIN" in f["actions"] and "android.intent.category.LAUNCHER" in f["categories"]:
                out["launchers"].append({"name": c["name"], "enabled": c["enabled"] is not False})
                if out["launcher"] is None and c["enabled"] is not False:
                    out["launcher"] = c["name"]     # el primero habilitado (los desactivados son alias/disfraces)
            if "android.intent.category.BROWSABLE" in f["categories"]:
                for d in f["data"]:
                    out["deep_links"].append(f"{d.get('scheme', '*')}://{d.get('host', '*')}{d.get('path') or d.get('pathPrefix') or ''}")
        if exported and not c["permission"] and c["type"] != "activity-alias" and c["name"] != out["launcher"]:
            if c["type"] in ("service", "receiver", "provider") or not has_filter:
                findings.append(f"{c['type']} exportado sin permiso: {c['name']}")
        if not isinstance(c["exported"], bool) and has_filter and target >= 31:
            findings.append(f"{c['name']}: con intent-filter debe declarar android:exported (targetSdk ≥ 31)")
        del c["depth"]
    app = out["application"]
    if app.get("debuggable") is True:
        findings.append("La aplicación es depurable (android:debuggable=true).")
    if app.get("allowBackup") is not False:
        findings.append("android:allowBackup no está desactivado: los datos pueden copiarse por adb backup.")
    if app.get("usesCleartextTraffic") is True:
        findings.append("Permite tráfico HTTP sin cifrar (usesCleartextTraffic=true).")
    out["deep_links"] = list(dict.fromkeys(out["deep_links"]))
    short = [p.rsplit(".", 1)[-1] for p in out["permissions"]]
    out["dangerous_permissions"] = sorted(p for p in short if p in DANGEROUS)
    out["special_permissions"] = sorted(p for p in short if p in SPECIAL)
    for mm in elements[0].get("mismatches", []):
        findings.append(f"Manifiesto manipulado: {mm}")
    out["security_findings"] = findings
    out["components_summary"] = {t: sum(1 for c in out["components"] if c["type"] == t) for t in COMPONENTS}
    return out
