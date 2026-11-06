"""Fase A del plan de mejoras (2026-11-05): regresiones de los fallos de seguridad y bloqueos."""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

GIT = shutil.which("git")


def _git(cwd, *args, env=None):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env, check=True)


@pytest.mark.skipif(not GIT, reason="git no está instalado")
def test_analyzing_hostile_repo_never_runs_its_programs(tmp_path):
    """A14: un .git/config con log.showSignature + gpg.program no debe ejecutar nada al analizar."""
    from eolfi.sites.repo import analyze_repo

    repo = tmp_path / "hostil"
    repo.mkdir()
    marker = tmp_path / "pwned.txt"
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_AUTHOR_NAME="x", GIT_AUTHOR_EMAIL="x@x", GIT_COMMITTER_NAME="x", GIT_COMMITTER_EMAIL="x@x")
    _git(repo, "init", "-q", env=env)
    (repo / "a.txt").write_text("hola", encoding="utf-8")
    _git(repo, "add", "a.txt", env=env)
    _git(repo, "commit", "-q", "-m", "inicio", env=env)
    # Commit con cabecera gpgsig (firma falsa) para que «git log» intente verificarla.
    tree = _git(repo, "rev-parse", "HEAD^{tree}", env=env).stdout.strip()
    parent = _git(repo, "rev-parse", "HEAD", env=env).stdout.strip()
    body = (f"tree {tree}\nparent {parent}\nauthor x <x@x> 0 +0000\ncommitter x <x@x> 0 +0000\n"
            "gpgsig -----BEGIN PGP SIGNATURE-----\n \n -----END PGP SIGNATURE-----\n\nfirmado\n")
    # Bytes, no texto: en Windows el modo texto convertiría \n en \r\n y el commit quedaría corrupto.
    sha = subprocess.run(["git", "-C", str(repo), "hash-object", "-t", "commit", "-w", "--literally", "--stdin"],
                         input=body.encode(), capture_output=True, env=env, check=True).stdout.decode().strip()
    _git(repo, "update-ref", "HEAD", sha, env=env)
    # Programa «malicioso» que deja una marca si alguien lo ejecuta.
    if os.name == "nt":
        evil = tmp_path / "evil.bat"
        evil.write_text(f'@echo off\r\necho pwned> "{marker}"\r\n', encoding="utf-8")
    else:
        evil = tmp_path / "evil.sh"
        evil.write_text(f'#!/bin/sh\necho pwned > "{marker}"\n', encoding="utf-8")
        evil.chmod(0o755)
    cfg = repo / ".git" / "config"
    cfg.write_text(cfg.read_text(encoding="utf-8") + "[log]\n\tshowSignature = true\n[gpg]\n"
                   f"\tprogram = {evil.as_posix()}\n[core]\n\tfsmonitor = {evil.as_posix()}\n"
                   f"\tpager = {evil.as_posix()}\n", encoding="utf-8")
    _subject, findings = analyze_repo(str(repo))
    assert not marker.exists(), "git ejecutó un programa del repo analizado"
    git_info = next((f for f in findings if f["operation"] == "repo_git"), None)
    # Si git informa del commit, tiene que ser el del repositorio (antes la aserción acababa en «or True»).
    assert git_info is None or not git_info["result"].get("head") or git_info["result"]["head"].startswith(sha[:7])


def test_safe_git_env_drops_user_identity():
    from eolfi.sites.repo import SAFE_GIT_CONFIG, safe_git_env

    os.environ["SSH_AUTH_SOCK"] = "/tmp/agente"
    try:
        env = safe_git_env()
    finally:
        os.environ.pop("SSH_AUTH_SOCK", None)
    assert "SSH_AUTH_SOCK" not in env and env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert "IdentityAgent=none" in env["GIT_SSH_COMMAND"]
    assert "gpg.program=false" in SAFE_GIT_CONFIG and "log.showSignature=false" in SAFE_GIT_CONFIG


def test_overwrite_detected_when_source_given_by_subject_name(tmp_path):
    """A18: «Alejandria» (objetivo ya analizado) apunta a la misma carpeta que el destino."""
    from eolfi.core.evidence import EvidenceStore
    from eolfi.flows.create_flow import OverwriteSourceError, create_project
    from eolfi.flows.learn_flow import run_repo
    from tests.fixtures import build_repo

    repo = Path(build_repo(tmp_path / "MiBiblio"))
    (repo / "mio.txt").write_text("original", encoding="utf-8")
    store = EvidenceStore(str(tmp_path / "e.db"))
    run_repo(str(repo), store)
    with pytest.raises(OverwriteSourceError):
        create_project(["MiBiblio"], store, repo, name="X", target="static")
    r = create_project(["MiBiblio"], store, repo, name="X", target="static", force=True)
    assert r.get("backup") and (Path(r["backup"]) / "mio.txt").read_text(encoding="utf-8") == "original"


