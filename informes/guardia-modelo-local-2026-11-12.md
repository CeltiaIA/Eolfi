# Un solo modelo local en la GPU (A4) — 2026-11-12

Decisión del titular sobre el punto A4 de `informes/revision-retirada-y-limpieza-2026-11-12.md`: **guardia común**.
Eolas sigue siendo la vía de uso diario, eolas-v2 queda para experimentos con una guardia en los dos sentidos, y se
retira `eolfi llama start`.

## Problema observado

- **11 de noviembre:** «bad allocation». Eolas cargó Gemma mientras un llama-server huérfano ocupaba el 8090.
- **12 de noviembre:** en el laboratorio, eolas-v2 llevaba Mistral-Nemo cargado en el 8090 desde las 22:01
  (PID 18248). Eolas cargó Gemma al recibir la primera petición del agente. Con 8 GB de VRAM, Gemma quedó casi
  entera en la CPU y el agente avanzaba muy despacio.
- **Por qué no lo frenó la comprobación anterior:** eolas-v2 solo se negaba a arrancar si Eolas *anunciaba* modelos
  (`/api/tags`). Eolas anuncia su catálogo siempre, aunque no tenga nada en memoria, y carga el modelo más tarde, al
  recibir una petición. Ese sentido (Eolas carga cuando eolas-v2 ya está) no lo protegía nada.

## Cambios

| Cambio | Archivo |
|---|---|
| Módulo nuevo con varias funciones. `eolas_loaded()`: lo que Eolas tiene **cargado** (`/api/ps`). `release_eolas()`: le pide descargarlo (`keep_alive: 0`). `eolas_v2_holder()`: indica si eolas-v2 está vivo y si está generando (`/slots`). `check_before_eolas_v2()` y `free_for_eolas()`: las dos guardias. Además, un vigilante de inactividad. | `eolfi/local_gpu.py` |
| eolas-v2 se niega a arrancar si Eolas tiene un modelo **cargado**; el catálogo ya no cuenta. Con `eolfi eolas-v2 start --liberar-eolas` primero pide a Eolas que lo descargue. | `eolfi/eolas_v2.py` (`_legacy_eolas_models`, `_start_locked`, `start`), `eolfi/cli.py` |
| Cada servidor real de eolas-v2 lleva un vigilante, `python -m eolfi.local_gpu watch`, que lo para tras 15 minutos sin peticiones (`EOLFI_LOCAL_IDLE_MINUTES`; 0 lo desactiva). Cuenta las peticiones por `id_task`, así que también detecta las cortas que caen entre dos comprobaciones. | `eolfi/local_gpu.py`, `eolfi/eolas_v2.py` |
| Antes de una petición a Eolas *local*, el proveedor `eolas`/`gemma` para eolas-v2 si está ocioso. Si está generando, devuelve un error claro en vez de cargar otro modelo encima. Con un Eolas remoto no hace nada. | `eolfi/generador/llm.py` (`OllamaProvider.complete`) |
| La extensión de VS Code no pide nada a Eolas si eolas-v2 tiene un modelo cargado. Muestra cómo pararlo, o avisa de que se parará solo. Lee `~/.eolfi/eolas-v2.runtime.json` (o `EOLFI_EOLAS_V2_CONFIG`). Versión de la extensión: 0.6.12. | `eolfi/vscode-bridge/local-model.js`, `package.json` |
| `eolfi llama start` queda retirado: termina con código 2 y explica qué usar en su lugar. `status`, `stop` y `config` siguen disponibles para limpiar servidores antiguos. | `eolfi/cli.py` |

**Trabajo sin confirmar del titular:** no se tocan las partes de `eolas_v2.py`, `cli.py`, `llm.py` ni
`tests/test_eolas_v2.py` que el titular tiene modificadas en `D:\Eolfi`. Se comprobaron las zonas de cada diff local
para que estos cambios caigan en otras. En la prueba existente solo cambia el texto esperado del error.

## Pruebas

- Suites completas en local (Windows, Python 3.12.10): `python -m pytest -q` 546 aprobadas, 2 omitidas, 0 fallos; `node --test` en `eolfi/bridge` 63/0 (4 omitidas) y en `eolfi/vscode-bridge` 181/0; `npm test` en `tests/e2e` 18/0; `ruff --select F` limpio.
- `tests/test_local_gpu.py`, 6 pruebas con servidores HTTP simulados:
  - lo cargado frente al catálogo, y la liberación;
  - eolas-v2 se niega con Eolas cargado y arranca con `--liberar-eolas`;
  - eolas-v2 ocioso se para y uno ocupado no se interrumpe;
  - el proveedor solo aplica la guardia en local;
  - el vigilante para tras la inactividad y cuenta las peticiones cortas;
  - `llama start` retirado.
- `eolfi/vscode-bridge/test/local-model.test.js`: prueba nueva de la guardia de la extensión, con lectura real del
  archivo de estado.
- **Comprobación en el equipo real**, solo lectura: `python -m eolfi.local_gpu status` devolvió
  `{"eolas_loaded": ["gemma-4-12b-it:latest"], "eolas_v2": null}`. `python -m eolfi llama start` terminó con
  código 2 y el mensaje de retirada.

## NO VERIFICADO

- **Vigilante con un llama-server real de eolas-v2:** no se arrancó eolas-v2 para no cargar otro modelo en la GPU
  del titular. Está probado con un servidor y un reloj simulados.
- **`release_eolas` contra Eolas real:** la descarga con `keep_alive: 0` sigue la API de Ollama, que es la que
  publica Eolas 0.5.0. No se ejecutó para no descargar el modelo del titular mientras lo usaba.
- **Clientes de Eolas ajenos a Eolfi** (CeltIA, la web): pueden seguir pidiendo a Eolas que cargue Gemma con
  eolas-v2 en marcha. Esta guardia solo cubre los clientes de Eolfi. Para esos queda el vigilante, que libera
  eolas-v2 cuando no se usa.
