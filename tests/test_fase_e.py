"""Fase E del plan de mejoras (2026-11-05): mejoras rápidas y de mucho valor."""
import json
import time

import pytest

from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Authority, Confidence, Evidence, Incognita
from tests.elfgen import build_elf64


# -- pestaña «Trabajos» ---------------------------------------------------------------------
def test_job_history_survives_restart_and_can_be_repeated(tmp_path):
    from eolfi.server import EolfiApp

    db, samples = str(tmp_path / "e.db"), tmp_path / "s"
    a = EolfiApp(db, samples)
    a.create = lambda body: {"subject": "proyecto:x", "name": body["name"]}
    jid = a.start_job({"kind": "create", "body": {"name": "Tienda"}})["job_id"]
    for _ in range(100):
        if a.jobs[jid]["status"] == "done":
            break
        time.sleep(0.02)
    # Sin espera extra: «done» solo se publica cuando el trabajo ya está guardado (antes era intermitente).
    b = EolfiApp(db, samples)                       # «reinicio» del servidor
    b.create = a.create
    listed = b.job_status({})["jobs"]
    assert listed[0]["id"] == jid and listed[0]["stored"] and listed[0]["subject"] == "proyecto:x"
    new = b.repeat_job(jid)["job_id"]
    for _ in range(100):
        if b.jobs[new]["status"] == "done":
            break
        time.sleep(0.02)
    assert b.jobs[new]["result"]["name"] == "Tienda"


# -- informes ---------------------------------------------------------------------------------
def _store_with_hostile_subject(tmp_path):
    s = EvidenceStore(str(tmp_path / "e.db"))
    sub = "a" * 64
    s.add_evidence(Evidence(subject=sub, provider="p", provider_version="1", operation="android_manifest", params={},
                            result={"security_findings": ["<script>alert(1)</script>"]},
                            authority=list(Authority)[0], confidence=list(Confidence)[0]))
    s.add_incognita(Incognita(subject=sub, question="¿<img onerror=x>?", severity="high"))
    return s, sub


def test_report_html_escapes_and_markdown(tmp_path):
    from eolfi.core.report import build_report, fails, render_html, render_markdown

    s, sub = _store_with_hostile_subject(tmp_path)
    r = build_report(s, sub, ["<b>nombre</b>"])
    h = render_html(r)
    assert "<script>alert" not in h and "&lt;script&gt;" in h and "<img onerror" not in h
    assert "default-src 'none'" in h and "<script" not in h.lower()
    md = render_markdown(r)
    assert "## Incógnitas abiertas (1" in md and "**high**" in md
    assert fails(r, "high") and fails(r, "medium") and not fails(r, "critical") and not fails(r, None)


def test_cli_report_fail_on_exit_code(tmp_path, monkeypatch):
    from eolfi import cli

    s, sub = _store_with_hostile_subject(tmp_path)
    s.close()
    out = tmp_path / "r.html"
    assert cli.main(["--db", str(tmp_path / "e.db"), "report", sub, "--out", str(out)]) in (0, None)
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert cli.main(["--db", str(tmp_path / "e.db"), "report", sub, "--format", "md", "--out", str(out),
                     "--fail-on", "high"]) == 1


# -- CSP en Django ------------------------------------------------------------------------------
def test_django_target_has_security_headers_middleware(tmp_path):
    from eolfi.flows.create_flow import create_project
    from tests.fixtures import build_site

    site = build_site(tmp_path / "s")
    out = tmp_path / "dj"
    create_project([str(site)], EvidenceStore(str(tmp_path / "e.db")), out, name="X", target="django", do_verify=False)
    assert "core.middleware.SecurityHeadersMiddleware" in (out / "config" / "settings.py").read_text(encoding="utf-8")
    mw = (out / "core" / "middleware.py").read_text(encoding="utf-8")
    assert "frame-ancestors 'none'" in mw and "nosniff" in mw
    assert "test_security_headers" in (out / "core" / "tests.py").read_text(encoding="utf-8")


# -- ParseBudget y proveedores aislados -----------------------------------------------------------
def test_parse_budget_stops_runaway_reads():
    from eolfi.providers.binfmt import ParseError, Reader, parse_budget

    r = Reader(b"\x00" * 1024)
    with parse_budget(max_bytes=100, seconds=10):
        with pytest.raises(ParseError, match="presupuesto"):
            for _ in range(200):
                r.u32(0)
    for _ in range(200):   # fuera del bloque, sin presupuesto
        r.u32(0)


