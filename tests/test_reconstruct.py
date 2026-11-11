"""Fase 4: reconstrucción independiente desde la especificación (muestras sintéticas propias)."""
import base64
import json
import subprocess
import sys

import pytest

from eolfi.core.cases import CaseStore
from eolfi.core.evidence import EvidenceStore
from eolfi.observe import run_observation, run_replay
from eolfi.reconstruct import build_model, generate, reconstruct, verify
from eolfi.reconstruct.core import MANIFEST
from eolfi.spec import latest_spec, store_spec
from tests import observe_samples as samples
from tests.test_observe import _script


@pytest.fixture
def store(tmp_path):
    s = EvidenceStore(tmp_path / "e.db")
    yield s
    s.close()


def _observed_case(store, tmp_path):
    cid = CaseStore(store).create("rec")["case_id"]
    t = samples.write(tmp_path, "app.py", samples.APP_V1)
    steps = [{"id": "hola", "action": "run", "argv": ["{python}", "{target}"], "stdin": {"text": "hola"}},
             {"id": "vacio", "action": "run", "argv": ["{python}", "{target}"], "stdin": {"text": ""}},
             {"id": "hijo", "action": "run", "argv": ["{python}", "{target}", "--hijo"], "stdin": {"text": "x"}}]
    a = run_observation(_script(t, steps), store, authorized=True, case_id=cid)
    run_replay(store, a["evidence_id"], authorized=True, case_id=cid)
    store_spec(store, cid)
    return cid


def test_model_is_independent_and_explains_decisions(store, tmp_path):
    cid = _observed_case(store, tmp_path)
    model = build_model(store, cid)
    ids = {c["id"] for c in model["components"]}
    assert ids == {"cli", "persistence"}
    cli = next(c for c in model["components"] if c["id"] == "cli")
    assert len(cli["cases"]) == 3 and all(c["requirement"].startswith("REQ-") for c in cli["cases"])
    hola = next(c for c in cli["cases"] if c["stdin"] == "hola")
    assert hola["args"] == [] and hola["exit_code"] == 0 and "eco=hola" in hola["stdout"]
    assert any("{sandbox}" in c["stdout"] for c in cli["cases"])
    # Los efectos en archivos solo se conocen por hash: el caso se marca con lo pendiente.
    assert any("contenido del archivo" in p for p in hola["pending"])
    assert next(c for c in cli["cases"] if c["args"] == ["--hijo"])["exit_code"] == 0
    assert all(d["reason"] and d["alternatives"] for d in model["decisions"])
    assert all(d["requirements"] and d["evidence_ids"] for d in model["decisions"])
    known_evidence = {eid for req in latest_spec(store, cid)["requirements"] for eid in req["evidence_ids"]}
    assert all(set(d["evidence_ids"]) <= known_evidence for d in model["decisions"])
    persistence = next(c for c in model["components"] if c["id"] == "persistence")
    assert "{sandbox}/estado/datos.txt" in persistence["data"]
    assert model["spec_version"] >= 1 and len(model["content_sha256"]) == 64
    with pytest.raises(ValueError, match="especificación"):
        build_model(store, CaseStore(store).create("vacío")["case_id"])


