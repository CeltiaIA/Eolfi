Tarea O4 (continuación) en D:\Eolfi-objetivos. La ronda anterior hizo 3 de 4 ediciones en eolfi/vscode-bridge/agent-tools.js, pero NO terminó: faltan los pasos de abajo. No digas que está hecho hasta haber ejecutado node --test y visto su resultado.
Tu contexto es pequeño: NO leas archivos enteros ni listes carpetas.

1) eolfi_edit_file, path "eolfi/vscode-bridge/agent-tools.js":
   old_text: p.on('close', (code) => { clearTimeout(timer);
   new_text: p.on('close', (code) => { killed = true; clearTimeout(timer);

2) eolfi_edit_file, mismo path (sobran 3 espacios de sangría):
   old_text: "         // Mata el árbol completo"
   new_text: "      // Mata el árbol completo"

3) Crea con eolfi_write_file el archivo "eolfi/vscode-bridge/test/agent-tools-kill.test.js" copiando EXACTAMENTE el bloque que está en D:\Eolfi-objetivos\PROMPT_O4.md después de «con este contenido exacto:» y antes de «Luego ejecuta» (léelo con eolfi_read_file usando start_line 29 y end_line 91 y copia solo el código JavaScript, desde 'use strict'; hasta el último «});»).

4) En la terminal: cd D:\Eolfi-objetivos\eolfi\vscode-bridge; node --check agent-tools.js; node --test
   Si algo falla, corrígelo con eolfi_edit_file sin debilitar pruebas y repite.

5) Con eolfi_informe_anadir añade a informes/progreso-objetivos-eolfi.md una sección «O4 — resultado» con los archivos cambiados y las líneas literales «tests», «pass» y «fail» de node --test.

Solo cuando 4) haya pasado, termina con la línea EOLFI-OBJETIVOS-FIN.
