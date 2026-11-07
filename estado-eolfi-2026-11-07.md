# Eolfi: estado del plan (07/11/2026)

## Fases del plan (`PLAN_INGENIERIA_INVERSA_EOLFI.md`)

| Fase | Estado | Evidencia |
|---|---|---|
| 0. Rebaselinar | Cerrada | `main` |
| 1. Caso de análisis | Cerrada (5/5) | Integrada en `main`; informe `informes/caso-de-analisis-fase-1-2026-11-06.md` |
| 2. Observación de caja negra | 4/6 | Dos entregas ya publicadas; siguen pendientes las rutas Linux/macOS, la interfaz móvil y la prueba del agente en un VS Code real |
| 3. Especificación | 4/5 | `eolfi/spec/` y CLI; falta modelar protocolos y formatos con estado |
| 4 a 7 | Pendientes | — |

### Fase 2: entregado

- `eolfi/observe/` y CLI `observe run|replay|compare|show|check`; `run` y `replay` requieren autorización explícita.
- Registra entradas y salidas, archivos, procesos hijo, errores y HTTP con secretos ocultos; compara versiones y repite guiones.
- Observación web con navegador real y escritorio Windows con UI Automation.
- API, panel y herramienta de observación del agente.
- Límites pendientes: rutas Linux/macOS sin verificar, sin dispositivo móvil y sin prueba del agente en VS Code real.

### Fase 3: entregado

- `eolfi spec build|show|diff|review|tests --case`: requisitos con evidencia y confianza, contradicciones como incógnitas, hipótesis separadas, versiones revisables y pruebas generadas de lo observado.
- Falta: máquinas de estado para protocolos y formatos.
- Límites: fuentes estáticas resumidas por identidad del artefacto; máquinas de estado solo para flujos de interfaz; la aceptación de una implementación basada en la especificación aún no está demostrada.

### Flujo de creación de proyectos

- Formulario único para nombre, descripción, archivos, webs y repositorios; permite elegir modo automático o guiado.
- El plan muestra lo entendido, instrucciones pendientes, pasos, riesgos y verificación; nada se ejecuta hasta que se aprueba.
- Los cambios posteriores que alteran el plan requieren aprobación; cada paso y decisión queda en el caso.
- La generación usa plantillas propias y la verificación obligatoria; resultados que no la superan se presentan como `NO VERIFICADO`.

### Correcciones y validación

- Python 3.10: f-string compatible y lector TOML de respaldo.
- Descargas lentas: el vencimiento del plazo total se informa igual cuando el socket acaba la lectura como fin de datos.
- Repetición de UIA: normaliza identificadores variables de ventanas y controles.
- API del panel: publica el módulo de creación de proyectos; ejecución guiada y contraste del botón corregidos.
- Resultados: Python 387 pasadas y 2 omitidas; puente principal 50 pasadas y 1 omitida; extensión 128 pasadas; E2E en navegador 16 pasadas.
- Intérprete Python usado: `C:\Users\mejil\AppData\Local\Programs\Python\Python312\python.exe`.

## Entrega

Los cambios quedan en commits locales con autoría de Luis. El push queda a cargo de Luis.
