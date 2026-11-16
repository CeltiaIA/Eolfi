# G1: auditor en el chat y conexiones por PID — 16/11/2026

Continuación en `D:\Eolfi`, rama `codex/modelos-bloque-g`. Se conservan los cambios anteriores sin confirmar.
No hay commits, publicación, instalaciones, cambios de configuración ni de cortafuegos. No se ha lanzado,
detenido ni llamado al motor para generar texto.

## Qué cambia

- `python -m eolfi modelos conexiones --pid PID`: consulta nativa TCP/UDP, IPv4/IPv6, solo Windows.
- `python -m eolfi modelos auditar ARCHIVO --pid PID`: añade esa instantánea al informe del GGUF.
  Una consulta incompleta conserva los sockets obtenidos, marca la incógnita y devuelve código 2.
- `eolfi_modelos_auditar` en MCP y en el conjunto de herramientas del chat: lee GGUF sin cargar pesos,
  respeta las raíces permitidas y etiqueta el resultado como datos del objetivo. Acepta un adjunto `.bin`
  por su cabecera; no depende de la extensión. Un error de auditoría no se anuncia como llamada correcta.
- El contexto del chat orienta los adjuntos y rutas `.gguf` al auditor, también si se marcó «como binario»:
  no propone tratarlos como ejecutables nativos ni ejecutar su plantilla. Los archivos mal nombrados
  siguen teniendo que superar la comprobación de cabecera.

La implementación de conexiones usa `eolfi/modelos_red.py` y carga `iphlpapi.dll` desde System32.
La lectura tiene límites de tamaño/cantidad y hasta tres intentos si cambian las tablas. No consulta DNS,
no inicia un proceso auxiliar y no requiere instalar nada.

Entorno comprobado: Windows 11 `10.0.26300`, AMD64, Python 3.12.10 de 64 bits, ejecutable
`C:\Users\mejil\AppData\Local\Programs\Python\Python312\python.exe`.

## Evidencia ejecutada

### Motor existente

[`conexiones-motor-34776-final.json`](conexiones-motor-34776-final.json): orden CLI real, salida 0;
PID 34776, una escucha TCP `127.0.0.1:8090` y una conexión establecida cuyo remoto también es `127.0.0.1`.
Se consultaron las cuatro tablas TCP/UDP IPv4/IPv6; no se devolvieron enlaces UDP para ese PID.
No se observaron en esa instantánea remotos TCP ni escuchas fuera de loopback.

[`identidad-conexiones.json`](identidad-conexiones.json): identidad de archivos en disco, sin ejecución:

- `D:\EOLAS-BASE\llama\llama-server.exe`:
  `e339d7a3aad4bb0be10267a447e125db1f0a7db501eca08cddd8e4adcbadce08`.
  No declara versión de archivo/producto: versión **NO VERIFICADA** en esta comprobación.
- `C:\WINDOWS\System32\iphlpapi.dll`:
  `75c96c32969e9e1c13590287a63fb124af734bf4984fcb545cbc95523405cb2b`,
  versión de archivo `10.0.26100.9949 (WinBuild.160101.0800)`.
  La consulta informa Windows `10.0.26300`; versión del SO y del archivo se registran por separado.

No se ha comprobado que el ejecutable en disco coincida con la memoria del proceso ni se han inventariado
sus DLL cargadas. No se establece relación entre el PID y el contenido del GGUF a partir del nombre.

### Auditor MCP real

[`mcp-gemma-q4.json`](mcp-gemma-q4.json): `EolfiMCP.call_tool("eolfi_modelos_auditar", ...)` contra
`D:\AI\Hydra\gguf\gemma-4-12b-it-Q4_K_M.gguf`, sin un modelo generando la llamada.
667 tensores; SHA-256 completo
`43fec98c5102b1c446b4ddd0a9439f1db3a2e1f2e0b8cd143ce1ea619a9403d6`.
La operación termina y el análisis conserva **NO VERIFICADO**: 285 tensores de tipo 12 y 44 de tipo 14
con tamaño de bloque no establecido. No se cambia este resultado a verde por haber funcionado la llamada.

