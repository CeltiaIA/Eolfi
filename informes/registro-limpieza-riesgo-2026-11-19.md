# Registro de limpieza agrupado por riesgo — 19/11/2026

Fuente: REGISTRO_LIMPIEZA.md y comprobaciones de solo lectura de Git. No se borró ni movió nada.

## Riesgo alto — conservar

| Candidatos | Motivo |
|---|---|
| LIM-003 backups | Mecanismos de recuperación ignorados por Git. Falta inventariar su relación con el árbol actual. |
| LIM-013 base eolfi.db antigua | Puede contener credenciales de clientes. La migración conserva deliberadamente la base antigua. |
| LIM-040 rsi-eval | Incluye una copia de clave y evidencias del banco. Revisar primero, sin publicar su contenido. |
| LIM-023, LIM-038–LIM-046 worktrees con cambios | Varias ramas no tienen commits o conservan archivos sin seguimiento, enlaces de node_modules y evidencias de otras sesiones. |
| LIM-029 Java, LIM-043 Whisper y muestras REA | Herramientas y datos que siguen respaldando flujos del plan. |

## Riesgo medio — retirar solo con dependencias resueltas

| Candidatos | Condición previa |
|---|---|
| LIM-030 HYDRA-BASE/llama y LIM-027 configuración antigua | Confirmar que ningún consumidor externo usa la copia y reapuntar o retirar la configuración en la misma operación. |
| LIM-031, LIM-032 y worktrees de LIM-045/LIM-046 | Confirmar rama fusionada, árbol limpio y ausencia de sesiones. Quitar primero las uniones sin tocar su destino. |
| LIM-033, LIM-036, LIM-039, LIM-044 evidencias y scratchpads | Conservar hasta que el resultado asociado esté documentado y sus ramas estén integradas. |
| LIM-047 ejecutable 0.8.0 | Es un artefacto verificado. Retirar solo al sustituirlo por una construcción posterior igualmente verificada. |
| LIM-048 proveedor llama.cpp antiguo | Mantener hasta demostrar que ningún caller público, configuración anterior o guía lo usa. |

## Riesgo bajo — candidatos concretos, conservados

| Candidato | Evidencia y comprobación pendiente |
|---|---|
| LIM-049 eolfi/eolas_v2.py.pre-alejandria-20261118 | Su objeto Git coincide con HEAD, 14aa75f8…. Falta decidir si la copia previa conserva intención de otra sesión. |
| LIM-050 debug.log | Registro local del navegador, sin seguimiento. Falta identificar la prueba que lo genera y decidir si sirve para investigar los fallos de GPU/DNS. |
| LIM-013A Alejandría .codex-tmp | Son temporales de pytest. Debe retirarlos el flujo de organización del corpus después de probar sus exclusiones. |
| LIM-022 ID duplicado | Resuelto: la entrada de Alejandría es `LIM-013A`; `LIM-013` sigue identificando la base antigua. |

## Decisiones necesarias

1. Conservar o retirar la copia de clave y evidencias de LIM-040.
2. Confirmar si la copia previa LIM-049 pertenece a un cambio abandonado.
3. Elegir qué worktrees limpios se retiran una vez comprobados de nuevo.
4. Decidir si se conserva el ejecutable 0.8.0 como evidencia de distribución.
5. Autorizar una lista exacta de candidatos antes de cualquier retirada.

## Avance seguro del 19/11

- `LIM-022` queda resuelto: la copia temporal de Alejandría es `LIM-013A` y `LIM-013` conserva el significado
  histórico de la base antigua.
- `LIM-050` se conserva localmente y `/debug.log` queda ignorado por Git. El contenido observado son diagnósticos
  de Chromium sobre DNS y Vulkan; no se atribuye a una prueba concreta sin evidencia.
- `LIM-026` queda resuelto: las descripciones de VS Code enumeran Eolas local, Meta AI Web y DeepSeek Web, que son
  los motores presentes en el código, y dejan de atribuir respuestas a Copilot.
- No se borró ni movió ningún archivo y no se inspeccionó el contenido sensible de `LIM-040`.
