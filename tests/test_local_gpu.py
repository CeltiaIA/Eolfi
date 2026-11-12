"""Un solo modelo local en la GPU (eolfi/local_gpu.py).

Reproduce lo visto el 11-12/11/2026: Eolas V2 (Mistral-Nemo en el 8090) olvidado mientras Eolas cargaba Gemma al
recibir una petición; con 8 GB de VRAM, «bad allocation» y un agente casi parado. Sin GPU ni modelos reales:
servidores HTTP simulados en loopback.
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from eolfi import eolas_v2, local_gpu


class _Eolas(BaseHTTPRequestHandler):
    loaded: list = []
    unloads: list = []

    def log_message(self, *a):
        pass

    def _send(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/ps":
            self._send({"models": [{"name": n, "model": n} for n in _Eolas.loaded]})
        elif self.path == "/api/tags":            # el catálogo: siempre lleno, haya algo cargado o no
            self._send({"models": [{"name": "gemma-4-12b-it:latest"}, {"name": "mistral-7b:latest"}]})
        elif self.path == "/slots":
            self._send(_Eolas.slots)
        else:
            self.send_error(404)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/generate" and req.get("keep_alive") == 0:
            _Eolas.unloads.append(req["model"])
            _Eolas.loaded = [m for m in _Eolas.loaded if m != req["model"]]
        self._send({"done": True})


@pytest.fixture
def server():
    _Eolas.loaded, _Eolas.unloads, _Eolas.slots = [], [], [{"id": 0, "id_task": 1, "is_processing": False}]
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Eolas)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", srv.server_address[1]
    srv.shutdown()


@pytest.fixture
def v2(tmp_path, monkeypatch, server):
    """Un «Eolas V2» vivo: el runtime apunta a este proceso (vivo) y al servidor simulado como llama-server."""
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(tmp_path / "eolas-v2.json"))
    eolas_v2.runtime_file().write_text(json.dumps({"pid": os.getpid(), "profile": "nemo_q4", "port": server[1]}),
                                       encoding="utf-8")
    stops = []
    monkeypatch.setattr(eolas_v2, "stop", lambda: stops.append(1) or eolas_v2.runtime_file().unlink() or {"stopped": True})
    return stops


def test_lo_cargado_no_es_el_catalogo_y_se_puede_liberar(server):
    url = server[0]
    assert local_gpu.eolas_loaded(url) == []                       # catálogo lleno, nada cargado
    assert local_gpu.check_before_eolas_v2(url=url)["eolas_loaded"] == []
    _Eolas.loaded = ["gemma-4-12b-it:latest"]
    with pytest.raises(local_gpu.GpuBusy, match="--liberar-eolas"):
        local_gpu.check_before_eolas_v2(url=url)
    r = local_gpu.check_before_eolas_v2(release=True, url=url)
    assert r["released"] == ["gemma-4-12b-it:latest"] and _Eolas.unloads == ["gemma-4-12b-it:latest"]
    assert local_gpu.eolas_loaded(url) == []
    assert local_gpu.eolas_loaded("http://127.0.0.1:9") == []      # Eolas parado: nada cargado


def test_eolas_v2_no_arranca_con_el_modelo_de_eolas_cargado(tmp_path, monkeypatch):
    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(tmp_path / "eolas-v2.json"))
    (tmp_path / "gemma.gguf").touch()
    cfg = {**eolas_v2.DEFAULT_CONFIG, "server": "X:/llama-server.exe", "profiles": {
        **eolas_v2.DEFAULT_PROFILES, "gemma": {**eolas_v2.DEFAULT_PROFILES["gemma"], "model": str(tmp_path / "gemma.gguf")}}}
    monkeypatch.setattr(eolas_v2, "_healthy", lambda *a, **k: False)
    loaded = ["gemma-4-12b-it:latest"]
    monkeypatch.setattr(local_gpu, "eolas_loaded", lambda url=None: list(loaded))
    released = []
    monkeypatch.setattr(local_gpu, "release_eolas", lambda url=None: released.append(1) or loaded.clear() or ["x"])
    with pytest.raises(RuntimeError, match="tiene cargado en la GPU.*--liberar-eolas"):
        eolas_v2._start_locked("gemma", cfg, popen=lambda *a, **k: pytest.fail("no debe lanzar llama-server"))
    assert released == []
    # Con --liberar-eolas primero se descarga Eolas; después ya no hay bloqueo (falla más tarde: no hay llama-server).
    with pytest.raises(Exception) as exc:
        eolas_v2._start_locked("gemma", cfg, release_eolas=True,
                               popen=lambda *a, **k: (_ for _ in ()).throw(OSError("lanzado")))
    assert released == [1] and "tiene cargado en la GPU" not in str(exc.value)   # pasó la guardia


def test_antes_de_pedir_a_eolas_se_para_eolas_v2_ocioso_y_no_el_ocupado(v2, server):
    assert local_gpu.free_for_eolas()["stopped_eolas_v2"]["profile"] == "nemo_q4"
    assert v2 == [1] and local_gpu.eolas_v2_holder() is None
    eolas_v2.runtime_file().write_text(json.dumps({"pid": os.getpid(), "profile": "nemo_q4", "port": server[1]}),
                                       encoding="utf-8")
    _Eolas.slots = [{"id": 0, "id_task": 9, "is_processing": True}]
    with pytest.raises(local_gpu.GpuBusy, match="está generando"):
        local_gpu.free_for_eolas()
    assert v2 == [1]                                                  # no se interrumpe una generación


def test_proveedor_eolas_aplica_la_guardia_solo_en_local(monkeypatch):
    from eolfi.generador import llm

    calls = []
    monkeypatch.setattr(local_gpu, "free_for_eolas", lambda: calls.append(1) or (_ for _ in ()).throw(
        local_gpu.GpuBusy("Eolas V2 está generando")))
    monkeypatch.setattr(llm, "_post", lambda *a, **k: pytest.fail("no debe llegar a Eolas"))
    with pytest.raises(llm.LLMError, match="Eolas V2 está generando"):
        llm.OllamaProvider("http://127.0.0.1:11435", "gemma").complete("s", [{"role": "user", "content": "x"}], {}, None)
    monkeypatch.setattr(llm, "_post", lambda *a, **k: {"message": {"content": "{\"ok\": 1}"}})
    llm.OllamaProvider("http://eolas.remota:11435", "gemma").complete("s", [{"role": "user", "content": "x"}], {}, None)
    assert calls == [1]                                               # un Eolas remoto no toca la GPU local


def test_vigilante_para_tras_inactividad_y_cuenta_peticiones_cortas(v2, server):
    now = [0.0]

    def tick(_):
        now[0] += 60
        _Eolas.slots = [{"id": 0, "id_task": tasks.pop(0) if tasks else 7, "is_processing": False}]

    tasks = [2, 3, 4]                     # tres peticiones cortas, nunca vistas «en curso»
    r = local_gpu.watch(os.getpid(), server[1], idle_minutes=2, clock=lambda: now[0], sleep=tick)
    assert r.startswith("parado tras 2") and v2 == [1]
    assert now[0] >= 5 * 60                # las peticiones cortas reiniciaron la cuenta
    assert local_gpu.watch(os.getpid(), server[1], 2, clock=lambda: 0, sleep=lambda _: None) == "servidor terminado"


def test_eolfi_llama_start_retirado(capsys):
    from eolfi import cli

    assert cli.main(["llama", "start"]) != 0
    assert "retirado" in capsys.readouterr().err
