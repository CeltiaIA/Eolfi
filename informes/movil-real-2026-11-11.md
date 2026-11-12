# Paso «mobile» con un dispositivo Android real — 2026-11-11

Rama `fase2-movil-real`, creada desde `main` en `a0621aa`. Se continúa la casilla de la Fase 2 sobre la interfaz
móvil: el paso `mobile`, que hasta ahora solo se había probado con un adb simulado, se ejecuta por primera vez en
un dispositivo físico.

## Entorno

- **Dispositivo:** Xiaomi Redmi Note 12R Pro (`22101317C`, nombre en clave `sunstone`), Android 14, SDK 34,
  arm64-v8a. Compilación `Redmi/sunstone/sunstone:14/UKQ1.230917.001/V816.0.4.0.UMQMIXM`. Recién restablecido de
  fábrica y apartado por el titular para pruebas. Sin SIM.
- **adb:** Android platform-tools 37.0.1, en `D:\Tools\platform-tools`.
  - Descargado de `dl.google.com` con autorización del titular.
  - Zip de 8 044 989 bytes, SHA-256 `45F4D631…BC1A99`.
  - `adb.exe` con firma Authenticode válida de Google LLC.
  - Añadido al PATH del usuario a petición del titular.
- **App observada:** Calculadora del sistema (`com.miui.calculator` 15.0.14, código 315000014). No guarda datos
  personales. No se usó `clear_data`.

## Defectos que encontró el dispositivo real y su corrección

Cada corrección tiene una prueba que reproduce la situación en `tests/fake_adb.py`.

| Observado en el Redmi | Defecto en Eolfi | Corrección | Prueba |
|---|---|---|---|
| El primer `uiautomator dump`, justo después de lanzar la app, no deja el archivo («could not get idle state»). | El paso entero fallaba con «volcado no reconocido». | Hasta 5 reintentos dentro del plazo del paso; si aun así falla, se guarda el mensaje real de uiautomator. | `test_reintenta_el_volcado_mientras_la_ventana_se_dibuja` |
| Con la pantalla de bloqueo o el panel de notificaciones visibles, `dumpsys window` sigue dando la app como `mFocusedApp`, pero el árbol es de `com.android.systemui`. | La pantalla de bloqueo se registraba como pantalla inicial de la app. | Para considerar la app en primer plano se exige además que el árbol volcado sea suyo (`window_package`). | `test_primer_plano_exige_la_ventana_dibujada` |
| `input tap` responde con `SecurityException … INJECT_EVENTS`. En MIUI hace falta «Depuración USB (ajustes de seguridad)». | Solo se veía el final de una traza de Java. Se perdían las acciones ya registradas. | El error se reconoce sobre la salida completa y el mensaje dice qué ajuste activar. Esa acción queda `input_blocked`, el resto `skipped` y lo ya registrado se conserva. | `test_entrada_bloqueada_se_explica_y_no_es_comportamiento` |
| La pantalla se apagó a mitad de la segunda sesión (`mWakefulness=Dozing`). | Las acciones daban «not_found» sobre la pantalla de bloqueo y la especificación lo tomaba como comportamiento «inferido» de la app. | Antes de empezar se comprueban el estado de la pantalla (`dumpsys power`) y el foco del panel del sistema: si está apagada o bloqueada, el paso queda `unavailable` con instrucciones (Eolfi no desbloquea). Si ocurre a mitad, la acción queda `interrupted` y el resto `skipped`. | `test_pantalla_bloqueada_antes_y_durante` |
| — | Dos sesiones que fallan igual por el controlador salían en la especificación como requisito **«seguro»** con confianza alta. | En `spec/build.py`, si el controlador no observó el objetivo (no disponible, sin acciones, entrada bloqueada o interrumpida), el requisito queda `not_observed`, con grado «desconocido», confianza baja y motivo en `not_observed_reason`. No genera pruebas ni entra en la reconstrucción. | las dos anteriores |

Otra corrección: la app se cierra (`am force-stop`) aunque el paso falle o se agote el plazo.

## Resultado en el dispositivo real

