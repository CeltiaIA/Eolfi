
# Análisis y prueba Qwen en RTX 3060 Ti

## Perfil probado

llama.cpp de LM Studio, build 0.6.0-dev (commit 3109914), carpeta CUDA 12 2.53.0. Para ambos GGUF se ejecutó el lanzador con 8 capas GPU, contexto 32,000, batch 128/64, host loopback y puerto 8080. No se enviaron prompts.

## Qwen3-4B-Instruct-2507 Q4_K_M

- Archivo: D:\AI\image-models\z-image-turbo\Qwen3-4B-Instruct-2507-Q4_K_M.gguf
- Tamaño: 2,497,281,120 bytes; SHA-256: 3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597
- REA: arquitectura qwen3; 4,022,468,096 parámetros derivados; 398 tensores, 42 metadatos.
- Resultado: cargó y /health respondió status=ok con n_ctx_slot=32000. En la primera consulta el health devolvió 503 Loading model; después pasó a OK.
- VRAM en lectura de health: 5,572 MiB usados, 2,453 MiB libres; GPU 1%.
- Aviso de runtime: el token id 128247 (</s>) parecía especial pero no estaba tipado como control; el runtime lo anuló/reclasificó. No se corrigió sin referencia canónica.

## Qwen3.5-4B Q4_K_M

- Archivo: D:\HYDRA-BASE\.hydra\gguf\qwen3.5-4b\qwen3.5-4b-Q4_K_M.gguf
- Tamaño: 2,648,593,216 bytes; SHA-256: a9d0a3e1d8c91732a3812becd31f8d4a8ff57414903f226306069f0437e2ac50
- REA: arquitectura qwen35; 4,205,751,296 parámetros derivados; 426 tensores, 41 metadatos. El campo general.name declara literalmente “Source” aunque el tamaño declarado es 4.2B; se conserva como discrepancia de metadatos, no se editó.
- Resultado: cargó y /health respondió status=ok con n_ctx_slot=32000.
- VRAM en lectura de health: 5,225 MiB usados, 2,800 MiB libres; GPU 1%.
- Sin advertencias de token en el log observado.

Ambos servidores se detuvieron al acabar; no quedó listener en 8080. El recuento de parámetros, los pesos y la calidad de generación no se validaron mediante inferencia. Las lecturas de VRAM son globales del dispositivo, no una medición atribuida por proceso.

## Mistral y Qwen de tamaño comparable encontrados en Hugging Face

El inventario de GGUF de D:\AI no contenía Mistral. La búsqueda recursiva más amplia de D:\ se interrumpió por duración, así que la ausencia fuera de D:\AI queda NO VERIFICADA. Candidato adecuado para la RTX 3060 Ti: Bartowski Mistral-7B-Instruct-v0.3 Q4_K_M, 4.37 GB. Ficha: https://huggingface.co/bartowski/Mistral-7B-Instruct-v0.3-GGUF

Para comparar tamaño con Gemma 4 12B, la familia Qwen3-14B es la más cercana entre los Qwen buscados. El GGUF oficial Q4_K_M ocupa 9 GB, por encima de los 8 GiB de VRAM; se podría probar con descarga a CPU y 8 capas GPU, pero requiere RAM de sistema suficiente. Alternativa de menor tamaño: Q3_K_M, 7.32 GB, con más pérdida de calidad. Fichas: https://huggingface.co/Qwen/Qwen3-14B-GGUF y https://huggingface.co/tensorblock/Qwen_Qwen3-14B-GGUF

No se descargó ningún modelo de Hugging Face. Sin los archivos locales, Mistral y Qwen3-14B quedan NO VERIFICADOS en este equipo.
