"""Compatibilidade mínima para executar o servidor de testes sem instalar Flask.
NÃO é o Flask oficial; serve apenas para o teste offline desta aplicação.
"""
import json, re, threading, traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit, parse_qs

_local=threading.local()

class _Request:
    @property
    def method(self): return getattr(_local,'method','GET')
    @property
    def args(self): return _Args(getattr(_local,'args',{}))
    @property
    def headers(self): return getattr(_local,'headers',{})
    def get_json(self, force=False):
        raw=getattr(_local,'body',b'')
        if not raw: return None
        try:return json.loads(raw.decode('utf-8'))
        except Exception:
            if force:return None
            raise
request=_Request()

class _Args(dict):
    def get(self,key,default=None,type=None):
        v=super().get(key, [default]); v=v[0] if isinstance(v,list) else v
        if v is None:return default
        if type:
            try:return type(v)
            except:return default
        return v

class _Response:
    def __init__(self,data,status=200):
        self.data=json.dumps(data,ensure_ascii=False).encode('utf-8')
        self.status_code=status
        self.headers={'Content-Type':'application/json; charset=utf-8'}

def jsonify(**kwargs): return _Response(kwargs)

class Flask:
    def __init__(self,name): self.routes=[]
    def route(self,path,methods=None):
        methods=methods or ['GET']
        def deco(fn):
            self.routes.append((path,set(methods),fn)); return fn
        return deco
    def _match(self,template,path):
        partes=[];inicio=0
        for achado in re.finditer(r'<int:(\w+)>|<(\w+)>',template):
            partes.append(re.escape(template[inicio:achado.start()]))
            nome=achado.group(1) or achado.group(2)
            partes.append(f'(?P<{nome}>{"[0-9]+" if achado.group(1) else "[^/]+"})')
            inicio=achado.end()
        partes.append(re.escape(template[inicio:]))
        m=re.fullmatch(''.join(partes),path)
        return m.groupdict() if m else None
    def run(self,host='127.0.0.1',port=5000,debug=False,use_reloader=False,threaded=True):
        app=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,fmt,*args): pass
            def do_GET(self): self.handle_req()
            def do_POST(self): self.handle_req()
            def do_PUT(self): self.handle_req()
            def do_DELETE(self): self.handle_req()
            def handle_req(self):
                u=urlsplit(self.path); path=u.path; args=parse_qs(u.query,keep_blank_values=True)
                body=self.rfile.read(int(self.headers.get('Content-Length','0') or 0))
                for template,methods,fn in app.routes:
                    params=app._match(template,path)
                    if params is not None and self.command in methods:
                        _local.method=self.command; _local.args=args; _local.body=body; _local.headers=dict(self.headers.items())
                        try:
                            result=fn(**{k:int(v) if v.isdigit() else v for k,v in params.items()})
                            status=200
                            if isinstance(result,tuple): result,status=result
                            if isinstance(result,_Response): resp=result
                            elif isinstance(result,dict): resp=_Response(result)
                            else: resp=_Response({'resultado':result})
                            if status != 200: resp.status_code=status
                        except Exception as e:
                            traceback.print_exc()
                            resp=_Response({'erro':str(e)},500)
                        self.send_response(resp.status_code)
                        for k,v in resp.headers.items(): self.send_header(k,v)
                        self.send_header('Content-Length',str(len(resp.data))); self.end_headers(); self.wfile.write(resp.data); return
                self.send_response(404); self.end_headers()
        ThreadingHTTPServer((host,port),Handler).serve_forever()
