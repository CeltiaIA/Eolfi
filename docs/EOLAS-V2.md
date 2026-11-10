# Eolas V2 / CeltIA V2 Composite: motor local

Eolas administra un único `llama-server` en `127.0.0.1:8090` y permite alternar Gemma 4 12B Q5_K_M y Mistral 7B Instruct v0.3 Q4_K_M. El perfil inicial es Gemma. Ambos usan como valores iniciales 8 capas GPU, contexto 32,000 y lotes 128/64 para la RTX 3060 Ti de 8 GiB. Cambiar perfil detiene el proceso que Eolas inició y espera a que desaparezcan su PID y endpoint `/health` antes de cargar el siguiente.

## Comandos

```powershell
python -m eolfi eolas-v2 status
python -m eolfi eolas-v2 start
python -m eolfi eolas-v2 switch mistral
python -m eolfi eolas-v2 switch gemma
python -m eolfi eolas-v2 stop
```

La configuración queda en `%USERPROFILE%\.eolfi\eolas-v2.json`; puede cambiarse con `EOLFI_EOLAS_V2_CONFIG`. Las rutas de cada GGUF se pueden sobreescribir con `EOLFI_EOLAS_V2_GEMMA_GGUF` y `EOLFI_EOLAS_V2_MISTRAL_GGUF`. Estas variables no deben contener secretos.

El proveedor `eolas-v2` se puede usar en `eolfi create --ai` y `eolfi assist`; si el motor tiene un perfil activo, ese es el usado. La extensión de VS Code sigue usando el servicio CeltIA/Eolas V1 existente en `127.0.0.1:11435`, por compatibilidad; la nueva alternancia se controla mediante `eolfi eolas-v2` y el proveedor del generador.

## CeltIA V2 Composite

El proveedor `celtia-v2` compone los dos perfiles como una secuencia de trabajo, sin fusionar sus tensores: **Mistral redacta** una primera respuesta estructurada; Eolfi termina ese proceso, **Gemma revisa y compone** la salida final bajo la solicitud y el esquema originales. El runtime de Eolas V2 detiene un perfil antes de cargar el siguiente, así nunca quedan ambos modelos cargados a la vez. Si cualquiera de las fases falla, la operación falla cerrada y no devuelve como final el borrador sin revisar.

Se puede seleccionar con `eolfi assist --provider celtia-v2` o `eolfi create --ai --provider celtia-v2`; también aparece en el panel web. `eolas-v2` conserva el modo de perfil único para latencia menor. La composición duplica inferencia y arranque del servidor; puede tardar más. La secuencia real con los dos GGUF pasó una petición JSON corta en la RTX 3060 Ti; para ese smoke test se usaron 512 tokens máximos y razonamiento desactivado solo en memoria. La calidad en cambios de código extensos y la estabilidad bajo carga prolongada siguen `NO VERIFICADO` y necesitan evaluaciones con proyectos controlados.

## Feedback y selección

El almacenamiento está apagado por defecto. Para activarlo y guardar una valoración:

```powershell
python -m eolfi eolas-v2 feedback-consent on
python -m eolfi eolas-v2 feedback-add --profile gemma --task codigo --rating 5 --prompt-file pregunta.txt --response-file respuesta.txt --consent
python -m eolfi eolas-v2 calibrate codigo
python -m eolfi eolas-v2 feedback-export eolas-feedback.jsonl
python -m eolfi eolas-v2 feedback-import eolas-feedback.jsonl
python -m eolfi eolas-v2 dataset sft --out .eolas-v2\sft.jsonl --min-examples 20
python -m eolfi eolas-v2 dataset preference --out .eolas-v2\preferences.jsonl --min-examples 20
```

Las preferencias necesitan respuestas humanas al mismo prompt con rating ≥4 y ≤2. Los prompts y respuestas se conservan solo con consentimiento, se redaccionan valores que parezcan secretos y se guardan en `%USERPROFILE%\.eolfi\eolas-v2\feedback.jsonl`. `feedback-delete` permite borrar un registro por id. La calibración disponible recomienda perfil por dominio; aún no modifica pesos.

## Entrenamiento de adaptadores

`python -m eolfi eolas-v2 training-check --checkpoint RUTA --dataset ARCHIVO` verifica el checkpoint HF local, el hash/manifest de dataset SFT y las dependencias `torch`, `transformers`, `peft` y `bitsandbytes`. No instala ni descarga nada. Para iniciar el ajuste explícitamente: `python -m eolfi eolas-v2 train-sft --checkpoint RUTA --dataset sft.jsonl --out adaptadores\experimento-01 --consent`. El comando usa QLoRA 4-bit NF4 y crea un adaptador LoRA PEFT separado; exige CUDA y al menos 5 GiB VRAM libre, batch 1, acumulación 4 y longitud máxima predeterminada 1024. El directorio de salida debe ser nuevo. No modifica el checkpoint fuente ni calibra directamente un GGUF; hace falta el checkpoint Transformers original, porque los GGUF Q4/Q5 locales no son una fuente compatible para este flujo estándar. Solo se entrena SFT: preferencias/DPO se rechazan explícitamente. Cada artefacto se marca como experimento y requiere evaluación independiente antes de uso. En la RTX 3060 Ti de 8 GiB, que este método funcione con Gemma 12B/Mistral debe probarse en el entorno real; `training-check` no reserva VRAM ni demuestra que el entrenamiento quepa.

## Compatibilidad existente

El proveedor `eolas` actual sigue apuntando al servicio CeltIA en `127.0.0.1:11435`; `gemma` conserva su alias existente. `eolas-v2` es el nuevo proveedor OpenAI-compatible local y no debe coexistir en la GPU con el otro motor.
