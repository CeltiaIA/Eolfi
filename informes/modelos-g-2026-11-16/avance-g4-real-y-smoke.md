# G4: reconstrucción real de Gemma y smoke de inferencia — 17/11/2026

Estado: primera reconstrucción real terminada y respondiendo a una pregunta en CPU. **Banco, layouts K,
adopción (G6) y procedencia del SDK siguen NO VERIFICADOS.** G4 continúa parcial. Rama local
`luis/modelos-reconstruccion`, sin publicar. Continúa [avance-g4-reconstruccion.md](avance-g4-reconstruccion.md).

## Conversión real BF16 → Q4_K_M

Orden pública con hashes fijados: entrada `5a5eefea…6efd`, cuantizador `3da7b605…82a4`, paquete
`33c8f441…5262`, 6 hilos, buffer 256 MiB, timeout 5400 s. Inicio 2026-11-16 23:27 UTC.

- Cuantizador: salida 0, 722,1 s de proceso (607 s de cuantización declarados por el SDK); preparación
  previa 125,8 s y total con hashes y auditorías 947,2 s. CLI con código 2 por contrato (faltaban inferencia y banco).
- Salida `generated/modelos/gemma4-q4_k_m-2026-11-17/modelo.gguf`: 7.381.383.776 bytes, SHA-256
  `d5afb9efb2fa6e39cf9d64e96292f13f5b20c381789643fc9b6f15c9fdc3b054`. 22.712,94 MiB → 7.024,34 MiB
  (4,95 BPW declarados).
- Auditoría de salida: 667 tensores (338 F32, 284 tipo 12 = Q4_K, 45 tipo 14 = Q6_K), arquitectura,
  plantilla, planificador y declaraciones de tensores iguales a la entrada. Estado `NO VERIFICADO`
  porque el auditor no tiene establecidos los tamaños de bloque K (329 tensores): no se relaja esa regla.
- El original BF16 conserva su SHA-256 después de la conversión.
- Evidencia: [g4-real-q4_k_m-receta.json](g4-real-q4_k_m-receta.json).

Comparación con el Q4_K_M publicado en `D:\AI\Hydra\gguf` (auditoría previa, sin volver a leerlo): misma
arquitectura, 667 tensores y planificador idéntico. Difieren el tamaño (7.121.860.000 bytes el publicado) y el
SHA-256 de la plantilla de chat (`36e3a42e…` el publicado, `845f1ee4…` el BF16 y la reconstrucción). No se
sabe con qué versión, receta o matriz de importancia se hizo el publicado: la diferencia **no indica** cuál es mejor.

## Smoke de inferencia: `modelos probar`

Orden nueva y separada de la conversión. Prepara sin ejecutar: exige una receta terminada sin errores,
vuelve a hashear el modelo contra la receta e identifica el ejecutor y sus 33 DLL. Para ejecutar exige
`--sha256-paquete`. Solo CPU (`--device none -ngl 0`): no abre puertos ni toca la VRAM del motor activo.
Cada ejecución deja JSON, salida y registro nuevos; `receta.json` no se modifica; el modelo se vuelve a
hashear al final. Guía: [modelos-reconstruccion.md](../../docs/modelos-reconstruccion.md).

Incidencia corregida. Los dos primeros intentos (otra sesión, con `llama-completion`) fallaron: el modelo
abría `<|channel>thought` y agotaba los 64 tokens pensando. Con `--verbose-prompt` se vio la causa:
`llama-completion -cnv` (b11968) añade un mensaje de sistema vacío con el token `<|think|>` aunque se pida
`-rea off` (`--reasoning-budget 0` tampoco lo evita). Se cambió el ejecutor a `llama-cli` con
`--chat-template-kwargs '{"enable_thinking":false}'`, que la plantilla de Gemma 4 respeta. El intento fallido
se conserva: [g4-real-q4_k_m-smoke-fallido-completion.json](g4-real-q4_k_m-smoke-fallido-completion.json).

La salida de `llama-cli` lleva pancarta y estadísticas. La respuesta se toma solo entre el eco `> pregunta`
y la línea `[ Prompt:`; sin esas marcas el smoke falla. Se descartan el canal de pensamiento (hasta
`<channel|>`, como cierra Gemma; el filtro previo buscaba `<|channel>final`) y `<think>`.

