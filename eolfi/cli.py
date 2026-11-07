"""CLI de Eolfi.

Comandos:
  doctor                         Comprueba proveedores disponibles.
  triage <archivo>               Triaje en un paso; registra evidencias.
  evidence [--subject SHA] [--operation OP]
                                 Lista evidencias.
  incognitas [--status S]        Lista preguntas abiertas.
  resolve <incognita_id>         Marca una incógnita como resuelta.
  diff --ref CMD --cand CMD <corpus>
                                 Verificación diferencial (EJECUTA ambos).
  reconstruct --case ID --out DIR [--model]
                                 Reconstrucción independiente por etapas desde la especificación, con trazabilidad.
  spec build|show|diff|review|tests --case ID
                                 Especificación versionada y sustentada por las evidencias del caso.
  observe run|replay|compare|show|check
                                 Observación de caja negra desde un guion (run/replay EJECUTAN el objetivo).
  export <salida> [--format json|sarif] [--artifact RUTA ...]
                                 Exporta el paquete de evidencias.
  import <paquete.json>          Importa un paquete (validado).
  case create|list|show|link|artifact|record|report|export|import   (y --case ID en triage, web, repo, diff, compare, create)
                                 Gestiona casos persistentes y paquetes completos.
  resilience fuzz <semilla>      Fuerza entradas malformadas sin tumbar.
  resilience inject <archivo>    Busca patrones de inyección de prompts.
  web <url|archivo|carpeta>       Analiza una página/sitio web para aprender cómo está hecho.
  repo <carpeta|url-git>         Analiza un repositorio (clon superficial y seguro).
  create --from FUENTE ... --out DIR [--target T] [--verify]
                                 Crea un proyecto NUEVO a partir de una o varias fuentes.
  report <objetivo> [--format html|md|json] [--out ARCHIVO] [--fail-on high]
                                 Informe del objetivo; con --fail-on, código 1 si hay incógnitas graves.
  compare <objetivo_a> <objetivo_b>
                                 Compara dos objetivos analizados (p. ej. dos versiones).
  decompile <archivo> --functions entry,main
                                 Pseudo-C de funciones concretas con Ghidra.
  assist <proyecto> --brief TEXTO [--provider P] [--model M] [--base-url URL]
                                 La IA implementa cambios en un proyecto generado (verificado y,
                                 si no queda en verde, deshecho).
  bridge [--login] [--browser B] [--engine browser|electron] [--install-only]
                                 Puente de chats web (DeepSeek, Gemini, Meta AI) con tu sesión.
  corpus [--library DIR] [--dry-run]
                                 Guarda código y textos de las fuentes en el corpus de Alejandría.
  mcp [--root CARPETA ...]      Servidor MCP (stdio) para Copilot (modo agente), Claude Code u
                                 otros clientes MCP; consulta Alejandría en caso de duda.
  serve [--port 8777] [--reload] [--root CARPETA ...] [--allow-remote]
                                 Servidor de desarrollo: API JSON + panel web. --root limita las
                                 rutas locales (también EOLFI_ROOTS).

Opción global: --db RUTA (base de evidencias, por defecto eolfi.db). En «create», --db memory|sqlite
(alias --backend-db) es la persistencia del backend generado, no la base de evidencias.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from eolfi import __version__
from eolfi.core.evidence import EvidenceStore
from eolfi.core.models import Status


def _print(obj) -> None:
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    try:
        print(text)
    except UnicodeEncodeError:   # consola Windows sin UTF-8
        print(json.dumps(obj, indent=2, ensure_ascii=True))


def _default_library() -> str:
    """Sin ruta fija de un equipo concreto: EOLFI_LIBRARY, ~/Alejandria o D:\\Alejandria si existe."""
    from pathlib import Path

    for cand in (Path.home() / "Alejandria", Path("D:/Alejandria")):
        if (cand / "scripts").is_dir():
            return str(cand)
    return str(Path.home() / "Alejandria")


def _case_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--case", dest="case_id", default=None,
                   help="Registra artefactos y resultado en este caso (eolfi case create …)")
    p.add_argument("--provenance", default="", help="Procedencia declarada de la entrada (se guarda en el caso)")


def _parser() -> argparse.ArgumentParser:
    from eolfi.core.cases import RECORD_KINDS

    ap = argparse.ArgumentParser(prog="eolfi", description="Eolfi — ingeniería inversa local con modelo de evidencias")
    ap.add_argument("--db", default="eolfi.db", help="Ruta de la base de evidencias")
    ap.add_argument("--version", action="version", version=f"eolfi {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    doc = sub.add_parser("doctor", help="Comprueba proveedores")
    doc.add_argument("--pin", metavar="ARCHIVO", default=None,
                     help="Fija rutas, versiones y SHA-256 de las herramientas en este archivo de bloqueo")
    doc.add_argument("--check-pin", metavar="ARCHIVO", default=None,
                     help="Compara las herramientas actuales con un archivo de bloqueo (código 6 si cambiaron)")
    t = sub.add_parser("triage", help="Triaje en un paso")
    t.add_argument("target")
    t.add_argument("--summary", action="store_true", help="Omite la lista de evidence_ids")
    t.add_argument("--deep", action="store_true", help="Incluye Ghidra headless (lento)")
    t.add_argument("--local", action="store_true", help="Solo proveedores stdlib (sin herramientas externas)")
    _case_args(t)

    e = sub.add_parser("evidence", help="Lista evidencias")
    e.add_argument("--subject", default=None)
    e.add_argument("--operation", default=None)

    i = sub.add_parser("incognitas", help="Lista preguntas abiertas")
    i.add_argument("--status", choices=[s.value for s in Status], default=None)
    i.add_argument("--subject", default=None)

    rv = sub.add_parser("resolve", help="Marca una incógnita como resuelta")
    rv.add_argument("incognita_id")
    rv.add_argument("--status", choices=[s.value for s in Status], default=Status.RESOLVED.value)

    d = sub.add_parser("diff", help="Verificación diferencial referencia vs candidato (EJECUTA ambos)")
    d.add_argument("corpus", help="Archivo o carpeta de entradas")
    d.add_argument("--ref", required=True, help="Comando de referencia; {input} = ruta de la entrada (si no, stdin)")
    d.add_argument("--cand", required=True, help="Comando candidato (reimplementación)")
    d.add_argument("--timeout", type=float, default=10.0)
    d.add_argument("--stderr", action="store_true", help="Compara también stderr")
    d.add_argument("--normalize", choices=["exact", "newlines", "lines"], default="lines")
    d.add_argument("--threshold", type=float, default=1.0, help="Ratio mínimo de equivalencia (0-1)")
    d.add_argument("--mutate", type=int, default=0, help="Añade N entradas mutadas al corpus")
    d.add_argument("--determinism", action="store_true", help="Ejecuta la referencia dos veces para detectar no determinismo")
    d.add_argument("--autorizo", action="store_true",
                   help="Confirmo que estoy autorizado a ejecutar referencia y candidato (obligatorio)")
    _case_args(d)

    ob = sub.add_parser("observe", help="Observación de caja negra desde un guion (EJECUTA el objetivo)")
    obs_ = ob.add_subparsers(dest="obs_cmd", required=True)
    orun = obs_.add_parser("run", help="Ejecuta un guion de observación y guarda la sesión")
    orun.add_argument("script", help="Guion JSON (eolfi_observation_script: 1)")
    orun.add_argument("--autorizo", action="store_true",
                      help="Confirmo que estoy autorizado a ejecutar este objetivo (obligatorio)")
    orun.add_argument("--var", action="append", default=[], metavar="NOMBRE=VALOR", help="Variable {var:NOMBRE}")
    orun.add_argument("--keep-sandbox", action="store_true", help="No borra la carpeta temporal de la sesión")
    orun.add_argument("--playwright", default=None, help="Ruta del paquete playwright-core para pasos browser")
    _case_args(orun)
    orep = obs_.add_parser("replay", help="Repite una sesión guardada desde su guion y marca lo no reproducible")
    orep.add_argument("evidence_id")
    orep.add_argument("--autorizo", action="store_true", help="Confirmo la autorización para ejecutar (obligatorio)")
    orep.add_argument("--var", action="append", default=[], metavar="NOMBRE=VALOR")
    orep.add_argument("--playwright", default=None)
    orep.add_argument("--case", dest="case_id", default=None)
    ocmp = obs_.add_parser("compare", help="Compara dos sesiones (versiones o entornos): primer cambio observable")
    ocmp.add_argument("a")
    ocmp.add_argument("b")
    ocmp.add_argument("--case", dest="case_id", default=None)
    ocmp.add_argument("--tolerate", action="append", default=[], metavar="ASPECTO",
                      help="Aspecto tolerado (diferencia no funcional declarada), p. ej. «*.texto visible»")
    oshow = obs_.add_parser("show", help="Muestra una sesión guardada")
    oshow.add_argument("evidence_id")
    ochk = obs_.add_parser("check", help="Valida un guion sin ejecutar nada")
    ochk.add_argument("script")
    oplan = obs_.add_parser("plan", help="Qué ejecutaría el guion, con qué permisos y qué datos se guardarían (no ejecuta)")
    oplan.add_argument("script")
    oplan.add_argument("--var", action="append", default=[], metavar="NOMBRE=VALOR")
    ofor = obs_.add_parser("forget", help="Borra una sesión y sus evidencias derivadas (IRREVERSIBLE)")
    ofor.add_argument("evidence_id")
    ofor.add_argument("--confirmo", action="store_true", help="Confirmo el borrado irreversible")

    rc = sub.add_parser("reconstruct", help="Reconstrucción independiente y trazable desde la especificación del caso")
    rc.add_argument("--case", dest="case_id", required=True)
    rc.add_argument("--out", default=None, help="Carpeta destino (obligatoria salvo con --model)")
    rc.add_argument("--name", default="reconstruccion")
    rc.add_argument("--target", default="python-cli", choices=["python-cli"])
    rc.add_argument("--model", action="store_true", help="Solo muestra el modelo de comportamiento (no genera)")
    rc.add_argument("--equivalence", metavar="CANDIDATO", default=None,
                    help="Repite los guiones del caso con este candidato y compara con el original (EJECUTA)")
    rc.add_argument("--explore", metavar="CANDIDATO", default=None,
                    help="Variantes deterministas de las entradas: ejecuta original y candidato y reduce lo que falla")
    rc.add_argument("--variants", type=int, default=8)
    rc.add_argument("--seed", type=int, default=1337)
    rc.add_argument("--max-runs", type=int, default=200)
    rc.add_argument("--autorizo", action="store_true", help="Confirmo la autorización para ejecutar el candidato")
    rc.add_argument("--tolerate", action="append", default=[], metavar="ASPECTO",
                    help="Aspecto tolerado declarado (patrón, p. ej. «procesos hijos» o «*.accesibilidad»)")

    sp = sub.add_parser("spec", help="Especificación de comportamiento sustentada por las evidencias de un caso")
    sps = sp.add_subparsers(dest="spec_cmd", required=True)
    for name, hlp in (("build", "Construye y guarda una versión nueva si el contenido cambió"),
                      ("show", "Muestra la última versión (o --version N)"),
                      ("tests", "Casos de prueba derivados solo de requisitos observados")):
        x = sps.add_parser(name, help=hlp)
        x.add_argument("--case", dest="case_id", required=True)
        if name != "build":
            x.add_argument("--version", type=int, default=None)
        if name == "tests":
            x.add_argument("--out", default=None, help="Escribe los casos en este JSON")
    sdiff = sps.add_parser("diff", help="Compara dos versiones de la especificación")
    sdiff.add_argument("--case", dest="case_id", required=True)
    sdiff.add_argument("a", type=int)
    sdiff.add_argument("b", type=int)
    srev = sps.add_parser("review", help="Revisión humana de un requisito (queda registrada en el caso)")
    srev.add_argument("--case", dest="case_id", required=True)
    srev.add_argument("requirement")
    srev.add_argument("decision", choices=["accepted", "rejected", "needs_info"])
    srev.add_argument("--reviewer", required=True)
    srev.add_argument("--note", default="")

    ex = sub.add_parser("export", help="Exporta paquete de evidencias")
    ex.add_argument("out")
    ex.add_argument("--format", choices=["json", "sarif", "stix"], default=None,
                    help="Por defecto según la extensión: .sarif → sarif, .stix.json → stix, si no json")
    ex.add_argument("--artifact", action="append", default=[],
                    help="Ruta de un artefacto analizado, para enlazarlo en SARIF (repetible)")

    im = sub.add_parser("import", help="Importa paquete de evidencias")
    im.add_argument("inp")

    cs = sub.add_parser("case", help="Gestiona casos persistentes de análisis")
    css = cs.add_subparsers(dest="case_cmd", required=True)
    css.add_parser("list", help="Lista los casos")
    cnew = css.add_parser("create", help="Crea un caso")
    cnew.add_argument("name")
    cnew.add_argument("--description", default="")
    cshow = css.add_parser("show", help="Muestra el caso, objetivos, evidencias e incógnitas")
    cshow.add_argument("case_id")
    clink = css.add_parser("link", help="Asocia un objetivo ya analizado (identidad y herramientas desde sus evidencias)")
    clink.add_argument("case_id")
    clink.add_argument("subject", help="sha256, prefijo, nombre o ruta ya analizada")
    clink.add_argument("--provenance", default="", help="Procedencia declarada del artefacto")
    crep = css.add_parser("report", help="Informe HTML navegable del caso (o JSON)")
    crep.add_argument("case_id")
    crep.add_argument("--format", choices=["html", "json"], default="html")
    crep.add_argument("--out", help="Archivo de salida (por defecto, la salida estándar)")
    cart = css.add_parser("artifact", help="Asocia un artefacto por SHA-256 (o subject de Eolfi)")
    cart.add_argument("case_id")
    cart.add_argument("subject")
    cart.add_argument("--size", type=int, default=None, help="Bytes (omitir si se desconoce)")
    cart.add_argument("--format", required=True)
    cart.add_argument("--version", default="")
    cart.add_argument("--provenance", required=True)
    cart.add_argument("--path", default="")
    cart.add_argument("--platform", default="")
    crec = css.add_parser("record", help="Añade una observación/especificación/etc. desde JSON")
    crec.add_argument("case_id")
    crec.add_argument("kind", choices=sorted(RECORD_KINDS))
    crec.add_argument("payload", help="Objeto JSON o @ruta a un archivo JSON")
    cexport = css.add_parser("export", help="Exporta caso, evidencias e incógnitas a JSON")
    cexport.add_argument("case_id")
    cexport.add_argument("out")
    cimport = css.add_parser("import", help="Importa un paquete completo de caso validado")
    cimport.add_argument("inp")

    r = sub.add_parser("resilience", help="Banco de pruebas de resiliencia")
    rs = r.add_subparsers(dest="rcmd", required=True)
    rf = rs.add_parser("fuzz", help="Fuzzing de entradas sin tumbar el sistema")
    rf.add_argument("seed")
    rf.add_argument("--iters", type=int, default=200)
    rf.add_argument("--timeout", type=float, default=10.0)
    ri = rs.add_parser("inject", help="Escaneo de inyección de prompts")
    ri.add_argument("target")

    wb = sub.add_parser("web", help="Analiza una página o sitio web")
    wb.add_argument("source", help="URL http(s), archivo .html o carpeta de sitio estático")
    wb.add_argument("--max-assets", type=int, default=40)
    wb.add_argument("--cross-origin", action="store_true", help="Descarga también assets de otros dominios")
    wb.add_argument("--ignore-robots", action="store_true", help="No respetar robots.txt (solo con permiso)")
    wb.add_argument("--save", default=None, help="Guarda una copia de estudio de HTML/CSS/JS en esta carpeta")
    _case_args(wb)

    rp = sub.add_parser("repo", help="Analiza un repositorio local o remoto")
    rp.add_argument("source", help="Carpeta local o URL git")
    rp.add_argument("--workdir", default="samples/repos", help="Dónde clonar los repos remotos")
    _case_args(rp)

    cr = sub.add_parser("create", help="Crea un proyecto NUEVO a partir de una o varias fuentes")
    cr.add_argument("--from", dest="sources", action="append", required=True,
                    help="URL web, URL git, carpeta, archivo u objetivo ya analizado (repetible)")
    cr.add_argument("--out", required=True, help="Carpeta del proyecto nuevo (vacía o inexistente)")
    cr.add_argument("--name", default="Nuevo proyecto")
    cr.add_argument("--target", default="auto",
                    choices=["auto", "static", "react", "vue", "svelte", "next", "fastapi", "express", "django", "expo", "desktop", "tauri", "cli", "dotnet"])
    cr.add_argument("--verify", action="store_true", default=True,
                    help="Verificación obligatoria (opción conservada por compatibilidad)")
    # dest propio: con dest «db» pisaba el --db global y «create --db sqlite» creaba una base de
    # evidencias llamada «sqlite» en la carpeta actual (PLAN_MEJORAS servidor A1).
    cr.add_argument("--db", "--backend-db", dest="backend_db", choices=["memory", "sqlite"], default="memory",
                    help="Persistencia de los backends FastAPI/Express (sqlite: sin dependencias nuevas)")
    cr.add_argument("--auth", action="store_true",
                    help="Registro, inicio de sesión y token para las escrituras (FastAPI/Express)")
    cr.add_argument("--force", action="store_true", help="Escribe aunque la carpeta no esté vacía")
    cr.add_argument("--reanalyze", action="store_true", help="Vuelve a analizar fuentes ya conocidas")
    cr.add_argument("--workdir", default="samples/repos")
    _case_args(cr)
    cr.add_argument("--ai", dest="ai_brief", default=None,
                    help="Descripción para que la IA implemente la lógica de negocio")
    for sp in (cr,):
        sp.add_argument("--provider", default="claude", choices=["claude", "eolas", "deepseek", "gemini", "openai", "deepseek-web", "gemini-web", "meta-web", "chatgpt-web", "copilot-web", "lechat-web", "copilot-vscode", "gemma", "web"])
        sp.add_argument("--model", default=None, help="Modelo del proveedor (por defecto, el de su preajuste)")
        sp.add_argument("--base-url", default=None, help="URL del servidor (p. ej. Eolas en otro puerto)")

    asg = sub.add_parser("assist", help="Claude implementa cambios en un proyecto generado (requiere eolfi[ai])")
    asg.add_argument("project", help="Carpeta de un proyecto creado con 'eolfi create'")
    asg.add_argument("--brief", required=True, help="Qué quieres que implemente")
    asg.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    asg.add_argument("--provider", default="claude", choices=["claude", "eolas", "deepseek", "gemini", "openai", "deepseek-web", "gemini-web", "meta-web", "chatgpt-web", "copilot-web", "lechat-web", "copilot-vscode", "gemma", "web"])
    asg.add_argument("--model", default=None)
    asg.add_argument("--base-url", default=None)

    rpt = sub.add_parser("report", help="Informe HTML o Markdown de un objetivo (con umbral para CI)")
    rpt.add_argument("subject", help="Objetivo: sha256, prefijo, nombre o ruta ya analizada")
    rpt.add_argument("--format", choices=["html", "md", "json"], default="html")
    rpt.add_argument("--out", help="Archivo de salida (por defecto, la salida estándar)")
    rpt.add_argument("--fail-on", choices=["low", "medium", "high", "critical"], default=None,
                     help="Sale con código 1 si hay incógnitas abiertas de esa gravedad o mayor (para CI)")

    cp = sub.add_parser("compare", help="Compara dos objetivos analizados")
    cp.add_argument("a")
    cp.add_argument("b")
    _case_args(cp)

    dc = sub.add_parser("decompile", help="Decompila funciones concretas con Ghidra (lento)")
    dc.add_argument("target")
    dc.add_argument("--functions", default="entry",
                    help="Nombres o direcciones separados por comas; 'entry' = punto de entrada")

    br = sub.add_parser("bridge", help="Puente Electron para DeepSeek / Gemini / Meta AI web")
    br.add_argument("--install-only", action="store_true", help="Solo instala Electron en el puente")
    br.add_argument("--browser", default=None,
                    help="Navegador real: chrome, edge, brave, opera, vivaldi, chromium o ruta al ejecutable "
                         "(por defecto el primero instalado)")
    br.add_argument("--login", action="store_true",
                    help="Abre el perfil de Eolfi en un navegador normal, sin control remoto, para iniciar "
                         "sesión en Google/Gemini, DeepSeek y Meta (Google bloquea el acceso en navegadores controlados)")
    br.add_argument("--engine", choices=["browser", "electron"], default=None,
                    help="browser = navegador real (recomendado: Google bloquea el inicio de sesión en Electron)")

    vd = sub.add_parser("vscode-do", help="Acción en VS Code a través del puente: workspace, list, read, find, open, write, command, tool")
    vd.add_argument("action", choices=["workspace", "list", "read", "find", "open", "write", "command", "tool"])
    vd.add_argument("--path")
    vd.add_argument("--line", type=int)
    vd.add_argument("--glob")
    vd.add_argument("--text", help="Texto que buscar (find)")
    vd.add_argument("--content-file", help="Archivo local cuyo contenido escribir (write)")
    vd.add_argument("--reason", default="", help="Motivo que verá el usuario al confirmar (write)")
    vd.add_argument("--name", help="Comando de VS Code (command) o herramienta (tool)")
    vd.add_argument("--input", default="{}", help="JSON con argumentos de la herramienta (tool) o lista de argumentos (command)")

    lm = sub.add_parser("llama", help="Modelo local llama.cpp (Gemma 4): estado, arrancar, parar o abrir la configuración")
    lm.add_argument("accion", nargs="?", default="status", choices=["status", "start", "stop", "config"])

    vs = sub.add_parser("vscode", help="Abre VS Code con la extensión de Eolfi (IA de VS Code: --provider copilot-vscode)")
    vs.add_argument("folder", nargs="?", default=None, help="Carpeta que abrir en VS Code (opcional)")
    vs.add_argument("--login", action="store_true",
                    help="vincula VS Code con tu Eolfi sin mostrar ningún código (abre un enlace vscode://)")
    vs.add_argument("--install", action="store_true",
                    help="Instala la extensión de forma permanente (por defecto se carga solo en una ventana de desarrollo)")

    co = sub.add_parser("corpus", help="Guarda el código y los textos de las fuentes compartidas en el corpus de Alejandría")
    co.add_argument("--library", default=os.environ.get("EOLFI_LIBRARY") or _default_library(),
                    help="Carpeta de la biblioteca (EOLFI_LIBRARY, o Alejandria en la carpeta personal o en D:)")
    co.add_argument("--dry-run", action="store_true", help="Muestra qué se importaría sin copiar nada")

    mc = sub.add_parser("mcp", help="Servidor MCP por stdio (Copilot en modo agente, Claude Code…)")
    mc.add_argument("--root", action="append", default=[], metavar="CARPETA",
                    help="Carpeta permitida para rutas locales (repetible; también EOLFI_ROOTS)")
    mc.add_argument("--library", default=os.environ.get("EOLFI_LIBRARY") or _default_library(),
                    help="Biblioteca Alejandría local (también EOLFI_LIBRARY)")

    up = sub.add_parser("up", help="Arranca todo junto: Eolas local (CeltIA), el puente de chats web y el panel")
    up.add_argument("--port", type=int, default=8777)
    up.add_argument("--celtiaia", default=os.environ.get("CELTIAIA_HOME", r"D:\celtiaia"),
                    help="Repositorio CeltIA con launch-eolas.ps1 (también CELTIAIA_HOME)")
    up.add_argument("--no-eolas", action="store_true", help="No arranca Eolas")
    up.add_argument("--no-bridge", action="store_true", help="No arranca el puente de chats web")
    up.add_argument("--browser", default=None, help="Navegador del puente (como en «eolfi bridge»)")
    up.add_argument("--no-open", action="store_true", help="No abre el panel en el navegador")
    up.add_argument("--reload", action="store_true", help="Reinicia el panel al cambiar el código de eolfi/")

    sv = sub.add_parser("serve", help="Servidor de desarrollo (API + panel web)")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8777)
    sv.add_argument("--samples", default="samples", help="Carpeta donde guardar los archivos subidos")
    sv.add_argument("--reload", action="store_true", help="Reinicia al cambiar el código de eolfi/")
    sv.add_argument("--allow-remote", action="store_true", help="Permite escuchar fuera de localhost")
    sv.add_argument("--root", action="append", default=[], metavar="CARPETA",
                    help="Carpeta permitida para rutas locales (repetible). Sin --root, sin restricción en local; "
                         "en modo remoto, solo samples/ y generated/")
    return ap


def _vars(items: list[str]) -> dict[str, str]:
    out = {}
    for it in items:
        name, sep, value = it.partition("=")
        if not sep or not name:
            raise SystemExit(f"--var espera NOMBRE=VALOR: {it!r}")
        out[name] = value
    return out


def _spec(args, store: EvidenceStore) -> int:
    from pathlib import Path

    from eolfi.spec import diff_specs, latest_spec, review_requirement, spec_tests, store_spec

    try:
        if args.spec_cmd == "build":
            _print(store_spec(store, args.case_id))
        elif args.spec_cmd == "show":
            spec = latest_spec(store, args.case_id, args.version)
            if spec is None:
                _print({"error": "el caso no tiene especificación: ejecuta eolfi spec build"})
                return 1
            _print(spec)
        elif args.spec_cmd == "tests":
            spec = latest_spec(store, args.case_id, args.version)
            if spec is None:
                _print({"error": "el caso no tiene especificación: ejecuta eolfi spec build"})
                return 1
            t = spec_tests(spec)
            if args.out:
                Path(args.out).write_text(json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")
                _print({"out": args.out, "tests": len(t["tests"]), "skipped": len(t["skipped"])})
            else:
                _print(t)
        elif args.spec_cmd == "diff":
            a, b = latest_spec(store, args.case_id, args.a), latest_spec(store, args.case_id, args.b)
            _print(diff_specs(a, b))
        elif args.spec_cmd == "review":
            _print(review_requirement(store, args.case_id, args.requirement, args.decision,
                                      reviewer=args.reviewer, note=args.note))
    except ValueError as exc:
        _print({"error": str(exc)})
        return 1
    return 0


def _observe(args, store: EvidenceStore) -> int:
    from eolfi.observe import ScriptError, load_session, run_compare, run_observation, run_replay
    from eolfi.observe.session import load_script, static_unfixed_factors

    try:
        if args.obs_cmd == "check":
            script, _ = load_script(args.script)
            _print({"valid": True, "name": script["name"], "steps": [s["id"] for s in script["steps"]],
                    "unfixed_factors": static_unfixed_factors(script)})
            return 0
        if args.obs_cmd == "plan":
            from eolfi.security.levels import session_plan

            script, bdir = load_script(args.script)
            _print(session_plan(script, bdir, db_path=store.path, variables=_vars(args.var)))
            return 0
        if args.obs_cmd == "forget":
            if not args.confirmo:
                _print({"error": "el borrado es irreversible: repite con --confirmo"})
                return 2
            from eolfi.security.levels import forget_session

            _print(forget_session(store, args.evidence_id))
            return 0
        if args.obs_cmd == "show":
            _print(load_session(store, args.evidence_id))
            return 0
        if args.obs_cmd == "compare":
            rep = run_compare(store, args.a, args.b, case_id=args.case_id, tolerances=args.tolerate)
            _print(rep)
            return 0 if rep["identical"] else 5
        if args.obs_cmd == "run":
            rep = run_observation(args.script, store, authorized=args.autorizo, variables=_vars(args.var),
                                  case_id=args.case_id, keep_sandbox=args.keep_sandbox, playwright=args.playwright,
                                  provenance=args.provenance)
            _print(rep)
            return 0 if rep["status"] == "done" else 3
        if args.obs_cmd == "replay":
            rep = run_replay(store, args.evidence_id, authorized=args.autorizo, variables=_vars(args.var),
                             case_id=args.case_id, playwright=args.playwright)
            _print(rep)
            return 0 if rep["reproducible"] else 5
    except PermissionError as exc:
        _print({"error": str(exc)})
        return 2
    except (ScriptError, ValueError, FileNotFoundError) as exc:
        _print({"error": str(exc)})
        return 1
    return 1


def _dispatch(args, store: EvidenceStore) -> int:
    if args.cmd == "doctor":
        if args.pin or args.check_pin:
            from eolfi.security import toolpin

            if args.pin:
                _print(toolpin.write_lock(args.pin))
                return 0
            rep = toolpin.check_lock(args.check_pin)
            _print(rep)
            return 0 if rep["matches"] else 6
        from eolfi.flows.triage_flow import ALL_PROVIDERS

        out = {}
        for p in ALL_PROVIDERS:
            ok = p.available()
            if ok and hasattr(p, "_tool_version"):
                p.version = p._tool_version()
            out[p.name] = {"available": ok, "version": getattr(p, "version", "?")}
        from eolfi.generador.llm import PRESETS, probe

        out["ia"] = {name: probe(name) for name in PRESETS}
        _print(out)
    elif args.cmd == "triage":
        from eolfi.flows import triage_flow as tf

        provs = tf.LOCAL_PROVIDERS if args.local else tf.DEEP_PROVIDERS if args.deep else tf.DEFAULT_PROVIDERS
        rep = tf.run_triage(args.target, store, provs, case_id=args.case_id, provenance=args.provenance)
        if args.summary:
            rep.pop("evidence_ids", None)
        _print(rep)
    elif args.cmd == "evidence":
        rows = store.list_evidence(args.subject)
        if args.operation:
            rows = [r for r in rows if r["operation"] == args.operation]
        for r in rows:
            for k in ("params", "result", "links"):
                r[k] = json.loads(r[k]) if r.get(k) else r.get(k)
        _print(rows)
    elif args.cmd == "incognitas":
        _print(store.list_incognitas(Status(args.status) if args.status else None, subject=args.subject))
    elif args.cmd == "resolve":
        ok = store.resolve_incognita(args.incognita_id, Status(args.status))
        _print({"incognita_id": args.incognita_id, "updated": ok})
        return 0 if ok else 1
    elif args.cmd == "diff":
        from eolfi.flows.diff_flow import run_diff

        if not args.autorizo:
            _print({"error": "diff EJECUTA referencia y candidato sin aislamiento: confirma con --autorizo"})
            return 2

        rep = run_diff(
            args.ref, args.cand, args.corpus, store,
            timeout=args.timeout, compare_stderr=args.stderr, normalize=args.normalize,
            threshold=args.threshold, mutate=args.mutate, check_determinism=args.determinism,
            case_id=args.case_id, provenance=args.provenance,
        )
        _print(rep)
        return 0 if rep["passed"] else 4
    elif args.cmd == "reconstruct":
        from eolfi.reconstruct import build_model, reconstruct

        try:
            if args.model:
                _print(build_model(store, args.case_id))
                return 0
            if args.explore:
                from eolfi.reconstruct import explore

                try:
                    ex = explore(store, args.case_id, args.explore, authorized=args.autorizo, variants=args.variants,
                                 seed=args.seed, max_runs=args.max_runs, tolerances=args.tolerate)
                except PermissionError as exc:
                    _print({"error": str(exc)})
                    return 2
                _print(ex)
                return 0 if ex["divergent_variants"] == 0 else 5
            if args.equivalence:
                from eolfi.reconstruct import check_equivalence

                try:
                    eq = check_equivalence(store, args.case_id, args.equivalence, authorized=args.autorizo,
                                           tolerances=args.tolerate)
                except PermissionError as exc:
                    _print({"error": str(exc)})
                    return 2
                eq.pop("runs")
                _print(eq)
                return 0 if eq["equivalent"] else 5
            if not args.out:
                _print({"error": "indica --out"})
                return 1
            rep = reconstruct(store, args.case_id, args.out, name=args.name, target=args.target)
        except ValueError as exc:
            _print({"error": str(exc)})
            return 1
        rep.pop("model")
        _print(rep)
        v = rep["verification"]
        return 0 if v["differ"] == 0 and v["match"] > 0 else 4
    elif args.cmd == "spec":
        return _spec(args, store)
    elif args.cmd == "observe":
        return _observe(args, store)
    elif args.cmd == "export":
        low = args.out.lower()
        fmt = args.format or ("sarif" if low.endswith(".sarif") else "stix" if low.endswith(".stix.json") else "json")
        if fmt == "stix":
            from eolfi.core.stix import export_stix

            n = export_stix(store, args.out)
            _print({"exported": args.out, "format": "stix", "objects": n})
        elif fmt == "sarif":
            from eolfi.core.sarif import export_sarif

            n = export_sarif(store, args.out, args.artifact)
            _print({"exported": args.out, "format": "sarif", "results": n})
        else:
            store.export_package(args.out)
            _print({"exported": args.out, "format": "json"})
    elif args.cmd == "import":
        _print({"imported_new": store.import_package(args.inp)})
    elif args.cmd == "case":
        from eolfi.core.cases import CaseStore

        cases = CaseStore(store)
        if args.case_cmd == "list":
            _print(cases.list())
        elif args.case_cmd == "create":
            _print(cases.create(args.name, args.description))
        elif args.case_cmd == "show":
            _print(cases.get(args.case_id))
        elif args.case_cmd == "link":
            from eolfi.flows.create_flow import resolve_subject

            subject = resolve_subject(store, args.subject)
            if not subject:
                raise ValueError(f"objetivo no encontrado o ambiguo: {args.subject}")
            _print(cases.associate(args.case_id, subject, provenance=args.provenance))
        elif args.case_cmd == "report":
            from eolfi.core.case_report import build_case_report, render_case_html

            rep = build_case_report(cases.get(args.case_id))
            text = render_case_html(rep) if args.format == "html" else json.dumps(rep, ensure_ascii=False, indent=2)
            if args.out:
                from pathlib import Path
                Path(args.out).write_text(text, encoding="utf-8")
                _print({"case_id": args.case_id, "report": args.out, "format": args.format,
                        "conclusions": len(rep["conclusions"]), "open_incognitas": rep["open_incognitas"]})
            else:
                sys.stdout.write(text)
        elif args.case_cmd == "artifact":
            created = cases.add_artifact(args.case_id, args.subject, size=args.size, format=args.format,
                                         provenance=args.provenance, version=args.version,
                                         path=args.path, platform=args.platform)
            _print({"case_id": args.case_id, "subject": args.subject, "created": created})
        elif args.case_cmd == "record":
            from pathlib import Path
            raw = Path(args.payload[1:]).read_text(encoding="utf-8") if args.payload.startswith("@") else args.payload
            payload = json.loads(raw)
            record_id = cases.add_record(args.case_id, args.kind, payload)
            _print({"case_id": args.case_id, "record_id": record_id, "kind": args.kind})
        elif args.case_cmd == "export":
            cases.export(args.case_id, args.out)
            _print({"case_id": args.case_id, "exported": args.out})
        elif args.case_cmd == "import":
            _print({"imported": cases.import_case(args.inp)})
    elif args.cmd == "web":
        from eolfi.flows.learn_flow import run_web

        rep = run_web(args.source, store, max_assets=args.max_assets, cross_origin=args.cross_origin,
                      ignore_robots=args.ignore_robots, save_dir=args.save, progress=_progress,
                      case_id=args.case_id, provenance=args.provenance)
        rep.pop("evidence_ids", None)
        _print(rep)
    elif args.cmd == "repo":
        from eolfi.flows.learn_flow import run_repo

        rep = run_repo(args.source, store, workdir=args.workdir, progress=_progress, case_id=args.case_id,
                       provenance=args.provenance)
        rep.pop("evidence_ids", None)
        _print(rep)
    elif args.cmd == "create":
        from eolfi.flows.create_flow import create_project

        rep = create_project(args.sources, store, args.out, name=args.name, target=args.target,
                             do_verify=True, force=args.force, reanalyze=args.reanalyze,
                             workdir=args.workdir, ai_brief=args.ai_brief, ai_provider=args.provider,
                             ai_model=args.model, ai_base_url=args.base_url, db=args.backend_db, auth=args.auth,
                             progress=_progress, case_id=args.case_id, provenance=args.provenance)
        rep.pop("spec", None)
        _print(rep)
        if rep.get("assist") and not rep["assist"]["ok"]:
            return 6
        return 0 if rep.get("verification", {}).get("ok", False) else 5
    elif args.cmd == "bridge":
        if args.login:
            return _login_mode(args.browser)
        return _run_bridge(args.install_only, args.browser, args.engine)
    elif args.cmd == "assist":
        from eolfi.flows.create_flow import run_assist
        from eolfi.generador.assist import AssistError

        try:
            rep = run_assist(store, args.project, args.brief, provider=args.provider, model=args.model,
                             base_url=args.base_url, progress=_progress)
        except AssistError as exc:
            raise ValueError(str(exc)) from exc
        _print(rep)
        return 0 if rep["ok"] else 6
    elif args.cmd == "report":
        from eolfi.core.report import build_report, fails, render_html, render_markdown
        from eolfi.flows.create_flow import resolve_subject

        subject = resolve_subject(store, args.subject)
        if not subject:
            raise ValueError(f"objetivo no encontrado o ambiguo: {args.subject}")
        rep = build_report(store, subject)
        text = {"html": render_html, "md": render_markdown}.get(args.format, lambda r: json.dumps(r, indent=2, ensure_ascii=False))(rep)
        if args.out:
            from pathlib import Path as _P

            _P(args.out).write_text(text, encoding="utf-8")
            _progress(f"Informe en {args.out}")
        else:
            sys.stdout.write(text)
        if fails(rep, args.fail_on):
            _progress(f"Hay incógnitas abiertas de gravedad {args.fail_on} o mayor")
            return 1
    elif args.cmd == "compare":
        from eolfi.flows.compare_flow import compare
        from eolfi.flows.create_flow import resolve_subject

        a, b = resolve_subject(store, args.a), resolve_subject(store, args.b)
        if not a or not b:
            raise ValueError(f"objetivo no encontrado o ambiguo: {args.a if not a else args.b}")
        _print(compare(store, a, b, case_id=args.case_id, provenance=args.provenance))
    elif args.cmd == "decompile":
        from pathlib import Path

        from eolfi.flows.triage_flow import environment_string, record_findings
        from eolfi.providers.external import GhidraProvider
        from eolfi.providers.triage import sha256_file

        prov = GhidraProvider(decompile=args.functions.split(","))
        if not prov.available():
            raise FileNotFoundError("Ghidra no encontrado: define GHIDRA_INSTALL_DIR")
        if not Path(args.target).is_file():
            raise FileNotFoundError(args.target)
        _progress(f"Ghidra {prov._tool_version()}: analizando (puede tardar minutos)...")
        findings = prov.run(args.target)
        record_findings(store, sha256_file(args.target), prov, findings, environment_string())
        dec = next((f for f in findings if f["operation"] == "ghidra_decompilation"), None)
        if dec is None:
            _print(findings[0]["result"] if findings else {"error": "sin resultados"})
            return 1
        for fn in dec["result"]["functions"]:
            print(f"// {fn['name']} @ {fn['entry']}" + ("" if fn["ok"] else f"  (error: {fn['error']})"))
            print(fn["c"] or "")
    elif args.cmd == "resilience":
        from eolfi.security.resilience import fuzz_file, prompt_injection_scan

        if args.rcmd == "fuzz":
            _print(fuzz_file(args.seed, store, iters=args.iters, timeout=args.timeout))
        elif args.rcmd == "inject":
            _print(prompt_injection_scan(args.target, store))
    return 0


LOGIN_URLS = (
    "https://accounts.google.com/ServiceLogin?continue=https%3A%2F%2Fgemini.google.com%2Fapp",
    "https://chat.deepseek.com/sign_in",
    "https://www.meta.ai/",
)


def _login_mode(browser: str | None) -> int:
    """Inicio de sesión manual en un navegador normal (sin depuración remota) con el perfil de Eolfi.

    Google y otras webs rechazan el acceso desde navegadores controlados por software. Aquí no
    hay ningún control: es tu navegador con el perfil de Eolfi. Al cerrarlo, las sesiones quedan
    guardadas en ese perfil y el puente las reutiliza.
    """
    import json as _json
    import shutil
    import subprocess
    import urllib.request
    from pathlib import Path

    bridge = Path(__file__).with_name("bridge")
    node = shutil.which("node")
    if not node:
        raise FileNotFoundError("Node.js no está instalado")
    find = subprocess.run([node, "-e", "import('./engine/chrome.mjs').then(m => process.stdout.write(m.findBrowser(process.argv[1] || '') || ''))",
                           browser or ""], cwd=bridge, capture_output=True, text=True)
    exe = find.stdout.strip()
    if find.returncode != 0 or not exe:
        raise FileNotFoundError((find.stderr.strip().splitlines() or ["No se encontró ningún navegador Chromium"])[-1])
    base = Path.home() / ".eolfi"
    profile = base / "browser-profile"
    lock = base / "login.lock"
    profile.mkdir(parents=True, exist_ok=True)

    # El puente no debe lanzar un navegador controlado mientras dura el inicio de sesión.
    import os as _os
    lock.write_text(str(_os.getpid()), encoding="utf-8")   # pid: el puente detecta un lock huérfano
    try:
        # Cerrar el navegador controlado por el puente (si está abierto) para liberar el perfil.
        port_file = profile / "DevToolsActivePort"
        if port_file.exists():   # versiones anteriores del puente: control por puerto TCP
            try:
                port = port_file.read_text(encoding="utf-8").split()[0]
                info = _json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3).read())
                _progress("Cerrando el navegador controlado por el puente para liberar el perfil...")
                _close_browser(info["webSocketDebuggerUrl"])
            except (OSError, ValueError, KeyError):
                pass
        # Puente actual: control por tubería (sin puerto). Se pide un cierre normal (guarda cookies
        # y sesiones); solo si no responde se fuerza más abajo.
        controlled = [pid for pid, debug in _profile_browsers(profile) if debug]
        if controlled:
            _progress("Cerrando el navegador controlado por el puente para liberar el perfil...")
            _close_gracefully(controlled)
        if not _wait_profile_free(profile):
            _progress("El navegador del perfil de Eolfi no se cerró a tiempo: terminando solo esos procesos...")
            _kill_profile_browsers(profile)
            if not _wait_profile_free(profile, 10):
                raise RuntimeError("El perfil de Eolfi sigue en uso por otro navegador; ciérralo y repite")
        port_file.unlink(missing_ok=True)

        _progress("Navegador normal abierto con el perfil de Eolfi (sin control remoto).")
        _progress("Inicia sesión en Google (Gemini), DeepSeek y Meta AI y, al terminar, CIERRA esa ventana del navegador.")
        import time as _time
        t0 = _time.time()
        r = subprocess.run([exe, f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                            "--new-window", *LOGIN_URLS])
        if _time.time() - t0 < 5 and _profile_browsers(profile):
            # El lanzador cedió la ventana a otro proceso con el mismo perfil: esperar a que se cierre.
            _progress("Esperando a que cierres la ventana del navegador...")
            while _profile_browsers(profile):
                _time.sleep(2)
    finally:
        lock.unlink(missing_ok=True)
    _progress("Sesiones guardadas en el perfil de Eolfi. Arranca el puente:  python -m eolfi bridge")
    return r.returncode


def _user_data_dir(cmd: str) -> str | None:
    """Valor de --user-data-dir en una línea de comandos (con o sin comillas, con = o espacio)."""
    import re

    m = re.search(r"""--user-data-dir(?:=|\s+)(?:"([^"]+)"|'([^']+)'|(\S+))""", cmd)
    return next((g for g in m.groups() if g), None) if m else None


