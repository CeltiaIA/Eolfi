# Plan VAS: Sistema Autónomo Verificable

Pedido por el titular el 16/11/2026 («implementar un sistema VAS, Sistema Autónomo Verificable»), con permiso para
ejecutar los artefactos propios y cargar V1 o V2 (uno a la vez) cuando haga falta.

## Qué es y qué no es

El VAS es el conjunto CeltiaIA + Eolas V1/V2 + Fios + Eolfi trabajando **solo** en tareas de software (generar,
analizar con REA, reparar, mejorar su configuración) y demostrando cada resultado con una **verificación objetiva y
repetible**. No es una inteligencia general: la capacidad la pone el modelo local (hoy Gemma 4 12B en una RTX 3060 Ti
de 8 GB). El VAS hace que esa capacidad se use bien, se mida con honestidad y mejore con evidencia.

Principios:
1. **Nada cuenta sin juez.** Un resultado es correcto solo si lo comprueba algo que no escribió el modelo.
2. **Se mide con estadística.** Bancos repetidos con semillas, intervalos de confianza y prueba A/A; una muestra no
   decide nada.
3. **Todo queda registrado** en registros encadenados (SHA-256): acciones, decisiones, evaluaciones.
4. **El titular decide** lo que cambia la configuración o el código; el sistema propone con evidencia.
5. **Permisos cerrados por defecto**: lo que ejecuta, lee fuera de la carpeta o abre algo vivo pide permiso.

## Punto de partida (auditoría del 16/11/2026)

Informes completos en `docs/vas/`. Medido o comprobado:

| Hallazgo | Evidencia | Impacto |
|---|---|---|
| El verde de `create --ai` no prueba que la app funcione | Competición V1/V2: Eolfi aprobó 4 proyectos y el juez de Chrome dio 2 por rotos (1/4). En el banco RSI, 7/9, 5/9 y 1/9 salieron todos con verificación verde | El generador «cree» que acierta cuando no |
| Varianza enorme con la misma configuración | Banco «tareas», V2 `gemma_q4`: 7/9, 5/9, 1/9 (desviación ≈ 0,3); `temperature` 0.2 sin semilla | Ninguna mejora pequeña se puede demostrar con 3 muestras |
| El RSI adopta con n=3 y margen 0,05 | `rsi.py` (PR #46) | ~40 % de falsos positivos estimados frente a esa varianza |
| V1 carga solo 13 de 49 capas a 32K | `eolas plan` en vivo: KV estimada 13,7 GB a 32K (q8_0) frente a 0,86 GB a 2K; el planificador ignora la ventana deslizante de Gemma 4 (`plan.go:168-178`) | Web y Fios a ~3 t/s |
| `EOLAS_VRAM_LIMIT_MB` no limita la carga | `config.go:205-212`: solo recorta la copia que elige el perfil; el plan en vivo ve 7,9 GB libres | El reparto de VRAM entre V1 y la web no está controlado |
| V1 sin recuperación ante falta de memoria | 4 caídas `bad allocation`/`GGML_ASSERT` en el registro del runner; error 500 sin reintento | Caídas visibles para el usuario |
| CI de CeltiaIA no se ejecuta desde la PR #4 | `gh run view`: la cuenta de GitHub no tiene pago o límite de gasto | Nada de CeltiaIA está verificado por CI desde entonces |
| Fios: permisos de lectura abiertos y token del puente en `GET /` | `commandPolicy.ts:79-89`, `localServer.ts:107-116` (deducido del código) | Un agente puede leer fuera de la carpeta |
| 25+ PR abiertas, muchas en conflicto entre sí | `git merge-tree` | Lo hecho no llega a `main` |

Comprobado en verde: Eolas Base `go test` 344 PASS / 14 SKIP (las de GPU), CeltiaIA 72/72 pruebas puras, Eolfi
pytest 700 y e2e 19/19 (rama RSI). **NO VERIFICADO:** smokes de Fios, pruebas de CeltiaIA que arrancan servidores,
comportamiento de V1 con GPU real salvo el plan.

## Métricas del VAS (el tablero)

| Métrica | Hoy | Objetivo |
|---|---|---|
| Verdes falsos de `create --ai` (verde de Eolfi y juez < 9/9) | 2 de 4 | 0 % |
| Media del banco «tareas» (juez sobre 9) | 0,48 (V2) | ≥ 0,85 |
| Desviación típica del banco con la misma configuración | ≈ 0,30 | ≤ 0,10 |
| Falsos positivos del evaluador en prueba A/A | sin medir (~40 % estimado) | ≤ 5 % |
| Tiempo por muestra del banco (p50) | ≈ 13 min | ≤ 5 min |
| Capas de Gemma 4 12B en GPU a 32K (V1) | 13 de 49 | ≥ 30 |
| Tokens/s de V1 a 32K | ≈ 3 | ≥ 6 |
| Caídas por memoria en 100 prompts largos (V1) | 4 en el registro | 0 |
| PR y `main` con CI ejecutada y verde | Eolfi sí; CeltiaIA no | 100 % |
| Acciones de agente con registro encadenado | solo RSI | 100 % |

## Fases

### Fase 0: higiene (lo hecho, a `main`)
- Fusionar sin conflictos: Eolfi #43 (plazo local), #45 (JS del sitio), #20 (independencia), #44 (registros).
- Cerrar o rehacer #39 y #19 desde `main`; integrar las PR de REA (#21–#35) en una rama de integración, en el orden
  del informe de Eolfi.
- CeltiaIA: **el titular** resuelve la facturación de GitHub Actions (o un runner Windows propio); después #6, #7,
  #9, #10.
- Métrica: PR abiertas < 8; CI ejecutada en 100 % de las PR.

### Fase 1: medir con verdad (Eolfi)
1. **Juez funcional dentro de `verify`**: si el encargo trae criterios comprobables (o el destino es web), Eolfi
   prueba la app en Chrome y el resultado entra en `verification`; las rondas de reparación ven qué comprobación falla.
2. **Determinismo**: semilla y `temperature` 0 en la generación evaluada; prompt + `max_tokens` dentro de `ctx`.
3. **Evaluador estadístico** (RSI): muestras pareadas por semilla, varios encargos, intervalo al 95 % por bootstrap;
   se adopta solo si el límite inferior de la mejora es > 0. Prueba A/A obligatoria del propio evaluador.
4. **Telemetría por fase** (JSONL): carga, generación (tokens/s), verificación y juez por muestra.
- Métricas: verdes falsos, desviación del banco, falsos positivos A/A, p50 por muestra.

### Fase 2: motor local fiable (Eolas V1 y V2)
1. **Planificador con ventana deslizante** (V1): la KV de las capas SWA se calcula con su ventana, no con el
   contexto completo; validado contra la VRAM medida.
2. **Tope de VRAM real o retirado**: aplicarlo al planificador de carga y probar el arranque (`serveWithContext`).
3. **Recuperación ante falta de memoria**: clasificar el fallo y reintentar una vez con un plan reducido.
4. **Métricas** (`/metrics`): tokens/s, capas, tipo de KV, VRAM planificada y medida, recargas, reinicios.
5. **Smoke reproducible** (`eolas bench`): JSON con SHA-256, plan, tokens/s y pico de memoria.
6. llama-server con clave propia (hoy escucha en loopback sin clave).
- Métricas: capas y tokens/s a 32K, caídas por memoria, diferencia entre dos smokes ≤ 10 %.

### Fase 3: seguridad y registro de acciones (CeltiaIA, Fios)
- Permisos de Fios cerrados por defecto (resolver `$env:`, `~`, `..` antes de decidir); token fuera de `GET /`;
  `api.key` con permisos solo del usuario.
- Registro encadenado de cada acción del agente (llamada al motor, herramienta y código de salida, aprobación).
- Errores del motor con su causa y cola en lugar de 429.
- Métricas: 0 lecturas fuera de la carpeta en 30+ comandos adversarios; 100 % de acciones registradas, cadena
  verificable, 0 secretos en el registro.

### Fase 4: autonomía con verificación
- Bucle planificar → generar → **juez** → reparar, conservando el mejor intento puntuado por el juez.
- Memoria de ejemplos: los casos corregidos y verificados alimentan las siguientes generaciones.
- Elección de motor (V1 o V2) y de perfil por banco, no por intuición.
- RSI con más superficies (capas y contexto de V1, plantillas de prompt), siempre con el evaluador de la fase 1.
- Métricas: media del banco ≥ 0,85 en 3 encargos distintos; tasa «a la primera».

### Fase 5: escalar el modelo
- Con el banco y el evaluador ya fiables, comparar modelos mayores o mejor cuantizados cuando el hardware lo permita,
  y adoptar solo con mejora demostrada.

## Orden de ejecución

1. Fase 2.1 (planificador con ventana deslizante): mayor efecto inmediato, medible en minutos con `eolas plan` y un
   smoke.
2. Fase 1.3 (evaluador estadístico en el RSI, PR #46) y 1.1 (juez en `verify`).
3. Fase 0 en paralelo según decida el titular (las fusiones son suyas).
4. Fases 3 y 4.

Cada paso: rama propia, pruebas, comprobación en vivo cuando aplique, PR y registro en `ESTADO-TRABAJO.md`.
