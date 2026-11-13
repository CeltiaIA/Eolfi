"""Run isolated real Eolfi creation jobs; persist progress and results."""
import argparse
import json
import time
import sys
import urllib.request
from pathlib import Path
from datetime import datetime

BRIEFS = {
    'small': ('Crea una calculadora de suma y resta con validación numérica, mensajes en español y pruebas para entradas inválidas. '
              'Conserva la estructura HTML existente, main, lang y la etiqueta CSP exactamente como están. '
              'Añade el formulario dentro de main; usa un módulo externo js/calculator.mjs y pruebas nuevas tests/calculator.test.mjs. '
              'No modifiques tests/site.test.mjs. Valida vacíos, texto, negativos y decimales. No añadas dependencias.'),
    'medium': 'Crea un inventario con altas, edición, borrado, búsqueda y persistencia local. Valida cantidades no negativas. Añade pruebas de validación y persistencia. No añadas dependencias.',
    'large': 'Crea gestión de pedidos con catálogo, inventario, líneas de pedido, reservas, comisión, totales e informe. Separa lógica y presentación. Persiste localmente y añade pruebas de cálculo, stock insuficiente y recuperación. No añadas dependencias.',
}

def api(path, body=None):
    req = urllib.request.Request('http://127.0.0.1:8777'+path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'X-Eolfi':'1','Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)

def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--size', choices=BRIEFS, default='small')
    args = parser.parse_args()
    root = Path('generated') / ('nemo-benchmark-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    root.mkdir(parents=True)
    source = root / 'source.html'
    source.write_text('<!doctype html><html lang="es"><title>Banco de creación</title><h1>Aplicación de prueba</h1></html>', encoding='utf-8')
    body = {'name':'Nemo benchmark '+args.size,'sources':[str(source.resolve())],
            'out':str((root/'project').resolve()),'target':'static','ai_provider':'nemo-moe','ai_brief':BRIEFS[args.size]}
    job = api('/api/jobs', {'kind':'create','body':body})
    print(json.dumps({'job':job,'directory':str(root.resolve())}),flush=True)
    since = 0
    while True:
        status = api('/api/jobs?id='+job['job_id']+'&since='+str(since))
        (root/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
        for entry in status.get('log',[]):
            print(json.dumps(entry,ensure_ascii=False),flush=True)
        since = status.get('next',since)
        if status['status'] not in ('running','queued'):
            print(json.dumps(status,ensure_ascii=False),flush=True)
            break
        time.sleep(2)

if __name__ == '__main__':
    main()