def _same_path(a: str, b) -> bool:
    import os

    norm = lambda x: os.path.normcase(os.path.realpath(os.path.expanduser(str(x).strip())))  # noqa: E731
    return norm(a) == norm(b)


def _profile_browsers(profile) -> list[tuple[int, bool]]:
    """Procesos principales de navegador cuyo --user-data-dir es EXACTAMENTE el perfil de Eolfi:
    [(pid, con_depuración)]. Nunca coincide con «browser-profile2» ni con el Chrome personal."""
    import os
    import subprocess

    out: list[tuple[int, bool]] = []
    try:
        if os.name == "nt":
            ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -notmatch '--type=' } | "
                  "ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.CommandLine }")
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=60)
            lines = r.stdout.splitlines()
        else:
            r = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True, timeout=30)
            lines = [ln.strip().replace(" ", "|", 1) for ln in r.stdout.splitlines()]
    except (OSError, subprocess.TimeoutExpired):
        return []
    for ln in lines:
        pid, _, cmd = ln.partition("|")
        if "--type=" in cmd or not pid.strip().isdigit():
            continue
        udd = _user_data_dir(cmd)
        if udd and _same_path(udd, profile):
            out.append((int(pid), "remote-debugging" in cmd.lower()))
    return out


def _close_gracefully(pids: list[int]) -> None:
    """Cierre normal (como pulsar la X): Windows envía WM_CLOSE; en Unix, SIGTERM."""
    import os
    import signal
    import subprocess

    for pid in pids:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True, timeout=15)
            else:
                os.kill(pid, signal.SIGTERM)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _wait_profile_free(profile, seconds: float = 15) -> bool:
    import time

    end = time.time() + seconds
    while time.time() < end:
        if not _profile_browsers(profile):
            return True
        time.sleep(1)
    return False


