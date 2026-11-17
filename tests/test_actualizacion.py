"""C2: «eolfi update --check» con red simulada."""
from __future__ import annotations

import json

import pytest

from eolfi import __version__
from eolfi import actualizacion as A


def _fetch(respuestas: dict[str, object]):
    vistas: list[str] = []

    def fetch(url: str) -> bytes:
        vistas.append(url)
        for clave, valor in respuestas.items():
            if url.endswith(clave):
                if isinstance(valor, Exception):
                    raise valor
                return json.dumps(valor).encode()
        raise A.NoEncontrado(url)
    return fetch, vistas


def _siguiente(version: str) -> str:
    a, b, c, *_ = A.parsear(version)
    return f"v{a}.{b + 1}.0"


def test_parsear_y_comparar():
    assert A.parsear("v0.9.1")[:3] == (0, 9, 1)
    assert A.parsear("1.0") [:3] == (1, 0, 0)
    assert A.parsear("main") is None and A.parsear("") is None
    assert A.comparar("0.10.0", "0.9.9") == 1
    assert A.comparar("1.0.0rc1", "1.0.0") == -1
    assert A.comparar("v0.8.0", "0.8.0") == 0
    assert A.comparar("x", "0.8.0") is None


def test_sin_red_no_conecta(monkeypatch):
    monkeypatch.delenv("EOLAS_OFFLINE", raising=False)
    fetch, vistas = _fetch({})
    res = A.comprobar(fetch=fetch)
    assert res["estado"] == "NO VERIFICADO" and vistas == []
    assert res["instalada"]["version"] == __version__ and res["instala_nada"] is True


def test_offline_rechaza_aunque_haya_red(monkeypatch):
    monkeypatch.setenv("EOLAS_OFFLINE", "1")
    fetch, vistas = _fetch({})
    res = A.comprobar(red=True, fetch=fetch)
    assert res["estado"] == "NO VERIFICADO" and "EOLAS_OFFLINE" in res["motivo"] and vistas == []


def test_nueva_version_por_publicacion(monkeypatch):
    monkeypatch.delenv("EOLAS_OFFLINE", raising=False)
    nueva = _siguiente(__version__)
    fetch, vistas = _fetch({"/releases/latest": {"tag_name": nueva, "html_url": "https://github.com/x/y/r",
                                                 "published_at": "2026-11-17T00:00:00Z", "body": "ignorar"}})
    res = A.comprobar(red=True, fetch=fetch)
    assert res["estado"] == "nueva_version" and res["publicada"]["version"] == nueva
    assert res["publicada"]["origen"] == "publicacion" and "body" not in res["publicada"]
    assert res["como_actualizar"]
    assert vistas == ["https://api.github.com/repos/CeltiaIA/Eolfi/releases/latest"]


def test_sin_publicacion_usa_la_mayor_etiqueta(monkeypatch):
    monkeypatch.delenv("EOLAS_OFFLINE", raising=False)
    fetch, _ = _fetch({"/tags?per_page=100": [{"name": "v0.1.0"}, {"name": "experimento"}, {"name": f"v{__version__}"},
                                              {"name": "v0.0.9"}]})
    res = A.comprobar(red=True, fetch=fetch)
    assert res["estado"] == "al_dia" and res["publicada"]["origen"] == "etiqueta"


def test_sin_publicaciones_ni_etiquetas(monkeypatch):
    monkeypatch.delenv("EOLAS_OFFLINE", raising=False)
    fetch, _ = _fetch({"/tags?per_page=100": []})
    assert A.comprobar(red=True, fetch=fetch)["estado"] == "sin_publicaciones"


def test_fallo_de_red_es_no_verificado(monkeypatch):
    monkeypatch.delenv("EOLAS_OFFLINE", raising=False)
    fetch, _ = _fetch({"/releases/latest": OSError("sin conexión")})
    res = A.comprobar(red=True, fetch=fetch)
    assert res["estado"] == "NO VERIFICADO" and "sin conexión" in res["motivo"]


def test_repo_invalido():
    with pytest.raises(A.ActualizacionError):
        A.comprobar(repo="../../evil")


def test_solo_api_github_https():
    assert A._host_permitido("https://api.github.com/repos/a/b")
    assert not A._host_permitido("http://api.github.com/repos/a/b")
    assert not A._host_permitido("https://api.github.com.evil.example/")
    assert not A._host_permitido("https://objects.githubusercontent.com/x")
    with pytest.raises(A.ActualizacionError):
        A._fetch_red("https://evil.example/")


def test_modo_instalacion(tmp_path):
    assert A.modo_instalacion(frozen=True) == "ejecutable"
    assert A.modo_instalacion(frozen=False, raiz=tmp_path,
                              prefix="C:\\Users\\x\\pipx\\venvs\\eolfi") == "pipx"
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    assert A.modo_instalacion(frozen=False, raiz=tmp_path) == "copia_repositorio"
    assert "pipx upgrade" in A.instrucciones("pipx")


def test_cli_update_check_sin_red(capsys, monkeypatch):
    from eolfi.cli import main

    monkeypatch.delenv("EOLAS_OFFLINE", raising=False)
    assert main(["update", "--check"]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["estado"] == "NO VERIFICADO" and out["instalada"]["version"] == __version__
    assert out["instalada"]["modo"] == "copia_repositorio"
