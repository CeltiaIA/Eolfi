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
| B6 | Bucle generar → juez → reparar que conserva el mejor intento; memoria de ejemplos verificados | Implementado en local: puntúa cada intento por pasos reales superados, marca el mejor y conserva su evidencia; si ninguno queda verde restaura el proyecto. Solo una ronda verde entra en memoria local, redactada, deduplicada y sin código fuente ni rutas absolutas; los resúmenes recordados se tratan como datos no confiables. 12 pruebas específicas en verde. Pendiente: prueba controlada con modelo real |
| B7 | Elección de motor y perfil por banco; más superficies del RSI | Parcial: la memoria del banco conserva batería, resumen, ganador y aprobados. `eolas-v2 recomendar-perfil` ofrece vista previa y solo cambia el activo con `--aplicar`; `assist --model banco` usa la misma evidencia y falla sin ganador reciente. Excluye perfiles retirados o sin GGUF y limita la antigüedad. Vista previa real: `NO_VERIFICADO`, porque las rondas históricas anteriores no guardaban el resumen nuevo; no inventó ganador. Pendiente: nueva ronda completa y ampliar superficies RSI |
| B8 | Registro encadenado de todas las acciones de agente (hoy solo el RSI) | Parcial: `eolfi/acciones.py` encadena por SHA-256 en `~/.eolfi/acciones.jsonl` cada acción que cambia estado en esta rama (arrancar, cambiar y parar el motor; perfil activo; retirar, restaurar, desinstalar, adoptar, quitar y recomendar con `--aplicar`; reconstruir y smoke ejecutados), venga de la CLI, el panel o un agente. Las vistas previas no se registran. Solo guarda campos declarados, sin prompts ni código. Tiene cerrojo entre procesos, `eolfi acciones verificar/listar` y `EOLFI_ACCIONES=0`. También `assist` y `create` (el encargo solo como SHA-256 y longitud). `eolfi acciones anclar --destino` copia la cabeza a un archivo externo y `verificar --ancla` detecta una reescritura o un truncado anteriores al ancla. 25 pruebas. El puente Node (`eolfi/bridge/acciones.mjs`) escribe en la misma cadena: envíos a chats web con su decisión (aprobado, denegado, caducado, cancelado o tecleado en el panel), comparativas, «Permitir 30 minutos», revocaciones y reinicios; el prompt y la respuesta solo como SHA-256 y bytes. Una prueba cruzada intercala eventos de Python y de Node y `verificar` los acepta. De paso se corrigió `verificar`: `splitlines` partía en U+2028 un evento legítimo. **17/11, unión y firma:** las acciones del RSI (proponer, evaluar, A/A, decidir, aplicar, revertir, ajustar umbrales) se reflejan en la misma cadena como `rsi.<tipo>` con el número y el SHA-256 de su evento en la cadena del RSI, que se conserva porque de ella se reconstruyen las propuestas; las observaciones no se reflejan, pero reescribir una rompe el siguiente reflejo. `eolfi acciones verificar --rsi` comprueba las dos cadenas y cada reflejo. Firma: `eolfi acciones clave --destino` crea una clave de 32 bytes (no junto al registro ni sobre otra), `eolfi acciones firmar --clave` añade `acciones.firma` con el HMAC-SHA256 de la cabeza y `verificar --clave` lo recalcula: una reescritura coherente de la cadena o una firma inventada se detectan sin depender de un archivo externo. 10 pruebas en `tests/test_acciones_firma.py`. Límites: HMAC es simétrico (protege solo si la clave queda fuera del alcance de quien escribe el registro); la cola posterior a la última firma y el recorte de la última firma no se detectan sin conservar fuera su número; no hay firma automática |

Métricas: las del tablero de `PLAN_VAS.md` (verdes falsos 0 %, media del banco ≥ 0,85, desviación ≤ 0,10, falsos
positivos A/A ≤ 5 %, p50 por muestra ≤ 5 min).

## Bloque C: producto (viene de la fase E4 de `PLAN_MEJORAS`)