def test_opt_in_file_capture_reconstructs_bytes_but_keeps_state_limit_partial(store, tmp_path):
    target = tmp_path / "writer.py"
    target.write_text(
        "from pathlib import Path\n"
        "p=Path('salida/result.bin'); p.parent.mkdir(parents=True, exist_ok=True)\n"
        "p.write_bytes(bytes([0, 1, 254, 255]))\n"
        "print('guardado')\n",
        encoding="utf-8")
    cid = CaseStore(store).create("archivo capturado")['case_id']
    script = _script(target, [{"id": "guardar", "action": "run", "argv": ["{python}", "{target}"]}],
                     scope={"files": ["."], "capture_contents": ["{sandbox}/salida/result.bin"]})
    observed = run_observation(script, store, authorized=True, case_id=cid)
    assert observed["status"] == "done"
    assert observed["coverage"]["file_contents"]["status"] == "captured"
    assert observed["coverage"]["file_contents"]["not_redacted"] is True
    effect = observed["steps"][0]["effects"]["files"][0]
    capture = effect["after"]["content_capture"]
    assert capture["status"] == "captured" and capture["utf8"] is False
    assert base64.b64decode(capture["data_base64"]) == bytes([0, 1, 254, 255])
    store_spec(store, cid)
    model = build_model(store, cid)
    case = next(c for component in model["components"] if component["id"] == "cli" for c in component["cases"])
    assert case["status"] == "parcial" and len(case["file_ops"]) == 1
    assert any("transiciones de estado" in reason for reason in case["pending"])
    out = tmp_path / "generated"
    generated = generate(model, out)
    assert generated["simulated"] == 0 and generated["partial"] == 1 and generated["pending"] == 0
    verified = verify(out)
    assert verified["match"] == 0 and verified["partial"] == 1 and verified["differ"] == 0
    assert verified["equivalent_on_observed"] is False
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    proc = subprocess.run([sys.executable, str(out / "app.py")], input=b"", capture_output=True, cwd=run_dir)
    assert proc.returncode == 0 and proc.stdout.replace(b"\r\n", b"\n") == b"guardado\n"
    assert (run_dir / "salida/result.bin").read_bytes() == bytes([0, 1, 254, 255])
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(out / "tests")],
                           capture_output=True, cwd=out)
    assert tests.returncode == 0, tests.stdout.decode("utf-8", "replace")[-2000:]


def test_generate_verify_and_trace(store, tmp_path):
    cid = _observed_case(store, tmp_path)
    out = tmp_path / "rec"
    rep = reconstruct(store, cid, out, name="muestra")
    gen, ver = rep["generation"], rep["verification"]
    assert set(gen["written"]) == {"app.py", "comportamiento.json", "tests/test_app.py", "README.md"}
    assert gen["simulated"] == 0 and gen["partial"] == 3 and gen["pending"] == 0
    assert ver["match"] == 0 and ver["partial"] == 3 and ver["differ"] == 0
    assert ver["equivalent_on_observed"] is False
    assert "no demuestra equivalencia general" in ver["limits"]
    # La base generada arranca, reproduce lo observado y declara lo no especificado.
    p = subprocess.run([sys.executable, str(out / "app.py")], input=b"hola", capture_output=True, cwd=tmp_path)
    assert p.returncode == 0 and f"cwd={tmp_path}" in p.stdout.decode() and "eco=hola" in p.stdout.decode()
    p = subprocess.run([sys.executable, str(out / "app.py"), "--otra"], input=b"", capture_output=True)
    assert p.returncode == 2 and "no especificado" in p.stderr.decode("utf-8", "replace")
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(out / "tests")],
                       capture_output=True, cwd=out)
    assert p.returncode == 0, p.stdout.decode()[-2000:]
    # No copia código del original: ninguna línea característica del objetivo aparece en lo generado.
    gen_text = "".join(f.read_text(encoding="utf-8") for f in out.rglob("*.py"))
    assert "subprocess.run([sys.executable, \"-c\"" not in gen_text and "winreg" not in gen_text
    m = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    assert m["files"]["app.py"]["requirements"] and m["cases"][0]["evidence_ids"]
    assert {c["id"]: c["generated"] for c in m["components"]} == {"cli": True, "persistence": False}
    # Registro del caso con la verificación como evidencia.
    rec = [r for r in CaseStore(store).get(cid)["records"] if r["payload"].get("flow") == "reconstruct"][0]
    assert rec["kind"] == "reconstruction" and rec["payload"]["status"] == "partial"
    assert rec["payload"]["result"]["match"] == 0


