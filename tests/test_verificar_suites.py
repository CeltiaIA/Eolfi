"""Guardia de suites (14/11/2026): nada con fallos sin arreglar pasa el pre-push."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verificar_suites", ROOT / "tools" / "verificar_suites.py")
vs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vs)


def test_falla_si_alguna_suite_falla_o_no_se_ejecuta(monkeypatch, capsys):
    results = {"pytest": (True, "ok"), "puente": (False, "1 failed"), "puente VS Code": (True, "ok"),
               "navegador (e2e)": (False, "no se pudo ejecutar: falta npm")}
    monkeypatch.setattr(vs, "run", lambda name, argv, cwd: results[name])
    assert vs.main([]) == 1
    out = capsys.readouterr().out
    assert "no pasa" in out and "puente," in out and "navegador (e2e)" in out


def test_pasa_solo_con_todo_en_verde(monkeypatch):
    monkeypatch.setattr(vs, "run", lambda name, argv, cwd: (True, "ok"))
    assert vs.main([]) == 0
    seen = []
    monkeypatch.setattr(vs, "run", lambda name, argv, cwd: seen.append(name) or (True, "ok"))
    assert vs.main(["--sin-e2e"]) == 0 and "navegador (e2e)" not in seen


def test_el_gancho_pre_push_usa_el_guardia():
    hook = (ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
    assert "tools/verificar_suites.py" in hook and "--sin-e2e" not in hook   # el gancho exige las cuatro


def test_no_se_cae_con_caracteres_que_la_consola_no_admite(monkeypatch):
    """13/11/2026: el «ℹ» de `node --test` en una consola cp1252 tiraba la guardia con UnicodeEncodeError."""
    import io
    import sys

    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", console)
    monkeypatch.setattr(vs, "run", lambda name, argv, cwd: (True, "ℹ tests 53 · ✔ ok"))
    assert vs.main([]) == 0
    console.flush()
    assert "GUARDIA: las suites" in raw.getvalue().decode("utf-8")


def test_las_suites_no_heredan_las_variables_git_del_gancho(monkeypatch, tmp_path):
    """13/11/2026: dentro del pre-push, GIT_DIR apuntaba al repositorio de Eolfi y una prueba que hace «git init» y
    «update-ref HEAD» sobre un repositorio temporal escribió en el de verdad (bare = true y commits en las ramas)."""
    import sys

    monkeypatch.setenv("GIT_DIR", str(tmp_path / "no-tocar.git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "index"))
    monkeypatch.setenv("EOLFI_OTRA", "se conserva")
    env = vs.clean_env()
    assert not any(k.upper().startswith("GIT_") for k in env) and env["EOLFI_OTRA"] == "se conserva"
    ok, info = vs.run("eco", [sys.executable, "-c", "import os; print(os.environ.get('GIT_DIR', 'sin GIT_DIR'))"], tmp_path)
    assert ok and "sin GIT_DIR" in info
