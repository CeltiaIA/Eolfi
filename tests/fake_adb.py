"""adb simulado para las pruebas del paso «mobile»: un dispositivo con una app sintética.

App ``org.eolfi.muestra`` (versión 1.2, código 3): un campo «nombre», un botón «Saludar» que escribe «Hola, NOMBRE»
en «saludo», y un campo de contraseña. BACK la cierra y vuelve al lanzador. El estado vive en el archivo JSON de
``FAKE_ADB_STATE``. ``FAKE_ADB_DEVICES`` controla la salida de ``adb devices`` (por defecto un emulador listo).

Situaciones vistas en un Redmi Note 12R Pro real (Android 14, MIUI), reproducidas con variables de entorno:
- ``FAKE_ADB_DUMP_FAILS=N``: los N primeros ``uiautomator dump`` no escriben el archivo (ventana dibujándose).
- ``FAKE_ADB_BLOCK_INPUT=1``: ``input`` falla con SecurityException INJECT_EVENTS seguida de una traza larga.
- ``FAKE_ADB_LOCK_AFTER=N``: tras N órdenes ``input`` la pantalla se apaga y queda la pantalla de bloqueo; dumpsys
  sigue dando la app como ``mFocusedApp``.
- ``FAKE_ADB_LOCKED=1``: la pantalla está apagada desde el principio.
"""
import json
import os
import shlex
import sys
import time
from pathlib import Path

PKG = "org.eolfi.muestra"
STATE = Path(os.environ["FAKE_ADB_STATE"])
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (360).to_bytes(4, "big") + (640).to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"


def load():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"running": False, "nombre": "", "saludo": "", "dump": "", "log": [], "dumps": 0, "inputs": 0,
            "locked": os.environ.get("FAKE_ADB_LOCKED") == "1"}


def save(st):
    STATE.write_text(json.dumps(st), encoding="utf-8")


def xml(st):
    if st.get("locked"):
        return ('<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0"><node class="android.widget.FrameLayout" '
                'package="com.android.systemui" text="" resource-id="com.android.systemui:id/notification_panel" '
                'content-desc="" bounds="[0,0][360,640]"/></hierarchy>')
    if not st["running"]:
        return ('<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0"><node class="android.widget.FrameLayout" '
                'package="com.android.launcher3" text="" resource-id="" content-desc="Inicio" clickable="false" '
                'bounds="[0,0][360,640]"/></hierarchy>')

    def node(rid, cls, text, bounds, **flags):
        extra = "".join(f' {k}="{v}"' for k, v in flags.items())
        return (f'<node index="0" text="{text}" resource-id="{PKG}:id/{rid}" class="{cls}" package="{PKG}" '
                f'content-desc="" enabled="true" bounds="{bounds}"{extra}/>')

    return ('<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0">'
            f'<node class="android.widget.FrameLayout" package="{PKG}" text="" resource-id="" content-desc="" bounds="[0,0][360,640]">'
            + node("titulo", "android.widget.TextView", "Muestra Eolfi", "[0,0][360,80]")
            + node("nombre", "android.widget.EditText", st["nombre"], "[0,100][360,180]", clickable="true", focusable="true")
            + node("clave", "android.widget.EditText", "secreto", "[0,190][360,260]", clickable="true", password="true")
            + node("saludar", "android.widget.Button", "Saludar", "[0,280][360,360]", clickable="true")
            + node("saludo", "android.widget.TextView", st["saludo"], "[0,380][360,460]")
            + "</node></hierarchy>")


