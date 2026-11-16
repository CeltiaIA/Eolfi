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
            # Como el llama-server real arrancado con --api-key-file: sin la clave, 401 (P0-2, 15/11/2026).
            if self.headers.get("Authorization") != f"Bearer {eolas_v2.api_key()}":
                self.send_error(401)
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
        llm.EolasV1Provider("http://127.0.0.1:11435", "gemma").complete("s", [{"role": "user", "content": "x"}], {}, None)
    monkeypatch.setattr(llm, "_post", lambda *a, **k: {"message": {"content": "{\"ok\": 1}"}})
    llm.EolasV1Provider("http://eolas.remota:11435", "gemma").complete("s", [{"role": "user", "content": "x"}], {}, None)
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


def test_el_vigilante_lee_slots_con_la_clave_de_eolas_v2(v2, server):
    _Eolas.slots = [{"id": 0, "id_task": 5, "is_processing": True}]
    holder = local_gpu.eolas_v2_holder()
    assert holder["slots_ok"] and holder["busy"] and holder["tasks"] == (5,)


class _Proc:
    def __init__(self, pid):
        self.pid = pid


def test_vigilante_sale_del_job_y_si_no_puede_se_lanza_igual(monkeypatch):
    monkeypatch.setattr(local_gpu.os, "name", "nt")
    monkeypatch.setattr(local_gpu.subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000, raising=False)
    calls = []

    def popen(args, creationflags=0, **k):
        calls.append(creationflags)
        if creationflags & 0x01000000 and len(calls) == 1 and fail:
            raise OSError("acceso denegado")
        return _Proc(4242)

    fail = False
    assert local_gpu.start_watchdog(1, 8090, 15, popen=popen, token="t") == 4242
    assert calls[0] & 0x01000000
    calls.clear()
    fail = True
    assert local_gpu.start_watchdog(1, 8090, 15, popen=popen) == 4242
    assert calls[0] & 0x01000000 and not calls[1] & 0x01000000


def test_vigilante_perdido_se_rearma_y_el_antiguo_se_retira(v2, server, monkeypatch):
    launched = []
    alive = {os.getpid()}
    monkeypatch.setattr(eolas_v2, "_pid_alive", lambda pid: pid in alive)
    popen = lambda args, **k: launched.append(args) or _Proc(777)
    first = local_gpu.ensure_watchdog(popen=popen)
    record = json.loads(eolas_v2.runtime_file().read_text(encoding="utf-8"))
    assert first == 777 and record["idle_watchdog_pid"] == 777 and len(launched) == 1
    old_token = record["idle_watchdog_token"]
    assert launched[0][launched[0].index("--token") + 1] == old_token
    alive.add(777)
    assert local_gpu.ensure_watchdog(popen=popen) == 777 and len(launched) == 1   # vivo: no se duplica
    alive.discard(777)                                                           # murió con su sesión
    assert local_gpu.ensure_watchdog(popen=popen) == 777 and len(launched) == 2
    new_token = json.loads(eolas_v2.runtime_file().read_text(encoding="utf-8"))["idle_watchdog_token"]
    assert new_token != old_token
    # Un vigilante antiguo que siguiera vivo ve otro token y se retira sin parar el servidor.
    r = local_gpu.watch(os.getpid(), server[1], 15, clock=lambda: 0, sleep=lambda _: None, token=old_token)
    assert r == "otro vigilante activo" and v2 == []


def test_eolfi_llama_start_retirado(capsys):
    from eolfi import cli

    assert cli.main(["llama", "start"]) != 0
    assert "retirado" in capsys.readouterr().err


def test_un_pid_reutilizado_no_se_toma_por_eolas_v2(v2, server, monkeypatch):
    """P2-3 (15/11/2026): con la hora de creación anotada, otro proceso con el mismo PID no es el servidor."""
    started = eolas_v2._process_started(os.getpid())
    assert started is not None and abs(started - __import__("time").time()) < 7 * 24 * 3600
    record = {"pid": os.getpid(), "pid_started": started, "profile": "nemo_q4", "port": server[1]}
    assert eolas_v2._record_alive(record)
    assert not eolas_v2._record_alive({**record, "pid_started": started - 3600})     # PID reutilizado
    assert eolas_v2._record_alive({k: v for k, v in record.items() if k != "pid_started"})   # registro antiguo
    eolas_v2.runtime_file().write_text(json.dumps({**record, "pid_started": started - 3600}), encoding="utf-8")
    assert local_gpu.eolas_v2_holder() is None
    killed = []
    monkeypatch.setattr(eolas_v2.subprocess, "run", lambda *a, **k: killed.append(a) or pytest.fail("no debe matar"))
    monkeypatch.setattr(eolas_v2, "_read_json", lambda *a, **k: None)
    assert eolas_v2._stop_locked() is True and killed == []          # limpia el registro sin tocar el proceso ajeno
    assert not eolas_v2.runtime_file().exists()


