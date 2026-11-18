"""C7 (18/11/2026): HTTPS opcional en «eolfi serve» para que el móvil pueda usar el micrófono del panel."""
from __future__ import annotations

import datetime
import http.client
import ipaddress
import ssl
import threading

import pytest

from eolfi import cli
from eolfi.server import con_tls, make_server

x509 = pytest.importorskip("cryptography.x509")


def _certificado(tmp_path):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    clave = ec.generate_private_key(ec.SECP256R1())
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    ahora = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(nombre).issuer_name(nombre).public_key(clave.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(ahora - datetime.timedelta(minutes=1))
            .not_valid_after(ahora + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
            .sign(clave, hashes.SHA256()))
    c, k = tmp_path / "cert.pem", tmp_path / "key.pem"
    c.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    k.write_bytes(clave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    return c, k


@pytest.fixture
def https(tmp_path):
    cert, key = _certificado(tmp_path)
    httpd = con_tls(make_server(str(tmp_path / "s.db"), "127.0.0.1", 0, tmp_path / "samples", token="secreto"),
                    cert, key)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    ctx = ssl.create_default_context(cafile=str(cert))
    yield httpd.server_address[1], ctx
    httpd.shutdown()
    httpd.server_close()


def _get(port, ctx, path, headers=None):
    c = http.client.HTTPSConnection("127.0.0.1", port, timeout=30, context=ctx)
    c.request("GET", path, headers=headers or {})
    r = c.getresponse()
    r.read()
    c.close()
    return r.status, dict(r.getheaders())


def test_https_sirve_el_panel_y_la_cookie_va_con_secure(https):
    port, ctx = https
    st, h = _get(port, ctx, "/?token=secreto")
    assert st == 303 and "Secure" in h["Set-Cookie"] and "HttpOnly" in h["Set-Cookie"]
    assert _get(port, ctx, "/api/health", {"Cookie": "eolfi_token=secreto"})[0] == 200
    # Un cliente que habla HTTP plano al puerto TLS no recibe nada útil y el servidor sigue atendiendo.
    plano = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    with pytest.raises((http.client.HTTPException, ConnectionError, OSError)):
        plano.request("GET", "/api/health")
        plano.getresponse().read()
    plano.close()
    assert _get(port, ctx, "/api/health", {"Cookie": "eolfi_token=secreto"})[0] == 200


def test_sin_tls_la_cookie_no_lleva_secure(tmp_path):
    httpd = make_server(str(tmp_path / "s.db"), "127.0.0.1", 0, tmp_path / "samples", token="secreto")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=30)
        c.request("GET", "/?token=secreto")
        r = c.getresponse()
        r.read()
        assert r.status == 303 and "Secure" not in r.getheader("Set-Cookie")
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_cli_rechaza_certificados_que_no_sirven(tmp_path, capsys):
    malo = tmp_path / "malo.pem"
    malo.write_text("no es un certificado", encoding="utf-8")
    assert cli.main(["serve", "--port", "0", "--cert", str(malo)]) == 2
    assert "certificado" in capsys.readouterr().err
    assert cli.main(["serve", "--port", "0", "--key", str(malo)]) == 2
    assert "--key necesita --cert" in capsys.readouterr().err


def test_el_panel_explica_por_que_no_hay_microfono_sin_https():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "eolfi" / "web" / "voz.js").read_text(encoding="utf-8")
    assert "window.isSecureContext" in js and "serve --cert" in js