def test_regeneration_keeps_manual_changes(store, tmp_path):
    cid = _observed_case(store, tmp_path)
    out = tmp_path / "rec"
    model = build_model(store, cid)
    generate(model, out)
    (out / "README.md").write_text("mis notas", encoding="utf-8")
    again = generate(model, out)
    assert again["kept_manual"] == ["README.md"]
    assert (out / "README.md").read_text(encoding="utf-8") == "mis notas"
    assert (out / "README.md.nuevo").exists()
    assert json.loads((out / MANIFEST).read_text(encoding="utf-8"))["files"]["README.md"]["manual_changes"] is True
    # Un archivo no tocado sí se regenera.
    assert "app.py" in again["written"]


def test_contradicted_requirement_stays_pending(store, tmp_path):
    cid = CaseStore(store).create("azar")["case_id"]
    n = samples.write(tmp_path, "azar.py", samples.NONDETERMINISTIC)
    s = _script(n, [{"id": "azar", "action": "run", "argv": ["{python}", "{target}"]}])
    run_observation(s, store, authorized=True, case_id=cid)
    run_observation(s, store, authorized=True, case_id=cid)
    store_spec(store, cid)
    rep = reconstruct(store, cid, tmp_path / "rec")
    assert rep["generation"]["pending"] == 1 and rep["verification"]["pending"] == 1
    assert rep["verification"]["equivalent_on_observed"] is False
    p = subprocess.run([sys.executable, str(tmp_path / "rec" / "app.py")], input=b"", capture_output=True)
    assert p.returncode == 3 and "pendiente" in p.stderr.decode("utf-8", "replace")


def test_cli_reconstruct(store, tmp_path, capsys):
    from eolfi.cli import main

    db = tmp_path / "c.db"
    s = EvidenceStore(db)
    cid = _observed_case(s, tmp_path)
    s.close()
    assert main(["--db", str(db), "reconstruct", "--case", cid, "--model"]) == 0
    assert json.loads(capsys.readouterr().out)["components"]
    assert main(["--db", str(db), "reconstruct", "--case", cid, "--out", str(tmp_path / "r")]) == 4
    assert json.loads(capsys.readouterr().out)["verification"]["partial"] == 3


def test_equivalence_same_script_structured_effects_coverage_and_incognitas(store, tmp_path):
    from eolfi.core.models import Status
    from eolfi.reconstruct import check_equivalence

    cid = _observed_case(store, tmp_path)
    # Un guion sin objetivo (solo escribe un archivo) no se puede ejercitar contra el candidato: queda listado.
    run_observation(_script(None, [{"id": "solo", "action": "write_file", "path": "a.txt", "text": "x"}]),
                    store, authorized=True, case_id=cid)
    store_spec(store, cid)
    rep = reconstruct(store, cid, tmp_path / "rec")
    cand = tmp_path / "rec" / "app.py"
    with pytest.raises(PermissionError):
        check_equivalence(store, cid, cand, authorized=False)
    eq = check_equivalence(store, cid, cand, authorized=True)
    reqs = {r["title"]: r for r in eq["requirements"]}
    assert reqs["write_file «solo»"]["result"] == "not_exercised"
    assert eq["coverage"]["not_exercised"] == [reqs["write_file «solo»"]["id"]]
    hola = next(r for r in eq["requirements"] if r["result"] != "not_exercised" and "hola" in r["title"])
    # stdout/código coinciden; los efectos en archivos (y el proceso hijo) no se reconstruyeron: divergencia visible.
    assert hola["result"] == "divergent" and "archivos" in hola["aspects"] and "stdout" not in hola["aspects"]
    assert hola["severity"] == "medium"
    hijo = next(r for r in eq["requirements"] if r["title"] == "run «hijo»")
    assert "procesos hijos" in hijo["aspects"]
    assert eq["equivalent"] is False and eq["incognitas_opened"] >= 3
    subj = rep["model"]["components"] and store.get_evidence(eq["runs"][0]["original"])["subject"]
    open_q = [i for i in store.list_incognitas(Status.OPEN, subject=subj) if i["question"].startswith("Equivalencia:")]
    assert open_q
    # Con tolerancias declaradas, lo que queda coincide y las incógnitas de esos requisitos se cierran.
    eq2 = check_equivalence(store, cid, cand, authorized=True, tolerances=["archivos", "procesos hijos"])
    assert eq2["counts"]["divergent"] == 0 and eq2["counts"]["equivalent"] == 3
    assert eq2["equivalent"] is False                        # hay un requisito sin ejercitar: no se declara total
    assert eq2["incognitas_closed"] >= 1
    assert not [i for i in store.list_incognitas(Status.OPEN, subject=subj)
                if i["question"].startswith("Equivalencia:") and hola["id"] in i["question"]]
    rec = [r for r in CaseStore(store).get(cid)["records"] if r["payload"].get("flow") == "equivalence"]
    assert len(rec) == 2 and rec[-1]["kind"] == "comparison"


