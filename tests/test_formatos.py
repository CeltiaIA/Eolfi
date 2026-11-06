"""Formatos nuevos (Fase E, grupo 2): Authenticode, .NET, Java/JAR, WebAssembly, APK (firma, .so, DEX) e IPA."""
import mmap
import shutil
from pathlib import Path

import pytest

from eolfi.core.evidence import EvidenceStore
from tests import formats as F

SIGNED_EXE = Path(r"C:\Program Files\dotnet\dotnet.exe")
NETFX = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\System.dll")


def _pe(path):
    from eolfi.providers.binfmt import parse_pe

    with open(path, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        info = parse_pe(mm)
        from eolfi.providers import pe_extra

        return info, pe_extra.analyze(mm, info)


# ------------------------------------------------------------------------------------------ DER / X.509
def test_x509_reader_matches_openssl_fingerprint():
    from eolfi.providers.der import parse_certificate_der
    from tests.fixtures import TEST_CERT_DER

    c = parse_certificate_der(TEST_CERT_DER)
    assert c["subject"] == "CN=Eolfi Prueba, O=Eolfi, C=ES" and c["self_signed"]
    assert c["sha256"] == "b7a2198d3aa8c2ecffa683861f4584a68ee1f76bfb4aa0998dd97a786de823fb"   # openssl -fingerprint
    assert c["key_algorithm"] == "ecPublicKey" and c["not_after"].startswith("2126-")


def test_der_rejects_lengths_outside_their_container():
    from eolfi.providers.binfmt import ParseError
    from eolfi.providers.der import read_tlv

    with pytest.raises(ParseError):
        read_tlv(b"\x30\x84\x7f\xff\xff\xff\x00", 0)
    with pytest.raises(ParseError):
        read_tlv(b"\x30\x80\x00\x00", 0)   # longitud indefinida: no es DER


# ------------------------------------------------------------------------------------------ PE
@pytest.mark.skipif(not SIGNED_EXE.is_file(), reason="sin un ejecutable firmado de referencia")
def test_authenticode_real_and_tampered(tmp_path):
    _info, x = _pe(SIGNED_EXE)
    sig = x["authenticode"]
    assert sig["digest_matches"] is True and "Microsoft" in sig["signer"]["subject"]
    assert sig["signatures"][0]["timestamped"]
    bad = tmp_path / "dotnet.exe"
    shutil.copyfile(SIGNED_EXE, bad)
    data = bytearray(bad.read_bytes())
    data[0x500] ^= 0xFF   # un byte del código, después de firmar
    bad.write_bytes(bytes(data))
    _i, x2 = _pe(bad)
    assert x2["authenticode"]["digest_matches"] is False
    from eolfi.flows.triage_flow import LOCAL_PROVIDERS, run_triage

    s = EvidenceStore(str(tmp_path / "e.db"))
    run_triage(str(bad), s, LOCAL_PROVIDERS)
    assert any("no coincide" in i["question"] and i["severity"] == "high" for i in s.list_incognitas())


@pytest.mark.skipif(not SIGNED_EXE.is_file(), reason="sin un ejecutable de referencia")
def test_pe_metadata_real():
    _info, x = _pe(SIGNED_EXE)
    assert len(x["imphash"]) == 32
    assert x["version_info"]["strings"]["CompanyName"] == "Microsoft Corporation"
    assert x["rich_header"]["present"] and x["rich_header"]["entries"]


def test_imphash_matches_pefile_rules():
    from eolfi.providers.pe_extra import imphash

    import hashlib

    assert imphash({"KERNEL32.dll": ["CreateFileW", "#12"], "ws2_32.DLL": ["send"]}) == \
        hashlib.md5(b"kernel32.createfilew,kernel32.ord12,ws2_32.send").hexdigest()
    assert imphash({}) is None


@pytest.mark.skipif(not NETFX.is_file(), reason="sin .NET Framework")
def test_dotnet_metadata_real():
    from eolfi.providers.dotnet import parse_clr

    with open(NETFX, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        from eolfi.providers.binfmt import parse_pe

        c = parse_clr(mm, parse_pe(mm))
    assert c["assembly"]["name"] == "System" and c["il_only"] and c["strong_name_signed"]
    assert any(r["name"] == "mscorlib" for r in c["assembly_refs"])
    assert "kernel32.dll" in {k.lower() for k in c["pinvoke"]}


def test_dotnet_bundle_marker():
    import struct

    from eolfi.providers.dotnet import BUNDLE_SIGNATURE, single_file_bundle

    def s7(t):
        b = t.encode()
        return bytes([len(b)]) + b
    header = struct.pack("<III", 6, 0, 2) + s7("ID123") + b"\x00" * 40
    header += struct.pack("<qqq", 0, 10, 0) + b"\x01" + s7("App.dll")
    header += struct.pack("<qqq", 0, 10, 0) + b"\x02" + s7("libclrjit.so")
    body = b"MZ" + b"\x00" * 62
    hdr_off = len(body) + 8 + len(BUNDLE_SIGNATURE)
    data = body + struct.pack("<q", hdr_off) + BUNDLE_SIGNATURE + header
    b = single_file_bundle(data)
    assert b["bundle"] and b["assemblies"] == ["App.dll"] and b["native"] == ["libclrjit.so"]


# ------------------------------------------------------------------------------------------ Java
def test_java_class_and_spring_boot_jar(tmp_path):
    from eolfi.providers.dex import AndroidJavaProvider

    cls = tmp_path / "Demo.class"
    cls.write_bytes(F.build_class())
    [r] = AndroidJavaProvider().run(str(cls))
    res = r["result"]
    assert r["operation"] == "java_class" and res["java_version"] == "17"
    assert res["class"] == "com.ejemplo.Demo" and res["interfaces"] == ["java.lang.Runnable"]
    assert "java.lang.Runtime" in res["referenced_classes"] and res["strings"] == ["https://api.example.com"]
    jar = F.build_spring_jar(tmp_path / "app.jar")
    [inv] = AndroidJavaProvider().run(str(jar))
    j = inv["result"]["jar"]
    assert j["spring_boot"] == {"version": "3.3.5", "start_class": "com.ejemplo.App"}
    assert j["main_class"] == "com.ejemplo.App" and set(j["embedded_libraries"]) == {"spring-core", "jackson-databind"}
    assert j["bytecode_versions"] == {"21": 1, "17": 1}


# ------------------------------------------------------------------------------------------ WebAssembly
def test_wasm_module(tmp_path):
    from eolfi.providers.binfmt import BinaryFormatProvider

    f = tmp_path / "m.wasm"
    f.write_bytes(F.build_wasm())
    [r] = BinaryFormatProvider().run(str(f))
    w = r["result"]
    assert r["operation"] == "wasm_module"
    assert w["import_modules"] == {"wbg": 1, "env": 1} and w["export_count"] == 2
    assert w["memory"][0]["imported"] and (w["memory"][0]["min"], w["memory"][0]["max"]) == (1, 16)
    assert w["names"]["module"] == "demo" and w["names"]["function_sample"] == ["greet"]
    assert w["producers"]["language"] == ["Rust"] and "Rust + wasm-bindgen" in w["toolchain"]


def test_wasm_truncated_is_parse_error(tmp_path):
    from eolfi.providers.binfmt import BinaryFormatProvider

    f = tmp_path / "m.wasm"
    f.write_bytes(F.build_wasm()[:-7])
    [r] = BinaryFormatProvider().run(str(f))
    assert r["operation"] == "wasm_parse_error"


# ------------------------------------------------------------------------------------------ APK
def test_apk_signature_v2_v3(tmp_path):
    from eolfi.providers.dex import analyze_zip
    from tests.fixtures import build_signed_apk

    r = analyze_zip(build_signed_apk(tmp_path / "f.apk"))
    sig = r["signature"]
    assert {"v2", "v3"} <= set(sig["schemes"])
    assert sig["certificate_sha256"] == ["b7a2198d3aa8c2ecffa683861f4584a68ee1f76bfb4aa0998dd97a786de823fb"]
    v3 = next(s for s in sig["signers"] if s["scheme"] == "v3")
    assert v3["min_sdk"] == 24 and v3["subject"].startswith("CN=Eolfi Prueba")


def test_unsigned_apk_is_flagged(tmp_path):
    import zipfile

    from eolfi.providers.dex import analyze_zip
    from tests.fixtures import build_apk

    apk = build_apk(tmp_path / "x.apk")
    clean = tmp_path / "sin.apk"
    with zipfile.ZipFile(apk) as src, zipfile.ZipFile(clean, "w") as dst:
        for i in src.infolist():
            if not i.filename.startswith("META-INF/"):
                dst.writestr(i, src.read(i))
    r = analyze_zip(clean)
    assert "APK sin firma: Android no lo instalará" in r["signature"]["findings"]
    assert any("sin firma" in f for f in r["manifest"]["security_findings"])


@pytest.mark.parametrize("align,ok", [(0x4000, True), (0x1000, False)])
def test_android_native_libs_16k_alignment_and_jni(tmp_path, align, ok):
    from eolfi.providers.dex import analyze_zip

    r = analyze_zip(F.build_apk_with_native(tmp_path / "n.apk", align))
    lib = r["native_analysis"]["arm64-v8a"]["libnativo.so"]
    assert lib["aligned_16k"] is ok and lib["jni_onload"]
    assert lib["jni_exports"] == ["Java_com_ejemplo_Nativo_suma"] and len(lib["build_id"]) == 40
    flagged = any("16 KB" in f for f in r["manifest"]["security_findings"])
    assert flagged is (not ok)


def test_dex_sensitive_apis_urls_and_sha1(tmp_path):
    from eolfi.providers.dex import parse_dex

    d = parse_dex(F.build_dex_with_methods())
    assert d["sensitive_apis"] == {"ejecuta comandos (Runtime.exec)": 1,
                                   "puente JavaScript en WebView (addJavascriptInterface)": 1}
    assert d["cleartext_urls"] == ["http://inseguro.example.com/api"] and d["signature_sha1_ok"] is True


# ------------------------------------------------------------------------------------------ iOS
def test_ipa_full(tmp_path):
    from eolfi.providers.dex import analyze_zip

    r = analyze_zip(F.build_ipa(tmp_path / "d.ipa"))
    assert r["kind"] == "ipa"
    ios = r["ios"]
    assert ios["info"]["bundle_id"] == "com.ejemplo.demo" and ios["info"]["url_schemes"] == ["demo"]
    assert ios["info"]["privacy_usage"] == ["NSCameraUsageDescription", "NSLocationWhenInUseUsageDescription"]
    assert ios["provisioning"]["team_id"] == "ABCDE12345" and ios["provisioning"]["distribution"] == "development"
    sig = ios["signature"]
    assert sig["identifier"] == "com.ejemplo.demo" and sig["team_id"] == "ABCDE12345" and sig["hash_type"] == "sha256"
    assert sig["entitlements"] == {"get-task-allow": True}
    assert ios["executable"]["encrypted"] is True
    text = " ".join(ios["findings"])
    assert "App Transport Security" in text and "FairPlay" in text and "get-task-allow" in text
    assert ios["frameworks"] == ["Alamofire.framework"] and ios["app_extensions"] == ["Widget.appex"]


def test_ipa_findings_become_incognitas(tmp_path):
    from eolfi.flows.triage_flow import LOCAL_PROVIDERS, run_triage

    ipa = F.build_ipa(tmp_path / "e.ipa", enterprise=True)
    s = EvidenceStore(str(tmp_path / "e.db"))
    run_triage(str(ipa), s, LOCAL_PROVIDERS)
    qs = [i["question"] for i in s.list_incognitas()]
    assert any(q.startswith("iOS: Perfil empresarial") for q in qs)


def test_report_mentions_new_formats(tmp_path):
    from eolfi.core.report import build_report, render_markdown
    from eolfi.flows.triage_flow import LOCAL_PROVIDERS, run_triage
    from tests.fixtures import build_signed_apk

    s = EvidenceStore(str(tmp_path / "e.db"))
    rep = run_triage(str(build_signed_apk(tmp_path / "f.apk")), s, LOCAL_PROVIDERS)
    md = render_markdown(build_report(s, rep["subject"]))
    assert "Firma APK: esquemas" in md


def test_new_parsers_survive_mutations(tmp_path):
    """Fuzz de mutación sobre los formatos nuevos: solo errores controlados, nunca excepciones sueltas."""
    import random

    from eolfi.providers.binfmt import BinaryFormatProvider
    from eolfi.providers.dex import AndroidJavaProvider
    from tests.fixtures import build_signed_apk

    seeds = [F.build_wasm(), F.build_class(), F.build_android_so(), F.build_ios_macho(), F.build_dex_with_methods(),
             build_signed_apk(tmp_path / "s.apk").read_bytes(), F.build_ipa(tmp_path / "s.ipa").read_bytes(),
             F.build_spring_jar(tmp_path / "s.jar").read_bytes()]
    rng = random.Random(11)
    f = tmp_path / "m.bin"
    for seed in seeds:
        for _ in range(60):
            b = bytearray(seed)
            for _k in range(rng.randint(1, 8)):
                b[rng.randrange(len(b))] = rng.randrange(256)
            f.write_bytes(bytes(b[:rng.randrange(len(b))] if rng.random() < 0.2 else b))
            BinaryFormatProvider().run(str(f))
            AndroidJavaProvider().run(str(f))


def test_zip_with_impossible_version_is_contained(tmp_path):
    import struct

    from eolfi.providers.dex import AndroidJavaProvider
    from tests.fixtures import build_apk

    raw = bytearray(build_apk(tmp_path / "a.apk").read_bytes())
    cd = raw.find(b"PK\x01\x02")
    struct.pack_into("<H", raw, cd + 6, 99)   # «versión necesaria» 9.9
    f = tmp_path / "v.apk"
    f.write_bytes(bytes(raw))
    [r] = AndroidJavaProvider().run(str(f))
    assert r["operation"] == "archive_parse_error"
