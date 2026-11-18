"""E3 (18/11/2026): paquete completo de evidencias de REA junto al caso (`eolfi rea ... --paquete CARPETA`)."""
import hashlib
import json
from pathlib import Path

import pytest

from eolfi import rea_paquete
from eolfi.core.cases import CaseStore
from eolfi.core.evidence import EvidenceStore

BUNDLE = {"artifacts": [{"sha256": "a" * 64}], "captures": [], "environments": [], "providers": [],
          "records": [{"id": 1}, {"id": 2}], "scenarios": [], "unknowns": [{"id": "u1"}]}


class FakeRea:
    """REA falso: export_evidence_bundle escribe su paquete como lo hace REA (falla si el archivo ya existe y no se
    permite sobrescribir)."""
    llamadas: list = []

    def __init__(self, *a, **k):
        pass

    def call(self, name, args):
        FakeRea.llamadas.append((name, args))
        assert name == "export_evidence_bundle"
        ruta = Path(args["path"])
        if ruta.exists() and not args.get("overwrite"):
            return "destination exists", False
        ruta.write_text(json.dumps(BUNDLE, separators=(",", ":")), encoding="utf-8")
        return json.dumps({"normalized_result": {"result": {"path": str(ruta), "records": 2, "unknowns": 1}}}), True

    def close(self):
        pass


@pytest.fixture
def cli_rea(monkeypatch, tmp_path):
    from eolfi import cli, rea_client, rea_compuestas

    FakeRea.llamadas = []
    monkeypatch.setattr(rea_client, "ReaClient", FakeRea)
    monkeypatch.setattr(rea_compuestas, "inventario_dependencias",
                        lambda client, ruta: {"archivo": ruta, "sha256": "b" * 64, "librerias": ["libc"]})
    db = str(tmp_path / "e.db")
    s = EvidenceStore(db)
    case = CaseStore(s).create("Paquete REA", "")["case_id"]
    s.close()
    return cli, db, case


