# Auditoría de los modelos locales: puertas traseras y envío de datos (16/11/2026)

Pedida por el titular: comprobar que los modelos no tienen puertas traseras ni envían datos a terceros.

## Resultado

**No se ha encontrado ninguna puerta trasera ni ninguna conexión hacia fuera.** No había nada que anular.

Un archivo de modelo GGUF son pesos y metadatos: no contiene código que se ejecute y no puede abrir conexiones por
sí mismo. Quien puede conectarse es el programa que lo carga, así que se han revisado las dos cosas.

## Qué se comprobó y cómo

### 1. Los archivos de modelo (`eolfi modelos auditar`)

| Archivo | SHA-256 | Tensores | Bytes sobrantes | Cadenas sospechosas |
|---|---|---|---|---|
| Gemma 4 12B Q4_K_M (V1 `latest` y V2) | `43fec98c…03d6` | 667 | 0 | ninguna |
| Gemma 4 12B Q5_K_M (V1 `q5_k_m` y V2) | `32c554c7…16cd` | 667 | 0 | ninguna |
| Mistral 7B Instruct v0.3 Q4_K_M (V1) | `1270d22c…62b6` | 291 | 0 | ninguna |
| Mistral Small 3.2 24B Q5_K_M (V2) | `c3313e3e…201f` | — | 0 | ninguna |

- **Estructura:** cabecera GGUF v3 válida; el archivo termina exactamente donde acaba el último tensor (0 bytes
  sobrantes), así que no hay nada pegado detrás.
- **Metadatos:** todas las claves son las normales (`general.*`, `tokenizer.*`, las de la arquitectura); ninguna
  fuera de norma.
- **Plantilla de chat** (lo único «programable» de un GGUF, una plantilla Jinja): sin URL ni órdenes. Las únicas URL
  del archivo son las de procedencia y licencia (Google, Hugging Face `unsloth`).
- **Identidad:** en el almacén de V1 el nombre de cada archivo es su SHA-256 y coincide con el contenido. Los
  archivos de V2 (`D:\AI\Hydra\gguf`) son idénticos byte a byte a los de V1.
- Las palabras `curl`, `socket`, `subprocess`… que aparecen en el vocabulario son tokens del idioma, no órdenes.

### 2. Los motores, en vivo

Con Eolas V2 generando (prueba A/A del RSI): `llama-server.exe` solo **escucha en 127.0.0.1:8090** y su única
conexión es local (el propio Eolfi). Ninguna conexión hacia fuera, ningún puerto UDP. Sus argumentos no incluyen
descargas (`-hf`, `--model-url`) y exigen clave.

### 3. Los motores, en el código

- **Eolas V1** (código propio, Go): las únicas conexiones salientes posibles son las de **descargar un modelo**
  (`eolas pull`, `/api/pull`) desde `registry.ollama.ai` o `hf.co`, y solo cuando se pide. No hay telemetría.
- **llama.cpp b11968**: los 57 archivos coinciden con la distribución oficial (LIM-030, `sha256sum`). Puede
  descargar modelos si se le pasa `-hf`; Eolfi y Eolas no lo hacen.
- **Voz** (nuevo): el audio va solo al servidor local; la lectura usa solo voces locales.

## Límites (NO VERIFICADO)

- Una puerta trasera **en los pesos** (que el modelo responda de forma dañina ante una frase concreta) no se puede
  descartar inspeccionando el archivo: nadie puede hoy. Lo que protege es que el modelo no ejecuta nada por sí
  mismo: toda acción pasa por las herramientas de Eolfi, con permisos y registro.
- La comprobación en vivo es una muestra (un motor, unos minutos), no una vigilancia continua.
- El SHA-256 de los GGUF no se ha comparado con el que publica el origen (exigiría conexión). El de Mistral Small
  trae su `.sha256` al lado.
- El motor nativo `eolas` (en proceso) no se observó en vivo en esta auditoría.

## Refuerzos propuestos (bloque G de `PLAN_DEFINITIVO.md`)

1. **Regla de cortafuegos** que bloquee la salida de `llama-server.exe` y `eolas.exe`. Cambia la seguridad del
   sistema y pide administrador: **lo decide y lo ejecuta el titular**.
2. **Modo sin red en Eolas** (`EOLAS_OFFLINE=1`): `pull` desactivado salvo que se pida expresamente.
3. **Lista de modelos de confianza** con su SHA-256: Eolas y Eolfi se niegan a cargar un archivo que no esté.
   **Hecho para Eolas V2**; falta Eolas V1 (está en el repositorio de CeltiaIA).
4. `eolfi modelos auditar`: esta misma auditoría como orden, repetible y con informe. **Hecho** (`eolfi/modelos.py`),
   junto con la lista de confianza (`eolfi modelos confiar`, `exigir`) y `eolfi modelos conexiones`.