Resultado real: `llama-cli.exe` SHA-256 `fe9a01ee…d59a`, paquete `dcacad86…c696`, build declarada
`b11968-ac8e1694d`. Pregunta «¿Cuánto es 17*3-8? Responde solo con el número.» → respuesta **`43`**,
salida 0, 13,4 s en total, 3,7 t/s de generación declarados, 6 hilos. Estado `smoke_superado`; modelo con
el mismo SHA-256 al terminar. Evidencia: [g4-real-q4_k_m-smoke.json](g4-real-q4_k_m-smoke.json).

REA `rea-pe-imports` v1 inspeccionó el ejecutor real `llama-cli.exe`: PE x86-64, cobertura completa de
8 descriptores DLL y 35 imports, sin incidencias del parser. Es inspección estática de las tablas PE; no
observa enlaces resueltos, alcanzabilidad ni carga dinámica en ejecución. Evidencia:
[g6-rea-ejecutor.json](g6-rea-ejecutor.json).

Durante la conversión y el smoke había otro motor (llama-server PID 34776, Gemma Q4 publicado, 8090) y
un banco B2 de otra sesión en marcha; no se detuvieron ni se reconfiguraron.

## Banco «tareas» sobre la reconstrucción: interrumpido por timeout (17/11, 06:21–07:22)

Referencia: el B2 de otra sesión (16/11 20:46 – 17/11 00:53, Q4_K_M publicado) terminó con salida 0: 6/6
muestras con juez 9/9, media 1,000, desviación 0, de 39 a 44 min por muestra. Ejecución sobre la reconstrucción
con el mismo código fijado (`D:\Eolfi-wt-banco`, `52cc369`), el mismo script (SHA-256 `498940b3…1e56`) y las mismas
semillas. Configuración Eolas V2 copiada a un directorio temporal: mismo perfil `gemma_q4` (ctx 16384, 99 capas,
`-fa on`, KV q8_0) con el GGUF reconstruido y puerto 8092. Ni la configuración real, ni los perfiles, ni la
lista de confianza se modificaron.

- Resultado: **sin ninguna muestra puntuada**. En la semilla 0, `eolfi create` superó el límite de 3600 s
  del banco (`rsi_banco.py`) y el script terminó con salida 1. El motor se paró después.
- Causa observada: generación a 4,1–4,7 t/s frente a 7,6–8,8 t/s del publicado en el B2, y lectura del prompt a
  unos 90 t/s frente a 96–150. La primera petición (6.166 tokens) tardó 22 min frente a unos 13 min, y la segunda
  se canceló a los 60 min. La VRAM llegó a 7.668 de 8.192 MiB. Que la diferencia se deba a que
  el modelo (260 MB mayor que el publicado) no cabe entero en la GPU es una hipótesis NO VERIFICADA.
- El modelo conserva su SHA-256 antes y después (`d5afb9ef…b054`).
- **NO VERIFICADO:** calidad de la reconstrucción en el banco. El timeout no es una nota de 0 del juez ni
  una comparación de calidad; solo muestra que en esta GPU, con el perfil del publicado, no cabe en el
  presupuesto de tiempo del banco.
- **Suspendido por el titular (17/11):** no se repetirá hasta tener las implementaciones necesarias, que son
  el ajuste de memoria y rendimiento del perfil y el presupuesto de tiempo del banco. Hasta entonces la
  reconstrucción es un modelo con fallos NO VALIDADOS y no se usa como activo.

## G6: plan, adopción y smoke de servidor (17/11)

`eolas-v2 plan` auditó íntegramente la reconstrucción y enlazó receta y smoke por el SHA-256
`d5afb9ef…b054`. Observó Gemma4, 48 capas, contexto declarado 262.144, ventana deslizante 1.024,
embedding 3.840, 16 cabezas y plantilla de 18.924 bytes (`845f1ee4…3d1b`). La propuesta
`gemma4_recon_q4` usa contexto 32.000, 8 capas GPU, batch 128 y ubatch 64. No escribió configuración,
no cambió el perfil activo ni arrancó un motor: `adoptado: false`. Los 284 tensores tipo 12 y 45 tipo 14,
el banco y el ajuste definitivo de memoria/rendimiento permanecen NO VERIFICADOS.
Evidencia: [g6-plan-real.json](g6-plan-real.json).
La ejecución final, tras endurecer la comparación contra los metadatos registrados, volvió a terminar 0:
48 capas, contexto 262.144, ventana 1.024, smoke enlazado y dos incógnitas K; `adoptado: false`.