def _kill_profile_browsers(profile) -> None:
    """Termina SOLO los navegadores que usan el perfil de Eolfi (nunca el Chrome personal)."""
    import os
    import signal
    import subprocess

    for pid, _debug in _profile_browsers(profile):
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass


def _close_browser(ws_url: str) -> None:
    """Cierra un Chrome con depuración remota mediante CDP (Browser.close), sin dependencias."""
    import base64
    import os
    import socket
    import struct
    import time
    from urllib.parse import urlsplit

    u = urlsplit(ws_url)
    s = socket.create_connection((u.hostname, u.port), timeout=5)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    s.recv(4096)
    payload = b'{"id":1,"method":"Browser.close"}'
    mask = os.urandom(4)
    frame = bytes([0x81, 0x80 | len(payload)]) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    s.sendall(frame)
    try:
        s.recv(4096)
    except OSError:
        pass
    s.close()
    time.sleep(2)


def _bridge_home(src):
    """Carpeta donde se instala y ejecuta el puente: la del código si se puede escribir en ella (desarrollo) o
    una copia en ~/.eolfi/bridge-app (paquete instalado en site-packages), renovada al cambiar de versión."""
    import os
    import shutil
    from pathlib import Path

    if os.access(src, os.W_OK) and not os.environ.get("EOLFI_BRIDGE_HOME"):
        return src
    dst = Path(os.environ.get("EOLFI_BRIDGE_HOME") or Path.home() / ".eolfi" / "bridge-app")
    stamp = dst / ".eolfi-version"
    from eolfi import __version__

    if not stamp.is_file() or stamp.read_text(encoding="utf-8").strip() != __version__:
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            if item.name == "node_modules":
                continue
            target = dst / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
        stamp.write_text(__version__, encoding="utf-8")
    return dst


