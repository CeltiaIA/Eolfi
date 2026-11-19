from pathlib import Path


def test_inventario_e4_no_instala_y_declara_alternativas(tmp_path, monkeypatch):
    from eolfi import herramientas_rea

    cutter = tmp_path / "Cutter.exe"
    rizin = tmp_path / "rizin.exe"
    cutter.touch()
    rizin.touch()
    monkeypatch.setattr(herramientas_rea, "_npcap_registry", lambda: False)
    monkeypatch.setattr(herramientas_rea, "_first_existing", lambda paths: str(cutter) if any("Cutter" in str(p) for p in paths) else None)
    monkeypatch.setattr(herramientas_rea.shutil, "which", lambda name: str(rizin) if name == "rizin" else None)
    result = herramientas_rea.inventory(sigrok_probe=lambda: ["wsl.exe", "env", "REA_SIGROK_COMMAND=/x"])
    assert result["estado"] == "inventariado" and result["solo_lectura"] is True
    assert result["npcap"]["disponible"] is False
    assert result["sigrok"]["disponible"] is True
    assert result["cutter"]["ruta"] == str(cutter)
    assert result["cutter"]["alternativa_rizin"] == str(rizin.resolve())
    assert result["sigrok"]["instalador"].endswith("tools\\instalar-sigrok-wsl.sh")
    assert [p["herramienta"] for p in result["pendientes"]] == ["Npcap"]
    assert result["cambios"] == []


def test_inventario_e4_separa_ausente_de_no_accesible(tmp_path, monkeypatch):
    from eolfi import herramientas_rea

    monkeypatch.setattr(herramientas_rea, "_npcap_registry", lambda: False)
    monkeypatch.setattr(herramientas_rea, "_first_existing", lambda paths: None)
    monkeypatch.setattr(herramientas_rea.shutil, "which", lambda name: None)
    result = herramientas_rea.inventory(sigrok_probe=lambda: None)
    assert result["sigrok"]["disponible"] is False
    assert "no demuestra que falte" in result["sigrok"]["nota"]
    assert [p["herramienta"] for p in result["pendientes"]] == ["Npcap", "sigrok", "Cutter"]
    sigrok = next(p for p in result["pendientes"] if p["herramienta"] == "sigrok")
    assert sigrok["comando"].endswith("/tools/instalar-sigrok-wsl.sh") and "\\" not in sigrok["comando"]
    assert result["cambios"] == []


def test_cli_herramientas_rea(tmp_path, monkeypatch, capsys):
    from eolfi import herramientas_rea
    from eolfi.cli import main

    monkeypatch.setattr(herramientas_rea, "inventory", lambda: {"estado": "inventariado", "cambios": []})
    assert main(["--db", str(tmp_path / "eolfi.db"), "rea", "herramientas"]) == 0
    assert '"estado": "inventariado"' in capsys.readouterr().out
    assert not Path(tmp_path / "eolfi.db").exists()