`eolas-v2 adoptar` añade una segunda revalidación y exige el SHA-256 revisado. Su vista previa real terminó 0,
mantuvo activo `gemma_q4` y el SHA-256 del archivo de configuración fue idéntico antes y después
(`58ece425…773d`). La aplicación está implementada y probada con configuración temporal: solo añade un perfil
nuevo e inactivo, no permite argumentos de proceso arbitrarios, fija el modelo por hash y desactiva pensamiento.
La vista previa se conserva en [g6-adopcion-preview.json](g6-adopcion-preview.json). Después se aplicó el
plan real: instaló `gemma4_recon_q4` como perfil inactivo, mantuvo `gemma_q4` activo y no arrancó el motor
durante la adopción. La nueva orden `quitar-perfil` permite revertir solo esa entrada con pin SHA-256, siempre
que no esté activa ni cargada, y conserva GGUF, receta, smoke y evidencias. Evidencia:
[g6-adopcion-aplicada.json](g6-adopcion-aplicada.json).

El arranque temporal del perfil reconstruido terminó 0 y quedó sano en `127.0.0.1:8090`. Una petición local
autenticada respondió exactamente `EOLFI-G6` (`finish=stop`, 25 tokens de entrada y 6 de salida). La parada
terminó 0; el estado final mostró `running=false`, sin PID de servidor ni de vigilante, y `gemma_q4` continuó
activo. Evidencia: [g6-servidor-smoke.json](g6-servidor-smoke.json). Esto demuestra carga e inferencia mínima,
no calidad general: banco, contexto largo, herramientas y ajuste definitivo siguen NO VERIFICADOS.

## G3: modo offline nativo (17/11)

La ayuda del `llama-server.exe` instalado expone `--offline` y lo describe como uso forzado de caché sin acceso
de red. Con `EOLAS_OFFLINE=1`, Eolfi añade ese argumento y hereda las variables offline de llama.cpp,
Hugging Face y Transformers. El runtime real registró `offline_requested=true`, `running_offline=true` y
`model_verified=true`; una inferencia respondió exactamente `EOLFI-OFFLINE` y la parada dejó servidor y
vigilante sin PID. Evidencia: [g3-offline-smoke.json](g3-offline-smoke.json).

La prueba no capturó tráfico ni creó una regla del sistema. Por eso `firewall_verified=false`: el cortafuegos
de salida continúa NO VERIFICADO y solo lo ejecutará el titular.

## Pruebas

- `tests/test_modelos_reconstruir.py`: 46 pasadas y 6 omitidas sin opt-in; junto con Eolas V2 y el cliente,
  105 pasadas y 6 omitidas. Cubren
  vista previa sin ejecución, hash de paquete, argumentos o ejecutor cambiados, receta no terminada o
  alterada, respuesta incorrecta, salida distinta de 0, pensamiento sin cierre, valor fuera del tramo de
  respuesta (pancarta o pregunta), modelo alterado por el ejecutor, timeout, interrupción en el hash final
  y códigos de la CLI.
- Suite completa final en la copia real (Windows, Python 3.12.10), con las seis conversiones nativas:
  `python -m pytest -q` **776 pasadas, 2 omitidas, 398,62 s, salida 0**. `node --test` en
  `eolfi/bridge` 63 pasadas/4 omitidas; en `eolfi/vscode-bridge` 192 pasadas; `npm test` en `tests/e2e`
  19 pasadas; todas salida 0. `git diff --check` salida 0. No sustituye la matriz CI Linux/Windows 3.10/3.12.

## Límites

- Una pregunta aritmética no mide calidad, contexto largo, herramientas ni velocidad en GPU. El banco de
  Eolas sobre la reconstrucción se inició, pero no produjo una muestra antes del timeout: calidad NO VERIFICADA.
- El smoke depende del formato de salida de `llama-cli`; un cambio de build daría `fallido`, no un falso
  positivo, pero habría que revisar el extractor.
- Tamaños de bloque K NO VERIFICADOS en el auditor; procedencia del SDK frente a una release oficial NO VERIFICADA.
- La reconstrucción está adoptada como perfil inactivo; la lista de confianza y el perfil activo no cambiaron.
- LIM-G-006 conserva la carpeta de 7,4 GB hasta la revisión de limpieza.
