# Guía: versión instalada y acceso directo

Dos órdenes para saber qué Eolfi tienes y abrirlo sin terminal. Ninguna instala nada. `tests/test_guia_instalador.py`
ejecuta estos pasos en la CI (Windows y Linux) con una carpeta temporal y un registro de acciones temporal.

## 1. Qué versión tengo

```bash
python -m eolfi --version
python -m eolfi update --check
```

**Aceptación:** `--version` y `update --check` dan la misma versión (`instalada.version`). `instalada.modo` dice cómo
está instalado (`copia_repositorio`, `entorno_virtual`, `pipx`, `ejecutable` o `python_sistema`); en una copia del repositorio incluye
el commit. `instala_nada` es `true`.

Sin `--red` no se consulta GitHub: `estado` es `NO VERIFICADO`, el motivo lo explica y el código de salida es `2`.
Con `--red` compara con la última publicación de `CeltiaIA/Eolfi` (sin credenciales; nunca con `EOLAS_OFFLINE=1`).

## 2. Un lanzador del panel

```bash
python -m eolfi acceso-directo --carpeta lanzadores             # vista previa
python -m eolfi acceso-directo --carpeta lanzadores --aplicar
python -m eolfi acceso-directo --carpeta lanzadores --quitar
```

Sin `--carpeta` el lanzador va al escritorio (`--donde escritorio`) o al menú (`--donde menu`). Aquí se usa una
carpeta de prueba para no tocar el escritorio.

**Aceptación:**

- La vista previa dice qué ejecutará el lanzador (`orden`: Python, `-m eolfi up --port 8777`), dónde lo pondría
  (`ruta`: `Eolfi.lnk` en Windows, `eolfi.desktop` en Linux), `vista_previa: true`, y **no crea nada**.
- `--aplicar` lo crea y lo lee de vuelta: `creado: true` y `comprobado: true`. Queda en el registro de acciones como
  `instalador.acceso_directo` (ver la [guía del registro](../registro-acciones/GUIA.md)).
- `--quitar` lo retira (`quitado: true`). Nunca sustituye ni borra un archivo que no sea un lanzador de Eolfi.

NO VERIFICADO aquí: macOS, `pipx` real y el ejecutable firmado (ver C2 en `PLAN_DEFINITIVO.md`).

## Limpieza

Borra la carpeta `lanzadores`.
