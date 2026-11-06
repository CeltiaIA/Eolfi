"""Constructores de archivos sintéticos para los formatos nuevos (Fase E, grupo 2)."""
from __future__ import annotations

import plistlib
import struct
import zipfile
import zlib
from pathlib import Path

from tests.fixtures import _uleb, build_macho64


# ---------------------------------------------------------------------------------------- Java .class
def build_class(name: str = "com/ejemplo/Demo", major: int = 61, strings=("https://api.example.com",)) -> bytes:
    pool: list[bytes] = []

    def utf8(s: str) -> int:
        b = s.encode()
        pool.append(b"\x01" + struct.pack(">H", len(b)) + b)
        return len(pool)

    def cls(s: str) -> int:
        i = utf8(s)
        pool.append(b"\x07" + struct.pack(">H", i))
        return len(pool)

    this, sup, iface = cls(name), cls("java/lang/Object"), cls("java/lang/Runnable")
    cls("java/lang/Runtime")
    for s in strings:
        i = utf8(s)
        pool.append(b"\x08" + struct.pack(">H", i))
    pool.append(b"\x05" + struct.pack(">q", 7))   # long: ocupa dos entradas
    pool.append(b"")
    m_run, desc = utf8("run"), utf8("()V")
    body = b"".join(pool)
    count = len(pool) + 1
    methods = struct.pack(">H", 1) + struct.pack(">HHHH", 1, m_run, desc, 0)
    return (struct.pack(">IHHH", 0xCAFEBABE, 0, major, count) + body
            + struct.pack(">HHHH", 0x21, this, sup, 1) + struct.pack(">H", iface)
            + struct.pack(">H", 0) + methods + struct.pack(">H", 0))


def build_spring_jar(path: Path) -> Path:
    man = ("Manifest-Version: 1.0\r\nMain-Class: org.springframework.boot.loader.launch.JarLauncher\r\n"
           "Start-Class: com.ejemplo.App\r\nSpring-Boot-Version: 3.3.5\r\nCreated-By: Maven JAR Plugin 3.4.1\r\n"
           "Build-Jdk-Spec: 21\r\n\r\n")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("META-INF/MANIFEST.MF", man)
        zf.writestr("BOOT-INF/classes/com/ejemplo/App.class", build_class("com/ejemplo/App", 65))
        zf.writestr("BOOT-INF/lib/spring-core-6.1.14.jar", b"PK\x05\x06" + b"\x00" * 18)
        zf.writestr("BOOT-INF/lib/jackson-databind-2.17.2.jar", b"PK\x05\x06" + b"\x00" * 18)
        zf.writestr("org/springframework/boot/loader/launch/JarLauncher.class", build_class(
            "org/springframework/boot/loader/launch/JarLauncher", 61))
    return path


# ---------------------------------------------------------------------------------------- WebAssembly
def _wname(s: str) -> bytes:
    b = s.encode()
    return _uleb(len(b)) + b


def _section(sid: int, body: bytes) -> bytes:
    return bytes([sid]) + _uleb(len(body)) + body


def build_wasm() -> bytes:
    types = _section(1, _uleb(1) + b"\x60\x00\x00")
    imports = _section(2, _uleb(2) + _wname("wbg") + _wname("__wbindgen_throw") + b"\x00" + _uleb(0)
                       + _wname("env") + _wname("memory") + b"\x02\x01" + _uleb(1) + _uleb(16))
    funcs = _section(3, _uleb(1) + _uleb(0))
    exports = _section(7, _uleb(2) + _wname("greet") + b"\x00" + _uleb(1) + _wname("__wbindgen_malloc") + b"\x00" + _uleb(1))
    code = _section(10, _uleb(1) + _uleb(2) + b"\x00\x0b")
    name_sub0 = b"\x00" + _uleb(len(_wname("demo"))) + _wname("demo")
    fn = _uleb(1) + _uleb(1) + _wname("greet")
    name_sub1 = b"\x01" + _uleb(len(fn)) + fn
    names = _section(0, _wname("name") + name_sub0 + name_sub1)
    prod = _uleb(2) + _wname("language") + _uleb(1) + _wname("Rust") + _wname("") \
        + _wname("processed-by") + _uleb(2) + _wname("rustc") + _wname("1.82.0") + _wname("wasm-bindgen") + _wname("0.2.95")
    producers = _section(0, _wname("producers") + prod)
    return b"\x00asm" + struct.pack("<I", 1) + types + imports + funcs + exports + code + names + producers


