"""Voz local (PLAN_DEFINITIVO.md, bloque A): validación del audio, motores y API. El motor real de Windows solo se
prueba donde existe; el resto usa un motor simulado."""
import json
import math
import struct
from pathlib import Path

import pytest

from eolfi import cli, voz
from tests.test_server import req, srv  # noqa: F401 — fixture


def wav(segundos=0.5, hz=16000, canales=1, bits=16, codec=1):
    n = int(segundos * hz)
    datos = b"".join(struct.pack("<h", int(8000 * math.sin(i / 10))) * canales for i in range(n))
    cab = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(datos), b"WAVE", b"fmt ", 16, codec, canales, hz,
                      hz * canales * bits // 8, canales * bits // 8, bits, b"data", len(datos))
    return cab + datos


@pytest.fixture(autouse=True)
def sin_piper_del_equipo(monkeypatch, tmp_path):
    """Estas pruebas son de las voces de Windows: sin el Piper que haya instalado en el equipo (18/11/2026)."""
    monkeypatch.setenv("EOLFI_PIPER_VENV", str(tmp_path / "sin-piper"))
    monkeypatch.setenv("EOLFI_PIPER_VOCES", str(tmp_path / "sin-voces"))


@pytest.fixture
def motor(monkeypatch):
    """Motor de Windows simulado: reconocedor es-ES y una voz; anota lo que se le pide."""
    llamadas = []
    monkeypatch.setattr(voz, "_estado_windows", {"disponible": True, "reconocedores": ["es-ES"],
                                                 "voces": [{"nombre": "Voz de prueba", "idioma": "es-ES"}]})

    def ps(script, entorno=None, *, plazo=0):
        llamadas.append(entorno or {})
        if "EOLFI_VOZ_TEXTO" in (entorno or {}):
            Path(entorno["EOLFI_VOZ_WAV"]).write_bytes(wav(0.3))
            return {"ok": True}
        return {"segmentos": [{"texto": "hola", "confianza": 0.8}, {"texto": "mundo", "confianza": 0.6}]}
    monkeypatch.setattr(voz, "_ps", ps)
    return llamadas


def test_validar_wav_acepta_pcm16_y_rechaza_lo_demas():
    assert voz.validar_wav(wav(1.0)) == {"hz": 16000, "canales": 1, "segundos": 1.0}
    assert voz.validar_wav(wav(0.5, hz=48000, canales=2))["canales"] == 2
    for malo in (b"", b"RIFF" + b"x" * 60, wav(0.5, codec=3), wav(0.5, hz=96000), wav(0.01),
                 wav(0.5)[:30], b"MZ" + wav(0.5)):
        with pytest.raises(voz.VozError):
            voz.validar_wav(malo)
    with pytest.raises(voz.VozError):
        voz.validar_wav(b"RIFF" + bytes(1) * (voz.MAX_BYTES + 1))


def test_transcribir_une_segmentos_y_no_deja_el_audio(motor, tmp_path):
    r = voz.transcribir(wav(1.0))
    assert (r["texto"], r["motor"], r["idioma"], r["local"]) == ("hola mundo", "windows", "es-ES", True)
    assert r["confianza"] == 0.7
    assert not Path(motor[0]["EOLFI_VOZ_WAV"]).exists()          # la carpeta temporal se borra
    with pytest.raises(voz.VozError):
        voz.transcribir(wav(1.0), idioma="fr-FR")                # sin reconocedor instalado
    with pytest.raises(voz.VozError):
        voz.transcribir(wav(1.0), idioma="es; rm -rf")           # nunca llega al guion


def test_hablar_valida_texto_y_voz(motor):
    assert voz.validar_wav(voz.hablar("Hola"))["hz"] == 16000
    assert motor[-1]["EOLFI_VOZ_NOMBRE"] == ""
    for texto, kw in (("", {}), ("x" * (voz.MAX_TEXTO + 1), {}), ("Hola", {"voz": "Otra voz"}), ("Hola", {"voz": "a'; calc"})):
        with pytest.raises(voz.VozError):
            voz.hablar(texto, **kw)


