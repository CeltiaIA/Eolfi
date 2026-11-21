import json
import subprocess

import pytest

from eolfi import cortafuegos


def _result(stdout="", stderr="", code=0):
    return subprocess.CompletedProcess([], code, stdout, stderr)


def test_vista_previa_consulta_regla_exacta(tmp_path):
    exe = tmp_path / "llama-server.exe"
    exe.write_bytes(b"MZ")
    calls = []

    def run(script, env):
        calls.append((script, env))
        return _result('{"existe":false}')

    result = cortafuegos.estado(exe, sistema="windows", run=run)
    assert result["estado"] == "ausente" and result["verificada"]
    assert calls[0][1]["EOLFI_REGLA"].startswith("Eolfi sin red ")
    assert str(exe) not in calls[0][0]


def test_aplicar_y_retirar_verifican_sin_interpolar_rutas(tmp_path, monkeypatch):
    exe = tmp_path / "servidor $ especial.exe"
    exe.write_bytes(b"MZ")
    estados = iter([
        _result(), _result(json.dumps({"existe": True, "enabled": "True", "direction": "Outbound",
                                      "action": "Block", "program": str(exe)})),
        _result(), _result('{"existe":false}'),
    ])
    anotados = []
    monkeypatch.setattr("eolfi.acciones.anotar", lambda *a, **kw: anotados.append((a, kw)))

    def run(script, env):
        assert str(exe) not in script
        return next(estados)

    assert cortafuegos.cambiar(exe, aplicar=True, sistema="windows", run=run)["estado"] == "bloqueado"
    assert cortafuegos.cambiar(exe, aplicar=False, sistema="windows", run=run)["estado"] == "ausente"
    assert [a[0][0] for a in anotados] == ["cortafuegos.bloquear", "cortafuegos.retirar"]


def test_regla_ajena_o_consulta_fallida_no_quedan_verificadas(tmp_path):
    exe = tmp_path / "server.exe"
    exe.write_bytes(b"MZ")
    result = cortafuegos.estado(exe, sistema="windows",
                                run=lambda *a: _result('{"existe":true,"enabled":"False"}'))
    assert result["estado"] == "NO VERIFICADO" and not result["verificada"]
    result = cortafuegos.estado(exe, sistema="windows", run=lambda *a: _result(stderr="denegado", code=1))
    assert result["estado"] == "NO VERIFICADO" and "denegado" in result["motivo"]
    with pytest.raises(cortafuegos.CortafuegosError, match="implementada para Windows"):
        cortafuegos.cambiar(exe, aplicar=True, sistema="linux")
