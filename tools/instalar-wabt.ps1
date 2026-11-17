# Instala WABT 1.0.42 para el REA de Windows (análisis de módulos WebAssembly: eolfi rea wasm).
#
# REA exige esta versión exacta (comprueba «--version» de wasm-validate, wasm-objdump y wasm2wat). Eolfi pasa la carpeta
# a REA en REA_WABT_BIN_DIRECTORY si está en ~/.eolfi/tools/wabt-1.0.42 (eolfi/rea_client.py, rea_env).
#
#   powershell -ExecutionPolicy Bypass -File tools\instalar-wabt.ps1
#
# Descarga el paquete oficial de https://github.com/WebAssembly/wabt/releases/tag/1.0.42 y lo instala SOLO si su SHA-256
# coincide con el publicado. No toca nada si ya está instalado.
$ErrorActionPreference = "Stop"
$version = "1.0.42"
$name = "wabt-$version-windows-x64.tar.gz"
$sha256 = "62f1eb2b51aa57cf0f0b8ba333bf2c72a049930aa9c5de01dcad271c4fe48c88"
$url = "https://github.com/WebAssembly/wabt/releases/download/$version/$name"
$tools = Join-Path $HOME ".eolfi\tools"
$dest = Join-Path $tools "wabt-$version"

if (Test-Path $dest) {
    Write-Host "WABT $version ya está instalado en $dest"
} else {
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("wabt-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        $file = Join-Path $tmp $name
        Invoke-WebRequest -Uri $url -OutFile $file -UseBasicParsing
        $got = (Get-FileHash -Algorithm SHA256 $file).Hash.ToLowerInvariant()
        if ($got -ne $sha256) { throw "SHA-256 distinto: $got (esperado $sha256). No se instala." }
        New-Item -ItemType Directory -Force -Path $tools | Out-Null
        # El tar de Windows: con Git en el PATH, «tar» puede ser el de GNU, que toma «C:» por un servidor remoto.
        & (Join-Path $env:SystemRoot "System32\tar.exe") -xzf $file -C $tmp
        if ($LASTEXITCODE -ne 0) { throw "tar no pudo extraer $name" }
        Move-Item (Join-Path $tmp "wabt-$version") $dest
    } finally {
        Remove-Item -Recurse -Force $tmp
    }
}
foreach ($t in "wasm-validate", "wasm-objdump", "wasm2wat") {
    $v = & (Join-Path $dest "bin\$t.exe") --version
    if ($v.Trim() -ne $version) { throw "$t informa la versión «$v», no $version" }
    Write-Host "$t $v"
}