def _run_bridge(install_only: bool, browser: str | None = None, engine: str | None = None) -> int:
    """Instala (la primera vez) y arranca el puente Electron de chats web."""
    import shutil
    import subprocess
    from pathlib import Path

    bridge = _bridge_home(Path(__file__).with_name("bridge"))
    npm = shutil.which("npm")
    if not npm:
        raise FileNotFoundError("Node.js/npm no está instalado (necesario para el puente Electron)")
    if not (bridge / "node_modules" / "electron").is_dir():
        _progress("Instalando Electron para el puente (solo la primera vez)...")
        r = subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=bridge)
        if r.returncode != 0:
            return r.returncode
    if install_only:
        _progress(f"Puente listo en {bridge}")
        return 0
    _progress("Abriendo el puente: inicia sesión en DeepSeek, Gemini, Meta AI y Le Chat en sus ventanas "
              f"({'navegador ' + browser if browser else 'navegador real instalado'}"
              f"{' / Electron' if engine == 'electron' else ''}).")
    _progress("Aviso: automatizar estas webs puede ir contra sus condiciones de uso; se usa tu cuenta.")
    import os

    env = dict(os.environ)
    # La terminal de VS Code exporta ELECTRON_RUN_AS_NODE=1: Electron arrancaría como Node y main.mjs fallaría
    # («does not provide an export named 'BrowserWindow'»).
    env.pop("ELECTRON_RUN_AS_NODE", None)
    if browser:
        env["EOLFI_BROWSER"] = browser
    if engine:
        env["EOLFI_ENGINE"] = engine
    npx = shutil.which("npx") or npm
    cmd = [npx, "electron", "."] if npx != npm else [npm, "start"]
    return subprocess.run(cmd, cwd=bridge, env=env).returncode