| Comprobación | Resultado |
|---|---|
| Selección de dispositivo, identidad del dispositivo (número de serie solo como hash) y de la app | correcto |
| Lanzamiento, volcado y pantalla inicial (`com.miui.calculator.cal.CalculatorActivity`, 48 elementos, «0» en la expresión) | correcto |
| Captura PNG de la pantalla inicial | correcto: 85 KB, 1080×2400 |
| Pantalla apagada o bloqueada | `unavailable` con instrucciones; requisito «desconocido» |
| Toques y teclas (`tap`, `input_text`, `key`) | **NO VERIFICADO**: el teléfono los bloquea (INJECT_EVENTS). `persist.security.adbinput` sigue vacío tras el intento del titular de activar el ajuste; en MIUI suele exigir SIM y cuenta Mi. Eolfi lo detecta y lo explica. |
| Especificación de las sesiones bloqueadas | `not_observed`, «desconocido»: correcto |

## Comandos y resultados (Windows 11, Python 3.12.10, `D:\Eolfi-fases34`)

| Comprobación | Resultado |
|---|---|
| `python -m pytest -q tests/test_observe_mobile.py` | 23 aprobadas |
| `python -m pytest -q` | 539 aprobadas, 2 omitidas, 0 fallos. Tras los cambios del ZTE: 540 aprobadas, 2 omitidas, 0 fallos |
| `python -m ruff check --select F eolfi tests/test_observe_mobile.py tests/fake_adb.py` | sin avisos |
| `node --test` en `eolfi/bridge`, `eolfi/vscode-bridge` y `npm test` en `tests/e2e` | Ver la PR: este cambio no toca el código de Node. |

## NO VERIFICADO y límites

- **Acciones táctiles y de teclado en un dispositivo real.** Están bloqueadas por MIUI hasta que se active
  «Depuración USB (ajustes de seguridad)». Siguen probadas solo con el adb simulado.
- **Otros fabricantes y emuladores:** sin probar. La salida de `dumpsys` cambia según el fabricante.
- **iOS:** no está implementado.

## Registro de limpieza

`D:\Tools\platform-tools` es una herramienta instalada a petición del titular, no un artefacto temporal. Las bases
de prueba están en el scratchpad de la sesión, fuera del repositorio.

## Segundo dispositivo: ZTE Blade A34 — toques verificados (2026-11-12)

- **Dispositivo:** ZTE Blade A34 (`P963F94`), Android 13, SDK 33. Conectado por USB y autorizado por el titular.
  Al contrario que MIUI, acepta `input` desde adb sin ningún ajuste extra.
- **App:** Calculadora de Google (`com.google.android.calculator` 9.3, código 85022643).
- **Escenario:** borrar todo, 7, ×, 6, = y leer.
- **Resultado:** las 7 pantallas en estado `ok` y en primer plano. Fórmula y resultado leídos del árbol:
  «Sin fórmula» → «7» → «7×» → «7×6» con vista previa «42» → «42». Capturas PNG de 720×1612.
  Cobertura `ui_mobile: observed`. El informe del caso muestra las 7 capturas.

Dos hallazgos más, que solo se ven en un dispositivo real:

| Observado en el ZTE | Situación en Eolfi | Decisión | Prueba |
|---|---|---|---|
| Sin `clear_data`, la segunda sesión muestra en el historial el «42» de la primera. | La especificación marca el requisito como contradicho en `*.interfaz`. | **Es correcto:** la app guarda historial entre ejecuciones y el plan ya avisaba («datos de la app» como factor no fijado). Con `clear_data` (solo borra el historial de la Calculadora, creado en esta prueba) las 7 huellas de interfaz coinciden en las dos sesiones. | `test_estado_persistente_y_capturas_en_la_especificacion` |
| Los hashes de las capturas cambian en cada ejecución (reloj, batería y cursor de la barra de estado). | Dos sesiones independientes dejaban el requisito «contradicted» y con grado «desconocido» solo por los píxeles. | **Defecto corregido:** la especificación ya no compara las capturas. Las guarda como `visual_evidence` (`compared: false`, con el motivo). El requisito del ZTE queda `observed`, `seguro`, `high`, con 24 aspectos esperados. La comparación entre sesiones sigue listando las diferencias visuales: es un hecho y no se oculta. | ídem |

Con esto, **`tap`, `wait_for`, `key` y `read` quedan verificados en un dispositivo real**. Escenario aparte con
`clear_data`: 7, esperar a que la fórmula sea «7» y BACK. El paso termina `ok` y la última pantalla es el lanzador
de ZTE (`com.zte.mifavor.launcher`). **`input_text` sigue NO VERIFICADO en un dispositivo real:** la Calculadora no
tiene campo de texto y no se usaron apps con datos personales. En el Redmi, los toques siguen bloqueados por
MIUI.
