"""B8: registro encadenado de acciones que cambian estado."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from eolfi import acciones


def _lines(path: Path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_cadena_se_verifica_y_enlaza():
    a = acciones.anotar("prueba.uno", params={"x": 1})
    b = acciones.anotar("prueba.dos", resultado={"estado": "ok"})
    assert a["seq"] == 1 and a["prev"] == acciones.CERO
    assert b["seq"] == 2 and b["prev"] == a["sha256"]
    res = acciones.verificar()
    assert res == {"ok": True, "eventos": 2, "ultimo": b["sha256"], "archivo": str(acciones.registro_file())}


def test_sin_registro_es_cadena_vacia_valida():
    res = acciones.verificar()
    assert res["ok"] is True and res["eventos"] == 0


@pytest.mark.parametrize("dano", ["editar", "borrar", "reordenar", "basura"])
def test_cualquier_alteracion_rompe_la_cadena(dano):
    for i in range(3):
        acciones.anotar(f"prueba.{i}", params={"i": i})
    path = acciones.registro_file()
    lines = _lines(path)
    if dano == "editar":
        e = json.loads(lines[1])
        e["params"]["i"] = 99
        lines[1] = json.dumps(e, ensure_ascii=False)
    elif dano == "borrar":
        del lines[1]
    elif dano == "reordenar":
        lines[0], lines[1] = lines[1], lines[0]
    else:
        lines[2] = "{no es json"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = acciones.verificar()
    assert res["ok"] is False and res["roto_en"] in (1, 2, 3)


def test_desactivado_no_escribe(monkeypatch):
    monkeypatch.setenv("EOLFI_ACCIONES", "0")
    assert acciones.anotar("prueba") is None
    assert not acciones.registro_file().exists()


def test_valores_acotados_sin_textos_largos():
    e = acciones.anotar("prueba", params={"texto": "a" * 5000, "lista": list(range(100)),
                                          "anidado": {"a": {"b": {"c": {"d": 1}}}}, "ruta": Path("x") / "y"})
    p = e["params"]
    assert len(p["texto"]) <= acciones._MAX_TEXTO + 1
    assert len(p["lista"]) == 20
    assert p["anidado"]["a"]["b"] == "…"
    assert p["ruta"] == str(Path("x") / "y")


def test_decorador_registra_solo_lo_declarado_y_salta_vistas_previas():
    @acciones.registrada("prueba.aplicar", campos=("nombre",), resultado=("estado",),
                         si=lambda a: bool(a.get("apply")))
    def aplicar(nombre, secreto="no", *, apply=False):
        return {"estado": "aplicado" if apply else "vista", "interno": "x"}

    assert aplicar("p1")["estado"] == "vista"
    assert not acciones.registro_file().exists()
    aplicar("p2", "clave", apply=True)
    [e] = acciones.eventos()
    assert e["operacion"] == "prueba.aplicar" and e["ok"] is True
    assert e["params"] == {"nombre": "p2"}
    assert e["resultado"] == {"estado": "aplicado"}


def test_decorador_registra_fallos_y_relanza():
    @acciones.registrada("prueba.falla", campos=("n",))
    def falla(n):
        raise ValueError("no vale")

    with pytest.raises(ValueError, match="no vale"):
        falla(3)
    [e] = acciones.eventos()
    assert e["ok"] is False and "ValueError: no vale" in e["error"] and e["params"] == {"n": 3}


def test_resultado_fallido_se_marca_no_ok():
    @acciones.registrada("prueba.estado", resultado=("estado",))
    def f():
        return {"estado": "fallido"}

    f()
    assert acciones.eventos()[0]["ok"] is False


def test_error_al_escribir_no_deshace_la_accion(monkeypatch, capsys):
    def roto(*a, **k):
        raise OSError("disco lleno")

    monkeypatch.setattr(acciones, "anotar", roto)

    @acciones.registrada("prueba.disco")
    def f():
        return 7

    assert f() == 7
    assert "no se pudo registrar la acción prueba.disco" in capsys.readouterr().err


def test_funciones_que_cambian_estado_estan_registradas():
    from eolfi import eolas_v2, modelos_reconstruir

    esperadas = {
        eolas_v2.start: "eolas_v2.arrancar", eolas_v2.stop: "eolas_v2.parar", eolas_v2.switch: "eolas_v2.cambiar",
        eolas_v2.set_active_profile: "eolas_v2.perfil_activo", eolas_v2.retire_profile: "eolas_v2.retirar_perfil",
        eolas_v2.uninstall_profile: "eolas_v2.desinstalar_perfil",
        eolas_v2.restore_profile: "eolas_v2.restaurar_perfil",
        eolas_v2.remove_custom_profile: "eolas_v2.quitar_perfil",
        eolas_v2.apply_recommended_profile: "eolas_v2.recomendar_perfil",
        modelos_reconstruir.execute: "modelos.reconstruir", modelos_reconstruir.execute_smoke: "modelos.probar",
        modelos_reconstruir.adopt_profile: "eolas_v2.adoptar",
    }
    for fn, op in esperadas.items():
        assert getattr(fn, "__eolfi_accion__", None) == op, fn.__name__


def test_retirar_y_restaurar_perfil_reales_quedan_en_la_cadena():
    from eolfi import eolas_v2

    perfil = next(n for n in eolas_v2.load_config()["profiles"] if n != eolas_v2.load_config()["active_profile"])
    eolas_v2.retire_profile(perfil)
    eolas_v2.restore_profile(perfil)
    ops = [(e["operacion"], e["params"]) for e in acciones.eventos()]
    assert ops == [("eolas_v2.retirar_perfil", {"name": perfil}), ("eolas_v2.restaurar_perfil", {"name": perfil})]
    assert acciones.verificar()["ok"] is True


def test_escrituras_concurrentes_de_varios_procesos_mantienen_la_cadena(tmp_path):
    codigo = ("import sys; from eolfi import acciones\n"
              "for i in range(15): acciones.anotar('prueba.proc', params={'p': sys.argv[1], 'i': i})\n")
    env = {**os.environ, "EOLFI_ACCIONES_FILE": str(acciones.registro_file()),
           "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    procs = [subprocess.Popen([sys.executable, "-c", codigo, str(n)], env=env) for n in range(4)]
    assert [p.wait(timeout=120) for p in procs] == [0, 0, 0, 0]
    res = acciones.verificar()
    assert res == {**res, "ok": True, "eventos": 60}


def test_cli_verificar_y_listar(capsys):
    from eolfi.cli import main

    acciones.anotar("prueba.cli")
    assert main(["acciones", "verificar"]) == 0
    assert json.loads(capsys.readouterr().out)["eventos"] == 1
    assert main(["acciones", "listar", "-n", "5"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["operacion"] == "prueba.cli"
    path = acciones.registro_file()
    path.write_text(path.read_text(encoding="utf-8").replace("prueba.cli", "otra"), encoding="utf-8")
    assert main(["acciones", "verificar"]) == 2


def test_huellas_guardan_hash_y_no_el_texto():
    @acciones.registrada("prueba.huella", huellas=("brief",))
    def f(brief):
        return {"ok": True}

    f("encargo secreto")
    e = acciones.eventos()[0]
    assert "encargo secreto" not in json.dumps(e, ensure_ascii=False)
    assert e["params"]["brief"] == acciones.huella("encargo secreto")
    assert e["params"]["brief"]["bytes"] == len(b"encargo secreto")


def test_resumen_calculado_y_ok_desde_resumen():
    @acciones.registrada("prueba.resumen", resultado=lambda r: {"ok": r["verification"]["ok"], "n": len(r["files"])})
    def f(ok):
        return {"verification": {"ok": ok}, "files": [1, 2, 3]}

    f(True)
    f(False)
    a, b = acciones.eventos()
    assert a["resultado"] == {"ok": True, "n": 3} and a["ok"] is True
    assert b["resultado"] == {"ok": False, "n": 3} and b["ok"] is False


def test_resumen_roto_no_oculta_la_accion():
    @acciones.registrada("prueba.resumen_roto", resultado=lambda r: r["no_existe"])
    def f():
        return {"x": 1}

    assert f() == {"x": 1}
    assert "KeyError" in acciones.eventos()[0]["resultado"]["resumen_error"]


def test_assist_y_create_estan_registrados():
    from eolfi.flows.create_flow import create_project
    from eolfi.generador.assist import assist

    assert assist.__eolfi_accion__ == "generador.assist"
    assert create_project.__eolfi_accion__ == "generador.create"


def test_assist_fallido_queda_en_la_cadena_sin_el_encargo(tmp_path):
    from eolfi.generador.assist import AssistError, assist

    with pytest.raises(AssistError):
        assist(tmp_path, "haz la lista de tareas privada", provider="eolas-v2")
    [e] = acciones.eventos()
    assert e["operacion"] == "generador.assist" and e["ok"] is False
    assert e["params"]["brief"] == acciones.huella("haz la lista de tareas privada")
    assert "tareas privada" not in json.dumps(e, ensure_ascii=False)
    assert "AssistError" in e["error"]


def test_anclas_detectan_reescritura_y_truncado(tmp_path):
    ancla = tmp_path / "fuera" / "anclas.jsonl"
    for i in range(3):
        acciones.anotar(f"prueba.{i}")
    a = acciones.anclar(ancla)
    assert a["seq"] == 3 and acciones.verificar_anclas(ancla)["ok"] is True
    acciones.anotar("prueba.posterior")
    assert acciones.verificar_anclas(ancla) == {**acciones.verificar_anclas(ancla), "ok": True, "anclas": 1}

    # Reescritura completa con una cadena nueva y válida: la cadena sola no lo ve, el ancla sí.
    path = acciones.registro_file()
    path.unlink()
    for i in range(4):
        acciones.anotar(f"falsa.{i}")
    assert acciones.verificar()["ok"] is True
    res = acciones.verificar_anclas(ancla)
    assert res["ok"] is False and res["ancla_rota"] == 1

    # Truncado por debajo del ancla.
    path.unlink()
    acciones.anotar("solo.uno")
    assert acciones.verificar_anclas(ancla)["ok"] is False


def test_anclar_rechaza_cadena_rota_vacia_o_el_propio_registro(tmp_path):
    with pytest.raises(ValueError, match="no hay eventos"):
        acciones.anclar(tmp_path / "a.jsonl")
    acciones.anotar("prueba")
    with pytest.raises(ValueError, match="propio registro"):
        acciones.anclar(acciones.registro_file())
    path = acciones.registro_file()
    path.write_text(path.read_text(encoding="utf-8").replace("prueba", "otra"), encoding="utf-8")
    with pytest.raises(ValueError, match="cadena rota"):
        acciones.anclar(tmp_path / "a.jsonl")
    assert not (tmp_path / "a.jsonl").exists()


def test_verificar_anclas_sin_archivo_o_ilegible(tmp_path):
    acciones.anotar("prueba")
    assert acciones.verificar_anclas(tmp_path / "no.jsonl")["ok"] is False
    malo = tmp_path / "malo.jsonl"
    malo.write_text("{roto\n", encoding="utf-8")
    assert "ilegible" in acciones.verificar_anclas(malo)["motivo"]


def test_cli_anclar_y_verificar_con_ancla(tmp_path, capsys):
    from eolfi.cli import main

    ancla = tmp_path / "anclas.jsonl"
    assert main(["acciones", "anclar", "--destino", str(ancla)]) == 2
    capsys.readouterr()
    acciones.anotar("prueba.cli")
    assert main(["acciones", "anclar", "--destino", str(ancla)]) == 0
    assert json.loads(capsys.readouterr().out)["seq"] == 1
    assert main(["acciones", "verificar", "--ancla", str(ancla)]) == 0
    capsys.readouterr()
    acciones.registro_file().unlink()
    acciones.anotar("otra")
    assert main(["acciones", "verificar", "--ancla", str(ancla)]) == 2


def test_separadores_unicode_no_rompen_la_cadena(tmp_path, monkeypatch):
    """U+2028 y U+0085 van sin escapar en el JSON; str.splitlines los trataría como fin de línea."""
    from eolfi import acciones

    monkeypatch.setenv("EOLFI_ACCIONES_FILE", str(tmp_path / "a.jsonl"))
    acciones.anotar("x", params={"nota": "a" + chr(0x2028) + "b" + chr(0x85) + "c"})
    acciones.anotar("y")
    assert acciones.verificar()["ok"] is True and len(acciones.eventos()) == 2
