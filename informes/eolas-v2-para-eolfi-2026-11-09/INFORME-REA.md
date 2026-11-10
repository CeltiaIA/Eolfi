# Gemma 4 12B IT Q5_K_M — REA static analysis

## Alcance

Inspección estática del GGUF con REA `inspect_model_artifact`; no se cargó el modelo, no se interpretó el payload de tensores y no se ejecutó ningún runtime. La inspección completa transmitió el archivo únicamente para calcular SHA-256.

## Identidad y observaciones

- Archivo: `D:\AI\Hydra\gguf\gemma-4-12b-it-Q5_K_M.gguf`
- Tamaño: 8,413,576,000 bytes (≈ 7.84 GiB)
- SHA-256 completo: `32c554c7d1338a23837ae39b3db482213a4a642f96df3b2619f516a2375d16cd`
- Encabezado GGUF v3, little-endian, alineación 32; datos de tensores desde el offset 15,824,192.
- Declaración de arquitectura: `gemma4`; nombre: `Gemma-4-12B-It`; 11,907,350,576 parámetros derivados; 667 tensores; 58 claves de metadatos.
- Tipos: 285 Q5_K, 44 Q6_K y 338 F32. El tamaño en bytes de los tensores K no se pudo resolver de forma inequívoca; no afirmamos que la tabla de tensores valide físicamente el payload.
- Metadatos declaran contexto máximo 262,144 y contienen `tokenizer.chat_template`; esto no demuestra soporte del runtime ni calidad de inferencia.
- El nombre de archivo indica Q5_K_M, pero REA observó que el tipo general es 17 y los tensores K son de tamaños ambiguos entre perfiles GGUF conocidos. Se conserva como dato declarado, no como validación completa de cuantización.

## RTX 3060 Ti: perfil inicial propuesto

El archivo ocupa aproximadamente 8,028 MiB frente a los 8,192 MiB observados en la GPU, antes de reservar memoria para runtime, caché KV, buffers y contexto; por tanto, no hay margen razonable para cargar todos los pesos en VRAM. El script propone 8 capas GPU y contexto 2,048 para comenzar con descarga parcial a CPU. Es un punto de partida conservador, no una garantía de que arranque o que quepa en memoria. Baje `-GpuLayers` o use 0 si aparece OOM; aumente gradualmente solo midiendo la VRAM disponible. El perfil no aplica el contexto declarado de 262,144.

## Uso del lanzador

1. Coloque un `llama-server.exe` compatible en esta carpeta o pase `-RuntimePath` con su ruta.
2. Ejecute en PowerShell:

   ```powershell
   .\run-gemma4-3060ti.ps1 -RuntimePath 'C:\ruta\llama-server.exe'
   ```

3. Abra `http://127.0.0.1:8080`. El servidor solo escucha en loopback.

El lanzador no instala ni descarga software. Llama.cpp debe estar compilado con backend CUDA compatible y soporte para la arquitectura Gemma 4 en la versión instalada.

## Estado de verificación

- REA inspección del formato/cabecera y metadatos: observada.
- SHA-256 completo del archivo: observado.
- Inventario de 667 declaraciones de tensor: paginado completo por REA; tamaños de almacenamiento K parciales/desconocidos.
- Compatibilidad de llama.cpp/Gemma 4: **NO VERIFICADO**.
- Arranque, consumo real de VRAM, velocidad, salida y smoke test: **NO VERIFICADO**; no se ejecutó el modelo ni el runtime.
- No se inspeccionó un árbol de código fuente del modelo: el objetivo es un único GGUF con metadatos y pesos, no código fuente. El inventario completo está en `tensor-inventory.csv`.

## Evidencia REA

El bundle íntegro se entrega en `rea-evidence.json` (6 registros, 676,589 bytes; el ledger residual está vacío, mientras que las vistas sí enumeran límites y unknowns). Evidencia principal:
- Cabecera + SHA completo: `ev_ec23aca6d8738279cf70b425f974275dbd9ed148e9c93e75c0fa79557d07e1d5`
- Vista resumen derivada: `ev_a7279dd73ff80c47ceb1589917dd6650104829b086068f74f68068e5f3a8af45`
- Inventario de tensores: `ev_88c60d4d31f9438ccd3a490c4ab162c6d4e494ecc43c19f8d224710cecd6c8f4`
- Metadatos completos (valores de arrays limitados a vista previa): `ev_1bf8f22f8b14b11a79669e2639a8e01d0d19308ec4f7b68ea5f36b5b6b351634`
- Perfiles de tipo: `ev_3835f98fc7d4611407c733f3805f309eae0e4b0f3cf1ff77fca9f12e0e80b647`

