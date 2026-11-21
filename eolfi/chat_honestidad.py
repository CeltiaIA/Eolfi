"""Honestidad del chat (17/11/2026): que Eolas no invente capacidades, acciones ni licencias.

Origen: una conversación real del panel con gemma-4-12b (Eolas V2) en la que el chat
- anunciaba «Acciones en curso» y «en mi próxima respuesta te entregaré…» sin haber llamado a ninguna herramienta
  (nada sigue ejecutándose cuando termina una respuesta);
- inventaba capacidades: «RSI (Recursive State Inference)», fusionar pesos de Gemma, Mistral y Qwen en un
  «Eolas.gguf» con MoE;
- prometía que «todo el código y los pesos» serían propiedad de Eolas, cuando los pesos derivados siguen la licencia
  de su origen (Gemma Terms of Use, Apache-2.0…);
- decía que no podía conectarse a VS Code y pedía al titular que creara los archivos a mano.

Tres piezas:
1. `contexto(estado)`: el ESTADO REAL que recibe el modelo en el mensaje de sistema (puente de VS Code, límites).
2. `revisar(texto, llamadas, ofrecidas, estado)`: detector determinista de esos defectos; cada hallazgo tiene un
   código estable para poder medir cuánto varía el modelo entre ejecuciones (tools/medir_deriva_chat.py).
3. `aviso(hallazgos)`: el texto que se antepone a la respuesta si, tras una ronda de corrección, sigue fallando.
Es un filtro de patrones: reduce y mide estos defectos concretos, no garantiza que el modelo no invente otros.
"""
from __future__ import annotations

import re
import time
import unicodedata
from typing import Any

LIMITES = (
    "Límites reales de Eolfi (no los contradigas ni los adornes):\n"
    "- Cada respuesta termina cuando la envías: nada sigue «en curso» ni «en marcha» después. Solo ha ocurrido lo que "
    "hiciste con una herramienta en ESTE turno y figura en su resultado. No anuncies acciones en curso ni prometas "
    "entregar algo «en la próxima respuesta»: hazlo ahora con una herramienta o propónlo como pregunta.\n"
    "- Eolfi NO entrena, fusiona, destila ni «entrelaza» pesos de modelos, no crea modelos nuevos funcionales a partir "
    "de estadísticas de otros y no descarga modelos de Internet. Puede leer la cabecera de un GGUF sin cargarlo "
    "(eolfi_modelos_auditar, eolfi_revisar_modelo) y escribir código de prueba con ejecutar_python.\n"
    "- «RSI» significa Recursive Self-Improvement (automejora recursiva). En Eolfi es la automejora SUPERVISADA de la "
    "propia Eolfi (eolfi_automejora): observa sus fallos, propone cambios, los evalúa y el TITULAR decide si se "
    "aplican o se revierten. No es una arquitectura de modelo, ni una capa de pesos, ni «Recursive State Inference» "
    "ni «Recursive System Intelligent»: si el usuario lo llama así, acláraselo. No existen «sistemas propios de "
    "inteligencia», MoE propio ni protocolos internos fuera de las herramientas que ves.\n"
    "- Licencias: los pesos derivados de Gemma, Mistral, Qwen u otros siguen la licencia de su origen (Gemma Terms of "
    "Use, Apache-2.0, etc.). Ni Eolfi ni el usuario pueden ponerles una licencia propia exclusiva; dilo así.\n"
    "- Para generar una aplicación (carpetas, archivos, pruebas) usa eolfi_vscode_encargo si el puente de VS Code está "
    "activo (la crea en la carpeta abierta en VS Code) o eolfi_proponer_proyecto si no: ambas proponen el plan "
    "verificado y el titular lo aprueba (panel o VS Code); el proyecto sale verificado (compilación, pruebas, juez). "
    "Un encargo recién hecho está PENDIENTE: no digas que la aplicación ya está creada; su estado real lo da "
    "eolfi_vscode_encargo_estado. No pidas al usuario que cree a mano archivos que Eolfi puede generar.\n"
    "- Si algo no se puede hacer, dilo claramente y propone lo que sí se puede."
)


