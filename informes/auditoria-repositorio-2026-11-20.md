# Auditoría acotada del repositorio Eolfi — 20/11/2026

Autoría de entrega: Luis. Trabajo local, sin commit ni publicación. Estado general: **NO VERIFICADO** como cierre integral. La petición de revisar «todo» se abordó por áreas, pero esta revisión no demuestra ausencia de defectos ni equivalencia funcional completa.

## Coordinación y alcance

Se leyó `AGENTS.md`, el plan, la CI y `COORDINACION.md`. Las rutas de Codex se anotaron y liberaron en la tabla de archivos ocupados. Se preservaron los cambios previos de Claude en `eolfi/herramientas_rea.py` y `tests/test_herramientas_rea.py`, la muestra B6 y los informes B7/G6. Codex no arrancó Eolas V2, no detuvo Docker, no instaló dependencias ni hizo commit o push. Claude revisó después la primera tanda, ejecutó las suites finales y la publicó en `luis/voz-piper` con el commit `4d76bf4`. Las pruebas de Codex se ejecutaron sobre `D:\Eolfi`; sus directorios temporales los eligió pytest en el perfil restringido de este cliente.

Se revisaron generación/verificación, cliente API, actualización de modelos, puente de chats, puente VS Code, CI y pruebas e2e. La auditoría estática REA queda detallada en la sección final cuando termine la herramienta; no se ejecutó ningún objetivo para ganar cobertura.

## Cambios aplicados

| Ruta | Motivo y cambio | Evidencia específica |
|---|---|---|
| `eolfi/cliente_api.py`, `tests/test_cliente_api.py` | Evita firmas inválidas por `self`/`cuerpo` y colisiones de parámetros normalizados; prueba que el cliente generado se carga y ejecuta. | `python -m pytest -q tests/test_rea_compuestas.py tests/test_cliente_api.py`: 78 aprobadas. |
| `eolfi/generador/juez.py`, `tests/test_juez.py` | `EOLFI_JUEZ=0` deja la verificación funcional como fallo `NO VERIFICADO`; el diagnóstico largo de stderr conserva el comienzo de la última línea, incluido el tipo de excepción. | Dos pruebas focales tras ambos cambios: 2 aprobadas. `tests/test_juez.py` posterior: 37 aprobadas, 3 omitidas y 1 fallida (caché de Go denegada). |
| `eolfi/modelos_actualizar.py`, `tests/test_modelos_actualizar.py` | Respuestas API sin estructura, tamaño o metadatos LFS válidos, y error de lectura local, devuelven `NO VERIFICADO` en vez de abortar o sugerir una descarga con tamaño dudoso. | 31 pruebas específicas aprobadas; área: 142 aprobadas, 6 omitidas, 1 fallida por Windows IP Helper con acceso denegado. |
| `eolfi/bridge/approval.mjs`, `server.mjs` y pruebas | Acepta únicamente respuestas explícitas 0/1; una comparativa cancelada durante la aprobación no inicia envíos. | `node --test` en `eolfi/bridge`: 72 aprobadas, 4 omitidas. |
| `tests/e2e/panel.test.mjs` | Aísla también el registro de acciones del proceso Python auxiliar para no competir con el perfil real. | `npm.cmd test` en `tests/e2e`: 28 aprobadas, sin aviso de cerrojo en la última ejecución. |
| `REGISTRO_LIMPIEZA.md` | LIM-055 conserva y etiqueta un log B7 sin seguimiento cuya sesión y resultado hay que cotejar antes de decidir nada. | `git status --short`, `Get-Item` y búsqueda de referencias en tres documentos. |

## Comprobaciones y límites

