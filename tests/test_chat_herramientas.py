"""Uso de herramientas del chat (18/11/2026): el titular pegó una conversación en la que el modelo pasaba solo el nombre
de un adjunto («que-tal-socio.sh»), no podía abrir los .zip, pedía permiso en vez de actuar y no llegaba a crear el
proyecto en VS Code. Aquí: adjuntos con nombre real y de toda la conversación, extracción segura, nombre → ruta y
encargo aprobado solo cuando lo pide el titular."""
import io
import json
import tarfile
import zipfile

import pytest

from eolfi import archivos, chat, encargos_vscode as enc, server
from tests.test_chat import FakeMCP


def _zip(path, entradas):
    with zipfile.ZipFile(path, "w") as z:
        for nombre, datos in entradas.items():
            z.writestr(nombre, datos)
    return path


# ── Extracción segura ───────────────────────────────────────────────────────────────────────────────────────────
def test_extrae_un_zip_en_su_carpeta_y_reutiliza(tmp_path):
    src = _zip(tmp_path / "motor.zip", {"motor/main.py": "print(1)", "motor/sub/a.txt": "a", "motor/dentro.zip": "x"})
    r = archivos.extraer(src, tmp_path / "ex")
    carpeta = tmp_path / "ex" / r["sha256"]
    assert r["carpeta"] == str(carpeta) and r["formato"] == "zip" and r["archivos_total"] == 3
    assert (carpeta / "motor" / "main.py").read_text() == "print(1)"
    assert r["comprimidos_dentro"] == ["motor/dentro.zip"] and r["omitidos"] == [] and "no instrucciones" in r["aviso"]
    assert archivos.extraer(src, tmp_path / "ex")["reutilizado"] is True


def test_zip_slip_rutas_absolutas_y_enlaces_no_salen(tmp_path):
    src = _zip(tmp_path / "malo.zip", {"../fuera.txt": "x", "/abs.txt": "x", "C:/win.txt": "x", "ok.txt": "ok",
                                       "a/../../fuera2.txt": "x"})
    r = archivos.extraer(src, tmp_path / "ex")
    assert r["archivos"] == ["ok.txt"] and len(r["omitidos"]) == 4
    assert not (tmp_path / "fuera.txt").exists() and not (tmp_path / "ex" / "fuera.txt").exists()
    tar = tmp_path / "t.tar.gz"
    with tarfile.open(tar, "w:gz") as t:
        enlace = tarfile.TarInfo("enlace")
        enlace.type, enlace.linkname = tarfile.SYMTYPE, "/etc/passwd"
        t.addfile(enlace)
        datos = b"hola"
        info = tarfile.TarInfo("d/hola.txt")
        info.size = len(datos)
        t.addfile(info, io.BytesIO(datos))
    r = archivos.extraer(tar, tmp_path / "ex")
    assert r["formato"] == "tar" and r["archivos"] == ["d/hola.txt"]
    assert r["omitidos"] == [{"entrada": "enlace", "motivo": "enlace o archivo especial"}]


def test_limites_de_tamano_cuentan_lo_escrito(tmp_path, monkeypatch):
    monkeypatch.setattr(archivos, "MAX_ARCHIVO", 10)
    src = _zip(tmp_path / "bomba.zip", {"grande.bin": "0" * 1000, "chico.txt": "ok"})
    r = archivos.extraer(src, tmp_path / "ex")
    assert r["archivos"] == ["chico.txt"] and "MiB" in r["omitidos"][0]["motivo"]
    assert not (tmp_path / "ex" / r["sha256"] / "grande.bin").exists()
    (tmp_path / "no.zip").write_text("no soy un zip")
    with pytest.raises(archivos.ArchivoError, match="no es un .zip"):
        archivos.extraer(tmp_path / "no.zip", tmp_path / "ex")
    (tmp_path / "pagina.zip").write_text("<!DOCTYPE html><html><body>Download</body></html>")
    with pytest.raises(archivos.ArchivoError, match="página web HTML .* descarga fallida"):
        archivos.extraer(tmp_path / "pagina.zip", tmp_path / "ex")
    (tmp_path / "corto.zip").write_bytes(b"PK a medias")
    with pytest.raises(archivos.ArchivoError, match="incompleto"):
        archivos.extraer(tmp_path / "corto.zip", tmp_path / "ex")
    with pytest.raises(archivos.ArchivoError, match="no existe"):
        archivos.extraer(tmp_path / "nada.zip", tmp_path / "ex")