def test_configuracion_validada_y_estado(motor):
    assert voz.cargar()["motor"] == "auto"
    assert voz.guardar({"motor": "windows", "idioma": "en-US"})["idioma"] == "en-US"
    for cambios in ({"motor": "nube"}, {"idioma": "español"}, {"voz": "x" * 200}):
        with pytest.raises(voz.VozError):
            voz.guardar(cambios)
    voz.config_path().write_text("{no es json", encoding="utf-8")
    assert voz.cargar() == voz.DEFECTO                            # una configuración rota no rompe nada
    e = voz.estado()
    assert e["motor_activo"] == "windows" and e["voz_a_texto"] and e["texto_a_voz"] and e["local"]


def test_sin_motor_el_error_es_claro(monkeypatch):
    monkeypatch.setattr(voz, "_estado_windows", {"disponible": False, "reconocedores": [], "voces": []})
    assert voz.estado()["voz_a_texto"] is False
    with pytest.raises(voz.VozError, match="ningún motor"):
        voz.transcribir(wav(1.0))


def test_whisper_tiene_prioridad_en_auto_si_esta_instalado(motor, monkeypatch, tmp_path):
    exe, modelo = tmp_path / "whisper-cli.exe", tmp_path / "ggml.bin"
    exe.write_bytes(b"x")
    modelo.write_bytes(b"x")
    voz.config_path().write_text(json.dumps({"whisper": {"bin": str(exe), "modelo": str(modelo)}}), encoding="utf-8")
    visto = {}

    class Salida:
        returncode, stdout, stderr = 0, b" hola  desde whisper \n", b""

    def run(cmd, **kw):
        visto["cmd"] = cmd
        return Salida()
    monkeypatch.setattr(voz.subprocess, "run", run)
    r = voz.transcribir(wav(1.0))
    assert (r["texto"], r["motor"]) == ("hola desde whisper", "whisper")
    assert visto["cmd"][:3] == [str(exe), "-m", str(modelo)] and visto["cmd"][5:7] == ["-l", "es"]


def test_api_de_voz(srv, motor):  # noqa: F811
    port, _ = srv
    h = {"X-Eolfi": "1"}
    st, e, _ = req(port, "GET", "/api/voz/estado")
    assert st == 200 and e["motor_activo"] == "windows"
    st, r, _ = req(port, "POST", "/api/voz/transcribir", wav(1.0), {**h, "Content-Type": "audio/wav"})
    assert st == 200 and r["texto"] == "hola mundo"
    st, r, _ = req(port, "POST", "/api/voz/transcribir", b"no es audio", h)
    assert st == 400 and "WAV" in r["error"]
    assert req(port, "POST", "/api/voz/transcribir", wav(1.0))[0] == 403          # sin la cabecera anti-CSRF
    st, audio, hdrs = req(port, "POST", "/api/voz/hablar", json.dumps({"texto": "Hola"}), h)
    assert st == 200 and hdrs["Content-Type"] == "audio/wav" and audio[:4] == b"RIFF"
    assert req(port, "POST", "/api/voz/hablar", json.dumps({"texto": ""}), h)[0] == 400
    st, js, hdrs = req(port, "GET", "/voz.js")
    assert st == 200 and hdrs["Content-Type"].startswith("text/javascript")
    assert b"/api/voz/transcribir" in js and b"https://" not in js and b"webkitSpeechRecognition" not in js


def test_cli_voz(motor, tmp_path, capsys):
    f = tmp_path / "a.wav"
    f.write_bytes(wav(1.0))
    assert cli.main(["voz", "transcribir", str(f)]) == 0
    assert "hola mundo" in capsys.readouterr().out
    assert cli.main(["voz", "decir", "Hola", "--out", str(tmp_path / "s.wav")]) == 0
    assert (tmp_path / "s.wav").read_bytes()[:4] == b"RIFF"
    assert cli.main(["voz", "transcribir", str(tmp_path / "no-existe.wav")]) == 2
    assert cli.main(["voz", "estado"]) == 0


@pytest.mark.skipif(voz._powershell() is None, reason="solo con Windows PowerShell")
def test_motor_real_de_windows_de_ida_y_vuelta(monkeypatch):
    monkeypatch.setattr(voz, "_estado_windows", None)
    e = voz.estado()
    if not (e["texto_a_voz"] and e["voz_a_texto"]):
        pytest.skip("este Windows no tiene voz o reconocedor para es-ES")
    r = voz.transcribir(voz.hablar("Analiza este archivo y dime qué hace."))
    assert r["motor"] == "windows" and "archivo" in r["texto"].lower()


