"""G1 en vivo (8777, Gemma real): ¿elige el modelo eolfi_modelos_auditar sin que se le nombre?"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8777"
H = {"Content-Type": "application/json", "X-Eolfi": "1"}
Q4 = r"D:\Alejandria\corpus\modelos.gguf\objetos\sha256\43\43fec98c5102b1c446b4ddd0a9439f1db3a2e1f2e0b8cd143ce1ea619a9403d6\pesos.gguf"
CASOS = [
    ("1 GGUF por ruta", f"¿Me puedo fiar del archivo de modelo {Q4}? Revisa su estructura, su plantilla y su hash "
                        "sin cargarlo y dime si ves algo raro.", "eolfi_modelos_auditar"),
    ("2 carpeta de modelos", "¿Qué modelos hay en la carpeta " + Q4.rsplit("\\", 1)[0] + " y qué tamaño tienen?",
     "eolfi_modelos_auditar"),
    ("3 control: ejecutable", r"¿Qué es el archivo C:\Windows\System32\notepad.exe? Analízalo y resúmelo.",
     "eolfi_triage"),
]


def api(path, body=None):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode() if body is not None else None, H,
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def chat(etiqueta, texto):
    t0 = time.time()
    for _ in range(120):   # si otra sesión usa el motor, se espera el turno
        job = api("/api/jobs", {"kind": "chat", "body": {"name": f"G1 · {etiqueta}",
                                                          "messages": [{"role": "user", "content": texto}]}})
        while True:
            d = api(f"/api/jobs?id={job['job_id']}")
            if d["status"] not in ("queued", "running"):
                break
            time.sleep(3)
        if "está respondiendo una petición" not in str(d.get("error")):
            break
        time.sleep(30)
    r = d.get("result") or {}
    return {"etiqueta": etiqueta, "estado": d["status"], "error": d.get("error"), "segundos": round(time.time() - t0),
            "herramientas": [{"name": t["name"], "ok": t["ok"], "args": str(t.get("args"))[:200],
                              **({"error": t["error"]} if t.get("error") else {})} for t in r.get("tools", [])],
            "respuesta": (r.get("text") or "")[:1500]}


salida = []
for etiqueta, texto, esperada in CASOS:
    res = chat(etiqueta, texto)
    usadas = [t["name"] for t in res["herramientas"]]
    res["esperada"] = esperada
    res["elige_la_esperada"] = esperada in usadas
    res["auditor_usado"] = "eolfi_modelos_auditar" in usadas
    salida.append(res)
    print(json.dumps(res, ensure_ascii=False, indent=1), flush=True)
json.dump(salida, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