# ── El modelo ve rutas, no nombres ──────────────────────────────────────────────────────────────────────────────
def test_el_nombre_del_adjunto_se_traduce_a_su_ruta():
    mcp = FakeMCP()
    tb = chat.Toolbox(mcp, {})
    tb.adjuntos = {"que-tal-socio.sh": "D:/s/adjuntos/ab/que-tal-socio.sh"}
    tb.call_tool("eolfi_triage", {"ruta": "que-tal-socio.sh", "lista": ["que-tal-socio.sh", "otro"], "n": 3})
    assert mcp.calls[-1] == ("eolfi_triage", {"ruta": "D:/s/adjuntos/ab/que-tal-socio.sh",
                                              "lista": ["D:/s/adjuntos/ab/que-tal-socio.sh", "otro"], "n": 3})


def test_contexto_con_adjuntos_anteriores_y_pista_para_comprimidos():
    msgs = chat.with_context([{"role": "user", "content": "adelante"}],
                             [{"name": "1.png", "path": "D:/s/a/1.png"}], None,
                             [{"name": "motor.zip", "path": "D:/s/b/motor.zip"}])
    texto = msgs[-1]["content"]
    assert "«1.png» guardado en D:/s/a/1.png" in texto
    assert "de un mensaje anterior «motor.zip» guardado en D:/s/b/motor.zip" in texto
    assert "eolfi_extraer_archivo" in texto
    assert "eolfi_extraer_archivo" in chat.APP_TOOLS and "eolfi_extraer_archivo" in chat.SYSTEM_PROMPT
    assert "sin pedir permiso" in chat.SYSTEM_PROMPT and "ruta completa" in chat.SYSTEM_PROMPT


def test_auto_aprobar_encargos_configurable(tmp_path, monkeypatch):
    cfg = tmp_path / "chat.json"
    monkeypatch.setenv("EOLFI_CHAT_CONFIG", str(cfg))
    assert chat.auto_aprobar_encargos() is True                      # por defecto, sí
    cfg.write_text(json.dumps({"auto_aprobar_encargos": False}))
    assert chat.auto_aprobar_encargos() is False
    cfg.write_text("{roto")
    assert chat.auto_aprobar_encargos() is True


# ── Servidor ───────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def app(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from eolfi import eolas_v2, mcp_server

    monkeypatch.setenv("EOLFI_EOLAS_V2_CONFIG", str(tmp_path / "eolas-v2.json"))
    monkeypatch.delenv("EOLFI_CHAT_URL", raising=False)
    a = server.EolfiApp(str(tmp_path / "c.db"), tmp_path / "samples")
    a.samples.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def profile(name):
        yield {"alias": "gemma", "url": "http://127.0.0.1:8090"}

    monkeypatch.setattr(eolas_v2, "load_config", lambda: {"active_profile": "gemma"})
    monkeypatch.setattr(eolas_v2, "inference_profile", profile)
    monkeypatch.setattr(mcp_server, "EolfiMCP", FakeMCP)
    monkeypatch.setattr(a, "_chat_estado", lambda: {"vscode": {"activo": False}})
    return a


