import json
import shutil
import sys

import pytest

from eolfi.core.evidence import EvidenceStore
from eolfi.core.stix import build_stix
from eolfi.flows.compare_flow import compare
from eolfi.flows.create_flow import classify, create_project
from eolfi.flows.learn_flow import run_repo, run_web
from eolfi.flows.triage_flow import LOCAL_PROVIDERS, run_triage
from eolfi.generador import templates as tpl
from eolfi.generador.generators import generate
from eolfi.generador.spec import build_spec, palette
from eolfi.providers.binfmt import BinaryFormatProvider, ParseError
from eolfi.providers.dex import AndroidJavaProvider, parse_dex
from eolfi.providers.macho import parse_macho
from eolfi.security.resilience import _mutate
from eolfi.sites.fetch import Fetcher, FetchError, host_is_private
from eolfi.sites.webpage import PageParser, analyze_css
from tests.fixtures import build_apk, build_dex, build_macho64, build_repo, build_site


# -- Mach-O / DEX / APK -----------------------------------------------------
def test_macho_synthetic():
    info = parse_macho(build_macho64())
    s = info["slices"][0]
    assert s["headers"]["cpu"] == "arm64" and s["headers"]["filetype"] == "execute"
    assert s["headers"]["platform"] == "macos" and s["headers"]["min_os"] == "14.0.0"
    assert s["dylibs"][0]["name"] == "/usr/lib/libSystem.B.dylib"
    assert s["security"]["pie"] is True and s["security"]["stack_canary"] and s["security"]["arc"]
    assert s["sections"][0]["name"] == "__TEXT,__text"


def test_macho_provider(tmp_path):
    f = tmp_path / "a.macho"
    f.write_bytes(build_macho64())
    ops = {x["operation"] for x in BinaryFormatProvider().run(str(f))}
    assert {"macho_headers", "macho_security", "macho_dylibs", "packing_signals"} <= ops


def test_dex_and_checksum():
    d = parse_dex(build_dex())
    assert d["checksum_ok"] is True and d["counts"]["classes"] == 3
    assert "com.example.app.MainActivity" in d["class_sample"]
    assert d["top_packages"][0]["package"] == "com.example"


def test_axml_manifest_variants():
    from eolfi.providers.axml import parse_axml, summarize_manifest
    from tests.fixtures import SAMPLE_MANIFEST, build_axml
    for kw in ({}, {"utf8": True}, {"obfuscate_names": True}):
        m = summarize_manifest(parse_axml(build_axml(SAMPLE_MANIFEST, **kw)))
        assert m["package"] == "com.example.demo" and m["version_code"] == 42 and m["target_sdk"] == 34
        assert m["launcher"] == "com.example.demo.MainActivity" and m["deep_links"] == ["demo://open"]
        assert m["dangerous_permissions"] == ["CAMERA"] and m["special_permissions"] == ["SYSTEM_ALERT_WINDOW"]
        f = " ".join(m["security_findings"])
        assert "SyncService" in f and "depurable" in f and "sin cifrar" in f and "Boot" in f
        assert "Files" not in f                     # provider no exportado


def test_axml_survives_mutations():
    import random
    from eolfi.providers.axml import parse_axml
    from tests.fixtures import SAMPLE_MANIFEST, build_axml
    rng = random.Random(5)
    seed = build_axml(SAMPLE_MANIFEST)
    for _ in range(300):
        try:
            parse_axml(_mutate(seed, rng))
        except ParseError:
            pass


def test_apk_inventory(tmp_path):
    apk = build_apk(tmp_path / "x.apk")
    [f] = AndroidJavaProvider().run(str(apk))
    r = f["result"]
    assert r["kind"] == "apk" and "Flutter" in r["frameworks"]
    assert r["native_libs"] == {"arm64-v8a": ["libflutter.so", "libapp.so"]}
    assert r["dex"]["classes.dex"]["checksum_ok"] is True
    assert r["manifest"]["package"] == "com.example.demo"


