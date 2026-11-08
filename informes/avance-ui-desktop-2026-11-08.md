# Avance de observación visual de escritorio — 2026-11-08

## Alcance

Se añadió captura JPEG optativa por acción a los escenarios `desktop` de Windows UI Automation. El controlador captura únicamente la primera ventana del proceso objetivo; limita cada paso a 20 imágenes de 256 KiB, escala máxima 1280×800, y registra dimensiones y SHA-256. La sesión comprueba el hash y tamaño, el informe HTML autocontenido incrusta capturas JPEG válidas y la comparación de replay registra el hash visual como aspecto separado.

La prueba ejecutó una aplicación WinForms sintética autorizada con tres acciones. El SHA-256 de la muestra fue `283706167e3ff1de3f3cf11b2223fc84a1663c2dae632269c0ca4464642568b2`. Las capturas diferían en replay y se reportaron como no reproducibles; los estados de UI Automation se compararon por separado. Las imágenes de la prueba se guardaron en el almacenamiento temporal del caso y no se retuvieron como artefactos del repositorio.

## Validación ejecutada

- `tests/test_observe.py`: 34 passed.
- `python -m pytest -q`: 455 passed, 2 skipped.
- `npm test` desde `tests/e2e`: 18 passed.

Python usado: `C:\Users\mejil\AppData\Local\Programs\Python\Python312\python.exe`.

## Límites

- Es evidencia de ejecución de la prueba local de Windows, no cobertura REA ni una validación sobre una aplicación de producción.
- La captura visual no redacta texto, credenciales ni datos personales; la cobertura los marca `not_redacted`. Debe habilitarse solo para ventanas cuyo contenido se pueda conservar.
- UI móvil sigue `NO VERIFICADO`: no se encontró `adb`, Android SDK ni dispositivo/emulador disponible.
- La igualdad de hash visual estricta puede variar por animaciones, antialiasing o datos cambiantes; la diferencia se clasifica como aspecto no reproducible, no como defecto confirmado.
