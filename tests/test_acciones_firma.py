"""B8: firma HMAC de la cadena de acciones y unión con la cadena del RSI."""
from __future__ import annotations

import hashlib
import json

import pytest

from eolfi import acciones, rsi
from eolfi.cli import main


@pytest.fixture
def clave(tmp_path):
    return acciones.generar_clave(tmp_path / "fuera" / "clave.hex")["clave"]


def _reescribir_igual(path, cambio):
    """Reescribe el registro con una cadena nueva y válida (lo que haría quien puede escribir el archivo)."""
    evs = acciones.eventos(path)
    prev = acciones.CERO
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for e in evs:
            cambio(e)
            e["prev"] = prev
            e["sha256"] = acciones._digest(e)
            prev = e["sha256"]
            fh.write(acciones._canon(e) + "\n")


def test_firmar_y_verificar(clave):
    for i in range(3):
        acciones.anotar(f"prueba.{i}")
    f = acciones.firmar(clave)
    assert f["firmado_hasta"] == 3 and f["evento"] == 4
    res = acciones.verificar_firmas(clave)
    assert res["ok"] and res["firmas"] == 1 and res["firmado_hasta"] == 3 and res["sin_firmar_al_final"] == 0
    acciones.anotar("prueba.posterior")
    assert acciones.verificar_firmas(clave)["sin_firmar_al_final"] == 1
    assert "hmac" in acciones.eventos()[3]["resultado"] and len(acciones.eventos()[3]["resultado"]["hmac"]) == 64


def test_reescritura_valida_sin_clave_se_detecta(clave):
    for i in range(3):
        acciones.anotar(f"prueba.{i}", params={"x": i})
    acciones.firmar(clave)
    _reescribir_igual(acciones.registro_file(), lambda e: e["params"].update(x=99) if "x" in e["params"] else None)
    assert acciones.verificar()["ok"] is True                      # la cadena sola no lo ve
    res = acciones.verificar_firmas(clave)
    assert res["ok"] is False and res["firma_rota"] == 4


def test_firma_falsificada_sin_clave_se_detecta(clave, tmp_path):
    acciones.anotar("prueba")
    kid = acciones.generar_clave(tmp_path / "otra" / "k.hex")["clave_id"]
    assert kid != acciones.verificar_firmas(clave)["clave_id"]
    cabeza = acciones.verificar()["ultimo"]
    real = acciones._clave_id(acciones._leer_clave(clave))
    acciones.anotar("acciones.firma", params={"hasta_seq": 1, "cabeza": cabeza, "clave_id": real},
                    resultado={"hmac": hashlib.sha256(b"inventado").hexdigest()})
    res = acciones.verificar_firmas(clave)
    assert res["ok"] is False and res["firma_rota"] == 2


def test_firmas_de_otra_clave_se_cuentan_aparte(clave, tmp_path):
    otra = acciones.generar_clave(tmp_path / "otra" / "k.hex")["clave"]
    acciones.anotar("prueba")
    acciones.firmar(otra)
    res = acciones.verificar_firmas(clave)
    assert res["ok"] and res["firmas"] == 0 and res["firmas_de_otra_clave"] == 1 and "aviso" in res


def test_clave_no_se_sustituye_ni_va_junto_al_registro(tmp_path, clave):
    with pytest.raises(ValueError, match="ya existe"):
        acciones.generar_clave(clave)
    with pytest.raises(ValueError, match="junto al registro"):
        acciones.generar_clave(acciones.registro_file().parent / "clave.hex")
    (tmp_path / "corta.hex").write_text("abcd", encoding="ascii")
    with pytest.raises(ValueError, match="32 bytes"):
        acciones.firmar(tmp_path / "corta.hex")
    with pytest.raises(ValueError, match="falta la clave"):
        acciones.firmar(None)