def test_parse_budget_deadline():
    from eolfi.providers.binfmt import ParseError, Reader, parse_budget

    r = Reader(b"\x00" * 16)
    with parse_budget(max_bytes=10**12, seconds=-1):   # ya vencido (el reloj de Windows va a saltos de ~15 ms)
        with pytest.raises(ParseError, match="tiempo"):
            for _ in range(5000):
                r.u8(0)


def test_isolated_local_providers_give_the_same_result(tmp_path):
    from eolfi.flows import triage_flow as tf

    f = tmp_path / "a.elf"
    f.write_bytes(build_elf64())
    a, b = EvidenceStore(str(tmp_path / "a.db")), EvidenceStore(str(tmp_path / "b.db"))
    ra = tf.run_triage(str(f), a, tf.LOCAL_PROVIDERS)
    rb = tf.run_triage(str(f), b, tf.LOCAL_PROVIDERS, isolate=True)
    assert ra["providers_run"] == rb["providers_run"] and not rb["providers_failed"]
    ops = lambda s: sorted((e["operation"], e["result"]) for e in s.list_evidence())  # noqa: E731
    assert ops(a) == ops(b)


def test_isolated_runner_refuses_foreign_modules(tmp_path):
    import subprocess
    import sys

    f = tmp_path / "x"
    f.write_bytes(b"x")
    p = subprocess.run([sys.executable, "-m", "eolfi.providers.isolated", "os", "system", str(f)],
                       capture_output=True, text=True)
    assert p.returncode == 2 and "no permitido" in p.stdout


def test_isolated_provider_crash_is_contained(tmp_path, monkeypatch):
    """Un proveedor que muere en el subproceso queda como «falló», no tumba el triaje."""
    from eolfi.flows import triage_flow as tf

    f = tmp_path / "a.elf"
    f.write_bytes(build_elf64())
    monkeypatch.setattr(tf, "_run_isolated", lambda prov, path, timeout=180.0: (_ for _ in ()).throw(
        RuntimeError("el proceso aislado falló: MemoryError")))
    s = EvidenceStore(str(tmp_path / "e.db"))
    r = tf.run_triage(str(f), s, tf.LOCAL_PROVIDERS, isolate=True)
    assert set(r["providers_failed"]) == {p.name for p in tf.LOCAL_PROVIDERS}


# -- grupo 3: puente ----------------------------------------------------------------------------------
def test_bridge_compare_and_selftest_validation(tmp_path):
    from eolfi.server import ApiError, EolfiApp

    a = EolfiApp(str(tmp_path / "e.db"), tmp_path / "s")
    for body in ({"providers": ["chatgpt"], "prompt": "x"}, {"providers": ["chatgpt", "inventado"], "prompt": "x"},
                 {"providers": ["chatgpt", "lechat"], "prompt": " "},
                 {"providers": ["chatgpt", "lechat"], "prompt": "x", "conversation": "../otra"}):
        with pytest.raises(ApiError) as e:
            a.bridge_compare(body)
        assert e.value.status == 400
    with pytest.raises(ApiError):
        a.bridge_selftest({"provider": "inventado"})


def test_new_web_chat_presets():
    from eolfi.generador.llm import PRESETS, choose_web_site

    assert {"chatgpt-web", "copilot-web", "lechat-web"} <= set(PRESETS)
    st = {"chatgpt": {"ok": True, "signedIn": True}, "gemini": {"ok": False}}
    assert choose_web_site(st) == "chatgpt"


# -- Copilot por VS Code -----------------------------------------------------------------------------
@pytest.fixture
def fake_vscode_bridge(tmp_path, monkeypatch):
    import http.server
    import json as _j
    import threading

    seen = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj, status=200):
            body = _j.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._send({"ok": True, "vscode": "1.145.0", "models": 2})

        def do_POST(self):
            body = _j.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, body, self.headers.get("Authorization")))
            if self.path == "/v1/chat":
                return self._send({"text": '```json\n{"summary": "hecho", "files": [], "notes": []}\n```',
                                   "model": {"id": "gpt-x", "name": "GPT X"}})
            return self._send({"ok": True, "path": self.path})

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    f = tmp_path / "vscode-bridge.json"
    f.write_text(_j.dumps({"url": f"http://127.0.0.1:{srv.server_address[1]}", "token": "v" * 64, "pid": 1}),
                 encoding="utf-8")
    monkeypatch.setenv("EOLFI_VSCODE_BRIDGE_FILE", str(f))
    yield seen
    srv.shutdown()
    srv.server_close()