def contexto(estado: dict[str, Any] | None) -> str:
    """Bloque para el mensaje de sistema con el estado comprobado al empezar el turno."""
    vs = (estado or {}).get("vscode")
    if vs is None:
        linea = "- VS Code: no comprobado en este turno; no afirmes ni niegues que esté conectado."
    elif vs.get("activo"):
        carpetas = ", ".join(str(c) for c in (vs.get("carpetas") or [])[:5]) or "sin carpeta abierta"
        linea = (f"- VS Code: el puente de la extensión @eolfi está ACTIVO (carpetas: {carpetas}). Eolfi SÍ se comunica "
                 "con VS Code; no digas que no puedes conectarte. Para crear allí una aplicación, eolfi_vscode_encargo.")
    else:
        linea = ("- VS Code: el puente de la extensión @eolfi NO responde ahora. Dilo así y explica que se activa "
                 "abriendo VS Code con la extensión de Eolfi; no inventes otra vía.")
    return "Estado real comprobado por Eolfi al empezar este turno:\n" + linea + "\n" + memoria(estado) + LIMITES


def _fecha(ts: Any) -> str:
    try:
        return time.strftime("%d/%m/%Y %H:%M", time.localtime(float(ts)))
    except (TypeError, ValueError, OverflowError, OSError):
        return "fecha desconocida"


ESTADOS_ENCARGO = {"hecho": "terminado", "en_curso": "en curso", "fallido": "fallido o sin verificar",
                   "pendiente": "pendiente de aprobación", "rechazado": "rechazado", "aprobado": "aprobado"}


def parecidos(texto: str, estado: dict[str, Any] | None) -> list[tuple[str, str, str]]:
    """Palabras del mensaje que se parecen al nombre de un proyecto o caso conocido: (palabra, nombre, tipo).

    21/11/2026, Redmi: el dictado escribió «Hilfee» por el caso «ilfy» y el chat preguntó qué era o se inventó su
    estado. No se reescribe lo dictado (podría ser otra cosa); se le dice al modelo qué nombre real se parece."""
    import difflib

    mem = (estado or {}).get("memoria") or {}
    nombres = [(str(p.get("nombre") or ""), "proyecto") for p in mem.get("proyectos") or []]
    nombres += [(str(c.get("nombre") or ""), "caso") for c in mem.get("casos") or []]
    palabras = re.findall(r"[^\W\d_]{3,}", texto)
    out: list[tuple[str, str, str]] = []
    for nombre, tipo in nombres:
        clave = _plano(nombre).strip()
        if not clave or any(n == nombre for _p, n, _t in out):
            continue
        n = len(clave.split())
        for i in range(len(palabras)):
            trozo = " ".join(palabras[i:i + n])
            plano = _plano(trozo)
            if plano == clave:
                break   # ya lo nombra tal cual: no hace falta nota
            # Sin la «h» muda inicial del dictado («Hilfee» → «ilfee»).
            ratio = max(difflib.SequenceMatcher(None, plano, clave).ratio(),
                        difflib.SequenceMatcher(None, plano.removeprefix("h"), clave).ratio())
            if ratio >= 0.6 and len(clave) >= 3:
                out.append((trozo, nombre, tipo))
                break
    return out[:3]


def nota_parecidos(texto: str, estado: dict[str, Any] | None) -> str:
    pares = parecidos(texto, estado)
    if not pares:
        return ""
    return "\n\n[Nota de Eolfi: el mensaje puede venir de un dictado. " + "; ".join(
        f"«{p}» se parece al {t} «{n}»" for p, n, t in pares) + ". Si encaja con la pregunta, es ese.]"


