# Análisis y prueba Mistral en RTX 3060 Ti

## Archivo y origen

- Hugging Face: https://huggingface.co/bartowski/Mistral-7B-Instruct-v0.3-GGUF/blob/main/Mistral-7B-Instruct-v0.3-Q4_K_M.gguf
- Ruta local: D:\AI\Hydra\gguf\Mistral-7B-Instruct-v0.3-Q4_K_M.gguf
- Tamaño observado y remoto: 4,372,812,000 bytes.
- SHA-256 calculado por REA: 1270d22c0fbb3d092fb725d4d96c457b7b687a5f5a715abe1e818da303e562b6
- El SHA-256 coincide con el publicado en la página de Hugging Face.

## Análisis REA

REA model header reader v1 (GGUF v3) observó arquitectura llama, nombre Mistral-7B-Instruct-v0.3, contexto declarado 32,768, 7,248,023,552 parámetros derivados, 291 tensores y 29 entradas de metadatos. Tipos declarados: 193 Q4_K, 65 F32 y 33 Q6_K. Los pesos no se interpretaron ni modificaron.

Evidencia exportada en rea-evidence-mistral.json; incluye la inspección completa y la vista de los 291 tensores. El recuento de parámetros calculado desde las formas del CSV es 7248023552 y coincide con el total derivado por REA.

## Prueba de arranque

Runtime: backend CUDA 12 de LM Studio, llama.cpp 0.6.0-dev build 1, commit 3109914. Se ejecutó run-gemma4-3060ti.ps1 con este modelo, 8 capas GPU, contexto 32,000 y batch 128/64.

Resultado: modelo cargado; n_ctx_slot=32000; listener en 127.0.0.1:8080; GET /health devolvió {"status":"ok"}. nvidia-smi durante la prueba informó 3,144 MiB usados y 4,881 MiB libres en la RTX 3060 Ti. Es una lectura global de GPU, no una medición atribuida al proceso. El comando pasó --n-gpu-layers 8; el log no enumeró el número efectivo de capas offloaded por separado.

El servidor se detuvo al terminar y el puerto 8080 quedó cerrado. No se enviaron prompts: la generación, calidad de respuestas y fin de turno no se probaron. El runtime no emitió advertencias de tokenizer durante esta carga.

## Caché temporal

El primer hf download quedó atascado antes de transferir bytes y se detuvo. Se conservaron sus archivos .lock/.incomplete en D:\AI\Hydra\gguf\.cache\huggingface\download; no se usan para el GGUF final, que se descargó con curl y se verificó por tamaño y SHA-256.

## Análisis REA ampliado de estructura y tokenizador

La evidencia completa marca GGUF v3, little-endian, alineación 32 y datos de tensores desde el offset 757,984. La inspección cubrió el encabezado completo (29 campos de metadatos, 291 tensores); los bytes del payload se leyeron para el SHA-256, pero no se interpretaron como valores numéricos.

Metadatos arquitectónicos declarados: 32 bloques, embedding 4,096, feed-forward 14,336, 32 cabezas de atención y 8 KV heads. La longitud máxima declarada es 32,768; vocabulario 32,768. El tokenizer declara BOS=1, EOS=2, añadir BOS=true y añadir EOS=false. Está incrustada una plantilla de chat que emplea los delimitadores Mistral [INST]/[/INST]. Los arrays de tokens, scores y tipos tienen 32,768 elementos cada uno; REA solo retiene una vista previa de hasta ocho elementos de cada array.

El inventario contiene 291 entradas: 193 Q4_K, 33 Q6_K y 65 F32. La suma de productos de formas tensoriales es 7,248,023,552 parámetros y coincide con el total derivado por REA. Las longitudes de almacenamiento de los 226 tensores K quedaron desconocidas porque la codificación K admite perfiles de bloque ambiguos bajo la misma versión GGUF; no se afirma que el payload esté validado tensor por tensor.

## Conclusión de la auditoría

La estructura declarada es coherente en los recuentos revisados y el archivo coincide por tamaño y SHA-256 con el objeto de Hugging Face. No hay evidencia en esta revisión para corregir el GGUF. El hash prueba identidad de bytes, no calidad de pesos; la inspección no demuestra exactitud numérica, calidad de respuestas ni equivalencia con el checkpoint original. La carga de runtime y health check están verificados por separado en la sección anterior; la generación permanece NO VERIFICADA.

Cobertura: operación inspect_model_artifact, proveedor REA model header reader v1; proyecciones rea-analysis-view v1. Bundle portátil: rea-evidence-mistral.json.