@pytest.mark.parametrize("seed_fn,parser", [(build_macho64, parse_macho), (build_dex, parse_dex)])
def test_new_parsers_survive_mutations(seed_fn, parser):
    import random
    rng = random.Random(3)
    for _ in range(300):
        try:
            parser(_mutate(seed_fn(), rng))
        except ParseError:
            pass


# -- Web ----------------------------------------------------------------------
def test_web_local_site(tmp_path):
    site = build_site(tmp_path / "site")
    s = EvidenceStore(":memory:")
    rep = run_web(str(site), s)
    ev = {e["operation"]: json.loads(e["result"]) for e in s.list_evidence(rep["subject"])}
    st = ev["web_structure"]
    assert st["lang"] == "es" and st["title"] == "Demo"
    assert {p["path"] for p in st["pages"]} == {"index.html", "about.html"}
    assert ev["web_css"]["breakpoints"] == ["min-width:768px", "min-width:64rem"]
    assert "#e11d48" in ev["web_css"]["colors"] and ev["web_css"]["fonts"] == ["Inter"]
    assert ev["web_js"]["api_endpoints"] == ["/api/products", "/api/orders/{id}"]
    sm = ev["web_sourcemaps"][0]
    assert sm["app_files"] == ["src/components/Card.tsx"] and sm["npm_packages"] == ["react"]
    assert "CODIGO SECRETO" not in json.dumps(ev)          # nunca se guarda el código original
    names = {t["name"] for t in ev["web_stack"]["technologies"]}
    assert {"Next.js", "React"} <= names
    issues = " ".join(ev["web_accessibility"]["issues"])
    assert "sin atributo alt" in issues and "sin texto" in issues


def test_html_parser_tolerates_garbage():
    p = PageParser()
    p.feed("<div><p><span></div></b><script>if(a<b){}</script><h1>T</h1><<>>" + "<div>" * 5000)
    p.close()
    assert p.headings == [(1, "T")]
    assert p.nodes <= 601


def test_css_range_media():
    r = analyze_css([("x", "@media (width >= 48rem) and (width < 80rem) {a{b:c}}")])
    assert r["breakpoints"] == ["min-width:48rem", "max-width:80rem"]


def test_ssrf_guard():
    assert host_is_private("127.0.0.1") and host_is_private("10.1.2.3")
    f = Fetcher()
    f.allow_private = False                    # como si la página analizada fuera pública
    with pytest.raises(FetchError, match="anti-SSRF"):
        f._check_url("http://127.0.0.1/admin")
    with pytest.raises(FetchError, match="no soportada"):
        f._check_url("file:///etc/passwd")


# -- Repos ----------------------------------------------------------------------
def test_repo_local(tmp_path):
    repo = build_repo(tmp_path / "repo")
    s = EvidenceStore(":memory:")
    rep = run_repo(str(repo), s)
    ev = {e["operation"]: json.loads(e["result"]) for e in s.list_evidence(rep["subject"])}
    assert ev["repo_languages"]["code"][0]["language"] == "TypeScript (TSX)"
    assert ev["repo_manifests"]["package_managers"] == ["pnpm"]
    techs = {t["name"]: t for t in ev["repo_stack"]["technologies"]}
    assert techs["React"]["runtime"] is True and techs["Express"]["runtime"] is False
    bp = ev["repo_blueprint"]
    assert "Express" not in bp["stack"] and "React" in bp["stack"]
    assert bp["package_manager"] == "pnpm" and "pnpm run dev    # vite" in bp["how_to_run"]
    assert ev["repo_docs"]["license"] == "MIT" and ev["repo_docs"]["env_variables"] == ["API_URL", "DB_PASSWORD"]
    assert ev["repo_hygiene"]["possibly_sensitive_files"] == [".env"]
    assert "nunca-se-lee" not in json.dumps(ev)
    assert ev["repo_quality"]["ci"]["github_actions"][0]["actions"] == ["actions/checkout"]


