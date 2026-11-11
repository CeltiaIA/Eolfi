"""Paso «mobile» (Android con adb + uiautomator) contra un adb simulado (tests/fake_adb.py).

Lo que se comprueba aquí es la lógica de Eolfi (guion, selección de dispositivo, órdenes adb, análisis del árbol,
privacidad, cobertura, especificación y comparación). Un dispositivo real NO se ejecuta en estas pruebas.
"""
import base64
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from eolfi.core.case_report import build_case_report, render_case_html
from eolfi.core.cases import CaseStore
from eolfi.core.evidence import EvidenceStore
from eolfi.observe import ScriptError, compare_sessions, run_observation, validate_script
from eolfi.observe import mobile
from eolfi.security.levels import session_plan

AUTH = "app sintética propia en un dispositivo simulado"
FAKE = Path(__file__).with_name("fake_adb.py")


@pytest.fixture
def store(tmp_path):
    s = EvidenceStore(tmp_path / "e.db")
    yield s
    s.close()


@pytest.fixture
def adb(tmp_path, monkeypatch):
    """Ejecutable adb simulado (envoltorio .cmd en Windows, sh en POSIX) y su archivo de estado."""
    d = tmp_path / "adb"
    d.mkdir()
    if sys.platform == "win32":
        exe = d / "adb.cmd"
        exe.write_text(f'@echo off\r\n"{sys.executable}" "{FAKE}" %*\r\n', encoding="utf-8")
    else:
        exe = d / "adb"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n', encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    state = tmp_path / "estado-adb.json"
    monkeypatch.setenv("EOLFI_ADB", str(exe))
    monkeypatch.setenv("FAKE_ADB_STATE", str(state))
    return state


def _script(steps, **extra):
    return {"eolfi_observation_script": 1, "name": "móvil", "authorization": AUTH, "steps": steps, **extra}


def _step(**over):
    s = {"id": "app", "action": "mobile", "package": "org.eolfi.muestra", "clear_data": True, "timeout": 60,
         "actions": [{"id": "escribir", "do": "input_text", "resource_id": "org.eolfi.muestra:id/nombre",
                      "value": "Ana"},
                     {"id": "saludar", "do": "tap", "text": "Saludar"},
                     {"id": "esperar", "do": "wait_for", "text": "Hola, Ana"},
                     {"id": "salir", "do": "key", "value": "BACK"}]}
    s.update(over)
    return s


@pytest.mark.parametrize("bad, msg", [
    ({"package": "sin_punto"}, "package"),
    ({"platform": "ios"}, "iOS"),
    ({"device": "a b"}, "device"),
    ({"actions": [{"do": "tap"}]}, "resource_id, text o content_desc"),
    ({"actions": [{"do": "input_text", "text": "x"}]}, "value"),
    ({"actions": [{"do": "key", "value": "POWER"}]}, "key necesita"),
    ({"actions": [{"id": "_inicio", "do": "read"}]}, "id"),
    ({"clear_data": "sí"}, "booleano"),
    ({"argv": ["x"]}, "no admitidas"),
])
def test_validacion_del_paso_mobile(bad, msg):
    with pytest.raises(ScriptError, match=msg):
        validate_script(_script([_step(**bad)]))


def test_mobile_no_admite_contenedor():
    with pytest.raises(ScriptError, match="mobile"):
        validate_script(_script([_step()], isolation={"mode": "container", "image": "python:3.12-slim"}))


def test_sin_adb_no_se_declara_observado(store, tmp_path, monkeypatch):
    monkeypatch.setenv("EOLFI_ADB", str(tmp_path / "no-existe"))
    rep = run_observation(_script([_step()]), store, authorized=True)
    assert rep["steps"][0]["status"] == "unavailable"
    assert rep["coverage"]["ui_mobile"]["status"] == "not_available"
    assert "EOLFI_ADB" in rep["coverage"]["ui_mobile"]["reason"]


@pytest.mark.parametrize("devices, msg", [
    ("-", "ningún dispositivo"),
    ("emulator-5554\tunauthorized\n", "sin autorizar"),
    ("a\tdevice\nb\tdevice\n", "indica cuál"),
])
def test_seleccion_de_dispositivo(store, adb, monkeypatch, devices, msg):
    monkeypatch.setenv("FAKE_ADB_DEVICES", devices)
    rep = run_observation(_script([_step()]), store, authorized=True)
    assert rep["steps"][0]["status"] == "unavailable" and msg in rep["steps"][0]["error"]


