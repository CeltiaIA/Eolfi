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
  spec build|show|diff|review|tests|contract --case ID
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
  autofix <proyecto> [--provider P] [--model M] [--base-url URL]   comprueba que no queden errores y los corrige
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

Opción global: --db RUTA (base de evidencias; por defecto EOLFI_DB o ~/.eolfi/eolfi.db). En «create», --db memory|sqlite
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


def _emit(text: str, end: str = "\n", ascii_fallback: str | None = None) -> None:
    """Escribe en stdout. Redirigido a archivo/tubería: bytes UTF-8 (15/11/2026).

    En Windows, con stdout redirigido, Python codifica con la página local (cp1252) y el JSON o el informe
    resultante no es UTF-8 válido. Si stdout no es una consola y expone `buffer`, se escriben los bytes UTF-8
    directamente. En consola se usa el flujo de texto; si no puede codificar, `ascii_fallback` o reemplazo.
    """
    out = sys.stdout
    buf = getattr(out, "buffer", None)
    try:
        tty = out.isatty()
    except (AttributeError, ValueError):
        tty = False
    if buf is not None and not tty:
        out.flush()   # conserva el orden con lo ya escrito por la capa de texto
        buf.write((text + end).encode("utf-8"))
        buf.flush()
        return
    try:
        out.write(text + end)
    except UnicodeEncodeError:   # consola Windows sin UTF-8
        if ascii_fallback is None:
            enc = getattr(out, "encoding", None) or "ascii"
            ascii_fallback = text.encode(enc, "replace").decode(enc)
        out.write(ascii_fallback + end)


def _print(obj) -> None:
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    _emit(text, ascii_fallback=json.dumps(obj, indent=2, ensure_ascii=True))