def test_severity_levels():
    from eolfi.reconstruct.equivalence import severity

    assert severity("código de salida") == "high" and severity("pulsar.url") == "high"
    assert severity("archivos") == "medium" and severity("ui.accesibilidad") == "medium"
    assert severity("stderr") == "low" and severity("procesos hijos") == "low"


def test_ddmin_reduces_to_minimal_failing_input():
    from eolfi.reconstruct.explore import ddmin

    data = b"linea uno\nlinea dos BOOM\nlinea tres\n"
    budget = [500]
    small = ddmin(data, lambda d: b"BOOM" in d, budget)
    assert small == b"BOOM" and budget[0] > 0


def test_variants_are_deterministic_and_exclude_original():
    import random

    from eolfi.reconstruct.explore import variants_for

    a = variants_for(b"hola mundo", 8, random.Random("1337:REQ-x"))
    b = variants_for(b"hola mundo", 8, random.Random("1337:REQ-x"))
    c = variants_for(b"hola mundo", 8, random.Random("7:REQ-x"))
    assert a == b and a != c and b"hola mundo" not in a and len(set(a)) == 8


def test_explore_variations_reduce_and_replay(store, tmp_path):
    from eolfi.reconstruct import explore

    cid = _observed_case(store, tmp_path)
    reconstruct(store, cid, tmp_path / "rec")
    cand = tmp_path / "rec" / "app.py"
    with pytest.raises(PermissionError):
        explore(store, cid, cand, authorized=False)
    rep = explore(store, cid, cand, authorized=True, variants=3, seed=11, max_runs=120,
                  tolerances=["archivos", "procesos hijos"])
    explored = [r for r in rep["requirements"] if r["status"] == "explored"]
    assert explored and rep["divergent_variants"] > 0          # la etapa 1 no generaliza: se ve con variantes
    hola = next(r for r in explored if "hola" in r["title"])
    assert len(hola["variants"]) == 3 and hola["minimal_failing"]
    m = hola["minimal_failing"][0]
    assert "código de salida" in m["aspects"] and m["size"] <= 4
    assert rep["config"] == {"seed": 11, "variants": 3, "max_runs": 120,
                             "tolerances": ["archivos", "procesos hijos"], "spec_version": rep["config"]["spec_version"]}
    again = explore(store, cid, cand, authorized=True, variants=3, seed=11, max_runs=120,
                    tolerances=["archivos", "procesos hijos"])
    h2 = next(r for r in again["requirements"] if r["title"] == hola["title"])
    assert [v["sha256"] for v in h2["variants"]] == [v["sha256"] for v in hola["variants"]]   # repetición determinista
    inc = [i for i in store.list_incognitas() if i["question"].startswith("Exploración:")]
    assert inc
    rec = [r for r in CaseStore(store).get(cid)["records"] if r["payload"].get("flow") == "explore"]
    assert rec and rec[0]["payload"]["result"]["config"]["seed"] == 11
    # Original cambiado: no se ejecuta otro binario en su lugar.
    t = tmp_path / "app.py"
    t.write_text(samples.APP_V2, encoding="utf-8")
    skipped = explore(store, cid, cand, authorized=True, variants=1, seed=11, max_runs=20)
    assert skipped["explored"] == 0 and all("original no disponible" in r["reason"] for r in skipped["requirements"])


