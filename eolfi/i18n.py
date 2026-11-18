"""Idiomas es/en de la CLI y de la API (C1, PLAN_DEFINITIVO.md).

Eolfi está escrito en castellano y el inglés se añade con catálogos cuya clave es el propio texto en castellano,
como en el panel (``eolfi/web/i18n-en.json`` y ``eolfi/web/i18n.js``): no hay claves que mantener aparte y un texto
sin traducir se muestra tal cual, en castellano.

- CLI: ``eolfi --idioma en …`` o ``EOLFI_IDIOMA=en``. Traduce la descripción y la ayuda de cada subcomando
  (``-h``) y la de los argumentos que estén en el catálogo. Los resultados JSON no cambian: sus claves son la API.
- API: ``?lang=en``, la cookie ``eolfi_idioma`` que guarda el panel o ``Accept-Language``. Traduce el campo
  ``error`` de las respuestas si el mensaje completo está en el catálogo y responde con ``Content-Language``.
"""
from __future__ import annotations

import argparse
import os
import re
from collections.abc import Sequence

IDIOMAS = ("es", "en")
DEFECTO = "es"


def _valido(valor: str | None) -> str | None:
    v = (valor or "").strip().lower()[:2]
    return v if v in IDIOMAS else None


def idioma_cli(argv: Sequence[str]) -> str:
    """``--idioma X`` / ``--idioma=X`` en la línea de órdenes, después ``EOLFI_IDIOMA``; si no, castellano."""
    for i, a in enumerate(argv):
        if a == "--idioma" and i + 1 < len(argv):
            return _valido(argv[i + 1]) or DEFECTO
        if a.startswith("--idioma="):
            return _valido(a.split("=", 1)[1]) or DEFECTO
    return _valido(os.environ.get("EOLFI_IDIOMA")) or DEFECTO


def idioma_http(lang: str | None = None, cookie: str | None = None, accept_language: str | None = None) -> str:
    """``?lang``, después la cookie ``eolfi_idioma`` y después ``Accept-Language`` (el de más peso entre es y en)."""
    if _valido(lang):
        return _valido(lang)  # type: ignore[return-value]
    m = re.search(r"(?:^|;\s*)eolfi_idioma=([a-zA-Z-]+)", cookie or "")
    if m and _valido(m.group(1)):
        return _valido(m.group(1))  # type: ignore[return-value]
    mejores: list[tuple[float, int, str]] = []
    for i, parte in enumerate((accept_language or "").split(",")):
        trozos = parte.strip().split(";")
        codigo = _valido(trozos[0])
        if not codigo:
            continue
        q = 1.0
        for t in trozos[1:]:
            if t.strip().startswith("q="):
                try:
                    q = float(t.strip()[2:])
                except ValueError:
                    q = 0.0
        mejores.append((-q, i, codigo))
    return min(mejores)[2] if mejores else DEFECTO


def traducir(texto: str, idioma: str, catalogo: dict[str, str]) -> str:
    if idioma != "en" or not isinstance(texto, str):
        return texto
    return catalogo.get(texto, texto)


def traducir_parser(parser: argparse.ArgumentParser, idioma: str) -> None:
    """Sustituye en el árbol de argparse las descripciones y ayudas que estén en el catálogo de la CLI."""
    if idioma != "en":
        return
    if parser.description:
        parser.description = CLI_EN.get(parser.description, parser.description)
    for accion in parser._actions:
        if accion.help and accion.help is not argparse.SUPPRESS:
            accion.help = CLI_EN.get(accion.help, accion.help)
        if isinstance(accion, argparse._SubParsersAction):
            for elegida in accion._choices_actions:
                if elegida.help:
                    elegida.help = CLI_EN.get(elegida.help, elegida.help)
            for sub in accion.choices.values():
                if sub.description:
                    sub.description = CLI_EN.get(sub.description, sub.description)
                traducir_parser(sub, idioma)