| # | Pieza | Estado |
|---|---|---|
| C1 | Idiomas es/en en el panel, la API y la CLI | Parcial (17/11): catálogos cuya clave es el texto en castellano, sin claves aparte. **Panel:** selector ES/EN en la cabecera (castellano salvo elección o `?lang=en`; no se deduce del navegador), `eolfi/web/i18n.js` traduce los nodos de texto y `title`/`placeholder`/`aria-label` exactos, también lo que añade el JS después, y nunca el contenido marcado `data-i18n-no` (chats, evidencias, incógnitas, casos), `pre`, `code` ni `textarea`; `tools/i18n_panel.py` mide la cobertura: **289/289 textos fijos de `index.html`**. **API:** `?lang`, cookie `eolfi_idioma` del panel o `Accept-Language`; traduce el campo `error` y responde con `Content-Language`: **61/61 mensajes fijos**. **CLI:** `--idioma en` o `EOLFI_IDIOMA=en` traduce la descripción y la ayuda de **todos los subcomandos (129)**; los resultados JSON no cambian. Pruebas: `tests/test_i18n.py` (10) y e2e del panel en inglés. Pendiente: textos dinámicos del JS (avisos, estados), los 16 errores con partes variables, la ayuda de los argumentos (2 de 169) y los mensajes de la CLI |
| C2 | Instalador y versión única: pipx o ejecutable, acceso directo, `eolfi update --check` | Parcial: `eolfi update --check` (`eolfi/actualizacion.py`) muestra la versión, el modo de instalación (copia, pipx, entorno virtual o ejecutable), el commit si es una copia y las versiones del puente y de la extensión. Con `--red` compara con la última publicación o etiqueta de `CeltiaIA/Eolfi` (solo api.github.com, sin credenciales, nunca con `EOLAS_OFFLINE=1`). No instala nada. 11 pruebas con red simulada. Consulta real NO VERIFICADA: el repositorio aún no tiene publicaciones ni etiquetas. **17/11:** la rueda no incluía `generador/juez_web.mjs` ni `sites/render_driver.mjs` (B1 y C3 fallaban instalados): corregido en `pyproject.toml`. `tools/verificar_paquete.py` construye la rueda sin red en una copia temporal, la instala en un entorno virtual nuevo (lo que hace pipx), comprueba versión única (rueda, `--version`, `update --check`), modo `entorno_virtual`, los 182 archivos de `eolfi/` y el panel (`/api/health` y `/`): verificado. Ejecutable con PyInstaller 6.22.3 (entorno propio `~/.eolfi/tools/pyinstaller`, instalado a petición del titular): `tools/construir_ejecutable.py` deja `dist/eolfi-VERSIÓN-PLATAFORMA/` con `SHA256SUMS.txt` y lo verifica (versión, modo `ejecutable`, `-m eolfi` vía `eolfi/_ejecutable.py`, datos y panel): verificado en Windows x64 (24,7 MB). `eolfi acceso-directo [--donde escritorio\|menu] [--aplicar\|--quitar]`: `.lnk` en Windows (probado en carpeta temporal y leído de vuelta), `.desktop` en Linux; nunca sustituye un archivo ajeno; queda en el registro de acciones. 12 pruebas en `tests/test_instalador.py`. Pendiente: firma del ejecutable, `pipx` real (no instalado), Linux real del `.desktop` y macOS, publicar una versión |
| C3 | `eolfi web` con páginas renderizadas (SPA) y rastreo limitado con inventario de plantillas | Hecho en local: `eolfi web URL --render [--paginas N --profundidad D]` renderiza en Chrome sin interfaz (`eolfi/sites/render.py` y `render_driver.mjs`). Rastrea en anchura solo el mismo origen (como máximo 50 páginas y 5 saltos), respeta robots.txt, sigue rutas `pushState`, bloquea los otros hosts y analiza la estructura del DOM renderizado de la portada. Avisa si parece una SPA. 9 pruebas, una con Chrome real contra una SPA local. Pendiente: interacciones (clics, formularios) y una prueba contra un sitio público autorizado |
| C4 | Proyectos generados: e2e con Playwright y axe, PWA, i18n y receta de despliegue | Parcial (17/11): el juez funcional de `verify` (B1) admite la comprobación `sin_problemas_accesibilidad`: pasa axe-core (WCAG 2.0/2.1 A y AA y buenas prácticas; la versión fijada en `tests/e2e` o `EOLFI_AXE`) por la página en ese momento del recorrido, sin relajar su CSP, y falla con problemas graves o críticos; sin axe falla como NO VERIFICADO. Con ella, la plantilla `static` mostró dos fallos reales de contraste, ya corregidos: el atenuado sobre las tarjetas (pie de las citas) y el primario de la marca en el tema oscuro (enlaces a 2,9:1); la paleta garantiza ahora AA del texto y el atenuado sobre la superficie, y el tema oscuro tiene primario y acento propios. Prueba con la plantilla generada en claro y oscuro. `eolfi create --accesibilidad` instala esos criterios (sin errores de JS, axe en el estado inicial y tras cambiar el tema) ANTES de verificar, así que la plantilla base también se mide; con `--juez` se añaden al final de los criterios del titular. Prueba: `create` static con `--accesibilidad` sale en verde con «juez funcional (3/3)». El juez (y con él axe) cubre también `react`, `vue` y `svelte`: sirve la compilación de `npm run build` en `dist/`, lo que se publicaría; sin compilación no aprueba. Probado con una compilación con la forma de la de Vite; con un proyecto react/vue/svelte generado de verdad NO VERIFICADO (exige `npm install` con red). **Por defecto (17/11, decisión del titular):** `create`, la API y el plan del panel miden la accesibilidad en los destinos que cubre el juez cuando verifican; se quita con `--sin-accesibilidad`, `accesibilidad: false` o la casilla del panel (traducida). **Navegador propio:** `eolfi navegador instalar` deja en `~/.eolfi/navegador` `playwright-core` 1.64.1 y `axe-core` 4.14.0 (npm, sha512 en `package-lock.json`, sin scripts) y Chrome Headless Shell (revisión 1248, de cdn.playwright.dev), con manifiesto y SHA-256 del ejecutable y entrada en el registro de acciones; el juez lo prefiere al Chrome del equipo. Instalado en el equipo del titular y verificado con la rueda en un entorno virtual nuevo (`tools/verificar_paquete.py`: el juez instalado usa lo propio y aprueba 3/3). La CI de Python lo instala antes de pytest. Límite: Playwright no publica un SHA-256 del navegador para comparar. **Destinos con servidor (17/11):** el juez arranca `next start`, express, uvicorn (fastapi) o `runserver` (django) en 127.0.0.1 con lo que instaló la verificación, espera a que responda, juzga por URL y mata el árbol de procesos (el puerto queda libre); un servidor que no arranca o no responde no aprueba. Verificado con proyectos generados de verdad por `create` con verificación completa: express (express 5.3.0) y next (next 16.4.6, react 19.3.1) con `npm install` en carpetas temporales, y fastapi y django (Django 6.1.3) con un `.venv` sobre los paquetes del equipo: juez 3/3 con axe en los cuatro. Pendiente: PWA, i18n y receta de despliegue |
| C5 | Mapa visual de la app en el panel (grafo de pantallas y llamadas de REA) | Hecho (17/11): al abrir una evidencia de REA, el panel la dibuja antes del JSON (`eolfi/web/mapa.js`, sin bibliotecas ni Mermaid). `grafo_llamadas`: grafo por niveles en SVG con la función analizada, las del programa y las importaciones de otra biblioteca diferenciadas, flechas en el sentido de la llamada y la lista de llamadas en texto; el resultado trae ahora `enlaces` y las evidencias antiguas se dibujan a partir de su Mermaid. `mapa_app_android`: pantallas (actividades) y demás componentes con totales, la de inicio y lo exportado sin permiso, y los permisos peligrosos. `mapa_app_apple`: bundles por papel con su firma y los permisos de privacidad. Los nombres del objetivo se pintan como texto. Prueba e2e con los resultados reales de las funciones (con los dobles de REA) y axe sin problemas graves en claro y oscuro; de paso, los bloques JSON de las evidencias son enfocables con el teclado. Verificado en el navegador con una base de demostración. Límite: Android no tiene la navegación entre pantallas (REA no la da en estático); con una app real NO VERIFICADO aquí |
| C6 | Guías y ejemplos autorizados por flujo (lo que queda de la fase 7) | Parcial (17/11): las guías de O13 están completas. A las seis existentes (caja negra, API HTTP, triaje y diff, web y repo, puente, agente VS Code) se suma `ejemplos/crear-proyecto/GUIA.md`: fuente sintética propia, plan por `POST /api/projects/plan` sin ejecutar nada, ejecución rechazada (409) sin aprobación, aprobación solo de la versión vigente, trabajo `project` en modo auto, objeto `verification` con sus pasos y códigos de salida, lo que se conserva de la fuente sin copiarla, estado persistente tras reiniciar `serve` y la variante `create` de la CLI. Guías breves de los flujos nuevos: `registro-acciones` (B8: listar, verificar, clave sin sobrescribir, firma, eventos sin firmar al final y manipulación detectada), `instalador` (C2: `update --check` sin red = NO VERIFICADO con salida 2; acceso directo en vista previa, aplicado, retirado y sin tocar un archivo ajeno) e `idioma` (C1: ayuda de la CLI y errores de la API en inglés solo cuando se pide). Cada una con su prueba (`tests/test_guia_crear_proyecto.py`, `_registro_acciones`, `_instalador`, `_idioma`), en pytest y por tanto en la CI. Pendiente: retirar opciones (`informes/revision-retirada-y-limpieza-2026-11-12.md`, decisión del titular) y el servidor MCP en modo agente de un VS Code real (NO VERIFICADO) |
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
| E1 | Fusionar las PR de REA #20 a #35 en una rama de integración, en orden | Hecho (17/11): la PR #55 llevó a `main`, en orden, las 29 PR abiertas, entre ellas #20–#35 |
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
| G3 | Modo sin red en Eolas (`EOLAS_OFFLINE=1`) y regla de cortafuegos de salida | Parcial: Eolas V2 pasa `--offline` nativo y variables offline al servidor, registra el modo y rechaza reutilizar un proceso iniciado con otro modo. Pendiente: regla de cortafuegos ejecutada y verificada por el titular |
| G4 | **Reconstruir modelos**: del original (BF16, ya en disco) a cada cuantización con `llama-quantize`, con receta, SHA-256 de entrada y salida y registro | Flujo CLI con receta, hashes fijados, auditoría y hash posterior del original. 17/11: Gemma BF16 real → Q4_K_M convertido (salida 0, 7.381.383.776 bytes, original intacto) y `modelos probar` (smoke CPU con llama-cli, sin pensamiento) responde «43». Banco, layouts K y procedencia del SDK siguen NO VERIFICADOS. Ver `informes/modelos-g-2026-11-16/avance-g4-real-y-smoke.md` |
| G5 | **Actualizar modelos**: comprobar si hay versión nueva, descargar solo con permiso, auditar (G1) y comparar con el banco antes de adoptar | Parcial: `eolfi modelos actualizar` compara el SHA-256 local con el publicado en Hugging Face (solo con `--red`, nunca con `EOLAS_OFFLINE=1`, solo hosts de HF y sin credenciales) y `eolfi modelos descargar` baja un archivo fijado por commit y SHA-256 sin sobrescribir; un hash distinto queda como `.rechazado`. Después lo audita (G1), deja un recibo y lo registra en B8. 23 pruebas con red simulada; guía en `docs/modelos-actualizar.md`. Pendiente: consulta real (NO VERIFICADA), comparación con el banco antes de adoptar y reanudación de descargas |
| G6 | **Adaptar al nuevo Eolas**: metadatos que usa el planificador (ventana deslizante, capas), plantilla de chat propia y perfil por modelo; validar cada modelo reconstruido con `eolas plan` y un smoke | Parcial avanzado: `eolas-v2 plan` valida receta, SHA-256, smoke, plantilla, contexto, capas y ventana. El perfil real `gemma4_recon_q4` fue adoptado inactivo y fijado al hash; el activo siguió siendo `gemma_q4`. Arranque temporal e inferencia real correctos (`EOLFI-G6`), seguidos de parada comprobada. La retirada reversible conserva el GGUF. Pendiente: banco de calidad y ajuste definitivo de memoria/rendimiento |
| G7 | Ajuste fino (LoRA) con los ejemplos verificados del bloque B6 | Largo plazo; depende del hardware |