def test_forced_write_on_any_nonempty_folder_makes_backup(tmp_path):
    from eolfi.core.evidence import EvidenceStore
    from eolfi.flows.create_flow import create_project
    from tests.fixtures import build_site

    site = Path(build_site(tmp_path / "site"))
    out = tmp_path / "otra"
    out.mkdir()
    (out / "conftest.py").write_text("raise SystemExit('no debe ejecutarse')", encoding="utf-8")
    r = create_project([str(site)], EvidenceStore(str(tmp_path / "e.db")), out, name="Y", target="static", force=True)
    assert r.get("backup")


def test_title_with_colon_is_not_a_path(tmp_path):
    from eolfi.core.evidence import EvidenceStore
    from eolfi.flows.create_flow import create_project
    from tests.fixtures import build_site

    site = Path(build_site(tmp_path / "s"))
    r = create_project([str(site)], EvidenceStore(str(tmp_path / "e.db")), tmp_path / "o", name="Tienda: precios",
                       target="static")
    assert r["spec"]["title"].startswith("Tienda")


def test_corpus_command_never_contains_external_data(tmp_path, monkeypatch):
    """M40: rutas con comillas tipográficas no pueden inyectar código en PowerShell."""
    import json as _json
    import subprocess as sp

    from eolfi import corpus

    lib = tmp_path / "bib’; calc; ‘"
    (lib / "scripts").mkdir(parents=True)
    (lib / "config").mkdir()
    (lib / "scripts" / "Organizar-Corpus.ps1").write_text("", encoding="utf-8")
    src = tmp_path / "fuente’ ; Remove-Item x ; ‘"
    src.mkdir()
    (lib / "config" / "fuentes.json").write_text(_json.dumps({"fuentes": [str(src)]}), encoding="utf-8")
    seen = {}
    monkeypatch.setattr(corpus.shutil, "which", lambda name: "pwsh")
    monkeypatch.setattr(sp, "call", lambda args, env=None: seen.update(args=args, env=env) or 0)
    assert corpus.run_corpus(str(lib), dry_run=True) == 0
    command = seen["args"][-1]
    assert "’" not in command and "‘" not in command and "calc" not in command and "Remove-Item" not in command
    data = _json.loads(seen["env"]["EOLFI_CORPUS_ARGS"])
    assert data["sources"] == [str(src)] and data["dryRun"] is True


def test_verify_kills_whole_process_tree_on_timeout(tmp_path):
    """A9: un nieto colgado con las tuberías abiertas no debe bloquear verify."""
    from eolfi.generador.verify import _run

    child = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); time.sleep(60)"
    t = time.time()
    r = _run([sys.executable, "-c", child], tmp_path, timeout=2)
    assert r["exit"] is None and r["tail"] == "timeout"
    assert time.time() - t < 20


def test_sandbox_env_hides_user_profile(tmp_path):
    """A10: el código escrito por la IA no ve la carpeta personal real."""
    from eolfi.generador.verify import sandbox_env

    env = sandbox_env(tmp_path / "home")
    real = str(Path.home())
    for k in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
        assert env[k].startswith(str(tmp_path)), k
    assert env["HOME"] != real and "ANTHROPIC_API_KEY" not in env
    assert env["npm_config_cache"]   # las cachés de paquetes sí se comparten


def test_slow_header_server_respects_total_deadline():
    """A17: un servidor que envía la cabecera byte a byte no puede alargar la petición más allá del plazo."""
    import socket
    import threading

    from eolfi.sites.fetch import Fetcher

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def serve():
        conn, _ = srv.accept()
        try:
            conn.recv(4096)
            for ch in b"HTTP/1.1 200 OK\r\nX-Lento: " + b"a" * 200:
                conn.sendall(bytes([ch]))
                time.sleep(0.05)
        except OSError:
            pass
        finally:
            conn.close()

    threading.Thread(target=serve, daemon=True).start()
    f = Fetcher(delay=0, respect_robots=False, timeout=0.5)   # plazo total = 1,5 s
    t = time.time()
    try:
        r = f._raw_get(f"http://127.0.0.1:{port}/", 1000)
        assert r.error or r.status is None
    except Exception:  # noqa: BLE001 — también vale un error explícito
        pass
    assert time.time() - t < 5, "la petición superó el plazo total"
    srv.close()