def test_normalize_paths_longest_first_macos_private_var():
    """CI macOS: /var/folders/… es enlace de /private/var/folders/…; la forma larga debe sustituirse antes."""
    from eolfi.reconstruct.core import normalize_paths

    text = "cwd=/private/var/folders/ab/T/eolfi-rec-x\r\n"
    for forms in ({"/var/folders/ab/T/eolfi-rec-x", "/private/var/folders/ab/T/eolfi-rec-x"},
                  {"/private/var/folders/ab/T/eolfi-rec-x", "/var/folders/ab/T/eolfi-rec-x"}):
        assert normalize_paths(text, forms) == "cwd={sandbox}\n"


# -- O7: API HTTP observada ------------------------------------------------------------------------------
class _SampleApi(__import__("http.server").server.BaseHTTPRequestHandler):
    """Muestra sintética propia: dos rutas estables, una con cookie y un contador que cambia entre peticiones."""
    count = 0

    def log_message(self, *a):
        pass

    def _send(self, status, body, ctype="application/json", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/estado":
            return self._send(200, b'{"version": 1, "estado": "listo"}')
        if self.path == "/api/sesion":
            return self._send(200, b'{"sesion": true}', extra={"Set-Cookie": "sid=secreto-abc; Path=/"})
        if self.path == "/api/contador":
            _SampleApi.count += 1
            return self._send(200, json.dumps({"n": _SampleApi.count}).encode())
        return self._send(404, b"no existe", "text/plain; charset=utf-8")

    def do_POST(self):
        data = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/api/eco" and json.loads(data) == {"x": 1}:
            return self._send(201, b'{"recibido": 1}')
        return self._send(400, b'{"error": "entrada"}')


@pytest.fixture
def sample_api():
    from http.server import ThreadingHTTPServer
    import threading

    _SampleApi.count = 0
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _SampleApi)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def _http_case(store, port):
    cid = CaseStore(store).create("api")["case_id"]
    base = "http://127.0.0.1:{var:port}"
    steps = [{"id": "estado", "action": "http", "url": base + "/api/estado"},
             {"id": "eco", "action": "http", "method": "POST", "url": base + "/api/eco", "body": {"json": {"x": 1}},
              "headers": {"Content-Type": "application/json"}},
             {"id": "noexiste", "action": "http", "url": base + "/nada"},
             {"id": "sesion", "action": "http", "url": base + "/api/sesion"},
             {"id": "contador1", "action": "http", "url": base + "/api/contador"},
             {"id": "contador2", "action": "http", "url": base + "/api/contador"}]
    run_observation(_script(None, steps), store, authorized=True, case_id=cid, variables={"port": str(port)})
    store_spec(store, cid)
    return cid


def test_http_model_generates_only_observed_routes_with_traceability(store, tmp_path, sample_api):
    cid = _http_case(store, sample_api)
    model = build_model(store, cid)
    api = next(c for c in model["components"] if c["id"] == "http_api")
    by_path = {(c["method"], c["path"]): c for c in api["cases"]}
    assert by_path[("GET", "/api/estado")]["status"] == "simulado"
    assert by_path[("GET", "/api/estado")]["response_status"] == 200
    assert by_path[("GET", "/api/estado")]["content_type"] == "application/json"
    eco = by_path[("POST", "/api/eco")]
    assert eco["status"] == "simulado" and eco["response_status"] == 201
    assert base64.b64decode(eco["request_body_base64"]) == b'{"x": 1}' or json.loads(
        base64.b64decode(eco["request_body_base64"])) == {"x": 1}
    assert by_path[("GET", "/nada")]["response_status"] == 404     # un 404 observado también se reproduce
    sesion = by_path[("GET", "/api/sesion")]
    assert sesion["status"] == "parcial" and any("cookies" in p for p in sesion["pending"])
    assert "secreto-abc" not in json.dumps(model)
    contador = by_path[("GET", "/api/contador")]
    assert contador["status"] == "pendiente" and any("contradicho" in p for p in contador["pending"])
    assert all(c["evidence_ids"] for c in api["cases"])
    assert any("API HTTP" in d["decision"] and d["evidence_ids"] for d in model["decisions"])

    out = tmp_path / "api"
    gen = generate(model, out)                     # sin objetivo: no hay CLI, se elige la API HTTP
    assert {"server.py", "api.json", "tests/test_server.py", "README.md"} <= set(gen["written"])
    assert gen["simulated"] == 3 and gen["partial"] == 1 and gen["pending"] == 1
    manifest = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    assert manifest["target"] == "python-http"
    assert {c["route"] for c in manifest["cases"]} >= {"GET /api/estado", "POST /api/eco", "GET /api/contador"}
    assert all(c["evidence_ids"] for c in manifest["cases"])
    assert "secreto-abc" not in (out / "api.json").read_text(encoding="utf-8")

    ver = verify(out)
    assert ver["match"] == 3 and ver["partial"] == 1 and ver["pending"] == 1 and ver["differ"] == 0
    assert ver["equivalent_on_observed"] is False      # hay casos parciales y pendientes: no se da verde
    assert "cabeceras de la petición" in ver["limits"]

    p = subprocess.run([sys.executable, "-m", "pytest", "-q", str(out / "tests")], capture_output=True, text=True,
                       timeout=180)
    assert p.returncode == 0, p.stdout + p.stderr


