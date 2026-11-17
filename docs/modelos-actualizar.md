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

## Límites

- El hash publicado demuestra que se recibió lo publicado, no que los pesos sean seguros ni mejores.
- No hay reanudación de descargas cortadas: el `.part` se conserva y hay que retirarlo a mano tras revisarlo.
- Comparar con el banco antes de adoptar sigue siendo manual (el banco sobre la reconstrucción está suspendido).
- Probado con respuestas simuladas; la consulta real a Hugging Face no se ha ejecutado: NO VERIFICADO.