# ── Dictado desde el micrófono del equipo (A9, 18/11/2026) ──────────────────────────────────────────────────────
@pytest.fixture
def microfono(motor, monkeypatch):
    """Grabación simulada: el guion de MCI escribe un WAV donde se le pide; el resto, el motor simulado."""
    real = voz._ps
    grabaciones = []

    def ps(script, entorno=None, *, plazo=0):
        if script is voz._PS_GRABAR:
            grabaciones.append((dict(entorno), plazo))
            Path(entorno["EOLFI_VOZ_WAV"]).write_bytes(wav(int(entorno["EOLFI_VOZ_MS"]) / 1000))
            return {"ok": True}
        return real(script, entorno, plazo=plazo)
    monkeypatch.setattr(voz, "_ps", ps)
    return grabaciones


def test_dictar_graba_transcribe_y_no_guarda(microfono):
    r = voz.dictar(2, idioma="es-ES")
    assert r["texto"] == "hola mundo" and r["segundos"] == 2.0 and r["audio_guardado"] is False
    (entorno, plazo), = microfono
    assert entorno["EOLFI_VOZ_MS"] == "2000" and plazo == 32
    assert not Path(entorno["EOLFI_VOZ_WAV"]).parent.exists()          # la carpeta temporal se borra
    for malo in (0, 31, "x", None):
        with pytest.raises(voz.VozError):
            voz.dictar(malo)
    assert len(microfono) == 1                                          # duraciones malas: no se graba


def test_dictar_sin_motor_ni_grabacion(monkeypatch):
    monkeypatch.setattr(voz, "_estado_windows", {"disponible": False, "reconocedores": [], "voces": []})
    grabado = []
    monkeypatch.setattr(voz, "grabar", lambda s: grabado.append(s))
    with pytest.raises(voz.VozError, match="motor"):
        voz.dictar(3)
    assert grabado == []                                                # sin motor no se pide hablar


def test_dictar_sin_microfono_y_uno_a_la_vez(motor, monkeypatch):
    monkeypatch.setattr(voz, "_ps", lambda *a, **k: {"ok": True})       # MCI no escribió nada
    with pytest.raises(voz.VozError, match="micrófono"):
        voz.dictar(1)
    assert voz._dictando.acquire(blocking=False)
    try:
        with pytest.raises(voz.VozError, match="en curso"):
            voz.dictar(1)
    finally:
        voz._dictando.release()


def test_api_y_cli_de_dictado(srv, microfono, capsys):  # noqa: F811
    port, _ = srv
    st, r, _ = req(port, "POST", "/api/voz/dictar", json.dumps({"segundos": 1}), {"X-Eolfi": "1"})
    assert st == 200 and r["texto"] == "hola mundo"
    st, r, _ = req(port, "POST", "/api/voz/dictar", json.dumps({"segundos": 99}), {"X-Eolfi": "1"})
    assert st == 400 and "entre 1 y 30" in r["error"]
    assert req(port, "POST", "/api/voz/dictar", json.dumps({"segundos": 1}))[0] == 403    # sin cabecera anti-CSRF
    assert cli.main(["voz", "dictar", "--segundos", "1"]) == 0
    assert "hola mundo" in capsys.readouterr().out


# ── Micrófonos del equipo (19/11/2026) ──────────────────────────────────────────────────────────────────────────
def _mics(monkeypatch, lista):
    monkeypatch.setattr(voz, "_powershell", lambda: "powershell.exe")
    monkeypatch.setattr(voz, "_ps", lambda script, entorno=None, *, plazo=0:
                        {"microfonos": lista} if script is voz._PS_MICROFONOS else pytest.fail("solo se consulta"))


def test_microfonos_estado_y_diagnostico(monkeypatch):
    torre = {"nombre": "Micrófono (High Definition Audio Device)", "estado": 1, "predeterminado": True,
             "silenciado": False, "volumen": 100}
    otra = {"nombre": "Entrada de línea", "estado": 8, "predeterminado": False, "silenciado": False, "volumen": -1}
    _mics(monkeypatch, [otra, torre])
    m = voz.microfonos()
    assert m["predeterminado"] == torre["nombre"] and m["diagnostico"] is None
    assert [(x["nombre"], x["estado"], x["volumen"]) for x in m["microfonos"]] == [
        (torre["nombre"], "activo", 100), ("Entrada de línea", "desconectado", None)]
    _mics(monkeypatch, {**torre, "silenciado": True})                      # un solo elemento llega como objeto
    assert "silenciado" in voz.microfonos()["diagnostico"]
    _mics(monkeypatch, [{**torre, "volumen": 3}])
    assert "volumen de entrada al 3 %" in voz.microfonos()["diagnostico"]
    _mics(monkeypatch, [otra])
    m = voz.microfonos()
    assert m["predeterminado"] is None and "ningún micrófono activo (1 toma(s) sin nada enchufado)" in m["diagnostico"]


