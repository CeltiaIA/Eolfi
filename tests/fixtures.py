"""Muestras sintéticas mínimas (Mach-O, DEX, APK, sitio web, repositorio)."""
from __future__ import annotations

import json
import struct
import zipfile
import zlib
from pathlib import Path


def build_macho64() -> bytes:
    def pad8(b: bytes) -> bytes:
        return b + b"\x00" * (-len(b) % 8)

    seg = struct.pack("<II16sQQQQiiII", 0x19, 72 + 80, b"__TEXT", 0x100000000, 0x1000, 0, 0x400, 5, 5, 1, 0)
    sect = struct.pack("<16s16sQQIIIIIIII", b"__text", b"__TEXT", 0x100000180, 0x10, 0x180, 4, 0, 0, 0x80000400, 0, 0, 0)
    name = pad8(b"/usr/lib/libSystem.B.dylib\x00")
    dylib = struct.pack("<IIIIII", 0xC, 24 + len(name), 24, 2, 0x050C0000, 0x00010000) + name
    main = struct.pack("<IIQQ", 0x80000028, 24, 0x180, 0)
    build = struct.pack("<IIIIII", 0x32, 24, 1, 0x000E0000, 0x000F0000, 0)
    strtab = b"\x00___stack_chk_fail\x00_objc_release\x00"
    symoff, stroff = 0x300, 0x340
    symtab = struct.pack("<IIIIII", 0x2, 24, symoff, 2, stroff, len(strtab))
    cmds = seg + sect + dylib + main + build + symtab
    hdr = struct.pack("<IiiIIIII", 0xFEEDFACF, 0x0100000C, 0, 2, 5, len(cmds), 0x200000, 0)
    data = bytearray(0x400)
    data[: len(hdr) + len(cmds)] = hdr + cmds
    data[0x180:0x190] = b"\x1f\x20\x03\xd5" * 4
    for i, strx in enumerate((1, 1 + len("___stack_chk_fail") + 1)):
        struct.pack_into("<IBBHQ", data, symoff + i * 16, strx, 0x01, 0, 0, 0)
    data[stroff:stroff + len(strtab)] = strtab
    return bytes(data)