## Bloque F: higiene (depende del titular)

| # | Pieza | Estado |
|---|---|---|
| F1 | Facturación de GitHub Actions: la CI no arranca en Eolfi ni en CeltiaIA | Resuelto en Eolfi (17/11: la CI de las PR #55 y #56 corrió en Ubuntu y Windows); CeltiaIA sin comprobar |
| F2 | Fusionar las PR abiertas (22 en Eolfi) en el orden de `docs/vas/VAS-auditoria-eolfi.md` | Hecho en Eolfi (17/11, PR #55: 29 PR). En CeltiaIA/CeltiaIA quedan abiertas #6–#13 |
| F3 | Revisar `REGISTRO_LIMPIEZA.md` con el titular (LIM-040, copia de una clave, primero) | Pendiente |
| F4 | Ruff F sin avisos (PR #19, rehacer desde `main`) | Hecho (17/11): la #19 entró con la #55 y se corrigieron los 12 avisos que dejaron las fusiones; `ruff check --select F eolfi tests tools` sin avisos (ruff 0.16.8) |

## Orden de ejecución

1. **A1 a A5** (voz en el chat): lo pedido ahora, sin dependencias y sin instalar nada.
2. **B1 y B2** (juez en `verify` y determinismo): sin ellos, ninguna mejora posterior se puede demostrar.
3. **A6 y A7**, **B4 y B5**.
4. **C1, C2 y C6** (idiomas, instalador y guías).
5. **G1 a G4 y G6** (modelos), **B6 a B8**, **C3 a C5**, **E**.
6. **D**.

Cada pieza: rama propia, pruebas, comprobación en vivo cuando aplique y nota en `ESTADO-TRABAJO.md`. Las casillas
solo cambian con evidencia.