def test_si_llega_silencio_se_dice_que_revisar(motor, monkeypatch):
    silencio = wav(1.0)[:44] + bytes(32000)
    assert voz.nivel(silencio) == {"pico": 0, "rms": 0.0} and voz.nivel(wav(1.0))["pico"] > 7000
    monkeypatch.setattr(voz, "microfonos", lambda: {"predeterminado": "Mic de la torre", "diagnostico": None})
    with pytest.raises(voz.VozError, match="No llega sonido de «Mic de la torre»"):
        voz.transcribir(silencio)
    monkeypatch.setattr(voz, "microfonos", lambda: {"predeterminado": "Mic", "diagnostico": "«Mic» está silenciado"})
    with pytest.raises(voz.VozError, match="está silenciado"):
        voz.transcribir(silencio)
    assert motor == []                                                     # el silencio no llega al reconocedor


def test_api_y_cli_de_microfonos(srv, monkeypatch, capsys):  # noqa: F811
    _mics(monkeypatch, [{"nombre": "Mic", "estado": 1, "predeterminado": True, "silenciado": False, "volumen": 80}])
    port, _ = srv
    st, m, _ = req(port, "GET", "/api/voz/microfonos")
    assert st == 200 and m["predeterminado"] == "Mic"
    assert cli.main(["voz", "microfonos"]) == 0 and '"Mic"' in capsys.readouterr().out
    monkeypatch.setattr(voz, "_ps", lambda *a, **k: (_ for _ in ()).throw(voz.VozError("PowerShell roto")))
    assert voz.microfonos() == {"disponible": False, "microfonos": [], "predeterminado": None,
                                "diagnostico": "PowerShell roto"}


@pytest.mark.skipif(voz._powershell() is None, reason="solo con Windows PowerShell")
def test_microfonos_reales_del_equipo():
    m = voz.microfonos()
    assert m["disponible"] and all(x["estado"] in voz.ESTADOS_MIC.values() for x in m["microfonos"])


def test_microfono_silenciado_con_hilo_de_ruido_y_marcas_de_whisper(motor, monkeypatch, tmp_path):
    """19/11/2026, en vivo: el auricular en la otra toma rosa, silenciada en Windows, dejaba un ruido de pico ~100 y
    Whisper devolvía «(Silencio) (Silencio)» como si fuera texto."""
    flojo = wav(1.0)[:44] + b"".join(struct.pack("<h", 100 if i % 50 == 0 else 0) for i in range(16000))
    consultas = []
    monkeypatch.setattr(voz, "microfonos", lambda: consultas.append(1) or
                        {"predeterminado": "Mic", "diagnostico": "«Mic» está silenciado en Windows"})
    with pytest.raises(voz.VozError, match="silenciado"):
        voz.transcribir(flojo)
    monkeypatch.setattr(voz, "microfonos", lambda: consultas.append(1) or {"predeterminado": "Mic", "diagnostico": None})
    assert voz.transcribir(flojo)["texto"] == "hola mundo"           # flojo pero bien configurado: se transcribe
    n = len(consultas)
    voz.transcribir(wav(1.0))
    assert len(consultas) == n                                         # con buen nivel no se consulta nada
    exe, modelo = tmp_path / "whisper-cli.exe", tmp_path / "ggml.bin"
    exe.write_bytes(b"x")
    modelo.write_bytes(b"x")
    voz.config_path().write_text(json.dumps({"whisper": {"bin": str(exe), "modelo": str(modelo)}}), encoding="utf-8")

    class Salida:
        returncode, stderr = 0, b""
        stdout = "(Silencio) hola [Pausa] [BLANK_AUDIO] adiós [Música de fondo]".encode()
    monkeypatch.setattr(voz.subprocess, "run", lambda cmd, **kw: Salida())
    assert voz.transcribir(wav(1.0))["texto"] == "hola adiós"
    Salida.stdout = b"(Silencio) (Silencio) (Silencio)"
    assert voz.transcribir(wav(1.0))["texto"] == ""
