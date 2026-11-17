"""Auditoría estática de archivos GGUF (16/11/2026): estructura, datos sobrantes, cadenas con URL y plantilla."""
import hashlib, json, re, struct, sys, os
T = {0:'B',1:'b',2:'H',3:'h',4:'I',5:'i',6:'f',7:'?',10:'Q',11:'q',12:'d'}
# tipo ggml -> (elementos por bloque, bytes por bloque)
BLK = {0:(1,4),1:(1,2),2:(32,18),3:(32,20),6:(32,22),7:(32,24),8:(32,34),9:(32,36),10:(256,84),11:(256,110),
       12:(256,144),13:(256,176),14:(256,210),15:(256,292),24:(1,1),25:(1,2),26:(1,4),27:(1,8),28:(1,8),30:(1,2)}
URL = re.compile(r"https?://[^\s\"'<>)]+|\b(?:curl|wget|fetch\(|XMLHttpRequest|socket|powershell|cmd\.exe|eval\(|exec\(|__import__|os\.system|subprocess)\b", re.I)
def rd(f, fmt): return struct.unpack('<'+fmt, f.read(struct.calcsize(fmt)))[0]
def rs(f): return f.read(rd(f,'Q')).decode('utf-8','replace')
def val(f, t):
    if t == 8: return rs(f)
    if t == 9:
        at, n = rd(f,'I'), rd(f,'Q')
        return [rs(f) for _ in range(n)] if at == 8 else [rd(f, T[at]) for _ in range(n)]
    return rd(f, T[t])
def auditar(path, con_hash=True):
    r = {"archivo": path, "bytes": os.path.getsize(path)}
    with open(path,'rb') as f:
        if f.read(4) != b'GGUF': return {**r, "error": "no es GGUF"}
        r["version"] = rd(f,'I'); nt, nkv = rd(f,'Q'), rd(f,'Q')
        meta, hallazgos, tokens_raros = {}, [], 0
        for _ in range(nkv):
            k = rs(f); t = rd(f,'I'); v = val(f, t)
            meta[k] = v
            cad = [v] if isinstance(v, str) else [x for x in v if isinstance(x, str)] if isinstance(v, list) else []
            if k == "tokenizer.ggml.tokens":
                tokens_raros = sum(1 for x in cad if URL.search(x) and x.lower().startswith("http"))
                continue
            for x in cad:
                for m in URL.finditer(x):
                    hallazgos.append((k, m.group(0)[:100]))
        tensores = []
        for _ in range(nt):
            _nombre = rs(f); nd = rd(f,'I'); dims = [rd(f,'Q') for _ in range(nd)]; tp = rd(f,'I'); off = rd(f,'Q')
            tensores.append((off, tp, dims))
        ali = meta.get("general.alignment", 32)
        base = (f.tell() + ali - 1) // ali * ali
        off, tp, dims = max(tensores)
        elems = 1
        for d in dims: elems *= d
        if tp in BLK:
            e, b = BLK[tp]; fin = base + off + (elems + e - 1) // e * b
            r["bytes_sobrantes"] = r["bytes"] - fin
        else:
            r["bytes_sobrantes"] = f"tipo de tensor {tp} sin tabla"
        tpl = meta.get("tokenizer.chat_template", "")
        r.update({"tensores": nt, "claves": nkv, "arquitectura": meta.get("general.architecture"),
                  "nombre": meta.get("general.name"), "origen": {k: v for k, v in meta.items() if k.startswith("general.") and isinstance(v, str) and ("url" in k or "source" in k or "repo" in k or "license" in k or "base_model" in k)},
                  "claves_fuera_de_norma": sorted(k for k in meta if not k.startswith(("general.", "tokenizer.", meta.get("general.architecture","?") + ".", "quantize."))),
                  "plantilla_bytes": len(tpl), "plantilla_sha256": hashlib.sha256(tpl.encode()).hexdigest()[:16],
                  "cadenas_sospechosas": sorted(set(hallazgos)), "tokens_con_url": tokens_raros})
    if con_hash:
        h = hashlib.sha256()
        with open(path,'rb') as f:
            for b in iter(lambda: f.read(8 << 20), b''): h.update(b)
        r["sha256"] = h.hexdigest()
    return r
for p in sys.argv[1:]:
    print(json.dumps(auditar(p), ensure_ascii=False, indent=1)); sys.stdout.flush()
