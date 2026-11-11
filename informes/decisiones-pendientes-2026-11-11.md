# Decisiones pendientes del titular — 2026-11-11

> Lista para revisar de una vez. Cada punto dice qué hay que decidir, las opciones, la recomendación y qué pasa
> si no se decide. **Nada de esto se ha cambiado**: todo sigue como está hasta que el titular elija. Contestar con
> el número y la letra (p. ej. «1A, 4B, 8A…») basta.

Contexto: rama `objetivos-rea-2026-11-09` (PR #1, https://github.com/CeltiaIA/Eolfi/pull/1) con O1–O8, O10, O12 y
parte de O13; rama `avance-fases-2-3` con Eolas v2, las herramientas del puente de VS Code y los informes del 09/11.

## A. Integración en Git

**1. Fusionar la PR #1**
- A) Fusionar cuando `python -m pytest -q` pase en Windows y la CI esté en verde. *(Recomendado)*
- B) Esperar a terminar O13 (guías del puente y del agente VS Code).
- Si no se decide: la rama sigue creciendo y alejándose de `avance-fases-2-3`.
- Nota: las suites de O7 y O13 solo se han ejecutado en Linux.

**2. Orden de integración de las dos ramas**
- A) Primero la PR #1 en la rama principal y después `avance-fases-2-3` encima, resolviendo conflictos. *(Recomendado:
  la PR #1 es más pequeña y ya está revisada.)*
- B) Al revés.
- Nota: la corrección de Meta (líneas ocultas) está en las dos ramas con el mismo contenido (`7cdaaa5` y `2079533`);
  Git debería resolverla sin conflicto.

**3. Archivos de supervisión en `D:\Eolfi-objetivos`** (`OBJETIVOS_EOLFI.md`, `PROMPT_*`, `prompts-o5/`, `prompts-o10/`,
`prompts-o14/`), sin confirmar
- A) Moverlos a una carpeta fuera del repositorio (p. ej. `D:\Eolfi-supervision\2026-11`). *(Recomendado: se conservan
  y dejan de ensuciar `git status`.)*
- B) Añadirlos a `.gitignore`.
- C) Borrarlos.

## B. Seguridad y datos locales

**4. `eolfi.db` en la raíz del repositorio** (LIM-013; contiene `client_tokens`)
- A) Moverla a `~/.eolfi/eolfi.db` como ruta por defecto, con migración automática que copia la base antigua sin
  borrarla. *(Recomendado: deja de estar junto al código y de poder acabar en una copia o un zip del repo.)*
- B) Dejarla donde está (ya la ignora Git).
- Si no se decide: sigue igual; el riesgo es copiarla sin querer junto con el proyecto.

**5. Fusibles de Electron** (O6; motor Electron del puente)
- A) No empaquetar: seguir con tu navegador como motor por defecto y el aviso al arrancar con Electron. *(Recomendado
  mientras el motor Electron sea solo la reserva.)*
- B) Instalar `@electron/fuses` y empaquetar con `EnableCookieEncryption` activado y `RunAsNode`, `NODE_OPTIONS` e
  `--inspect` desactivados. Requiere autorizar la dependencia nueva.

**6. `-ExecutionPolicy Bypass` en el lanzador de Eolas** (O5)
- A) Mantenerlo, recomendando configurar `eolfi.fallback.eolasLauncherSha256` para que solo se ejecute el script con
  el hash esperado. *(Recomendado.)*
- B) Quitarlo: el script solo arrancaría si la política de PowerShell lo permite o si está firmado.

**7. Inicio de sesión de ChatGPT y Le Chat con la política de navegación nueva** (O2)
- DeepSeek, Gemini y Meta AI se probaron en vivo el 09/11. ChatGPT y Le Chat no.
- A) Probarlos en vivo con tus cuentas cuando te venga bien (unos minutos con `eolfi bridge --login`). *(Recomendado.)*
- B) Dejarlo como NO VERIFICADO.

## C. Comportamiento del producto

**8. `create` añade las secciones `Hero` y `Features` aunque la fuente no las tenga**
(`eolfi/generador/spec.py`)
- A) Mantenerlas y anotar en `eolfi.spec.json` cuáles se añadieron por defecto (p. ej. `"sections_added": ["Hero",
  "Features"]`). *(Recomendado: la salida no cambia y la trazabilidad mejora.)*
- B) No añadirlas: solo las secciones observadas.
- C) Dejarlo como está (la guía ya lo advierte).

**9. Opción `create --verify`**
- Hoy no hace nada: la verificación es siempre obligatoria y la ayuda dice «conservada por compatibilidad».
- A) Retirarla en la próxima versión, avisando un tiempo antes si se usa. *(Recomendado.)*
- B) Mantenerla.

**10. `equivalent_on_observed` no tiene en cuenta los casos pendientes**
- Hoy exige 0 diferencias y 0 parciales; los pendientes se cuentan aparte y la orden termina con código 4.
- A) Mantenerlo y añadir un campo nuevo, `complete`, que solo sea verdadero sin pendientes. *(Recomendado: no rompe a
  quien lea el campo actual.)*
- B) Cambiar `equivalent_on_observed` para que exija también 0 pendientes.
- C) Dejarlo como está (ya documentado en la guía de la API).

## D. Registro de limpieza (para la revisión final; nada se borra ahora)

| N.º | Entrada | Recomendación |
|---|---|---|
| 11 | LIM-001: `.eolfi-browser-check.*.log` | Proponer retirar: la evidencia ya está en los informes. |
| 12 | LIM-002: `eolfi-modo-agente.patch` | Conservar fuera del repo hasta comparar cada cambio con el historial. |
| 13 | LIM-004: `generated/nuevo-proyecto/` | Decidir si se guarda como ejemplo o se borra. |
| 14 | LIM-006: `samples/index.json` con referencias a muestras que faltan; APK sin procedencia | Quitar del índice lo que no existe y documentar la procedencia del APK o retirarlo. |
| 15 | LIM-011: `import base64` duplicado en la plantilla de la CLI reconstruida | Retirar: no tiene efecto y la plantilla está cubierta por pruebas. |
| 16 | LIM-008: compatibilidad con casos v1 | Conservar hasta confirmar que no has compartido paquetes v1. |

## E. Bloqueados por recursos

**17. O9 (interfaz móvil)**: no hay dispositivo, emulador ni `adb`.
- A) Declararla `not_available` en la cobertura, igual que se hizo con el escritorio fuera de Windows en O8.
  *(Recomendado.)*
- B) Dejarla bloqueada hasta tener un emulador.

**18. O11 (seguimiento REA)**: necesita una sesión con el servidor MCP `rea`.
- A) Hacerlo en la próxima sesión que lo tenga, repitiendo R1 y R3 sobre el puente tras O1, O2, O4 y O6.
  *(Recomendado.)*
- B) Darlo por cerrado con lo que hay.

**19. O13 (guías del puente y del agente VS Code y laboratorio en un VS Code real)**: necesitan tus sesiones o un
VS Code real.
- A) Escribir ya las guías con la parte que se puede probar en la CI (simulada) y dejar el laboratorio para cuando
  estés delante. *(Recomendado.)*
- B) Esperar y hacerlo todo en vivo.

## Lo que no necesita decisión

- Aviso de Pillow por `getdata` (obsoleto) en `tests/test_observe.py`: es una corrección pequeña y se puede hacer sin
  más.
