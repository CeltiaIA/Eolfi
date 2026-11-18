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


def _plantillas(catalogo: dict[str, str]) -> list[tuple[re.Pattern[str], str]]:
    """Claves con «{}» del catálogo como expresiones; la más concreta (más texto fijo) primero."""
    claves = sorted((k for k in catalogo if "{}" in k), key=lambda k: -len(k.replace("{}", "")))
    return [(re.compile("^" + "(.+?)".join(map(re.escape, k.split("{}"))) + "$", re.S), catalogo[k]) for k in claves]


_CACHE_PLANTILLAS: dict[int, list[tuple[re.Pattern[str], str]]] = {}


def traducir(texto: str, idioma: str, catalogo: dict[str, str]) -> str:
    """Traducción exacta o, si no la hay, por plantilla: una clave con «{}» («modo inválido: {}») reconoce el
    mensaje con su parte variable, que pasa tal cual (rutas, nombres) o traducida si está en el catálogo (exacta o
    por plantilla; el panel, i18n.js, solo traduce huecos exactos). En la traducción, «{}» toma los huecos en orden
    y «{0}», «{1}»… por posición."""
    if idioma != "en" or not isinstance(texto, str):
        return texto
    if texto in catalogo:
        return catalogo[texto]
    plantillas = _CACHE_PLANTILLAS.setdefault(id(catalogo), _plantillas(catalogo))
    for patron, trad in plantillas:
        m = patron.match(texto)
        if m:
            # Cada hueco se traduce igual (exacto o por plantilla): «→ {}» con «sintaxis JS del sitio ({})» dentro.
            lista = [traducir(h, idioma, catalogo) if h != texto else h for h in m.groups()]
            huecos = iter(lista)
            return re.sub(r"\{(\d*)\}", lambda g: next(huecos, "") if g.group(1) == "" else lista[int(g.group(1))], trad)
    return texto


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
    # D1 en el panel (18/11/2026): trabajo «sync»
    "{} no tiene eolfi.spec.json: no es un proyecto creado con «eolfi create»":
        "{} has no eolfi.spec.json: it is not a project created with \"eolfi create\"",
    "eolfi.spec.json ilegible: {}": "unreadable eolfi.spec.json: {}",
    "Sincronización aplicada pero NO VERIFICADA: {}; copia de lo anterior en {}":
        "Sync applied but NOT VERIFIED: {}; copy of the previous version in {}",
    "la verificación falló": "verification failed",
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
    # ── Mensajes con partes variables (plantillas con «{}», C1 18/11): rutas, nombres y valores pasan tal cual;
    # una parte que sea entera un texto de este catálogo («carpeta destino», «aprobado») se traduce.
    "kind debe ser uno de {} y body un objeto": "kind must be one of {} and body an object",
    "Autofix sin estado verde: {}; archivos restaurados": "Autofix without a green state: {}; files restored",
    "Creación fallida: la verificación del proyecto no se superó y autofix no lo corrigió ({})":
        "Creation failed: the project verification did not pass and autofix did not fix it ({})",
    "attachments: hasta {} archivos": "attachments: up to {} files",
    "analyze.kind debe ser uno de {} con su destino": "analyze.kind must be one of {} with its target",
    "el encargo ya está {}": "the task is already {}",
    "{} fuera de las carpetas permitidas: {} (permitidas: {})": "{} outside the allowed folders: {} (allowed: {})",
    "No es una carpeta: {}": "Not a folder: {}",
    "no es una carpeta: {}": "not a folder: {}",
    "Sin permiso para leer {}": "No permission to read {}",
    "status inválido: {}": "invalid status: {}",
    "modo inválido: {}": "invalid mode: {}",
    "no existe el archivo ni la carpeta: {}": "neither the file nor the folder exists: {}",
    "proveedores desconocidos: {}": "unknown providers: {}",
    "objetivo no encontrado o ambiguo: {}": "target not found or ambiguous: {}",
    "Host no permitido: {}": "Host not allowed: {}",
    "Content-Length inválido o mayor que {} bytes": "Invalid Content-Length or larger than {} bytes",
    "JSON inválido: {}": "invalid JSON: {}",
    "petición inválida: {}": "invalid request: {}",
    # Partes que se traducen dentro de las plantillas.
    "ruta": "path",
    "carpeta": "folder",
    "carpeta destino": "destination folder",
    "carpeta del proyecto": "project folder",
    "fuente": "source",
    "archivo": "file",
    "guion": "script",
    "objetivo": "target",
    "pendiente": "pending",
    "aprobado": "approved",
    "rechazado": "rejected",
    "en_curso": "in progress",
    "hecho": "done",
    "fallido": "failed",
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
    "Juego o app de Unity con IL2CPP: ensamblados, tipos y métodos con su dirección (global-metadata.dat y binario "
    "nativo), sin ejecutarlo":
        "Unity game or app built with IL2CPP: assemblies, types and methods with their address (global-metadata.dat and "
        "native binary), without running it",
    "Qué cambió entre dos versiones, con el veredicto verificable de REA":
        "What changed between two versions, with REA's verifiable verdict",
    "Comprueba los SHA-256 de un paquete hecho con --paquete (sin REA)":
        "Checks the SHA-256 hashes of a package made with --paquete (without REA)",
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
    "Graba del micrófono del equipo y lo transcribe (nada se guarda)":
        "Records from this computer's microphone and transcribes it (nothing is stored)",
    "Duración de la grabación (1-30 s)": "Recording length (1-30 s)",
    "Elige motor, idioma o voz": "Chooses engine, language or voice",
    # Comandos de las ramas de C2 y B8 (luis/c2-instalador, luis/b8-firma), cubiertos antes de fusionarse.
    "Navegador, Playwright y axe propios de Eolfi para el juez funcional (en ~/.eolfi/navegador)":
        "Eolfi's own browser, Playwright and axe for the functional judge (in ~/.eolfi/navegador)",
    "Lanzador de «eolfi up» en el escritorio o el menú (vista previa salvo con --aplicar)":
        "Launcher for \"eolfi up\" on the desktop or the menu (preview unless --aplicar)",
    "Crea una clave de firma de 32 bytes (guárdala fuera del equipo)": "Creates a 32-byte signing key (keep it off the computer)",
    "Firma con HMAC-SHA256 la cabeza de la cadena": "Signs the head of the chain with HMAC-SHA256",
    # ── Ayudas de los argumentos (C1, 18/11/2026) ──
    "Vuelve a analizar las fuentes de un proyecto generado y propone los cambios con fusión a tres bandas (tus cambios se conservan)":
        "Re-analyzes a generated project's sources and proposes the changes with a three-way merge (your changes are kept)",
    "Escribe los cambios (con copia de lo que toca en .eolfi-sync/) y verifica el resultado":
        "Writes the changes (with a copy of what it touches in .eolfi-sync/) and verifies the result",
    "Con --aplicar: no verificar (el resultado queda NO VERIFICADO)":
        "With --aplicar: do not verify (the result stays NOT VERIFIED)",
    ".app, .zip, .ipa o ejecutable Mach-O": ".app, .zip, .ipa or Mach-O executable",
    "A/A simulada con esa desviación típica, sin cargar nada":
        "Simulated A/A with that standard deviation, without loading anything",
    "ABI del snapshot que se examina (por defecto la que elija REA)":
        "ABI of the snapshot to examine (default: the one REA chooses)",
    "Abre el perfil de Eolfi en un navegador normal, sin control remoto, para iniciar sesión en Google/Gemini, DeepSeek y Meta (Google bloquea el acceso en navegadores controlados)":
        "Opens Eolfi's profile in a normal browser, without remote control, to sign in to Google/Gemini, DeepSeek and Meta (Google blocks access from controlled browsers)",
    "Abre las páginas en Chrome sin interfaz (SPA) y rastrea el mismo origen":
        "Opens the pages in headless Chrome (SPA) and crawls the same origin",
    "Archivo WAV de salida": "Output WAV file",
    "Archivo de anclas externo: comprueba también que cada ancla sigue en la cadena":
        "External anchors file: also checks that each anchor is still in the chain",
    "Archivo de clave (o EOLFI_ACCIONES_CLAVE)": "Key file (or EOLFI_ACCIONES_CLAVE)",
    "Archivo de clave (o EOLFI_ACCIONES_CLAVE): comprueba también las firmas":
        "Key file (or EOLFI_ACCIONES_CLAVE): also checks the signatures",
    "Archivo de salida (por defecto, la salida estándar)": "Output file (default: standard output)",
    "Archivo fuera del alcance de quien escribe el registro": "File out of reach of whoever writes the log",
    "Archivo local cuyo contenido escribir (write)": "Local file whose content to write (write)",
    "Archivo nuevo, fuera del alcance de quien escribe el registro": "New file, out of reach of whoever writes the log",
    "Archivo o carpeta de entradas": "Inputs file or folder",
    "Aspecto tolerado (diferencia no funcional declarada), p. ej. «*.texto visible»":
        "Tolerated aspect (declared non-functional difference), e.g. \"*.texto visible\"",
    "Aspecto tolerado declarado (patrón, p. ej. «procesos hijos» o «*.accesibilidad»)":
        "Declared tolerated aspect (pattern, e.g. \"procesos hijos\" or \"*.accesibilidad\")",
    "Autoriza la consulta a la API pública de Hugging Face": "Authorizes querying the public Hugging Face API",
    "Autoriza la descarga": "Authorizes the download",
    "Autoriza uso de GPU y escritura de un adaptador nuevo": "Authorizes GPU use and writing a new adapter",
    "Añade N entradas mutadas al corpus": "Adds N mutated inputs to the corpus",
    "Añade una instantánea de sockets de este PID (Windows)": "Adds a socket snapshot of this PID (Windows)",
    "Base generada (por defecto: la CLI si se observó; si no, la API HTTP observada)":
        "Generated base (default: the CLI if it was observed; otherwise the observed HTTP API)",
    "Biblioteca Alejandría local (también EOLFI_LIBRARY)": "Local Alejandría library (also EOLFI_LIBRARY)",
    "Bytes (omitir si se desconoce)": "Bytes (omit if unknown)",
    "Carpeta creada por `modelos reconstruir`, con smoke superado":
        "Folder created by `modelos reconstruir`, with a passed smoke test",
    "Carpeta de destino; nunca se sobrescribe": "Destination folder; never overwritten",
    "Carpeta de la biblioteca (EOLFI_LIBRARY, o Alejandria en la carpeta personal o en D:)":
        "Library folder (EOLFI_LIBRARY, or Alejandria in the home folder or on D:)",
    "Carpeta de salida de `modelos reconstruir`, con receta.json y modelo.gguf":
        "Output folder of `modelos reconstruir`, with receta.json and modelo.gguf",
    "Carpeta de un proyecto creado con 'eolfi create'": "Folder of a project created with 'eolfi create'",
    "Carpeta del proyecto nuevo (vacía o inexistente)": "Folder for the new project (empty or nonexistent)",
    "Carpeta destino (obligatoria salvo con --model)": "Destination folder (required unless --model)",
    "Carpeta donde guardar los archivos subidos": "Folder where uploaded files are stored",
    "Carpeta local o URL git": "Local folder or git URL",
    "Carpeta nueva; nunca sobrescribe una anterior": "New folder; never overwrites a previous one",
    "Carpeta permitida para rutas locales (repetible). Sin --root, sin restricción en local; en modo remoto, solo samples/ y generated/":
        "Allowed folder for local paths (repeatable). Without --root, no restriction locally; in remote mode, only samples/ and generated/",
    "Carpeta permitida para rutas locales (repetible; también EOLFI_ROOTS)":
        "Allowed folder for local paths (repeatable; also EOLFI_ROOTS)",
    "Carpeta que abrir en VS Code (opcional)": "Folder to open in VS Code (optional)",
    "Comando candidato (reimplementación)": "Candidate command (reimplementation)",
    "Comando de VS Code (command) o herramienta (tool)": "VS Code command (command) or tool (tool)",
    "Comando de referencia; {input} = ruta de la entrada (si no, stdin)":
        "Reference command; {input} = path of the input (otherwise stdin)",
    "Commit completo revisado con «modelos actualizar»": "Full commit reviewed with \"modelos actualizar\"",
    "Compara las herramientas actuales con un archivo de bloqueo (código 6 si cambiaron)":
        "Compares the current tools with a lock file (code 6 if they changed)",
    "Compara también stderr": "Also compares stderr",
    "Comprobar; Eolfi nunca se actualiza solo": "Check; Eolfi never updates itself",
    "Comprueba también la cadena del RSI y que cada evento reflejado coincide":
        "Also checks the RSI chain and that each mirrored event matches",
    "Con --render: páginas como máximo (1-50)": "With --render: maximum pages (1-50)",
    "Con --render: saltos de enlace desde la inicial (0-5)": "With --render: link hops from the first page (0-5)",
    "Con --render: pulsa hasta N controles sin efectos por página (0-30); nunca envía formularios y solo deja salir "
    "peticiones GET":
        "With --render: presses up to N side-effect-free controls per page (0-30); never submits forms and only "
        "lets GET requests out",
    "Con estado: recalcula el SHA-256 del ejecutable": "With estado: recomputes the executable's SHA-256",
    "Confirmo el borrado irreversible": "I confirm the irreversible deletion",
    "Confirmo la autorización para ejecutar (obligatorio)": "I confirm the authorization to run (required)",
    "Confirmo la autorización para ejecutar el candidato": "I confirm the authorization to run the candidate",
    "Confirmo que estoy autorizado a ejecutar este objetivo (obligatorio)":
        "I confirm I am authorized to run this target (required)",
    "Confirmo que estoy autorizado a ejecutar referencia y candidato (obligatorio)":
        "I confirm I am authorized to run reference and candidate (required)",
    "Consiento guardar prompt y respuesta saneados": "I consent to storing the sanitized prompt and answer",
    "Crea el acceso directo": "Creates the shortcut",
    "Criterios del juez funcional (JSON): la app se prueba en Chrome y debe cumplirlos todos":
        "Functional judge criteria (JSON): the app is tested in Chrome and must meet them all",
    "Descarga también assets de otros dominios": "Also downloads assets from other domains",
    "Descompilador: ghidra (REA de Windows) o kuna (REA de WSL2; solo ELF y Mach-O)":
        "Decompiler: ghidra (Windows REA) or kuna (WSL2 REA; ELF and Mach-O only)",
    "Descripción para que la IA implemente la lógica de negocio":
        "Description for the AI to implement the business logic",
    "Dominio/tarea, p. ej. 'python' o 'resumen'": "Domain/task, e.g. 'python' or 'resumen'",
    "Dónde clonar los repos remotos": "Where to clone remote repos",
    "Ejecuta el cuantizador; requiere los hashes de entrada y paquete":
        "Runs the quantizer; requires the input and package hashes",
    "Ejecuta la referencia dos veces para detectar no determinismo":
        "Runs the reference twice to detect nondeterminism",
    "El modelo piensa en un bloque aparte (formato deepseek de llama-server)":
        "The model thinks in a separate block (llama-server's deepseek format)",
    "Escribe aunque la carpeta no esté vacía": "Writes even if the folder is not empty",
    "Escribe el perfil; sin esta opción solo muestra la vista previa":
        "Writes the profile; without this option it only shows the preview",
    "Escribe el resultado en este archivo": "Writes the result to this file",
    "Exige axe (WCAG A/AA) en tema claro y oscuro también en destinos que el juez no cubre (por defecto ya se mide en static, react, vue y svelte)":
        "Requires axe (WCAG A/AA) in light and dark themes also on targets the judge does not cover (by default it is already measured on static, react, vue and svelte)",
    "Fija rutas, versiones y SHA-256 de las herramientas en este archivo de bloqueo":
        "Pins the tools' paths, versions and SHA-256 in this lock file",
    "GameAssembly.dll/.so/.dylib, libil2cpp.so o UnityFramework de 64 bits (por defecto lo busca junto a los metadatos)":
        "64-bit GameAssembly.dll/.so/.dylib, libil2cpp.so or UnityFramework (by default it is looked for next to the metadata)",
    "Guarda una copia de estudio de HTML/CSS/JS en esta carpeta":
        "Saves a study copy of the HTML/CSS/JS in this folder",
    "Guion JSON (eolfi_observation_script: 1)": "JSON script (eolfi_observation_script: 1)",
    "Idioma de la interfaz, las pruebas y los comentarios del proyecto generado (README y receta de despliegue incluidos)":
        "Language of the generated project's interface, tests and comments (README and deployment recipe included)",
    "Incluye Ghidra headless (lento)": "Includes headless Ghidra (slow)",
    "Instala la extensión de forma permanente (por defecto se carga solo en una ventana de desarrollo)":
        "Installs the extension permanently (by default it only loads in a development window)",
    "JSON con argumentos de la herramienta (tool) o lista de argumentos (command)":
        "JSON with the tool's arguments (tool) or a list of arguments (command)",
    "JSON eolfi.modelos.fuentes/v1 con repo, archivo y SHA-256 local":
        "eolfi.modelos.fuentes/v1 JSON with repo, file and local SHA-256",
    "JSON producido y revisado por `eolas-v2 plan`": "JSON produced and reviewed by `eolas-v2 plan`",
    "JavaScript que carga el módulo (repetible): dónde lo nombra, sin ejecutarlo":
        "JavaScript that loads the module (repeatable): where it names it, without running it",
    "Mejora con razón verificable (seguridad-nosniff, seguridad-limite-cuerpo[=BYTES], compatibilidad-utf8); se rechaza si rompe un requisito observado o no se puede comprobar":
        "Improvement with a verifiable reason (seguridad-nosniff, seguridad-limite-cuerpo[=BYTES], compatibilidad-utf8); rejected if it breaks an observed requirement or cannot be checked",
    "Modelo del proveedor (por defecto, el de su preajuste)": "Provider model (default: its preset's)",
    "Motivo que verá el usuario al confirmar (write)": "Reason the user will see when confirming (write)",
    "Muestra los recuentos sin escribir nada": "Shows the counts without writing anything",
    "Muestra qué se importaría sin copiar nada": "Shows what would be imported without copying anything",
    "Navegador del puente (como en «eolfi bridge»)": "Bridge browser (as in \"eolfi bridge\")",
    "Navegador real: chrome, edge, brave, opera, vivaldi, chromium o ruta al ejecutable (por defecto el primero instalado)":
        "Real browser: chrome, edge, brave, opera, vivaldi, chromium or path to the executable (default: the first one installed)",
    "Nivel de la prueba exacta de signos": "Level of the exact sign test",
    "No abre el panel en el navegador": "Does not open the panel in the browser",
    "No arranca Eolas": "Does not start Eolas",
    "No arranca el puente de chats web": "Does not start the web chat bridge",
    "No borra la carpeta temporal de la sesión": "Does not delete the session's temporary folder",
    "No mide la accesibilidad con axe al verificar": "Does not measure accessibility with axe when verifying",
    "No respetar robots.txt (solo con permiso)": "Do not respect robots.txt (only with permission)",
    "Nombre nuevo (minúsculas, cifras y guion bajo)": "New name (lowercase letters, digits and underscore)",
    "Nombre nuevo del perfil (minúsculas y guion bajo)": "New profile name (lowercase letters and underscore)",
    "Nombre visible, p. ej. «Qwen3 14B Q4»": "Display name, e.g. \"Qwen3 14B Q4\"",
    "Nombres o direcciones separados por comas; 'entry' = punto de entrada":
        "Comma-separated names or addresses; 'entry' = entry point",
    "Objetivo: sha256, prefijo, nombre o ruta ya analizada": "Target: sha256, prefix, name or an already analyzed path",
    "Objeto JSON o @ruta a un archivo JSON": "JSON object or @path to a JSON file",
    "Omite la lista de evidence_ids": "Omits the list of evidence_ids",
    "Otra carpeta para el lanzador (en lugar del escritorio o el menú)":
        "Another folder for the launcher (instead of the desktop or the menu)",
    "Pares base/candidata (mínimo 5)": "Base/candidate pairs (minimum 5)",
    "Permite consultar api.github.com (sin credenciales)": "Allows querying api.github.com (no credentials)",
    "Sirve por HTTPS con este certificado (el móvil solo deja usar el micrófono con HTTPS)":
        "Serve over HTTPS with this certificate (phones only allow the microphone over HTTPS)",
    "Clave privada del certificado de --cert": "Private key for the --cert certificate",
    "Permite escuchar fuera de localhost": "Allows listening outside localhost",
    "Persistencia de los backends FastAPI/Express (sqlite: sin dependencias nuevas)":
        "Persistence of the FastAPI/Express backends (sqlite: no new dependencies)",
    "Pide antes a Eolas (11435) que descargue su modelo de la GPU":
        "First asks Eolas (11435) to unload its model from the GPU",
    "Por defecto según la extensión: .sarif → sarif, .stix.json → stix, si no json":
        "By default from the extension: .sarif → sarif, .stix.json → stix, otherwise json",
    "Por ejemplo es-ES": "For example es-ES",
    "Procedencia declarada de la entrada (se guarda en el caso)":
        "Declared provenance of the input (stored in the case)",
    "Procedencia declarada del artefacto": "Declared provenance of the artifact",
    "Proveedor de IA (por defecto, el motor local elegido con «eolfi motor-local»)":
        "AI provider (default: the local engine chosen with \"eolfi motor-local\")",
    "Proveedor de create --ai: eolas o eolas-v2": "Provider for create --ai: eolas or eolas-v2",
    "Puerto del panel que abre el lanzador": "Port of the panel the launcher opens",
    "Quién decide (queda en el registro)": "Who decides (recorded in the log)",
    "Qué quieres que implemente": "What you want it to implement",
    "Ratio mínimo de equivalencia (0-1)": "Minimum equivalence ratio (0-1)",
    "Registra artefactos y resultado en este caso (eolfi case create …)":
        "Records artifacts and result in this case (eolfi case create …)",
    "Registra el resultado en este caso (artefacto, evidencia e incógnitas)":
        "Records the result in this case (artifact, evidence and unknowns)",
    "Guarda en esta carpeta nueva el paquete completo: evidencias de REA, resultado, caso y manifiesto con SHA-256":
        "Saves the full package in this new folder: REA evidence, result, case and a manifest with SHA-256",
    "Registro, inicio de sesión y token para las escrituras (FastAPI/Express)":
        "Sign-up, sign-in and a token for writes (FastAPI/Express)",
    "Reglas de conversación de Mistral Instruct (sin mensaje de sistema propio)":
        "Mistral Instruct conversation rules (no system message of its own)",
    "Reinicia al cambiar el código de eolfi/": "Restarts when the eolfi/ code changes",
    "Reinicia el panel al cambiar el código de eolfi/": "Restarts the panel when the eolfi/ code changes",
    "Repite los guiones del caso con este candidato y compara con el original (EJECUTA)":
        "Replays the case's scripts with this candidate and compares with the original (RUNS IT)",
    "Repositorio CeltIA con launch-eolas.ps1 (también CELTIAIA_HOME)":
        "CeltIA repository with launch-eolas.ps1 (also CELTIAIA_HOME)",
    "Retira el acceso directo de Eolfi": "Removes Eolfi's shortcut",
    "Ruta de un artefacto analizado, para enlazarlo en SARIF (repetible)":
        "Path of an analyzed artifact, to link it in SARIF (repeatable)",
    "Ruta del .gguf (la primera parte si viene troceado)": "Path of the .gguf (the first part if it is split)",
    "Ruta del ejecutable local llama-cli": "Path of the local llama-cli executable",
    "Ruta del ejecutable local llama-quantize": "Path of the local llama-quantize executable",
    "Ruta del paquete playwright-core para pasos browser": "Path of the playwright-core package for browser steps",
    "SHA-256 publicado y revisado": "Published and reviewed SHA-256",
    "SHA-256 revisado del GGUF (opcional)": "Reviewed SHA-256 of the GGUF (optional)",
    "SHA-256 revisado del modelo": "Reviewed SHA-256 of the model",
    "Sale con código 1 si hay incógnitas abiertas de esa gravedad o mayor (para CI)":
        "Exits with code 1 if there are open unknowns of that severity or higher (for CI)",
    "Selecciona el perfil recomendado como activo": "Selects the recommended profile as active",
    "Si la verificación falla, no pedir a la IA que corrija los errores (autofix)":
        "If verification fails, do not ask the AI to fix the errors (autofix)",
    "Solo esta fuente": "Only this source",
    "Solo instala Electron en el puente": "Only installs Electron in the bridge",
    "Solo muestra el modelo de comportamiento (no genera)": "Only shows the behavior model (does not generate)",
    "Solo proveedores stdlib (sin herramientas externas)": "Stdlib providers only (no external tools)",
    "Tamaño publicado: se exige igual y se comprueba el espacio libre":
        "Published size: it must match and free space is checked",
    "Texto que buscar (find)": "Text to search for (find)",
    "URL del servidor (p. ej. Eolas en otro puerto)": "Server URL (e.g. Eolas on another port)",
    "URL http(s), archivo .html o carpeta de sitio estático": "http(s) URL, .html file or static site folder",
    "URL web, URL git, carpeta, archivo u objetivo ya analizado (repetible)":
        "Web URL, git URL, folder, file or already analyzed target (repeatable)",
    "Variable {var:NOMBRE}": "Variable {var:NOMBRE}",
    "Variantes deterministas de las entradas: ejecuta original y candidato y reduce lo que falla":
        "Deterministic variants of the inputs: runs original and candidate and reduces what fails",
    "Vuelve a analizar fuentes ya conocidas": "Re-analyzes already known sources",
    "browser = navegador real (recomendado: Google bloquea el inicio de sesión en Electron)":
        "browser = real browser (recommended: Google blocks sign-in in Electron)",
    "canales, opciones y anotaciones de un decodificador": "a decoder's channels, options and annotations",
    "carpeta de la compilación, .apk, .ipa, .zip o global-metadata.dat":
        "build folder, .apk, .ipa, .zip or global-metadata.dat",
    "carpeta nueva (ruta absoluta) donde escribir el paquete":
        "new folder (absolute path) where the package is written",
    "carpeta nueva o vacía donde guardar los módulos recuperados":
        "new or empty folder where the recovered modules are saved",
    "clases de anotación, p. ej. uart=rx-data": "annotation classes, e.g. uart=rx-data",
    "eolas-v1 | eolas-v2 (sin valor, muestra el actual)":
        "eolas-v1 | eolas-v2 (without a value, shows the current one)",
    "escribe el paquete; sin esto solo informa de lo que contendría":
        "writes the package; without this it only reports what it would contain",
    "estado (por defecto) o instalar (descarga unos 100 MB de npm y cdn.playwright.dev)":
        "estado (default) or instalar (downloads about 100 MB from npm and cdn.playwright.dev)",
    "extrae el contenido con Unblob 26.6.4 en esta carpeta nueva (sin montar ni ejecutar nada)":
        "extracts the content with Unblob 26.6.4 into this new folder (without mounting or running anything)",
    "formato de entrada de sigrok (por defecto lo detecta)": "sigrok input format (detected by default)",
    "genera además un cliente Python (solo biblioteca estándar) con las operaciones observadas; no sobrescribe":
        "also generates a Python client (standard library only) with the observed operations; does not overwrite",
    "máximo de componentes y bibliotecas listados (40)": "maximum components and libraries listed (40)",
    "máximo de dependencias listadas (60)": "maximum dependencies listed (60)",
    "máximo de elementos por lista (30)": "maximum items per list (30)",
    "máximo de elementos por lista (40)": "maximum items per list (40)",
    "máximo de elementos por lista (60)": "maximum items per list (60)",
    "máximo de la muestra (40)": "maximum sample size (40)",
    "máximo de nodos (2-300, 60 por defecto)": "maximum nodes (2-300, 60 by default)",
    "máximo de paquetes listados (60)": "maximum packages listed (60)",
    "método que se descompila": "method to decompile",
    "niveles (1-10, 3 por defecto)": "levels (1-10, 3 by default)",
    "nombre (p. ej. entry) o dirección (0x140001cb0)": "name (e.g. entry) or address (0x140001cb0)",
    "nombre completo de la clase o un trozo (distingue mayúsculas)": "full class name or a fragment (case-sensitive)",
    "nombre del entorno (obligatorio si el origen es localhost o una IP)":
        "environment name (required if the origin is localhost or an IP)",
    "nombre exacto de un tipo: sus métodos con la RVA": "exact name of a type: its methods with the RVA",
    "nombre o dirección (p. ej. entry o 0x140001010)": "name or address (e.g. entry or 0x140001010)",
    "otra versión del módulo: compara sus importaciones y exportaciones":
        "another version of the module: compares their imports and exports",
    "perfil Eolas V2 o ruta a un .gguf/.safetensors": "Eolas V2 profile or path to a .gguf/.safetensors",
    "pila de sigrok, p. ej. uart:rx=TX:baudrate=9600 o i2c:scl=scl:sda=sda,edid":
        "sigrok stack, e.g. uart:rx=TX:baudrate=9600 or i2c:scl=scl:sda=sda,edid",
    "porción del ejecutable universal (arm64 por defecto)": "slice of the universal executable (arm64 by default)",
    "profundidad máxima de extracción (con --extraer)": "maximum extraction depth (with --extraer)",
    "propietario/nombre (por defecto CeltiaIA/Eolfi o EOLFI_UPDATE_REPO)":
        "owner/name (default CeltiaIA/Eolfi or EOLFI_UPDATE_REPO)",
    "quién la llama, en vez de a quién llama": "who calls it, instead of what it calls",
    "ruta .json nueva para el volcado completo (tipos, métodos, cadenas, P/Invoke)":
        "new .json path for the full dump (types, methods, strings, P/Invoke)",
    "sha256, prefijo, nombre o ruta ya analizada": "sha256, prefix, name or already analyzed path",
    "texto en la ruta o en compatible para acotar los dispositivos":
        "text in the path or in compatible to narrow the devices",
    "texto que buscar en el identificador o el nombre": "text to search for in the identifier or the name",
    "vincula VS Code con tu Eolfi sin mostrar ningún código (abre un enlace vscode://)":
        "links VS Code with your Eolfi without showing any code (opens a vscode:// link)",
    "índice de la sobrecarga si el método tiene varias": "overload index if the method has several",
}


