param(
    [Parameter()]
    [string] $RuntimePath = 'llama-server.exe',

    [Parameter()]
    [string] $ModelPath = 'D:\AI\Hydra\gguf\gemma-4-12b-it-Q5_K_M.gguf',

    [ValidateRange(0, 999)]
    [int] $GpuLayers = 8,

    [ValidateRange(256, 262144)]
    [int] $Context = 32000,

    [ValidateRange(1, 65535)]
    [int] $Port = 8080
)

$ErrorActionPreference = 'Stop'

$runtimeCommand = Get-Command -Name $RuntimePath -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $runtimeCommand) {
    throw "No encuentro un ejecutable para '$RuntimePath'. Comprueba el PATH o pasa -RuntimePath con la ruta completa."
}
if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf)) {
    throw "No encuentro el GGUF en '$ModelPath'. Pasa -ModelPath con la ruta correcta."
}

$resolvedRuntime = $runtimeCommand.Source
$resolvedModel = (Resolve-Path -LiteralPath $ModelPath).Path

Write-Host "Modelo: $resolvedModel"
Write-Host "Runtime: $resolvedRuntime"
Write-Host "Perfil inicial: GPU layers=$GpuLayers, contexto=$Context, batch=128/64"
Write-Warning 'Compatibilidad del modelo y consumo de memoria no verificados. Si hay OOM, vuelve a ejecutar con -GpuLayers 0 o un valor menor.'
Write-Warning 'El servidor escuchará solo en 127.0.0.1.'

$serverArgs = @(
    '--model', $resolvedModel,
    '--n-gpu-layers', $GpuLayers,
    '--ctx-size', $Context,
    '--batch-size', 128,
    '--ubatch-size', 64,
    '--host', '127.0.0.1',
    '--port', $Port
)

& $resolvedRuntime @serverArgs
if ($LASTEXITCODE -ne 0) {
    throw "llama-server terminó con código $LASTEXITCODE. Revisa soporte de arquitectura, backend CUDA y memoria disponible."
}
