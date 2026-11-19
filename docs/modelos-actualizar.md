# Actualizar modelos (G5)

Dos órdenes separadas. Ninguna adopta el modelo: el banco y la adopción (G6: `eolas-v2 plan` y `adoptar`)
siguen siendo pasos aparte.

## 1. Comprobar si hay versión nueva

Archivo de fuentes (`eolfi.modelos.fuentes/v1`), uno por equipo:

```json
{
  "schema": "eolfi.modelos.fuentes/v1",
  "modelos": [
    {"nombre": "gemma4-12b-q4", "repo": "propietario/repositorio-GGUF", "archivo": "modelo-Q4_K_M.gguf",
     "sha256": "SHA256_DEL_ARCHIVO_LOCAL", "local": "D:\\AI\\Hydra\\gguf\\modelo-Q4_K_M.gguf"}
  ]
}
```

```powershell
python -m eolfi modelos actualizar --fuentes fuentes.json --red
```

- Sin `--red` no abre ninguna conexión; con `EOLAS_OFFLINE=1` se niega siempre.
- Consulta solo la API pública de Hugging Face (`/api/models/<repo>/revision/<rama>?blobs=true`) y compara el
  SHA-256 LFS publicado con el local. Si falta `sha256`, lo calcula del archivo `local` (lee el archivo entero).
- Estados: `al_dia` (código 0), `nueva_version` y `NO VERIFICADO` (código 2). En `nueva_version` el resultado
  trae el bloque `descarga` (repo, archivo, commit, SHA-256 y tamaño) que hay que revisar antes de descargar.
- No envía credenciales: un repositorio privado o con licencia aceptada por cuenta queda NO VERIFICADO.

## 2. Descargar con permiso

```powershell
python -m eolfi modelos descargar --repo propietario/repositorio-GGUF --archivo modelo-Q4_K_M.gguf `
  --revision COMMIT_DE_40_HEX --sha256 SHA256_PUBLICADO --bytes TAMAÑO --out D:\Eolfi\generated\modelos\nuevo --red
```

- Exige el commit completo y el SHA-256 revisados: nunca descarga «lo último» sin fijar.
- Solo HTTPS a `huggingface.co` y sus CDN (`*.hf.co`), también en las redirecciones.
- Escribe en `ARCHIVO.part` con creación exclusiva y no sobrescribe nada. Si el hash o el tamaño no coinciden,
  el archivo queda como `.rechazado` para revisarlo y el estado es `fallido`.
- Con el hash correcto, pasa la auditoría GGUF de G1 y deja `descarga.json` con origen, commit, hashes, tamaño,
  auditoría y `verificacion` (`banco: NO VERIFICADO`, adopción pendiente). Código 0 = descargado y auditado.
- Cada descarga queda en el registro de acciones (B8, `modelos.descargar`).

## 3. Cambiar de modelo sin tocar código

El modelo se elige en un solo sitio, `~/.eolfi/eolas-v2.json`. Ningún otro módulo de Eolfi, ni el panel ni la
extensión de VS Code, nombra un modelo: lo leen de ahí. La prueba `tests/test_modelo_unico.py` falla si alguien vuelve
a escribir un nombre de modelo en el código.

```powershell
python -m eolfi eolas-v2 perfiles                       # catálogo: etiqueta, si se puede usar, roles y admisión
python -m eolfi eolas-v2 alta qwen3_q4 D:\AI\Hydra\gguf\Qwen3-14B-Q4_K_M.gguf --etiqueta "Qwen3 14B Q4" --ctx 16384
python -m eolfi eolas-v2 examen qwen3_q4                # ronda completa: código y herramientas (carga el modelo, Docker)
python -m eolfi eolas-v2 activo qwen3_q4                # perfil de chat, generador y VS Code
python -m eolfi eolas-v2 rol revisor qwen3_q4           # o solo un papel: rapido, completo, redactor, revisor
```

- **Alta.** Un GGUF local pasa a ser un perfil con su etiqueta (nombre visible), su contexto y capas en la GPU, si
  piensa en un bloque aparte (`--razonamiento deepseek`) y si usa las reglas de Mistral Instruct (`--plantilla
  mistral`). Solo se admiten opciones de llama-server acotadas (`-fa`, `-ctk`, `-ctv`, `-np`, `--cache-ram`).
  El alta no activa el modelo ni lo arranca.
- **Roles.** `roles` en `eolas-v2.json` dice qué perfil hace cada papel: `rapido` y `completo` para el proveedor
  automático, y `redactor` y `revisor` para CeltIA V2. Si el perfil de un rol falta, no tiene GGUF, está retirado o
  no está admitido, se usa el perfil activo. Las claves antiguas `celtia_v2_redactor` y `celtia_v2_revisor` siguen
  valiendo.
- **Eolas V1.** El modelo que se pide a CeltIA va en `eolas_v1_model`. `EOLAS_MODEL` lo sustituye en una sola
  ejecución.

### Examen de herramientas (requisito para los modelos nuevos)

Un modelo nuevo (dado de alta o reconstruido) no se puede activar ni recibir un rol hasta aprobar la ronda completa.
La ronda exige al menos el 85 % a la primera en código y en herramientas. Las herramientas se examinan en cuatro
aspectos:

1. **Usarlas:** identificar un binario, buscar y leer en Alejandría, calcular ejecutando código y reimplementar lo leído.
2. **Elegir la correcta entre varias:** usar una que no corresponde es fallo.
3. **No usarlas cuando no hacen falta:** responder sin llamadas.
4. **Saber para qué sirve cada una:** sin llamarlas, decir cuál usaría para cada tarea.

El resultado queda en `~/.eolfi/eolas-v2/admision.json` con la huella del GGUF (ruta y tamaño). Un examen deja de
valer en dos casos: si el archivo cambia o si el examen es anterior a las pruebas actuales. Entonces hay que repetirlo.
Los perfiles de serie ya pasaron por las rondas de motores: para ellos el examen es recomendable, pero no obligatorio.

## Límites

- El hash publicado demuestra que se recibió lo publicado, no que los pesos sean seguros ni mejores.
- Para continuar una descarga interrumpida, repite `modelos descargar` con los mismos argumentos y añade
  `--reanudar`. Conserva juntos el `.part` y su `.part.control`. Eolfi comprueba el repositorio, el archivo,
  la revisión y el SHA-256 antes de pedir el rango pendiente. Si el servidor ignora el rango se conserva el
  parcial. Antes de publicar el archivo se calcula el hash completo, incluidos los bytes reutilizados.
- Para examinar dos perfiles usa `eolfi eolas-v2 examen BASE CANDIDATO --informe ronda.json`. El destino debe
  ser un JSON nuevo: se escribe atómicamente y nunca se sobrescribe una evidencia anterior. Después ejecuta
  `eolfi eolas-v2 comparar-banco ronda.json BASE CANDIDATO` para ver qué casos ganó o perdió cada uno.
  La comparación requiere una ronda con todos los casos previstos, ejecutados por ambos perfiles sin repesca.
- Probado con respuestas simuladas; la consulta real a Hugging Face no se ha ejecutado: NO VERIFICADO.
