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