def test_classify(tmp_path):
    assert classify("https://github.com/a/b") == "repo"
    assert classify("https://example.com/") == "web"
    assert classify(str(build_site(tmp_path / "s"))) == "web"
    assert classify(str(build_repo(tmp_path / "r"))) == "repo"
    assert classify("abc123") == "subject"


# -- Comparación y STIX ----------------------------------------------------------
def test_compare_versions(tmp_path):
    a, b = tmp_path / "a.elf", tmp_path / "b.elf"
    from tests.elfgen import build_elf64
    a.write_bytes(build_elf64())
    b.write_bytes(build_elf64() + b"\x00" * 64)
    s = EvidenceStore(":memory:")
    ra, rb = run_triage(str(a), s, LOCAL_PROVIDERS), run_triage(str(b), s, LOCAL_PROVIDERS)
    d = compare(s, ra["subject"], rb["subject"])
    assert "hash" in d["changed"] and d["headline"][0].startswith("Tamaño")
    assert "elf_security" in d["unchanged"]


def test_stix_bundle(tmp_path):
    s = EvidenceStore(":memory:")
    f = tmp_path / "m"
    f.write_bytes(build_macho64())
    run_triage(str(f), s, LOCAL_PROVIDERS)
    doc = build_stix(s)
    types = {o["type"] for o in doc["objects"]}
    assert {"identity", "file", "note", "grouping"} <= types
    ids = {o["id"] for o in doc["objects"]}
    for o in doc["objects"]:
        for ref in o.get("object_refs", []):
            assert ref in ids
    assert build_stix(s)["objects"][1]["id"] == doc["objects"][1]["id"]     # ids deterministas


# -- Forja ------------------------------------------------------------------------
def test_palette_ignores_transparent():
    p = palette(["#0000", "#00000080", "#e11d48", "#fff", "#111"])
    assert p["primary"] == "#e11d48" and p["text"] == "#111" and p["background"] == "#fff"


def _spec(tmp_path, target):
    s = EvidenceStore(":memory:")
    site = build_site(tmp_path / "site")
    repo = build_repo(tmp_path / "repo")
    subs = [run_web(str(site), s)["subject"], run_repo(str(repo), s)["subject"]]
    return s, subs, build_spec(s, subs, name="Mi Tienda", target=target)


def test_spec_merges_sources(tmp_path):
    _s, _subs, spec = _spec(tmp_path, "auto")
    assert spec["target"] == "next"          # la fuente usa Next.js y tiene API propia
    assert {"Hero", "Pricing", "Testimonials", "ContactForm"} <= set(spec["sections"])
    assert spec["api"]["resources"] == ["products", "orders"]
    assert spec["design"]["palette"]["primary"] == "#e11d48" and spec["design"]["font"] == "Inter"
    assert "about" in spec["pages"] and spec["conventions"]["ci"] and spec["conventions"]["typescript"]