def memoria(estado: dict[str, Any] | None) -> str:
    """21/11/2026 (titular: «tiene que poder recordar si hizo un proyecto con nombre incluido»): lo que Eolfi YA ha
    hecho, con nombre, para que «¿cómo va el último proyecto?» se conteste con datos y no con una pregunta o un
    estado inventado. Viene de `_chat_memoria` del servidor (encargos y casos reales)."""
    mem = (estado or {}).get("memoria")
    if mem is None:
        return ""
    lineas = ["- Proyectos y aplicaciones que Eolfi ha creado o tiene encargados (del más reciente al más antiguo):"]
    for p in (mem.get("proyectos") or [])[:8]:
        est = ESTADOS_ENCARGO.get(str(p.get("estado")), str(p.get("estado") or "desconocido"))
        ver = {True: ", verificado", False: ", NO verificado"}.get(p.get("verificado"), "")
        lineas.append(f"  · «{p.get('nombre')}» — {est}{ver}; carpeta {p.get('carpeta')}; {_fecha(p.get('fecha'))}"
                      f" (encargo {p.get('encargo_id')})")
    if len(lineas) == 1:
        lineas.append("  · ninguno todavía")
    lineas.append("- Casos de trabajo recientes (análisis y proyectos):")
    for c in (mem.get("casos") or [])[:8]:
        desc = f": {c.get('descripcion')}" if c.get("descripcion") else ""
        carpeta = f"; proyecto generado en {c.get('carpeta')}" if c.get("carpeta") else ""
        lineas.append(f"  · «{c.get('nombre')}»{desc} ({_fecha(c.get('fecha'))}{carpeta})")
    if not mem.get("casos"):
        lineas.append("  · ninguno todavía")
    lineas.append("  Si el usuario pregunta por «el último proyecto» o por uno con nombre, contesta con ESTOS datos "
                  "(nombre, estado, carpeta y fecha) y, para el detalle, llama a eolfi_vscode_encargo_estado con su "
                  "encargo. Si el nombre que dice no aparece, dilo y enséñale los que sí hay; nunca inventes el estado "
                  "de un proyecto.")
    return "\n".join(lineas) + "\n"


def _plano(texto: str) -> str:
    sin = unicodedata.normalize("NFKD", texto)
    return "".join(ch for ch in sin if not unicodedata.combining(ch)).casefold()


EN_CURSO = re.compile(
    r"acciones en curso|\b(?:esta|estan|queda|sigue|sigo|ya esta)\s+en\s+(?:marcha|curso)\b"
    r"|\b(?:estoy|seguimos|sigo|estamos)\s+(?:procesando|analizando|extrayendo|descargando|generando|creando"
    r"|construyendo|estructurando|preparando|configurando|escribiendo|desarrollando|elaborando|trabajando"
    r"|terminando|finalizando|ultimando|implementando|ajustando|iniciando|comenzando)\b"
    r"|\b(?:iniciando|comenzando)\s+(?:la\s+|el\s+)?(?:auditoria|analisis|creacion|generacion|descarga)\b"
    r"|\bmientras\s+(?:el|la|los|las)\s+[\w ]{0,40}?\b(?:corre|se ejecuta|avanza|termina)\b"
    r"|\ben\s+(?:mi|la)\s+proxima\s+respuesta\s+te\s+(?:entregare|dare|enviare|mostrare|traere)"
    r"|\bentrando en fase de\b|\bcomenzare a procesar\b")
# 20/11/2026 (tableta, gemma4 Q4 reconstruido): «Procederé a crear el archivo…», «Estoy trabajando en la creación…»,
# «En cuanto termine… te informaré», «Podrás seguir el progreso en Seguimiento», sin ninguna herramienta. Tras la
# respuesta no se ejecuta nada: son promesas falsas. Se revisan por frase y no cuentan las ofertas («si quieres,
# procederé a…») ni las preguntas.
PROMESA = re.compile(
    r"\bestoy\s+trabajando\s+en\b|\bprocedere\s+a\s+\w+|\bempezare\s+(?:con|por)\b"
    r"|\ben\s+cuanto\s+(?:termine|lo\s+tenga|este\s+list[oa]s?)\b|\bte\s+(?:informare|avisare|notificare)\b"
    r"|\bpodras\s+(?:seguir|ver)\s+(?:el\s+)?(?:progreso|avance)\b")
OFERTA = re.compile(r"\bsi\s+(?:quieres|lo\s+deseas|te\s+parece|me\s+(?:confirmas|lo\s+pides|das|dices))\b|\?\s*$")
HECHO = re.compile(r"\b(?:he|hemos)\s+(?:creado|descargado|generado|escrito|guardado|instalado|entrenado|fusionado|"
                   r"ejecutado|compilado)\b")