def test_hostile_text_inputs_are_linear():
    """A15/A16: miles de saltos de línea o guiones no disparan regex cuadráticas."""
    from eolfi.sites import repo
    from eolfi.sites.webpage import analyze_css, analyze_js

    t = time.time()
    analyze_js([("a.js", "\n" * 200_000 + "x")])
    analyze_css([("a.css", "-" * 2_000_000)])
    assert repo.parse_go_mod("\n" * 200_000 + "require github.com/spf13/cobra v1.8.0\n")[0] == {"github.com/spf13/cobra"}
    assert time.time() - t < 3


def _find_chunk(data: bytes, ctype: int, start: int = 0) -> int:
    import struct
    for off in range(start, len(data) - 8, 4):
        t, h, size = struct.unpack_from("<HHI", data, off)
        if t == ctype and h >= 20 and off + size <= len(data):
            return off
    raise AssertionError("bloque no encontrado")


def test_arsc_type_chunk_index_must_fit_in_chunk():
    """A5: un «count» enorme en un bloque de tipo no puede leer fuera del bloque ni iterar sin fin."""
    import struct

    from eolfi.providers import arsc
    from eolfi.providers.binfmt import ParseError
    from tests.fixtures import build_arsc

    data = bytearray(build_arsc())
    ok = arsc.resolve(bytes(data), [0x7F010000])
    off = _find_chunk(bytes(data), 0x0201)
    struct.pack_into("<I", data, off + 12, 0x7FFFFFFF)
    t = time.time()
    with pytest.raises(ParseError):
        arsc.resolve(bytes(data), [0x7F010000])
    assert time.time() - t < 1 and isinstance(ok, dict)


def test_string_pool_offsets_table_bounds():
    """A6: la tabla de desplazamientos no puede solaparse con las cadenas ni salirse del pool."""
    import struct

    from eolfi.providers.axml import _string_pool
    from eolfi.providers.binfmt import ParseError, Reader

    # Pool con 3 cadenas declaradas pero strings_start justo tras la cabecera (tabla solapada).
    body = struct.pack("<HHIIIIII", 0x0001, 28, 28 + 16, 3, 0, 0, 28, 0) + b"\x00" * 16
    with pytest.raises(ParseError):
        _string_pool(Reader(body), 0)
    with pytest.raises(ParseError):
        _string_pool(Reader(body), 0, limit=2)   # presupuesto global agotado


def test_manifest_typed_value_wins_over_raw_text():
    """A7: debuggable con texto «false» y valor tipado true es true, y se avisa de la manipulación."""
    from eolfi.providers.axml import _value

    mm: list[str] = []
    assert _value(0x12, 0xFFFFFFFF, 0, ["false"], mm, "debuggable") is True
    assert mm and "debuggable" in mm[0]
    mm2: list[str] = []
    assert _value(0x10, 42, 0, ["42"], mm2, "versionCode") == 42 and not mm2   # raw coherente: sin aviso
    assert _value(0x03, 0, 0, ["com.x"], mm2) == "com.x" and not mm2


def test_external_tool_timeout_kills_tree():
    """A8: al agotar el plazo, los nietos del lanzador también mueren y no bloquean."""
    from eolfi.providers.external import run_tree

    child = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); time.sleep(60)"
    t = time.time()
    with pytest.raises(subprocess.TimeoutExpired):
        run_tree([sys.executable, "-c", child], 2)
    assert time.time() - t < 20


def test_cli_create_db_flag_does_not_replace_evidence_store(tmp_path, monkeypatch):
    """Servidor A1: «create --db sqlite» elige la persistencia del backend, no la base de evidencias."""
    from eolfi import cli
    from tests.fixtures import build_site

    site = Path(build_site(tmp_path / "s"))
    monkeypatch.chdir(tmp_path)
    evid = tmp_path / "ev.db"
    rc = cli.main(["--db", str(evid), "create", "--from", str(site), "--out", str(tmp_path / "api"),
                   "--target", "fastapi", "--db", "sqlite"])
    assert rc in (0, None)
    assert evid.exists() and not (tmp_path / "sqlite").exists()
    assert "sqlite3" in (tmp_path / "api" / "app" / "main.py").read_text(encoding="utf-8") or \
        any("sqlite" in p.read_text(encoding="utf-8", errors="ignore") for p in (tmp_path / "api").rglob("*.py"))