def test_copilot_vscode_provider(fake_vscode_bridge, monkeypatch):
    from eolfi.generador.llm import make_provider, probe

    assert probe("copilot-vscode")["available"] is True
    p = make_provider("copilot-vscode")
    r = p.complete("Eres útil.", [{"role": "user", "content": "Haz X"}], {"type": "object"}, "high")
    assert r.data["summary"] == "hecho" and p.model == "GPT X"
    path, body, auth = fake_vscode_bridge[-1]
    assert path == "/v1/chat" and auth == "Bearer " + "v" * 64
    assert body["workspace_tools"] == "read" and body["messages"][0]["role"] == "system"
    monkeypatch.setenv("EOLFI_COPILOT_WORKSPACE", "off")
    p2 = make_provider("copilot-vscode")
    p2.complete("s", [{"role": "user", "content": "x"}], {"type": "object"}, "high")
    assert "workspace_tools" not in fake_vscode_bridge[-1][1]


def test_vscode_action_client(fake_vscode_bridge):
    from eolfi.generador.llm import LLMError
    from eolfi.vscode_tools import vscode_action

    assert vscode_action("open", path="README.md", line=3)["path"] == "/v1/workspace/open"
    assert vscode_action("tool", name="runTests", input={})["path"] == "/v1/tool"
    with pytest.raises(LLMError):
        vscode_action("borrar_todo")


def test_vscode_bridge_file_must_be_loopback(tmp_path, monkeypatch):
    import json as _j

    from eolfi.generador.llm import LLMError, read_vscode_bridge

    f = tmp_path / "b.json"
    f.write_text(_j.dumps({"url": "http://127.0.0.1:80@evil.com/", "token": "v" * 64}), encoding="utf-8")
    monkeypatch.setenv("EOLFI_VSCODE_BRIDGE_FILE", str(f))
    with pytest.raises(LLMError):
        read_vscode_bridge()


def test_copilot_auto_mode_journals_and_rollback(fake_vscode_bridge, monkeypatch):
    """Modo «auto»: escribe sin preguntar archivo por archivo, guarda los diarios y deshace si no queda en verde."""
    import json as _j

    from eolfi.generador import llm

    monkeypatch.setenv("EOLFI_COPILOT_WORKSPACE", "auto")
    p = llm.make_provider("copilot-vscode")
    assert p.workspace_tools is True and p.auto_approve is True

    real_post = llm._post

    def fake_post(url, body, headers, timeout, retries=llm.RETRIES, sleep=None):
        r = real_post(url, body, headers, timeout, retries=retries, sleep=sleep)
        if url.endswith("/v1/chat"):
            r = {**r, "journal": "J9", "written": 2}
        return r
    monkeypatch.setattr(llm, "_post", fake_post)
    p.complete("s", [{"role": "user", "content": "x"}], {"type": "object"}, "high")
    assert fake_vscode_bridge[-1][1]["auto_approve"] is True and p.journals == ["J9"]
    p.rollback()
    assert fake_vscode_bridge[-1][0] == "/v1/workspace/undo" and fake_vscode_bridge[-1][1] == {"journal": "J9"}
    assert p.journals == []


def test_assist_rolls_back_provider_when_not_green(tmp_path):
    from eolfi.generador.assist import _rollback_provider

    class P:
        name = "copilot-vscode"
        called = 0

        def rollback(self):
            P.called += 1
            return ["a.py"]
    logs = []
    _rollback_provider(P(), logs.append)
    assert P.called == 1 and "deshechos 1 archivos" in logs[0]
    _rollback_provider(object(), logs.append)   # proveedores sin rollback: nada