INVENTADO = re.compile(
    r"recursive\s+state\s+inference|recurrent\s+state\s+inference|inferencia\s+de\s+estado\s+recursiv"
    r"|recursive\s+sys?tem\s+intelligen\w*"
    r"|\bfusion\w*\s+(?:de\s+|los\s+|sus\s+|las\s+)*pesos\b|\bentrelaz\w*\b[^.\n]{0,40}\b(?:modelos|pesos)\b"
    r"|mis\s+(?:propios\s+protocolos|sistemas\s+propios)|inyectar\s+la\s+inteligencia")
NIEGA = re.compile(r"\bno\b|\bni\b|\bnunca\b|\bimposible\b")
LICENCIA = re.compile(r"licencia|propiedad\s+intelectual|property\s+of|exclusive\s+property|propiedad\s+exclusiva")
PROPIA = re.compile(r"\beolas\b|propia|exclusiv")
ORIGEN = re.compile(r"gemma|mistral|qwen|llama|pesos|weights|modelo")
NEGACION = re.compile(r"\bno\b|\bsiguen?\b|conserv|mantien|hereda|terms of use|apache|\bmit\b|\bsalvo\b|\bsin\b")
VSCODE_NO = re.compile(r"\bno\s+(?:puedo|tengo\s+(?:la\s+)?capacidad\s+de|me\s+es\s+posible)\s+(?:\w+\s+){0,4}?"
                       r"(?:\"?conectar\w*\"?|acceder|abrir|usar|controlar)[^.\n]{0,80}\bvs\s?code\b")
A_MANO = re.compile(r"\bcrea\s+(?:una\s+carpeta|el\s+archivo|los\s+archivos|estos\s+(?:\w+\s+)?archivos)[^.\n]{0,80}"
                    r"\ben\s+tu\s+(?:pc|vs\s?code|equipo|ordenador|maquina)\b|\btu\s+(?:creas|pegas)\s+los\s+archivos\b")
NOMBRE_HERRAMIENTA = re.compile(r"\b(?:eolfi|rea)_[a-z0-9_]+\b")

DESCRIPCION = {
    "accion_en_curso": "anuncia acciones «en curso» o para la próxima respuesta; nada se ejecuta tras responder",
    "hecho_sin_herramienta": "dice haber creado, descargado o ejecutado algo sin ninguna herramienta correcta en este turno",
    "capacidad_inventada": "atribuye a Eolfi capacidades que no tiene (RSI, que es Recursive Self-Improvement, "
                           "como arquitectura de modelo; fusión de pesos; sistemas propios)",
    "licencia_propia": "promete una licencia o propiedad propia sobre pesos o modelos derivados",
    "vscode_negado": "niega poder comunicarse con VS Code con el puente de @eolfi activo",
    "trabajo_a_mano": "pide al usuario crear a mano carpetas o archivos que Eolfi puede generar",
    "herramienta_inventada": "nombra herramientas que no existen",
    "encargo_como_hecho": "da por creada una aplicación sin constancia de su encargo terminado y verificado",
}


def _frases(plano: str) -> list[str]:
    return [f for f in re.split(r"(?<=[.!?:])\s+|\n+", plano) if f.strip()]


def _afirmacion(patron: re.Pattern[str], texto: str) -> re.Match[str] | None:
    """Negación local de actividad; no silencia otra afirmación de la misma frase."""
    return next((m for m in patron.finditer(texto)
                 if not re.search(r"\b(?:no|nunca|tampoco)\s+(?:(?:se|hay|tengo|tenemos|existen)\s+)?$",
                                  texto[:m.start()])), None)


