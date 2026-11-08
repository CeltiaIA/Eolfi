# Controlador de UI Automation (Windows) para los pasos «desktop» de una sesión de observación de Eolfi.
#
#   powershell -NoProfile -STA -File uia_driver.ps1 request.json   → JSON por stdout
#
# request: { pid, timeout_ms, actions: [{id, do, automation_id?, name?, value?}], close }
# Acciones: invoke (pulsar), set_value (escribir), toggle, select, wait_for, read (solo instantánea).
# Tras cada acción registra las ventanas del proceso y su árbol de accesibilidad (tipo, nombre, AutomationId,
# valor, habilitado), acotado. No interactúa con ventanas de otros procesos.
param([string]$RequestPath)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
if (-not ([System.Management.Automation.PSTypeName]'EolfiWindowCapture').Type) {
  Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class EolfiWindowCapture {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr handle, out RECT rect);
}
'@
}
$req = Get-Content -Raw -Encoding UTF8 $RequestPath | ConvertFrom-Json
$deadline = (Get-Date).AddMilliseconds([int]$req.timeout_ms)
$procCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, [int]$req.pid)

function Windows {
  [System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, $procCond)
}

function Describe($e) {
  $c = $e.Current
  $o = [ordered]@{ type = $c.ControlType.ProgrammaticName -replace '^ControlType\.', ''; name = $c.Name;
    automation_id = $c.AutomationId; enabled = $c.IsEnabled }
  $vp = $null
  if ($e.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$vp)) { $o.value = $vp.Current.Value }
  $tp = $null
  if ($e.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$tp)) { $o.toggle = "$($tp.Current.ToggleState)" }
  $o
}

function Snapshot {
  $wins = @()
  foreach ($w in (Windows)) {
    $items = @()
    $all = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
    $n = 0
    foreach ($e in $all) { if ($n -ge 300) { break }; $items += ,(Describe $e); $n++ }
    $wins += ,([ordered]@{ title = $w.Current.Name; class = $w.Current.ClassName; elements = $items; truncated = ($all.Count -gt 300) })
  }
  ,$wins
}

$script:screenshotCount = 0
function CaptureWindow($window) {
  if (-not $req.screenshots) { return @{ status = 'not_requested' } }
  if ($script:screenshotCount -ge 20) { return @{ status = 'limit_reached'; limit = 20 } }
  $script:screenshotCount++
  try {
    $rect = New-Object EolfiWindowCapture+RECT
    $handle = [IntPtr]$window.Current.NativeWindowHandle
    if ($handle -eq [IntPtr]::Zero -or -not [EolfiWindowCapture]::GetWindowRect($handle, [ref]$rect)) {
      return @{ status = 'window_bounds_unavailable' }
    }
    $width = $rect.Right - $rect.Left; $height = $rect.Bottom - $rect.Top
    if ($width -lt 1 -or $height -lt 1 -or $width -gt 16000 -or $height -gt 16000) {
      return @{ status = 'invalid_window_bounds' }
    }
    Add-Type -AssemblyName System.Drawing
    $scale = [Math]::Min(1.0, [Math]::Min(1280.0 / $width, 800.0 / $height))
    $outWidth = [Math]::Max(1, [int][Math]::Round($width * $scale))
    $outHeight = [Math]::Max(1, [int][Math]::Round($height * $scale))
    $source = New-Object System.Drawing.Bitmap($width, $height)
    $graphics = [System.Drawing.Graphics]::FromImage($source)
    try {
      $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $source.Size)
      $scaled = New-Object System.Drawing.Bitmap($outWidth, $outHeight)
      $scaledGraphics = [System.Drawing.Graphics]::FromImage($scaled)
      try {
        $scaledGraphics.DrawImage($source, 0, 0, $outWidth, $outHeight)
        $stream = New-Object System.IO.MemoryStream
        try {
          $scaled.Save($stream, [System.Drawing.Imaging.ImageFormat]::Jpeg)
          $bytes = $stream.ToArray()
          if ($bytes.Length -gt 262144) { return @{ status = 'over_budget'; bytes = $bytes.Length; max_bytes = 262144 } }
          $sha = [System.Security.Cryptography.SHA256]::Create()
          try { $digest = [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '').ToLowerInvariant() }
          finally { $sha.Dispose() }
          return @{ status = 'captured'; mime_type = 'image/jpeg'; width = $outWidth; height = $outHeight;
                    bytes = $bytes.Length; sha256 = $digest; data_base64 = [Convert]::ToBase64String($bytes) }
        } finally { $stream.Dispose() }
      } finally { $scaledGraphics.Dispose(); $scaled.Dispose() }
    } finally { $graphics.Dispose(); $source.Dispose() }
  } catch {
    return @{ status = 'capture_error'; error = "$($_.Exception.Message)".Substring(0, [Math]::Min(300, "$($_.Exception.Message)".Length)) }
  }
}