Proveedor de inspección: REA model header reader v1; proyecciones: rea-analysis-view v1.

## Comprobación estructural adicional (derivada localmente)

Se multiplicaron las dimensiones declaradas de cada fila de `tensor-inventory.csv` y se sumaron los 667 resultados: **11,907,350,576**, igual al recuento de parámetros derivado por REA. No detecta valores de peso alterados, corrupción de bloques ni compatibilidad de ejecución. Hay 329 filas con longitud de almacenamiento no resuelta por la ambigüedad de los bloques K; esto permanece pendiente del formato/payload y no se corrige inventando tamaños.

## Equipo observado

- GPU informada por nvidia-smi: NVIDIA GeForce RTX 3060 Ti, 8,192 MiB.
- llama-server.exe: no encontrado en PATH al momento de la comprobación.
- Comandos de detección: Get-Command llama-server.exe y 
vidia-smi --query-gpu=name,memory.total --format=csv,noheader.

## Verificación de ejecución (2026-11-09)

- Runtime: backend CUDA 12 de LM Studio en `llama.cpp-win-x86_64-nvidia-cuda12-avx2-2.53.0`; `llama-server --version` informó `0.6.0-dev`, build 1, commit `3109914`.
- La ayuda reconoció `--n-gpu-layers`, `--ctx-size`, `--batch-size` y `--ubatch-size`.
- Se ejecutó el lanzador con `-GpuLayers 8 -Context 16000`. Log: modelo cargado, listener en `127.0.0.1:8080`, `n_ctx_slot=16128`. GET `/health` devolvió `{"status":"ok"}`.
- `nvidia-smi` observó 6,791 MiB usados y 80% de utilización durante la comprobación. Es una lectura global de la GPU; el log no confirmó por separado el número exacto de capas efectivamente descargadas. El parámetro 8 sí se pasó al runtime.
- El runtime emitió avisos de que los tokens `<eos>`, `<|tool_response>` y `</s>` parecían tokens especiales pero no estaban tipados como control; luego quitó `</s>` de la lista EOG. La carga y el endpoint funcionaron, pero estos avisos pueden afectar el manejo de fin de turno/herramientas. No se corrigió el GGUF porque no se comparó con una fuente canónica.
- No se envió ningún prompt: inferencia, calidad de respuesta y uso de Gemma 4 (incluido el tokenizer en generación) siguen **NO VERIFICADOS**.
- El servidor se detuvo tras la comprobación; el puerto 8080 dejó de escuchar. El lanzador PowerShell tiene 0 errores de sintaxis.

Resultado: **arranque y health check verificados para este runtime y esta máquina**; **offload exacto por capa y generación no verificados**.
- El runtime avisó que no se configuró API key y que CORS acepta todos los orígenes; durante la verificación el bind fue solo loopback (`127.0.0.1`).

## Re-test de contexto 32,000 (2026-11-09)

- Se cambió el valor predeterminado del lanzador a Context=32000; sintaxis PowerShell: 0 errores.
- Ejecución del lanzador con 8 capas GPU y contexto 32,000: el log reportó n_ctx_slot=32000, modelo cargado y listener en 127.0.0.1:8080.
- GET /health: {"status":"ok"}.
- Durante la consulta: RTX 3060 Ti, 6,016 MiB usados de 8,192 MiB y 2,009 MiB libres; GPU 3%. Lectura global del dispositivo.
- Tras detener el servidor: 3,756 MiB usados, 4,269 MiB libres y ningún listener en el puerto 8080.
- No se envió prompt ni se verificó generación. Se repitieron los avisos de clasificación de tokens descritos arriba; el runtime logró iniciar y pasar health check pese a ellos.

Resultado: carga y health check verificados a contexto 32,000 en esta máquina con este runtime. La calidad de inferencia y el número exacto de capas GPU efectivamente residentes siguen sin verificarse por separado.
