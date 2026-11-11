Tarea O4 (último paso) en D:\Eolfi-objetivos. El código de eolfi/vscode-bridge/agent-tools.js ya está cambiado. Falta solo crear la prueba y ejecutarla. NO leas ni edites agent-tools.js.

1) Crea la prueba copiando las líneas 29-91 de PROMPT_O4.md con UNA orden de terminal (eolfi_terminal, carpeta "."):
Get-Content -Encoding UTF8 PROMPT_O4.md | Select-Object -Skip 28 -First 63 | Set-Content -Encoding UTF8 eolfi\vscode-bridge\test\agent-tools-kill.test.js

2) Ejecuta en la terminal (carpeta "eolfi/vscode-bridge"): node --check agent-tools.js; node --test test/agent-tools-kill.test.js; node --test

3) Con eolfi_informe_anadir añade a informes/progreso-objetivos-eolfi.md una sección «O4 — resultado» con: archivos cambiados (eolfi/vscode-bridge/agent-tools.js, eolfi/vscode-bridge/test/agent-tools-kill.test.js) y las líneas literales «tests», «pass» y «fail» del último node --test.

Solo si node --test termina sin fallos, acaba con la línea EOLFI-OBJETIVOS-FIN. Si falla, copia el error en la sección del progreso y no pongas esa línea.