@pytest.mark.parametrize("target,expect", [
    ("static", ["index.html", "about.html", "css/tokens.css", "tests/site.test.mjs"]),
    ("react", ["src/App.tsx", "src/components/Pricing.tsx", "src/components/ApiDemo.tsx", "src/App.test.tsx"]),
    ("vue", ["src/App.vue", "src/components/Pricing.vue", "src/router.ts", "src/App.test.ts"]),
    ("fastapi", ["app/main.py", "app/routers/products.py", "app/static/index.html", "tests/test_api.py"]),
    ("express", ["src/app.js", "src/routes/orders.js", "public/index.html", "test/api.test.js"]),
    ("svelte", ["src/App.svelte", "src/router.svelte.ts", "src/components/Pricing.svelte", "src/App.test.ts"]),
    ("next", ["app/layout.tsx", "app/page.tsx", "app/about/page.tsx", "app/api/products/[id]/route.ts",
              "components/ContactForm.tsx", "test/app.test.mjs"]),
    ("expo", ["App.tsx", "index.ts", "app.json", "src/components/Section.tsx", "src/api.ts", "__tests__/App.test.tsx"]),
    ("django", ["manage.py", "config/settings.py", "core/models.py", "core/migrations/0001_initial.py",
                "core/templates/core/home.html", "core/tests.py"]),
    ("desktop", ["main.js", "preload.js", "renderer/index.html", "renderer/js/desktop.js",
                 "test/app.test.js", "scripts/smoke.js", "package.json"]),
    ("tauri", ["src/index.html", "src-tauri/Cargo.toml", "src-tauri/src/main.rs", "src-tauri/tauri.conf.json",
               "src-tauri/capabilities/default.json", "src-tauri/icons/icon.png", "test/config.test.mjs"]),
    ("cli", ["pyproject.toml", "tests/test_cli.py"]),
    ("dotnet", ["global.json", "tests/" ]),
])
def test_generate_targets(tmp_path, target, expect):
    _s, _subs, spec = _spec(tmp_path, target)
    out = tmp_path / "out"
    files = generate(spec, out)
    for f in expect + ["README.md", "eolfi.spec.json", ".github/workflows/ci.yml"]:
        assert f in files or any(x.startswith(f) for x in files if f.endswith("/")), f
    text = "\n".join((out / f).read_text(encoding="utf-8") for f in files if not f.endswith(".png"))
    assert "CODIGO SECRETO" not in text and "Hola" not in text   # nada copiado de las fuentes
    with pytest.raises(FileExistsError):
        generate(spec, out)


def test_render_escapes_html():
    node = tpl.E("p", {}, tpl.T("title"))
    assert tpl.render_html(node, {"title": "<script>x</script>"}) == "<p>&lt;script&gt;x&lt;/script&gt;</p>"


@pytest.mark.skipif(not shutil.which("node"), reason="requiere Node.js")
def test_create_static_and_verify(tmp_path):
    s = EvidenceStore(":memory:")
    site = build_site(tmp_path / "site")
    r = create_project([str(site)], s, tmp_path / "nuevo", name="Sitio", target="static", do_verify=True)
    assert r["verification"]["ok"], r["verification"]


def test_create_verifies_by_default(tmp_path, monkeypatch):
    from eolfi.generador import verify as verify_module

    calls = []
    monkeypatch.setattr(verify_module, "verify", lambda project, target, **kw:
                        calls.append((project.resolve(), target)) or {"ok": True, "steps": []})
    site = build_site(tmp_path / "site")
    out = tmp_path / "nuevo"
    result = create_project([str(site)], EvidenceStore(":memory:"), out, target="static")
    assert calls == [(out.resolve(), "static")]
    assert result["verification"]["ok"] is True


def test_create_cli_keeps_verify_mandatory_without_flag():
    from eolfi.cli import _parser

    args = _parser().parse_args(["create", "--from", "fuente", "--out", "destino"])
    assert args.verify is True


@pytest.mark.skipif(sys.platform != "win32" and not shutil.which("python3"), reason="requiere Python")
def test_fastapi_generated_app_imports(tmp_path):
    """El backend generado se importa y responde (sin instalar nada: FastAPI ya está o se salta)."""
    fastapi = pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    _s, _subs, spec = _spec(tmp_path, "fastapi")
    out = tmp_path / "api"
    generate(spec, out)
    sys.path.insert(0, str(out))
    try:
        from fastapi.testclient import TestClient
        import importlib
        mod = importlib.import_module("app.main")
        c = TestClient(mod.app)
        assert c.get("/api/health").json() == {"ok": True, "db": "memory", "auth": False}
        assert c.post("/api/products", json={"name": "x"}).status_code == 201
        assert "<main>" in c.get("/").text
    finally:
        sys.path.remove(str(out))
        for m in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
            del sys.modules[m]
    assert fastapi