def test_http_generated_server_marks_unobserved_and_pending_and_verify_detects_changes(store, tmp_path, sample_api):
    import urllib.error
    import urllib.request

    cid = _http_case(store, sample_api)
    out = tmp_path / "api"
    generate(build_model(store, cid), out, target="python-http")
    proc = subprocess.Popen([sys.executable, str(out / "server.py"), "--port", "0"], cwd=tmp_path,
                            stdout=subprocess.PIPE, text=True)
    try:
        base = proc.stdout.readline().strip().rsplit(" ", 1)[-1]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def get(path, method="GET", data=None):
            try:
                r = opener.open(urllib.request.Request(base + path, method=method, data=data), timeout=10)
            except urllib.error.HTTPError as exc:
                r = exc
            with r:
                return r.code if hasattr(r, "code") else r.status, r.headers.get("X-Eolfi-Estado")
        assert get("/no-observada") == (501, "no-especificado")
        assert get("/api/estado", "DELETE") == (501, "no-especificado")        # método no observado
        assert get("/api/eco", "POST", b'{"x": 2}') == (501, "no-especificado")  # cuerpo no observado
        assert get("/api/contador") == (503, "pendiente")
        assert get("/api/estado") == (200, None)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        proc.stdout.close()

    # Un cambio en la respuesta generada se detecta por su aspecto concreto, no solo por el código.
    cases = json.loads((out / "api.json").read_text(encoding="utf-8"))
    estado = next(c for c in cases if c["path"] == "/api/estado")
    expected_body = estado["response_body"]
    server = (out / "server.py").read_text(encoding="utf-8")
    (out / "server.py").write_text(server.replace('_render(case["response_body"])',
                                                  '_render(case["response_body"]).replace("listo", "otro")'),
                                   encoding="utf-8")
    ver = verify(out)
    diff = next(r for r in ver["results"] if r.get("route") == "GET /api/estado")
    assert diff["status"] == "difiere" and diff["aspects"] == ["respuesta[*].cuerpo"]
    assert "listo" in expected_body


def test_http_reconstruct_records_evidence_and_target_errors(store, tmp_path, sample_api):
    cid = _http_case(store, sample_api)
    rep = reconstruct(store, cid, tmp_path / "rec")
    assert rep["generation"]["simulated"] == 3 and rep["verification"]["differ"] == 0
    assert store.get_evidence(rep["evidence_id"])["operation"] == "reconstruction_verification"
    with pytest.raises(ValueError, match="línea de comandos"):
        generate(build_model(store, cid), tmp_path / "cli", target="python-cli")
    cli_case = _observed_case(store, tmp_path)
    with pytest.raises(ValueError, match="API HTTP"):
        generate(build_model(store, cli_case), tmp_path / "http", target="python-http")