def test_paquete_completo_con_caso(cli_rea, tmp_path, capsys):
    cli, db, case = cli_rea
    carpeta = tmp_path / "paquete"
    rc = cli.main(["--db", db, "rea", "--caso", case, "--paquete", str(carpeta), "inventario", str(tmp_path / "a.exe")])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["paquete"]["carpeta"] == str(carpeta.resolve())
    assert FakeRea.llamadas[-1][1]["overwrite"] is False                      # REA nunca pisa nada
    # El paquete de REA queda tal cual lo escribió REA, sin reescribirlo.
    assert (carpeta / "rea-evidencias.json").read_text(encoding="utf-8") == json.dumps(BUNDLE, separators=(",", ":"))
    m = json.loads((carpeta / "manifiesto.json").read_text(encoding="utf-8"))
    assert m["formato"] == "eolfi-paquete-rea" and m["operacion"] == "inventario_dependencias" and m["caso"] == case
    assert m["rea"]["recuentos"]["records"] == 2 and m["rea"]["recuentos"]["unknowns"] == 1
    assert m["rea"]["version"] and m["plataforma"]["sistema"] and m["pendiente"] == []
    assert any("import_evidence_bundle" in l for l in m["limites"])
    assert {a["ruta"] for a in m["archivos"]} == {"rea-evidencias.json", "resultado.json", "caso.json"}
    for a in m["archivos"]:
        assert hashlib.sha256((carpeta / a["ruta"]).read_bytes()).hexdigest() == a["sha256"]
    # El caso exportado ya lleva el análisis registrado y se puede importar en otra base.
    caso = json.loads((carpeta / "caso.json").read_text(encoding="utf-8"))
    assert caso["case"]["case_id"] == case and len(caso["evidence_package"]["evidence"]) == 1
    otra = EvidenceStore(str(tmp_path / "otra.db"))
    try:
        assert CaseStore(otra).import_case(carpeta / "caso.json") is True
    finally:
        otra.close()
    resultado = json.loads((carpeta / "resultado.json").read_text(encoding="utf-8"))
    assert resultado["resultado"]["librerias"] == ["libc"] and resultado["resultado"]["caso"]["caso"] == case
    # La comprobación de integridad: verde, y en rojo si un archivo cambia.
    assert cli.main(["rea", "comprobar-paquete", str(carpeta)]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    (carpeta / "resultado.json").write_text("{}", encoding="utf-8")
    assert cli.main(["rea", "comprobar-paquete", str(carpeta)]) == 1
    assert json.loads(capsys.readouterr().out)["distintos"] == ["resultado.json"]


def test_sin_caso_no_hay_caso_json(cli_rea, tmp_path, capsys):
    cli, db, _case = cli_rea
    carpeta = tmp_path / "solo"
    assert cli.main(["--db", db, "rea", "--paquete", str(carpeta), "inventario", str(tmp_path / "a.exe")]) == 0
    capsys.readouterr()
    assert sorted(p.name for p in carpeta.iterdir()) == ["manifiesto.json", "rea-evidencias.json", "resultado.json"]


def test_una_carpeta_ocupada_se_rechaza_antes_de_arrancar_rea(tmp_path, monkeypatch, capsys):
    from eolfi import cli, rea_client

    monkeypatch.setattr(rea_client, "ReaClient", lambda *a, **k: pytest.fail("no debía arrancar REA"))
    ocupada = tmp_path / "ocupada"
    ocupada.mkdir()
    (ocupada / "previo.txt").write_text("no tocar", encoding="utf-8")
    rc = cli.main(["--db", str(tmp_path / "x.db"), "rea", "--paquete", str(ocupada), "inventario", "a.exe"])
    assert rc == 2 and "no está vacía" in capsys.readouterr().err
    assert [p.name for p in ocupada.iterdir()] == ["previo.txt"]


def test_si_rea_no_exporta_queda_pendiente(cli_rea, tmp_path, capsys, monkeypatch):
    cli, db, _case = cli_rea
    monkeypatch.setattr(FakeRea, "call", lambda self, name, args: ("sin sesión", False))
    carpeta = tmp_path / "p"
    assert cli.main(["--db", db, "rea", "--paquete", str(carpeta), "inventario", str(tmp_path / "a.exe")]) == 0
    capsys.readouterr()
    m = json.loads((carpeta / "manifiesto.json").read_text(encoding="utf-8"))
    assert m["pendiente"] == ["paquete de REA no exportado"] and "error" in m["rea"]["respuesta_exportacion"]
    assert [a["ruta"] for a in m["archivos"]] == ["resultado.json"]


def test_si_falla_el_analisis_no_queda_carpeta(cli_rea, tmp_path, capsys, monkeypatch):
    from eolfi import rea_compuestas

    cli, db, _case = cli_rea
    monkeypatch.setattr(rea_compuestas, "inventario_dependencias",
                        lambda client, ruta: (_ for _ in ()).throw(RuntimeError("REA caído")))
    carpeta = tmp_path / "p"
    assert cli.main(["--db", db, "rea", "--paquete", str(carpeta), "inventario", "a.exe"]) == 1
    assert not carpeta.exists()


def test_comprobar_detecta_faltantes_y_no_listados(tmp_path):
    carpeta = rea_paquete.preparar(tmp_path / "q")
    (carpeta / rea_paquete.REA).write_text("{}", encoding="utf-8")
    rea_paquete.cerrar(carpeta, operacion="x", params={}, resultado={}, rea_version="0", respuesta_rea=None)
    (carpeta / rea_paquete.REA).unlink()
    (carpeta / "intruso.txt").write_text("x", encoding="utf-8")
    r = rea_paquete.comprobar(carpeta)
    assert r["ok"] is False and r["faltan"] == ["rea-evidencias.json"] and r["no_listados"] == ["intruso.txt"]
    with pytest.raises(ValueError):
        rea_paquete.comprobar(tmp_path)                      # sin manifiesto de Eolfi