El contraste REA de la misma identidad y cabecera está en [`rea-gemma-q4.json`](rea-gemma-q4.json), realizado
en el avance anterior. No se repitió una pasada estática para presentarla como prueba de sockets.

## Validación

- `python -m pytest -q tests/test_guia_agente_vscode.py tests/test_modelos.py tests/test_modelos_red.py tests/test_chat.py tests/test_mcp_server.py`:
  **73 pasadas**. Incluye sockets loopback reales TCP y UDP de ambas familias en Windows; filtrado por PID,
  puertos, direcciones IPv4 mapeadas en IPv6, lectura parcial, rechazo de rutas fuera de raíces, cabecera
  GGUF con extensión `.bin`, salida desconocida conservada en CLI y bucle del chat con auditor real.
  Solo se sustituye la respuesta del modelo en esa prueba del chat; no equivale a que Gemma elija la herramienta.
- `node --test` en `eolfi/bridge`: **63 pasadas, 4 omitidas** (navegador real optativo).
- `node --test` en `eolfi/vscode-bridge`: **192 pasadas**.
- `npm test` en `tests/e2e`: **19 pasadas**, incluidos adjuntos de tres formatos y accesibilidad.
- Suite completa: **721 pasadas, 1 fallida, 2 omitidas**, 406,39 s. La única fallida era
  `test_guia_servidor_mcp`: esperaba 12 herramientas y obtuvo 13. Se actualizó la guía y la comprobación
  a 13, exigiendo también el auditor y sus atributos de solo lectura/mundo cerrado. Se conserva el resto
  de verificaciones de protocolo, raíces y triaje; no se ha reducido cobertura para dar verde.
- Repetición Python completa final: `python -m pytest -q` → **722 pasadas, 2 omitidas**, 408,62 s,
  salida 0. Dos invocaciones anteriores se interrumpieron antes de
  completarse para incorporar la corrección de IPv4 mapeada y la interpretación de los ámbitos IPv6 y
  extremos remotos de escuchas; no cuentan como validación completa.

El panel real respondió a `/api/health`: PID 32616, inicio a las 22:23:29 (Europa/Madrid), posterior a los
cambios de `chat.py` (22:17:19) y `mcp_server.py` (22:12:20). Se comprobó la recarga sin enviarle un trabajo
al modelo. `git diff --check` sin errores; quedan avisos de normalización CRLF/LF, no cambios de cobertura.

## Contrato y límites

La estructura y las llamadas se contrastaron con documentación primaria de Microsoft:
[GetExtendedTcpTable](https://learn.microsoft.com/en-us/windows/win32/api/iphlpapi/nf-iphlpapi-getextendedtcptable),
[GetExtendedUdpTable](https://learn.microsoft.com/en-us/windows/win32/api/iphlpapi/nf-iphlpapi-getextendedudptable),
[fila TCP IPv6 con PID](https://learn.microsoft.com/en-us/windows/win32/api/tcpmib/ns-tcpmib-mib_tcp6row_owner_pid) y
[fila UDP IPv6 con PID](https://learn.microsoft.com/en-us/windows/win32/api/udpmib/ns-udpmib-mib_udp6row_owner_pid).
Se convierten puertos/ámbitos desde el orden de red; en LISTEN no se interpreta un extremo remoto.

Las cuatro tablas se leen una tras otra, no son un historial ni una vigilancia continua. Un remoto no
loopback puede ser privado y no distingue tráfico entrante de saliente. UDP no revela destinos ni paquetes.
Una lista vacía no demuestra que el PID esté vivo. El proveedor Linux/macOS no se ha implementado: devuelve
**NO VERIFICADO**. No se asocia por esta consulta un archivo GGUF con los pesos en memoria ni se descartan
puertas traseras o vulnerabilidades del motor.

Pendientes de G1: layouts K con procedencia demostrable, proveedores Linux/macOS y elección efectiva del
auditor por un modelo real. G2 continúa sin activar/extender a todos los clientes. G3–G7 siguen pendientes.
La instantánea intermedia `conexiones-motor-34776.json` se conserva como historial y está registrada en limpieza;
para la interpretación final de escuchas debe consultarse el archivo terminado en `-final.json`.
