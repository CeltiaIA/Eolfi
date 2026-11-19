"""Cliente Android de la tableta satélite: la parte sin Android en la JVM (unidad e integración contra el panel real
con HTTPS y huella fijada) y la construcción del APK cuando las herramientas locales existen (19/11/2026)."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1] / "eolfi" / "tableta-android"
X = {"X-Eolfi": "1"}

javac = shutil.which("javac")
pytestmark = pytest.mark.skipif(not javac or not shutil.which("java"), reason="sin JDK (javac/java)")


@pytest.fixture(scope="module")
def clases(tmp_path_factory):
    out = tmp_path_factory.mktemp("jvm")
    fuentes = [RAIZ / "src/com/celtiaia/eolfi/tableta" / n for n in ("Wav.java", "Reglas.java", "Cliente.java")]
    r = subprocess.run([javac, "--release", "8", "-Xlint:all,-options", "-Werror", "-encoding", "UTF-8", "-d", str(out),
                        *map(str, fuentes), str(RAIZ / "pruebas" / "PruebasJvm.java")],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    return out


def _java(clases, *args):
    return subprocess.run(["java", "-cp", str(clases), "PruebasJvm", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120, check=False)


def test_unidad_en_la_jvm(clases):
    r = _java(clases, "unidad")
    assert r.returncode == 0 and r.stdout.strip().startswith("OK"), r.stdout + r.stderr


def test_cliente_java_contra_el_panel_real_con_huella_fijada(clases, tmp_path, monkeypatch):
    pytest.importorskip("cryptography")
    monkeypatch.setenv("EOLFI_TABLETA_DIR", str(tmp_path / "tableta"))   # el diagnóstico de prueba, aislado
    from eolfi.server import con_tls, make_server
    from tests.test_server_tls import _certificado

    cert, key = _certificado(tmp_path)
    httpd = con_tls(make_server(str(tmp_path / "e.db"), "127.0.0.1", 0, tmp_path / "samples"), cert, key, legado=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        port = httpd.server_address[1]
        import http.client
        import ssl

        ctx = ssl.create_default_context(cafile=str(cert))
        c = http.client.HTTPSConnection("127.0.0.1", port, timeout=10, context=ctx)
        c.request("POST", "/api/clients/pair", "{}", X)
        codigo = json.loads(c.getresponse().read())["code"]
        c.close()
        r = _java(clases, "cliente", f"https://127.0.0.1:{port}", codigo)
        assert r.returncode == 0 and r.stdout.strip().endswith("comprobaciones"), r.stdout + r.stderr
        assert "FALLA" not in r.stdout, r.stdout
        assert len(list((tmp_path / "tableta").glob("diagnostico-*.json"))) == 1
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_la_firma_pkcs7_sha1_es_valida_y_sin_atributos(tmp_path):
    pytest.importorskip("cryptography")
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.serialization import pkcs7
    from cryptography.x509.oid import NameOID

    sys.path.insert(0, str(RAIZ))
    try:
        import construir
    finally:
        sys.path.remove(str(RAIZ))
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    n = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "prueba")])
    ahora = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(n).issuer_name(n).public_key(k.public_key())
            .serial_number(2 ** 63 + 5).not_valid_before(ahora).not_valid_after(ahora + datetime.timedelta(days=1))
            .sign(k, hashes.SHA256()))
    datos = b"Signature-Version: 1.0\r\n\r\n"
    der = construir.pkcs7_sha1(datos, k, cert)
    assert pkcs7.load_der_pkcs7_certificates(der)[0] == cert           # DER bien formado y con el certificado
    firma = k.sign(datos, padding.PKCS1v15(), hashes.SHA1())
    assert firma in der                                                  # PKCS#1 v1.5 determinista: es esa firma
    k.public_key().verify(firma, datos, padding.PKCS1v15(), hashes.SHA1())
    assert bytes.fromhex("06092a864886f70d010903") not in der            # sin atributo contentType firmado
    assert bytes.fromhex("06052b0e03021a") in der                        # SHA-1


def test_manifiesto_jar_parte_lineas_largas():
    sys.path.insert(0, str(RAIZ))
    try:
        import construir
    finally:
        sys.path.remove(str(RAIZ))
    s = construir._seccion("a/" + "x" * 150, "abc=")
    lineas = s.split(b"\r\n")
    assert all(len(linea) <= 72 for linea in lineas)
    assert lineas[1].startswith(b" ") and lineas[2].startswith(b" ")
    assert b"".join([lineas[0]] + [linea[1:] for linea in lineas[1:3]]) == b"Name: a/" + b"x" * 150


def _herramientas_o_salta():
    sys.path.insert(0, str(RAIZ))
    try:
        import construir
    finally:
        sys.path.remove(str(RAIZ))
    try:
        construir.herramientas()
    except construir.ErrorConstruccion as exc:
        pytest.skip(f"sin herramientas de construcción locales: {exc}")
    return construir


def test_construye_el_apk_firmado_v1(tmp_path, monkeypatch):
    construir = _herramientas_o_salta()
    monkeypatch.setenv("EOLFI_TABLETA_DIR", str(tmp_path / "clave"))
    inf = construir.construir(tmp_path / "build")
    apk = Path(inf["apk"])
    assert inf["sha256"] == hashlib.sha256(apk.read_bytes()).hexdigest()
    with zipfile.ZipFile(apk) as z:
        nombres = z.namelist()
        assert nombres[:3] == ["META-INF/MANIFEST.MF", "META-INF/CERT.SF", "META-INF/CERT.RSA"]
        assert {"AndroidManifest.xml", "classes.dex"} <= set(nombres)
        mf = z.read("META-INF/MANIFEST.MF").decode()
        import base64

        for nombre in ("classes.dex", "AndroidManifest.xml"):
            dig = base64.b64encode(hashlib.sha1(z.read(nombre)).digest()).decode()
            assert f"Name: {nombre}\r\nSHA1-Digest: {dig}" in mf
        sf = z.read("META-INF/CERT.SF").decode()
        dig_mf = base64.b64encode(hashlib.sha1(mf.encode()).digest()).decode()
        assert f"SHA1-Digest-Manifest: {dig_mf}" in sf
        assert z.read("classes.dex")[:4] == b"dex\n"