def _uleb(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def build_dex(classes: list[str] | None = None) -> bytes:
    classes = classes or ["Lcom/example/app/MainActivity;", "Lcom/example/app/net/Api;", "La/b;"]
    n = len(classes)
    string_ids = 0x70
    type_ids = string_ids + 4 * n
    class_defs = type_ids + 4 * n
    data_off = class_defs + 32 * n
    body = bytearray(data_off)
    strings = b""
    offsets = []
    for c in classes:
        offsets.append(data_off + len(strings))
        strings += _uleb(len(c)) + c.encode() + b"\x00"
    body += strings
    for i, off in enumerate(offsets):
        struct.pack_into("<I", body, string_ids + 4 * i, off)
        struct.pack_into("<I", body, type_ids + 4 * i, i)
        struct.pack_into("<I", body, class_defs + 32 * i, i)
    body[0:8] = b"dex\n039\x00"
    struct.pack_into("<III", body, 32, len(body), 0x70, 0x12345678)
    struct.pack_into("<II", body, 56, n, string_ids)
    struct.pack_into("<II", body, 64, n, type_ids)
    struct.pack_into("<II", body, 96, n, class_defs)
    struct.pack_into("<I", body, 8, zlib.adler32(bytes(body[12:])))
    return bytes(body)


def build_apk(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("AndroidManifest.xml", build_axml(SAMPLE_MANIFEST))
        z.writestr("classes.dex", build_dex())
        z.writestr("lib/arm64-v8a/libflutter.so", b"\x7fELF")
        z.writestr("lib/arm64-v8a/libapp.so", b"\x7fELF")
        z.writestr("META-INF/CERT.RSA", b"x")
        z.writestr("res/layout/main.xml", b"<x/>")
    return path


def build_site(root: Path) -> Path:
    (root / "css").mkdir(parents=True)
    (root / "js").mkdir()
    (root / "index.html").write_text("""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>Demo</title>
<link rel="stylesheet" href="css/app.css"><script type="application/ld+json">{"@type":"Organization"}</script>
<script src="js/app.js"></script></head><body>
<header class="site-header"><nav><a href="/about.html">Sobre</a><a href="https://x.example/a">X</a></nav></header>
<main><h1>Hola</h1>
<section class="pricing"><div class="plan">A</div></section>
<section class="testimonial-list"><figure class="testimonial">1</figure><figure class="testimonial">2</figure><figure class="testimonial">3</figure></section>
<form action="/send" method="post"><input type="email"><button></button></form>
<img src="a.png"></main><footer>pie</footer>
<script>window.__NEXT_DATA__={}</script></body></html>""", encoding="utf-8")
    (root / "about.html").write_text("<html><title>Sobre</title><h1>Sobre nosotros</h1></html>", encoding="utf-8")
    (root / "css" / "app.css").write_text(
        ":root{--brand:#e11d48;--bg:#ffffff}.card{display:grid;color:#e11d48;font-family:'Inter',sans-serif}"
        "@media (min-width:768px){.card{display:flex}}@media (width>=64rem){.x{color:#0ea5e9}}"
        "/*# sourceMappingURL=app.css.map */", encoding="utf-8")
    (root / "css" / "app.css.map").write_text(json.dumps({
        "version": 3, "sources": ["webpack:///./src/components/Card.tsx", "webpack:///./node_modules/react/index.js"],
        "sourcesContent": ["CODIGO SECRETO"]}), encoding="utf-8")
    (root / "js" / "app.js").write_text(
        'import x from "./y.js"; fetch("/api/products"); fetch("/api/orders/{id}"); localStorage.setItem("a",1)',
        encoding="utf-8")
    return root


def build_repo(root: Path) -> Path:
    (root / "src" / "components").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "package.json").write_text(json.dumps({
        "name": "demo", "scripts": {"dev": "vite", "build": "vite build", "test": "vitest"},
        "dependencies": {"react": "^19", "react-dom": "^19"},
        "devDependencies": {"vite": "^8", "typescript": "^5", "vitest": "^5", "express": "^5"}}), encoding="utf-8")
    (root / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n", encoding="utf-8")
    (root / "tsconfig.json").write_text("{}", encoding="utf-8")
    (root / "src" / "main.tsx").write_text("export const a = 1;\n" * 10, encoding="utf-8")
    (root / "src" / "components" / "Card.tsx").write_text("export const b = 2;\n" * 5, encoding="utf-8")
    (root / "tests" / "card.test.ts").write_text("test('x', () => {});\n", encoding="utf-8")
    (root / ".github" / "workflows" / "ci.yml").write_text(
        "name: CI\non:\n  push:\n  pull_request:\njobs:\n  t:\n    steps:\n      - uses: actions/checkout@v4\n",
        encoding="utf-8")
    (root / "README.md").write_text("# Demo\n## Instalar\n## Uso\n", encoding="utf-8")
    (root / "LICENSE").write_text("MIT License\n\nPermission is hereby granted, free of charge", encoding="utf-8")
    (root / ".env").write_text("SECRET=nunca-se-lee\n", encoding="utf-8")
    (root / ".env.example").write_text("API_URL=\nDB_PASSWORD=\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    return root


ANDROID_NS = "http://schemas.android.com/apk/res/android"
_ATTR_IDS = {"name": 0x01010003, "versionCode": 0x0101021B, "versionName": 0x0101021C,
             "minSdkVersion": 0x0101020C, "targetSdkVersion": 0x01010270, "exported": 0x01010010,
             "debuggable": 0x0101000F, "allowBackup": 0x01010280, "usesCleartextTraffic": 0x010104EC,
             "scheme": 0x01010027, "host": 0x01010028, "permission": 0x01010006}


def build_axml(tree, utf8: bool = False, obfuscate_names: bool = False) -> bytes:
    """tree = (tag, {attr: valor}, [hijos]). Atributos android:* salvo 'package'."""
    attr_names: list[str] = []
    others: list[str] = []

    def collect(node):
        tag, attrs, kids = node
        others.append(tag)
        for k, v in attrs.items():
            if k != "package" and k not in attr_names:
                attr_names.append(k)
            elif k == "package":
                others.append(k)
            if isinstance(v, str):
                others.append(v)
        for k in kids:
            collect(k)
    collect(tree)
    others += [ANDROID_NS, "android"]
    pool = list(attr_names) + [s for s in dict.fromkeys(others) if s not in attr_names]
    idx = {s: i for i, s in enumerate(pool)}

    data = bytearray()
    offsets = []
    for s in pool:
        offsets.append(len(data))
        text = "" if (obfuscate_names and s in attr_names) else s
        if utf8:
            b = text.encode()
            data += bytes([len(text), len(b)]) + b + b"\x00"
        else:
            data += struct.pack("<H", len(text)) + text.encode("utf-16-le") + b"\x00\x00"
    while len(data) % 4:
        data.append(0)
    sp_header = 28
    strings_start = sp_header + 4 * len(pool)
    sp = struct.pack("<HHIIIIII", 0x0001, sp_header, strings_start + len(data), len(pool), 0,
                     0x100 if utf8 else 0, strings_start, 0)
    sp += b"".join(struct.pack("<I", o) for o in offsets) + bytes(data)
    rm = struct.pack("<HHI", 0x0180, 8, 8 + 4 * len(attr_names)) + b"".join(
        struct.pack("<I", _ATTR_IDS.get(a, 0x01010000)) for a in attr_names)
    nodes = struct.pack("<HHIIIII", 0x0100, 16, 24, 1, 0xFFFFFFFF, idx["android"], idx[ANDROID_NS])

    def emit(node):
        nonlocal nodes
        tag, attrs, kids = node
        body = b""
        for k, v in attrs.items():
            ns = 0xFFFFFFFF if k == "package" else idx[ANDROID_NS]
            if isinstance(v, bool):
                raw, dtype, val = 0xFFFFFFFF, 0x12, 0xFFFFFFFF if v else 0
            elif isinstance(v, int):
                raw, dtype, val = 0xFFFFFFFF, 0x10, v
            else:
                raw, dtype, val = idx[v], 0x03, idx[v]
            body += struct.pack("<IIIHBBI", ns, idx[k], raw, 8, 0, dtype, val)
        nodes += struct.pack("<HHIII", 0x0102, 16, 36 + len(body), 1, 0xFFFFFFFF)
        nodes += struct.pack("<IIHHHHHH", 0xFFFFFFFF, idx[tag], 20, 20, len(attrs), 0, 0, 0) + body
        for k in kids:
            emit(k)
        nodes += struct.pack("<HHIIIII", 0x0103, 16, 24, 1, 0xFFFFFFFF, 0xFFFFFFFF, idx[tag])
    emit(tree)
    body = sp + rm + nodes
    return struct.pack("<HHI", 0x0003, 8, 8 + len(body)) + body


SAMPLE_MANIFEST = ("manifest", {"package": "com.example.demo", "versionCode": 42, "versionName": "1.2.0"}, [
    ("uses-sdk", {"minSdkVersion": 24, "targetSdkVersion": 34}, []),
    ("uses-permission", {"name": "android.permission.INTERNET"}, []),
    ("uses-permission", {"name": "android.permission.CAMERA"}, []),
    ("uses-permission", {"name": "android.permission.SYSTEM_ALERT_WINDOW"}, []),
    ("application", {"name": ".App", "debuggable": True, "usesCleartextTraffic": True}, [
        ("activity", {"name": ".MainActivity", "exported": True}, [
            ("intent-filter", {}, [("action", {"name": "android.intent.action.MAIN"}, []),
                                   ("category", {"name": "android.intent.category.LAUNCHER"}, [])]),
            ("intent-filter", {}, [("action", {"name": "android.intent.action.VIEW"}, []),
                                   ("category", {"name": "android.intent.category.BROWSABLE"}, []),
                                   ("data", {"scheme": "demo", "host": "open"}, [])]),
        ]),
        ("service", {"name": ".SyncService", "exported": True}, []),
        ("receiver", {"name": "com.example.demo.Boot"}, [
            ("intent-filter", {}, [("action", {"name": "android.intent.action.BOOT_COMPLETED"}, [])])]),
        ("provider", {"name": ".Files", "exported": False}, []),
    ]),
])


def _pool(strings: list[str]) -> bytes:
    data = bytearray()
    offs = []
    for s in strings:
        offs.append(len(data))
        data += struct.pack("<H", len(s)) + s.encode("utf-16-le") + b"\x00\x00"
    while len(data) % 4:
        data.append(0)
    start = 28 + 4 * len(strings)
    return struct.pack("<HHIIIIII", 0x0001, 28, start + len(data), len(strings), 0, 0, start, 0) + \
        b"".join(struct.pack("<I", o) for o in offs) + bytes(data)


def build_arsc(flags: int = 0) -> bytes:
    """Tabla de recursos mínima: paquete 0x7f, tipo string (id 1):
    0x7f010000 app_name = "Demo Eolfi"; 0x7f010001 alias -> @0x7f010000.
    flags: 0 = denso u32, 0x01 = sparse (idx u16 + offset/4 u16), 0x02 = OFFSET16 (offset/4 u16)."""
    values = _pool(["Demo Eolfi"])
    types = _pool(["string"])
    keys = _pool(["app_name", "label_alias"])
    cfg = struct.pack("<I", 64) + b"\x00" * 60
    hsize = 20 + len(cfg)
    entries = (struct.pack("<HHI", 8, 0, 0) + struct.pack("<HBBI", 8, 0, 0x03, 0)
               + struct.pack("<HHI", 8, 0, 1) + struct.pack("<HBBI", 8, 0, 0x01, 0x7F010000))
    offsets = {0: struct.pack("<II", 0, 16), 1: struct.pack("<HHHH", 0, 0, 1, 4),
               2: struct.pack("<HH", 0, 4)}[flags]
    tchunk_body = struct.pack("<BBHII", 1, flags, 0, 2, hsize + len(offsets)) + cfg
    tchunk = struct.pack("<HHI", 0x0201, hsize, hsize + len(offsets) + len(entries)) + tchunk_body + offsets + entries
    phdr = 288
    type_off = phdr
    key_off = phdr + len(types)
    pbody = struct.pack("<I", 0x7F) + "demo".encode("utf-16-le").ljust(256, b"\x00") + \
        struct.pack("<IIIII", type_off, 0, key_off, 0, 0)
    pkg = struct.pack("<HHI", 0x0200, phdr, phdr + len(types) + len(keys) + len(tchunk)) + pbody + types + keys + tchunk
    body = values + pkg
    return struct.pack("<HHII", 0x0002, 12, 12 + len(body), 1) + body


# Certificado X.509 autofirmado de PRUEBA (CN=Eolfi Prueba, EC P-256), generado con openssl solo para los tests.
# No hay clave privada en el repositorio: las firmas de estos fixtures no son verificables (no hace falta).
TEST_CERT_DER = __import__("base64").b64decode("MIIBvjCCAWWgAwIBAgIUGa5+F7bKkRYZ5xjFpVKfCa3s7bwwCgYIKoZIzj0EAwIwNDEVMBMGA1UEAwwMRW9sZmkgUHJ1ZWJhMQ4wDAYDVQQKDAVFb2xmaTELMAkGA1UEBhMCRVMwIBcNMjYxMTA1MTY1MTU1WhgPMjEyNjEwMTIxNjUxNTVaMDQxFTATBgNVBAMMDEVvbGZpIFBydWViYTEOMAwGA1UECgwFRW9sZmkxCzAJBgNVBAYTAkVTMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEHE9Ky8T3XTvESyZ4AnfI18QG0fcEsIuf2tZYlYbM9LzNaCUvUKVjwRBGJFLHcFF2x0/MeAaSk4Mw/yZjxFdeQqNTMFEwHQYDVR0OBBYEFBUeWbyUjvrl9azl8ClZZLGGCkMCMB8GA1UdIwQYMBaAFBUeWbyUjvrl9azl8ClZZLGGCkMCMA8GA1UdEwEB/wQFMAMBAf8wCgYIKoZIzj0EAwIDRwAwRAIgYgzwNYSZUb+Kv4zRxq60P9RYlR7A6EXgrgHhGXjcfv4CIAEoMdKu8dlqSQ2L/LnERhBRWmhP+/kmn3xdcG/k9yns")


def build_signed_apk(path: Path, schemes=("v2", "v3"), cert: bytes | None = None) -> Path:
    """APK de prueba con bloque de firma APK (v2/v3) delante del directorio central."""
    cert = cert or TEST_CERT_DER
    raw = build_apk(path).read_bytes()
    eocd = raw.rfind(b"PK\x05\x06")
    cd_size, cd_off = struct.unpack_from("<II", raw, eocd + 12)

    def lp(b: bytes) -> bytes:
        return struct.pack("<I", len(b)) + b

    def signer(v3: bool) -> bytes:
        digests = lp(lp(struct.pack("<I", 0x0103) + lp(b"\x00" * 32)))
        certs = lp(lp(cert))
        sdk = struct.pack("<II", 24, 0x7FFFFFFF) if v3 else b""
        signed = digests + certs + sdk + lp(b"")
        return lp(lp(signed) + sdk + lp(b"") + lp(b"pk"))

    pairs = b""
    for scheme, pid in (("v2", 0x7109871A), ("v3", 0xF05368C0)):
        if scheme in schemes:
            value = lp(signer(scheme == "v3"))
            pairs += struct.pack("<QI", len(value) + 4, pid) + value
    size = len(pairs) + 8 + 16
    block = struct.pack("<Q", size) + pairs + struct.pack("<Q", size) + b"APK Sig Block 42"
    out = bytearray(raw[:cd_off] + block + raw[cd_off:])
    struct.pack_into("<I", out, eocd + len(block) + 16, cd_off + len(block))
    path.write_bytes(bytes(out))
    return path
