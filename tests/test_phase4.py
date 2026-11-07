"""Fase 4 del plan de correcciones: las pruebas que faltaban.

- Nombres hostiles en TODOS los destinos (el código generado sigue siendo válido y no inyecta nada).
- Fuzz por mutación de todos los formatos binarios con límite de tiempo.
- fetch: robots.txt con 5xx, anti-SSRF en la conexión y plazo total.
- Servidor: variantes de Host, cuerpos que no son objeto, /api/repo, /api/compare.
- Panel: nunca innerHTML/insertAdjacentHTML/eval en app.js.
- Migraciones generadas: número duplicado y CRLF.
"""
import ast
import http.server
import importlib.util
import json
import random
import sys
import threading
import time
from pathlib import Path

import pytest

from eolfi.core.evidence import EvidenceStore
from eolfi.flows.learn_flow import run_repo, run_web
from eolfi.generador.generators import generate
from eolfi.generador.spec import TARGETS, build_spec
from eolfi.providers.binfmt import ParseError
from tests.fixtures import build_repo, build_site

HOSTILE = 'Ti"""enda\n{{ request.META }}{% debug %}<img src=x onerror=alert(1)>${x}`y`\\z\'; DROP TABLE x;--'


# ---------------------------------------------------------------- nombres hostiles
@pytest.fixture(scope="module")
def hostile_store(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("hostil")
    s = EvidenceStore(":memory:")
    subs = [run_web(str(build_site(tmp / "site")), s)["subject"], run_repo(str(build_repo(tmp / "repo")), s)["subject"]]
    return s, subs


@pytest.mark.parametrize("target", TARGETS)
def test_hostile_title_in_every_target(hostile_store, tmp_path, target):
    s, subs = hostile_store
    spec = build_spec(s, subs, name=HOSTILE, target=target)
    out = tmp_path / "out"
    files = generate(spec, out)
    for f in files:
        path = out / f
        if f.endswith(".png"):
            continue
        text = path.read_text(encoding="utf-8")
        # Ninguna pieza peligrosa del título llega al código generado.
        # (palabras sueltas como «DROP TABLE» son texto inofensivo; lo peligroso son los delimitadores)
        for bad in ('Ti"""enda', "{{ request", "{% debug", "<img src=x", "${x}", "`y`", "x'; DROP"):
            assert bad not in text, (target, f, bad)
        if f.endswith(".py"):
            ast.parse(text, filename=f)                      # Python sigue siendo válido
        elif f.endswith(".json") and not f.endswith("tsconfig.json"):
            json.loads(text)                                 # JSON válido (package.json, tauri.conf…)
    assert spec["title"] and all(c not in spec["title"] for c in '"`{}<>$\\%\n')


# ---------------------------------------------------------------- fuzz de formatos
def _fixtures():
    from tests import fixtures as fx
    out = {"macho": fx.build_macho64(), "dex": fx.build_dex(["La/b;", "Lc/d;"]),
           "axml": fx.build_axml(("manifest", {"package": "com.x"}, [])), "arsc": fx.build_arsc()}
    try:
        from tests.elfgen import build_elf64
        out["elf"] = build_elf64()
    except Exception:  # noqa: BLE001
        pass
    return out


def _parsers():
    from eolfi.providers.arsc import resolve
    from eolfi.providers.axml import parse_axml
    from eolfi.providers.binfmt import parse_elf, parse_pe
    from eolfi.providers.dex import parse_dex
    from eolfi.providers.macho import parse_macho
    return {"macho": parse_macho, "dex": parse_dex, "axml": parse_axml, "elf": parse_elf, "pe": parse_pe,
            "arsc": lambda d: resolve(d, {0x7F010000})}


@pytest.mark.parametrize("kind", ["macho", "dex", "axml", "arsc", "elf"])
def test_fuzz_formats_fail_cleanly_and_fast(kind):
    seeds = _fixtures()
    if kind not in seeds:
        pytest.skip("sin semilla")
    parse = _parsers()[kind]
    rng = random.Random(1337)
    seed = bytearray(seeds[kind])
    t0 = time.time()
    for _ in range(300):
        data = bytearray(seed)
        for _ in range(rng.randint(1, 12)):
            if not data:
                break
            op = rng.random()
            i = rng.randrange(len(data))
            if op < 0.6:
                data[i] = rng.randrange(256)
            elif op < 0.8:
                data[i:i + 4] = rng.choice([b"\xff\xff\xff\x7f", b"\x00\x00\x00\x00", b"\xff\xff\xff\xff"])
            else:
                data = data[:i]
        start = time.time()
        try:
            parse(bytes(data))
        except ParseError:
            pass
        assert time.time() - start < 2, f"{kind}: entrada mutada tardó demasiado"
    assert time.time() - t0 < 30


# ---------------------------------------------------------------- fetch
class _Handler(http.server.BaseHTTPRequestHandler):
    routes: dict = {}

    def do_GET(self):  # noqa: N802
        code, headers, body = self.routes.get(self.path, (404, {}, b"no"))
        if callable(body):
            self.send_response(code)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            body(self.wfile)
            return
        self.send_response(code)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def local_server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_robots_5xx_means_disallow(local_server):
    from eolfi.sites.fetch import FetchError, Fetcher
    _srv, base = local_server
    _Handler.routes = {"/robots.txt": (503, {}, b"caido"), "/": (200, {"Content-Type": "text/html"}, b"<p>hola</p>")}
    with pytest.raises(FetchError, match="robots"):
        Fetcher(delay=0).get(base + "/")


def test_redirect_to_private_blocked_when_page_is_public(local_server):
    from eolfi.sites.fetch import FetchError, Fetcher
    _srv, base = local_server
    _Handler.routes = {"/": (200, {}, b"ok")}
    f = Fetcher(delay=0, respect_robots=False)
    f.allow_private = False                     # como si la primera URL fuese pública
    with pytest.raises(FetchError, match="anti-SSRF"):
        f._raw_get(base + "/", 1000)            # no llega al 127.0.0.1


def test_slow_drip_server_hits_total_deadline(local_server):
    from eolfi.sites.fetch import FetchError, Fetcher

    def drip(w):
        for _ in range(40):
            w.write(b"x")
            w.flush()
            time.sleep(0.1)
    _srv, base = local_server
    _Handler.routes = {"/lento": (200, {"Content-Type": "text/plain"}, drip)}
    f = Fetcher(delay=0, respect_robots=False, timeout=0.5)   # plazo total = 1,5 s
    t = time.time()
    with pytest.raises(FetchError, match="lenta"):
        f._raw_get(base + "/lento", 10_000)
    assert time.time() - t < 4


def test_https_to_http_redirect_rejected(monkeypatch):
    from eolfi.sites import fetch
    f = fetch.Fetcher(delay=0, respect_robots=False)

    class Resp:
        status = 302
        headers = type("H", (), {"items": lambda self: [("Location", "http://example.com/")],
                                 "get_all": lambda self, k: None})()

        def close(self):
            pass
    monkeypatch.setattr(f, "_check_url", lambda u: None)
    monkeypatch.setattr(f._opener, "open", lambda req, timeout=None: Resp())
    with pytest.raises(fetch.FetchError, match="https a http"):
        f._raw_get("https://example.com/", 100)


# ---------------------------------------------------------------- servidor y panel
@pytest.fixture
def api(tmp_path):
    from eolfi.server import make_server
    httpd = make_server(str(tmp_path / "e.db"), "127.0.0.1", 0, tmp_path / "s")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1], tmp_path
    httpd.shutdown()


