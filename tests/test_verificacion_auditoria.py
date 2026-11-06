"""Pruebas de los fallos REALES confirmados al verificar la auditoría archivo por archivo (2026-11-06)."""
import os

import pytest


def test_gitignore_extra_se_fusiona(tmp_path):
    """Antes .gitignore.extra se borraba sin fusionarse: los proyectos .NET quedaban sin ignorar bin/ y obj/."""
    from eolfi.core.evidence import EvidenceStore
    from eolfi.flows.learn_flow import run_repo
    from eolfi.generador.generators import generate
    from eolfi.generador.spec import build_spec
    from tests.fixtures import build_repo

    st = EvidenceStore(":memory:")
    sub = run_repo(str(build_repo(tmp_path / "repo")), st)["subject"]
    for target, own in (("dotnet", ["bin/", "obj/", "publish/"]), ("cli", ["build/", "*.spec"])):
        out = tmp_path / f"out-{target}"
        generate(build_spec(st, [sub], name="demo", target=target), out)
        gi = (out / ".gitignore").read_text(encoding="utf-8").splitlines()
        assert all(x in gi for x in own), (target, gi)
        assert "node_modules/" in gi and len(gi) == len(set(gi))
        assert not (out / ".gitignore.extra").exists()


def test_spec_con_recurso_peligroso_no_se_genera(tmp_path):
    from eolfi.generador.generators import generate

    spec = {"target": "static", "title": "Demo", "api": {"resources": ['x"><script>']}}
    with pytest.raises(ValueError, match="recurso no válido"):
        generate(spec, tmp_path / "out")


def test_vinculacion_anula_codigos_tras_5_fallos(tmp_path, monkeypatch):
    from eolfi import server

    monkeypatch.setattr(server.time, "sleep", lambda _s: None)
    app = server.EolfiApp(str(tmp_path / "e.db"), tmp_path / "samples")
    code = app.pair_code({})["code"]
    for _ in range(5):
        with pytest.raises(server.ApiError):
            app.pair_exchange({"code": "000000" if code != "000000" else "111111"})
    with pytest.raises(server.ApiError):   # el código bueno ya no vale: hay que generar otro
        app.pair_exchange({"code": code})
    code2 = app.pair_code({})["code"]
    assert app.pair_exchange({"code": code2})["token"].startswith("ect_")


def test_subproceso_aislado_sin_secretos(monkeypatch):
    from eolfi.flows import triage_flow

    seen = {}

    class P:
        returncode = 0
        stdout = '{"findings": [], "version": "1"}'
        stderr = ""

    def fake_run_tree(argv, timeout, env=None):
        seen.update(env)
        return P()

    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setattr("eolfi.providers.external.run_tree", fake_run_tree)

    class Prov:
        version = "0"

    triage_flow._run_isolated(Prov(), __file__)
    assert "GITHUB_TOKEN" not in seen and "OPENAI_API_KEY" not in seen
    assert "PYTHONPATH" in seen and seen.get("PATH") == os.environ.get("PATH")


def test_fetch_dns_mixto_no_abre_la_red_privada(monkeypatch):
    """Antes, un dominio cuyo DNS devolvía alguna IP privada activaba el permiso para direcciones privadas."""
    from eolfi.sites import fetch

    def fake_getaddrinfo(host, *a, **k):
        ips = {"mixto.ejemplo.es": ["93.184.216.34", "127.0.0.1"], "publico.ejemplo.es": ["93.184.216.34"],
               "localhost": ["127.0.0.1"], "otro.lan": ["192.168.1.9"]}.get(host, ["93.184.216.34"])
        return [(2, 1, 6, "", (ip, 0)) for ip in ips]

    monkeypatch.setattr(fetch.socket, "getaddrinfo", fake_getaddrinfo)
    f = fetch.Fetcher()
    with pytest.raises(fetch.FetchError, match="privada"):
        f._check_url("http://mixto.ejemplo.es/")
    assert f.allow_private is False
    local = fetch.Fetcher()
    local._check_url("http://localhost:8080/")              # tu propio localhost, a propósito: sí
    assert local.allow_private is True
    with pytest.raises(fetch.FetchError):                   # pero solo ese host: otra red privada, no
        local._check_url("http://otro.lan/")
    local._check_url("http://publico.ejemplo.es/")


def test_bomba_zip_en_firma_apk_e_ipa(tmp_path):
    import zipfile

    from eolfi.providers import apksig, apple
    from eolfi.providers.binfmt import ParseError

    apk = tmp_path / "bomba.apk"
    with zipfile.ZipFile(apk, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("AndroidManifest.xml", b"x")
        z.writestr("META-INF/CERT.RSA", b"\0" * (apksig.MAX_SIG_BYTES + 1))
    read = []
    real_read = zipfile.ZipFile.read
    zipfile.ZipFile.read = lambda self, name, *a: (read.append(name), real_read(self, name, *a))[1]
    try:
        with zipfile.ZipFile(apk) as zf:
            out = apksig.apk_signature(str(apk), zf)
    finally:
        zipfile.ZipFile.read = real_read
    assert "META-INF/CERT.RSA" not in read                  # la entrada enorme ni se descomprime
    assert any("ilegible" in f for f in out["findings"])
    with zipfile.ZipFile(tmp_path / "b.ipa", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Payload/X.app/Info.plist", b"\0" * (apple.MAX_META_BYTES + 1))
    with zipfile.ZipFile(tmp_path / "b.ipa") as z, pytest.raises(ParseError, match="descomprimidos"):
        apple._read_capped(z, "Payload/X.app/Info.plist")
