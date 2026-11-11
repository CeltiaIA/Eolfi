# Avance Fase 2: interfaz móvil Android — 2026-11-11

Rama `fase2-interfaz-movil` (desde `main` `14c5051`). Casilla del plan: «captura de escenarios de interfaz para
escritorio y móvil». El escritorio ya estaba (Windows, UI Automation). Este avance añade **Android**. La casilla
sigue abierta: falta probar con un dispositivo real y falta iOS.

## Qué se añade

| Cambio | Archivos |
|---|---|
| Paso de guion `mobile`. Admite `platform: android`, `package`, `activity` y `device`, todos opcionales salvo `package`; `timeout`; `stop`, `screenshots` y `clear_data`; y acciones `tap`, `input_text`, `key`, `wait_for` y `read` con selectores `resource_id`, `text` y `content_desc`. Se valida entero y no se admite en el modo contenedor. | `eolfi/observe/mobile.py`, `eolfi/observe/script.py` |
| Ejecución con `adb`, que se busca en `EOLFI_ADB` o en el PATH. Exige un único dispositivo listo, o el que se indique. No instala apps ni concede permisos: si el paquete no está instalado, el paso es un error. Tras cada acción guarda la actividad en primer plano y el árbol de `uiautomator dump`, con una huella de pantalla que no incluye posiciones ni foco. Las capturas PNG son opcionales: hasta 1 MiB cada una y 20 por paso. | `eolfi/observe/mobile.py`, `eolfi/observe/session.py` |
| Privacidad y seguridad. Los campos de contraseña se guardan sin texto. El número de serie solo como hash. El árbol pasa por la ocultación de datos personales. Se rechazan los volcados que traen DTD o entidades y se acotan a 300 elementos y 4 MiB. Lo que escribe `input_text` se guarda como huella en la evidencia de la sesión. | `eolfi/observe/mobile.py` |
| Cobertura `ui_mobile`, con tres estados: observed, partial o not_available, y la razón cuando corresponde. Factores no fijados: el dispositivo Android, y los datos de la app cuando no hay `clear_data`. Contenido visual sin redactar. | `eolfi/observe/session.py` |
| La comparación entre sesiones incluye la versión de la app y, por acción, el estado, la actividad, la interfaz y la captura. | `eolfi/observe/compare.py` |
| Especificación: entradas (paquete y acciones), máquina de estados (actividad y huella) y ejemplos de pantallas con los textos visibles. El modelo de reconstrucción lo trata como interfaz de usuario. | `eolfi/spec/build.py`, `eolfi/reconstruct/core.py` |
| Plan de sesión (`eolfi observe plan`): muestra la ruta de adb, el paquete y el dispositivo; advierte que actúa sobre un dispositivo real sin aislamiento y que `clear_data` borra datos. | `eolfi/security/levels.py` |
| El informe del caso admite capturas PNG de móvil: hasta 1 MiB y 2000×4000, con comprobación de firma y SHA-256. | `eolfi/core/case_report.py` |

## Pruebas

`tests/test_observe_mobile.py` tiene 19 pruebas y corre contra `tests/fake_adb.py`, un adb simulado con una app
sintética: campo de nombre, botón «Saludar», campo de contraseña y tecla BACK.
- **Validación:** 9 casos de guion y el rechazo del modo contenedor.
- **Sin adb:** el paso queda `unavailable` y nunca se declara observado.
- **Selección de dispositivo:** ninguno, sin autorizar o varios.
- **Paquete no instalado:** es un error y no se intenta instalar nada.
- **Escenario completo:** las cinco pantallas, la versión de la app, la identidad del dispositivo sin el número de serie, la contraseña ausente, las capturas PNG íntegras, la cobertura y el informe HTML.
- **Comparación:** dos sesiones iguales dan idénticas y una distinta da diferencias.
- **Especificación:** máquina de estados y ejemplos de pantalla.
- **Plan:** advertencias del dispositivo real y de `clear_data`.
- **Análisis del árbol:** rechazo de DTD, acotado de elementos y entrecomillado de `input text`.

## Comandos y resultados (Windows 11, Python 3.12.10, `D:\Eolfi-fases34`)

| Comprobación | Resultado |
|---|---|
| `python -m pytest -q tests/test_observe_mobile.py` | 19 aprobadas |
| `python -m pytest -q` | 533 aprobadas, 2 omitidas y 2 fallos: aserciones antiguas que esperaban `ui_mobile` siempre «not_available». Se cambiaron a «not_requested» (sin pasos móviles no se pide) y las 2 pasan después |
| `python -m ruff check --select F` | sin avisos |
| `node --test` en `eolfi/bridge` | 67: 63 aprobadas, 0 fallos, 4 omitidas |
| `node --test` en `eolfi/vscode-bridge` | 178 aprobadas, 0 fallos |
| `npm test` en `tests/e2e` | 18 aprobadas, 0 fallos |

## NO VERIFICADO y límites

- **Dispositivo o emulador real.** En este equipo no hay `adb`: se buscó en el PATH y en el disco. Hay un móvil
  conectado, pero es de uso personal y no se ha usado. Las órdenes son las estándar (`devices`, `getprop`,
  `pm path`, `dumpsys package`, `dumpsys window`, `monkey`, `am start -W`, `uiautomator dump`, `exec-out cat`,
  `input tap|text|keyevent`, `screencap -p`, `am force-stop` y `pm clear`). Su salida real varía según el
  fabricante y la versión de Android, sobre todo la de `dumpsys window`. Si no se reconoce la actividad, el
  registro la deja vacía y no la inventa.
- `input text` no escribe caracteres fuera de ASCII en muchos dispositivos. Es una limitación de Android, no de
  Eolfi.
- Las vistas sin accesibilidad no se ven: lienzos, juegos y WebView sin accesibilidad.
- iOS no está implementado.

## Registro de limpieza

No hay candidatos nuevos.