def test_arsc_resolves_and_follows_alias():
    from eolfi.providers.arsc import resolve, resolve_refs
    from tests.fixtures import build_arsc
    data = build_arsc()
    r = resolve(data, {0x7F010000, 0x7F010001, 0x7F020000})
    assert r[0x7F010000]["name"] == "string/app_name" and r[0x7F010000]["value"] == "Demo Eolfi"
    assert r[0x7F010001]["value"] == "@0x7f010000" and 0x7F020000 not in r
    out = resolve_refs({"application": {"label": "@0x7f010001"}}, data)
    assert out["@0x7f010001"] == {"name": "string/label_alias", "value": "Demo Eolfi", "alias_of": "@0x7f010000"}


def test_arsc_survives_mutations():
    import random
    from eolfi.providers.arsc import resolve
    from tests.fixtures import build_arsc
    rng = random.Random(9)
    seed = build_arsc()
    for _ in range(300):
        try:
            resolve(_mutate(seed, rng), {0x7F010000, 0x7F010001})
        except ParseError:
            pass



@pytest.mark.parametrize("target", ["fastapi", "express"])
def test_backend_sqlite_auth_files(tmp_path, target):
    _s, _subs, spec = _spec(tmp_path, target)
    spec["options"] = {"db": "sqlite", "auth": True}
    out = tmp_path / "out"
    files = generate(spec, out)
    if target == "fastapi":
        assert {"app/auth.py", "app/store.py", "tests/conftest.py"} <= set(files)
        store = (out / "app/store.py").read_text(encoding="utf-8")
        auth = (out / "app/auth.py").read_text(encoding="utf-8")
        assert "sqlite3" in store and "pbkdf2_hmac" in auth and "compare_digest" in auth
        assert "require_user" in (out / "app/routers/products.py").read_text(encoding="utf-8")
    else:
        assert {"src/auth.js", "src/store.js"} <= set(files)
        assert "node:sqlite" in (out / "src/store.js").read_text(encoding="utf-8")
        assert "timingSafeEqual" in (out / "src/auth.js").read_text(encoding="utf-8")
        assert "requireUser" in (out / "src/routes/products.js").read_text(encoding="utf-8")
    assert "data/" in (out / ".gitignore").read_text(encoding="utf-8")
    assert ".gitignore.extra" not in files and not (out / ".gitignore.extra").exists()



def test_desktop_window_is_hardened_and_multiplatform(tmp_path):
    _s, _subs, spec = _spec(tmp_path, "desktop")
    out = tmp_path / "out"
    generate(spec, out)
    main = (out / "main.js").read_text(encoding="utf-8")
    for must in ("contextIsolation: true", "sandbox: true", "nodeIntegration: false", "setWindowOpenHandler",
                 "will-navigate", "setPermissionRequestHandler", "requestSingleInstanceLock"):
        assert must in main, must
    assert "Content-Security-Policy" in (out / "renderer" / "index.html").read_text(encoding="utf-8")
    pkg = json.loads((out / "package.json").read_text(encoding="utf-8"))
    assert {"win", "mac", "linux"} <= set(pkg["build"])
    assert spec["platforms"] == ["windows", "macos", "linux"]
    ci = (out / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "windows-latest" in ci and "macos-latest" in ci and "ubuntu-latest" in ci


def test_choose_target_by_app_type():
    from collections import Counter
    from eolfi.generador.spec import _choose_target
    assert _choose_target(Counter({"App de escritorio": 3}), {}, Counter()) == "desktop"
    assert _choose_target(Counter({"Electron": 1, "React": 1}), {}, Counter()) == "desktop"
    assert _choose_target(Counter({"App móvil": 3, "Flutter": 1}), {}, Counter()) == "expo"
    assert _choose_target(Counter({"Qt": 1}), {}, Counter()) == "tauri"   # nativo ligero
    assert _choose_target(Counter({"React": 2}), {}, Counter()) == "react"


def test_pe_binary_source_creates_desktop_project(tmp_path):
    from eolfi.flows.create_flow import create_project
    from eolfi.core.evidence import EvidenceStore
    exe = tmp_path / "app.exe"
    exe.write_bytes(_build_min_pe())
    store = EvidenceStore(str(tmp_path / "e.db"))
    r = create_project([str(exe)], store, tmp_path / "nuevo", name="Mi app", do_verify=False)
    assert r["target"] == "desktop"
    assert r["spec"]["source_platforms"] == ["windows"]
    assert r["spec"]["platforms"] == ["windows", "macos", "linux"]


def _build_min_pe() -> bytes:
    import struct
    dos = bytearray(64)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 64)
    coff = struct.pack("<4sHHIIIHH", b"PE" + bytes(2), 0x8664, 0, 0, 0, 0, 240, 0x22)
    opt = bytearray(240)
    struct.pack_into("<H", opt, 0, 0x20B)
    return bytes(dos) + coff + bytes(opt)