def _req(port, method, path, body=None, headers=None):
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, data


@pytest.mark.parametrize("host,ok", [("127.0.0.1", True), ("localhost", True), ("[::1]", True),
                                     ("evil.example", False), ("127.0.0.1.nip.io", False)])
def test_host_header_variants(api, host, ok):
    port, _ = api
    st, _ = _req(port, "GET", "/api/health", headers={"Host": f"{host}:{port}"})
    assert (st == 200) == ok


@pytest.mark.parametrize("body", ["[]", '"x"', "42", "null"])
def test_non_object_bodies_are_400(api, body):
    port, _ = api
    st, data = _req(port, "POST", "/api/compare", body, {"X-Eolfi": "1", "Content-Type": "application/json"})
    assert st == 400, data


def test_repo_and_compare_endpoints(api):
    port, tmp = api
    h = {"X-Eolfi": "1", "Content-Type": "application/json"}
    repo = build_repo(tmp / "r1")
    site = build_site(tmp / "w1")
    st, a = _req(port, "POST", "/api/repo", json.dumps({"source": str(repo)}), h)
    assert st == 200, a
    st, b = _req(port, "POST", "/api/web", json.dumps({"source": str(site)}), h)
    assert st == 200, b
    a, b = json.loads(a)["subject"], json.loads(b)["subject"]
    st, r = _req(port, "POST", "/api/compare", json.dumps({"a": a, "b": b}), h)
    assert st == 200, r
    assert json.loads(r)["subject"].startswith("compare:")
    st, _ = _req(port, "POST", "/api/compare", json.dumps({"a": "no-existe", "b": b}), h)
    assert st == 404