def revisar(texto: str, llamadas: list[dict[str, Any]], ofrecidas: set[str] | frozenset[str],
            estado: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Hallazgos de la respuesta final. Cada uno: {"codigo", "detalle", "cita"} (la cita, ≤160 caracteres)."""
    plano = _plano(texto)
    out: list[dict[str, str]] = []

    def add(codigo: str, cita: str) -> None:
        if all(h["codigo"] != codigo for h in out):
            out.append({"codigo": codigo, "detalle": DESCRIPCION[codigo], "cita": cita.strip()[:160]})

    # 21/11/2026 (titular: «no se cierre nada si puede hacerse en segundo plano»): si en este turno se lanzó de
    # verdad un encargo (tiene id), decir que sigue en marcha o que puedes ver su avance es cierto y no se marca.
    en_marcha = any(c.get("ok") and c.get("name") == "eolfi_vscode_encargo" and c.get("encargo") for c in llamadas)
    if not en_marcha and (m := _afirmacion(EN_CURSO, plano)):
        add("accion_en_curso", m.group(0))
    for frase in _frases(plano):
        # «Te avisaré» sigue siendo falso aunque haya encargo: el chat no escribe después de responder.
        if ((m := _afirmacion(PROMESA, frase)) and not OFERTA.search(frase)
                and not (en_marcha and re.search(r"\bpodras\s+(?:seguir|ver)\b", m.group(0)))):
            add("accion_en_curso", m.group(0))
            break
    # La negación afecta solo a esta afirmación, no a otra posterior en la respuesta.
    hecho = _afirmacion(HECHO, plano)
    encargos = [c for c in llamadas if c.get("ok") and c.get("name") in (
        "eolfi_vscode_encargo", "eolfi_vscode_encargo_estado")]
    # Cada encargo necesita su propia comprobación; consultar otro no acredita el solicitado.
    estados = {c.get("encargo"): c for c in encargos if c.get("name") == "eolfi_vscode_encargo_estado"}
    verificados = bool(encargos) and all(
        c.get("encargo") and estados.get(c["encargo"], {}).get("estado_encargo") == "hecho"
        and estados[c["encargo"]].get("proyecto_verificado") is True for c in encargos)
    if not any(c.get("ok") for c in llamadas) and (m := hecho):
        add("hecho_sin_herramienta", m.group(0))
    elif encargos and not verificados and (m := hecho):
        add("encargo_como_hecho", m.group(0))
    for frase in _frases(plano):     # «no puedo fusionar pesos» o «RSI no es …» son aclaraciones, no invenciones
        if (m := INVENTADO.search(frase)) and not NIEGA.search(frase):
            add("capacidad_inventada", m.group(0))
            break
    for frase in _frases(plano):
        if LICENCIA.search(frase) and PROPIA.search(frase) and ORIGEN.search(frase) and not NEGACION.search(frase):
            add("licencia_propia", frase)
            break
    if ((estado or {}).get("vscode") or {}).get("activo") and (m := VSCODE_NO.search(plano)):
        add("vscode_negado", m.group(0))
    if m := A_MANO.search(plano):
        add("trabajo_a_mano", m.group(0))
    conocidas = {_plano(n) for n in ofrecidas} | {"ejecutar_python"}
    inventadas = sorted({n for n in NOMBRE_HERRAMIENTA.findall(plano) if n not in conocidas})
    if inventadas:
        add("herramienta_inventada", ", ".join(inventadas))
    return out


def correccion(hallazgos: list[dict[str, str]]) -> str:
    """Mensaje para la ronda de corrección (lo recibe el modelo, no el usuario)."""
    lineas = "\n".join(f"- {h['detalle']} (cita: «{h['cita']}»)" for h in hallazgos)
    return ("Revisión automática de Eolfi: tu respuesta contiene afirmaciones que no se sostienen:\n" + lineas +
            "\nReescribe la respuesta COMPLETA corrigiendo solo eso y manteniendo un tono cercano: afirma únicamente lo "
            "que han devuelto las herramientas, lo que no se puede hacer dilo claramente, y lo que se podría hacer "
            "después preséntalo como propuesta o pregunta («¿quieres que lo lance ahora?»). No llames a más "
            "herramientas.")


def aviso(hallazgos: list[dict[str, str]]) -> str:
    """Aviso visible que Eolfi antepone si la respuesta corregida sigue fallando."""
    return ("⚠ Ojo: al revisar mi respuesta he visto esto: " +
            "; ".join(h["detalle"] for h in hallazgos) + ". Tómala con cautela.\n\n")
