"""Muestras sintéticas propias para las pruebas de observación de caja negra (sin procedencia externa).

Cada muestra es un programa Python pequeño que se escribe en una carpeta temporal y se ejecuta como objetivo
«sin fuentes»: las pruebas solo miran su comportamiento observable.
"""
from __future__ import annotations

from pathlib import Path

# v1: lee stdin, escribe estado en la carpeta de trabajo y en APPDATA/HOME redirigido, lanza un hijo,
# informa de si ve una variable del entorno del operador, y opcionalmente escribe en el registro (Windows).
APP_V1 = r'''
import os, subprocess, sys, time
VERSION = "1"
data = sys.stdin.read()
os.makedirs("estado", exist_ok=True)
with open(os.path.join("estado", "datos.txt"), "w", encoding="utf-8") as f:
    f.write(f"v{VERSION}:{data.upper()}")
conf = os.path.join(os.environ.get("APPDATA") or os.environ.get("HOME") or ".", "muestra.ini")
os.makedirs(os.path.dirname(conf), exist_ok=True)
with open(conf, "a", encoding="utf-8") as f:
    f.write(f"arranques+=1 v{VERSION}\n")
if "--hijo" in sys.argv:
    subprocess.run([sys.executable, "-c", "import time; time.sleep(0.6)"], check=True)
if "--registro" in sys.argv:
    import winreg
    key = sys.argv[sys.argv.index("--registro") + 1]
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as h:
        winreg.SetValueEx(h, "arranques", 0, winreg.REG_SZ, "v" + VERSION)
print("cwd=" + os.getcwd())
print("secreto_visible=" + str("EOLFI_OBS_SECRETO_PRUEBA" in os.environ))
print("eco=" + data.strip())
sys.stderr.write("aviso v" + VERSION + "\n")
sys.exit(0 if data.strip() else 3)
'''

APP_V2 = APP_V1.replace('VERSION = "1"', 'VERSION = "2"').replace(
    'sys.exit(0 if data.strip() else 3)', 'sys.exit(7 if data.strip() == "fallo" else 0 if data.strip() else 3)')

NONDETERMINISTIC = r'''
import uuid
print(uuid.uuid4())
'''

SLEEPER = r'''
import subprocess, sys, time
subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
time.sleep(30)
'''

CRASH = r'''
import os, signal, sys
if os.name == "nt":
    os._exit(-1073741819)          # 0xC0000005 STATUS_ACCESS_VIOLATION
os.kill(os.getpid(), signal.SIGTERM)
'''


def write(dirpath: Path, name: str, source: str) -> Path:
    p = Path(dirpath, name)
    p.write_text(source, encoding="utf-8")
    return p
