# G4: reconstrucción local por cuantización — 16/11/2026

Estado: flujo implementado y probado con muestras propias; reconstrucciones de modelos reales,
inferencia y banco **NO VERIFICADOS**. Rama `codex/modelos-reconstruccion`, sin commits ni publicación.
Se conservan los cambios anteriores de G1/G2 y de adjuntos grandes.

## Cambio y alcance

`python -m eolfi modelos reconstruir` prepara una receta sin ejecutar ni crear salida. La ejecución
explícita exige hashes revisados de entrada y paquete del cuantizador, destino nuevo, y conserva receta,
registro, SHA-256 de entrada/salida y auditorías. Admite BF16/F16/F32 monolítico y seis presets; rechaza
requantización, entradas divididas y capas declaradas inválidas. Comprueba identidad de DLL locales,
argumentos, espacio, tiempo, presupuesto de registro/salida y original después de la conversión.
No cambia perfiles, lista de confianza, configuración del motor ni cortafuegos.

El entorno del hijo contiene solo variables de sistema/rutas/idioma e indicadores offline; no transmite
claves del cliente, proxies ni registros privados pip/npm. No constituye aislamiento de red ni prueba de
seguridad. La memoria indicada es buffer del cuantizador, no un límite de RAM impuesto por el SO.
La CLI devuelve 2 incluso tras conversión con salida 0: inferencia y banco pendientes. Un fallo real da
`fallido`, conserva parciales y no sustituye archivos previos. Guía: [modelos-reconstruccion.md](../../docs/modelos-reconstruccion.md).

## Identidad y proveedor

- Plataforma: Windows x64, Python 3.12.10 en
  `C:\Users\mejil\AppData\Local\Programs\Python\Python312\python.exe`; Node v24.22.1.
- Herramienta existente: `D:\EOLAS-BASE\llama\llama-quantize.exe`.
- SHA-256 ejecutable: `3da7b6058d055f99c9f3f012d6e3981aa2021958fc8e8078fbd2891d4dc282a4`.
- Paquete con 33 bibliotecas locales: `33c8f441079190342b65acb13ca6479ab72ac5037ccfe10e1661d18e947a5262`.
- Versión autodeclarada: 0.8.0-dev, build 11968, commit ac8e1694d; Clang 20.1.8 Windows x64.
  Procedencia respecto de una release oficial **NO VERIFICADA**.
- REA `rea-pe-imports` v1: PE AMD64, 8 descriptores DLL y 35 imports en el lanzador de 9216 bytes.
  Inspección estática, sin demostrar seguridad ni cobertura de módulos dinámicos/sistema.
  [Resultado completo](rea-cuantizador-imports.json).

## Ejecución real sobre muestra propia

BF16 sintético determinista de una capa, 12 tensores y vocabulario de prueba, generado por
`tests/ggufgen.py`; no es un modelo útil para inferencia. Se ejecutaron Q4_0, Q3_K_M, Q4_K_M,
Q5_K_M, Q6_K y Q8_0 con el cuantizador local. Cada proceso terminó 0 y el original conservó su SHA-256.
Las seis recetas `g4-native-*.json` y sus logs registran tiempos, arquitectura, plantilla,
planificador, formas y hashes. Q4_0 mezcla 8 tensores Q4_0, uno Q6_K y tres F32: no se asume pureza
de tipos por el nombre del preset. Los layouts K ambiguos quedan NO VERIFICADOS.

Q8_0: salida 510112 bytes, SHA-256
`e6e5c31cce83805c72b464ee8572ba32aa43da77c5f3abdd0d25a8db276ee83a`.
La prueba decodifica independientemente los 8192 elementos de embedding Q8 y compara con BF16:
error absoluto máximo mayor de cero y menor de 0,003. Esto comprueba esa matriz sintética,
no equivalencia funcional ni calidad de modelos reales.

