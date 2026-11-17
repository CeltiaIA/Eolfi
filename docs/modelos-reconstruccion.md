# Reconstrucción por cuantización: receta y ejecución local

`modelos reconstruir` prepara una receta para convertir un GGUF flotante monolítico con un cuantizador
local ya instalado. Se admiten entradas F32, F16 y BF16 y los presets Q4_0, Q3_K_M, Q4_K_M, Q5_K_M, Q6_K y Q8_0.
Se rechazan pesos ya cuantizados, entradas divididas (también renombradas) y cantidades de capas inválidas.
La compatibilidad semántica completa del modelo con el SDK sigue requiriendo una ejecución y un smoke.

## Preparar

```powershell
python -m eolfi modelos reconstruir 'D:\AI\Hydra\gguf\gemma-4-12b-it-BF16.gguf' --out 'D:\Eolfi\generated\modelos\gemma4-q4_k_m-2026-11-16' --cuantizador 'D:\EOLAS-BASE\llama\llama-quantize.exe' --tipo Q4_K_M
```

Por defecto no ejecuta el cuantizador ni crea la carpeta de salida: imprime JSON con `estado: preparado`
y `ejecutado: false`, código 0. Lee el archivo completo para calcular su SHA-256. La receta contiene el
hash de entrada, nombres/formas de tensores, metadatos del planificador, plantilla, argumentos, límites
y la identidad del ejecutable y sus bibliotecas locales. No descarga herramientas ni modelos.

`herramienta.bundle_sha256` identifica el ejecutable más los nombres/hashes de las DLL, SO o dylib de su
carpeta. Fijar solo el hash del pequeño ejecutable lanzador no identifica su implementación en DLL.
El hash del paquete no demuestra procedencia, seguridad ni qué bibliotecas del sistema se cargarán.

## Ejecutar una receta revisada

Se usa la misma orden, añadiendo `--ejecutar`, `--sha256-entrada HASH` y `--sha256-paquete HASH`, con los
valores revisados de la preparación. `--sha256-cuantizador HASH` permite fijar también el ejecutable de
forma explícita. La CLI vuelve a preparar/verificar los datos; no ejecuta argumentos de un JSON arbitrario.

Parámetros: `--hilos` (1–64, predeterminado 4), `--memoria-mib` (16–4096, predeterminado 256) y `--timeout`
(hasta 86400 s, predeterminado 1800). La memoria es el buffer que acepta el cuantizador, **no un límite de
RAM del sistema**. El timeout acota el proceso de cuantización; la lectura previa y los hashes/auditorías
posteriores pueden tardar más. Se exige espacio libre conservador: tamaño de entrada más 64 MiB.

La carpeta de salida debe ser nueva. Contiene `modelo.gguf`, `cuantizador.log` y `receta.json` actualizada
durante el trabajo y al acabar. Se comprueban código de salida, estructura, arquitectura, plantilla,
metadatos del planificador y nombres/formas de tensores; después se vuelve a hashear el original.
`declaraciones_tensores_sha256` resume nombres/formas, no los valores de los pesos ni su equivalencia funcional.
El límite de registro es 16 MiB y el de salida, tamaño de entrada más 64 MiB.

Los fallos conservan el registro y los archivos parciales, sin sobrescribir un destino previo. Ctrl+C intenta
cerrar solo el proceso de esta cuantización y deja `interrumpido`; si se interrumpe el hash final, este queda
NO VERIFICADO. Un cierre forzado externo puede dejar el último estado `en_ejecucion`: hay que revisar PID y
artefactos, no asumir finalización. Si no se puede confirmar el cierre del proceso, se registra el límite.

## Resultado y siguientes comprobaciones

Incluso con código 0 del cuantizador, la CLI devuelve **2** y `estado: NO VERIFICADO`: faltan inferencia y
banco. Para distinguir una conversión terminada de un fallo, revisar `conversion.exit`, `conversion.error`,
`auditoria_salida`, `sha256_entrada_despues` y `verificacion`. Una salida del SDK distinta de cero o una
discrepancia de integridad da `fallido`. La versión que imprime el SDK se conserva como declaración del
programa, no como verificación de la release oficial.

