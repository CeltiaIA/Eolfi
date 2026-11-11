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

# Aplicación de escritorio sintética (WinForms en PowerShell): texto → botón → etiqueta en mayúsculas y archivo.
WINFORMS = r'''
Add-Type -AssemblyName System.Windows.Forms
$f = New-Object System.Windows.Forms.Form
$f.Text = 'Muestra Eolfi'
$t = New-Object System.Windows.Forms.TextBox
$t.Name = 'entrada'; $t.AccessibleName = 'Entrada'; $t.Top = 10; $t.Left = 10
$b = New-Object System.Windows.Forms.Button
$b.Name = 'convertir'; $b.Text = 'Convertir'; $b.Top = 40; $b.Left = 10
$l = New-Object System.Windows.Forms.Label
$l.Name = 'resultado'; $l.Text = '(vacio)'; $l.Top = 70; $l.Left = 10; $l.Width = 200
$b.Add_Click({
  $l.Text = $t.Text.ToUpper()
  [Console]::Out.WriteLine('convertido:' + $t.Text)
  Set-Content -Path (Join-Path (Get-Location) 'ultimo.txt') -Value $t.Text -Encoding ASCII
})
$f.Controls.AddRange(@($t, $b, $l))
[void]$f.ShowDialog()
[Console]::Out.WriteLine('cerrado')
'''

# La misma muestra en una posición fija, para poder taparla con otra ventana en la prueba de captura.
WINFORMS_AT = WINFORMS.replace("$f.Text = 'Muestra Eolfi'",
                               "$f.Text = 'Muestra Eolfi'\n$f.StartPosition = 'Manual'; $f.Location = New-Object System.Drawing.Point(120, 120)")

# Ventana magenta, siempre encima y sin borde, que tapa la zona de WINFORMS_AT (otro proceso).
OCCLUDER = r'''
Add-Type -AssemblyName System.Windows.Forms
$o = New-Object System.Windows.Forms.Form
$o.FormBorderStyle = 'None'; $o.TopMost = $true; $o.ShowInTaskbar = $false
$o.StartPosition = 'Manual'; $o.Location = New-Object System.Drawing.Point(60, 60); $o.Size = New-Object System.Drawing.Size(700, 600)
$o.BackColor = [System.Drawing.Color]::FromArgb(255, 0, 255)
[void]$o.ShowDialog()
'''