def test_candado_explica_la_inferencia_y_el_vigilante_no_muere(v2, server, monkeypatch):
    """P2-4: una inferencia retiene el candado; stop lo explica y el vigilante sigue en lugar de morir."""
    with eolas_v2._exclusive_lock("inferencia"),             pytest.raises(eolas_v2.EolasBusy, match="respondiendo una petición"), eolas_v2._exclusive_lock():
        pass
    with eolas_v2._exclusive_lock(), pytest.raises(eolas_v2.EolasBusy, match="cambiando de perfil"),             eolas_v2._exclusive_lock():
        pass
    now = [0.0]
    attempts = []

    def busy_stop():
        attempts.append(now[0])
        if len(attempts) == 1:
            raise eolas_v2.EolasBusy("Eolas V2 está respondiendo una petición")
        eolas_v2.runtime_file().unlink()
        return {"stopped": True}

    monkeypatch.setattr(eolas_v2, "stop", busy_stop)

    def tick(_):
        now[0] += 60

    r = local_gpu.watch(os.getpid(), server[1], idle_minutes=2, clock=lambda: now[0], sleep=tick)
    assert r.startswith("parado tras 2") and len(attempts) == 2
    assert attempts[1] - attempts[0] >= 2 * 60          # el candado contó como uso y reinició la espera


def test_motor_local_se_elige_y_lo_siguen_el_generador_y_la_cli(monkeypatch, capsys):
    """15/11/2026: Eolfi trabaja con Eolas V1 o V2; la elección se guarda y la siguen proveedor y CLI."""
    from eolfi.cli import main
    from eolfi.generador.llm import default_provider, make_provider

    assert local_gpu.local_engine() == "eolas-v2" and default_provider() == "eolas-v2"
    assert main(["motor-local", "v1"]) == 0
    assert "eolas-v1" in capsys.readouterr().out
    assert local_gpu.local_engine() == "eolas-v1" and default_provider() == "eolas"
    assert make_provider().name == "eolas"
    monkeypatch.setenv("EOLFI_LOCAL_ENGINE", "eolas-v2")
    assert local_gpu.local_provider() == "eolas-v2"
    monkeypatch.delenv("EOLFI_LOCAL_ENGINE")
    assert main(["motor-local", "eolas-v3"]) == 2
    assert local_gpu.local_engine() == "eolas-v1"
    with pytest.raises(ValueError):
        local_gpu.set_local_engine("otro-motor")


def test_clave_de_eolas_v1_solo_va_a_este_equipo(tmp_path, monkeypatch):
    """P2-1: la clave que crea launch-eolas.ps1 se lee del runtime de CeltIA y nunca sale a un host remoto."""
    assert local_gpu.eolas_v1_headers("http://127.0.0.1:11435") == {}
    key = tmp_path / "celtiaia" / "runtime" / "eolas" / "api.key"
    key.parent.mkdir(parents=True)
    key.write_text("clave-de-prueba\n", encoding="utf-8")
    assert local_gpu.eolas_v1_headers("http://127.0.0.1:11435") == {"Authorization": "Bearer clave-de-prueba"}
    assert local_gpu.eolas_v1_headers("http://192.168.1.20:11435") == {}
    monkeypatch.setenv("EOLAS_API_KEY", "de-la-variable")
    assert local_gpu.eolas_v1_headers("http://localhost:11435") == {"Authorization": "Bearer de-la-variable"}