# -- Vinculación de la extensión de VS Code y VS Code integrado ------------------------------------
def test_vscode_client_pairing_and_revocation(tmp_path):
    import json as _j
    import threading

    from eolfi.server import make_server
    from tests.test_server import req

    httpd = make_server(str(tmp_path / "e.db"), "127.0.0.1", 0, tmp_path / "s")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    X = {"X-Eolfi": "1"}
    try:
        # Un cliente no puede pedirse un código a sí mismo; sin token, 401.
        assert req(port, "POST", "/api/clients/pair", "{}", {**X, "X-Eolfi-Client": "vscode"})[0] in (401, 403)
        assert req(port, "GET", "/api/health", None, {"X-Eolfi-Client": "vscode"})[0] == 401
        st, body, _ = req(port, "POST", "/api/clients/pair", "{}", X)       # el panel genera el código
        code = body["code"]
        assert st == 200 and len(code) == 6
        bad = req(port, "POST", "/api/clients/token", _j.dumps({"code": "000000" if code != "000000" else "111111"}),
                  {**X, "X-Eolfi-Client": "vscode"})
        assert bad[0] == 403
        st, tok, _ = req(port, "POST", "/api/clients/token", _j.dumps({"code": code, "name": "VS Code prueba"}),
                         {**X, "X-Eolfi-Client": "vscode"})
        assert st == 200 and tok["token"].startswith("ect_")
        auth = {"X-Eolfi-Client": "vscode", "Authorization": f"Bearer {tok['token']}"}
        assert req(port, "GET", "/api/health", None, auth)[0] == 200
        # El código era de un solo uso.
        assert req(port, "POST", "/api/clients/token", _j.dumps({"code": code}), {**X, "X-Eolfi-Client": "vscode"})[0] == 403
        clients = req(port, "GET", "/api/clients")[1]["clients"]
        assert clients[0]["name"] == "VS Code prueba" and clients[0]["last_used"]
        assert req(port, "DELETE", f"/api/clients?id={clients[0]['id']}", None, X)[1]["revoked"] == 1
        assert req(port, "GET", "/api/health", None, auth)[0] == 401
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_vscode_web_requires_license(tmp_path, monkeypatch):
    from eolfi import vscode_web
    from eolfi.server import ApiError, EolfiApp

    monkeypatch.setattr(vscode_web, "STATE_DIR", tmp_path / "home")
    app = EolfiApp(str(tmp_path / "e.db"), tmp_path / "s")
    st = app.vscode_status({})
    assert st["license_accepted"] is False and st["running"] is False and st["license_url"].startswith("https://")
    if st["available"]:
        with pytest.raises(ApiError) as e:
            app.vscode_start({"folder": str(tmp_path)})
        assert e.value.status == 412 and e.value.extra.get("needs_license")
    with pytest.raises(ApiError):
        app.vscode_start({"folder": str(tmp_path / "no-existe")})


def test_build_vsix_empaqueta_la_extension(tmp_path):
    import zipfile
    from pathlib import Path

    from eolfi.cli import build_vsix

    ext = Path(__file__).resolve().parents[1] / "eolfi" / "vscode-bridge"
    vsix = build_vsix(ext, tmp_path)
    names = zipfile.ZipFile(vsix).namelist()
    assert {"extension.vsixmanifest", "[Content_Types].xml", "extension/package.json",
            "extension/extension.js", "extension/chat.js"} <= set(names)
    assert not any("/test/" in n for n in names)
    manifest = zipfile.ZipFile(vsix).read("extension.vsixmanifest").decode()
    assert 'Publisher="eolfi"' in manifest and "Microsoft.VisualStudio.Code.Manifest" in manifest


