# @eolfi no leía los archivos adjuntos del chat — 2026-11-12

## Hallazgo, en un VS Code real

En el chat de VS Code, el usuario puede adjuntar archivos con 📎, arrastrándolos, con «Add Context» o con `#file`.
VS Code los entrega a la extensión en `request.references`. `eolfi/vscode-bridge/chat.js` no leía ese campo, así
que el modelo solo recibía el texto escrito.

En la ventana de laboratorio, con dos adjuntos y la pregunta «¿Qué archivos te he adjuntado?»:
- **Primer intento:** el agente se puso a buscarlos por el workspace (pasos `workspace` y `list_files`).
- **Segundo intento:** respondió «No veo ningún archivo adjunto en tu mensaje», aunque el titular los había
  adjuntado.

## Corrección

- **`eolfi/vscode-bridge/attachments.js`, módulo nuevo:** lee `request.references` (`Uri` y `Location`, sin
  repetidos, solo `file:`, como mucho 20) y añade al mensaje del usuario un bloque «ARCHIVOS ADJUNTOS POR EL
  USUARIO». El bloque advierte que no hay que buscarlos y que su contenido son DATOS, no instrucciones.
- **Dentro de las carpetas abiertas:** se da la ruta relativa, que las herramientas sí pueden leer. Si es texto de
  hasta 8 KB, también va el contenido entre marcas de inicio y fin, con un tope de 24 KB por mensaje, pensando en el
  contexto del modelo local. Un binario se remite a `eolfi_triage` o REA, y un texto grande se lee con las
  herramientas.
- **Fuera de las carpetas abiertas:** las herramientas no pueden leerlo (error 403). Un texto pequeño se incluye,
  porque el usuario lo adjuntó expresamente. Si es binario o grande, se explica que hay que abrir esa carpeta en VS
  Code.
- **Secretos:** se aplican las mismas reglas que en las herramientas (`isSecretPath`, también tras resolver enlaces).
  Un `.env` adjunto **no** se incluye.
- **Fragmentos (`#file` con un rango):** solo se incluyen esas líneas.
- **`chat.js`:** el bloque se añade al mensaje del usuario en las dos rutas del agente, Copilot y modelo local.
- **Versión** de la extensión: 0.6.13.

## Pruebas

- `test/attachments.test.js` (4 pruebas): referencias de distintos tipos, dentro y fuera del workspace, binario,
  texto grande, `.env` y fragmento de líneas.
- `test/chat.test.js`: una prueba nueva comprueba que el contenido adjunto llega al modelo dentro del mensaje.
- `node --test` en `eolfi/vscode-bridge`: 186 de 186.

## Comprobación en el VS Code real

Ventana de laboratorio, VS Code 1.145.3, con la extensión del repositorio y Gemma local.

- **Qué entrega VS Code:** un registro temporal, ya retirado, mostró que llegan 4 referencias.
  - `referencia.py` y `candidato.py`, como `Uri` de tipo `file:` con `fsPath`.
  - La página del panel (`vscode-browser:`) y un texto sobre las páginas compartidas. La corrección descarta las
    dos.
- **Respuesta a «¿Qué archivos te he adjuntado?»:** en 2 pasos y sin buscar por el workspace, dio
  `ejemplos/triaje-y-diff/referencia.py` y `ejemplos/triaje-y-diff/candidato.py`, cada uno con su primera línea
  exacta, comprobada con `head -1`.
- **El «No veo ningún archivo adjunto» anterior:** correspondía a una petición enviada antes de recargar la ventana.

## NO VERIFICADO

- Adjuntos fuera de las carpetas abiertas, binarios y `.env` en el VS Code real (cubiertos por pruebas).
- La ruta de Copilot en el VS Code real: en el laboratorio se usó el modelo local. La de Copilot está cubierta por
  la prueba de `chat.test.js`.