function Find($a) {
  foreach ($w in (Windows)) {
    if ($a.automation_id) {
      $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, [string]$a.automation_id)
    } else {
      $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, [string]$a.name)
    }
    $e = $w.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
    if ($e) { return $e }
  }
  $null
}

$out = [ordered]@{ status = 'ok'; actions = @() }
try {
  while (-not (Windows) -or (Windows).Count -eq 0) {
    if ((Get-Date) -gt $deadline) { throw 'la aplicación no abrió ninguna ventana a tiempo' }
    Start-Sleep -Milliseconds 100
  }
  # La ventana existe antes de terminar de construirse: se espera a dos instantáneas iguales seguidas (máx. 5 s).
  $stable = (Get-Date).AddSeconds(5)
  $prev = Snapshot | ConvertTo-Json -Depth 12 -Compress
  while ((Get-Date) -lt $stable) {
    Start-Sleep -Milliseconds 250
    $cur = Snapshot | ConvertTo-Json -Depth 12 -Compress
    if ($cur -eq $prev) { break }
    $prev = $cur
  }
  $acts = @([pscustomobject]@{ id = '_inicio'; do = 'read' }) + @($req.actions)
  foreach ($a in $acts) {
    $r = [ordered]@{ id = $a.id; do = $a.do; target = if ($a.automation_id) { "id:$($a.automation_id)" } elseif ($a.name) { "name:$($a.name)" } else { '' } }
    try {
      if ($a.do -ne 'read') {
        $e = $null
        while (-not ($e = Find $a)) {
          if ((Get-Date) -gt $deadline) { throw "no se encontró el elemento $($r.target)" }
          Start-Sleep -Milliseconds 100
        }
        switch ($a.do) {
          'invoke' { $e.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke() }
          'set_value' { $e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue([string]$a.value) }
          'toggle' { $e.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern).Toggle() }
          'select' { $e.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select() }
          'wait_for' { }
          default { throw "acción no admitida: $($a.do)" }
        }
      }
      $r.status = 'ok'
    } catch {
      $r.status = 'error'; $r.error = "$($_.Exception.Message)".Substring(0, [Math]::Min(500, "$($_.Exception.Message)".Length))
      $out.status = 'partial'
    }
    Start-Sleep -Milliseconds 300
    $r.windows = Snapshot
    if ($req.screenshots) {
      $window = Windows | Select-Object -First 1
      $r.screenshot = if ($window) { CaptureWindow $window } else { @{ status = 'no_window' } }
    }
    $out.actions += ,$r
  }
  if ($req.close) {
    foreach ($w in (Windows)) {
      $wp = $null
      if ($w.TryGetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern, [ref]$wp)) { $wp.Close() }
    }
  }
} catch {
  $out.status = 'error'; $out.error = "$($_.Exception.Message) $($_.InvocationInfo.ScriptLineNumber): $($_.InvocationInfo.Line.Trim())"
}
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$out | ConvertTo-Json -Depth 12 -Compress
