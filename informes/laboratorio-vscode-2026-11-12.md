# Laboratorio del agente @eolfi en un VS Code real — 2026-11-12

Es el paso A de `ejemplos/agente-vscode/GUIA.md` y lo pide la Fase 7: la sesión del agente en un VS Code real.
Hasta ahora estaba NO VERIFICADO.

## Entorno

- **VS Code 1.145.3 en Windows 11.** Ventana «Extension Development Host» abierta con
  `python -m eolfi vscode <carpeta>`. Usa la extensión del repositorio (`eolfi/vscode-bridge` de `main`), no la
  instalada. La instalada se llama igual, 0.6.11, pero es más antigua: le faltan `file-tools.js`, `lm-provider.js` y
  otros archivos.
- **Perfil del titular.** Sus ajustes incluyen `eolfi.agent.mode: "automatico"`, `eolfi.agent.model: "local"` y
  `eolfi.fallback.autoStart: true`.
- **Carpeta de laboratorio:** una copia de `ejemplos/` fuera del repositorio, para que el agente no escriba en él.
- **Modelo:** Eolas con Gemma 4 12B Q4_K_M (`127.0.0.1:11435`), servida por llama.cpp con `-ngl 7`, contexto de
  16384 y razonamiento activado. GPU de 8 GB.
- **Quién hizo qué:** las órdenes las escribió el titular en el chat. Yo envié una pulsando el botón de enviar y
  verifiqué con capturas, el estado de procesos y los registros.

## Resultados frente a la aceptación de la guía

| Paso / criterio | Resultado |
|---|---|
| `@eolfi /ayuda` | **Cumple.** Lista las órdenes, abre el panel y avisa de que Copilot está desconectado. |
| `@eolfi /modelo local`; responde el modelo local sin Copilot | **Cumple.** Responde «Modelo principal: local (llama.cpp) · gemma-4-12b-it-Q4_K_M.gguf · razonamiento activado (oculto) · temperatura 0.2. Copilot está desconectado.» |
| `@eolfi analiza ejemplos/triaje-y-diff/muestra.wasm`; llama al triaje y responde con las evidencias | **Cumple.** El panel registra el trabajo «triaje «default» de muestra.wasm: 6 proveedores». La respuesta separa evidencias, inferencias e incógnitas. El formato (WebAssembly) es correcto y el SHA-256 `ed2bf44b…53d84e4` coincide con el archivo (comprobado con `sha256sum`). |
| Al final indica qué modelo trabajó (`eolfi.agent.showModel`) | **Cumple**, una vez aplicada la corrección del defecto 1. Termina con «Modelo: gemma-4-12b-it:latest (llama.cpp local) · en tu equipo, sin Copilot.» |
| Con la corrección cargada (ventana recargada), repetir el análisis | **Cumple.** Ofrece «¿Deseas que realice un análisis más profundo…?» y se para ahí. Sin la corrección, ese mismo final desencadenaba más de 12 pasos sin sentido. |
| `/manual`: responde con las reglas del modo | **Cumple.** «Modo manual. Te pido permiso para los cambios: diff para aplicar o descartar, terminal e internet una vez por sesión; cada URL privada, borrado y herramienta de REA que ejecuta algo también se confirma.» |
| En modo manual, cada escritura muestra un diff para aprobarla | **Cumple.** «crea el archivo notas/prueba2.md…» abrió la pestaña «prueba2.md ↔ cambio propuesto por Eolfi (archivo nuevo)» y el archivo **no se escribió en disco** mientras no se aprobó (comprobado con `ls`). |
| En modo automático, la terminal no pide permiso | **Cumple.** `python --version` se ejecutó sin preguntar («Python 3.12.10») y quedó en `~/.eolfi/agent-log.jsonl`. `notas/prueba.md` también se escribió sin diff. |
| En modo manual, la terminal pide permiso una vez por sesión | **NO VERIFICADO.** En las dos tandas se envió `/auto` antes de la orden de terminal. Fue por cómo agrupé las instrucciones, no un fallo de Eolfi: `settings.json` cambió a «automatico» justo con ese `/auto`. |
| Servidor MCP «Eolfi» en el modo agente | **NO VERIFICADO** en esta sesión. El servidor por stdio sí está cubierto en la CI (pasos B y C). |