def test_paquete_no_instalado_es_error_sin_instalar(store, adb):
    rep = run_observation(_script([_step(package="org.eolfi.otra")]), store, authorized=True)
    step = rep["steps"][0]
    assert step["status"] == "error" and "no está instalado" in step["error"]
    log = json.loads(adb.read_text(encoding="utf-8"))["log"]
    assert not any("install" in " ".join(c) for c in log)


def test_escenario_android_completo(store, adb):
    cid = CaseStore(store).create("app móvil sintética")["case_id"]
    rep = run_observation(_script([_step(screenshots=True)]), store, authorized=True, case_id=cid)
    step = rep["steps"][0]
    assert step["status"] == "ok", json.dumps(step)[:3000]
    assert [a["id"] for a in step["actions"]] == ["_inicio", "escribir", "saludar", "esperar", "salir"]
    assert step["app"] == {"package": "org.eolfi.muestra", "installed": True,
                           "apk_paths": ["/data/app/org.eolfi.muestra/base.apk"], "version_name": "1.2",
                           "version_code": 3}
    dev = step["device"]
    assert dev["model"] == "Sintetico" and dev["sdk"] == "34" and len(dev["serial_sha256"]) == 16
    assert "emulator-5554" not in json.dumps(rep) and "no-debe-guardarse" not in json.dumps(rep)
    assert step["cleared_data"] is True and step["stopped"] is True

    def el(action, rid):
        return next(e for e in action["screen"]["elements"] if e["resource_id"] == f"org.eolfi.muestra:id/{rid}")

    ini, esc, sal, esp, back = step["actions"]
    assert ini["screen"]["activity"] == "org.eolfi.muestra.Principal"
    assert el(ini, "saludo")["text"] == "" and el(esc, "nombre")["text"] == "Ana"
    assert el(sal, "saludo")["text"] == "Hola, Ana" and esp["status"] == "ok"
    assert el(ini, "clave")["text"] is None and el(ini, "clave")["password"] is True
    assert "secreto" not in json.dumps(rep)
    assert back["screen"]["package"] == "com.android.launcher3"
    assert ini["screen_sha256"] != sal["screen_sha256"]
    assert esc["value_sha256"] == hashlib.sha256(b"Ana").hexdigest()
    for a in step["actions"]:
        shot = a["screenshot"]
        data = base64.b64decode(shot["data_base64"])
        assert shot["status"] == "captured" and shot["mime_type"] == "image/png"
        assert (shot["width"], shot["height"]) == (360, 640) and hashlib.sha256(data).hexdigest() == shot["sha256"]
    assert rep["coverage"]["ui_mobile"]["status"] == "observed"
    assert rep["coverage"]["ui_mobile"]["screenshots"] == "captured"
    assert rep["coverage"]["visual_content"]["status"] == "not_redacted"
    assert any(f["factor"] == "dispositivo Android" for f in rep["unfixed_factors"])
    assert not any(f["factor"] == "datos de la app" for f in rep["unfixed_factors"])     # clear_data=true
    report = build_case_report(CaseStore(store).get(cid))
    assert len(report["screenshots"]) == 5
    assert "data:image/png;base64," in render_case_html(report)


def test_comparacion_y_especificacion(store, adb, tmp_path):
    from eolfi.spec import build_spec

    a = run_observation(_script([_step()]), store, authorized=True)
    adb.unlink()                                               # dispositivo «limpio» otra vez
    b = run_observation(_script([_step(actions=[_step()["actions"][0],
                                                {"id": "saludar", "do": "tap", "text": "Saludar"}])]),
                        store, authorized=True)
    cmp_ = compare_sessions(a, b)
    assert not cmp_["identical"]
    same = run_observation(_script([_step()]), store, authorized=True)
    assert compare_sessions(a, same)["identical"], json.dumps(compare_sessions(a, same))[:2000]

    cid = CaseStore(store).create("spec móvil")["case_id"]
    for _ in range(2):
        run_observation(_script([_step()]), store, authorized=True, case_id=cid)
    spec = build_spec(store, cid)
    req = next(r for r in spec["requirements"] if r["inputs"]["action"] == "mobile")
    assert req["inputs"]["package"] == "org.eolfi.muestra"
    sm = req["state_machine"]
    assert {s["label"] for s in sm["states"]} >= {"org.eolfi.muestra.Principal"}
    assert [t["action"] for t in sm["transitions"]] == ["escribir", "saludar", "esperar", "salir"]
    screens = req["examples"]["screens"]
    assert screens[2]["visible_texts"][-1] == "Hola, Ana" and screens[1]["value"] == "Ana"