def test_cli_dotnet_tauri_targets_and_detection(tmp_path):
    from collections import Counter
    from eolfi.generador.spec import _choose_target
    assert _choose_target(Counter({"App de consola": 4}), {}, Counter()) == "cli"
    assert _choose_target(Counter({"Typer": 1}), {}, Counter()) == "cli"
    assert _choose_target(Counter({"App de escritorio": 3, "WPF": 1}), {}, Counter()) == "dotnet"
    assert _choose_target(Counter({"App de escritorio": 3, "Tauri": 1}), {}, Counter()) == "tauri"
    assert _choose_target(Counter({"App de escritorio": 3, "Qt": 1}), {}, Counter()) == "tauri"
    for target in ("cli", "dotnet", "tauri"):
        _s, _subs, spec = _spec(tmp_path / target, target)
        out = tmp_path / target / "out"
        files = generate(spec, out)
        assert spec["platforms"] == ["windows", "macos", "linux"], target
        ci = (out / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        assert "windows-latest" in ci and "macos-latest" in ci, target
        if target == "dotnet":
            cs = next(f for f in files if f.endswith("Program.cs"))
            assert "APP_SMOKE" in (out / cs).read_text(encoding="utf-8")
        if target == "tauri":
            assert (out / "src-tauri/icons/icon.png").read_bytes()[:4] == bytes([0x89, 0x50, 0x4E, 0x47])
            conf = json.loads((out / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
            assert conf["app"]["withGlobalTauri"] is False and "default-src 'self'" in conf["app"]["security"]["csp"]


def test_console_exe_source_creates_cli_project(tmp_path):
    import struct
    from eolfi.core.evidence import EvidenceStore
    from eolfi.flows.create_flow import create_project
    pe = bytearray(_build_min_pe())
    struct.pack_into("<H", pe, 64 + 24 + 68, 3)   # subsystem = windows_cui (consola)
    exe = tmp_path / "tool.exe"
    exe.write_bytes(bytes(pe))
    r = create_project([str(exe)], EvidenceStore(str(tmp_path / "e.db")), tmp_path / "nuevo", name="Mi herramienta",
                       do_verify=False)
    assert r["target"] == "cli"


def test_next_routes_are_extracted_and_used_for_pages_and_api(tmp_path):
    """Next.js: páginas y API por convención de archivos (sin ejecutar nada) y el generador las usa."""
    from eolfi.core.evidence import EvidenceStore
    from eolfi.flows.learn_flow import run_repo
    from eolfi.generador.spec import build_spec

    r = tmp_path / "app-next"
    for rel, text in {
        "package.json": '{"name":"x","dependencies":{"next":"15.0.0","react":"19.0.0"}}',
        "next.config.ts": "export default {}",
        "app/page.tsx": "export default function P(){return null}",
        "app/login/page.tsx": "export default function L(){return null}",
        "app/(privado)/panel/page.tsx": "export default function Pn(){return null}",
        "app/api/projects/route.ts": "export async function GET(){}\nexport async function POST(){}",
        "app/api/projects/[id]/route.ts": "export const DELETE = async () => {}",
        "pages/about.tsx": "export default function A(){return null}",
        "pages/_app.tsx": "x",
    }.items():
        f = r / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    store = EvidenceStore(tmp_path / "e.db")
    try:
        rep = run_repo(str(r), store, workdir=str(tmp_path / "w"))
        routes = next(json.loads(e["result"]) for e in store.list_evidence(rep["subject"])
                      if e["operation"] == "repo_routes")
        assert routes["pages"] == ["/", "/about", "/login", "/panel"]
        assert routes["api"] == [{"path": "/api/projects", "methods": ["GET", "POST"]},
                                 {"path": "/api/projects/[id]", "methods": ["DELETE"]}]
        spec = build_spec(store, [rep["subject"]], name="x", target="next")
        assert {"login", "panel", "about"} <= set(spec["pages"])
        assert "projects" in spec["api"]["resources"]
    finally:
        store.close()


def test_next_generator_respects_observed_methods_and_auth_routes(tmp_path):
    """Crunia: PATCH (no PUT) donde la fuente lo expone y login/logout propios donde la fuente los tiene."""
    from eolfi.core.evidence import EvidenceStore
    from eolfi.flows.learn_flow import run_repo
    from eolfi.generador.generators import generate
    from eolfi.generador.spec import build_spec

    r = tmp_path / "app-next"
    for rel, text in {
        "package.json": '{"name":"x","dependencies":{"next":"15.0.0","react":"19.0.0"}}',
        "app/page.tsx": "x", "app/login/page.tsx": "x",
        "app/api/projects/route.ts": "export async function GET(){}\nexport async function POST(){}",
        "app/api/projects/[id]/route.ts": "export async function PATCH(){}\nexport async function DELETE(){}",
        "app/api/auth/login/route.ts": "export async function POST(){}",
        "app/api/auth/logout/route.ts": "export async function GET(){}\nexport async function POST(){}",
    }.items():
        f = r / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    store = EvidenceStore(tmp_path / "e.db")
    try:
        rep = run_repo(str(r), store, workdir=str(tmp_path / "w"))
        spec = build_spec(store, [rep["subject"]], name="x", target="next")
        spec["options"] = {"db": "memory", "auth": False}
        assert spec["api"]["observed_methods"]["/api/projects/[id]"] == ["DELETE", "PATCH"]
        assert spec["api"]["auth_endpoints"] == ["/api/auth/login", "/api/auth/logout"]
        out = tmp_path / "gen"
        generate(spec, out)
        item = (out / "app/api/projects/[id]/route.ts").read_text(encoding="utf-8")
        assert "export async function PATCH(" in item and "function PUT(" not in item
        logout = (out / "app/api/auth/logout/route.ts").read_text(encoding="utf-8")
        assert "export function GET()" in logout and "export function POST()" in logout
        login = (out / "app/api/auth/login/route.ts").read_text(encoding="utf-8")
        assert "status: 401" in login and "status: 503" in login
        test = (out / "test/app.test.mjs").read_text(encoding="utf-8")
        assert 'json("PATCH"' in test and "inicio y cierre de sesión" in test and "{{" not in test
        assert any("PENDIENTE" in n for n in spec["notes"])
        # Sin rutas de autenticación ni --auth: no se generan.
        spec2 = build_spec(store, [rep["subject"]], name="y", target="next")
        spec2["api"]["auth_endpoints"] = []
        spec2["options"] = {"db": "memory", "auth": False}
        generate(spec2, tmp_path / "gen2")
        assert not (tmp_path / "gen2" / "app/api/auth").exists()
    finally:
        store.close()
