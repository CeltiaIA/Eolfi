# Plan definitivo de Eolfi

Pedido por el titular el 16/11/2026: un solo plan con todo lo que queda sin implementar en los planes anteriores y
todo lo nuevo (voz y lo demás). Sustituye como backlog vigente a `PLAN_INGENIERIA_INVERSA_EOLFI.md`,
`PLAN_MEJORAS_2026-11-05.md`, `PLAN_CORRECCIONES.md`, `PLAN_REA.md` y `PLAN_VAS.md`, que quedan como historial.

Reglas que no cambian: las de `AGENTS.md` (nada se da por hecho sin comprobarlo; lo no comprobado se marca
**NO VERIFICADO**), motor local primero, el titular decide lo que cambia la configuración o se publica, y los
candidatos a limpieza se anotan en `REGISTRO_LIMPIEZA.md` sin borrarlos.

## Auditoría del 16/11/2026: qué está hecho y qué no

Revisado sobre `origin/main` (`1d766da`), las 22 PR abiertas y los cinco planes.

| Plan | Estado |
|---|---|
| `PLAN_CORRECCIONES.md` (fases 1 a 5) | Cerrado. Queda M7 (`--ignore-scripts` al instalar dependencias), descartado a propósito |
| `PLAN_MEJORAS_2026-11-05.md` (fases A a E) | A–D y E1–E3 cerradas. **Pendientes E4 y E5** (bloques C y D de este plan) |
| `PLAN_INGENIERIA_INVERSA_EOLFI.md` (fases 0 a 7) | Cerrado salvo **guías y ejemplos por flujo** (fase 7) |
| `PLAN_REA.md` (puntos 1 a 12) | Código hecho en las PR #20 a #35 y #46, **sin fusionar**. Pendiente: probar la autorización por caso con un modelo, exportar el paquete completo de REA, mapa visual en el panel |
| `PLAN_VAS.md` (fases 0 a 5) | Hecho: 2.1 (planificador, CeltiaIA #11) y 1.3 (evaluador estadístico, en local). El resto, pendiente |

Comprobado en el código de `main`:

| Capacidad | ¿Existe? |
|---|---|
| Voz (dictado, lectura, conversación) | No. Ninguna referencia en `eolfi/` |
| Idiomas del panel (es/en) | No. Textos fijos en español |
| `eolfi sync` (volver a analizar y fusionar a tres bandas) | No |
| `eolfi update --check`, instalador (pipx o PyInstaller) | No |
| Destinos Go y Rust del generador | No (Rust solo dentro de Tauri) |
| Análisis de SPA renderizadas y rastreo limitado | Parcial (hay captura con navegador en `observe`; no en `eolfi web`) |
| PWA e i18n en los destinos web generados | No |
| e2e generadas con Playwright y axe en los proyectos | Parcial (solo en el propio panel) |
| Despliegue de los proyectos generados | No |
| Juez funcional dentro de `verify` | No (solo en el banco del RSI) |
| Semilla y `temperature` 0 en la generación evaluada | No (`temperature` 0.2 sin semilla en `generador/llm.py`) |
| Telemetría por fase (JSONL) | No |

Medios disponibles para la voz sin instalar nada: Windows trae el reconocedor `es-ES` y la voz «Microsoft Helena»
(`System.Speech`, sin conexión). No hay whisper.cpp, Piper ni ffmpeg instalados.

## Bloque A: voz (nuevo, primero)

Todo local por defecto. El audio no sale del equipo salvo que el titular active un motor externo.

| # | Pieza | Qué hace | Aceptación |
|---|---|---|---|
| A1 | **Motor de voz** (`eolfi/voz.py`) | Motores intercambiables: `windows` (System.Speech, ya disponible) y `whisper` (whisper.cpp si el titular lo instala: mejor calidad). Configuración en `~/.eolfi/voz.json`. `eolfi voz estado` | `eolfi voz estado` dice qué motores hay y cuál está activo, sin cargar nada |
| A2 | **Voz a texto** | `POST /api/voz/transcribir` recibe un WAV (16 kHz mono, tope de tamaño y de duración) y devuelve el texto. `eolfi voz transcribir ARCHIVO` | Un WAV sintetizado con la voz local vuelve como texto reconocible |
| A3 | **Dictado en el panel** | Botón de micrófono en el chat de Eolfi: graba, convierte a WAV en el navegador, transcribe y escribe en el cuadro (sin enviar). Atajo de teclado, estado visible y accesible | e2e: con audio simulado, el texto aparece en el cuadro; axe sin infracciones |
| A4 | **Texto a voz** | Leer en voz alta las respuestas: botón por mensaje y opción «leer siempre». Voz del sistema en el navegador (sin conexión); `POST /api/voz/hablar` y `eolfi voz decir` para la CLI | La respuesta se oye; se puede parar |
| A5 | **Modo conversación** | Manos libres: escucha → detecta el silencio → transcribe → envía → lee la respuesta → vuelve a escuchar. Se corta al hablar encima o con Esc | Tres turnos seguidos sin tocar el teclado |
| A6 | **Órdenes por voz** | «Envía», «borra», «para», «nueva conversación», «lee la última» | Cada orden hace lo suyo y no se escribe como texto |
| A7 | **Dictado en todo el panel** (hecho el 16/11) | Botón «Dictar» junto a «Crear proyecto», la petición para la IA, casos, chat web y comparación; Alt+M dicta en el cuadro con el foco. Ahí solo se escribe: sin órdenes ni conversación | Hecho: e2e con audio simulado en el chat y en «Crear proyecto», axe sin infracciones |
| A8 | **Whisper local** (hecho el 16/11, con permiso del titular) | whisper.cpp b5454 (CPU) y el modelo «small» en `~/.eolfi/tools/whisper-b5454`, con SHA-256 verificado; `motor: auto` lo elige | Hecho: 4 frases de prueba, Whisper 4 bien con tildes y puntuación (unos 6 s cada una); Windows 1 bien (1 s) |
| A9 | **Voz en VS Code y en Fios** | Dictado en el chat `@eolfi` y en Fios, reutilizando la API | Dictar en los dos sitios |

Límites que se declaran: el motor de Windows reconoce peor que Whisper y no puntúa; el micrófono exige que el
navegador dé permiso a la página (en `127.0.0.1` lo permite).

## Bloque B: medir con verdad y autonomía (viene de `PLAN_VAS.md`)

| # | Pieza | Estado |
|---|---|---|
| B1 | Juez funcional dentro de `verify` (prueba la app en Chrome; las reparaciones ven qué falla) | Hecho en local para `static` (rama `vas-b1-b2`) y probado con el modelo real: 9/9 en una muestra. Falta: otros destinos |
| B2 | Determinismo: semilla y `temperature` 0 en la generación evaluada; el banco pasa la semilla | Hecho en local para Eolas V2 y llama.cpp: `EOLFI_SEMILLA` envía semilla, temperatura 0 y `cache_prompt: false` (la caché de prompt era la causa). Medido: 7 de 7 respuestas idénticas. Falta: Eolas V1 y medir el banco completo |
| B3 | Evaluador estadístico y prueba A/A del RSI | Hecho en local (`73afd36`); A/A real en curso |
| B4 | Telemetría por fase en JSONL (carga, tokens/s, verificación, juez) | Hecho en local (rama `vas-b1-b2`): `eolfi/telemetria.py`, `eolfi telemetria`. Rondas de `assist` y muestras del banco; sin contenido. Falta: tiempo de carga del modelo |
| B5 | Más encargos en el banco (hoy uno solo, «tareas») | Hecho en local (rama `vas-b1-b2`): «contador» y «filtro», y `--banco todos`. Jueces validados con apps de referencia. NO VERIFICADO con un modelo real |
| B6 | Bucle generar → juez → reparar que conserva el mejor intento; memoria de ejemplos verificados | Pendiente |
| B7 | Elección de motor y perfil por banco; más superficies del RSI | Pendiente |
| B8 | Registro encadenado de todas las acciones de agente (hoy solo el RSI) | Pendiente |

Métricas: las del tablero de `PLAN_VAS.md` (verdes falsos 0 %, media del banco ≥ 0,85, desviación ≤ 0,10, falsos
positivos A/A ≤ 5 %, p50 por muestra ≤ 5 min).

## Bloque C: producto (viene de la fase E4 de `PLAN_MEJORAS`)

| # | Pieza | Estado |
|---|---|---|
| C1 | Idiomas es/en en el panel, la API y la CLI | Pendiente |
| C2 | Instalador y versión única: pipx o ejecutable, acceso directo, `eolfi update --check` | Pendiente |
| C3 | `eolfi web` con páginas renderizadas (SPA) y rastreo limitado con inventario de plantillas | Pendiente |
| C4 | Proyectos generados: e2e con Playwright y axe, PWA, i18n y receta de despliegue | Pendiente |
| C5 | Mapa visual de la app en el panel (grafo de pantallas y llamadas de REA) | Pendiente (los datos ya salen en Mermaid, PR #24 y #25) |
| C6 | Guías y ejemplos autorizados por flujo (lo que queda de la fase 7) | Pendiente |
| C7 | Panel en el móvil: revisar la interfaz Android de la fase 2 con la voz | Pendiente |

## Bloque D: largo plazo (fase E5)

| # | Pieza | Estado |
|---|---|---|
| D1 | `eolfi sync`: volver a analizar las fuentes y proponer un diff con fusión a tres bandas | Pendiente |
| D2 | Destinos Go y Rust del generador | Pendiente |
| D3 | Comparar modelos mayores cuando el banco sea fiable (fase 5 del VAS) | Pendiente |

## Bloque E: REA (lo que queda)

| # | Pieza | Estado |
|---|---|---|
| E1 | Fusionar las PR de REA #20 a #35 en una rama de integración, en orden | Pendiente; decide el titular |
| E2 | Probar en vivo la autorización por caso con un modelo | NO VERIFICADO |
| E3 | Exportar el paquete completo de evidencias de REA | Pendiente |
| E4 | Herramientas: Npcap, sigrok, Cutter (cada una pide permiso; Npcap instala un controlador) | Pendiente |

## Bloque G: modelos (confianza, actualización y reconstrucción)

Pedido por el titular el 16/11/2026. Auditoría previa en la copia `D:\Eolfi-wt-voz`:
`docs/auditoria-modelos-2026-11-16.md`. Esa lectura estática y su muestra de conexiones **no descartan puertas
traseras en los pesos ni demuestran aislamiento de red permanente**.

| # | Pieza | Estado |
|---|---|---|
| G1 | `eolfi modelos auditar`: estructura GGUF, bytes sobrantes, plantilla, SHA-256 y conexiones del motor en vivo | Auditor integrado en CLI, MCP y chat; instantáneas TCP/UDP por PID en Windows (`modelos conexiones --pid` o `auditar --pid`). Lectura real de Gemma Q4 y conexiones del motor activo registradas. Pendiente: layouts K con procedencia demostrable, proveedores de conexiones Linux/macOS y comprobar la elección de la nueva herramienta por el modelo real. Ver `informes/modelos-g-2026-11-16/avance-g1-chat-conexiones.md` |
| G2 | Lista de modelos de confianza (SHA-256): Eolas y Eolfi no cargan lo que no esté | Control implementado y probado en arranque Python de Eolas V2 y llama.cpp; activo solo si se establece EOLFI_MODELOS_CONFIANZA. No activado en el equipo. Pendiente: aprobación de hashes de origen, Eolas Base y rutas directas de otros clientes |
| G3 | Modo sin red en Eolas (`EOLAS_OFFLINE=1`) y regla de cortafuegos de salida | Pendiente; el cortafuegos lo ejecuta el titular |
| G4 | **Reconstruir modelos**: del original (BF16, ya en disco) a cada cuantización con `llama-quantize`, con receta, SHA-256 de entrada y salida y registro | Flujo CLI implementado: vista previa sin ejecución y `--ejecutar` con hashes de entrada/paquete, destino nuevo, auditoría y hash posterior del original. Seis presets probados con cuantizador real y fixture BF16 propio; Q8 con comprobación numérica. Recetas de Gemma BF16 preparadas, sin ejecutarlas. Reconstrucciones reales, inferencia y banco siguen NO VERIFICADOS. Ver `informes/modelos-g-2026-11-16/avance-g4-reconstruccion.md` |
| G5 | **Actualizar modelos**: comprobar si hay versión nueva, descargar solo con permiso, auditar (G1) y comparar con el banco antes de adoptar | Pendiente |
| G6 | **Adaptar al nuevo Eolas**: metadatos que usa el planificador (ventana deslizante, capas), plantilla de chat propia y perfil por modelo; validar cada modelo reconstruido con `eolas plan` y un smoke | Pendiente |
| G7 | Ajuste fino (LoRA) con los ejemplos verificados del bloque B6 | Largo plazo; depende del hardware |

## Bloque F: higiene (depende del titular)

| # | Pieza | Estado |
|---|---|---|
| F1 | Facturación de GitHub Actions: la CI no arranca en Eolfi ni en CeltiaIA | **Bloqueado**, lo resuelve el titular |
| F2 | Fusionar las PR abiertas (22 en Eolfi) en el orden de `docs/vas/VAS-auditoria-eolfi.md` | Pendiente |
| F3 | Revisar `REGISTRO_LIMPIEZA.md` con el titular (LIM-040, copia de una clave, primero) | Pendiente |
| F4 | Ruff F sin avisos (PR #19, rehacer desde `main`) | Pendiente |

## Orden de ejecución

1. **A1 a A5** (voz en el chat): lo pedido ahora, sin dependencias y sin instalar nada.
2. **B1 y B2** (juez en `verify` y determinismo): sin ellos, ninguna mejora posterior se puede demostrar.
3. **A6 y A7**, **B4 y B5**.
4. **C1, C2 y C6** (idiomas, instalador y guías).
5. **G1 a G4 y G6** (modelos), **B6 a B8**, **C3 a C5**, **E**.
6. **D**.

Cada pieza: rama propia, pruebas, comprobación en vivo cuando aplique y nota en `ESTADO-TRABAJO.md`. Las casillas
solo cambian con evidencia.