# ── Catálogo de la API: mensajes de error fijos de eolfi/server.py ────────────────────────────────────────────────
API_EN: dict[str, str] = {
    "'sources' debe ser una lista": "'sources' must be a list",
    "'sources' debe ser una lista no vacía": "'sources' must be a non-empty list",
    "Abre VS Code y vincula la extensión de Eolfi.": "Open VS Code and link the Eolfi extension.",
    "Chat local limitado a este equipo.": "Local chat is limited to this computer.",
    "el plan cambió desde que se propuso el encargo: revísalo en el panel":
        "the plan changed since the task was proposed: review it in the panel",
    "los encargos se deciden en el panel o en la extensión de VS Code":
        "tasks are decided in the panel or in the VS Code extension",
    "Content-Length inválido": "Invalid Content-Length",
    "El puente no responde: arráncalo con  python -m eolfi bridge":
        "The bridge is not responding: start it with  python -m eolfi bridge",
    "Mensaje o proyecto no válido.": "Invalid message or project.",
    "No hay espacio suficiente para guardar el adjunto; usa su ruta local":
        "Not enough space to store the attachment; use its local path",
    "acción desconocida": "unknown action",
    "actividad de VS Code no encontrada": "VS Code activity not found",
    "adjunto inválido": "invalid attachment",
    "adjunto no encontrado: vuelve a adjuntarlo": "attachment not found: attach it again",
    "archivo vacío": "empty file",
    "carpeta inválida": "invalid folder",
    "case_id inválido": "invalid case_id",
    "conversación inválida": "invalid conversation",
    "coordenadas fuera de rango": "coordinates out of range",
    "código incorrecto o caducado: genera otro en el panel (Proveedores → Vincular VS Code)":
        "wrong or expired code: generate another one in the panel (Providers → Link VS Code)",
    "demasiados códigos pendientes": "too many pending codes",
    "el cuerpo debe ser un objeto JSON": "the body must be a JSON object",
    "el código de vinculación se genera en el panel de Eolfi": "the link code is generated in the Eolfi panel",
    "elige entre 2 y 6 chats": "choose between 2 and 6 chats",
    "escribe un mensaje (máx. 30 000 caracteres)": "write a message (max. 30,000 characters)",
    "ese trabajo sigue en marcha": "that job is still running",
    "falta 'package' (el JSON exportado del caso)": "missing 'package' (the case's exported JSON)",
    "falta 'path'": "missing 'path'",
    "falta 'script' (ruta del guion u objeto)": "missing 'script' (script path or object)",
    "falta 'source'": "missing 'source'",
    "falta 'subject' (sha256, nombre o ruta ya analizada)": "missing 'subject' (sha256, name or already analyzed path)",
    "falta 'version' (entero)": "missing 'version' (integer)",
    "falta case_id": "missing case_id",
    "falta «project»: la carpeta de un proyecto generado por Eolfi":
        "missing \"project\": the folder of a project generated by Eolfi",
    "faltan coordenadas": "missing coordinates",
    "format debe ser html o md": "format must be html or md",
    "incógnita no encontrada": "unknown not found",
    "kind (texto) y payload (objeto) son obligatorios": "kind (text) and payload (object) are required",
    "la observación EJECUTA el objetivo: envía authorized=true para confirmarlo":
        "the observation RUNS the target: send authorized=true to confirm it",
    "la observación ejecuta programas: no está disponible en modo remoto":
        "the observation runs programs: it is not available in remote mode",
    "la subida se cortó antes de terminar": "the upload was cut off before finishing",
    "las propuestas de automejora se deciden en el panel de Eolfi":
        "self-improvement proposals are decided in the Eolfi panel",
    "limit/offset inválidos": "invalid limit/offset",
    "método no permitido": "method not allowed",
    "objetivo no encontrado o ambiguo": "target not found or ambiguous",
    "proveedor inválido": "invalid provider",
    "providers debe ser una lista de nombres": "providers must be a list of names",
    "run_id o phase inválido": "invalid run_id or phase",
    "ruta no encontrada": "path not found",
    "since inválido": "invalid since",
    "solo la extensión vinculada de VS Code puede publicar actividad":
        "only the linked VS Code extension can publish activity",
    "subida no encontrada": "upload not found",
    "tecla no soportada": "unsupported key",
    "texto inválido": "invalid text",
    "tipo de entrada no soportado": "unsupported input type",
    "tolerances debe ser una lista de patrones": "tolerances must be a list of patterns",
    "trabajo no encontrado": "job not found",
    "upload inválido": "invalid upload",
    "variables debe ser un objeto de textos": "variables must be an object of strings",
    "El cuerpo de la petición no está en UTF-8": "The request body is not UTF-8",
    "Cancelado por el usuario": "Cancelled by the user",
    "Creación fallida: la IA no superó las pruebas; archivos originales restaurados":
        "Creation failed: the AI did not pass the tests; original files restored",
    "Creación fallida: la verificación del proyecto no se superó": "Creation failed: the project verification did not pass",
}

