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


def test_el_tiempo_agotado_mata_la_suite_y_sus_descendientes(tmp_path):
    """15/11/2026: con un nieto que hereda las tuberías (como npm → node), el límite solo mataba al hijo y la
    guardia esperaba para siempre. Ahora termina, informa del fallo y no deja el nieto vivo."""
    import subprocess
    import sys
    import time

    pidfile = tmp_path / "nieto.pid"
    nieto = "import time; time.sleep(600)"
    hijo = (f"import subprocess, sys, time; p = subprocess.Popen([sys.executable, '-c', {nieto!r}]); "
            f"open({str(pidfile)!r}, 'w').write(str(p.pid)); time.sleep(600)")
    start = time.monotonic()
    ok, info = vs.run("colgada", [sys.executable, "-c", hijo], tmp_path, timeout=5)
    assert not ok and "sin terminar" in info
    assert time.monotonic() - start < 60
    pid = int(pidfile.read_text())
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        assert str(pid) not in out
    else:
        import os

        for _ in range(50):
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.1)
        else:
            raise AssertionError("el nieto sigue vivo")


def test_suite_npm_sin_node_modules_falla_con_motivo(tmp_path, monkeypatch):
    suite = tmp_path / "e2e"
    suite.mkdir()
    (suite / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(vs, "ROOT", tmp_path)
    ok, info = vs.run("navegador (e2e)", ["npm", "test"], suite)
    assert not ok and "faltan dependencias" in info and "npm ci" in info


def test_una_suite_que_falla_guarda_su_salida_completa(tmp_path, monkeypatch):
    """20/11/2026: un fallo intermitente solo dejó «AssertionEr...» en la guardia; ahora queda la salida entera."""
    import sys

    monkeypatch.setattr(vs.tempfile, "gettempdir", lambda: str(tmp_path / "temporal"))
    (tmp_path / "temporal").mkdir()
    code = "import sys; print('detalle completo de la asercion ' * 30); sys.exit(1)"
    ok, info = vs.run("pytest", [sys.executable, "-c", code], tmp_path)
    assert not ok and "salida completa:" in info
    saved = Path(info.split("salida completa: ", 1)[1])
    assert saved.parent == tmp_path / "temporal"
    assert saved.read_text(encoding="utf-8").count("detalle completo de la asercion") == 30
    ok, info = vs.run("pytest", [sys.executable, "-c", "print('bien')"], tmp_path)
    assert ok and "salida completa" not in info