def _http_ok(url: str, headers: dict[str, str] | None = None, timeout: float = 3) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=timeout) as r:
            return 200 <= r.status < 300
    except (OSError, ValueError):
        return False


def _bridge_running() -> bool:
    from eolfi.generador.llm import LLMError, read_bridge

    try:
        b = read_bridge()
    except LLMError:
        return False
    return _http_ok(b["url"] + "/v1/status", {"Authorization": f"Bearer {b['token']}"})


def _kill_tree(proc) -> None:
    """Para un proceso y sus hijos (en Windows, terminate() deja vivos Electron/Chrome o eolas.exe)."""
    import subprocess

    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()


def _port_listening(host: str, port: int) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _wait_http(url: str, seconds: float) -> bool:
    import time

    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if _http_ok(url, timeout=2):
            return True
        time.sleep(0.5)
    return False


def _start_eolas(eolas_url: str, celtiaia, logs) -> bool:
    """Conecta con Eolas en local y, si no está, lo arranca con el launcher de CeltIA (D:\\celtiaia)."""
    import shutil
    import subprocess
    import urllib.parse

    tags = eolas_url + "/api/tags"
    if _http_ok(tags):
        _progress(f"Eolas ya está activo en {eolas_url}")
        return True
    u = urllib.parse.urlsplit(eolas_url)
    host, port = u.hostname or "127.0.0.1", u.port or 11435
    if host not in ("127.0.0.1", "localhost"):
        _progress(f"Aviso: Eolas apunta a {eolas_url}, que no es este equipo; no lo arranco.")
        return False
    if _port_listening(host, port):
        # Otro supervisor lo está levantando (o cargando el modelo): lanzar otro fallaría por el puerto ocupado.
        _progress(f"El puerto {port} está ocupado pero Eolas aún no responde; espero a que termine de arrancar...")
        if _wait_http(tags, 120):
            _progress(f"Eolas listo en {eolas_url}")
            return True
        _progress(f"Aviso: algo ocupa el puerto {port} y no responde como Eolas; sigo sin Eolas.")
        return False
    launcher = celtiaia / "launch-eolas.ps1"
    shell = shutil.which("powershell.exe") or shutil.which("pwsh")
    if not launcher.is_file() or not shell:
        _progress(f"Aviso: no encuentro {launcher} (o PowerShell); sigo sin Eolas. Usa --celtiaia o CELTIAIA_HOME.")
        return False
    _progress(f"Arrancando Eolas desde {celtiaia} (registro: {logs / 'eolas.log'})...")
    # Como «npm start» de CeltIA, en segundo plano (-Detach) y sin abrir su página (-NoBrowser).
    cmd = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launcher),
           "-Detach", "-NoBrowser", "-EolasPort", str(port)]
    with open(logs / "eolas.log", "ab") as log:
        try:
            r = subprocess.run(cmd, cwd=celtiaia, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                               timeout=180)
        except subprocess.TimeoutExpired:
            r = None
    if r is not None and r.returncode != 0:
        _progress(f"Aviso: el launcher de Eolas falló (código {r.returncode}); mira {logs / 'eolas.log'}")
        return False
    if _wait_http(tags, 60):
        _progress(f"Eolas listo en {eolas_url} (para pararlo: {launcher} -Stop)")
        return True
    _progress("Aviso: Eolas aún no responde; el panel lo detectará cuando esté listo.")
    return False