def test_panel_never_uses_html_injection_sinks():
    js = (Path(__file__).resolve().parent.parent / "eolfi" / "web" / "app.js").read_text(encoding="utf-8")
    for sink in (".innerHTML", "insertAdjacentHTML", "outerHTML", "document.write", "eval(", "new Function("):
        assert sink not in js, sink


# ---------------------------------------------------------------- migraciones generadas
def _load_migrate(out: Path):
    spec = importlib.util.spec_from_file_location("gen_migrate", out / "app" / "migrate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gen_migrate"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_generated_migrations_reject_duplicates_and_ignore_crlf(hostile_store, tmp_path):
    import sqlite3
    s, subs = hostile_store
    spec = build_spec(s, subs, name="Tienda", target="fastapi")
    spec["options"] = {"db": "sqlite", "auth": False}
    out = tmp_path / "out"
    generate(spec, out)
    mig = _load_migrate(out)
    mig.MIGRATIONS = out / "migrations"
    db = sqlite3.connect(":memory:")
    assert mig.apply(db) == ["0001_init.sql"]
    # Misma migración con CRLF (git autocrlf en Windows): no cuenta como editada.
    f = out / "migrations" / "0001_init.sql"
    f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
    assert mig.apply(db) == []
    (out / "migrations" / "0002_a.sql").write_text("SELECT 1;", encoding="utf-8")
    (out / "migrations" / "0002_b.sql").write_text("SELECT 2;", encoding="utf-8")
    with pytest.raises(mig.MigrationError, match="repetido"):
        mig.apply(db)
    (out / "migrations" / "0002_b.sql").unlink()
    (out / "migrations" / "0003_tx.sql").write_text("BEGIN;\nSELECT 1;\nCOMMIT;", encoding="utf-8")
    with pytest.raises(mig.MigrationError, match="BEGIN"):
        mig.apply(db)


# ---------------------------------------------------------------- trabajos en segundo plano
def test_background_job_reports_progress_and_result(api):
    port, tmp = api
    h = {"X-Eolfi": "1", "Content-Type": "application/json"}
    site = build_site(tmp / "wj")
    st, r = _req(port, "POST", "/api/jobs", json.dumps({"kind": "web", "body": {"source": str(site)}}), h)
    assert st == 202, r
    jid = json.loads(r)["job_id"]
    log, since, status = [], 0, "running"
    for _ in range(200):
        st, r = _req(port, "GET", f"/api/jobs?id={jid}&since={since}")
        d = json.loads(r)
        log += d["log"]
        since, status = d["next"], d["status"]
        if status != "running":
            break
        time.sleep(0.1)
    assert status == "done", d
    assert d["result"]["subject"] and log, log
    st, r = _req(port, "POST", "/api/jobs", json.dumps({"kind": "repo", "body": {"source": "Z:/no/existe"}}), h)
    jid = json.loads(r)["job_id"]
    for _ in range(100):
        d = json.loads(_req(port, "GET", f"/api/jobs?id={jid}")[1])
        if d["status"] != "running":
            break
        time.sleep(0.1)
    assert d["status"] == "error" and d["code"] in (400, 404)
    assert _req(port, "POST", "/api/jobs", json.dumps({"kind": "rm -rf", "body": {}}), h)[0] == 400
    assert _req(port, "GET", "/api/jobs?id=nada")[0] == 404


# ---------------------------------------------------------------- carpetas permitidas
def test_allowed_roots_confine_local_paths(tmp_path):
    from eolfi.server import ApiError, EolfiApp
    inside, outside = tmp_path / "dentro", tmp_path / "fuera"
    for d in (inside, outside):
        d.mkdir()
        (d / "a.bin").write_bytes(b"MZ" + bytes(64))
    app = EolfiApp(str(tmp_path / "e.db"), tmp_path / "s", roots=[str(inside)])
    assert [d["path"] for d in app.fs_list({})["dirs"]] == [str(inside.resolve())]
    with pytest.raises(ApiError) as e:
        app.fs_list({"path": str(outside)})
    assert e.value.status == 403
    with pytest.raises(ApiError):
        app.triage_path({"path": str(outside / "a.bin"), "mode": "local"})
    assert app.triage_path({"path": str(inside / "a.bin"), "mode": "local"})["subject"]
    with pytest.raises(ApiError):
        app.create({"sources": [str(outside)], "out": str(inside / "nuevo")})
    with pytest.raises(ApiError):
        app.create({"sources": [str(inside)], "out": str(outside / "nuevo")})
    with pytest.raises(ApiError):
        app.learn("repo", {"source": str(outside)})
    # Sin carpetas configuradas (uso local) no hay restricción.
    assert EolfiApp(str(tmp_path / "f.db"), tmp_path / "s", roots=[]).fs_list({"path": str(outside)})


def test_remote_mode_defaults_to_eolfi_folders(tmp_path):
    from eolfi.server import make_server
    httpd = make_server(str(tmp_path / "r.db"), "127.0.0.1", 0, tmp_path / "s", token="t" * 32)
    try:
        assert httpd.app.roots == [(tmp_path / "s").resolve(), Path("generated").resolve()]
    finally:
        httpd.server_close()


# ---------------------------------------------------------------- pestaña Proveedores
def test_triage_with_explicit_provider_selection(tmp_path):
    from eolfi.server import ApiError, EolfiApp
    from tests.elfgen import build_elf64
    exe = tmp_path / "x.elf"
    exe.write_bytes(build_elf64())
    app = EolfiApp(str(tmp_path / "e.db"), tmp_path / "s", roots=[])
    rep = app.triage_path({"path": str(exe), "mode": "deep", "providers": ["eolfi.triage", "eolfi.strings"]})
    assert sorted(rep["providers_run"]) == ["eolfi.strings", "eolfi.triage"]
    with pytest.raises(ApiError) as e:
        app.triage_path({"path": str(exe), "providers": ["eolfi.triage", "rm -rf"]})
    assert e.value.status == 400
    names = [p["name"] for p in app.providers({})["providers"]]
    assert "ia:eolas" in names and "ghidra.headless" in names and "eolfi.binfmt" in names


def test_panel_has_providers_tab_and_theme_choice():
    root = Path(__file__).resolve().parent.parent / "eolfi" / "web"
    html = (root / "index.html").read_text(encoding="utf-8")
    css = (root / "style.css").read_text(encoding="utf-8")
    assert 'id="open-providers"' in html and 'id="providers-view"' in html and 'id="theme"' in html
    for v in ("auto", "light", "dark"):
        assert f'value="{v}"' in html
    assert ':root[data-theme="dark"]' in css and ':root:not([data-theme="light"])' in css


# ---------------------------------------------------------------- corpus compartido (Alejandría)
def test_corpus_config_reads_shared_sources(tmp_path):
    from eolfi.corpus import library_config, run_corpus
    lib = tmp_path / "lib"
    (lib / "config").mkdir(parents=True)
    src = tmp_path / "fuente"
    src.mkdir()
    (lib / "config" / "fuentes.json").write_text(json.dumps(
        {"fuentes": [str(src), str(tmp_path / "no-existe")], "excluir_carpetas": [".git"]}), encoding="utf-8")
    cfg = library_config(lib)
    assert cfg["fuentes"] == [str(src)] and cfg["excluir_carpetas"] == [".git"]
    with pytest.raises(FileNotFoundError):        # no es una biblioteca (faltan sus scripts)
        run_corpus(str(lib), dry_run=True)
    (lib / "config" / "fuentes.json").write_text('{"fuentes": []}', encoding="utf-8")
    with pytest.raises(ValueError):
        library_config(lib)


def test_deadline_when_closed_socket_reads_as_eof(monkeypatch):
    """Linux/macOS: el socket cerrado por el vigilante del plazo se lee como b"" (no OSError como en Windows)."""
    from eolfi.sites import fetch

    f = fetch.Fetcher(delay=0, respect_robots=False, timeout=0.2)    # plazo total = 0,6 s

    class Resp:
        status = 200
        headers = type("H", (), {"items": lambda self: [("Content-Type", "text/plain")],
                                 "get_all": lambda self, k: None})()

        def __init__(self):
            self.n = 0

        def read1(self, _n):
            self.n += 1
            if self.n < 3:
                return b"x"
            time.sleep(0.7)          # el vigilante cierra el socket y la lectura devuelve fin de datos
            return b""

        def close(self):
            pass
    monkeypatch.setattr(f, "_check_url", lambda u: None)
    monkeypatch.setattr(f._opener, "open", lambda req, timeout=None: Resp())
    with pytest.raises(fetch.FetchError, match="lenta"):
        f._raw_get("http://example.invalid/lento", 10_000)
