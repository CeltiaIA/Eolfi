"""La guía ejemplos/puente/GUIA.md, pasos C y D: pasarela real del puente con un chat simulado."""
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from eolfi.cli import main

ROOT = Path(__file__).resolve().parents[1]
EJEMPLOS = ROOT / "ejemplos"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="la pasarela del puente y la verificación usan Node.js")


@pytest.fixture
def guia(tmp_path, monkeypatch):
    work = tmp_path / "puente"
    shutil.copytree(EJEMPLOS / "puente", work)
    monkeypatch.chdir(work)
    return work


@pytest.fixture
def pasarela(guia, monkeypatch):
    procs = []

    def start(deny=False):
        bfile = guia / ("bridge-denegar.json" if deny else "bridge.json")
        replies = guia / "respuestas-simuladas.json"
        env = {**os.environ, "EOLFI_FAKE_BRIDGE_DENY": "1" if deny else "0"}
        procs.append(subprocess.Popen(["node", "tests/fake_bridge.mjs", str(bfile), str(replies)], cwd=ROOT, env=env))
        for _ in range(200):
            if bfile.exists() and bfile.stat().st_size:
                break
            time.sleep(0.05)
        monkeypatch.setenv("EOLFI_BRIDGE_FILE", str(bfile))
        return json.loads(bfile.read_text(encoding="utf-8")), replies
    yield start
    for p in procs:
        p.kill()
        p.wait(timeout=10)


def run(capsys, *args):
    code = main(["--db", "guia.db", *args])
    out = capsys.readouterr().out
    return code, (json.loads(out) if out.strip().startswith(("{", "[")) else out)


def _http(info, path, *, token=None, host=None, method="GET"):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if host:
        headers["Host"] = host
    req = urllib.request.Request(info["url"] + path, method=method, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, json.loads(exc.read() or b"{}")


def test_guia_puente_cambio_con_chat_simulado(guia, pasarela, capsys):
    texto = (guia / "GUIA.md").read_text(encoding="utf-8")
    assert "--provider meta-web" in texto and "tests/fake_bridge.mjs" in texto
    code, created = run(capsys, "create", "--from", str(EJEMPLOS / "web-y-repo" / "sitio"), "--out", "proyecto",
                        "--name", "Notas")
    assert code == 0 and created["verification"]["ok"] is True
    _info, replies = pasarela()
    code, rep = run(capsys, "assist", "proyecto", "--brief", "Destaca las notas nuevas", "--provider", "meta-web")
    assert code == 0 and rep["ok"] is True and rep["provider"] == "meta-web" and rep["restored"] is False
    assert rep["files_changed"] == ["css/ofertas.css"]
    assert (guia / "proyecto" / "css" / "ofertas.css").read_text(encoding="utf-8") == ".nota-nueva { font-weight: 600; }\n"
    seen = json.loads(Path(str(replies) + ".seen.json").read_text(encoding="utf-8"))
    assert len(seen) == 1 and seen[0]["site"] == "meta" and seen[0]["first"].startswith("Eres un ingeniero")
    assert seen[0]["length"] <= 31_000


def test_guia_puente_permiso_denegado_no_cambia_nada(guia, pasarela, capsys):
    run(capsys, "create", "--from", str(EJEMPLOS / "web-y-repo" / "sitio"), "--out", "proyecto", "--name", "Notas")
    antes = {p.relative_to(guia): p.read_bytes() for p in (guia / "proyecto").rglob("*") if p.is_file()}
    pasarela(deny=True)
    code = main(["--db", "guia.db", "assist", "proyecto", "--brief", "x", "--provider", "meta-web"])
    err = capsys.readouterr().err
    assert code == 1 and "El usuario denegó el envío en el puente" in err
    despues = {p.relative_to(guia): p.read_bytes() for p in (guia / "proyecto").rglob("*") if p.is_file()}
    assert despues == antes


def test_guia_puente_protecciones_de_la_pasarela(guia, pasarela):
    info, _ = pasarela()
    assert _http(info, "/v1/status")[0] == 401
    assert _http(info, "/v1/status", token="x" * 64)[0] == 401
    assert _http(info, "/v1/status", token=info["token"], host="evil.example:80")[0] == 421
    assert _http(info, "/v1/screen?provider=meta", token=info["token"])[0] == 403
    status, body = _http(info, "/v1/status", token=info["token"])
    assert status == 200 and body["providers"]["meta"]["ok"] is True