Los presets pueden mezclar tipos: en la muestra probada, Q4_0 también genera un tensor Q6_K. Los tamaños K
con layout ambiguo permanecen NO VERIFICADOS. La cuantización no cambia perfiles ni autoriza hashes en la
lista de confianza; la adopción y el smoke corresponden a G6. Los indicadores offline del proceso no
sustituyen el cortafuegos ni implementan por sí solos el modo sin red de G3.

El proceso recibe solo variables de sistema, rutas y configuración regional necesarias. No hereda claves
del cliente, proxies ni direcciones privadas de registros pip/npm. Esto reduce la información entregada
al cuantizador, pero no demuestra que el ejecutable sea seguro ni le impide acceder a archivos o a la red.

## Smoke de inferencia en CPU

`modelos probar` es el paso siguiente e independiente: carga la reconstrucción con un ejecutor local de
llama.cpp (`llama-cli`) y le hace una pregunta con respuesta conocida.

```powershell
python -m eolfi modelos probar 'D:\Eolfi\generated\modelos\gemma4-q4_k_m-2026-11-17' --ejecutor 'D:\EOLAS-BASE\llama\llama-cli.exe'
```

Se usa `llama-cli` y no `llama-completion` porque en la build b11968 `llama-completion -cnv` añade un mensaje
de sistema vacío con `<|think|>` aunque se pida `-rea off`; con Gemma 4 el modelo se pasaba los tokens
pensando y no respondía (dos intentos del 17/11 conservados en la carpeta de la reconstrucción).

Sin `--ejecutar` solo prepara: exige una `receta.json` de conversión terminada sin errores, vuelve a hashear
`modelo.gguf` contra el SHA-256 de salida de la receta e identifica el ejecutor y sus bibliotecas. No lanza
ningún proceso ni escribe en la carpeta. Para ejecutar se añade `--ejecutar --sha256-paquete HASH` con el
`herramienta.bundle_sha256` revisado; ese hash es distinto del paquete del cuantizador porque incluye el
ejecutable. `--pregunta` y `--esperado` se indican juntos; `--tokens` (1–512), `--hilos` y `--timeout`.

La ejecución es solo CPU (`--device none -ngl 0`), determinista (`--temp 0 --seed 1`), con razonamiento
desactivado (`-rea off` y `--chat-template-kwargs '{"enable_thinking":false}'`) y con la plantilla de chat
del propio GGUF. No abre puertos ni reserva VRAM, así que puede hacerse con otro
motor en marcha; sí usa RAM por el tamaño del modelo, sin límite impuesto. El proceso recibe el mismo
entorno reducido que el cuantizador. Cada ejecución deja `inferencia-FECHA.json`, `.salida.txt` y `.log`
nuevos; `receta.json` no se modifica. Después se vuelve a hashear el modelo.

La respuesta se toma solo del tramo entre el eco `> pregunta` de `llama-cli` y su línea `[ Prompt: …`;
si no aparecen esas marcas no hay respuesta identificable y el smoke falla, sin buscar el valor en la
pancarta ni en la pregunta. Dentro de ese tramo se descartan el canal de pensamiento de Gemma (hasta
`<channel|>`) y los bloques `<think>`, también los truncados. Resultado `smoke_superado` (código 0) si el
proceso termina 0 y esa respuesta contiene el valor esperado como palabra completa; en otro caso `fallido`
(código 2). El formato de salida de `llama-cli` puede cambiar entre builds: un cambio daría `fallido`, no un
falso positivo. **Código 0 significa solo que esa pregunta se
respondió bien**: `verificacion.banco` sigue NO VERIFICADO. No mide calidad ni velocidad en GPU, no ejercita
el servidor, las herramientas ni el planificador de Eolas, y no adopta el modelo. La velocidad y la versión
que aparecen se copian del registro del programa como declaración suya.