def _run_up(args) -> int:
    """`eolfi up`: Eolas local de CeltIA + puente de chats web + panel, en un solo comando. Lo que ya esté en
    marcha se reutiliza; al salir (Ctrl+C) se para lo arrancado aquí, salvo Eolas, que queda como servicio."""
    import subprocess
    import threading
    import time
    import webbrowser
    from pathlib import Path

    from eolfi.generador.llm import PRESETS

    logs = Path.home() / ".eolfi" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    started: list[tuple[str, subprocess.Popen]] = []
    os.environ.setdefault("EOLFI_DEFAULT_AI", "eolas")
    os.environ["EOLFI_BOOT_ID"] = str(int(time.time()))
    eolas_url = PRESETS["eolas"]["base_url"].rstrip("/")
    panel = f"http://127.0.0.1:{args.port}"

    try:
        # 1. Eolas (motor local de CeltIA). Es un servicio compartido con CeltIA: se lanza con -Detach (supervisor
        #    propio que reinicia Eolas si cae) y sigue activo al cerrar Eolfi; se para con launch-eolas.ps1 -Stop.
        if not args.no_eolas:
            _start_eolas(eolas_url, Path(args.celtiaia), logs)

        # 2. Puente de chats web: los proveedores web se eligen después en el panel, si hacen falta
        if args.no_bridge:
            pass
        elif _bridge_running():
            _progress("El puente de chats web ya está activo")
        else:
            env = dict(os.environ)
            env.pop("ELECTRON_RUN_AS_NODE", None)
            cmd = [sys.executable, "-m", "eolfi", "bridge"] + (["--browser", args.browser] if args.browser else [])
            log = open(logs / "bridge.log", "ab")  # noqa: SIM115
            proc = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            started.append(("puente", proc))
            _progress(f"Arrancando el puente de chats web (registro: {logs / 'bridge.log'})...")

        # 3. Panel
        if _http_ok(panel + "/api/health"):
            _progress(f"El panel de Eolfi ya estaba en {panel}: lo reutilizo (elige Eolas en «Proveedores» si no "
                      "sale por defecto). Ctrl+C para parar lo arrancado aquí.")
            if not args.no_open:
                webbrowser.open(panel)
            while any(p.poll() is None for _, p in started):
                time.sleep(1)
            return 0
        if not args.no_open:
            def _open():
                for _ in range(40):
                    if _http_ok(panel + "/api/health", timeout=1):
                        webbrowser.open(panel)
                        return
                    time.sleep(0.25)
            threading.Thread(target=_open, daemon=True).start()
        from eolfi import server

        if args.reload:
            return server.serve_with_reload(["--db", args.db, "serve", "--port", str(args.port)])
        return server.serve(args.db, "127.0.0.1", args.port, False, "samples")
    except KeyboardInterrupt:
        return 0
    finally:
        for name, proc in reversed(started):
            if proc.poll() is None:
                _progress(f"Parando {name}...")
                _kill_tree(proc)