# ── Catálogo de la CLI: descripción y ayuda de los subcomandos ────────────────────────────────────────────────────
CLI_EN: dict[str, str] = {
    "Eolfi — ingeniería inversa local con modelo de evidencias": "Eolfi — local reverse engineering with an evidence model",
    "Idioma de la ayuda (es o en; también EOLFI_IDIOMA)": "Help language (es or en; also EOLFI_IDIOMA)",
    "Ruta de la base de evidencias (por defecto EOLFI_DB o ~/.eolfi/eolfi.db)":
        "Path of the evidence database (default EOLFI_DB or ~/.eolfi/eolfi.db)",
    "Registro encadenado de acciones que cambian estado (B8)": "Chained log of state-changing actions (B8)",
    "Versión instalada y si hay otra publicada (solo comprueba, no instala)":
        "Installed version and whether a newer one is published (checks only, installs nothing)",
    "Modelos GGUF: auditoría, identidad y cuantización local": "GGUF models: audit, identity and local quantization",
    "Comprueba proveedores": "Checks providers",
    "Triaje en un paso": "One-step triage",
    "Lista evidencias": "Lists evidence",
    "Lista preguntas abiertas": "Lists open questions",
    "Marca una incógnita como resuelta": "Marks an unknown as resolved",
    "Verificación diferencial referencia vs candidato (EJECUTA ambos)":
        "Differential verification of reference vs candidate (RUNS both)",
    "Observación de caja negra desde un guion (EJECUTA el objetivo)": "Black-box observation from a script (RUNS the target)",
    "Reconstrucción independiente y trazable desde la especificación del caso":
        "Independent, traceable reconstruction from the case specification",
    "Especificación de comportamiento sustentada por las evidencias de un caso":
        "Behavior specification backed by a case's evidence",
    "Exporta paquete de evidencias": "Exports an evidence bundle",
    "Importa paquete de evidencias": "Imports an evidence bundle",
    "Gestiona casos persistentes de análisis": "Manages persistent analysis cases",
    "Banco de pruebas de resiliencia": "Resilience test bench",
    "Analiza una página o sitio web": "Analyzes a web page or site",
    "Analiza un repositorio local o remoto": "Analyzes a local or remote repository",
    "Crea un proyecto NUEVO a partir de una o varias fuentes": "Creates a NEW project from one or more sources",
    "La IA implementa cambios en un proyecto generado (requiere proveedor configurado)":
        "The AI implements changes in a generated project (requires a configured provider)",
    "Comprueba que no queden errores en un proyecto generado y, si los hay, la IA los corrige (se deshace si no queda en verde)":
        "Checks that a generated project has no errors left and, if it does, the AI fixes them (undone if it does not end green)",
    "Informe HTML o Markdown de un objetivo (con umbral para CI)": "HTML or Markdown report of a target (with a CI threshold)",
    "Compara dos objetivos analizados": "Compares two analyzed targets",
    "Decompila funciones concretas con Ghidra (lento)": "Decompiles specific functions with Ghidra (slow)",
    "Puente Electron para DeepSeek / Gemini / Meta AI web": "Electron bridge for DeepSeek / Gemini / Meta AI web",
    "Acción en VS Code a través del puente: workspace, list, read, find, open, write, command, tool":
        "Action in VS Code through the bridge: workspace, list, read, find, open, write, command, tool",
    "Motor Eolas V2: perfiles Gemma/Mistral alternos, feedback y preparación de aprendizaje":
        "Eolas V2 engine: alternating Gemma/Mistral profiles, feedback and training preparation",
    "Servidor llama.cpp antiguo de Eolfi: estado y parada (arrancar está retirado: usa Eolas o eolas-v2)":
        "Eolfi's old llama.cpp server: status and stop (starting it is retired: use Eolas or eolas-v2)",
    "Abre VS Code con la extensión de Eolfi (agente @eolfi, herramientas y auditoría)":
        "Opens VS Code with the Eolfi extension (@eolfi agent, tools and audit)",
    "Guarda el código y los textos de las fuentes compartidas en el corpus de Alejandría":
        "Stores the code and texts of shared sources in the Alejandría corpus",
    "Conjunto de datos para entrenar modelos (SFT en chat y preentrenamiento) a partir del corpus de Alejandría: verificado, sin duplicados y con privacidad":
        "Dataset to train models (chat SFT and pretraining) from the Alejandría corpus: verified, deduplicated and privacy-aware",
    "Ingeniería inversa con REA a través de Eolfi (estático: nunca ejecuta el objetivo)":
        "Reverse engineering with REA through Eolfi (static: never runs the target)",
    "Automejora recursiva acotada: propuestas evaluadas que el titular aprueba o revierte":
        "Bounded recursive self-improvement: evaluated proposals the owner approves or reverts",
    "Telemetría local: tiempos y rendimiento por fase (no sale del equipo)":
        "Local telemetry: timings and performance per phase (never leaves the computer)",
    "Voz local: voz a texto y texto a voz sin que el audio salga del equipo":
        "Local voice: speech-to-text and text-to-speech without the audio leaving the computer",
    "Servidor MCP por stdio (Copilot en modo agente, Claude Code…)": "MCP server over stdio (Copilot agent mode, Claude Code…)",
    "Muestra o elige el motor local compartido: eolas-v1 (CeltIA, 11435) o eolas-v2 (Eolfi, 8090)":
        "Shows or chooses the shared local engine: eolas-v1 (CeltIA, 11435) or eolas-v2 (Eolfi, 8090)",
    "Arranca todo junto: Eolas local (CeltIA), el puente de chats web y el panel":
        "Starts everything together: local Eolas (CeltIA), the web chat bridge and the panel",
    "Servidor de desarrollo (API + panel web)": "Development server (API + web panel)",
    "Recalcula la cadena SHA-256 del registro": "Recomputes the log's SHA-256 chain",
    "Copia la cabeza de la cadena a un archivo externo": "Copies the head of the chain to an external file",
    "Muestra los últimos eventos": "Shows the latest events",
    "Comprueba estructura GGUF y SHA-256": "Checks GGUF structure and SHA-256",
    "Consulta sockets de un PID, sin iniciar el motor": "Queries the sockets of a PID without starting the engine",
    "Comprueba un hash contra un manifiesto autorizado": "Checks a hash against an authorized manifest",
    "G5: compara los modelos locales con lo publicado (abre la red con --red)":
        "G5: compares local models with the published ones (opens the network with --red)",
    "G5: descarga un GGUF fijado por commit y SHA-256 y lo audita": "G5: downloads a GGUF pinned by commit and SHA-256 and audits it",
    "Prepara una receta de cuantización; ejecutar exige opción y hashes":
        "Prepares a quantization recipe; running it requires an option and hashes",
    "Prepara un smoke de inferencia en CPU de una reconstrucción; ejecutar exige opción y hash":
        "Prepares a CPU inference smoke test of a reconstruction; running it requires an option and a hash",
    "Ejecuta un guion de observación y guarda la sesión": "Runs an observation script and saves the session",
    "Repite una sesión guardada desde su guion y marca lo no reproducible":
        "Replays a saved session from its script and flags what is not reproducible",
    "Compara dos sesiones (versiones o entornos): primer cambio observable":
        "Compares two sessions (versions or environments): first observable change",
    "Muestra una sesión guardada": "Shows a saved session",
    "Valida un guion sin ejecutar nada": "Validates a script without running anything",
    "Qué ejecutaría el guion, con qué permisos y qué datos se guardarían (no ejecuta)":
        "What the script would run, with which permissions and what data would be stored (runs nothing)",
    "Borra una sesión y sus evidencias derivadas (IRREVERSIBLE)": "Deletes a session and its derived evidence (IRREVERSIBLE)",
    "Construye y guarda una versión nueva si el contenido cambió": "Builds and saves a new version if the content changed",
    "Muestra la última versión (o --version N)": "Shows the latest version (or --version N)",
    "Casos de prueba derivados solo de requisitos observados": "Test cases derived only from observed requirements",
    "Contrato de implementación: qué es seguro, inferido o desconocido":
        "Implementation contract: what is certain, inferred or unknown",
    "Compara dos versiones de la especificación": "Compares two versions of the specification",
    "Revisión humana de un requisito (queda registrada en el caso)": "Human review of a requirement (recorded in the case)",
    "Lista los casos": "Lists the cases",
    "Crea un caso": "Creates a case",
    "Muestra el caso, objetivos, evidencias e incógnitas": "Shows the case, targets, evidence and unknowns",
    "Asocia un objetivo ya analizado (identidad y herramientas desde sus evidencias)":
        "Links an already analyzed target (identity and tools from its evidence)",
    "Informe HTML navegable del caso (o JSON)": "Browsable HTML report of the case (or JSON)",
    "Asocia un artefacto por SHA-256 (o subject de Eolfi)": "Links an artifact by SHA-256 (or Eolfi subject)",
    "Añade una observación/especificación/etc. desde JSON": "Adds an observation/specification/etc. from JSON",
    "Exporta caso, evidencias e incógnitas a JSON": "Exports the case, evidence and unknowns to JSON",
    "Importa un paquete completo de caso validado": "Imports a complete, validated case bundle",
    "Fuzzing de entradas sin tumbar el sistema": "Input fuzzing without bringing the system down",
    "Escaneo de inyección de prompts": "Prompt injection scan",
    "Estado del único llama-server administrado por Eolas": "Status of the single llama-server managed by Eolas",
    "Valida una reconstrucción y propone un perfil sin adoptarlo": "Validates a reconstruction and proposes a profile without adopting it",
    "Revalida un plan y añade el perfil sin activarlo": "Revalidates a plan and adds the profile without activating it",
    "Quita un perfil reconstruido gestionado, conservando el GGUF": "Removes a managed reconstructed profile, keeping the GGUF",
    "Propone el ganador de un banco reciente; no cambia nada por defecto":
        "Proposes the winner of a recent benchmark; changes nothing by default",
    "Arranca el perfil activo (o el indicado)": "Starts the active profile (or the given one)",
    "Detiene el perfil activo y arranca el otro": "Stops the active profile and starts the other one",
    "Detiene solo el llama-server que inició Eolas": "Stops only the llama-server that Eolas started",
    "Catálogo: etiqueta, si se puede usar, roles y admisión de cada perfil":
        "Catalogue: label, whether it can be used, roles and admission of each profile",
    "Da de alta un GGUF local como perfil nuevo (no lo activa)": "Registers a local GGUF as a new profile (does not activate it)",
    "Elige el perfil activo (sin arrancarlo); los nuevos deben estar admitidos":
        "Selects the active profile (without starting it); new ones must be admitted",
    "Asigna un perfil a un papel: rapido, completo, redactor, revisor…":
        "Assigns a profile to a role: rapido, completo, redactor, revisor…",
    "Ronda completa de un perfil (código y herramientas): decide su admisión. CARGA el modelo y necesita Docker":
        "Full round for one profile (code and tools): decides its admission. LOADS the model and needs Docker",
    "Revisa la cabecera del GGUF de un perfil (o una ruta) con REA": "Reviews the GGUF header of a profile (or a path) with REA",
    "Retira un perfil que no aprueba (conserva su GGUF)": "Retires a profile that does not pass (keeps its GGUF)",
    "Desinstala un motor: retira el perfil y borra su GGUF y sus lecciones":
        "Uninstalls an engine: retires the profile and deletes its GGUF and lessons",
    "Vuelve a ofrecer un perfil retirado": "Offers a retired profile again",
    "Activa o desactiva el almacenamiento local de feedback": "Turns local feedback storage on or off",
    "Guarda una valoración explícita localmente": "Stores an explicit rating locally",
    "Borra un registro local de feedback por id": "Deletes a local feedback record by id",
    "Exporta solo registros con consentimiento a JSONL": "Exports only consented records to JSONL",
    "Importa JSONL validado sin duplicar ids": "Imports validated JSONL without duplicating ids",
    "Prepara JSONL SFT/preferencias desde valoraciones humanas": "Prepares SFT/preference JSONL from human ratings",
    "Recomienda perfil por tarea usando valoraciones humanas": "Recommends a profile per task using human ratings",
    "Comprueba si hay checkpoint HF, dataset y dependencias para entrenar":
        "Checks whether there is an HF checkpoint, dataset and dependencies to train",
    "Entrena un adaptador QLoRA SFT aislado desde checkpoint/dataset locales":
        "Trains an isolated QLoRA SFT adapter from a local checkpoint/dataset",
    "Cabecera de un GGUF/safetensors y si la cuantización coincide": "Header of a GGUF/safetensors file and whether the quantization matches",
    "Explica un ejecutable: importaciones, cadenas y funciones clave (Ghidra)":
        "Explains an executable: imports, strings and key functions (Ghidra)",
    "Pseudocódigo, firma y llamadas de una función para reimplementarla":
        "Pseudocode, signature and calls of a function to reimplement it",
    "Librerías, firmas, recursos y dependencias Go/Rust de un binario":
        "Libraries, signatures, resources and Go/Rust dependencies of a binary",
    "Analiza una app JavaScript, Electron o web (carpeta o .asar) sin ejecutarla":
        "Analyzes a JavaScript, Electron or web app (folder or .asar) without running it",
    "Reconstruye fuentes legibles de un JavaScript minificado (Wakaru en WSL2)":
        "Rebuilds readable sources from minified JavaScript (Wakaru in WSL2)",
    "De una captura de red (.pcap/.pcapng) a un borrador de API (OpenAPI si hay tshark en WSL)":
        "From a network capture (.pcap/.pcapng) to an API draft (OpenAPI if tshark is in WSL)",
    "Desglose de una imagen de firmware: firmas, regiones y huecos (Binwalk 3.1.0 en WSL2)":
        "Breakdown of a firmware image: signatures, regions and gaps (Binwalk 3.1.0 in WSL2)",
    "De una captura web (.har) a un entorno para agentes de REA (AgentEnv); ensayo salvo --escribir":
        "From a web capture (.har) to an REA agent environment (AgentEnv); dry run unless --escribir",
    "Mapa de una app Android (.apk): permisos, componentes exportados y estructura (JADX)":
        "Map of an Android app (.apk): permissions, exported components and structure (JADX)",
    "Grafo de llamadas de una función (Ghidra), con nombres y en Mermaid":
        "Call graph of a function (Ghidra), with names and in Mermaid",
    "Qué hay en un ensamblado .NET: identidad, referencias, tipos, cadenas y P/Invoke (REA de WSL2)":
        "What is in a .NET assembly: identity, references, types, strings and P/Invoke (WSL2 REA)",
    "Clases y métodos de un APK descompilados con JADX, sin ejecutar la app":
        "Classes and methods of an APK decompiled with JADX, without running the app",
    "Qué hay en una app Flutter: motor, snapshot Dart y paquetes, sin ejecutarla":
        "What is in a Flutter app: engine, Dart snapshot and packages, without running it",
    "Mapa de una app de Apple (.app, .zip, .ipa o .dmg): bundles, ejecutables e Info.plist, sin ejecutarla":
        "Map of an Apple app (.app, .zip, .ipa or .dmg): bundles, executables and Info.plist, without running it",
    "Mapa del hardware de un devicetree (.dtb): placa, CPU, memoria y dispositivos":
        "Hardware map of a devicetree (.dtb): board, CPU, memory and devices",
    "Tipos Swift y clases Objective-C de una app de Apple (Ghidra en el REA de WSL), sin macOS":
        "Swift types and Objective-C classes of an Apple app (Ghidra in the WSL REA), without macOS",
    "Ejecutable Go: versión de Go, módulo, dependencias y ajustes de compilación, sin ejecutarlo":
        "Go executable: Go version, module, dependencies and build settings, without running it",
    "Ejecutable Rust con cargo-auditable: crates, raíz y dependencias directas, sin ejecutarlo":
        "Rust executable with cargo-auditable: crates, root and direct dependencies, without running it",
    "Decodifica una grabación de analizador lógico (.sr, VCD, CSV) con sigrok en el REA de WSL":
        "Decodes a logic analyzer recording (.sr, VCD, CSV) with sigrok in the WSL REA",
    "Decodificadores de sigrok instalados, o la ayuda de uno (--ayuda ID)":
        "Installed sigrok decoders, or the help of one (--ayuda ID)",
    "Qué cambió entre dos versiones, con el veredicto verificable de REA":
        "What changed between two versions, with REA's verifiable verdict",
    "Módulo WebAssembly sin ejecutarlo: validez, secciones, importaciones y exportaciones (WABT 1.0.42)":
        "WebAssembly module without running it: validity, sections, imports and exports (WABT 1.0.42)",
    "Observaciones, casos de regresión, propuestas, reglas y registro":
        "Observations, regression cases, proposals, rules and log",
    "Comprueba la cadena SHA-256 del registro": "Checks the log's SHA-256 chain",
    "Propone cambios a partir de los síntomas repetidos": "Proposes changes from repeated symptoms",
    "Línea base contra candidata con un banco de pruebas (CARGA el modelo local)":
        "Baseline versus candidate with a test bench (LOADS the local model)",
    "Prueba A/A del evaluador con el banco real (CARGA el modelo local)":
        "A/A test of the evaluator with the real bench (LOADS the local model)",
    "Aplica una propuesta evaluada con éxito": "Applies a successfully evaluated proposal",
    "Descarta una propuesta": "Discards a proposal",
    "Devuelve una propuesta aplicada a su valor anterior": "Returns an applied proposal to its previous value",
    "Motores disponibles, idioma y voces": "Available engines, language and voices",
    "Voz a texto de un WAV (PCM de 16 bits)": "Speech-to-text of a WAV (16-bit PCM)",
    "Texto a voz: escribe un WAV": "Text-to-speech: writes a WAV",
    "Elige motor, idioma o voz": "Chooses engine, language or voice",
    # Comandos de las ramas de C2 y B8 (luis/c2-instalador, luis/b8-firma), cubiertos antes de fusionarse.
    "Navegador, Playwright y axe propios de Eolfi para el juez funcional (en ~/.eolfi/navegador)":
        "Eolfi's own browser, Playwright and axe for the functional judge (in ~/.eolfi/navegador)",
    "Lanzador de «eolfi up» en el escritorio o el menú (vista previa salvo con --aplicar)":
        "Launcher for \"eolfi up\" on the desktop or the menu (preview unless --aplicar)",
    "Crea una clave de firma de 32 bytes (guárdala fuera del equipo)": "Creates a 32-byte signing key (keep it off the computer)",
    "Firma con HMAC-SHA256 la cabeza de la cadena": "Signs the head of the chain with HMAC-SHA256",
}
