# Auditoría REA de Gemma 4 y Mistral para Eolas V2

Fecha: 2026-11-09  
Autoridad: inspección estática de los artefactos locales (`shipped-artifact`).  
Proveedor: REA `model-artifact`, `REA model header reader` v1.  
Cobertura: cabeceras GGUF completas y SHA-256 calculado leyendo cada archivo completo; no se cargaron ni ejecutaron los modelos.

## Hallazgos

| Modelo | Tamaño | SHA-256 | Arquitectura declarada | Contexto | Tensores | Parámetros derivados |
|---|---:|---|---|---:|---:|---:|
| Gemma-4-12B-It Q5_K_M | 8,413,576,000 bytes | `32c554c7d1338a23837ae39b3db482213a4a642f96df3b2619f516a2375d16cd` | `gemma4` | 262,144 | 667 | 11,907,350,576 |
| Mistral-7B-Instruct-v0.3 Q4_K_M | 4,372,812,000 bytes | `1270d22c0fbb3d092fb725d4d96c457b7b687a5f5a715abe1e818da303e562b6` | `llama` | 32,768 | 291 | 7,248,023,552 |

Ambos declaran GGUF v3, little-endian y plantilla de chat. Los totales de parámetros son derivados de las formas declaradas por el formato; no son una lectura ni validación numérica de los pesos.

## Lo que puede y no puede extraerse

Los GGUF no incluyen el corpus original, ejemplos, etiquetas ni receta completa de entrenamiento. REA confirmó que los valores numéricos de tensores no se interpretaron. Por tanto, no es posible extraer de estos archivos “los datos de entrenamiento” ni reconstruir fielmente lo aprendido como dataset. La inferencia es una fuente posible de ejemplos sintéticos, pero requeriría prompts, generación, revisión humana y medición de calidad; esos ejemplos serían nuevos, no datos originales recuperados.

No se deben promediar ni concatenar directamente estos pesos para fabricar un modelo único: declaran arquitecturas distintas (`gemma4` y `llama`) y cuantizaciones distintas (Q5_K_M y Q4_K_M). La compatibilidad posicional de cada tensor y del grafo no está establecida. La vía viable es destilación: ejecutar uno cada vez como profesor, recopilar respuestas a un corpus curado, validarlas, y ajustar un adaptador en un checkpoint Transformers compatible. Ese adaptador queda aparte; los GGUF originales se preservan.

## Limitaciones de la inspección

- REA no cargó el modelo, no verificó generación ni calidad de inferencia.
- El SHA-256 completo identifica cada archivo inspeccionado.
- Los tamaños de almacenamiento de varios tensores K permanecen desconocidos por ambigüedad entre diseños de bloques de GGUF. Los rangos son parciales y REA no validó la distribución interna de los pesos.
- Los pesos GGUF no se inspeccionaron numéricamente ni se modificaron.

## Composición de CeltIA V2 y ajuste posterior

Se implementó en Eolfi una partitura secuencial para el proveedor `celtia-v2`: **Mistral redacta** una respuesta estructurada y **Gemma actúa como revisor senior**, corrige y entrega la respuesta final. Eolas V2 termina el proceso de Mistral antes de cargar Gemma; si falla cualquiera de las fases, no publica el borrador como resultado final. El proveedor se integró con `assist`, `create` y el selector del panel. Es composición de inferencias con una GPU compartida, no una mezcla de pesos.

La prueba de humo real completó ambas fases en la RTX 3060 Ti, con contexto 32,000, `max_tokens=512` y razonamiento desactivado solo en la configuración en memoria de la prueba. Resultado: `generation_ok`; Mistral→Gemma devolvió JSON válido, resumen «Una respuesta fue redactada por Mistral y revisada por Gemma», y 267 tokens de entrada/131 de salida acumulados. El servidor Eolas V2 se detuvo correctamente después (`stopped: true`). Se restauró el supervisor CeltIA previo: `/api/tags` volvió a anunciar `gemma-4-12b-it:latest` en 11435 y el panel de 5176 respondió HTTP 200. Esto verifica el paso de composición básico; no prueba calidad de una tarea extensa ni seguridad/corrección del código producido.

## Estado del camino de ajuste

Eolas V2 ya tiene un comando explícito `train-sft` que escribe un adaptador QLoRA PEFT separado desde checkpoint y dataset SFT locales; rechaza GGUF como checkpoint de entrenamiento, datasets pequeños/preferencias (DPO aún no implementado), directorios de salida existentes y arranque sin `--consent`. El código requiere CUDA y comprueba 5 GiB libres antes de cargar. Estos guardarraíles no prueban que el entrenamiento Gemma 12B quepa en la RTX 3060 Ti de 8 GiB ni que el adaptador mejore el modelo.

Para ejecutar entrenamiento real aún hacen falta: (1) checkpoint Transformers de la arquitectura elegida, (2) dataset SFT curado con train/validation/test y consentimiento, (3) dependencias QLoRA ya disponibles, (4) medición real de VRAM, y (5) evaluación antes/después. Ninguno de esos cinco puntos se atribuye a los GGUF inspeccionados. El ajuste permanece **NO VERIFICADO** y no se inició cómputo de entrenamiento.

## Evidencia

El bundle REA completo de esta sesión se exportó a [`rea-eolas-v2-model-audit-2026-11-09.json`](rea-eolas-v2-model-audit-2026-11-09.json): 23 registros, 0 unknowns registrados en el bundle; contiene también evidencia previa de Qwen/Mistral. Los Evidence de las inspecciones actuales son `ev_ec23aca6d8738279cf70b425f974275dbd9ed148e9c93e75c0fa79557d07e1d5` (Gemma) y `ev_a2c5ecc08c1f2dc75d8c936512b07f2f67ff60df507a84d334b97fa9f1b94201` (Mistral). La ausencia de unknowns de ledger no significa que los valores de pesos o su comportamiento se hayan verificado; siguen expresamente fuera de cobertura.