def test_vscode_login_no_muestra_el_codigo(monkeypatch, capsys):
    import io
    import json
    import os

    from eolfi import cli

    opened = []

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=10):
        assert req.full_url.endswith("/api/clients/pair") and req.get_header("X-eolfi") == "1"
        return R(json.dumps({"code": "424242", "expires_in": 600}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(os, "startfile", lambda link: opened.append(link), raising=False)
    assert cli._vscode_login() == 0
    assert opened == ["vscode://eolfi.eolfi-vscode-bridge/login?code=424242"]
    out = capsys.readouterr()
    assert "424242" not in out.out + out.err


def test_licencia_propietaria():
    import zipfile
    from pathlib import Path

    import eolfi
    from eolfi.cli import build_vsix

    root = Path(__file__).resolve().parents[1]
    lic = (root / "LICENSE").read_text(encoding="utf-8")
    assert "Copyright (c) 2026 CeltiaIA (celtiaia.com)." in lic
    assert "Todos los derechos reservados" in lic
    assert "Proprietary" in (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "Propietaria" in eolfi.__license__
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        assert "extension/LICENSE.txt" in zipfile.ZipFile(build_vsix(root / "eolfi" / "vscode-bridge", d)).namelist()


def test_dotenv_carga_sin_pisar_y_sin_mostrar(tmp_path, monkeypatch):
    import os

    from eolfi import dotenv

    f = tmp_path / ".env"
    f.write_text('# comentario\nexport EOLFI_T_A=uno\nEOLFI_T_B="dos # no es comentario"\n'
                 "EOLFI_T_C='tres'  \nEOLFI_T_D=cuatro # comentario\nEOLFI_T_YA=nuevo\nlinea rota\n", encoding="utf-8")
    monkeypatch.delenv("EOLFI_NO_DOTENV", raising=False)
    for k in ("EOLFI_T_A", "EOLFI_T_B", "EOLFI_T_C", "EOLFI_T_D"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("EOLFI_T_YA", "viejo")
    loaded = dotenv.load_dotenv([f])
    assert sorted(loaded) == ["EOLFI_T_A", "EOLFI_T_B", "EOLFI_T_C", "EOLFI_T_D"]
    assert os.environ["EOLFI_T_A"] == "uno" and os.environ["EOLFI_T_B"] == "dos # no es comentario"
    assert os.environ["EOLFI_T_C"] == "tres" and os.environ["EOLFI_T_D"] == "cuatro"
    assert os.environ["EOLFI_T_YA"] == "viejo"          # no pisa lo ya definido
    monkeypatch.setenv("EOLFI_NO_DOTENV", "1")
    assert dotenv.load_dotenv([f]) == []


def test_env_ignorado_por_git():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    gi = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in gi and "!.env.example" in gi
    example = (root / ".env.example").read_text(encoding="utf-8")
    assert "GITHUB_TOKEN=" in example
    # la plantilla no lleva valores en las claves
    for line in example.splitlines():
        if line and not line.startswith("#") and line.endswith("=") is False:
            raise AssertionError(f"la plantilla tiene un valor: {line.split('=')[0]}")


def test_github_token_solo_para_github_https(monkeypatch):
    import base64

    from eolfi.sites import repo

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert repo.github_auth_env("https://github.com/yo/privado") == {}
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_prueba123")
    env = repo.github_auth_env("https://github.com/yo/privado.git")
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraHeader"
    assert base64.b64decode(env["GIT_CONFIG_VALUE_0"].split()[-1]).decode() == "x-access-token:ghp_prueba123"
    for url in ("https://gitlab.com/yo/x", "https://github.com.evil.es/x", "https://evil.es/github.com/x",
                "git@github.com:yo/x.git", "https://github.com:8443/yo/x", "https://otro@github.com/yo/x"):
        assert repo.github_auth_env(url) == {}, url


def test_git_endurecido_ignora_config_del_entorno(monkeypatch):
    from eolfi.sites import repo

    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.sshCommand")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "calc.exe")
    env = repo.safe_git_env()
    assert not any(k.startswith("GIT_CONFIG_COUNT") or k.startswith("GIT_CONFIG_KEY_") or k.startswith("GIT_CONFIG_VALUE_")
                   for k in env)


def test_clone_privado_sin_token_explica_que_hacer(monkeypatch, tmp_path):
    import shutil
    import subprocess

    import pytest

    from eolfi.sites import repo

    if not shutil.which("git"):
        pytest.skip("sin git")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(repo, "host_is_private", lambda h: False, raising=False)
    seen = {}

    def fake(git, args, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(args, 128, "", "remote: Repository not found.\nfatal: repository not found")
    monkeypatch.setattr(repo, "safe_git", fake)
    with pytest.raises(ValueError, match="GITHUB_TOKEN del archivo .env"):
        repo.clone("https://github.com/yo/privado", tmp_path)
    assert seen["extra_env"] == {}
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    with pytest.raises(ValueError) as e:
        repo.clone("https://github.com/yo/privado", tmp_path)
    assert "no da acceso" in str(e.value) and "ghp_x" not in str(e.value)
    assert seen["extra_env"]["GIT_CONFIG_KEY_0"].endswith("extraHeader")


def test_herramientas_en_la_carpeta_de_eolfi(tmp_path, monkeypatch):
    import os

    from eolfi.providers import external

    monkeypatch.setenv("EOLFI_TOOLS_DIR", str(tmp_path))
    exe = tmp_path / "rizin-v0.9.1" / "bin" / ("rizin.exe" if os.name == "nt" else "rizin")
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert external.tools_dir_find("rizin") == str(exe)
    assert external.tools_dir_find("capa") is None
    monkeypatch.setenv("EOLFI_TOOLS_DIR", str(tmp_path / "no-existe"))
    assert external.tools_dir_find("rizin") is None


def test_job_is_stored_before_it_is_published_as_done(tmp_path):
    """CI Windows: el trabajo se veía «done» antes de estar en el historial y otra instancia no lo encontraba."""
    from eolfi.server import EolfiApp

    db, samples = str(tmp_path / "e.db"), tmp_path / "s"
    a = EolfiApp(db, samples)
    a.create = lambda body: {"subject": "proyecto:x"}
    real = a._save_job

    def slow_save(job):
        time.sleep(0.3)               # guardado lento: «done» no puede aparecer antes
        real(job)
    a._save_job = slow_save
    jid = a.start_job({"kind": "create", "body": {"name": "T"}})["job_id"]
    for _ in range(300):
        if a.jobs[jid]["status"] == "done":
            break
        time.sleep(0.01)
    assert a.jobs[jid]["status"] == "done"
    listed = EolfiApp(db, samples).job_status({})["jobs"]
    assert listed and listed[0]["id"] == jid and listed[0]["status"] == "done"
