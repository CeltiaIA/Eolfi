"""Liberación del turno del motor ante cancelación y errores, sin usar la GPU."""
from contextlib import contextmanager

import pytest

from eolfi import eolas_v2, server


@pytest.mark.parametrize("error", [server.JobCancelled, RuntimeError])
def test_error_en_aviso_de_turno_libera_contexto_inmediatamente(tmp_path, monkeypatch, error):
    app = server.EolfiApp(str(tmp_path / "e.db"))
    estado = {"intentos": 0, "liberado": False}

    @contextmanager
    def motor(_perfil):
        estado["intentos"] += 1
        if estado["intentos"] == 1:
            raise eolas_v2.EolasBusy("ocupado")
        try:
            yield {"alias": "modelo"}
        finally:
            estado["liberado"] = True

    def progreso(msg):
        if "ya está libre" in msg:
            raise error()

    monkeypatch.setattr(eolas_v2, "inference_profile", motor)
    monkeypatch.setattr(app, "_progress", progreso)
    monkeypatch.setattr(app, "_dormir", lambda _n: None)
    # Mantener el traceback: la liberación debe ocurrir al salir, no depender del recolector.
    with pytest.raises(error) as exc:
        with app._eolas_en_turno("gemma"):
            pytest.fail("El aviso ya ha cancelado o fallado")
    assert exc.value is not None
    assert estado == {"intentos": 2, "liberado": True}


@pytest.mark.parametrize("esperar", [False, True])
@pytest.mark.parametrize("fallar_cuerpo", [False, True])
def test_turno_se_cierra_al_terminar_o_fallar_el_trabajo(tmp_path, monkeypatch, esperar, fallar_cuerpo):
    app = server.EolfiApp(str(tmp_path / "e.db"))
    eventos = []
    intentos = 0

    @contextmanager
    def motor(_perfil):
        nonlocal intentos
        intentos += 1
        if esperar and intentos == 1:
            raise eolas_v2.EolasBusy("ocupado")
        eventos.append("adquirido")
        try:
            yield {"alias": "modelo"}
        finally:
            eventos.append("liberado")

    monkeypatch.setattr(eolas_v2, "inference_profile", motor)
    monkeypatch.setattr(app, "_progress", lambda _msg: None)
    monkeypatch.setattr(app, "_dormir", lambda _n: None)

    def trabajo():
        with app._eolas_en_turno("gemma") as cfg:
            assert cfg["alias"] == "modelo" and eventos == ["adquirido"]
            if fallar_cuerpo:
                raise RuntimeError("fallo del trabajo")

    if fallar_cuerpo:
        with pytest.raises(RuntimeError, match="fallo del trabajo"):
            trabajo()
    else:
        trabajo()
    assert eventos == ["adquirido", "liberado"]


@pytest.mark.parametrize("limite,esperas", [("1", [1]), ("6", [5, 1]), ("0", []), ("-2", [])])
def test_espera_no_supera_el_plazo_configurado(tmp_path, monkeypatch, limite, esperas):
    app = server.EolfiApp(str(tmp_path / "e.db"))
    llamadas = []

    def ocupado(_perfil):
        raise eolas_v2.EolasBusy("ocupado")

    monkeypatch.setenv("EOLFI_ESPERA_IA_SEG", limite)
    monkeypatch.setattr(eolas_v2, "inference_profile", ocupado)
    monkeypatch.setattr(app, "_progress", lambda _msg: None)
    monkeypatch.setattr(app, "_dormir", llamadas.append)
    with pytest.raises(RuntimeError, match="esperados"):
        with app._eolas_en_turno("gemma"):
            pytest.fail("No se obtuvo turno")
    assert llamadas == esperas


@pytest.mark.parametrize("limite", ["inf", "-inf", "nan", "no-numero"])
def test_plazo_invalido_usa_el_predeterminado_finito(tmp_path, monkeypatch, limite):
    app = server.EolfiApp(str(tmp_path / "e.db"))
    llamadas = []

    def ocupado(_perfil):
        raise eolas_v2.EolasBusy("ocupado")

    def dormir(segundos):
        llamadas.append(segundos)
        if len(llamadas) > 240:
            pytest.fail("La espera quedó sin límite")

    monkeypatch.setenv("EOLFI_ESPERA_IA_SEG", limite)
    monkeypatch.setattr(eolas_v2, "inference_profile", ocupado)
    monkeypatch.setattr(app, "_progress", lambda _msg: None)
    monkeypatch.setattr(app, "_dormir", dormir)
    with pytest.raises(RuntimeError, match="esperados 1200 s"):
        with app._eolas_en_turno("gemma"):
            pytest.fail("No se obtuvo turno")
    assert sum(llamadas) == 1200