def shell(st, words):
    cmd = words[0] if words else ""
    out = ""
    if cmd == "getprop":
        out = ("[ro.product.manufacturer]: [Eolfi]\n[ro.product.model]: [Sintetico]\n"
               "[ro.build.version.release]: [14]\n[ro.build.version.sdk]: [34]\n[ro.product.cpu.abi]: [x86_64]\n"
               "[ro.serialno]: [no-debe-guardarse]\n")
    elif cmd == "pm" and words[1] == "path":
        out = f"package:/data/app/{PKG}/base.apk\n" if words[2] == PKG else ""
    elif cmd == "pm" and words[1] == "clear":
        st.update(running=False, nombre="", saludo="")
        out = "Success\n"
    elif cmd == "dumpsys" and words[1] == "package":
        out = "    versionCode=3 minSdk=24 targetSdk=34\n    versionName=1.2\n" if words[2] == PKG else ""
    elif cmd == "dumpsys" and words[1] == "window":
        focus = ("NotificationShade" if st.get("locked") else f"{PKG}/{PKG}.Principal" if st["running"] else
                 "com.android.launcher3/com.android.launcher3.Launcher")
        out = f"  mCurrentFocus=Window{{1a2b3c u0 {focus}}}\n"
        if st.get("locked") and st["running"]:          # como en el Redmi: la app sigue como mFocusedApp
            out += f"  mFocusedApp=ActivityRecord{{9 u0 {PKG}/.Principal t5}}\n"
    elif cmd == "dumpsys" and words[1] == "power":
        out = f"  mWakefulness={'Dozing' if st.get('locked') else 'Awake'}\n"
    elif cmd in ("monkey", "am") and (cmd == "monkey" or words[1] == "start"):
        st["running"] = True
        out = "Events injected: 1\n"
    elif cmd == "am" and words[1] == "force-stop":
        st["running"] = False
    elif cmd == "uiautomator":
        st["dumps"] += 1
        if st["dumps"] <= int(os.environ.get("FAKE_ADB_DUMP_FAILS", "0")):
            st["dump"] = ""
            return 0, "ERROR: could not get idle state.\n"
        st["dump"] = xml(st)
        out = "UI hierchary dumped to: /sdcard/eolfi_ui.xml\n"
    elif cmd == "rm":
        pass
    elif cmd == "input" and os.environ.get("FAKE_ADB_BLOCK_INPUT") == "1":
        sys.stderr.write(f"Exception occurred while executing '{words[1]}':\njava.lang.SecurityException: Injecting "
                         "input events requires the caller (or the source of the instrumentation, if any) to have the "
                         "INJECT_EVENTS permission.\n"
                         + "\tat com.android.server.input.InputManagerService.x(InputManagerService.java:1)\n" * 30)
        return 255, ""
    elif cmd == "input" and st.get("locked"):
        pass                                             # con la pantalla apagada el toque no llega a la app
    elif cmd == "input" and words[1] == "tap":
        x, y = int(words[2]), int(words[3])
        st["focus"] = "nombre" if 100 <= y < 180 else None
        if st["running"] and 280 <= y < 360 and 0 <= x <= 360:
            st["saludo"] = f"Hola, {st['nombre']}"
    elif cmd == "input" and words[1] == "text":
        if st.get("focus") == "nombre":
            st["nombre"] += words[2].replace("%s", " ")
    elif cmd == "input" and words[1] == "keyevent":
        if words[2] == "KEYCODE_BACK":
            st["running"] = False
    else:
        sys.stderr.write(f"orden no simulada: {words}\n")
        return 1, out
    if cmd == "input":
        st["inputs"] += 1
        limit = os.environ.get("FAKE_ADB_LOCK_AFTER")
        if limit and st["inputs"] >= int(limit):
            st["locked"] = True
    return 0, out


def main(argv):
    if argv[:1] == ["-s"]:
        argv = argv[2:]
    st = load()
    st["log"].append(argv)
    if argv == ["devices"]:
        listed = os.environ.get("FAKE_ADB_DEVICES", "emulator-5554\tdevice\n")
        sys.stdout.write("List of devices attached\n" + ("" if listed == "-" else listed))   # «-»: ninguno
        save(st)
        return 0
    if argv[:1] == ["exec-out"]:
        words = shlex.split(" ".join(argv[1:]))
        if words[:1] == ["cat"]:
            if not st["dump"]:
                sys.stdout.write("cat: /sdcard/eolfi_ui.xml: No such file or directory\n")
                save(st)
                return 1
            sys.stdout.buffer.write(st["dump"].encode("utf-8"))
        elif words[:2] == ["screencap", "-p"]:
            # como en un móvil real, la imagen lleva la hora de la barra de estado: cambia en cada captura
            sys.stdout.buffer.write(PNG + json.dumps([st["nombre"], st["saludo"], st["running"], time.time()]).encode())
        save(st)
        return 0
    if argv[:1] == ["shell"]:
        code, out = shell(st, shlex.split(" ".join(argv[1:])))
        sys.stdout.write(out)
        save(st)
        return code
    sys.stderr.write(f"orden no simulada: {argv}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
