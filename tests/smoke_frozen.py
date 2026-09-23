"""Verify bundled HTML/modules are present in both frozen desktop apps."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

for name in ('Gerente_Farmacia.exe','Cliente_Farmacia.exe'):
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    p=subprocess.Popen([str(Path(sys.argv[1]).resolve()/name),'--no-browser','--port',str(port)])
    try:
        for attempt in range(80):
            if p.poll() is not None:raise RuntimeError(name+' encerrou antes de abrir a interface')
            try:
                with urlopen(f'http://127.0.0.1:{port}/',timeout=1) as r:
                    assert b'SISTFARMA' in r.read()
                break
            except OSError:time.sleep(.25)
        else:raise RuntimeError(name+' nao iniciou')
        for asset,marker in [('bootstrap.js',b'1.4.1'),('app.js',b'renderDashboard'),('data.js',b'stockMetrics'),('app.css',b'.sidebar'),('brand.svg',b'<svg')]:
            with urlopen(f'http://127.0.0.1:{port}/{asset}',timeout=3) as r:assert marker in r.read(),asset
        print(name+': executavel e recursos internos OK')
    finally:
        p.terminate();p.wait(timeout=15)
