# G3 · Acotar la entrada de python.exe al puente de la tableta (decisión de Luis, 20/11/2026).
#
# Ejecutar en PowerShell COMO ADMINISTRADOR (lo ejecuta Luis; Claude no cambia el cortafuegos):
#   powershell -ExecutionPolicy Bypass -File D:\Eolfi\informes\g3-acotar-python-18779-2026-11-20.ps1
#
# Qué hace:
#   1. Copia de seguridad de TODA la política del cortafuegos (.wfw) para poder volver atrás.
#   2. DESACTIVA (no borra) las 4 reglas «python.exe» que hoy admiten entradas TCP/UDP en todos los puertos
#      (perfiles Público y Privado).
#   3. Crea una regla única: TCP 18779 (eolfi tableta-puente) solo desde la LAN 192.168.1.0/24 y Tailscale
#      100.64.0.0/10. El 8777 escucha en 127.0.0.1 y no necesita regla.
#
# Volver atrás: ejecutar con -Deshacer (reactiva las 4 reglas y quita la nueva), o importar la copia con
#   netsh advfirewall import "<ruta .wfw>"
param([switch]$Deshacer)
$ErrorActionPreference = 'Stop'

$python = 'C:\users\mejil\appdata\local\programs\python\python312\python.exe'
$abiertas = @(
  'TCP Query User{25FDEA66-4C14-48A9-A65D-7DE49C2E858D}C:\users\mejil\appdata\local\programs\python\python312\python.exe',
  'UDP Query User{B0234858-CBD1-4A28-8F41-8F55FCA104F2}C:\users\mejil\appdata\local\programs\python\python312\python.exe',
  'TCP Query User{18EBCB2F-DF00-4857-91B6-0588539754EF}C:\users\mejil\appdata\local\programs\python\python312\python.exe',
  'UDP Query User{07A82C66-088C-4B01-A08B-D11FA974F00D}C:\users\mejil\appdata\local\programs\python\python312\python.exe'
)
$nueva = 'Eolfi tableta-puente 18779 (LAN + Tailscale)'

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw 'Abre PowerShell como administrador.' }

if ($Deshacer) {
  foreach ($n in $abiertas) { Enable-NetFirewallRule -Name $n }
  Get-NetFirewallRule -DisplayName $nueva -ErrorAction SilentlyContinue | Remove-NetFirewallRule
  Write-Host 'Deshecho: reglas python.exe reactivadas y regla 18779 retirada.'
  return
}

$copia = Join-Path $env:USERPROFILE (".eolfi\cortafuegos-antes-g3-{0}.wfw" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force (Split-Path $copia) | Out-Null
netsh advfirewall export "$copia" | Out-Null
if (-not (Test-Path $copia)) { throw "No se pudo guardar la copia en $copia; no se cambia nada." }
Write-Host "Copia de la política: $copia"

if (-not (Get-NetFirewallRule -DisplayName $nueva -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -DisplayName $nueva -Direction Inbound -Action Allow -Program $python -Protocol TCP `
    -LocalPort 18779 -RemoteAddress 192.168.1.0/24, 100.64.0.0/10 -Profile Private, Public | Out-Null
}
foreach ($n in $abiertas) { Disable-NetFirewallRule -Name $n }

Write-Host 'Hecho. Estado:'
Get-NetFirewallApplicationFilter | Where-Object { $_.Program -like '*python312\python.exe' } | ForEach-Object {
  $r = $_ | Get-NetFirewallRule; $p = $r | Get-NetFirewallPortFilter; $a = $r | Get-NetFirewallAddressFilter
  '{0,-8} {1,-7} {2,-5} puerto {3,-6} desde {4}  [{5}]' -f $r.Enabled, $r.Profile, $p.Protocol, $p.LocalPort,
    ($a.RemoteAddress -join ','), $r.DisplayName
}
