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

Durante la conversión y el smoke había otro motor (llama-server PID 34776, Gemma Q4 publicado, 8090) y
un banco B2 de otra sesión en marcha; no se detuvieron ni se reconfiguraron.

## Pruebas

- `tests/test_modelos_reconstruir.py`: 36 pasadas y 6 omitidas (conversiones nativas sin opt-in). Cubren
  vista previa sin ejecución, hash de paquete, argumentos o ejecutor cambiados, receta no terminada o
  alterada, respuesta incorrecta, salida distinta de 0, pensamiento sin cierre, valor fuera del tramo de
  respuesta (pancarta o pregunta), modelo alterado por el ejecutor, timeout, interrupción en el hash final
  y códigos de la CLI.
- Suites completas en la copia real (Windows, Python 3.12.10), después del cambio a `llama-cli`:
  `python -m pytest -q` **758 pasadas, 8 omitidas, 429,46 s, salida 0** (6 de las omitidas son las
  conversiones nativas, sin opt-in en esta ejecución; con opt-in pasaron el 16/11). `node --test` en
  `eolfi/bridge` 63 pasadas/4 omitidas; en `eolfi/vscode-bridge` 192 pasadas; `npm test` en `tests/e2e`
  19 pasadas; todas salida 0. `git diff --check` salida 0. No sustituye la matriz CI Linux/Windows 3.10/3.12.

## Límites

- Una pregunta aritmética no mide calidad, contexto largo, herramientas ni velocidad en GPU. El banco de
  Eolas sobre la reconstrucción no se ha ejecutado.
- El smoke depende del formato de salida de `llama-cli`; un cambio de build daría `fallido`, no un falso
  positivo, pero habría que revisar el extractor.
- Tamaños de bloque K NO VERIFICADOS en el auditor; procedencia del SDK frente a una release oficial NO VERIFICADA.
- La reconstrucción no se adopta: perfiles, lista de confianza y motor activo sin cambios (G6).
- LIM-G-006 conserva la carpeta de 7,4 GB hasta la revisión de limpieza.
