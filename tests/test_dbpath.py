"""Ruta por defecto de la base de evidencias y copia de la base antigua (LIM-013)."""
import json
import sqlite3

import pytest

from eolfi.core.dbpath import MIGRATED, resolve_db


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.delenv("EOLFI_DB", raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("EOLFI_HOME", str(home))
    work = tmp_path / "proyecto"
    work.mkdir()
    logs = []
    return home, work, logs.append, logs


def _db(path, rows):
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE IF NOT EXISTS t (x TEXT)")
    con.executemany("INSERT INTO t VALUES (?)", [(r,) for r in rows])
    con.commit()
    return con          # abierta: el WAL sigue con datos sin volcar


def test_explicit_and_env_win(entorno, monkeypatch):
    home, work, log, logs = entorno
    assert resolve_db("otra.db", cwd=work, log=log) == "otra.db"
    monkeypatch.setenv("EOLFI_DB", "/x/y.db")
    assert resolve_db(None, cwd=work, log=log) == "/x/y.db"
    assert logs == [] and not home.exists()


def test_default_is_data_home_without_legacy(entorno):
    home, work, log, logs = entorno
    assert resolve_db(None, cwd=work, log=log) == str(home / "eolfi.db")
    assert home.is_dir() and logs == []


def test_legacy_is_copied_once_with_wal_and_kept(entorno):
    home, work, log, logs = entorno
    legacy = work / "eolfi.db"
    con = _db(legacy, ["a", "b"])
    try:
        before = legacy.read_bytes()
        path = resolve_db(None, cwd=work, log=log)
        assert path == str(home / "eolfi.db")
        copied = sqlite3.connect(path)
        assert [r[0] for r in copied.execute("SELECT x FROM t ORDER BY x")] == ["a", "b"]
        copied.close()
        assert legacy.read_bytes() == before                     # la original no se toca
        assert len(logs) == 1 and "se conserva" in logs[0]
        assert json.loads((home / MIGRATED).read_text(encoding="utf-8"))["from"] == [str(legacy.resolve())]
        assert resolve_db(None, cwd=work, log=log) == path and len(logs) == 1   # sin avisos repetidos
    finally:
        con.close()


def test_other_folder_db_is_not_used_but_warned(entorno):
    home, work, log, logs = entorno
    resolve_db(None, cwd=work, log=log)                 # crea la carpeta de datos
    _db(home / "eolfi.db", ["home"]).close()
    other = work / "eolfi.db"
    _db(other, ["otra"]).close()
    assert resolve_db(None, cwd=work, log=log) == str(home / "eolfi.db")
    assert len(logs) == 1 and "no se usa" in logs[0] and str(other) in logs[0]


def test_failed_copy_keeps_using_legacy(entorno, monkeypatch):
    import eolfi.core.dbpath as dbpath

    home, work, log, logs = entorno
    _db(work / "eolfi.db", ["a"]).close()
    monkeypatch.setattr(dbpath, "_copy", lambda s, d: (_ for _ in ()).throw(OSError("disco lleno")))
    assert resolve_db(None, cwd=work, log=log) == str(work / "eolfi.db")
    assert "no se pudo copiar" in logs[0] and not (home / "eolfi.db").exists()


def test_cli_uses_resolved_default(entorno, monkeypatch, capsys):
    from eolfi.cli import main

    home, work, log, logs = entorno
    monkeypatch.chdir(work)
    assert main(["case", "create", "x"]) == 0
    assert (home / "eolfi.db").is_file() and not (work / "eolfi.db").exists()
