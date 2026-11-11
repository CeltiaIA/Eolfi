# Licencias de terceros — Eolfi

Eolfi es software propietario de CeltiaIA (celtiaia.com) (véase [LICENSE](LICENSE)). Este archivo enumera los
componentes de terceros que Eolfi usa, descarga o invoca. Cada uno se rige por su propia licencia; la licencia de
Eolfi no la modifica (LICENSE, apartado 4).

Actualizado: 2026-11-06.

## 1. Dependencias incluidas en el puente de chats web (`eolfi/bridge/node_modules`)

Instaladas con npm como dependencias de desarrollo de `eolfi/bridge` (Electron y lo que necesita para descargarse).

| Paquete | Versión | Licencia |
|---|---|---|
| electron | 45.2.2 | MIT |
| @electron/get | 5.1.0 | MIT |
| @electron-internal/extract-zip | 1.0.8 | MIT |
| @types/node | 24.19.2 | MIT |
| debug | 4.4.3 | MIT |
| env-paths | 3.0.0 | MIT |
| graceful-fs | 4.2.11 | ISC |
| ms | 2.1.3 | MIT |
| progress | 2.0.3 | MIT |
| semver | 7.8.6 | ISC |
| sumchecker | 3.0.1 | Apache-2.0 |
| undici | 7.30.1 | MIT |
| undici-types | 7.24.6 | MIT |

Electron incorpora Chromium, Node.js y otros componentes con sus propias licencias; el detalle se distribuye con
Electron en `node_modules/electron/dist/LICENSES.chromium.html` y `LICENSE`.

## 2. Dependencias de Python (`pyproject.toml`)

El núcleo de Eolfi usa solo la biblioteca estándar de Python (licencia PSF). Dependencias opcionales:

| Paquete | Uso | Licencia |
|---|---|---|
| anthropic | modo asistido (`eolfi assist`, `create --ai`) | MIT |
| pytest | pruebas (desarrollo) | MIT |

## 3. Extensión de VS Code (`eolfi/vscode-bridge`)

Sin dependencias de npm en tiempo de ejecución. Usa la API de extensiones de Visual Studio Code, que proporciona el
propio editor (licencia de Microsoft para Visual Studio Code). GitHub Copilot, cuando se elige como modelo, se usa a
través de la API de modelos de lenguaje de VS Code y se rige por los términos de GitHub Copilot.

## 4. Herramientas externas que Eolfi invoca (no se distribuyen con Eolfi)

Eolfi las ejecuta si están instaladas en el equipo; cada una se obtiene e instala por separado.

| Herramienta | Uso en Eolfi | Licencia |
|---|---|---|
| Ghidra | análisis y descompilación de binarios | Apache-2.0 |
| rizin | análisis de binarios | LGPL-3.0 |
| capa (Mandiant) | detección de capacidades en binarios | Apache-2.0 |
| Servidor de VS Code (`code serve-web` / servidor remoto) | panel web | Licencia de Microsoft para VS Code Server |
| llama.cpp (`llama-server`) | modelo local, directamente o detrás de Eolas | MIT |
| Eolas (CELTIAIA) | motor local de modelos | propietario, de su titular |

## 5. Modelos de lenguaje

Los pesos de los modelos locales (por ejemplo Gemma `gemma-4-12b-it`) no forman parte de Eolfi. Se rigen por los
términos de uso que publica su proveedor, que deben aceptarse al descargarlos.

## Mantenimiento

Al añadir o actualizar dependencias, revisar este archivo. Para el puente web, la lista se obtiene de
`eolfi/bridge/node_modules/*/package.json` (campo `license`).