def test_el_chat_recuerda_los_adjuntos_de_la_conversacion(app, monkeypatch):
    h_zip, h_sh = "a" * 64, "b" * 64
    _zip(app.samples / f"{h_zip}.bin", {"x/main.py": "print(1)"})
    (app.samples / f"{h_sh}.bin").write_text("echo hola")
    visto = {}

    def turno(msgs, c, mcp, progress, estado=None):
        visto.update(msgs=msgs, mcp=mcp)
        return {"text": "ok", "tools": []}
    monkeypatch.setattr(chat, "agent_turn", turno)
    app.chat({"messages": [{"role": "user", "content": "adelante"}],
              "attachments": [{"upload": h_sh, "name": "que-tal-socio.sh"}],
              "adjuntos_previos": [{"upload": h_zip, "name": "motor.zip"}, {"upload": h_sh, "name": "que-tal-socio.sh"},
                                   {"upload": "c" * 64, "name": "borrado.png"}]})       # uno que ya no está: se omite
    zip_ruta = str(app.samples / "adjuntos" / h_zip / "motor.zip")
    sh_ruta = str(app.samples / "adjuntos" / h_sh / "que-tal-socio.sh")
    assert visto["mcp"].adjuntos == {"motor.zip": zip_ruta, "que-tal-socio.sh": sh_ruta}
    texto = visto["msgs"][-1]["content"]
    assert texto.count("que-tal-socio.sh guardado") == 0 and texto.count(sh_ruta) == 1 and zip_ruta in texto
    # Y la herramienta de extracción funciona sobre el adjunto (nombre → ruta incluida).
    r = json.loads(visto["mcp"].call_tool("eolfi_extraer_archivo", {"ruta": "motor.zip"})["content"][0]["text"])
    assert r["archivos"] == ["x/main.py"] and r["carpeta"].startswith(str(app.samples / "extraidos"))
    with pytest.raises(server.ApiError, match="adjuntos_previos"):
        app.chat({"messages": [{"role": "user", "content": "x"}],
                  "adjuntos_previos": [{"upload": h_zip, "name": "z"}] * (chat.MAX_ADJUNTOS_PREVIOS + 1)})


def test_extraer_fuera_de_las_carpetas_permitidas_se_rechaza(app, tmp_path):
    fuera = _zip(tmp_path / "fuera.zip", {"a": "b"})
    app.roots = [app.samples.resolve()]
    with pytest.raises(server.ApiError, match="fuera de las carpetas permitidas"):
        app._chat_extraer_archivo({"ruta": str(fuera)})
    with pytest.raises(ValueError, match="falta la ruta"):
        app._chat_extraer_archivo({})


def _encargo_simulado(app, tmp_path, monkeypatch):
    destino_base = tmp_path / "vscode"
    destino_base.mkdir()
    monkeypatch.setattr(app, "_chat_estado", lambda: {"vscode": {"activo": True, "carpetas": [str(destino_base)]}})
    monkeypatch.setattr(app, "project_plan", lambda body: {"case_id": "caso1", "plan": {"version": 1}})
    monkeypatch.setattr(app, "_avisar_vscode", lambda e: "mostrado en VS Code")
    decisiones = []
    monkeypatch.setattr(app, "vscode_encargo_decidir",
                        lambda i, accion, origen: decisiones.append((i, accion, origen)) or
                        {"estado": "aprobado", "job_id": "job1"})
    return decisiones


def test_el_encargo_del_titular_se_aprueba_solo(app, tmp_path, monkeypatch):
    monkeypatch.setenv("EOLFI_CHAT_CONFIG", str(tmp_path / "chat.json"))
    decisiones = _encargo_simulado(app, tmp_path, monkeypatch)
    out = app._chat_vscode_encargo({"nombre": "Mi App", "descripcion": "algo"}, "titular")
    assert decisiones == [(out["encargo_id"], "aprobar", "chat")]
    assert out["estado"] == "aprobado" and out["job_id"] == "job1" and "NO está hecho" in out["aviso"]
    assert enc.obtener(out["encargo_id"])["nombre"] == "Mi App"