def test_eolas_v1_recibe_la_clave_en_chat_y_en_ps(tmp_path, monkeypatch):
    """El proveedor eolas y la guardia de GPU envían la clave a 11435 (con ella activa, sin clave es 401)."""
    seen = []

    class H(BaseHTTPRequestHandler):
        def _ok(self, body):
            seen.append((self.path, self.headers.get("Authorization")))
            if self.headers.get("Authorization") != "Bearer k1":
                self.send_response(401)
                self.end_headers()
                return
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._ok({"models": []})

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self._ok({"message": {"content": "{\"ok\": 1}"}})

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        monkeypatch.setenv("EOLAS_API_KEY", "k1")
        assert local_gpu.eolas_loaded(url) == []
        from eolfi.generador import llm

        monkeypatch.setattr(local_gpu, "free_for_eolas", lambda: {"freed": []})
        provider = llm.make_provider("eolas", base_url=url)
        assert provider.complete("s", [{"role": "user", "content": "x"}], {}, None).data["ok"] == 1
        assert all(auth == "Bearer k1" for _, auth in seen) and any(p == "/api/chat" for p, _ in seen)
    finally:
        srv.shutdown()


def test_free_for_eolas_por_linea_de_ordenes(monkeypatch, capsys):
    """P1-5: la extensión libera Eolas V2 antes de usar V1 llamando a «python -m eolfi.local_gpu free-for-eolas»."""
    monkeypatch.setattr(local_gpu, "free_for_eolas", lambda: {"freed": ["eolas-v2"]})
    assert local_gpu.main(["free-for-eolas"]) == 0
    assert json.loads(capsys.readouterr().out) == {"freed": ["eolas-v2"]}

    def busy():
        raise local_gpu.GpuBusy("Eolas V2 está respondiendo")

    monkeypatch.setattr(local_gpu, "free_for_eolas", busy)
    assert local_gpu.main(["free-for-eolas"]) == 3
    assert "respondiendo" in json.loads(capsys.readouterr().out)["error"]


def test_modelo_local_que_agota_el_plazo_no_se_reintenta(monkeypatch):
    """15/11/2026: Eolas V1 tenía 900 s y 3 reintentos; cada reintento volvía a generar desde cero en la GPU."""
    import time

    from eolfi.generador import llm

    hits = []

    class Lento(BaseHTTPRequestHandler):
        def do_POST(self):
            hits.append(1)
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            time.sleep(1.5)
            try:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")
            except OSError:
                pass

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Lento)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/api/chat"
    try:
        with pytest.raises(llm.LLMError, match="no se repite la petición"):
            llm._post(url, {}, {}, 0.3, sleep=lambda s: None, retry_timeouts=False)
        assert len(hits) == 1
        hits.clear()
        with pytest.raises(llm.LLMError, match="No se pudo conectar"):
            llm._post(url, {}, {}, 0.3, retries=1, sleep=lambda s: None)
        assert len(hits) == 2                              # las API remotas siguen reintentando
    finally:
        srv.shutdown()
    assert llm.EolasV1Provider("http://127.0.0.1:11435", "m").timeout == llm.LOCAL_TIMEOUT == 1800.0


def test_opciones_de_eolas_v1_por_variables(monkeypatch):
    from eolfi.generador.llm import LLMError, eolas_v1_options

    for name in ("EOLFI_EOLAS_NUM_CTX", "EOLFI_EOLAS_NUM_PREDICT", "EOLFI_EOLAS_NUM_GPU"):
        monkeypatch.delenv(name, raising=False)
    assert eolas_v1_options() == {"num_ctx": 32768, "num_predict": 12000, "temperature": 0.2}
    monkeypatch.setenv("EOLFI_EOLAS_NUM_CTX", "16384")
    monkeypatch.setenv("EOLFI_EOLAS_NUM_PREDICT", "4096")
    monkeypatch.setenv("EOLFI_EOLAS_NUM_GPU", "99")
    assert eolas_v1_options() == {"num_ctx": 16384, "num_predict": 4096, "temperature": 0.2, "num_gpu": 99}
    monkeypatch.setenv("EOLFI_EOLAS_NUM_GPU", "muchas")
    with pytest.raises(LLMError, match="EOLFI_EOLAS_NUM_GPU"):
        eolas_v1_options()
    monkeypatch.setenv("EOLFI_EOLAS_NUM_GPU", "0")
    monkeypatch.setenv("EOLFI_EOLAS_NUM_CTX", "10")
    with pytest.raises(LLMError, match="al menos 1024"):
        eolas_v1_options()