Smoke público CLI: vista previa sin salida y ejecución con pins; conversión 0, CLI 2 y estado
NO VERIFICADO según contrato. Evidencias: [vista previa](g4-smoke-receta-previa.json),
[resultado CLI](g4-smoke-cli.json). Entrada y salida pequeñas conservadas en
`generated/modelos/g4-smoke-2026-11-16/`, registradas en LIM-G-005.

Contraste estático REA sobre esa salida Q8: GGUF v3, 19 metadatos, 12 tensores de dos tipos,
507904 bytes de tensores y 475904 parámetros; rangos de almacenamiento completos.
Las vistas de arrays se acotan a 8 elementos; los pesos no se interpretan ni se ejecuta inferencia.
Proveedor/formato de resultado `projection` v1, hash completo coincide:
[g4-rea-q8.json](g4-rea-q8.json).

Se conservan los diagnósticos de una primera muestra sin capas rechazada por el SDK y de la
suposición inicial incorrecta de Q4_0 puro: `g4-fixture-cero-capas.*`, `g4-q4-mixto.*`.
Se corrigió la muestra y la aserción para respetar la salida mixta real; no se relajó la auditoría K.

## Modelo del titular: preparación sin conversión

Se leyó y auditó íntegramente `D:\AI\Hydra\gguf\gemma-4-12b-it-BF16.gguf`:
23832066656 bytes; SHA-256 `5a5eefea73350705c6753105b725a51301d653e8d6646173db29a7e8da8e6efd`;
667 tensores (338 F32 y 329 BF16), arquitectura Gemma4 y 48 capas.
La preparación tardó 148,219 s, código 0, `ejecutado: false`; no creó el destino.
[Receta base](g4-bf16-receta.json). Las seis recetas `g4-bf16-*.json` se derivan de esa misma
preparación, actualizando preset/destino/argv: no son seis auditorías independientes ni ejecuciones.
No se convirtió ni adoptó el modelo real y no se interrumpió el motor activo.

## Validación y límites

Pruebas específicas con opt-in nativo: **99 pasadas en 48,50 s**. Cubren controles previos, hashes,
DLL, entorno sin credenciales, conservación de parciales, timeout, interrupción y seis conversiones.
Opt-in: `EOLFI_TEST_QUANTIZER` con ruta anterior y `EOLFI_TEST_QUANTIZER_SHA256` con hash anterior.

Una primera suite completa terminó 748 pasadas, 2 omitidas (465,93 s). Después del ajuste del entorno
del hijo, otra terminó 747 pasadas, 1 fallo y 2 omitidas (489,89 s): la prueba HTTP de reconstrucción
invocaba pytest del proyecto generado sin fijar directorio/raíz. La colección alcanzó temporales globales
que desaparecían (`playwright_chromiumdev_profile-*`); la repetición aislada reprodujo el problema con
`eolfi-diff-*`. Se fija `cwd`, `--rootdir` y `--confcutdir` al proyecto generado, conservando su carpeta
de pruebas completa. `python -m pytest -q tests/test_reconstruct.py`: **16 pasadas en 53,95 s**.

Repetición final `python -m pytest -q` con opt-in de las seis conversiones nativas:
**748 pasadas, 2 omitidas en 432,91 s, salida 0**. Resultados de este avance:
`node --test` en `eolfi/bridge`: 63 pasadas/4 omitidas; en `eolfi/vscode-bridge`: 192 pasadas;
`npm test` en `tests/e2e`: 19 pasadas; todos salida 0. `git diff --check`: salida 0 (avisos de
normalización CRLF/LF, sin errores de espacios). Las 18 evidencias G4 JSON son legibles y los enlaces
locales principales existen. Sin instalaciones ni cambios a CI. Esta ejecución Windows no sustituye
la matriz CI Linux/Windows y Python 3.10/3.12.

Las seis recetas y logs de la repetición final se conservan en `g4-suite-final/`, además de las evidencias
anteriores; se comprobó salida 0, ausencia de error y coincidencia del hash original en las seis.

Pendiente: conversión real de modelos grandes, inferencia, banco, adopción G6; layouts K y procedencia
del SDK; G3 sin red y G5 actualización. G4 permanece parcial. No hay equivalencia funcional demostrada.
