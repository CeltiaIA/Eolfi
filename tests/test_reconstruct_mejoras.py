"""Fase 4: mejoras con razón verificable, compatibilidad conductual, compilación e independencia del original."""
import json
import os
import subprocess
import sys

import pytest

from eolfi.cli import main
from eolfi.core.cases import CaseStore
from eolfi.observe import run_observation, run_replay
from eolfi.reconstruct import build_model, generate, reconstruct, verify
from eolfi.reconstruct.core import MANIFEST, independence
from eolfi.reconstruct.improvements import CATEGORIES, CATALOG, parse
from eolfi.spec import store_spec
from tests import observe_samples as samples
from tests.test_observe import _script
from tests import test_reconstruct as _tr
from tests.test_reconstruct import _http_case, _observed_case

# Las mismas fixtures que tests/test_reconstruct.py (base temporal y API sintética).
store = _tr.store
sample_api = _tr.sample_api

# Escribe UTF-8 explícitamente: lo observado no depende de la codificación de la consola del equipo.
NO_ASCII = "import sys\nsys.stdout.buffer.write(('año: ñandú ' + sys.stdin.read() + chr(10)).encode('utf-8'))\n"


def _cli_case(store, tmp_path, source, stdin="x"):
    cid = CaseStore(store).create("utf8")["case_id"]
    t = samples.write(tmp_path, "texto.py", source)
    a = run_observation(_script(t, [{"id": "uno", "action": "run", "argv": ["{python}", "{target}"],
                                     "stdin": {"text": stdin}}]), store, authorized=True, case_id=cid)
    run_replay(store, a["evidence_id"], authorized=True, case_id=cid)
    store_spec(store, cid)
    return cid, t


def test_catalogo_con_razon_y_categoria_admitida():
    assert CATALOG and all(m["category"] in CATEGORIES and m["reason"] and m["check"] for m in CATALOG.values())
    assert parse("seguridad-limite-cuerpo=10") == ("seguridad-limite-cuerpo", "10")
    with pytest.raises(ValueError, match="desconocida"):
        parse("mas-rapido")


def test_http_mejoras_aplicadas_comprobadas_y_compatibles(store, tmp_path, sample_api):
    cid = _http_case(store, sample_api)
    model = build_model(store, cid)
    base = tmp_path / "base"
    generate(model, base, target="python-http")
    v0 = verify(base)
    out = tmp_path / "mejorada"
    gen = generate(model, out, target="python-http",
                   improvements=["seguridad-nosniff", "seguridad-limite-cuerpo=1024"])
    assert [i["status"] for i in gen["improvements"]] == ["applied", "applied"]
    assert json.loads((out / "mejoras.json").read_text(encoding="utf-8")) == {"nosniff": True, "max_body": 1024}
    manifest = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    assert {i["id"] for i in manifest["improvements"]} == {"seguridad-nosniff", "seguridad-limite-cuerpo"}
    assert all(i["reason"] and i["category"] == "seguridad" for i in manifest["improvements"])
    v = verify(out)
    assert v["improvements_verified"] is True and v["build"]["status"] == "ok"
    assert {c["id"]: c["verified"] for c in v["improvements"]} == {"seguridad-nosniff": True,
                                                                     "seguridad-limite-cuerpo": True}
    # Compatibilidad conductual: los casos observados dan lo mismo con y sin mejoras.
    assert [(r["requirement"], r["status"]) for r in v["results"]] == \
        [(r["requirement"], r["status"]) for r in v0["results"]]
    assert v["differ"] == 0 and v0["improvements_verified"] is None and not v0["improvements"]
    # Las pruebas generadas siguen en verde con las mejoras.
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(out / "tests")],
                           capture_output=True, cwd=out)
    assert tests.returncode == 0, tests.stdout.decode("utf-8", "replace")[-2000:]