def test_no_firma_cadena_rota_ni_vacia(clave):
    with pytest.raises(ValueError, match="no hay eventos"):
        acciones.firmar(clave)
    acciones.anotar("a")
    acciones.anotar("b")
    lineas = acciones.registro_file().read_text(encoding="utf-8").splitlines()
    acciones.registro_file().write_text(lineas[1] + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cadena rota"):
        acciones.firmar(clave)


def test_rsi_refleja_sus_acciones_y_no_las_observaciones():
    rsi.observar("rea", "binary", {"ok": True})
    rsi._anotar("decision", {"id": "abc123", "decision": "rechazar", "por": "titular", "texto_largo": "x" * 900})
    reflejos = [e for e in acciones.eventos() if e["operacion"].startswith("rsi.")]
    assert [e["operacion"] for e in reflejos] == ["rsi.decision"]
    p = reflejos[0]["params"]
    assert p["rsi_seq"] == 2 and p["id"] == "abc123" and p["por"] == "titular" and "texto_largo" not in p
    assert reflejos[0]["origen"] == "rsi"
    res = acciones.verificar_rsi()
    assert res["ok"] and res["reflejos"] == 1 and res["rsi_sin_reflejo"] == []


def test_reescribir_el_rsi_rompe_el_reflejo():
    rsi._anotar("observacion", {"ok": True})
    rsi._anotar("propuesta", {"id": "p1", "superficie": "eolas_v2.max_tokens"})
    rsi._anotar("decision", {"id": "p1", "decision": "aprobar", "por": "titular"})
    assert acciones.verificar_rsi()["ok"]
    # Reescritura coherente del registro del RSI (su cadena sigue siendo válida) cambiando la observación.
    path = rsi._registro()
    evs = rsi.eventos()
    evs[0]["datos"] = {"ok": False}
    prev = "0" * 64
    with path.open("w", encoding="utf-8") as fh:
        for e in evs:
            e["prev"] = prev
            body = {k: v for k, v in e.items() if k != "sha256"}
            e["sha256"] = hashlib.sha256(rsi._canon(body).encode("utf-8")).hexdigest()
            prev = e["sha256"]
            fh.write(rsi._canon(e) + "\n")
    assert rsi.verificar_registro()["ok"] is True
    res = acciones.verificar_rsi()
    assert res["ok"] is False and "reflejo_roto" in res


def test_rsi_anterior_a_la_union_y_reflejo_perdido(monkeypatch):
    monkeypatch.setenv("EOLFI_ACCIONES", "0")
    rsi._anotar("propuesta", {"id": "viejo"})                     # antes de unir: sin reflejo, se cuenta aparte
    monkeypatch.setenv("EOLFI_ACCIONES", "1")
    rsi._anotar("propuesta", {"id": "nuevo"})
    res = acciones.verificar_rsi()
    assert res["ok"] and res["rsi_anteriores_a_la_union"] == 1
    monkeypatch.setenv("EOLFI_ACCIONES", "0")
    rsi._anotar("decision", {"id": "nuevo", "decision": "aprobar"})   # escribir el reflejo «falla»
    monkeypatch.setenv("EOLFI_ACCIONES", "1")
    res = acciones.verificar_rsi()
    assert res["ok"] is False and res["rsi_sin_reflejo"] == [3]


def test_cli_clave_firmar_y_verificar(tmp_path, capsys):
    destino = tmp_path / "usb" / "clave.hex"
    assert main(["acciones", "clave", "--destino", str(destino)]) == 0
    acciones.anotar("prueba")
    rsi._anotar("decision", {"id": "x", "decision": "aprobar"})
    assert main(["acciones", "firmar", "--clave", str(destino)]) == 0
    capsys.readouterr()
    assert main(["acciones", "verificar", "--clave", str(destino), "--rsi"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["firmas"]["firmas"] == 1 and out["rsi"]["reflejos"] == 1
    assert main(["acciones", "verificar", "--clave", str(tmp_path / "no-existe.hex")]) == 2
    assert main(["acciones", "firmar", "--clave", str(tmp_path / "no-existe.hex")]) == 2


# ── Firma automática (18/11/2026) ─────────────────────────────────────────────────────────────────────────────────
def test_firma_automatica_no_deja_cola(clave, monkeypatch):
    monkeypatch.setenv("EOLFI_ACCIONES_FIRMA_AUTO", "1")
    monkeypatch.setenv("EOLFI_ACCIONES_CLAVE", clave)
    a = acciones.anotar("prueba.uno")
    b = acciones.anotar("prueba.dos", params={"x": 1})
    evs = acciones.eventos()
    assert [e["operacion"] for e in evs] == ["prueba.uno", "acciones.firma", "prueba.dos", "acciones.firma"]
    assert evs[1]["origen"] == "auto" and evs[1]["params"]["hasta_seq"] == a["seq"]
    assert evs[3]["params"]["cabeza"] == b["sha256"]
    res = acciones.verificar_firmas()
    assert res["ok"] and res["firmas"] == 2 and res["sin_firmar_al_final"] == 0 and res["firmas_fallidas"] == 0
    # Una firma a mano no se firma a sí misma otra vez.
    acciones.firmar()
    assert [e["operacion"] for e in acciones.eventos()][-2:] == ["acciones.firma", "acciones.firma"]
    # Reescribir lo firmado con una cadena coherente sigue detectándose.
    _reescribir_igual(acciones.registro_file(), lambda e: e["params"].update(x=2) if e["seq"] == b["seq"] else None)
    assert not acciones.verificar_firmas()["ok"]


def test_firma_automatica_sin_clave_no_bloquea(monkeypatch, tmp_path):
    monkeypatch.setenv("EOLFI_ACCIONES_FIRMA_AUTO", "1")
    monkeypatch.delenv("EOLFI_ACCIONES_CLAVE", raising=False)
    assert acciones.anotar("prueba")["seq"] == 1
    fallo = acciones.eventos()[-1]
    assert fallo["operacion"] == "acciones.firma" and fallo["ok"] is False and "falta la clave" in fallo["error"]
    assert acciones.verificar()["ok"]
    # Clave junto al registro: tampoco se firma con ella.
    junto = acciones.registro_file().parent / "clave.hex"
    junto.write_text("ab" * 32, encoding="ascii")
    monkeypatch.setenv("EOLFI_ACCIONES_CLAVE", str(junto))
    acciones.anotar("prueba.dos")
    assert "junto al registro" in acciones.eventos()[-1]["error"]
    otra = acciones.generar_clave(tmp_path / "fuera2" / "c.hex")["clave"]
    res = acciones.verificar_firmas(otra)
    assert res["firmas_fallidas"] == 2 and res["firmas"] == 0 and res["sin_firmar_al_final"] == 2


def test_sin_firma_automatica_no_cambia_nada(clave, monkeypatch):
    monkeypatch.delenv("EOLFI_ACCIONES_FIRMA_AUTO", raising=False)
    monkeypatch.setenv("EOLFI_ACCIONES_CLAVE", clave)
    acciones.anotar("prueba")
    assert [e["operacion"] for e in acciones.eventos()] == ["prueba"]