def _rsi_observar(fuente: str, operacion: str, resultado, contexto: dict | None = None) -> None:
    """Anota el resultado para la automejora (PLAN_REA.md, punto 12). Nunca rompe la orden que observa."""
    try:
        from eolfi import rsi

        rsi.observar(fuente, operacion, resultado, contexto=contexto)
    except Exception as exc:   # noqa: BLE001 — el registro es accesorio
        print(f"(RSI: no se pudo anotar la observación: {exc})", file=sys.stderr)


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
    ap.add_argument("--db", default=None,
                    help="Ruta de la base de evidencias (por defecto EOLFI_DB o ~/.eolfi/eolfi.db)")
    ap.add_argument("--version", action="version", version=f"eolfi {__version__}")
    ap.add_argument("--idioma", choices=("es", "en"), default=None,
                    help="Idioma de la ayuda (es o en; también EOLFI_IDIOMA)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    acc = sub.add_parser("acciones", help="Registro encadenado de acciones que cambian estado (B8)")
    acc_cmd = acc.add_subparsers(dest="acciones_action", required=True)
    acc_ver = acc_cmd.add_parser("verificar", help="Recalcula la cadena SHA-256 del registro")
    acc_ver.add_argument("--ancla", help="Archivo de anclas externo: comprueba también que cada ancla sigue en la cadena")
    acc_ver.add_argument("--clave", help="Archivo de clave (o EOLFI_ACCIONES_CLAVE): comprueba también las firmas")
    acc_ver.add_argument("--rsi", action="store_true",
                         help="Comprueba también la cadena del RSI y que cada evento reflejado coincide")
    acc_cla = acc_cmd.add_parser("clave", help="Crea una clave de firma de 32 bytes (guárdala fuera del equipo)")
    acc_cla.add_argument("--destino", required=True, help="Archivo nuevo, fuera del alcance de quien escribe el registro")
    acc_fir = acc_cmd.add_parser("firmar", help="Firma con HMAC-SHA256 la cabeza de la cadena")
    acc_fir.add_argument("--clave", help="Archivo de clave (o EOLFI_ACCIONES_CLAVE)")
    acc_anc = acc_cmd.add_parser("anclar", help="Copia la cabeza de la cadena a un archivo externo")
    acc_anc.add_argument("--destino", required=True, help="Archivo fuera del alcance de quien escribe el registro")
    acc_list = acc_cmd.add_parser("listar", help="Muestra los últimos eventos")
    acc_list.add_argument("-n", type=int, default=20)
    upd = sub.add_parser("update", help="Versión instalada y si hay otra publicada (solo comprueba, no instala)")
    upd.add_argument("--check", action="store_true", required=True, help="Comprobar; Eolfi nunca se actualiza solo")
    upd.add_argument("--red", action="store_true", help="Permite consultar api.github.com (sin credenciales)")
    upd.add_argument("--repo", help="propietario/nombre (por defecto CeltiaIA/Eolfi o EOLFI_UPDATE_REPO)")
    nav = sub.add_parser("navegador", help="Navegador, Playwright y axe propios de Eolfi para el juez funcional "
                                           "(en ~/.eolfi/navegador)")
    nav.add_argument("accion", nargs="?", choices=("estado", "instalar"), default="estado",
                     help="estado (por defecto) o instalar (descarga unos 100 MB de npm y cdn.playwright.dev)")
    nav.add_argument("--comprobar", action="store_true", help="Con estado: recalcula el SHA-256 del ejecutable")
    acd = sub.add_parser("acceso-directo", help="Lanzador de «eolfi up» en el escritorio o el menú (vista previa "
                                                "salvo con --aplicar)")
    acd.add_argument("--donde", choices=("escritorio", "menu"), default="escritorio")
    acd.add_argument("--carpeta", help="Otra carpeta para el lanzador (en lugar del escritorio o el menú)")
    acd.add_argument("--port", type=int, default=8777, help="Puerto del panel que abre el lanzador")
    acd_modo = acd.add_mutually_exclusive_group()
    acd_modo.add_argument("--aplicar", action="store_true", help="Crea el acceso directo")
    acd_modo.add_argument("--quitar", action="store_true", help="Retira el acceso directo de Eolfi")
    models = sub.add_parser("modelos", help="Modelos GGUF: auditoría, identidad y cuantización local")
    model_commands = models.add_subparsers(dest="modelos_action", required=True)
    ma = model_commands.add_parser("auditar", help="Comprueba estructura GGUF y SHA-256")
    ma.add_argument("archivo")
    ma.add_argument("--pid", type=int, help="Añade una instantánea de sockets de este PID (Windows)")
    mc = model_commands.add_parser("conexiones", help="Consulta sockets de un PID, sin iniciar el motor")
    mc.add_argument("--pid", type=int, required=True)
    mt = model_commands.add_parser("comprobar", help="Comprueba un hash contra un manifiesto autorizado")
    mt.add_argument("archivo")
    mt.add_argument("--manifiesto", required=True)
    mu = model_commands.add_parser("actualizar", help="G5: compara los modelos locales con lo publicado (abre la red con --red)")
    mu.add_argument("--fuentes", required=True, help="JSON eolfi.modelos.fuentes/v1 con repo, archivo y SHA-256 local")
    mu.add_argument("--nombre", help="Solo esta fuente")
    mu.add_argument("--red", action="store_true", help="Autoriza la consulta a la API pública de Hugging Face")
    md = model_commands.add_parser("descargar", help="G5: descarga un GGUF fijado por commit y SHA-256 y lo audita")
    md.add_argument("--repo", required=True)
    md.add_argument("--archivo", required=True)
    md.add_argument("--revision", required=True, help="Commit completo revisado con «modelos actualizar»")
    md.add_argument("--sha256", required=True, help="SHA-256 publicado y revisado")
    md.add_argument("--bytes", type=int, help="Tamaño publicado: se exige igual y se comprueba el espacio libre")
    md.add_argument("--out", required=True, help="Carpeta de destino; nunca se sobrescribe")
    md.add_argument("--red", action="store_true", help="Autoriza la descarga")
    mr = model_commands.add_parser("reconstruir", help="Prepara una receta de cuantización; ejecutar exige opción y hashes")
    mr.add_argument("archivo")
    mr.add_argument("--out", required=True, help="Carpeta nueva; nunca sobrescribe una anterior")
    mr.add_argument("--cuantizador", required=True, help="Ruta del ejecutable local llama-quantize")
    mr.add_argument("--tipo", choices=["Q4_0", "Q3_K_M", "Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0"], default="Q4_K_M")
    mr.add_argument("--sha256-entrada")
    mr.add_argument("--sha256-cuantizador")
    mr.add_argument("--sha256-paquete")
    mr.add_argument("--hilos", type=int, default=4)
    mr.add_argument("--memoria-mib", type=int, default=256)
    mr.add_argument("--timeout", type=float, default=1800)
    mr.add_argument("--ejecutar", action="store_true", help="Ejecuta el cuantizador; requiere los hashes de entrada y paquete")
    mp = model_commands.add_parser("probar", help="Prepara un smoke de inferencia en CPU de una reconstrucción; ejecutar exige opción y hash")
    mp.add_argument("carpeta", help="Carpeta de salida de `modelos reconstruir`, con receta.json y modelo.gguf")
    mp.add_argument("--ejecutor", required=True, help="Ruta del ejecutable local llama-cli")
    mp.add_argument("--sha256-paquete")
    mp.add_argument("--ejecutar", action="store_true")
    mp.add_argument("--pregunta")
    mp.add_argument("--esperado")
    mp.add_argument("--tokens", type=int, default=64)
    mp.add_argument("--hilos", type=int, default=4)
    mp.add_argument("--timeout", type=float, default=900)

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
    rc.add_argument("--target", default=None, choices=["python-cli", "python-http"],
                    help="Base generada (por defecto: la CLI si se observó; si no, la API HTTP observada)")
    rc.add_argument("--model", action="store_true", help="Solo muestra el modelo de comportamiento (no genera)")
    rc.add_argument("--mejora", action="append", default=[], metavar="ID[=VALOR]",
                    help="Mejora con razón verificable (seguridad-nosniff, seguridad-limite-cuerpo[=BYTES], "
                         "compatibilidad-utf8); se rechaza si rompe un requisito observado o no se puede comprobar")
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
                      ("tests", "Casos de prueba derivados solo de requisitos observados"),
                      ("contract", "Contrato de implementación: qué es seguro, inferido o desconocido")):
        x = sps.add_parser(name, help=hlp)
        x.add_argument("--case", dest="case_id", required=True)
        if name != "build":
            x.add_argument("--version", type=int, default=None)
        if name in ("tests", "contract"):
            x.add_argument("--out", default=None, help="Escribe el resultado en este archivo")
        if name == "contract":
            x.add_argument("--format", choices=["md", "json"], default="md")
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
    wb.add_argument("--render", action="store_true", help="Abre las páginas en Chrome sin interfaz (SPA) y rastrea el mismo origen")
    wb.add_argument("--paginas", type=int, default=1, help="Con --render: páginas como máximo (1-50)")
    wb.add_argument("--profundidad", type=int, default=1, help="Con --render: saltos de enlace desde la inicial (0-5)")
    wb.add_argument("--interactuar", type=int, default=0, metavar="N",
                    help="Con --render: pulsa hasta N controles sin efectos por página (0-30); nunca envía "
                         "formularios y solo deja salir peticiones GET")
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
                    choices=["auto", "static", "react", "vue", "svelte", "next", "fastapi", "express", "django", "expo", "desktop", "tauri", "cli", "dotnet", "go", "rust"])
    # Obsoleta (decisión del titular 2026-11-11): la verificación es siempre obligatoria. Se acepta y avisa; se
    # retirará en una versión posterior.
    cr.add_argument("--verify", action="store_true", default=False, help=argparse.SUPPRESS)
    # dest propio: con dest «db» pisaba el --db global y «create --db sqlite» creaba una base de
    # evidencias llamada «sqlite» en la carpeta actual (PLAN_MEJORAS servidor A1).
    cr.add_argument("--db", "--backend-db", dest="backend_db", choices=["memory", "sqlite"], default="memory",
                    help="Persistencia de los backends FastAPI/Express (sqlite: sin dependencias nuevas)")
    cr.add_argument("--auth", action="store_true",
                    help="Registro, inicio de sesión y token para las escrituras (FastAPI/Express)")
    cr.add_argument("--idioma-proyecto", dest="idioma_proyecto", choices=("es", "en"), default="es",
                    help="Idioma de la interfaz, las pruebas y los comentarios del proyecto generado (README y receta de despliegue incluidos)")
    cr.add_argument("--force", action="store_true", help="Escribe aunque la carpeta no esté vacía")
    cr.add_argument("--reanalyze", action="store_true", help="Vuelve a analizar fuentes ya conocidas")
    cr.add_argument("--workdir", default="samples/repos")
    _case_args(cr)
    cr.add_argument("--ai", dest="ai_brief", default=None,
                    help="Descripción para que la IA implemente la lógica de negocio")
    cr.add_argument("--juez", default=None, metavar="ARCHIVO",
                    help="Criterios del juez funcional (JSON): la app se prueba en Chrome y debe cumplirlos todos")
    cr_a11y = cr.add_mutually_exclusive_group()
    cr_a11y.add_argument("--accesibilidad", dest="accesibilidad", action="store_const", const=True, default=None,
                         help="Exige axe (WCAG A/AA) en tema claro y oscuro también en destinos que el juez no "
                              "cubre (por defecto ya se mide en static, react, vue y svelte)")
    cr_a11y.add_argument("--sin-accesibilidad", dest="accesibilidad", action="store_const", const=False,
                         help="No mide la accesibilidad con axe al verificar")
    cr.add_argument("--sin-autofix", dest="autofix", action="store_false", default=True,
                    help="Si la verificación falla, no pedir a la IA que corrija los errores (autofix)")
    for sp in (cr,):
        sp.add_argument("--provider", default=None, choices=["eolas", "eolas-v2", "celtia-v2", "deepseek-web", "gemini-web", "meta-web", "web"],
                    help="Proveedor de IA (por defecto, el motor local elegido con «eolfi motor-local»)")
        sp.add_argument("--model", default=None, help="Modelo del proveedor (por defecto, el de su preajuste)")
        sp.add_argument("--base-url", default=None, help="URL del servidor (p. ej. Eolas en otro puerto)")

    asg = sub.add_parser("assist", help="La IA implementa cambios en un proyecto generado (requiere proveedor configurado)")
    asg.add_argument("project", help="Carpeta de un proyecto creado con 'eolfi create'")
    asg.add_argument("--brief", required=True, help="Qué quieres que implemente")
    asg.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    asg.add_argument("--provider", default=None, choices=["eolas", "eolas-v2", "celtia-v2", "deepseek-web", "gemini-web", "meta-web", "web"],
                    help="Proveedor de IA (por defecto, el motor local elegido con «eolfi motor-local»)")
    asg.add_argument("--model", default=None)
    asg.add_argument("--base-url", default=None)

    afx = sub.add_parser("autofix", help="Comprueba que no queden errores en un proyecto generado y, si los hay, "
                                         "la IA los corrige (se deshace si no queda en verde)")
    afx.add_argument("project", help="Carpeta de un proyecto creado con 'eolfi create'")
    afx.add_argument("--provider", default=None, choices=["eolas", "eolas-v2", "celtia-v2", "deepseek-web", "gemini-web", "meta-web", "web"],
                    help="Proveedor de IA (por defecto, el motor local elegido con «eolfi motor-local»)")
    afx.add_argument("--model", default=None)
    afx.add_argument("--base-url", default=None)

    syn = sub.add_parser("sync", help="Vuelve a analizar las fuentes de un proyecto generado y propone los cambios "
                                      "con fusión a tres bandas (tus cambios se conservan)")
    syn.add_argument("project", help="Carpeta de un proyecto creado con 'eolfi create'")
    syn.add_argument("--aplicar", action="store_true",
                     help="Escribe los cambios (con copia de lo que toca en .eolfi-sync/) y verifica el resultado")
    syn.add_argument("--sin-verificar", dest="verificar", action="store_false", default=True,
                     help="Con --aplicar: no verificar (el resultado queda NO VERIFICADO)")
    syn.add_argument("--workdir", default="repos", help="Dónde clonar los repos remotos")

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

    eo = sub.add_parser("eolas-v2", help="Motor Eolas V2: perfiles Gemma/Mistral alternos, feedback y preparación de aprendizaje")
    eos = eo.add_subparsers(dest="eolas_action", required=True)
    eos.add_parser("status", help="Estado del único llama-server administrado por Eolas")
    # 18/11/2026 (titular: cambiar de modelo sin tocar código). El modelo se elige en eolas-v2.json con estas órdenes.
    eos.add_parser("perfiles", help="Catálogo: etiqueta, si se puede usar, roles y admisión de cada perfil")
    eos_alta = eos.add_parser("alta", help="Da de alta un GGUF local como perfil nuevo (no lo activa)")
    eos_alta.add_argument("profile", help="Nombre nuevo (minúsculas, cifras y guion bajo)")
    eos_alta.add_argument("gguf", help="Ruta del .gguf (la primera parte si viene troceado)")
    eos_alta.add_argument("--etiqueta", default="", help="Nombre visible, p. ej. «Qwen3 14B Q4»")
    eos_alta.add_argument("--alias", default="")
    eos_alta.add_argument("--ctx", type=int, default=16384)
    eos_alta.add_argument("--gpu-layers", type=int, default=99)
    eos_alta.add_argument("--batch", type=int, default=512)
    eos_alta.add_argument("--ubatch", type=int, default=512)
    eos_alta.add_argument("--razonamiento", choices=["deepseek"], default=None,
                          help="El modelo piensa en un bloque aparte (formato deepseek de llama-server)")
    eos_alta.add_argument("--plantilla", choices=["mistral"], default=None,
                          help="Reglas de conversación de Mistral Instruct (sin mensaje de sistema propio)")
    eos_alta.add_argument("--sha256", default=None, help="SHA-256 revisado del GGUF (opcional)")
    eos_activo = eos.add_parser("activo", help="Elige el perfil activo (sin arrancarlo); los nuevos deben estar admitidos")
    eos_activo.add_argument("profile")
    eos_rol = eos.add_parser("rol", help="Asigna un perfil a un papel: rapido, completo, redactor, revisor…")
    eos_rol.add_argument("rol")
    eos_rol.add_argument("profile")
    eos_examen = eos.add_parser("examen", help="Ronda completa de un perfil (código y herramientas): decide su admisión. "
                                              "CARGA el modelo y necesita Docker")
    eos_examen.add_argument("profile")
    eos_plan = eos.add_parser("plan", help="Valida una reconstrucción y propone un perfil sin adoptarlo")
    eos_plan.add_argument("carpeta", help="Carpeta creada por `modelos reconstruir`, con smoke superado")
    eos_plan.add_argument("--profile", required=True, help="Nombre nuevo del perfil (minúsculas y guion bajo)")
    eos_plan.add_argument("--alias")
    eos_plan.add_argument("--ctx", type=int, default=32000)
    eos_plan.add_argument("--gpu-layers", type=int, default=8)
    eos_plan.add_argument("--batch", type=int, default=128)
    eos_plan.add_argument("--ubatch", type=int, default=64)
    eos_adopt = eos.add_parser("adoptar", help="Revalida un plan y añade el perfil sin activarlo")
    eos_adopt.add_argument("plan", help="JSON producido y revisado por `eolas-v2 plan`")
    eos_adopt.add_argument("--sha256-modelo", required=True, help="SHA-256 revisado del modelo")
    eos_adopt.add_argument("--aplicar", action="store_true", help="Escribe el perfil; sin esta opción solo muestra la vista previa")
    eos_remove = eos.add_parser("quitar-perfil", help="Quita un perfil reconstruido gestionado, conservando el GGUF")
    eos_remove.add_argument("profile")
    eos_remove.add_argument("--sha256-modelo", required=True)
    eos_recommend = eos.add_parser("recomendar-perfil", help="Propone el ganador de un banco reciente; no cambia nada por defecto")
    eos_recommend.add_argument("--bateria", choices=["completa", "codigo", "json"], default="completa")
    eos_recommend.add_argument("--antiguedad-dias", type=int, default=30)
    eos_recommend.add_argument("--aplicar", action="store_true", help="Selecciona el perfil recomendado como activo")
    eos_start = eos.add_parser("start", help="Arranca el perfil activo (o el indicado)")
    eos_start.add_argument("--profile", default=None)
    eos_switch = eos.add_parser("switch", help="Detiene el perfil activo y arranca el otro")
    eos_switch.add_argument("profile")
    eos.add_parser("stop", help="Detiene solo el llama-server que inició Eolas")
    eos_review = eos.add_parser("revisar", help="Revisa la cabecera del GGUF de un perfil (o una ruta) con REA")
    eos_review.add_argument("objetivo", help="perfil Eolas V2 o ruta a un .gguf/.safetensors")
    eos_retire = eos.add_parser("retire", help="Retira un perfil que no aprueba (conserva su GGUF)")
    eos_retire.add_argument("profile")
    eos_uninstall = eos.add_parser("uninstall", help="Desinstala un motor: retira el perfil y borra su GGUF y sus lecciones")
    eos_uninstall.add_argument("profile")
    eos_restore = eos.add_parser("restore", help="Vuelve a ofrecer un perfil retirado")
    eos_restore.add_argument("profile")
    eos_consent = eos.add_parser("feedback-consent", help="Activa o desactiva el almacenamiento local de feedback")
    eos_consent.add_argument("state", choices=["on", "off"])
    eos_feedback = eos.add_parser("feedback-add", help="Guarda una valoración explícita localmente")
    eos_feedback.add_argument("--profile", required=True)
    eos_feedback.add_argument("--task", required=True, help="Dominio/tarea, p. ej. 'python' o 'resumen'")
    eos_feedback.add_argument("--rating", type=int, choices=range(1, 6), required=True)
    eos_feedback.add_argument("--prompt", default=None)
    eos_feedback.add_argument("--prompt-file", default=None)
    eos_feedback.add_argument("--response", default=None)
    eos_feedback.add_argument("--response-file", default=None)
    eos_feedback.add_argument("--consent", action="store_true", help="Consiento guardar prompt y respuesta saneados")
    eos_delete = eos.add_parser("feedback-delete", help="Borra un registro local de feedback por id")
    eos_delete.add_argument("record_id")
    eos_export = eos.add_parser("feedback-export", help="Exporta solo registros con consentimiento a JSONL")
    eos_export.add_argument("out")
    eos_import = eos.add_parser("feedback-import", help="Importa JSONL validado sin duplicar ids")
    eos_import.add_argument("source")
    eos_data = eos.add_parser("dataset", help="Prepara JSONL SFT/preferencias desde valoraciones humanas")
    eos_data.add_argument("kind", choices=["sft", "preference"])
    eos_data.add_argument("--out", required=True)
    eos_data.add_argument("--min-examples", type=int, default=20)
    eos_cal = eos.add_parser("calibrate", help="Recomienda perfil por tarea usando valoraciones humanas")
    eos_cal.add_argument("task")
    eos_check = eos.add_parser("training-check", help="Comprueba si hay checkpoint HF, dataset y dependencias para entrenar")
    eos_check.add_argument("--checkpoint", required=True)
    eos_check.add_argument("--dataset", required=True)
    eos_train = eos.add_parser("train-sft", help="Entrena un adaptador QLoRA SFT aislado desde checkpoint/dataset locales")
    eos_train.add_argument("--checkpoint", required=True)
    eos_train.add_argument("--dataset", required=True)
    eos_train.add_argument("--out", required=True)
    eos_start.add_argument("--liberar-eolas", action="store_true",
                           help="Pide antes a Eolas (11435) que descargue su modelo de la GPU")
    eos_train.add_argument("--epochs", type=float, default=1.0)
    eos_train.add_argument("--max-seq-length", type=int, default=1024)
    eos_train.add_argument("--consent", action="store_true", help="Autoriza uso de GPU y escritura de un adaptador nuevo")

    lm = sub.add_parser("llama", help="Servidor llama.cpp antiguo de Eolfi: estado y parada (arrancar está retirado: usa Eolas o eolas-v2)")
    lm.add_argument("accion", nargs="?", default="status", choices=["status", "start", "stop", "config"])

    vs = sub.add_parser("vscode", help="Abre VS Code con la extensión de Eolfi (agente @eolfi, herramientas y auditoría)")
    vs.add_argument("folder", nargs="?", default=None, help="Carpeta que abrir en VS Code (opcional)")
    vs.add_argument("--login", action="store_true",
                    help="vincula VS Code con tu Eolfi sin mostrar ningún código (abre un enlace vscode://)")
    vs.add_argument("--install", action="store_true",
                    help="Instala la extensión de forma permanente (por defecto se carga solo en una ventana de desarrollo)")

    co = sub.add_parser("corpus", help="Guarda el código y los textos de las fuentes compartidas en el corpus de Alejandría")
    co.add_argument("--library", default=os.environ.get("EOLFI_LIBRARY") or _default_library(),
                    help="Carpeta de la biblioteca (EOLFI_LIBRARY, o Alejandria en la carpeta personal o en D:)")
    co.add_argument("--dry-run", action="store_true", help="Muestra qué se importaría sin copiar nada")
    ds = sub.add_parser("dataset", help="Conjunto de datos para entrenar modelos (SFT en chat y preentrenamiento) a "
                                        "partir del corpus de Alejandría: verificado, sin duplicados y con privacidad")
    ds.add_argument("--library", default=os.environ.get("EOLFI_LIBRARY") or _default_library(),
                    help="Carpeta de la biblioteca (EOLFI_LIBRARY, o Alejandria en la carpeta personal o en D:)")
    ds.add_argument("--dry-run", action="store_true", help="Muestra los recuentos sin escribir nada")

    # REA a través de Eolfi (plan PLAN_REA.md): mismas herramientas compuestas que usa el chat de Eolas V2.
    rp = sub.add_parser("rea", help="Ingeniería inversa con REA a través de Eolfi (estático: nunca ejecuta el objetivo)")
    rp.add_argument("--caso", default=None, help="Registra el resultado en este caso (artefacto, evidencia e incógnitas)")
    rp.add_argument("--paquete", default=None, metavar="CARPETA",
                    help="Guarda en esta carpeta nueva el paquete completo: evidencias de REA, resultado, caso y "
                         "manifiesto con SHA-256")
    rps = rp.add_subparsers(dest="rea_action", required=True)
    rcp = rps.add_parser("comprobar-paquete", help="Comprueba los SHA-256 de un paquete hecho con --paquete (sin REA)")
    rcp.add_argument("carpeta")
    r1 = rps.add_parser("revisar-modelo", help="Cabecera de un GGUF/safetensors y si la cuantización coincide")
    r1.add_argument("ruta")
    r2 = rps.add_parser("explicar", help="Explica un ejecutable: importaciones, cadenas y funciones clave (Ghidra)")
    r2.add_argument("ruta")
    r2.add_argument("--funciones", type=int, default=5)
    r3 = rps.add_parser("reimplementar", help="Pseudocódigo, firma y llamadas de una función para reimplementarla")
    r3.add_argument("ruta")
    r3.add_argument("funcion", help="nombre o dirección (p. ej. entry o 0x140001010)")
    for sp in (r2, r3):
        sp.add_argument("--motor", choices=["ghidra", "kuna"], default="ghidra",
                        help="Descompilador: ghidra (REA de Windows) o kuna (REA de WSL2; solo ELF y Mach-O)")
    r5 = rps.add_parser("inventario", help="Librerías, firmas, recursos y dependencias Go/Rust de un binario")
    r5.add_argument("ruta")
    r6 = rps.add_parser("app-js", help="Analiza una app JavaScript, Electron o web (carpeta o .asar) sin ejecutarla")
    r6.add_argument("ruta")
    r7 = rps.add_parser("recuperar-js", help="Reconstruye fuentes legibles de un JavaScript minificado (Wakaru en WSL2)")
    r7.add_argument("ruta")
    r7.add_argument("destino", help="carpeta nueva o vacía donde guardar los módulos recuperados")
    r8 = rps.add_parser("api", help="De una captura de red (.pcap/.pcapng) a un borrador de API (OpenAPI si hay tshark en WSL)")
    r8.add_argument("ruta")
    r8.add_argument("--cliente", metavar="ARCHIVO.py", help="genera además un cliente Python (solo biblioteca estándar) con las operaciones observadas; no sobrescribe")
    r10 = rps.add_parser("firmware", help="Desglose de una imagen de firmware: firmas, regiones y huecos (Binwalk 3.1.0 en WSL2)")
    r10.add_argument("ruta")
    r10.add_argument("--extraer", metavar="DESTINO", help="extrae el contenido con Unblob 26.6.4 en esta carpeta nueva (sin montar ni ejecutar nada)")
    r10.add_argument("--profundidad", type=int, help="profundidad máxima de extracción (con --extraer)")
    r9 = rps.add_parser("entorno", help="De una captura web (.har) a un entorno para agentes de REA (AgentEnv); ensayo salvo --escribir")
    r9.add_argument("ruta")
    r9.add_argument("destino", help="carpeta nueva (ruta absoluta) donde escribir el paquete")
    r9.add_argument("--nombre", help="nombre del entorno (obligatorio si el origen es localhost o una IP)")
    r9.add_argument("--escribir", action="store_true", help="escribe el paquete; sin esto solo informa de lo que contendría")
    r11 = rps.add_parser("mapa-app", help="Mapa de una app Android (.apk): permisos, componentes exportados y estructura (JADX)")
    r11.add_argument("ruta")
    r11.add_argument("--limite", type=int, default=40, help="máximo de componentes y bibliotecas listados (40)")
    r12 = rps.add_parser("llamadas", help="Grafo de llamadas de una función (Ghidra), con nombres y en Mermaid")
    r12.add_argument("ruta")
    r12.add_argument("funcion", help="nombre (p. ej. entry) o dirección (0x140001cb0)")
    r12.add_argument("--atras", action="store_true", help="quién la llama, en vez de a quién llama")
    r12.add_argument("--profundidad", type=int, default=3, help="niveles (1-10, 3 por defecto)")
    r12.add_argument("--max-nodos", type=int, default=60, help="máximo de nodos (2-300, 60 por defecto)")
    r13 = rps.add_parser("dotnet", help="Qué hay en un ensamblado .NET: identidad, referencias, tipos, cadenas y P/Invoke (REA de WSL2)")
    r13.add_argument("ruta")
    r13.add_argument("--limite", type=int, default=30, help="máximo de elementos por lista (30)")
    r13.add_argument("--salida", help="ruta .json nueva para el volcado completo (tipos, métodos, cadenas, P/Invoke)")
    r14 = rps.add_parser("clase", help="Clases y métodos de un APK descompilados con JADX, sin ejecutar la app")
    r14.add_argument("ruta")
    r14.add_argument("consulta", help="nombre completo de la clase o un trozo (distingue mayúsculas)")
    r14.add_argument("--metodo", help="método que se descompila")
    r14.add_argument("--sobrecarga", type=int, help="índice de la sobrecarga si el método tiene varias")
    r14.add_argument("--limite", type=int, default=40, help="máximo de elementos por lista (40)")
    r15 = rps.add_parser("flutter", help="Qué hay en una app Flutter: motor, snapshot Dart y paquetes, sin ejecutarla")
    r15.add_argument("ruta")
    r15.add_argument("--abi", help="ABI del snapshot que se examina (por defecto la que elija REA)")
    r15.add_argument("--limite", type=int, default=40, help="máximo de elementos por lista (40)")
    r16 = rps.add_parser("apple", help="Mapa de una app de Apple (.app, .zip, .ipa o .dmg): bundles, ejecutables e Info.plist, sin ejecutarla")
    r16.add_argument("ruta")
    r16.add_argument("--limite", type=int, default=40, help="máximo de elementos por lista (40)")
    r17 = rps.add_parser("devicetree", help="Mapa del hardware de un devicetree (.dtb): placa, CPU, memoria y dispositivos")
    r17.add_argument("ruta")
    r17.add_argument("--filtro", help="texto en la ruta o en compatible para acotar los dispositivos")
    r17.add_argument("--limite", type=int, default=40, help="máximo de elementos por lista (40)")
    r17 = rps.add_parser("swift", help="Tipos Swift y clases Objective-C de una app de Apple (Ghidra en el REA de WSL), sin macOS")
    r17.add_argument("ruta", help=".app, .zip, .ipa o ejecutable Mach-O")
    r17.add_argument("--arquitectura", help="porción del ejecutable universal (arm64 por defecto)")
    r17.add_argument("--limite", type=int, default=60, help="máximo de elementos por lista (60)")
    r18 = rps.add_parser("go", help="Ejecutable Go: versión de Go, módulo, dependencias y ajustes de compilación, sin ejecutarlo")
    r18.add_argument("ruta")
    r18.add_argument("--limite", type=int, default=60, help="máximo de dependencias listadas (60)")
    r19 = rps.add_parser("rust", help="Ejecutable Rust con cargo-auditable: crates, raíz y dependencias directas, sin ejecutarlo")
    r19.add_argument("ruta")
    r19.add_argument("--limite", type=int, default=60, help="máximo de paquetes listados (60)")
    r18 = rps.add_parser("senal", help="Decodifica una grabación de analizador lógico (.sr, VCD, CSV) con sigrok en el REA de WSL")
    r18.add_argument("ruta")
    r18.add_argument("--decodificadores", required=True,
                     help="pila de sigrok, p. ej. uart:rx=TX:baudrate=9600 o i2c:scl=scl:sda=sda,edid")
    r18.add_argument("--anotaciones", help="clases de anotación, p. ej. uart=rx-data")
    r18.add_argument("--formato", help="formato de entrada de sigrok (por defecto lo detecta)")
    r18.add_argument("--limite", type=int, default=40, help="máximo de la muestra (40)")
    r20 = rps.add_parser("unity", help="Juego o app de Unity con IL2CPP: ensamblados, tipos y métodos con su dirección "
                                       "(global-metadata.dat y binario nativo), sin ejecutarlo")
    r20.add_argument("ruta", help="carpeta de la compilación, .apk, .ipa, .zip o global-metadata.dat")
    r20.add_argument("--binario", help="GameAssembly.dll/.so/.dylib, libil2cpp.so o UnityFramework de 64 bits "
                                       "(por defecto lo busca junto a los metadatos)")
    r20.add_argument("--tipo", help="nombre exacto de un tipo: sus métodos con la RVA")
    r20.add_argument("--limite", type=int, default=40, help="máximo de elementos por lista (40)")
    r19 = rps.add_parser("decodificadores", help="Decodificadores de sigrok instalados, o la ayuda de uno (--ayuda ID)")
    r19.add_argument("consulta", nargs="?", help="texto que buscar en el identificador o el nombre")
    r19.add_argument("--ayuda", metavar="ID", help="canales, opciones y anotaciones de un decodificador")
    r4 = rps.add_parser("comparar", help="Qué cambió entre dos versiones, con el veredicto verificable de REA")
    r4.add_argument("original")
    r4.add_argument("nueva")
    rw = rps.add_parser("wasm", help="Módulo WebAssembly sin ejecutarlo: validez, secciones, importaciones y "
                                     "exportaciones (WABT 1.0.42)")
    rw.add_argument("ruta")
    rw.add_argument("--frente", default=None, metavar="OTRO.wasm",
                    help="otra versión del módulo: compara sus importaciones y exportaciones")
    rw.add_argument("--js", action="append", default=[], metavar="CARGADOR.js",
                    help="JavaScript que carga el módulo (repetible): dónde lo nombra, sin ejecutarlo")
    rw.add_argument("--limite", type=int, default=40)

    # Automejora recursiva acotada (PLAN_REA.md, punto 12): observa, propone, evalúa y el titular decide.
    rs = sub.add_parser("rsi", help="Automejora recursiva acotada: propuestas evaluadas que el titular aprueba o revierte")
    rss = rs.add_subparsers(dest="rsi_action", required=True)
    rss.add_parser("estado", help="Observaciones, casos de regresión, propuestas, reglas y registro")
    rss.add_parser("verificar", help="Comprueba la cadena SHA-256 del registro")
    rss.add_parser("proponer", help="Propone cambios a partir de los síntomas repetidos")
    rse = rss.add_parser("evaluar", help="Línea base contra candidata con un banco de pruebas (CARGA el modelo local)")
    rse.add_argument("id")
    rse.add_argument("--banco", choices=["tareas", "contador", "filtro", "todos"], default="tareas")
    rse.add_argument("--proveedor", required=True, help="Proveedor de create --ai: eolas o eolas-v2")
    rse.add_argument("--modelo", default=None)
    rse.add_argument("--muestras", type=int, default=5, help="Pares base/candidata (mínimo 5)")
    rse.add_argument("--margen", type=float, default=0.05)
    rse.add_argument("--alfa", type=float, default=0.05, help="Nivel de la prueba exacta de signos")
    rsa = rss.add_parser("aa", help="Prueba A/A del evaluador con el banco real (CARGA el modelo local)")
    rsa.add_argument("--banco", choices=["tareas", "contador", "filtro", "todos"], default="tareas")
    rsa.add_argument("--proveedor", required=True, help="Proveedor de create --ai: eolas o eolas-v2")
    rsa.add_argument("--modelo", default=None)
    rsa.add_argument("--muestras", type=int, default=5)
    rsa.add_argument("--simulada", type=float, default=None, metavar="DESVIACION",
                     help="A/A simulada con esa desviación típica, sin cargar nada")
    for name, text in (("aprobar", "Aplica una propuesta evaluada con éxito"), ("rechazar", "Descarta una propuesta"),
                       ("revertir", "Devuelve una propuesta aplicada a su valor anterior")):
        r_ = rss.add_parser(name, help=text)
        r_.add_argument("id")
        r_.add_argument("--por", required=True, help="Quién decide (queda en el registro)")

    tl = sub.add_parser("telemetria", help="Telemetría local: tiempos y rendimiento por fase (no sale del equipo)")
    tl.add_argument("telemetria_action", choices=["resumen", "ruta"], nargs="?", default="resumen")
    vz = sub.add_parser("voz", help="Voz local: voz a texto y texto a voz sin que el audio salga del equipo")
    vzs = vz.add_subparsers(dest="voz_action", required=True)
    vzs.add_parser("estado", help="Motores disponibles, idioma y voces")
    vzs.add_parser("microfonos", help="Micrófonos de Windows: cuál es el predeterminado, si está silenciado o desconectado")
    vzt = vzs.add_parser("transcribir", help="Voz a texto de un WAV (PCM de 16 bits)")
    vzt.add_argument("archivo")
    vzt.add_argument("--idioma", default=None, help="Por ejemplo es-ES")
    vzm = vzs.add_parser("dictar", help="Graba del micrófono del equipo y lo transcribe (nada se guarda)")
    vzm.add_argument("--segundos", type=float, default=8, help="Duración de la grabación (1-30 s)")
    vzm.add_argument("--idioma", default=None)
    vzd = vzs.add_parser("decir", help="Texto a voz: escribe un WAV")
    vzd.add_argument("texto")
    vzd.add_argument("--out", required=True, help="Archivo WAV de salida")
    vzd.add_argument("--idioma", default=None)
    vzd.add_argument("--voz", default=None)
    vzc = vzs.add_parser("configurar", help="Elige motor, idioma o voz")
    vzc.add_argument("--motor", choices=["auto", "windows", "whisper"], default=None)
    vzc.add_argument("--idioma", default=None)
    vzc.add_argument("--voz", default=None)
    mc = sub.add_parser("mcp", help="Servidor MCP por stdio (Copilot en modo agente, Claude Code…)")
    mc.add_argument("--root", action="append", default=[], metavar="CARPETA",
                    help="Carpeta permitida para rutas locales (repetible; también EOLFI_ROOTS)")
    mc.add_argument("--library", default=os.environ.get("EOLFI_LIBRARY") or _default_library(),
                    help="Biblioteca Alejandría local (también EOLFI_LIBRARY)")

    ml = sub.add_parser("motor-local", help="Muestra o elige el motor local compartido: eolas-v1 (CeltIA, 11435) "
                                            "o eolas-v2 (Eolfi, 8090)")
    ml.add_argument("motor", nargs="?", default=None, help="eolas-v1 | eolas-v2 (sin valor, muestra el actual)")

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
    sv.add_argument("--cert", default=None, metavar="PEM",
                    help="Sirve por HTTPS con este certificado (el móvil solo deja usar el micrófono con HTTPS)")
    sv.add_argument("--key", default=None, metavar="PEM", help="Clave privada del certificado de --cert")
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

    from eolfi.spec import (build_contract, contract_markdown, diff_specs, latest_spec, review_requirement,
                            spec_tests, store_spec)

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
        elif args.spec_cmd == "contract":
            spec = latest_spec(store, args.case_id, args.version)
            if spec is None:
                _print({"error": "el caso no tiene especificación: ejecuta eolfi spec build"})
                return 1
            c = build_contract(spec)
            text = contract_markdown(c) if args.format == "md" else json.dumps(c, ensure_ascii=False, indent=2)
            if args.out:
                Path(args.out).write_text(text, encoding="utf-8")
                _print({"out": args.out, "format": args.format, "requirements": len(c["requirements"]),
                        **{k: len(v) for k, v in c["summary"].items()}})
            else:
                _emit(text)
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
            rep = reconstruct(store, args.case_id, args.out, name=args.name, target=args.target,
                              improvements=args.mejora)
        except ValueError as exc:
            _print({"error": str(exc)})
            return 1
        rep.pop("model")
        _print(rep)
        v = rep["verification"]
        return 0 if v["differ"] == 0 and v["partial"] == 0 and v["pending"] == 0 and v["match"] > 0 \
            and v["build"]["status"] == "ok" and v["independence"]["status"] != "copia" \
            and v["improvements_verified"] is not False else 4
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
                _emit(text, end="")
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
                      case_id=args.case_id, provenance=args.provenance, render=args.render,
                      max_pages=args.paginas, max_depth=args.profundidad, interact=args.interactuar)
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

        ctx = {"proveedor": args.provider or "", "modelo": args.model or "", "destino": args.target}
        if args.juez:
            from pathlib import Path as _Path

            from eolfi.generador import juez as _juez

            try:
                _juez.validar(json.loads(_Path(args.juez).read_text(encoding="utf-8")))
            except (OSError, ValueError) as exc:
                print(f"create: criterios del juez inválidos: {exc}", file=sys.stderr)
                return 2
        try:
            rep = create_project(args.sources, store, args.out, name=args.name, target=args.target,
                                 do_verify=True, force=args.force, reanalyze=args.reanalyze,
                                 workdir=args.workdir, ai_brief=args.ai_brief, ai_provider=args.provider,
                                 ai_model=args.model, ai_base_url=args.base_url, db=args.backend_db, auth=args.auth,
                                 progress=_progress, case_id=args.case_id, provenance=args.provenance,
                                 autofix=args.autofix, juez=args.juez, accesibilidad=args.accesibilidad,
                                 idioma=args.idioma_proyecto)
        except Exception as exc:
            if args.ai_brief:
                _rsi_observar("generador", "create_ai", {"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ctx)
            raise
        rep.pop("spec", None)
        if args.ai_brief and rep.get("assist"):
            a = rep["assist"]
            _rsi_observar("generador", "create_ai", {"ok": bool(a.get("ok")), "rondas": len(a.get("rounds") or []),
                                                     "fallos": [r.get("failed_step") for r in a.get("rounds") or []
                                                                if r.get("failed_step")]}, ctx)
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
    elif args.cmd == "autofix":
        from eolfi.flows.create_flow import run_autofix
        from eolfi.generador.assist import AssistError

        try:
            rep = run_autofix(store, args.project, provider=args.provider, model=args.model,
                              base_url=args.base_url, progress=_progress)
        except AssistError as exc:
            raise ValueError(str(exc)) from exc
        _print(rep)
        return 0 if rep["ok"] else 5
    elif args.cmd == "sync":
        from eolfi.flows.sync_flow import sync_project

        rep = sync_project(store, args.project, aplicar=args.aplicar, verificar=args.verificar, workdir=args.workdir,
                           progress=_progress)
        _print(rep)
        if rep["summary"]["conflicto"]:
            return 3
        return 0 if not rep["applied"] or rep["verification"]["ok"] else 5
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
            _emit(text, end="")
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
            _emit(f"// {fn['name']} @ {fn['entry']}" + ("" if fn["ok"] else f"  (error: {fn['error']})"))
            _emit(fn["c"] or "")
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


def _wait_http(url: str, seconds: float, headers: dict[str, str] | None = None) -> bool:
    import time

    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if _http_ok(url, headers, timeout=2):
            return True
        time.sleep(0.5)
    return False


def _start_eolas(eolas_url: str, celtiaia, logs) -> bool:
    """Conecta con Eolas en local y, si no está, lo arranca con el launcher de CeltIA (D:\\celtiaia)."""
    import shutil
    import subprocess
    import urllib.parse

    from eolfi.local_gpu import eolas_v1_headers

    tags = eolas_url + "/api/tags"
    # Con la clave de API (launch-eolas.ps1 la crea en runtime\eolas\api.key) /api/tags responde 401 sin ella.
    if _http_ok(tags, eolas_v1_headers(eolas_url)):
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
        if _wait_http(tags, 120, eolas_v1_headers(eolas_url)):
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
    # La clave puede haberse creado en este arranque: se vuelve a leer.
    if _wait_http(tags, 60, eolas_v1_headers(eolas_url)):
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
    from eolfi.local_gpu import local_engine, local_provider

    engine = local_engine()
    os.environ.setdefault("EOLFI_DEFAULT_AI", local_provider())
    os.environ["EOLFI_BOOT_ID"] = str(int(time.time()))
    eolas_url = PRESETS["eolas"]["base_url"].rstrip("/")
    panel = f"http://127.0.0.1:{args.port}"

    try:
        # 1. Eolas (motor local de CeltIA). Es un servicio compartido con CeltIA: se lanza con -Detach (supervisor
        #    propio que reinicia Eolas si cae) y sigue activo al cerrar Eolfi; se para con launch-eolas.ps1 -Stop.
        if not args.no_eolas and engine == "eolas-v2":
            _progress("Motor local: Eolas V2 (8090); se arranca al usarlo («python -m eolfi eolas-v2 start»). "
                      "Para usar Eolas V1 de CeltIA: «python -m eolfi motor-local eolas-v1».")
        elif not args.no_eolas:
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
              "permitir que la extensión use los modelos de IA: acéptalo.")
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
    from eolfi import i18n

    if i18n.idioma_cli(argv) != "en":
        return _main(argv)
    # C1 (18/11/2026): con --idioma en, los avisos por stderr también en inglés. La salida estándar (JSON) no cambia.
    anterior = sys.stderr
    sys.stderr = i18n.StderrTraducido(anterior)
    try:
        return _main(argv)
    finally:
        try:
            sys.stderr.flush()
        finally:
            sys.stderr = anterior


def _main(argv: list[str]) -> int:
    from eolfi.dotenv import load_dotenv

    load_dotenv()   # secretos del .env (no pisa variables ya definidas; nunca se muestran)
    from eolfi import i18n

    parser = _parser()
    i18n.traducir_parser(parser, i18n.idioma_cli(argv))   # C1: ayuda en inglés con --idioma en o EOLFI_IDIOMA=en
    args = parser.parse_args(argv)
    if hasattr(args, "provider") and args.provider is None:
        from eolfi.generador.llm import default_provider

        args.provider = default_provider()
    if args.cmd == "acciones":
        from eolfi import acciones

        if args.acciones_action == "verificar":
            result = acciones.verificar_anclas(args.ancla) if args.ancla else acciones.verificar()
            try:
                if args.clave or os.environ.get("EOLFI_ACCIONES_CLAVE"):
                    firmas = acciones.verificar_firmas(args.clave)
                    result = {**result, "firmas": {k: firmas.get(k) for k in (
                        "ok", "firmas", "firmas_de_otra_clave", "firmas_fallidas", "firmado_hasta",
                        "sin_firmar_al_final", "clave_id",
                        "firma_rota", "motivo", "aviso") if k in firmas}, "ok": result["ok"] and firmas["ok"]}
            except (OSError, ValueError) as exc:
                result = {**result, "ok": False, "firmas": {"ok": False, "error": str(exc)}}
            if args.rsi:
                rsi = acciones.verificar_rsi()
                result = {**result, "rsi": {k: v for k, v in rsi.items() if k not in ("archivo", "ultimo", "eventos")},
                          "ok": result["ok"] and rsi["ok"]}
            _print(result)
            return 0 if result["ok"] else 2
        if args.acciones_action in ("clave", "firmar"):
            try:
                _print(acciones.generar_clave(args.destino) if args.acciones_action == "clave"
                       else acciones.firmar(args.clave))
            except (OSError, ValueError) as exc:
                _print({"ok": False, "error": str(exc)})
                return 2
            return 0
        if args.acciones_action == "anclar":
            try:
                _print(acciones.anclar(args.destino))
            except (OSError, ValueError) as exc:
                _print({"ok": False, "error": str(exc)})
                return 2
            return 0
        _print(acciones.listar(args.n))
        return 0
    if args.cmd == "update":
        from eolfi.actualizacion import ActualizacionError, comprobar as comprobar_version

        try:
            result = comprobar_version(red=args.red, repo=args.repo)
        except ActualizacionError as exc:
            _print({"ok": False, "error": str(exc)})
            return 2
        _print(result)
        return {"al_dia": 0, "instalada_mas_reciente": 0, "sin_publicaciones": 0, "nueva_version": 1}.get(
            result["estado"], 2)
    if args.cmd == "navegador":
        from eolfi import navegador

        if args.accion == "instalar":
            try:
                _print(navegador.instalar())
            except navegador.NavegadorError as exc:
                _print({"ok": False, "error": str(exc)})
                return 1
            return 0
        info = navegador.estado(comprobar_hash=args.comprobar)
        _print(info)
        return 0 if info["instalado"] and info.get("sha256_coincide", True) else 1
    if args.cmd == "acceso-directo":
        from eolfi import instalador

        try:
            if args.quitar:
                result = instalador.quitar(args.donde, carpeta=args.carpeta)
            elif args.aplicar:
                result = instalador.crear(args.donde, port=args.port, carpeta=args.carpeta)
            else:
                result = {**instalador.plan(args.donde, port=args.port, carpeta=args.carpeta),
                          "vista_previa": True, "nota": "Nada creado; repite con --aplicar para crearlo."}
        except instalador.AccesoDirectoError as exc:
            _print({"ok": False, "error": str(exc)})
            return 1
        _print(result)
        return 0 if result.get("comprobado", True) else 1
    if args.cmd == "modelos":
        from eolfi.modelos import audit, check_trust

        try:
            if args.modelos_action == "actualizar":
                from eolfi.modelos_actualizar import comprobar

                result = comprobar(args.fuentes, nombre=args.nombre, red=args.red)
                _print(result)
                # 0 solo si todo está al día; una versión nueva o un dato no verificado piden revisión.
                return 0 if result["estado"] == "al_dia" else 2
            if args.modelos_action == "descargar":
                from eolfi.modelos_actualizar import descargar

                result = descargar(args.repo, args.archivo, args.revision, args.sha256, args.out, red=args.red,
                                   bytes_esperados=args.bytes)
                _print(result)
                # Descargado y auditado no significa adoptado: banco y G6 siguen pendientes.
                return 0 if result["estado"] == "descargado" else 2
            if args.modelos_action == "reconstruir":
                from eolfi.modelos_reconstruir import prepare, execute

                if args.ejecutar and not (args.sha256_entrada and args.sha256_paquete):
                    raise ValueError("--ejecutar requiere --sha256-entrada y --sha256-paquete de la receta revisada")
                result = prepare(args.archivo, args.out, args.cuantizador, args.tipo,
                                 source_sha=args.sha256_entrada, tool_sha=args.sha256_cuantizador,
                                 bundle_sha=args.sha256_paquete, threads=args.hilos, buffer_mib=args.memoria_mib,
                                 timeout=args.timeout)
                if args.ejecutar:
                    result = execute(result, timeout=args.timeout)
                _print(result)
                # El resultado aún necesita inferencia y banco: no anunciar un modelo listo.
                return 2 if args.ejecutar else 0
            if args.modelos_action == "probar":
                from eolfi.modelos_reconstruir import SMOKE_EXPECTED, SMOKE_PROMPT, execute_smoke, prepare_smoke

                if args.ejecutar and not args.sha256_paquete:
                    raise ValueError("--ejecutar requiere --sha256-paquete del ejecutor revisado")
                if (args.pregunta is None) != (args.esperado is None):
                    raise ValueError("--pregunta y --esperado se indican juntos")
                result = prepare_smoke(args.carpeta, args.ejecutor, bundle_sha=args.sha256_paquete,
                                       prompt=SMOKE_PROMPT if args.pregunta is None else args.pregunta,
                                       expected=SMOKE_EXPECTED if args.esperado is None else args.esperado,
                                       tokens=args.tokens, threads=args.hilos, timeout=args.timeout)
                if args.ejecutar:
                    result = execute_smoke(result)
                _print(result)
                # 0 significa solo «smoke superado»; el banco y la adopción siguen pendientes en `verificacion`.
                return 0 if result["estado"] in ("preparado", "smoke_superado") else 2
            if args.modelos_action == "auditar":
                result = audit(args.archivo)
                if args.pid is not None:
                    from eolfi.modelos_red import snapshot

                    result["conexiones_motor"] = snapshot(args.pid)
                    if result["conexiones_motor"]["estado"] == "NO VERIFICADO":
                        result["incognitas"].append("Conexiones del PID no verificadas completamente")
                        if result["estado"] != "fallido":
                            result["estado"] = "NO VERIFICADO"
                _print(result)
                return 0 if result["estado"] == "estructura_verificada" else 2
            if args.modelos_action == "conexiones":
                from eolfi.modelos_red import snapshot

                result = snapshot(args.pid)
                _print(result)
                return 0 if result["estado"] == "observado" else 2
            _print(check_trust(args.archivo, args.manifiesto))
            return 0
        except (OSError, ValueError, KeyError, TypeError) as exc:
            _print({"estado": "fallido", "error": str(exc)})
            return 2
    if args.cmd == "eolas-v2":
        from pathlib import Path as _P
        from eolfi import eolas_v2

        try:
            if args.eolas_action == "status":
                _print(eolas_v2.status())
            elif args.eolas_action == "perfiles":
                _print({"perfiles": eolas_v2.catalogo()})
            elif args.eolas_action == "alta":
                _print(eolas_v2.register_profile(args.profile, args.gguf, etiqueta=args.etiqueta, alias=args.alias,
                                                 ctx=args.ctx, gpu_layers=args.gpu_layers, batch=args.batch,
                                                 ubatch=args.ubatch, reasoning_format=args.razonamiento,
                                                 plantilla=args.plantilla, sha256=args.sha256))
            elif args.eolas_action == "activo":
                _print(eolas_v2.set_active_profile(args.profile))
            elif args.eolas_action == "rol":
                _print(eolas_v2.set_role(args.rol, args.profile))
            elif args.eolas_action == "examen":
                report = eolas_v2.run_round(profiles=[args.profile], progress=_progress)
                _print({"resumen": report.get("summary"), "admision": eolas_v2.admitido(args.profile)})
            elif args.eolas_action == "plan":
                from eolfi.modelos_reconstruir import plan_profile

                _print(plan_profile(args.carpeta, args.profile, alias=args.alias, ctx=args.ctx,
                                    gpu_layers=args.gpu_layers, batch=args.batch, ubatch=args.ubatch))
            elif args.eolas_action == "adoptar":
                from eolfi.modelos_reconstruir import adopt_profile

                _print(adopt_profile(args.plan, args.sha256_modelo, apply=args.aplicar))
            elif args.eolas_action == "quitar-perfil":
                _print(eolas_v2.remove_custom_profile(args.profile, args.sha256_modelo))
            elif args.eolas_action == "recomendar-perfil":
                _print(eolas_v2.apply_recommended_profile(args.bateria, max_age_days=args.antiguedad_dias,
                                                           apply=args.aplicar))
            elif args.eolas_action == "start":
                _print(eolas_v2.start(args.profile, release_eolas=args.liberar_eolas))
            elif args.eolas_action == "switch":
                _print(eolas_v2.switch(args.profile))
            elif args.eolas_action == "stop":
                _print(eolas_v2.stop())
            elif args.eolas_action == "revisar":
                from eolfi import rea_client, rea_compuestas
                target = (eolas_v2.profile_config(args.objetivo)["model"] if args.objetivo in eolas_v2.load_config()["profiles"]
                          else args.objetivo)
                client = rea_client.ReaClient()
                try:
                    _print(rea_compuestas.revisar_modelo(client, target))
                finally:
                    client.close()
            elif args.eolas_action == "retire":
                _print({"retirados": eolas_v2.retire_profile(args.profile)})
            elif args.eolas_action == "uninstall":
                _print(eolas_v2.uninstall_profile(args.profile))
            elif args.eolas_action == "restore":
                _print({"retirados": eolas_v2.restore_profile(args.profile)})
            elif args.eolas_action == "feedback-consent":
                _print(eolas_v2.set_feedback_consent(args.state == "on"))
            elif args.eolas_action == "feedback-add":
                if bool(args.prompt) == bool(args.prompt_file) or bool(args.response) == bool(args.response_file):
                    raise ValueError("indica exactamente uno de --prompt/--prompt-file y --response/--response-file")
                prompt = _P(args.prompt_file).read_text(encoding="utf-8") if args.prompt_file else args.prompt
                response = _P(args.response_file).read_text(encoding="utf-8") if args.response_file else args.response
                _print(eolas_v2.record_feedback(profile=args.profile, task=args.task, prompt=prompt,
                                                response=response, rating=args.rating, consent=args.consent))
            elif args.eolas_action == "feedback-delete":
                _print({"deleted": eolas_v2.delete_feedback(args.record_id)})
            elif args.eolas_action == "feedback-export":
                _print(eolas_v2.export_feedback(_P(args.out)))
            elif args.eolas_action == "feedback-import":
                _print(eolas_v2.import_feedback(_P(args.source)))
            elif args.eolas_action == "dataset":
                _print(eolas_v2.build_dataset(kind=args.kind, out=_P(args.out), min_examples=args.min_examples))
            elif args.eolas_action == "calibrate":
                _print(eolas_v2.recommend_profile(args.task))
            elif args.eolas_action == "training-check":
                _print(eolas_v2.training_readiness(_P(args.checkpoint), _P(args.dataset)))
            elif args.eolas_action == "train-sft":
                _print(eolas_v2.train_sft(_P(args.checkpoint), _P(args.dataset), _P(args.out), consent=args.consent,
                                          epochs=args.epochs, max_seq_length=args.max_seq_length))
            return 0
        except (FileNotFoundError, FileExistsError, ValueError, PermissionError, OSError, RuntimeError, TimeoutError) as exc:
            if os.environ.get("EOLFI_DEBUG"):
                raise
            print(f"eolfi eolas-v2: error: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
    if args.cmd == "create" and args.verify:
        print("Eolfi: --verify está obsoleta y no hace nada (la verificación siempre es obligatoria); se retirará "
              "en una versión posterior.", file=sys.stderr)
    if args.cmd != "llama":
        from eolfi.core.dbpath import resolve_db

        args.db = resolve_db(args.db)
    if args.cmd == "llama":
        from eolfi import llamacpp

        if args.accion == "start":
            print("eolfi llama: «start» está retirado: dejaba un segundo modelo en la GPU (puerto 8090) junto al de "
                  "Eolas. Usa Eolas (proveedor eolas) o «eolfi eolas-v2 start». «eolfi llama stop» sigue disponible "
                  "para parar uno antiguo.", file=sys.stderr)
            return 2
        elif args.accion == "stop":
            _print({"stopped": llamacpp.stop()})
        elif args.accion == "config":
            llamacpp.load_config()
            _emit(str(llamacpp.config_file()))
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
    if args.cmd == "dataset":
        from eolfi.dataset_llm import build

        _print(build(args.library, dry_run=args.dry_run))
        return 0
    if args.cmd == "rsi":
        from eolfi import rsi

        a = args.rsi_action
        try:
            if a == "estado":
                _print(rsi.estado())
            elif a == "verificar":
                res = rsi.verificar_registro()
                _print(res)
                return 0 if res["ok"] else 1
            elif a == "proponer":
                _print(rsi.proponer())
            elif a == "aa" and args.simulada is not None:
                _print(rsi.calibrar_aa(desviacion=args.simulada, muestras=args.muestras))
            elif a in ("evaluar", "aa"):
                from eolfi import rsi_banco

                banco = rsi_banco.banco(args.banco, proveedor=args.proveedor, modelo=args.modelo,
                                               registro=lambda d: _progress(f"RSI muestra: {d}"))
                if a == "aa":
                    _print(rsi.prueba_aa(banco, muestras=args.muestras))
                else:
                    _print(rsi.evaluar(args.id, banco, muestras=args.muestras, margen=args.margen, alfa=args.alfa))
            elif a == "revertir":
                _print(rsi.revertir(args.id, por=args.por))
            else:
                _print(rsi.decidir(args.id, a, por=args.por))
        except rsi.RSIError as exc:
            print(f"RSI: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.cmd == "rea":
        from eolfi import rea_client, rea_compuestas as rc, rea_paquete

        if args.rea_action == "comprobar-paquete":
            try:
                comprobado = rea_paquete.comprobar(args.carpeta)
            except (OSError, ValueError) as exc:
                print(f"eolfi rea comprobar-paquete: {exc}", file=sys.stderr)
                return 2
            _print(comprobado)
            return 0 if comprobado["ok"] else 1
        if args.caso:
            # 14/11/2026: el caso se comprobaba DESPUÉS del análisis, y un identificador mal escrito tiraba minutos de
            # Ghidra sin mostrar nada. Ahora se comprueba antes de empezar.
            from eolfi.core.cases import CaseStore
            from eolfi.core.evidence import EvidenceStore as _EvidenceStore

            check = _EvidenceStore(args.db)
            try:
                CaseStore(check).get(args.caso)
            except ValueError:
                print(f"caso no encontrado: {args.caso}. Usa el identificador de «eolfi case list» o crea uno con "
                      "«eolfi case create <nombre>».", file=sys.stderr)
                return 2
            finally:
                check.close()
        motor = getattr(args, "motor", "ghidra")
        carpeta_paquete = None
        if args.paquete:   # E3: se comprueba antes del análisis para no perderlo por una carpeta ocupada
            try:
                carpeta_paquete = rea_paquete.preparar(args.paquete)
            except (OSError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 2
        wsl = args.rea_action in ("recuperar-js", "firmware", "dotnet") or motor == "kuna"
        cmd = rea_client.wsl_rea_command() if wsl else None
        if wsl and not cmd:
            print("REA de WSL2 no instalado: ejecuta tools/instalar-rea-wsl.sh dentro de Ubuntu", file=sys.stderr)
            return 2
        if args.rea_action in ("senal", "decodificadores"):
            cmd = rea_client.wsl_rea_sigrok_command()
            if not cmd:
                print("sigrok en el REA de WSL no disponible: hace falta el REA de WSL (tools/instalar-rea-wsl.sh) y "
                      "sigrok-cli 0.7.2 (tools/instalar-sigrok-wsl.sh)", file=sys.stderr)
                return 2
        if motor == "kuna" and not rea_client.wsl_has_kuna(cmd):
            print("Kuna no instalado en WSL2: vuelve a ejecutar tools/instalar-rea-wsl.sh dentro de Ubuntu "
                  "(REA solo admite Kuna en Linux y macOS)", file=sys.stderr)
            return 2
        if args.rea_action == "firmware" and args.extraer and not any(c.startswith("REA_UNBLOB_COMMAND=") for c in cmd):
            print("Unblob 26.6.4 no instalado en WSL2: ejecuta tools/instalar-unblob-wsl.sh dentro de Ubuntu", file=sys.stderr)
            return 2
        if args.rea_action == "firmware" and not args.extraer and not any(c.startswith("REA_BINWALK_COMMAND=") for c in cmd):
            print("Binwalk 3.1.0 no instalado en WSL2: ejecuta tools/instalar-binwalk-wsl.sh dentro de Ubuntu", file=sys.stderr)
            return 2
        if args.rea_action == "swift":
            cmd = rea_client.wsl_rea_ghidra_command()
            if not cmd:
                print("Ghidra en el REA de WSL no disponible: hace falta el REA de WSL (tools/instalar-rea-wsl.sh), "
                      "Java 21 (tools/instalar-java-wsl.sh) y GHIDRA_INSTALL_DIR con Ghidra 12.1", file=sys.stderr)
                return 2
        from eolfi import rsi

        # Plazo del cliente: el de Ghidra en WSL para Swift; si no, el ajuste del RSI (900 s salvo propuesta aprobada).
        plazo = rea_client.GHIDRA_CLIENT_TIMEOUT if args.rea_action == "swift" else rsi.ajuste("rea.timeout")
        client = rea_client.ReaClient(cmd, timeout=plazo)
        if motor == "kuna":   # el REA de WSL ve las rutas de Windows como /mnt/<unidad>/…
            from eolfi.server import _WslPaths

            raw, client = client, _WslPaths(client)
            client.close = raw.close
        op = args.rea_action
        try:
            if args.rea_action == "recuperar-js":
                op, params = "recuperar_fuentes_js", {"ruta": args.ruta, "destino": args.destino}
                result = rc.recuperar_fuentes_js(client, args.ruta, args.destino)
            elif args.rea_action == "api":
                from eolfi.server import EolfiApp

                op, params = "api_desde_captura", {"ruta": args.ruta}
                result = EolfiApp(args.db)._api_from_capture(client, args.ruta)
                if args.cliente:   # plan REA, punto 7: cliente de lo observado
                    from eolfi import cliente_api

                    params["cliente"] = args.cliente
                    try:
                        result["cliente"] = cliente_api.escribir_cliente(result, args.cliente)
                    except (ValueError, OSError) as exc:   # BorradorIncompleto es ValueError
                        result["cliente_error"] = str(exc)
            elif args.rea_action == "firmware" and args.extraer:
                op = "extraer_firmware"
                params = {"ruta": args.ruta, "destino": args.extraer, "profundidad": args.profundidad}
                result = rc.extraer_firmware(client, args.ruta, args.extraer, profundidad=args.profundidad)
            elif args.rea_action == "firmware":
                op, params, result = "firmware_regiones", {"ruta": args.ruta}, rc.firmware_regiones(client, args.ruta)
            elif args.rea_action == "entorno":
                op = "entorno_agente"
                params = {"ruta": args.ruta, "destino": args.destino, "nombre": args.nombre, "escribir": args.escribir}
                result = rc.entorno_agente(client, args.ruta, args.destino, args.nombre, escribir=args.escribir)
            elif args.rea_action == "mapa-app":
                op, params = "mapa_app_android", {"ruta": args.ruta, "limite": args.limite}
                result = rc.mapa_app_android(client, args.ruta, args.limite)
            elif args.rea_action == "llamadas":
                hacia = "atras" if args.atras else "adelante"
                op = "grafo_llamadas"
                params = {"ruta": args.ruta, "funcion": args.funcion, "hacia": hacia, "profundidad": args.profundidad}
                result = rc.grafo_llamadas(client, args.ruta, args.funcion, hacia=hacia, profundidad=args.profundidad,
                                           max_nodos=args.max_nodos)
            elif args.rea_action == "dotnet":
                op, params = "ensamblado_dotnet", {"ruta": args.ruta, "limite": args.limite, "salida": args.salida}
                result = rc.ensamblado_dotnet(client, args.ruta, args.limite, args.salida)
            elif args.rea_action == "clase":
                op = "clase_android"
                params = {"ruta": args.ruta, "consulta": args.consulta, "metodo": args.metodo,
                          "sobrecarga": args.sobrecarga}
                result = rc.clase_android(client, args.ruta, args.consulta, metodo=args.metodo,
                                          sobrecarga=args.sobrecarga, limite=args.limite)
            elif args.rea_action == "flutter":
                op, params = "app_flutter", {"ruta": args.ruta, "abi": args.abi}
                result = rc.app_flutter(client, args.ruta, args.abi, args.limite)
            elif args.rea_action == "apple":
                op, params = "mapa_app_apple", {"ruta": args.ruta}
                result = rc.mapa_app_apple(client, args.ruta, args.limite)
            elif args.rea_action == "devicetree":
                op, params = "devicetree_hw", {"ruta": args.ruta, "filtro": args.filtro}
                result = rc.devicetree_hw(client, args.ruta, args.limite, args.filtro)
            elif args.rea_action == "swift":
                op, params = "tipos_swift_apple", {"ruta": args.ruta, "arquitectura": args.arquitectura}
                result = rc.tipos_swift_apple(client, args.ruta, arquitectura=args.arquitectura, limite=args.limite,
                                              ruta_rea=rea_client.wsl_path, demangle=rea_client.wsl_swift_demangle)
            elif args.rea_action == "go":
                op, params, result = "binario_go", {"ruta": args.ruta}, rc.binario_go(client, args.ruta, args.limite)
            elif args.rea_action == "rust":
                op, params = "binario_rust", {"ruta": args.ruta}
                result = rc.binario_rust(client, args.ruta, args.limite)
            elif args.rea_action == "senal":
                op, params = "decodificar_senal", {"ruta": args.ruta, "decodificadores": args.decodificadores}
                result = rc.decodificar_senal(client, args.ruta, args.decodificadores, anotaciones=args.anotaciones,
                                              formato=args.formato, limite=args.limite, ruta_rea=rea_client.wsl_path)
            elif args.rea_action == "unity":
                op, params = "unity_il2cpp", {"ruta": args.ruta, "binario": args.binario, "tipo": args.tipo}
                result = rc.unity_il2cpp(client, args.ruta, binario=args.binario, tipo=args.tipo, limite=args.limite)
            elif args.rea_action == "decodificadores":
                op, params = "decodificadores_senal", {"consulta": args.consulta, "decodificador": args.ayuda}
                result = rc.decodificadores_senal(client, args.consulta, decodificador=args.ayuda)
            elif args.rea_action == "revisar-modelo":
                op, params, result = "revisar_modelo", {"ruta": args.ruta}, rc.revisar_modelo(client, args.ruta)
            elif args.rea_action == "explicar":
                extra = {"motor": motor} if motor != "ghidra" else {}
                op, params = "explicar_binario", {"ruta": args.ruta, "funciones": args.funciones, **extra}
                result = rc.explicar_binario(client, args.ruta, args.funciones, motor=motor)
            elif args.rea_action == "inventario":
                op, params, result = "inventario_dependencias", {"ruta": args.ruta}, rc.inventario_dependencias(client, args.ruta)
            elif args.rea_action == "wasm":
                op, params = "modulo_wasm", {"ruta": args.ruta, "frente": args.frente, "js": args.js}
                result = rc.modulo_wasm(client, args.ruta, args.frente, args.limite, args.js)
            elif args.rea_action == "app-js":
                op, params, result = "analizar_app_js", {"ruta": args.ruta}, rc.analizar_app_js(client, args.ruta)
            elif args.rea_action == "reimplementar":
                extra = {"motor": motor} if motor != "ghidra" else {}
                op, params = "reimplementar_funcion", {"ruta": args.ruta, "funcion": args.funcion, **extra}
                result = rc.reimplementar_funcion(client, args.ruta, args.funcion, motor=motor)
            else:
                op, params = "comparar_versiones", {"original": args.original, "nueva": args.nueva}
                result = rc.comparar_versiones(client, args.original, args.nueva)
            respuesta_rea = None
            if carpeta_paquete is not None:   # con la sesión de REA aún abierta: su paquete cubre este análisis
                try:
                    en_wsl = (wsl and motor != "kuna") or args.rea_action in ("senal", "decodificadores", "swift")
                    respuesta_rea = rea_paquete.exportar_rea(client, carpeta_paquete, wsl=en_wsl)
                except (ValueError, RuntimeError, OSError) as exc:
                    respuesta_rea = {"error": f"no se pudo exportar el paquete de REA: {str(exc)[:300]}"}
        except (ValueError, RuntimeError) as exc:
            # Error de REA o ruta no válida: el mensaje, sin traza (EOLFI_DEBUG la muestra). El RSI lo anota igual
            # (un plazo agotado es el síntoma que propone ampliar rea.timeout).
            _rsi_observar("rea", op, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            if os.environ.get("EOLFI_DEBUG"):
                raise
            hint = (" Kuna solo admite ELF y Mach-O de una arquitectura; para PE usa --motor ghidra."
                    if motor == "kuna" and "unsupported_provider" in str(exc) else "")
            print(f"eolfi rea {args.rea_action}: {exc}{hint}", file=sys.stderr)
            if carpeta_paquete is not None and not any(carpeta_paquete.iterdir()):
                carpeta_paquete.rmdir()   # sin análisis no hay paquete: no se deja una carpeta vacía
            return 1
        except Exception as exc:
            _rsi_observar("rea", op, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            raise
        finally:
            client.close()
        _rsi_observar("rea", op, {"ok": not result.get("error"), "error": str(result.get("error") or "")}
                      if isinstance(result, dict) else result)
        paquete_caso = None
        if args.caso:   # plan REA, punto 6: lo analizado queda en el caso
            # Alias: un «import EvidenceStore» aquí lo haría local a TODA la función y rompería las demás órdenes.
            from eolfi import rea_caso
            from eolfi.core.evidence import EvidenceStore as _EvidenceStore

            store = _EvidenceStore(args.db)
            try:
                result["caso"] = rea_caso.registrar(store, args.caso, op, params, result)
                if carpeta_paquete is not None:
                    from eolfi.core.cases import CaseStore

                    paquete_caso = CaseStore(store).package(args.caso)
            except (ValueError, OSError) as exc:
                # El análisis ya está hecho: se muestra igual, con el error del registro, en vez de perderlo.
                result["caso_error"] = str(exc)
            finally:
                store.close()
        if carpeta_paquete is not None:
            from eolfi.rea_caso import rea_version

            try:
                result["paquete"] = rea_paquete.cerrar(
                    carpeta_paquete, operacion=op, params=params, resultado=result, rea_version=rea_version(),
                    respuesta_rea=respuesta_rea, paquete_caso=paquete_caso, caso=args.caso)
            except (ValueError, OSError) as exc:
                result["paquete_error"] = str(exc)
        _print(result)
        return 0
    if args.cmd == "telemetria":
        from eolfi import telemetria

        _print({"carpeta": str(telemetria.carpeta()), "activa": telemetria.activa()}
               if args.telemetria_action == "ruta" else telemetria.resumen())
        return 0
    if args.cmd == "voz":
        from pathlib import Path

        from eolfi import voz

        try:
            if args.voz_action == "estado":
                _print(voz.estado())
            elif args.voz_action == "microfonos":
                _print(voz.microfonos())
            elif args.voz_action == "transcribir":
                _print(voz.transcribir(Path(args.archivo).read_bytes(), idioma=args.idioma))
            elif args.voz_action == "dictar":
                _print(voz.dictar(args.segundos, idioma=args.idioma))
            elif args.voz_action == "decir":
                data = voz.hablar(args.texto, idioma=args.idioma, voz=args.voz)
                Path(args.out).write_bytes(data)
                _print({"archivo": args.out, "bytes": len(data)})
            else:
                _print(voz.guardar({k: v for k, v in (("motor", args.motor), ("idioma", args.idioma),
                                                      ("voz", args.voz)) if v is not None}))
        except (voz.VozError, OSError) as exc:
            print(f"voz: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.cmd == "mcp":
        from eolfi import mcp_server

        return mcp_server.main(args.db, args.root, args.library)
    if args.cmd == "motor-local":
        from eolfi import local_gpu

        if args.motor:
            try:
                local_gpu.set_local_engine(args.motor)
            except ValueError as exc:
                print(f"eolfi motor-local: error: {exc}", file=sys.stderr)
                return 2
        motor = local_gpu.local_engine()
        forced = " (fijado por EOLFI_LOCAL_ENGINE)" if os.environ.get("EOLFI_LOCAL_ENGINE") else ""
        print(f"Motor local: {motor}{forced} — proveedor «{local_gpu.ENGINE_PROVIDER[motor]}» — {local_gpu.engine_file()}")
        return 0
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
        if args.key and not args.cert:
            print("eolfi: --key necesita --cert", file=sys.stderr)
            return 2
        return server.serve(args.db, args.host, args.port, args.allow_remote, args.samples, args.cert, args.key)
    from eolfi.sites.fetch import FetchError

    store = EvidenceStore(args.db)
    try:
        return _dispatch(args, store)
    except (FileNotFoundError, FileExistsError, ValueError, PermissionError, IsADirectoryError, FetchError) as exc:
        if os.environ.get("EOLFI_DEBUG"):
            raise
        print(f"eolfi: error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