def test_export_import_roundtrip_with_list_result(tmp_path):
    """Un paquete exportado por Eolfi se puede volver a importar aunque algún resultado sea una lista."""
    from eolfi.core.evidence import EvidenceStore
    from eolfi.core.models import Authority, Confidence, Evidence

    a = EvidenceStore(str(tmp_path / "a.db"))
    a.add_evidence(Evidence(subject="s" * 64, provider="t", provider_version="1", operation="web_sourcemaps",
                            params={}, result=[{"map": "x"}], authority=list(Authority)[0],
                            confidence=list(Confidence)[0]))
    a.export_package(tmp_path / "p.json")
    b = EvidenceStore(str(tmp_path / "b.db"))
    assert b.import_package(tmp_path / "p.json") == 1


def _gen(tmp_path, target, **kw):
    from eolfi.core.evidence import EvidenceStore
    from eolfi.flows.create_flow import create_project
    from tests.fixtures import build_site

    site = Path(build_site(tmp_path / "site"))
    out = tmp_path / target
    create_project([str(site)], EvidenceStore(str(tmp_path / "e.db")), out, target=target, do_verify=False, **kw)
    return out


@pytest.mark.parametrize("target,path,needle", [
    ("static", "index.html", 'http-equiv="Content-Security-Policy"'),
    ("static", "scripts/serve.mjs", "X-Content-Type-Options"),
    ("react", "vite.config.ts", "cspMeta()"),
    ("vue", "vite.config.ts", "preview: { headers: SECURITY_HEADERS }"),
    ("svelte", "vite.config.ts", "cspMeta()"),
    ("next", "next.config.ts", "frame-ancestors 'none'"),
    ("fastapi", "app/main.py", "@app.middleware(\"http\")"),
    ("express", "src/app.js", "X-Content-Type-Options"),
])
def test_web_targets_send_security_headers(tmp_path, target, path, needle):
    """A11: todos los destinos web llevan CSP, nosniff y compañía."""
    out = _gen(tmp_path, target, name="Demo")
    assert needle in (out / path).read_text(encoding="utf-8")


def test_express_answers_json_errors(tmp_path):
    """M30: un JSON mal formado devuelve JSON, no la página HTML con la traza."""
    src = (_gen(tmp_path, "express", name="Demo") / "src" / "app.js").read_text(encoding="utf-8")
    assert "app.use((err, _req, res, _next)" in src and "JSON inválido" in src


def test_auth_limits_per_ip_and_bounds_memory(tmp_path):
    """M28: límite por IP en /register y /login y mapas con tope."""
    py = (_gen(tmp_path / "a", "fastapi", name="Demo", auth=True) / "app" / "auth.py").read_text(encoding="utf-8")
    js = (_gen(tmp_path / "b", "express", name="Demo", auth=True) / "src" / "auth.js").read_text(encoding="utf-8")
    assert "dependencies=[Depends(limit_ip)]" in py and "MAX_TRACKED" in py
    assert 'authRouter.post("/login", limitIp' in js and "MAX_TRACKED" in js


def test_django_is_secure_by_default(tmp_path):
    """M29: sin variables, el servidor de producción arranca sin DEBUG y con SECURE_*."""
    out = _gen(tmp_path, "django", name="Demo")
    settings = (out / "config" / "settings.py").read_text(encoding="utf-8")
    assert 'os.environ.get("DJANGO_DEBUG", "0")' in settings and "SECURE_HSTS_SECONDS" in settings
    assert 'setdefault("DJANGO_DEBUG", "1")' in (out / "manage.py").read_text(encoding="utf-8")


def test_package_names_never_shadow_stdlib_or_keywords():
    """A12."""
    from eolfi.generador.generators_cli import _pkg
    from eolfi.generador.generators_dotnet import project_name

    assert _pkg("class") == "app_class" and _pkg("json") == "app_json" and _pkg("mi tienda") == "mi_tienda"
    assert project_name("system") == "AppSystem" and project_name("avalonia") == "AppAvalonia"


@pytest.mark.parametrize("colors", [["#fde047"], ["#a3e635", "#facc15"], ["#22d3ee"], [], ["#111111", "#4f46e5"]])
def test_palette_meets_wcag_contrast(colors):
    """A13: texto de botones ≥ 4,5:1, primario ≥ 4,5:1 sobre el fondo, foco ≥ 3:1."""
    from eolfi.generador.spec import contrast, palette

    p = palette(colors)
    assert contrast(p["on_primary"], p["primary"]) >= 4.5
    assert contrast(p["primary"], p["background"]) >= 4.5
    assert contrast(p["accent"], p["background"]) >= 3.0
    assert contrast(p["text"], p["background"]) >= 4.5