# ---------------------------------------------------------------------------------------- ELF .so de Android
def build_android_so(align: int = 0x4000, exports=("Java_com_ejemplo_Nativo_suma", "JNI_OnLoad")) -> bytes:
    """ELF64 ET_DYN aarch64 con PT_LOAD (alineación dada), PT_NOTE (build-id) y .dynsym/.dynstr."""
    note = struct.pack("<III", 4, 20, 3) + b"GNU\x00" + bytes(range(20))
    dynstr = b"\x00" + b"\x00".join(e.encode() for e in exports) + b"\x00"
    syms = [b"\x00" * 24]
    off = 1
    for e in exports:
        syms.append(struct.pack("<IBBHQQ", off, 0x12, 0, 9, 0x1000, 4))   # GLOBAL FUNC definida (shndx 9)
        off += len(e) + 1
    dynsym = b"".join(syms)
    shstr = b"\x00.dynsym\x00.dynstr\x00.shstrtab\x00"
    ehdr_size, ph_size, nph = 64, 56, 2
    data_off = ehdr_size + ph_size * nph
    note_off = data_off
    dynsym_off = note_off + len(note)
    dynstr_off = dynsym_off + len(dynsym)
    shstr_off = dynstr_off + len(dynstr)
    sh_off = (shstr_off + len(shstr) + 7) & ~7
    total_before_sh = sh_off
    phdrs = struct.pack("<IIQQQQQQ", 1, 5, 0, 0, 0, total_before_sh, total_before_sh, align) \
        + struct.pack("<IIQQQQQQ", 4, 4, note_off, note_off, note_off, len(note), len(note), 4)

    def sh(name, typ, offset, size, link=0, entsize=0):
        return struct.pack("<IIQQQQIIQQ", name, typ, 2, offset, offset, size, link, 0, 8, entsize)

    shdrs = (b"\x00" * 64 + sh(1, 11, dynsym_off, len(dynsym), 2, 24) + sh(9, 3, dynstr_off, len(dynstr))
             + sh(17, 3, shstr_off, len(shstr)))
    ehdr = (b"\x7fELF\x02\x01\x01" + b"\x00" * 9
            + struct.pack("<HHIQQQIHHHHHH", 3, 183, 1, 0, ehdr_size, sh_off, 0, ehdr_size, ph_size, nph, 64, 4, 3))
    body = ehdr + phdrs + note + dynsym + dynstr + shstr
    body += b"\x00" * (sh_off - len(body))
    return body + shdrs


def build_apk_with_native(path: Path, align: int) -> Path:
    from tests.fixtures import build_apk

    build_apk(path)
    with zipfile.ZipFile(path, "a") as zf:
        zf.writestr("lib/arm64-v8a/libnativo.so", build_android_so(align))
    return path


# ---------------------------------------------------------------------------------------- DEX con métodos
def build_dex_with_methods() -> bytes:
    strings = ["Lcom/ejemplo/Main;", "Ljava/lang/Runtime;", "exec", "http://inseguro.example.com/api",
               "Landroid/webkit/WebView;", "addJavascriptInterface"]
    types = [0, 1, 4]   # índices de cadena de los tipos
    methods = [(1, 2), (2, 5)]   # (tipo, nombre)
    string_ids = 0x70
    type_ids = string_ids + 4 * len(strings)
    method_ids = type_ids + 4 * len(types)
    class_defs = method_ids + 8 * len(methods)
    data_off = class_defs + 32
    body = bytearray(data_off)
    blob = b""
    for i, s in enumerate(strings):
        struct.pack_into("<I", body, string_ids + 4 * i, data_off + len(blob))
        blob += _uleb(len(s)) + s.encode() + b"\x00"
    body += blob
    for i, t in enumerate(types):
        struct.pack_into("<I", body, type_ids + 4 * i, t)
    for i, (cls, name) in enumerate(methods):
        struct.pack_into("<HHI", body, method_ids + 8 * i, cls, 0, name)
    struct.pack_into("<I", body, class_defs, 0)
    body[0:8] = b"dex\n039\x00"
    struct.pack_into("<III", body, 32, len(body), 0x70, 0x12345678)
    struct.pack_into("<II", body, 56, len(strings), string_ids)
    struct.pack_into("<II", body, 64, len(types), type_ids)
    struct.pack_into("<II", body, 88, len(methods), method_ids)
    struct.pack_into("<II", body, 96, 1, class_defs)
    import hashlib

    body[12:32] = hashlib.sha1(bytes(body[32:])).digest()
    struct.pack_into("<I", body, 8, zlib.adler32(bytes(body[12:])))
    return bytes(body)