# ── Avisos de la CLI por stderr (C1, 18/11/2026) ──────────────────────────────────────────────────────────────────
# Mensajes de progreso y avisos que la CLI escribe por stderr: los de cli.py y los de los flujos que reciben
# `progress` (create, web, repo, verify, autofix/assist). Con «{}» la parte variable pasa tal cual. Lo que viene de
# una excepción o de una herramienta externa sigue en su idioma.
AVISOS_EN: dict[str, str] = {
    "eolfi: --key necesita --cert": "eolfi: --key requires --cert",
    "eolfi: no se pudo cargar el certificado ({})": "eolfi: could not load the certificate ({})",
    # cli.py
    "Eolfi: --verify está obsoleta y no hace nada (la verificación siempre es obligatoria); se retirará en una "
    "versión posterior.":
        "Eolfi: --verify is obsolete and does nothing (verification is always required); it will be removed in a "
        "later version.",
    "(RSI: no se pudo anotar la observación: {})": "(RSI: the observation could not be recorded: {})",
    "eolfi llama: «start» está retirado: dejaba un segundo modelo en la GPU (puerto 8090) junto al de Eolas. Usa Eolas "
    "(proveedor eolas) o «eolfi eolas-v2 start». «eolfi llama stop» sigue disponible para parar uno antiguo.":
        "eolfi llama: \"start\" is retired: it left a second model on the GPU (port 8090) next to Eolas's. Use Eolas "
        "(provider eolas) or \"eolfi eolas-v2 start\". \"eolfi llama stop\" is still available to stop an old one.",
    "REA de WSL2 no instalado: ejecuta tools/instalar-rea-wsl.sh dentro de Ubuntu":
        "WSL2 REA not installed: run tools/instalar-rea-wsl.sh inside Ubuntu",
    "Kuna no instalado en WSL2: vuelve a ejecutar tools/instalar-rea-wsl.sh dentro de Ubuntu (REA solo admite Kuna en "
    "Linux y macOS)":
        "Kuna not installed in WSL2: run tools/instalar-rea-wsl.sh again inside Ubuntu (REA only supports Kuna on "
        "Linux and macOS)",
    "Unblob 26.6.4 no instalado en WSL2: ejecuta tools/instalar-unblob-wsl.sh dentro de Ubuntu":
        "Unblob 26.6.4 not installed in WSL2: run tools/instalar-unblob-wsl.sh inside Ubuntu",
    "Binwalk 3.1.0 no instalado en WSL2: ejecuta tools/instalar-binwalk-wsl.sh dentro de Ubuntu":
        "Binwalk 3.1.0 not installed in WSL2: run tools/instalar-binwalk-wsl.sh inside Ubuntu",
    "sigrok en el REA de WSL no disponible: hace falta el REA de WSL (tools/instalar-rea-wsl.sh) y sigrok-cli 0.7.2 "
    "(tools/instalar-sigrok-wsl.sh)":
        "sigrok in the WSL REA not available: it needs the WSL REA (tools/instalar-rea-wsl.sh) and sigrok-cli 0.7.2 "
        "(tools/instalar-sigrok-wsl.sh)",
    "Ghidra en el REA de WSL no disponible: hace falta el REA de WSL (tools/instalar-rea-wsl.sh), Java 21 "
    "(tools/instalar-java-wsl.sh) y GHIDRA_INSTALL_DIR con Ghidra 12.1":
        "Ghidra in the WSL REA not available: it needs the WSL REA (tools/instalar-rea-wsl.sh), Java 21 "
        "(tools/instalar-java-wsl.sh) and GHIDRA_INSTALL_DIR with Ghidra 12.1",
    "caso no encontrado: {}. Usa el identificador de «eolfi case list» o crea uno con «eolfi case create <nombre>».":
        "case not found: {}. Use the identifier from \"eolfi case list\" or create one with "
        "\"eolfi case create <nombre>\".",
    "create: criterios del juez inválidos: {}": "create: invalid judge criteria: {}",
    "Sesiones guardadas en el perfil de Eolfi. Arranca el puente:  python -m eolfi bridge":
        "Sessions saved in Eolfi's profile. Start the bridge:  python -m eolfi bridge",
    "Abriendo el puente: inicia sesión en DeepSeek, Gemini, Meta AI y Le Chat en sus ventanas ({}{}).":
        "Opening the bridge: sign in to DeepSeek, Gemini, Meta AI and Le Chat in their windows ({}{}).",
    "Aviso: automatizar estas webs puede ir contra sus condiciones de uso; se usa tu cuenta.":
        "Warning: automating these websites may go against their terms of use; your account is used.",
    "Arrancando Eolas desde {} (registro: {})...": "Starting Eolas from {} (log: {})...",
    "Aviso: Eolas aún no responde; el panel lo detectará cuando esté listo.":
        "Warning: Eolas is not responding yet; the panel will detect it when it is ready.",
    "Abriendo VS Code para vincularlo (el código no se muestra). Si VS Code pregunta, permite abrir el enlace.":
        "Opening VS Code to link it (the code is not shown). If VS Code asks, allow opening the link.",
    "Abriendo VS Code con el puente de Eolfi. La primera petición mostrará un aviso de VS Code para permitir que la "
    "extensión use los modelos de IA: acéptalo.":
        "Opening VS Code with Eolfi's bridge. The first request will show a VS Code prompt to allow the extension to "
        "use the AI models: accept it.",
    "Navegador normal abierto con el perfil de Eolfi (sin control remoto).":
        "Normal browser opened with Eolfi's profile (without remote control).",
    "Inicia sesión en Google (Gemini), DeepSeek y Meta AI y, al terminar, CIERRA esa ventana del navegador.":
        "Sign in to Google (Gemini), DeepSeek and Meta AI and, when done, CLOSE that browser window.",
    "Instalando Electron para el puente (solo la primera vez)...":
        "Installing Electron for the bridge (first time only)...",
    "Puente listo en {}": "Bridge ready at {}",
    "Eolas ya está activo en {}": "Eolas is already running at {}",
    "Aviso: Eolas apunta a {}, que no es este equipo; no lo arranco.":
        "Warning: Eolas points to {}, which is not this computer; I am not starting it.",
    "El puerto {} está ocupado pero Eolas aún no responde; espero a que termine de arrancar...":
        "Port {} is in use but Eolas is not responding yet; waiting for it to finish starting...",
    "Aviso: algo ocupa el puerto {} y no responde como Eolas; sigo sin Eolas.":
        "Warning: something is using port {} and does not respond like Eolas; continuing without Eolas.",
    "Aviso: no encuentro {} (o PowerShell); sigo sin Eolas. Usa --celtiaia o CELTIAIA_HOME.":
        "Warning: {} (or PowerShell) not found; continuing without Eolas. Use --celtiaia or CELTIAIA_HOME.",
    "Aviso: el launcher de Eolas falló (código {}); mira {}": "Warning: the Eolas launcher failed (code {}); see {}",
    "Eolas listo en {} (para pararlo: {} -Stop)": "Eolas ready at {} (to stop it: {} -Stop)",
    "Cerrando el navegador controlado por el puente para liberar el perfil...":
        "Closing the browser controlled by the bridge to free the profile...",
    "El navegador del perfil de Eolfi no se cerró a tiempo: terminando solo esos procesos...":
        "The browser with Eolfi's profile did not close in time: ending only those processes...",
    "Esperando a que cierres la ventana del navegador...": "Waiting for you to close the browser window...",
    "Eolas listo en {}": "Eolas ready at {}",
    "Motor local: Eolas V2 (8090); se arranca al usarlo («python -m eolfi eolas-v2 start»). Para usar Eolas V1 de "
    "CeltIA: «python -m eolfi motor-local eolas-v1».":
        "Local engine: Eolas V2 (8090); it starts when used (\"python -m eolfi eolas-v2 start\"). To use CeltIA's "
        "Eolas V1: \"python -m eolfi motor-local eolas-v1\".",
    "El panel de Eolfi ya estaba en {}: lo reutilizo (elige Eolas en «Proveedores» si no sale por defecto). Ctrl+C "
    "para parar lo arrancado aquí.":
        "Eolfi's panel was already at {}: reusing it (choose Eolas in \"Proveedores\" if it is not the default). "
        "Ctrl+C to stop what was started here.",
    "Extensión instalada ({}). En VS Code: Ctrl+Shift+P → «Reload Window». Para quitarla: code --uninstall-extension "
    "eolfi.eolfi-vscode-bridge":
        "Extension installed ({}). In VS Code: Ctrl+Shift+P → \"Reload Window\". To remove it: "
        "code --uninstall-extension eolfi.eolfi-vscode-bridge",
    "El puente de chats web ya está activo": "The web chat bridge is already running",
    "Arrancando el puente de chats web (registro: {})...": "Starting the web chat bridge (log: {})...",
    "Parando {}...": "Stopping {}...",
    "RSI muestra: {}": "RSI sample: {}",
    "Informe en {}": "Report at {}",
    "Hay incógnitas abiertas de gravedad {} o mayor": "There are open unknowns of severity {} or higher",
    "Ghidra {}: analizando (puede tardar minutos)...": "Ghidra {}: analyzing (it may take minutes)...",
    # core/dbpath.py (se escriben con el prefijo «Eolfi: »)
    "Eolfi: la base de evidencias pasa a {}. Se ha copiado {}, que se conserva sin cambios y ya no se usa por defecto (para "
    "usarla: --db \"{}\").":
        "Eolfi: the evidence database moves to {}. {} was copied; it is kept unchanged and is no longer used by default (to "
        "use it: --db \"{}\").",
    "Eolfi: en esta carpeta hay una {} que no se usa; la base por defecto es {}. Para usar la de aquí: --db \"{}\".":
        "Eolfi: this folder has an unused {}; the default database is {}. To use the one here: --db \"{}\".",
    "Eolfi: no se pudo copiar {} a {} ({}: {}); se sigue usando {}": "Eolfi: {} could not be copied to {} ({}: {}); still using {}",
    # flows/create_flow.py, flows/project_flow.py, sites/*
    "especificación: destino {}, secciones {}, páginas {}": "specification: target {}, sections {}, pages {}",
    "criterios de accesibilidad instalados (axe en el estado inicial y tras cambiar el tema)":
        "accessibility criteria installed (axe in the initial state and after switching the theme)",
    "analizando {} como {}…": "analyzing {} as {}…",
    "copia de seguridad de {} en {}": "backup of {} in {}",
    "{} archivos verificados y copiados a {}": "{} files verified and copied to {}",
    "{} archivos generados en {}": "{} files generated in {}",
    "criterios del juez funcional instalados ({} comprobaciones)": "functional judge criteria installed ({} checks)",
    "'{}' se interpreta como la carpeta {}": "'{}' is interpreted as the folder {}",
    "verificando en una carpeta limpia ({}) antes de escribir sobre el origen…":
        "verifying in a clean folder ({}) before writing over the source…",
    "paso {}: {}": "step {}: {}",
    "renderizando {} página(s) de profundidad {}…": "rendering {} page(s) at depth {}…",
    "{} archivos": "{} files",
    "clonando {} (superficial, sin hooks)…": "cloning {} (shallow, without hooks)…",
    "página principal: {} ({} B)": "main page: {} ({} B)",
    "assets: {} descargados de {}": "assets: {} downloaded out of {}",
    # generador/assist.py (autofix y assist)
    "autofix: comprobando si quedan errores…": "autofix: checking whether errors remain…",
    "autofix: falla «{}»; se pide la corrección a {}": "autofix: \"{}\" fails; asking {} for the fix",
    "instalando dependencias antes de pedir cambios…": "installing dependencies before asking for changes…",
    "no se logró el verde: se conserva el mejor intento (ronda {}, juez {})":
        "green was not reached: keeping the best attempt (round {}, judge {})",
    "autofix: sin errores, no hace falta corregir nada": "autofix: no errors, nothing to fix",
    "autofix: {}; es de preparación del entorno y la IA no puede corregirlo":
        "autofix: {}; it is an environment setup issue and the AI cannot fix it",
    "autofix: no se logró un estado verde; restaurando los archivos originales":
        "autofix: a green state was not reached; restoring the original files",
    "ronda {}: pidiendo cambios a {} ({})…": "round {}: asking {} for changes ({})…",
    "  {} archivos escritos": "  {} files written",
    "  {} archivos escritos, {} rechazados": "  {} files written, {} rejected",
    "no se logró un estado verde: restaurando los archivos originales":
        "a green state was not reached: restoring the original files",
    "presupuesto de {} tokens agotado: no se piden más rondas": "budget of {} tokens used up: no more rounds requested",
    "detalle de verificación: {}": "verification detail: {}",
    "deshechos {} archivos escritos por {} en VS Code": "undid {} files written by {} in VS Code",
    "no se pudo deshacer lo escrito por {}: {}": "what {} wrote could not be undone: {}",
    "  la respuesta se cortó por longitud: ronda {} sin cambios":
        "  the answer was cut off by length: round {} without changes",
    "  la ronda {} empeoró: se vuelve a la versión de la ronda {} ({})":
        "  round {} got worse: going back to the version of round {} ({})",
    # generador/verify.py
    "→ juez funcional (la aplicación en Chrome)": "→ functional judge (the application in Chrome)",
    "  versiones: {}": "  versions: {}",
    "  publicar: {} no tiene un identificador de .NET; se omite": "  publish: {} has no .NET identifier; skipped",
    "  versiones fijadas: {}": "  pinned versions: {}",
    "  AVISO: «pip freeze» no devolvió versiones: requirements.txt queda sin fijar":
        "  WARNING: \"pip freeze\" returned no versions: requirements.txt stays unpinned",
    "verificación aislada: carpeta personal temporal {}": "isolated verification: temporary home folder {}",
    "autofix no disponible: {}": "autofix not available: {}",
    # flows/sync_flow.py (D1)
    "volviendo a analizar {} como {}…": "re-analyzing {} as {}…",
    "{} archivos escritos; copia de los anteriores en {}": "{} files written; copy of the previous ones in {}",
    # Pasos de la verificación (verify.py: «→ paso» y «  OK|FALLO (n s)»): la etiqueta se traduce entera.
    "→ {}": "→ {}",
    "  {} ({} s)": "  {} ({} s)",
    "  {}: {} ({} s)": "  {}: {} ({} s)",
    "FALLO": "FAILED",
    "juez funcional": "functional judge",
    "juez funcional ({})": "functional judge ({})",
    "juez funcional (desactivado con EOLFI_JUEZ=0: NO VERIFICADO)":
        "functional judge (disabled with EOLFI_JUEZ=0: NOT VERIFIED)",
    "alinear React/React Native con el SDK (expo install)": "align React/React Native with the SDK (expo install)",
    "compilar (avisos = errores)": "build (warnings = errors)",
    "compilar (tipos + bundle)": "build (types + bundle)",
    "compilar el comando (cargo build --release)": "build the command (cargo build --release)",
    "compilar el ejecutable (go build)": "build the executable (go build)",
    "compilar la app nativa con Rust (tauri build --debug)": "build the native app with Rust (tauri build --debug)",
    "comprobar proyecto (manage.py check)": "check the project (manage.py check)",
    "comprobar tipos (tsc)": "check types (tsc)",
    "crear entorno virtual": "create virtual environment",
    "empaquetar para este sistema (electron-builder --dir)": "package for this system (electron-builder --dir)",
    "empaquetar versión web (expo export)": "package the web version (expo export)",
    "generar iconos (Windows .ico, macOS .icns, PNG)": "generate icons (Windows .ico, macOS .icns, PNG)",
    "herramientas de pruebas y tipos": "test and type tools",
    "instalar Electron y electron-builder (latest)": "install Electron and electron-builder (latest)",
    "instalar Expo (latest)": "install Expo (latest)",
    "instalar dependencias (latest)": "install dependencies (latest)",
    "instalar la CLI de Tauri (latest)": "install the Tauri CLI (latest)",
    "prueba de humo: abrir la ventana nativa de verdad": "smoke test: really open the native window",
    "prueba de humo: arrancar el servidor y pedirle /api/health y la portada": "smoke test: start the server and request /api/health and the home page",
    "prueba de humo: arrancar la app de escritorio de verdad": "smoke test: really start the desktop app",
    "prueba de humo: arrancar la app nativa de verdad": "smoke test: really start the native app",
    "pruebas": "tests",
    "pruebas (Jest + Testing Library)": "tests (Jest + Testing Library)",
    "pruebas (cargo test)": "tests (cargo test)",
    "pruebas (go test)": "tests (go test)",
    "pruebas (manage.py test)": "tests (manage.py test)",
    "pruebas (node --test)": "tests (node --test)",
    "pruebas (pytest)": "tests (pytest)",
    "pruebas (seguridad de la configuración e interfaz)": "tests (configuration and interface security)",
    "pruebas (seguridad de la ventana, interfaz e instaladores)": "tests (window, interface and installer security)",
    "pruebas (xUnit)": "tests (xUnit)",
    "restaurar paquetes NuGet (última versión estable)": "restore NuGet packages (latest stable version)",
    "revisar el código (go vet)": "review the code (go vet)",
    "validar configuración nativa (app.json)": "validate native configuration (app.json)",
    "ejecutar el comando compilado ({} --json info)": "run the built command ({} --json info)",
    "ejecutar el comando instalado ({} --json info)": "run the installed command ({} --json info)",
    "instalar el comando (pip install -e .)": "install the command (pip install -e .)",
    "publicar ejecutable autocontenido para este sistema ({})": "publish a self-contained executable for this system ({})",
    "sintaxis JS del sitio ({})": "site JS syntax ({})",
    "  AVISO: no se pudo leer «dotnet list package»: las versiones NuGet quedan sin fijar (*)":
        "  WARNING: \"dotnet list package\" could not be read: the NuGet versions stay unpinned (*)",
}


class StderrTraducido:
    """Envoltorio de sys.stderr que traduce cada línea completa con un catálogo (``eolfi --idioma en``). Lo que no
    está en el catálogo pasa tal cual; nunca toca la salida estándar (el JSON de los resultados)."""

    def __init__(self, destino, catalogo: dict[str, str] | None = None):
        self._destino = destino
        self._catalogo = AVISOS_EN if catalogo is None else catalogo
        self._pendiente = ""

    def write(self, texto: str) -> int:
        self._pendiente += texto
        *lineas, self._pendiente = self._pendiente.split("\n")
        for linea in lineas:
            self._destino.write(traducir(linea, "en", self._catalogo) + "\n")
        return len(texto)

    def flush(self) -> None:
        if self._pendiente:
            self._destino.write(traducir(self._pendiente, "en", self._catalogo))
            self._pendiente = ""
        self._destino.flush()

    def __getattr__(self, nombre: str):
        return getattr(self._destino, nombre)
