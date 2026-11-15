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
    key: str | None = None     # como llama-server con --api-key-file: /slots exige «Authorization: Bearer»

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
            if _Eolas.key and self.headers.get("Authorization") != f"Bearer {_Eolas.key}":
                self.send_error(401, "Invalid API Key")
                return
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
    _Eolas.key = None
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
    _Eolas.key = eolas_v2.api_key()           # el servidor real exige la clave en /slots
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


# ---------------------------------------------------------------- regresiones de la auditoría del 15/11/2026
def test_slots_se_pide_con_clave(v2, server):
    """P0-2: sin la clave, /slots daba 401, todo parecía ocioso y el vigilante cortaba conversaciones."""
    _Eolas.slots = [{"id": 0, "id_task": 5, "is_processing": True}]
    holder = local_gpu.eolas_v2_holder()
    assert holder["slots_known"] and holder["busy"] and holder["tasks"] == (5,)


def test_sin_ver_slots_no_se_para_a_ciegas(v2, server, monkeypatch):
    monkeypatch.setattr(eolas_v2, "auth_headers", lambda: {"Authorization": "Bearer otra"})   # clave que no vale
    holder = local_gpu.eolas_v2_holder()
    assert holder is not None and not holder["slots_known"] and not holder["busy"]
    with pytest.raises(local_gpu.GpuBusy, match="no lo paro a ciegas"):
        local_gpu.free_for_eolas()
    now = [0.0]

    def tick(_):
        now[0] += 60
        if now[0] >= 30 * 60:                 # el servidor termina por su cuenta a los 30 min
            eolas_v2.runtime_file().unlink()

    assert local_gpu.watch(os.getpid(), server[1], idle_minutes=2, clock=lambda: now[0], sleep=tick)         == "servidor terminado"
    assert v2 == []                           # en 30 min sin ver /slots, el vigilante no lo paró


def test_vigilante_sale_del_job_object_como_el_servidor(monkeypatch):
    """P0-3: el vigilante debe sobrevivir a la terminal o sesión que lo lanzó (Job con kill-on-close)."""
    calls = []

    class Proc:
        pid = 4321

    def popen(args, **kw):
        calls.append(kw["creationflags"])
        if len(calls) == 1 and fail_first:
            raise OSError("acceso denegado: el Job no permite salir")
        return Proc()

    monkeypatch.setattr(local_gpu.os, "name", "nt")
    monkeypatch.setattr(local_gpu.subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000, raising=False)
    monkeypatch.setattr(local_gpu.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    monkeypatch.setattr(local_gpu.subprocess, "DETACHED_PROCESS", 0x8, raising=False)
    monkeypatch.setattr(local_gpu.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    fail_first = False
    assert local_gpu.start_watchdog(1, 8090, 15, popen=popen) == 4321
    assert calls[-1] & 0x01000000 and calls[-1] & 0x8
    calls.clear()
    fail_first = True                         # sin permiso de salida: se lanza dentro, como antes
    assert local_gpu.start_watchdog(1, 8090, 15, popen=popen) == 4321
    assert calls[0] & 0x01000000 and not calls[1] & 0x01000000
    assert local_gpu.start_watchdog(1, 8090, 0, popen=popen) is None     # vigilante desactivado


def test_vigilante_perdido_se_vuelve_a_armar(tmp_path, monkeypatch):
    """P0-3: con el servidor ya en marcha, un vigilante muerto (o nunca guardado) se vuelve a lanzar."""
    import subprocess

    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(tmp_path / "eolas-v2.json"))
    launched = []
    monkeypatch.setattr(local_gpu, "start_watchdog", lambda pid, port, idle: launched.append((pid, port)) or 777)
    record = {"pid": os.getpid(), "profile": "gemma", "port": 8090, "idle_watchdog_pid": 0}
    assert eolas_v2._ensure_watchdog(record, 8090, subprocess.Popen) == 777
    assert launched == [(os.getpid(), 8090)]
    assert json.loads(eolas_v2.runtime_file().read_text(encoding="utf-8"))["idle_watchdog_pid"] == 777
    alive = {**record, "idle_watchdog_pid": os.getpid()}             # vigilante vivo: no se duplica
    assert eolas_v2._ensure_watchdog(alive, 8090, subprocess.Popen) == os.getpid() and len(launched) == 1
    assert eolas_v2._ensure_watchdog(record, 8090, lambda *a, **k: None) is None   # popen simulado: nada