# ---------------------------------------------------------------------------------------- IPA
def _code_signature(identifier: str, team: str, entitlements: dict) -> bytes:
    ident = identifier.encode() + b"\x00"
    teamb = team.encode() + b"\x00"
    cd_hdr = 52
    cd = bytearray(cd_hdr) + ident + teamb
    struct.pack_into(">IIIIIIIIIBBBBII", cd, 0, 0xFADE0C02, len(cd), 0x20400, 0x10000, 0, cd_hdr, 0, 0, 0,
                     32, 2, 0, 12, 0, 0)
    struct.pack_into(">I", cd, 48, cd_hdr + len(ident))
    ent = plistlib.dumps(entitlements)
    entblob = struct.pack(">II", 0xFADE7171, 8 + len(ent)) + ent
    count = 2
    hdr = 12 + 8 * count
    sb = struct.pack(">III", 0xFADE0CC0, hdr + len(cd) + len(entblob), count)
    sb += struct.pack(">II", 0, hdr) + struct.pack(">II", 5, hdr + len(cd))
    return sb + bytes(cd) + entblob


def build_ios_macho(encrypted: bool = True, entitlements: dict | None = None) -> bytes:
    """Mach-O arm64 con LC_ENCRYPTION_INFO_64 y LC_CODE_SIGNATURE añadidos al fixture base."""
    base = bytearray(build_macho64())
    ncmds, sizeofcmds = struct.unpack_from("<II", base, 16)
    sig = _code_signature("com.ejemplo.demo", "ABCDE12345", entitlements or {"get-task-allow": True})
    sig_off = len(base) + 64
    enc = struct.pack("<IIIIII", 0x2C, 24, 0x4000, 0x1000, 1 if encrypted else 0, 0)
    cs = struct.pack("<IIII", 0x1D, 16, sig_off, len(sig))
    at = 32 + sizeofcmds
    base[at:at + len(enc) + len(cs)] = enc + cs   # el fixture deja hueco libre tras los comandos
    struct.pack_into("<II", base, 16, ncmds + 2, sizeofcmds + len(enc) + len(cs))
    return bytes(base) + b"\x00" * 64 + sig


def build_ipa(path: Path, enterprise: bool = False, ats_off: bool = True) -> Path:
    info = {"CFBundleIdentifier": "com.ejemplo.demo", "CFBundleName": "Demo", "CFBundleShortVersionString": "1.2.0",
            "CFBundleVersion": "42", "CFBundleExecutable": "Demo", "MinimumOSVersion": "16.0",
            "CFBundleURLTypes": [{"CFBundleURLSchemes": ["demo"]}],
            "NSCameraUsageDescription": "Para escanear", "NSLocationWhenInUseUsageDescription": "Para el mapa"}
    if ats_off:
        info["NSAppTransportSecurity"] = {"NSAllowsArbitraryLoads": True}
    profile = {"Name": "Demo Dev", "TeamIdentifier": ["ABCDE12345"], "TeamName": "Ejemplo SL",
               "ProvisionedDevices": ["00008030-001"], "Entitlements": {"get-task-allow": True}}
    if enterprise:
        profile = {**profile, "ProvisionsAllDevices": True, "ProvisionedDevices": []}
    cms = b"0\x82\x10\x00" + b"\x06\x09*\x86H\x86\xf7\r\x01\x07\x02" + plistlib.dumps(profile) + b"\x00" * 16
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Payload/Demo.app/Info.plist", plistlib.dumps(info, fmt=plistlib.FMT_BINARY))
        zf.writestr("Payload/Demo.app/Demo", build_ios_macho())
        zf.writestr("Payload/Demo.app/embedded.mobileprovision", cms)
        zf.writestr("Payload/Demo.app/Frameworks/Alamofire.framework/Alamofire", b"\xcf\xfa\xed\xfe")
        zf.writestr("Payload/Demo.app/PlugIns/Widget.appex/Info.plist", plistlib.dumps({}))
    return path
