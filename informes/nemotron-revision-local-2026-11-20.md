# Nemotron: revisión local de descargas — 20/11/2026

Revisión sin descargar, instalar dependencias, ejecutar código de los modelos ni cambiar el perfil activo. Archivos bajo `D:\Alejandria\corpus\modelos\huggingface\repos\nvidia`.

| Modelo | Archivos observados | Cotejo actual |
|---|---|---|
| NVIDIA-Nemotron-Labs-Dory1.0-4B-BF16 | 9 archivos del catálogo; peso único de 7.950.515.472 bytes | Todos los tamaños y hashes coinciden con el catálogo local del 19/11. El peso coincide también con el SHA-256 publicado **registrado en ese catálogo**. |
| NVIDIA-Nemotron-Nano-9B-v2-Base | 17 archivos del catálogo; cuatro partes de pesos | Todos los tamaños y hashes coinciden con el catálogo. Las cuatro partes declaradas por `model.safetensors.index.json` están presentes y coinciden con los SHA-256 publicados registrados. |
| Nemotron-Terminal-14B | `model-00001-of-00007.safetensors` (4.876.014.992 bytes) y `model-00002-of-00007.safetensors` (3.743.568.816 bytes) | **Incompleto**: solo dos partes visibles de las siete indicadas por sus nombres; no hay índice de pesos en el directorio revisado. No figura entre los dos modelos de `catalogo-nemotron.json`. |

Revisiones fijadas en las rutas: Dory `ee517dd388a9b348890ae1e00dacc5eb4d0c750d`, Nano `dc0661c829b14e5b9246c05cfa89094a0875e052`, Terminal `fa6f29a51305285c6a396049f5bb359ae505ef6c`.

## Identidades recalculadas

| Peso | SHA-256 completo calculado |
|---|---|
| Dory, único | `207483664dfef54c4c4438863260d3ba423bf3d6009b43fe84264b281e9fda23` |
| Nano, 1/4 | `8808ddb60f7bff5dca84e750ab32c80d203584209e575aa95c4ed13d3317f97e` |
| Nano, 2/4 | `69c8eb54788a683e38f9d47fbbf321510376654858e67b218cf2c4aa60da184b` |
| Nano, 3/4 | `0e885f8c5c3632a9fff4427efef4102be87363e7a3082198247aa887a3caa6e8` |
| Nano, 4/4 | `44aba30aa9986d904119cebdeb06eb73fd93cbf15cfe0b80378f2565563f6a2c` |

Se comprobó estabilidad de tamaño, fecha de modificación e identidad de archivo antes/después de cada lectura. Guion y resultados locales: `.pytest-tmp-tableta-historial/revisar_nemotron.py`, `.json` y `nemotron-descargas.log`; termina con `REVISION_TERMINADA`. El cotejo no consultó de nuevo el repositorio remoto y no constituye una certificación independiente del origen.

## Estructura y límites

REA `inspect_model_artifact`, modo `header`, vista `summary`, inspeccionó declaraciones safetensors del peso de Dory y de la primera parte de Terminal y Nano sin interpretar los valores de los tensores. Proveedor de vista `rea-analysis-view` versión 1; plataforma Windows, artefactos locales. Evidencias padre:

- Dory: `ev_98d26203c51546edd9cce9e4f6bd3376c9cefce9129baad0d4317b49c276e7e1`, 507 tensores declarados, cabecera SHA-256 `5215be26239c23e1c8a51502c9269b1b98e1a8d1e5ee27dffdab451bee9f056c`.
- Terminal, 1/7: `ev_fbc07f682e88a451ee884e9d0e961c6855ffbd6293f7342bcfb9159ceaaf423d`, 79 tensores declarados. No acredita el modelo completo ni la segunda parte.
- Nano, 1/4: `ev_db942135c21dfa3301f730eeb1a2246dcee77728be5ce337b2fdfe5dde9d0ac6`, 88 tensores declarados. El resto de las partes se contrastó por hash, no por inspección REA de sus cabeceras en esta revisión.

Modo cabecera: REA no calcula identidad completa de los pesos; los SHA-256 completos anteriores proceden del recorrido de bytes separado. Cobertura declarativa de cabecera/rangos/tamaños completa dentro de cada archivo inspeccionado; valores de tensores, ejecución, compatibilidad con motores y calidad de inferencia: **NO VERIFICADOS**. Copia local: `nemotron-rea-cabeceras.json` en la carpeta de evidencias de esta sesión.

`config.json` de Dory declara `DoryForCausalLM`; Nano declara `NemotronHForCausalLM` y un `auto_map` hacia código Python propio. Estos datos no son prueba de compatibilidad con el motor actual. No se ha ejecutado ese código. Las pruebas de inferencia se harán después de comprobar el soporte del destino elegido; el formato presente es safetensors, no un GGUF listo para activar en el perfil actual.

Se conservan dos restos `.incomplete` de Dory en la caché HF, de 0 y 1.139.717.525 bytes, ya registrados en LIM-068. No son el peso completo que se verificó. No se borró ni movió nada. Una tercera parte parcial de Terminal consta en notas de otra revisión, pero no se localizó en las carpetas de caché comprobadas aquí: no se acredita su ruta ni cantidad descargada con esta inspección.
