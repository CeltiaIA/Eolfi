"""G5: comprobar versiones nuevas y descargar con permiso, sin red real."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from eolfi import acciones
from eolfi.modelos_actualizar import (
    ActualizarError,
    _host_permitido,
    comprobar,
    descargar,
    leer_fuentes,
)

COMMIT = "a" * 40


@pytest.fixture
def gguf(tmp_path) -> bytes:
    from tests.ggufgen import build_bf16

    path = tmp_path / "muestra.gguf"
    build_bf16(path)
    return path.read_bytes()


def _fuentes(tmp_path: Path, **extra) -> Path:
    entry = {"nombre": "gemma", "repo": "org/modelo-GGUF", "archivo": "modelo-Q4_K_M.gguf", "sha256": "1" * 64}
    entry.update(extra)
    path = tmp_path / "fuentes.json"
    path.write_text(json.dumps({"schema": "eolfi.modelos.fuentes/v1", "modelos": [entry]}), encoding="utf-8")
    return path


def _api(sha: str, *, commit: str = COMMIT, archivo: str = "modelo-Q4_K_M.gguf", size: int = 10):
    def fetch(url: str) -> bytes:
        assert url.startswith("https://huggingface.co/api/models/org/modelo-GGUF/revision/main")
        return json.dumps({"sha": commit, "lastModified": "2026-11-01T00:00:00.000Z",
                           "siblings": [{"rfilename": archivo, "size": size,
                                         "lfs": {"sha256": sha, "size": size}}]}).encode()
    return fetch


def test_sin_red_no_conecta(tmp_path):
    def nunca(url):
        raise AssertionError("no debía conectar")

    with pytest.raises(ActualizarError, match="--red"):
        comprobar(_fuentes(tmp_path), fetch=nunca)


def test_modo_offline_rechaza_aunque_se_pida_red(tmp_path, monkeypatch):
    monkeypatch.setenv("EOLAS_OFFLINE", "1")
    with pytest.raises(ActualizarError, match="EOLAS_OFFLINE"):
        comprobar(_fuentes(tmp_path), red=True, fetch=_api("1" * 64))


def test_al_dia_y_version_nueva(tmp_path):
    al_dia = comprobar(_fuentes(tmp_path), red=True, fetch=_api("1" * 64))
    assert al_dia["estado"] == "al_dia" and al_dia["modelos"][0]["revision"] == COMMIT
    nueva = comprobar(_fuentes(tmp_path), red=True, fetch=_api("2" * 64))
    m = nueva["modelos"][0]
    assert nueva["estado"] == "nueva_version"
    assert m["descarga"] == {"repo": "org/modelo-GGUF", "archivo": "modelo-Q4_K_M.gguf", "revision": COMMIT,
                             "sha256": "2" * 64, "bytes": 10}


@pytest.mark.parametrize("fetch, motivo", [
    (lambda url: (_ for _ in ()).throw(OSError("sin conexión")), "OSError"),
    (_api("2" * 64, commit="main"), "commit"),
    (_api("2" * 64, archivo="otro.gguf"), "ya no está publicado"),
    (_api("no-es-hash"), "SHA-256 LFS"),
])
def test_respuestas_dudosas_son_no_verificado(tmp_path, fetch, motivo):
    res = comprobar(_fuentes(tmp_path), red=True, fetch=fetch)
    assert res["estado"] == "NO VERIFICADO" and motivo in res["modelos"][0]["error"]


def test_sin_sha_local_calcula_el_del_archivo_o_queda_no_verificado(tmp_path):
    local = tmp_path / "local.gguf"
    local.write_bytes(b"pesos")
    sha = hashlib.sha256(b"pesos").hexdigest()
    res = comprobar(_fuentes(tmp_path, sha256=None, local=str(local)), red=True, fetch=_api(sha))
    assert res["estado"] == "al_dia" and res["modelos"][0]["sha256_local_origen"] == "calculado"
    res = comprobar(_fuentes(tmp_path, sha256=None), red=True, fetch=_api(sha))
    assert res["estado"] == "NO VERIFICADO"


@pytest.mark.parametrize("cambio, error", [
    ({"repo": "sin-barra"}, "repo"), ({"archivo": "../fuera.gguf"}, "archivo"),
    ({"archivo": "modelo.bin"}, "archivo"), ({"sha256": "corto"}, "sha256"),
])
def test_fuentes_invalidas(tmp_path, cambio, error):
    with pytest.raises(ActualizarError, match=error):
        leer_fuentes(_fuentes(tmp_path, **cambio))


def test_solo_hosts_de_hugging_face():
    assert _host_permitido("https://huggingface.co/api/models/a/b")
    assert _host_permitido("https://cdn-lfs-us-1.hf.co/repos/x")
    assert _host_permitido("https://cas-bridge.xethub.hf.co/x")
    assert not _host_permitido("http://huggingface.co/x")
    assert not _host_permitido("https://huggingface.co.malo.example/x")
    assert not _host_permitido("https://example.com/x")


def _stream(data: bytes, partes: int = 3):
    def stream(url):
        assert url == f"https://huggingface.co/org/modelo-GGUF/resolve/{COMMIT}/modelo-Q4_K_M.gguf"
        step = max(1, len(data) // partes)
        for i in range(0, len(data), step):
            yield data[i:i + step]
    return stream


def test_descarga_correcta_audita_y_deja_recibo(tmp_path, gguf):
    sha = hashlib.sha256(gguf).hexdigest()
    out = tmp_path / "nuevo"
    res = descargar("org/modelo-GGUF", "modelo-Q4_K_M.gguf", COMMIT, sha, out, red=True,
                    bytes_esperados=len(gguf), stream=_stream(gguf))
    assert res["estado"] == "descargado", res
    assert Path(res["archivo_local"]).read_bytes() == gguf
    assert res["auditoria"]["estado"] in ("estructura_verificada", "NO VERIFICADO")
    assert res["verificacion"]["banco"] == "NO VERIFICADO"
    recibo = json.loads((out / "descarga.json").read_text(encoding="utf-8"))
    assert recibo["sha256_obtenido"] == sha and recibo["revision"] == COMMIT
    [e] = acciones.eventos()
    assert e["operacion"] == "modelos.descargar" and e["ok"] is True and e["params"]["sha256"] == sha


def test_hash_distinto_queda_rechazado_y_no_se_usa(tmp_path, gguf):
    out = tmp_path / "nuevo"
    res = descargar("org/modelo-GGUF", "modelo-Q4_K_M.gguf", COMMIT, "3" * 64, out, red=True,
                    stream=_stream(gguf))
    assert res["estado"] == "fallido" and "no coinciden" in res["error"]
    assert not (out / "modelo-Q4_K_M.gguf").exists()
    assert (out / "modelo-Q4_K_M.gguf.rechazado").read_bytes() == gguf
    assert acciones.eventos()[0]["ok"] is False


def test_mas_bytes_de_los_publicados_corta(tmp_path, gguf):
    res = descargar("org/modelo-GGUF", "modelo-Q4_K_M.gguf", COMMIT, hashlib.sha256(gguf).hexdigest(),
                    tmp_path / "n", red=True, bytes_esperados=len(gguf) - 1, stream=_stream(gguf))
    assert res["estado"] == "fallido" and "más bytes" in res["error"]
    assert not (tmp_path / "n" / "modelo-Q4_K_M.gguf").exists()


def test_nunca_sobrescribe(tmp_path, gguf):
    out = tmp_path / "n"
    out.mkdir()
    (out / "modelo-Q4_K_M.gguf").write_bytes(b"previo")
    with pytest.raises(ActualizarError, match="nunca sobrescribe"):
        descargar("org/modelo-GGUF", "modelo-Q4_K_M.gguf", COMMIT, "1" * 64, out, red=True, stream=_stream(gguf))
    assert (out / "modelo-Q4_K_M.gguf").read_bytes() == b"previo"


@pytest.mark.parametrize("args, error", [
    (("org/m", "modelo.gguf", "main", "1" * 64), "commit"),
    (("org/m", "modelo.gguf", COMMIT, "corto"), "sha256"),
    (("org/m", "../modelo.gguf", COMMIT, "1" * 64), "archivo"),
    (("malo", "modelo.gguf", COMMIT, "1" * 64), "repo"),
])
def test_descarga_exige_datos_revisados(tmp_path, args, error):
    with pytest.raises(ActualizarError, match=error):
        descargar(*args, tmp_path, red=True, stream=_stream(b"x"))


def test_descarga_sin_red_no_conecta(tmp_path):
    def nunca(url):
        raise AssertionError("no debía conectar")

    with pytest.raises(ActualizarError, match="--red"):
        descargar("org/m", "m.gguf", COMMIT, "1" * 64, tmp_path, stream=nunca)


def test_cli_actualizar_sin_red_falla_y_no_conecta(tmp_path, capsys):
    from eolfi.cli import main

    assert main(["modelos", "actualizar", "--fuentes", str(_fuentes(tmp_path))]) == 2
    assert "--red" in json.loads(capsys.readouterr().out)["error"]