## Defectos encontrados

1. **El modo automático convertía una tarea terminada en otra sin fin, y el modelo local llegó a simular trabajo.**
   - **Qué pasó:** tras responder al análisis, Gemma cerró con «¿Deseas que realice un análisis más profundo con
     las herramientas de REA…?». `asksInsteadOfDoing` (`chat.js`) lo tomó como «pregunta en vez de hacer» y, en modo
     automático, le ordenó hasta 10 veces «No me preguntes… HAZLO ahora… sin parar hasta terminar la tarea
     completa». El agente siguió por su cuenta durante más de 12 de los 40 pasos permitidos:
     - leyó la guía y los scripts del ejemplo;
     - ejecutó `python3 -c "import os; print('Simulando triaje de muestra.wasm...')"`, es decir, simuló el triaje
       en vez de usar una herramienta;
     - escribió un script con un `SyntaxError`.
   - **Corrección:** nueva función `offersExtraAfterAnswer`. Si en la petición ya se usaron herramientas, la
     respuesta tiene cuerpo (300 caracteres o más antes de la última pregunta) y esa pregunta solo ofrece trabajo
     extra («más profundo», «adicional», «ampliar», «además», «descompilar»…), no se empuja: la tarea está hecha.
     Pedir permiso para la propia tarea («¿Quieres que los analice?») se sigue empujando como antes. Además, el
     texto del empujón prohíbe ahora «simular o inventar resultados» y ejecutar órdenes que solo imprimen texto.
   - **Pruebas:** dos nuevas en `eolfi/vscode-bridge/test/chat.test.js`, con el texto real de esta sesión.
     `node --test` en `eolfi/vscode-bridge`: 180 de 180.
   - **Comprobado en el VS Code real:** tras recargar la ventana con la corrección, el mismo análisis se para en la
     oferta y muestra el modelo.
2. **Dos modelos cargados a la vez en 8 GB de VRAM.**
   - **Qué pasó:** «Eolas v2» (`eolfi/eolas_v2.py`, cambios sin confirmar del titular) había dejado Mistral-Nemo
     12B en el puerto 8090 desde las 22:01 del día anterior (PID 18248, `~/.eolfi/eolas-v2.runtime.json`), junto a la
     Gemma de Eolas.
   - **Solución aplicada:** se paró con `python -m eolfi eolas-v2 stop`, a petición del titular. La memoria usada en
     la GPU bajó de 6,1 GB a 3,2 GB.
   - **Pendiente:** no se modifica `eolas_v2.py` porque es trabajo sin confirmar del titular. Queda como propuesta:
     que Eolas o Eolas v2 avise cuando otro llama-server ocupa la GPU.
3. **El agente local es demasiado lento para tareas largas.**
   - **Qué pasó:** Gemma 12B con `-ngl 7` y razonamiento activado corre casi entera en la CPU (uso de la GPU entre
     el 2 y el 10 %). Cada paso tarda minutos, así que una tarea de 40 pasos no es práctica.
   - **Propuesta:** un modelo más pequeño que quepa en la GPU, menos contexto para subir `-ngl`, o desactivar el
     razonamiento en tareas largas.

## Otros hallazgos del procedimiento

- **`code chat` no sirve para dirigir un laboratorio con varias ventanas.** Ignora `--user-data-dir` y manda la
  orden a la última ventana activa. Un `@eolfi /ayuda` acabó en la ventana principal del titular; no tuvo efecto,
  porque es solo informativo. Para repetir el laboratorio, las órdenes debe escribirlas una persona en la ventana
  de desarrollo.
- **Desde el uso del ordenador, VS Code solo admite clics.** No se puede escribir en él, así que esta sesión
  necesita al titular.

## NO VERIFICADO

- Que en modo manual la terminal y el acceso a internet pidan permiso una vez por sesión. Las pruebas de la
  extensión lo cubren con un VS Code simulado, pero en el real no se llegó a ver.
- Que cada borrado y cada URL privada pidan confirmación también en modo automático.
- El servidor MCP «Eolfi» desde el modo agente de VS Code.