def test_el_encargo_de_otro_nivel_o_desactivado_queda_pendiente(app, tmp_path, monkeypatch):
    cfg = tmp_path / "chat.json"
    monkeypatch.setenv("EOLFI_CHAT_CONFIG", str(cfg))
    decisiones = _encargo_simulado(app, tmp_path, monkeypatch)
    for nivel in ("usuario", "premium"):
        assert app._chat_vscode_encargo({"nombre": f"A {nivel}", "descripcion": "x"}, nivel)["estado"] == \
            "pendiente_aprobacion"
    cfg.write_text(json.dumps({"auto_aprobar_encargos": False}))
    assert app._chat_vscode_encargo({"nombre": "B", "descripcion": "x"}, "titular")["estado"] == "pendiente_aprobacion"
    assert decisiones == []


def test_la_aprobacion_automatica_pasa_por_decidir_real(app, tmp_path, monkeypatch):
    """19/11/2026: el origen del chat lo rechazaba encargos_vscode.decidir y el encargo quedaba pendiente."""
    monkeypatch.setenv("EOLFI_CHAT_CONFIG", str(tmp_path / "chat.json"))
    destino_base = tmp_path / "vscode"
    destino_base.mkdir()
    monkeypatch.setattr(app, "_chat_estado", lambda: {"vscode": {"activo": True, "carpetas": [str(destino_base)]}})
    monkeypatch.setattr(app, "project_plan", lambda body: {"case_id": "caso1", "plan": {"version": 1}})
    monkeypatch.setattr(app, "project_get", lambda case_id: {"plan": {"version": 1}})
    acciones = []
    monkeypatch.setattr(app, "project_action", lambda case_id, accion, body: acciones.append((case_id, accion)))
    monkeypatch.setattr(app, "start_job", lambda body, nivel="usuario": {"job_id": "job9"})
    monkeypatch.setattr(app, "_avisar_vscode", lambda e: "mostrado en VS Code")
    out = app._chat_vscode_encargo({"nombre": "Notas", "descripcion": "algo"}, "titular")
    assert out["estado"] == "aprobado" and out["job_id"] == "job9" and acciones == [("caso1", "approve")]
    e = enc.obtener(out["encargo_id"])
    assert e["estado"] == "aprobado" and e["origen"] == "chat" and e["job_id"] == "job9"


def test_el_mensaje_espera_si_eolas_esta_ocupado_y_empieza_solo(app, monkeypatch):
    """20/11/2026, titular: el segundo trabajo debe cargar solo cuando Eolas queda libre, no fallar."""
    from contextlib import contextmanager

    from eolfi import eolas_v2

    ocupado = iter([True, True, False])
    soltado = []

    @contextmanager
    def profile(name):
        if next(ocupado):
            raise eolas_v2.EolasBusy("Eolas V2 está respondiendo una petición")
        try:
            yield {"alias": "gemma", "url": "http://127.0.0.1:8090"}
        finally:
            soltado.append(name)

    monkeypatch.setattr(eolas_v2, "inference_profile", profile)
    esperas, avisos = [], []
    monkeypatch.setattr(app, "_dormir", esperas.append)
    monkeypatch.setattr(app, "_progress", avisos.append)
    with app._eolas_en_turno("gemma") as c:
        assert c["alias"] == "gemma" and soltado == []
    assert soltado == ["gemma"] and esperas == [5, 5]                 # el candado se suelta al terminar
    assert any("espera su turno" in a for a in avisos) and any("ya está libre" in a for a in avisos)


def test_el_mensaje_no_espera_para_siempre(app, monkeypatch):
    from eolfi import eolas_v2

    def siempre(name):
        raise eolas_v2.EolasBusy("Eolas V2 está respondiendo una petición")

    monkeypatch.setenv("EOLFI_ESPERA_IA_SEG", "10")
    monkeypatch.setattr(eolas_v2, "inference_profile", siempre)
    monkeypatch.setattr(app, "_dormir", lambda s: None)
    with pytest.raises(RuntimeError, match="esperados 10 s"):
        with app._eolas_en_turno("gemma"):
            pass