def test_mejoras_incompatibles_o_sin_razon_comprobable_se_rechazan(store, tmp_path, sample_api):
    cid = _http_case(store, sample_api)
    model = build_model(store, cid)
    out = tmp_path / "rec"
    gen = generate(model, out, target="python-http",
                   improvements=["seguridad-limite-cuerpo=3", "compatibilidad-utf8"])
    limite, utf8 = gen["improvements"]
    # El cuerpo observado de POST /api/eco tiene más de 3 bytes: aplicarla rompería ese requisito.
    assert limite["status"] == "rejected" and "rompería la compatibilidad" in limite["why"] and limite["requirements"]
    assert utf8["status"] == "rejected" and "python-cli" in utf8["why"]
    assert not (out / "mejoras.json").exists()
    v = verify(out)
    assert v["improvements_verified"] is None and len(v["improvements_rejected"]) == 2
    with pytest.raises(ValueError, match="repetida"):
        generate(model, out, target="python-http", improvements=["seguridad-nosniff", "seguridad-nosniff"])
    # Sin salida no ASCII observada, la razón de la mejora UTF-8 no se puede comprobar: se rechaza.
    cli = _observed_case(store, tmp_path)
    g = generate(build_model(store, cli), tmp_path / "cli", improvements=["compatibilidad-utf8"])
    assert g["improvements"][0]["status"] == "rejected" and "ASCII" in g["improvements"][0]["why"]


def test_utf8_razon_demostrada_y_regeneracion_la_retira(store, tmp_path):
    cid, _t = _cli_case(store, tmp_path, NO_ASCII)
    model = build_model(store, cid)
    plain, better = tmp_path / "sin", tmp_path / "con"
    generate(model, plain)
    gen = generate(model, better, improvements=["compatibilidad-utf8"])
    assert gen["improvements"][0]["status"] == "applied"
    env = {**os.environ, "PYTHONIOENCODING": "ascii"}
    # La razón es real: sin la mejora, una consola ASCII rompe la salida observada.
    p = subprocess.run([sys.executable, str(plain / "app.py")], input=b"x", capture_output=True, env=env,
                       cwd=tmp_path)
    assert p.returncode != 0 and b"UnicodeEncodeError" in p.stderr
    q = subprocess.run([sys.executable, str(better / "app.py")], input=b"x", capture_output=True, env=env,
                       cwd=tmp_path)
    assert q.returncode == 0 and q.stdout.decode("utf-8").startswith("año: ñandú x")
    v = verify(better)
    assert v["improvements_verified"] is True and v["match"] == v["cases"] - v["partial"] - v["pending"]
    # Regenerar sin pedir la mejora retira mejoras.json (no se había editado a mano).
    again = generate(model, better)
    assert again["removed"] == ["mejoras.json"] and not (better / "mejoras.json").exists()


def test_compila_e_independiente_del_original(store, tmp_path):
    cid, target = _cli_case(store, tmp_path, NO_ASCII)
    out = tmp_path / "rec"
    rep = reconstruct(store, cid, out)
    v = rep["verification"]
    assert v["build"]["status"] == "ok" and v["build"]["python_files"] >= 2
    ind = v["independence"]
    assert ind["status"] == "independiente" and ind["checked"][0]["name"] == "texto.py" and not ind["shared_lines"]
    ev = store.get_evidence(rep["evidence_id"])
    assert json.loads(ev["result"])["independence"]["status"] == "independiente"
    # Si alguien pegara código del original en la base, la comprobación lo detecta.
    app = out / "app.py"
    app.write_text(app.read_text(encoding="utf-8") + "\n" + NO_ASCII.splitlines()[1] + "\n", encoding="utf-8")
    assert independence(out, [target])["status"] == "copia"
    assert independence(out, [tmp_path / "no-existe.py"])["status"] == "no_comprobado"
    (out / "roto.py").write_text("def (:\n", encoding="utf-8")
    assert verify(out)["build"]["status"] == "error"


def test_cli_mejora(store, tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cid, _t = _cli_case(store, tmp_path, NO_ASCII)
    store.close()
    code = main(["--db", str(tmp_path / "e.db"), "reconstruct", "--case", cid, "--out", "rec",
                 "--mejora", "compatibilidad-utf8", "--mejora", "seguridad-nosniff"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0, out
    v = out["verification"]
    assert v["improvements_verified"] is True
    assert [i["id"] for i in v["improvements_rejected"]] == ["seguridad-nosniff"]
    code = main(["--db", str(tmp_path / "e.db"), "reconstruct", "--case", cid, "--out", "rec2", "--mejora", "x"])
    assert code == 1 and "mejora desconocida" in capsys.readouterr().out