def test_plan_muestra_dispositivo_y_borrado(adb):
    plan = session_plan(validate_script(_script([_step()])), Path("."))
    prog = next(p for p in plan["programs"] if p["action"] == "mobile")
    assert prog["found"] and prog["package"] == "org.eolfi.muestra"
    assert plan["permissions"]["mobile_adb"] is True
    assert any("dispositivo Android real" in w for w in plan["warnings"])
    assert any("clear_data BORRA" in w for w in plan["warnings"])


def test_analisis_del_arbol_rechaza_dtd_y_acota():
    with pytest.raises(mobile.AdbError, match="DTD"):
        mobile.parse_hierarchy('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><hierarchy></hierarchy>')
    nodes = "".join(f'<node text="t{i}" resource-id="" bounds="[0,0][1,1]"/>' for i in range(400))
    parsed = mobile.parse_hierarchy(f"<hierarchy>{nodes}</hierarchy>")
    assert len(parsed["elements"]) == mobile.MAX_ELEMENTS and parsed["truncated"] and parsed["elements_total"] == 400
    assert mobile.shell_quote_text("a b'c") == "'a%sb'\"'\"'c'"
    assert os.path.basename(__file__)


# -- situaciones vistas en un dispositivo real (Redmi Note 12R Pro, Android 14) ---------------------------------
def test_reintenta_el_volcado_mientras_la_ventana_se_dibuja(store, adb, monkeypatch):
    monkeypatch.setenv("FAKE_ADB_DUMP_FAILS", "2")
    rep = run_observation(_script([_step()]), store, authorized=True)
    assert rep["steps"][0]["status"] == "ok", rep["steps"][0].get("error")
    monkeypatch.setenv("FAKE_ADB_DUMP_FAILS", "99")
    adb.unlink()
    rep = run_observation(_script([_step()]), store, authorized=True)
    step = rep["steps"][0]
    assert step["status"] == "error" and "could not get idle state" in step["error"]
    assert step["stopped"] is True                       # la app se cierra aunque el paso falle


def test_entrada_bloqueada_se_explica_y_no_es_comportamiento(store, adb, monkeypatch):
    from eolfi.spec import build_spec

    monkeypatch.setenv("FAKE_ADB_BLOCK_INPUT", "1")
    cid = CaseStore(store).create("entrada bloqueada")["case_id"]
    for _ in range(2):
        rep = run_observation(_script([_step()]), store, authorized=True, case_id=cid)
        adb.unlink()
    step = rep["steps"][0]
    assert step["status"] == "partial" and "INJECT_EVENTS" in step["input_blocked"]
    assert "Depuración USB (ajustes de seguridad)" in step["error"]
    assert [a["status"] for a in step["actions"]] == ["ok", "input_blocked", "skipped", "skipped", "skipped"]
    req = next(r for r in build_spec(store, cid)["requirements"] if r["inputs"]["action"] == "mobile")
    assert req["status"] == "not_observed" and req["certainty"] == "desconocido"
    assert "INJECT_EVENTS" in req["not_observed_reason"][0]


def test_pantalla_bloqueada_antes_y_durante(store, adb, monkeypatch):
    from eolfi.spec import build_spec

    monkeypatch.setenv("FAKE_ADB_LOCKED", "1")
    rep = run_observation(_script([_step()]), store, authorized=True)
    assert rep["steps"][0]["status"] == "unavailable" and "apagada o bloqueada" in rep["steps"][0]["error"]
    log = json.loads(adb.read_text(encoding="utf-8"))["log"]
    assert not any("input" in " ".join(c) for c in log)  # no intenta desbloquear ni tocar nada
    adb.unlink()
    monkeypatch.delenv("FAKE_ADB_LOCKED")
    monkeypatch.setenv("FAKE_ADB_LOCK_AFTER", "2")       # se apaga tras escribir el nombre (tap + text)
    cid = CaseStore(store).create("bloqueo a mitad")["case_id"]
    for _ in range(2):
        rep = run_observation(_script([_step()]), store, authorized=True, case_id=cid)
        adb.unlink()
    step = rep["steps"][0]
    assert [a["status"] for a in step["actions"]] == ["ok", "ok", "interrupted", "skipped", "skipped"]
    assert "se apagó o se bloqueó" in step["interrupted"]
    req = next(r for r in build_spec(store, cid)["requirements"] if r["inputs"]["action"] == "mobile")
    assert req["status"] == "not_observed" and req["certainty"] == "desconocido"


def test_primer_plano_exige_la_ventana_dibujada():
    drv = mobile._Driver(None, {"package": "org.eolfi.muestra"}, None)
    assert drv.in_front({"package": "org.eolfi.muestra", "window_package": "org.eolfi.muestra"})
    assert not drv.in_front({"package": "org.eolfi.muestra", "window_package": "com.android.systemui"})