| Comando / directorio | Resultado |
|---|---|
| `python -m pip check` / raíz | Salida 0, sin requisitos rotos del entorno actual. |
| `ruff check --select F eolfi tests` / raíz | Salida 0. |
| `git diff --check` / raíz | Salida 0 en la comprobación previa al último ajuste; repetir al cerrar. |
| `python -m pytest -q` / raíz | Salida 1: **1319 aprobadas, 15 omitidas, 16 fallidas**, 1033,06 s. Esta corrida precede al último ajuste del diagnóstico en `juez.py`; no valida integralmente el árbol final. |
| `python -m pytest -q tests/test_juez.py` / raíz, después del ajuste | Salida 1: 37 aprobadas, 3 omitidas, 1 fallida; `go test` no pudo abrir `D:\dev\go\cache` (acceso denegado). |
| `node --test` / `eolfi/bridge` | Salida 0: 72 aprobadas, 4 omitidas. Las omitidas requieren navegador real del puente. |
| `node --test` / `eolfi/vscode-bridge` | Salida 0: 211 aprobadas. Aviso de invocación recursiva de `node:test`, sin fallo. |
| `npm.cmd test` / `tests/e2e` | Salida 0: 28 aprobadas en Chrome del equipo; tres ejecuciones, la última sin aviso del registro real. |
| `python -m pytest -q` sobre 13 áreas afectadas, ejecutado por Claude en su entorno sin sandbox | Salida 0: **333 aprobadas, 1 omitida, 0 fallidas** en 4 min 49 s, sobre el árbol con estos cambios. Es una comprobación cruzada comunicada por Claude; no sustituye la suite completa final. |
| `python -m pytest -q` completo, ejecutado por Claude antes de `4d76bf4` | Salida 0: **1342 aprobadas, 8 omitidas** en 13 min 22 s; Ruff F y `git diff --check`, salida 0. El hook previo al push repitió Python, ambos puentes Node y e2e, todos con salida 0. |

### Fallos de la suite Python

- **Dependencias y herramientas fuera del entorno:** dos casos Rust fallan al compilar `serde`/`serde_json`; Go `vet` no puede abrir su caché en `D:\dev\go\cache`; FastAPI no se pudo restaurar por DNS/red cerrada; la instalación de la rueda en un entorno nuevo tampoco alcanzó su aceptación. Son comprobaciones de instalación/compilación **NO VERIFICADAS** aquí. No se abrió la red ni se instaló nada para forzar verde.
- **Rutas y servicios restringidos:** tres pruebas de adaptadores externos rechazan una ruta temporal de este cliente con `#!sandbox` como argumento no seguro; `modelos_red` devuelve `NO VERIFICADO` por Windows IP Helper (Errno 5); la prueba de repositorio privado ve `github.com` como dirección no pública en anti-SSRF. La prueba de poda de clones conserva un clon antiguo bajo esta ruta temporal y requiere diagnóstico propio.
- **Observación Windows:** fallan seguimiento de proceso hijo, efecto de registro y dos escenarios de UI/PrintWindow. La prueba de ventana superpuesta abrió temporalmente una ventana magenta y llegó a su `finally`; el PID comunicado para la tapa ya no figuraba en `Get-Process` al cierre. El resultado de observación es parcial, no cobertura demostrada.
- **Juez de consola:** el tipo `FileNotFoundError` quedaba fuera del recorte de 200 caracteres de stderr. Se corrigió después de la suite global y sus dos pruebas focales pasaron. No se atribuye a permisos.

Las solicitudes de repetir suites de área con ejecución local ampliada fueron rechazadas automáticamente por la política granular del cliente (`sandbox_approval=false`); no se eludió la restricción. Claude repitió las 13 áreas afectadas sin el sandbox de este cliente y no reprodujo los 16 fallos. Eso es compatible con límites del entorno local; la causa exacta de la poda de clones en este cliente no está diagnosticada. Las pruebas verdes no prueban equivalencia global. Un proyecto generado con `do_verify=False` en la preparación e2e es un dato de prueba y no un proyecto entregable verificado.

## Continuación posterior a `4d76bf4`

Esta tanda permanece sin commit mientras Claude ejecuta G6 bis y no forma parte de la suite completa citada arriba:

- `eolfi/cliente_api.py` valida que la base sea HTTP/HTTPS con host y puerto válidos, sin credenciales, consulta ni fragmento; admite prefijos de ruta. Valida un plazo positivo y finito, limita las respuestas a 16 MiB por defecto, tolera HTTPError sin cabeceras y detecta `Content-Type` sin distinguir mayúsculas. Bloquea por defecto redirecciones a otro origen; si se habilitan explícitamente, conserva solo `Accept`, `Accept-Language` y `User-Agent` al cambiar de origen.
- `eolfi/rea_compuestas.py` solo incorpora URI HTTP/HTTPS válidas al borrador, elimina usuario, contraseña y fragmento, y redacta secretos tanto en consulta como en segmentos opacos de ruta. Usa presupuestos amplios: URI de 64 KiB, 1.000 campos de consulta, 100.000 registros, 16 MiB por cuerpo y 256 MiB agregados; la rama completa aplica los mismos saneados y solicita el límite de registros a REA.
- La redacción de capturas es necesariamente heurística: no permite afirmar ausencia de secretos con nombres o formatos arbitrarios. El resultado debe revisarse antes de compartirlo.
- `README.md` documenta el efecto de `EOLFI_JUEZ=0` y el cliente desde captura. `docs/modelos-actualizar.md` explica cuándo los metadatos remotos incompletos quedan `NO VERIFICADO` sin propuesta de descarga.
- Verificación focal actual: `python -m pytest -q tests/test_cliente_api.py tests/test_rea_compuestas.py` → **108 aprobadas**. La revisión de seguridad encontró y corrigió fuga de credenciales por redirección entre orígenes, posible SSRF por 30x externo, secretos en rutas, bases terminadas en `?`/`#` y presupuestos desiguales en la rama completa. Una segunda lectura amplió el bloqueo al cambio de esquema/puerto, redujo las cabeceras del opt-in a una lista inocua, cubrió camelCase/segmentos codificados y añadió presupuesto agregado. Bandit no señaló hallazgos medios ni altos en los dos módulos; sus dos avisos bajos corresponden a un cierre tolerante y a un uso previo de `subprocess`, fuera de este diff. Ruff F/E9, compilación de los módulos y `git diff --check` → salida 0. Una ejecución intermedia detectó Python generado inválido por un escape insuficiente; se corrigió y no se reproduce en la ejecución final.

La suite completa sobre esta continuación queda pendiente. Estos resultados no cambian el estado REA ni demuestran equivalencia funcional completa.

## Pendientes y riesgo

1. Las 13 áreas afectadas pasaron en el entorno de Claude. Mantener como pendiente el diagnóstico exacto de la poda de clones en este cliente y la incompatibilidad de `#!sandbox` con el filtro de argumentos; no alterar las aserciones para obtener verde.
2. Ejecutar la suite Python completa después de la continuación posterior a `4d76bf4`; la suite completa verde anterior no contiene esos cambios.
3. Revisar con Claude la rama de creación y este informe, como quedó solicitado en `COORDINACION.md`. El registro de limpieza mantiene LIM-053 y LIM-055 como evidencias conservadas, sin decisión de borrado.
4. REA estático: **NO VERIFICADO**, como se detalla abajo. Los cambios JavaScript tienen pruebas Node y e2e, pero eso no sustituye el análisis del artefacto ni demuestra comportamiento en chats web reales.

## REA: intento y cobertura

Se invocó `analyze_javascript_application` sobre los directorios `D:\Eolfi\eolfi\bridge` (cinco rutas fuente seleccionadas) y `D:\Eolfi\eolfi\vscode-bridge` (cuatro rutas). Ambas llamadas se abortaron tras aproximadamente 1363 s sin devolver Evidence ni grafo. **Cobertura, proveedor y versión: NO VERIFICADO; desconocidos al menos los nueve módulos seleccionados y el resto de cada inventario.** Plataforma cliente: Windows. No se repitió la misma llamada sin remediar el bloqueo del host, ni se ejecutaron los objetivos. El conteo de hallazgos REA es indeterminado, no cero defectos.

Identidades de archivos relevantes después de los cambios, SHA-256: `bridge/server.mjs` `c68ef20f6199ccdc2848cdc092a20b3c41c658a35c05b97d7909f8e5126161a5`; `bridge/approval.mjs` `75edcbc843b7b33134c8cec86c3914a1046563ec9e7d9773ea8c02afeb1bce6b`; `vscode-bridge/extension.js` `09893f358e1c68bec6c7093bda1a0e47f6e7a127fd8fa9af1db759f9bbb33fb5`. Son hashes locales, no un resultado REA. Falta una ejecución REA con plazo de llamada del cliente suficiente o un alcance acotado que devuelva Evidence; el análisis estático por sí solo tampoco verificaría la interacción real.