def _vscode_login(server: str = "http://127.0.0.1:8777") -> int:
    """Vincula VS Code sin mostrar el código: lo pide al servidor local y lo pasa solo dentro del enlace vscode://."""
    import json as _json
    import os
    import urllib.request

    url = os.environ.get("EOLFI_SERVER", server).rstrip("/")
    req = urllib.request.Request(f"{url}/api/clients/pair", data=b"{}", method="POST",
                                 headers={"X-Eolfi": "1", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            code = _json.loads(r.read())["code"]
    except OSError as exc:
        raise RuntimeError(f"El servidor de Eolfi no responde en {url} (python -m eolfi serve): {exc}") from exc
    link = f"vscode://eolfi.eolfi-vscode-bridge/login?code={code}"
    if hasattr(os, "startfile"):
        os.startfile(link)  # noqa: S606 — enlace propio de VS Code
    else:
        import subprocess
        subprocess.call(["xdg-open" if sys.platform != "darwin" else "open", link])
    _progress("Abriendo VS Code para vincularlo (el código no se muestra). Si VS Code pregunta, permite abrir el enlace.")
    return 0


def _run_vscode(folder: str | None, install: bool, login: bool = False) -> int:
    """Carga la extensión eolfi/vscode-bridge en VS Code. Por defecto como «extensión en desarrollo» (no se instala
    nada: solo vive en esa ventana); con --install se copia a ~/.vscode/extensions."""
    import shutil
    import subprocess
    from pathlib import Path

    ext = Path(__file__).with_name("vscode-bridge")
    code = shutil.which("code") or shutil.which("code-insiders")
    if not code:
        raise FileNotFoundError("No se encuentra el comando «code» de VS Code (añádelo al PATH desde VS Code)")
    if login:
        return _vscode_login()
    if install:
        # VSIX propio (sin vsce) e instalación oficial: así aparece en «Extensiones» y en todas las ventanas.
        vsix = build_vsix(ext, Path.home() / ".eolfi")
        rc = subprocess.call([code, "--install-extension", str(vsix), "--force"])
        if rc == 0:
            _progress(f"Extensión instalada ({vsix.name}). En VS Code: Ctrl+Shift+P → «Reload Window». "
                      "Para quitarla: code --uninstall-extension eolfi.eolfi-vscode-bridge")
        return rc
    cmd = [code, "--new-window", f"--extensionDevelopmentPath={ext}"] + ([str(Path(folder).resolve())] if folder else [])
    _progress("Abriendo VS Code con el puente de Eolfi. La primera petición mostrará un aviso de VS Code para "
              "permitir que la extensión use los modelos de IA: acéptalo. Después: --provider copilot-vscode")
    return subprocess.call(cmd)


def build_vsix(ext, out_dir):
    """Empaqueta eolfi/vscode-bridge como .vsix (un zip con manifiesto) sin necesitar vsce ni npm."""
    import json as _json
    import zipfile
    from pathlib import Path
    from xml.sax.saxutils import escape

    ext, out_dir = Path(ext), Path(out_dir)
    meta = _json.loads((ext / "package.json").read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    vsix = out_dir / f"{meta['publisher']}.{meta['name']}-{meta['version']}.vsix"
    manifest = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" '
        'xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">\n'
        ' <Metadata>\n'
        f'  <Identity Language="en-US" Id="{escape(meta["name"])}" Version="{escape(meta["version"])}" '
        f'Publisher="{escape(meta["publisher"])}"/>\n'
        f'  <DisplayName>{escape(meta.get("displayName", meta["name"]))}</DisplayName>\n'
        f'  <Description xml:space="preserve">{escape(meta.get("description", ""))}</Description>\n'
        '  <Categories>Other</Categories>\n'
        '  <Properties>\n'
        f'   <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{escape(meta["engines"]["vscode"])}"/>\n'
        '  </Properties>\n'
        ' </Metadata>\n'
        ' <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation>\n'
        ' <Dependencies/>\n'
        ' <Assets><Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" '
        'Addressable="true"/></Assets>\n'
        '</PackageManifest>\n')
    types = ('<?xml version="1.0" encoding="utf-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
             'content-types"><Default Extension=".json" ContentType="application/json"/><Default Extension=".js" '
             'ContentType="application/javascript"/><Default Extension=".vsixmanifest" ContentType="text/xml"/>'
             '</Types>')
    with zipfile.ZipFile(vsix, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("extension.vsixmanifest", manifest)
        lic = ext.parent.parent / "LICENSE"
        if lic.is_file():
            z.write(lic, "extension/LICENSE.txt")
        for f in sorted(ext.iterdir()):
            if f.is_file() and f.suffix in (".js", ".json"):
                z.write(f, f"extension/{f.name}")
    return vsix


def _progress(msg: str) -> None:
    try:
        print(msg, file=sys.stderr, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode(), file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    from eolfi.dotenv import load_dotenv

    load_dotenv()   # secretos del .env (no pisa variables ya definidas; nunca se muestran)
    args = _parser().parse_args(argv)
    if args.cmd == "llama":
        from eolfi import llamacpp

        if args.accion == "start":
            _print(llamacpp.start())
        elif args.accion == "stop":
            _print({"stopped": llamacpp.stop()})
        elif args.accion == "config":
            llamacpp.load_config()
            print(llamacpp.config_file())
            if hasattr(os, "startfile"):
                os.startfile(llamacpp.config_file())  # noqa: S606 — abre tu propia configuración
        else:
            _print(llamacpp.status())
        return 0
    if args.cmd == "vscode":
        return _run_vscode(args.folder, args.install, args.login)
    if args.cmd == "vscode-do":
        from pathlib import Path as _P

        from eolfi.vscode_tools import vscode_action

        params: dict = {k: v for k, v in {"path": args.path, "line": args.line, "glob": args.glob, "text": args.text}.items() if v}
        if args.action == "write":
            if not args.content_file:
                raise ValueError("write necesita --content-file")
            params["content"] = _P(args.content_file).read_text(encoding="utf-8")
            params["reason"] = args.reason
        elif args.action == "command":
            params = {"command": args.name, "args": json.loads(args.input or "[]") if args.input != "{}" else []}
        elif args.action == "tool":
            params = {"name": args.name, "input": json.loads(args.input or "{}")}
        _print(vscode_action(args.action, **params))
        return 0
    if args.cmd == "corpus":
        from eolfi.corpus import run_corpus

        return run_corpus(args.library, dry_run=args.dry_run)
    if args.cmd == "mcp":
        from eolfi import mcp_server

        return mcp_server.main(args.db, args.root, args.library)
    if args.cmd == "up":
        return _run_up(args)
    if args.cmd == "serve":
        from eolfi import server

        if args.reload:
            if args.root:
                os.environ["EOLFI_ROOTS"] = os.pathsep.join(args.root)
            return server.serve_with_reload([a for a in argv if a != "--reload"])
        if args.root:   # el proceso con --reload hereda la variable
            os.environ["EOLFI_ROOTS"] = os.pathsep.join(args.root)
        return server.serve(args.db, args.host, args.port, args.allow_remote, args.samples)
    store = EvidenceStore(args.db)
    try:
        return _dispatch(args, store)
    except (FileNotFoundError, FileExistsError, ValueError, PermissionError, IsADirectoryError) as exc:
        if os.environ.get("EOLFI_DEBUG"):
            raise
        print(f"eolfi: error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
