"""Sequential local timing probe; preserves results after each request."""
import json
import time
import urllib.request
from pathlib import Path
from eolfi import eolas_v2 as engine

def main():
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')   # redirigido en Windows: UTF-8, no cp1252
    rows = []
    output = Path('informes/model-timings.json')
    cfg = engine.load_config()
    original = cfg['active_profile']
    try:
        # Perfiles a medir: los indicados en la línea de órdenes o todos los instalados (sin nombres fijos, 18/11/2026).
        perfiles = sys.argv[1:] or [p for p in engine.available_evaluation_profiles(cfg) if p != engine.NEMO_MOE_PROFILE]
        for profile in perfiles:
            started = time.monotonic()
            engine.switch(profile)
            load = round(time.monotonic()-started, 3)
            c = engine.profile_config(profile)
            for trial in range(3):
                started = time.monotonic()
                payload = {'model': c['alias'], 'temperature': 0, 'max_tokens': 96,
                           'messages': [{'role':'user','content':'Devuelve SOLO JSON: {"resultado":43,"estado":"listo"}'}],
                           'chat_template_kwargs': {'enable_thinking':False}, 'cache_prompt':True}
                req = urllib.request.Request(c['url']+'/v1/chat/completions', data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(req, timeout=180) as response:
                    data = json.load(response)
                rows.append({'profile':profile,'trial':trial,'load_seconds':load if trial==0 else 0,
                             'request_seconds':round(time.monotonic()-started,3), 'timings':data.get('timings'),
                             'usage':data.get('usage'), 'choice':data.get('choices')})
                output.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps(rows[-1],ensure_ascii=False),flush=True)
    finally:
        engine.switch(original)

if __name__ == '__main__':
    main()
