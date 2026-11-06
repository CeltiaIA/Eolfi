# Registro de posibles restos obsoletos y limpieza

Registro vivo para la hoja de ruta de `PLAN_INGENIERIA_INVERSA_EOLFI.md`. Sirve para decidir al final qué conviene retirar; **no autoriza borrados durante el desarrollo**.

## Criterios

- Solo se registra un candidato cuando hay una ruta concreta y evidencia. No se etiqueta como basura por antigüedad, tamaño o por estar fuera de Git.
- Cada decisión debe comprobar referencias en código, configuración, CI, documentación, pruebas y uso local conocido. Una búsqueda textual sin resultados es evidencia parcial.
- Estados: `PENDIENTE` (requiere investigación), `CONSERVAR` (uso o motivo confirmado), `PROPONER RETIRAR` (evidencia suficiente para revisión al cierre), `RETIRADO` (solo después de la revisión final acordada).
- No se elimina, mueve ni modifica ningún candidato antes de acabar el plan y revisar las propuestas con el usuario. Mantener intactos backups y cambios locales sin confirmar.

## Candidatos iniciales — 2026-11-06

| ID | Ruta / grupo | Evidencia actual | Riesgo / comprobaciones pendientes | Estado |
|---|---|---|---|---|
| LIM-001 | `.eolfi-browser-check.out.log`, `.eolfi-browser-check.err.log` | Archivos locales sin seguimiento; los nombres sugieren salida de una comprobación del navegador. No apareció ninguna referencia textual en el repositorio. | Confirmar que no son evidencia requerida para el informe y que ningún proceso los sigue usando; revisar antes de proponer limpieza. | PENDIENTE |
| LIM-002 | `eolfi-modo-agente.patch` | Archivo local sin seguimiento; no hay referencias textuales en el repositorio. | Puede ser un parche de recuperación de cambios del usuario. Comparar su contenido con el árbol actual y determinar si conserva cambios únicos antes de proponer nada. | PENDIENTE |
| LIM-003 | `backups/` | Hay copias con nombres y fechas de respaldo, además de `eolfi-para-git.tgz`; la carpeta está ignorada por Git. | Son posibles mecanismos de recuperación. Inventariar procedencia, contenido y relación con el árbol actual; no borrar sin decisión expresa al cierre. | CONSERVAR |
| LIM-004 | `generated/nuevo-proyecto/` | Carpeta generada e ignorada por Git; consta en el inventario local, sin análisis de referencias ni de su propósito. | Determinar si es demo, fixture, salida útil o residuo de una prueba; comprobar si el usuario quiere conservar proyectos generados. | PENDIENTE |
| LIM-005 | `PLAN_CORRECCIONES.md`, `PLAN_MEJORAS_2026-11-05.md` | Ambos se declaran históricos y enlazan al backlog activo. | No son código ni basura; conservar como historial salvo que al final se decida consolidar su contenido y referencias. | CONSERVAR |
| LIM-006 | `samples/index.json` y `samples/` local | El informe de estado dice que el índice apunta a elementos ausentes; el APK local carece de procedencia/licencia documentada y está excluido de validación. | Corregir/retirar del índice las referencias no disponibles y documentar procedencia antes de decidir sobre muestras; no borrar muestras en esta fase. | PENDIENTE |
| LIM-007 | Scripts y módulos candidatos a obsolescencia | En esta primera inspección no se ha demostrado ningún script o módulo Python/JavaScript sin uso. | Revisar dependencias, puntos de entrada, empaquetado, CI, referencias dinámicas y pruebas durante las fases; añadir hallazgos concretos aquí. | PENDIENTE |

| LIM-008 | `eolfi/core/cases.py`: `CaseStore._migrate` y la rama `case_package_version == 1` de `import_case` | Compatibilidad añadida en la Fase 1 para bases y paquetes creados con el esquema v1 de casos (solo SHA-256, sin identidad/entorno/herramientas). La SQLite local `eolfi.db` no tenía tablas de casos al revisarlo (2026-11-06). Cubierto por `test_v1_schema_and_v1_package_are_upgraded`. | Retirar solo cuando no queden bases ni paquetes v1 en uso; confirmar con el usuario si compartió paquetes v1. | CONSERVAR |
| LIM-009 | Imports sin uso: `struct` en `eolfi/cli.py` (función alrededor de la línea 684) y `HTTPStatus` en `eolfi/server.py:27` | `ruff check --select F` los marca como F401; `HTTPStatus` ya estaba en el commit inicial. No forman parte de los cambios de la Fase 1. | Comprobar que ningún código dinámico ni prueba los usa y retirarlos en una limpieza de estilo, con la suite completa. | PENDIENTE |

## Registro de revisiones

- **2026-11-06 — inicio:** se inspeccionaron estado de Git, inventario de directorios `generated/`, `backups/`, `samples/` y `.claude/`, referencias textuales de algunos artefactos y los planes activos/históricos. No se borró ni movió nada. Este barrido no es un análisis completo de código muerto.

- **2026-11-06 — Fase 1:** añadidas LIM-008 (compatibilidad v1 de casos) y LIM-009 (imports sin uso preexistentes). No se borró ni movió ningún candidato; `.claude/launch.json`, `eolfi-modo-agente.patch` y los registros `.eolfi-browser-check.*.log` quedan fuera del commit de la fase.

## Revisión final

Al completar la hoja de ruta, revisar cada entrada y sus dependencias; etiquetar solo entonces las propuestas `PROPONER RETIRAR`, separar lo que requiere conservar y tomar la decisión de limpieza sobre una lista explícita. Hasta ese momento, actualizar este registro si las fases revelan candidatos nuevos o demuestran que una entrada tiene uso.