## Preparar el perfil de Eolas

Después de un smoke superado, `eolas-v2 plan` vuelve a auditar el GGUF y enlaza la receta y el smoke por
el mismo SHA-256. Comprueba que el contexto no supere `*.context_length`, que las capas GPU no superen
`*.block_count`, y valida la ventana deslizante cuando el modelo la declara.

```powershell
python -m eolfi eolas-v2 plan 'D:\Eolfi\generated\modelos\gemma4-q4_k_m-2026-11-17' `
  --profile gemma4_recon_q4 --ctx 32000 --gpu-layers 8 --batch 128 --ubatch 64
```

La orden solo devuelve una propuesta: `adoptado: false`. No escribe la configuración, no cambia el perfil
activo y no arranca el servidor. Conserva como límites el banco pendiente, los layouts K no cubiertos y la
necesidad de medir memoria y rendimiento antes de elegir capas GPU, batch y ubatch definitivos.

La adopción tiene otra vista previa y exige volver a escribir el SHA-256 revisado:

```powershell
python -m eolfi eolas-v2 adoptar '.\informes\modelos-g-2026-11-16\g6-plan-real.json' `
  --sha256-modelo d5afb9efb2fa6e39cf9d64e96292f13f5b20c381789643fc9b6f15c9fdc3b054
```

Sin `--aplicar` revalida el modelo, receta, smoke, metadatos y propuesta, y deja la configuración intacta.
Con `--aplicar` añade un perfil nuevo gestionado, fijado al SHA-256 y con pensamiento desactivado; no permite
`extra_args`, no sobrescribe perfiles y no selecciona ni arranca el nuevo perfil. La selección y la prueba del
servidor son pasos posteriores. Los perfiles gestionados verifican su SHA-256 antes de construir los argumentos
de arranque.

Un perfil gestionado que no esté activo ni cargado puede retirarse sin borrar el modelo ni sus evidencias:

```powershell
python -m eolfi eolas-v2 quitar-perfil gemma4_recon_q4 `
  --sha256-modelo d5afb9efb2fa6e39cf9d64e96292f13f5b20c381789643fc9b6f15c9fdc3b054
```

La retirada exige el mismo SHA-256 fijado y rechaza perfiles predeterminados, activos o cargados.

## Modo sin red de Eolas V2

Antes de arrancar el servidor puede solicitarse el modo offline de llama.cpp:

```powershell
$env:EOLAS_OFFLINE = '1'
python -m eolfi eolas-v2 start --profile gemma4_recon_q4
```

Eolfi añade `--offline` y pasa `LLAMA_ARG_OFFLINE=1`, `HF_HUB_OFFLINE=1` y
`TRANSFORMERS_OFFLINE=1`. El runtime registra el modo y no reutiliza silenciosamente un servidor iniciado
con otro valor. `eolas-v2 status` distingue el modo solicitado y el modo del proceso. Esto reduce la superficie
de red del motor, pero **no verifica el cortafuegos del sistema**: la regla de salida de G3 sigue siendo una
acción separada del titular.

## Pruebas nativas optativas

```powershell
$env:EOLFI_TEST_QUANTIZER = 'D:\EOLAS-BASE\llama\llama-quantize.exe'
$env:EOLFI_TEST_QUANTIZER_SHA256 = 'SHA256_REVISADO_DEL_EJECUTABLE'
python -m pytest -q tests/test_modelos_reconstruir.py
```

Sin esas variables, las seis conversiones nativas se omiten explícitamente; las pruebas de control siguen
ejecutándose. Con ellas, se cuantiza un BF16 sintético propio de una capa, se comprueban los seis presets y
se decodifica Q8 para comprobar error numérico menor de 0,003 en la matriz de referencia. Esa prueba no
demuestra la calidad de un modelo real. Las evidencias locales están en
`informes/modelos-g-2026-11-16/avance-g4-reconstruccion.md`.
