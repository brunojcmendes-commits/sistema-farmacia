"""Local desktop gateway; reuses the existing server without touching its DB."""
import argparse
import hmac
import http.server
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
from urllib import error, parse, request
import webbrowser

VERSION = '1.4.1'
DEFAULT_SERVER = 'http://10.56.121.242:5000'


def data_directory():
    if os.environ.get('FARMACIA_CLIENT_DATA_DIR'):
        return Path(os.environ['FARMACIA_CLIENT_DATA_DIR'])
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'FarmaciaCliente'
    return Path.home() / '.local/share/farmacia-cliente'


def normalize_server(value):
    value = str(value).strip()
    if '://' not in value:
        value = 'http://' + value
    parts = parse.urlsplit(value)
    if (parts.scheme not in ('http', 'https') or not parts.hostname or
            parts.username or parts.password or parts.query or parts.fragment or
            parts.path not in ('', '/')):
        raise ValueError('Informe somente o endereço e a porta do servidor.')
    port = parts.port or (443 if parts.scheme == 'https' else 5000)
    host = parts.hostname
    if ':' in host:
        host = '[' + host + ']'
    return f'{parts.scheme}://{host}:{port}'


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Bridge:
    def __init__(self, mode='gestor', server=None, directory=None):
        self.mode = mode
        self.directory = Path(directory) if directory else data_directory()
        self.config_path = self.directory / 'config_cliente.json'
        self.config = {}
        if self.config_path.exists():
            try:
                self.config = json.loads(self.config_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                pass
        self.server = normalize_server(server or self.config.get('servidor_url') or DEFAULT_SERVER)
        self.key = secrets.token_urlsafe(32)
        self.token = ''
        self.user = None
        self.lock = threading.RLock()
        self.last_seen = time.monotonic()
        self.opener = request.build_opener(request.ProxyHandler({}), NoRedirect())

    def metadata(self):
        return {'versao': VERSION, 'modo': self.mode, 'servidor_url': self.server, 'usuario': self.user}

    def save_server(self, value):
        server = normalize_server(value)
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.config_path.exists():
            self.config = json.loads(self.config_path.read_text(encoding='utf-8'))
        self.config['servidor_url'] = server
        temp = self.config_path.with_name('config_cliente.' + secrets.token_hex(6) + '.tmp')
        temp.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, self.config_path)
        self.server, self.token, self.user = server, '', None

    def remote(self, method, path, body=None):
        headers = {'Accept': 'application/json', 'User-Agent': 'SISTFARMA/' + VERSION}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        payload = None
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        req = request.Request(self.server + path, data=payload, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=10) as response:
                return response.status, json.loads(response.read(16 * 1024 * 1024))
        except error.HTTPError as exc:
            try:
                data = json.loads(exc.read(1024 * 1024))
            except (ValueError, OSError):
                data = {'erro': f'O servidor retornou o erro {exc.code}.'}
            if exc.code == 401:
                self.token, self.user = '', None
            return exc.code, data
        except (error.URLError, TimeoutError, OSError, ValueError):
            message = 'Não foi possível consultar o servidor. Verifique a rede e o endereço configurado.'
            if method != 'GET':
                message = ('Não foi possível confirmar a resposta do servidor. Confira o resultado '
                           'antes de repetir a operação, pois ela pode ter sido registrada.')
            return 502, {'erro': message, 'resultado_incerto': method != 'GET'}

    def dispatch(self, method, path, body=None):
        endpoint = parse.urlsplit(path).path
        if endpoint == '/config' and method == 'GET':
            return 200, self.metadata()
        if endpoint == '/heartbeat' and method == 'POST':
            self.last_seen = time.monotonic()
            return 200, {'ok': True}
        if endpoint == '/config' and method == 'POST':
            self.save_server((body or {}).get('servidor_url', ''))
            return 200, self.metadata()
        if endpoint == '/ping' and method == 'GET':
            return self.remote(method, path)
        if endpoint == '/login' and method == 'POST' and self.mode == 'gestor':
            status, result = self.remote(method, path, body)
            if status == 200 and result.get('token') and isinstance(result.get('usuario'), dict):
                self.token, self.user = result['token'], result['usuario']
                return 200, {'usuario': self.user}
            return (502, {'erro': 'Resposta de login inválida.'}) if status == 200 else (status, result)
        if endpoint == '/logout' and method == 'POST':
            if self.token:
                self.remote('POST', '/logout', {})
            self.token, self.user = '', None
            return 200, {'ok': True}
        if endpoint == '/classico' and method == 'POST':
            if getattr(sys, 'frozen', False):
                cmd = [sys.executable, '--classico']
            else:
                script = 'gestor_html.py' if self.mode == 'gestor' else 'cliente_html.py'
                cmd = [sys.executable, str(Path(__file__).parent / script), '--classico']
            subprocess.Popen(cmd, close_fds=True)
            return 200, {'ok': True}
        client_routes = {('GET', '/categorias'), ('GET', '/medicamentos'),
                         ('GET', '/lotes'), ('POST', '/retiradas')}
        if self.mode == 'cliente':
            if (method, endpoint) not in client_routes:
                return 403, {'erro': 'Esta função pertence ao Gestor Farmácia.'}
        elif not self.user:
            return 401, {'erro': 'Entre com seu usuário para acessar o Gestor Farmácia.'}
        if endpoint in ('/auditoria', '/usuarios') or endpoint.startswith('/usuarios/'):
            if not self.user or self.user.get('perfil') != 'gerente':
                return 403, {'erro': 'Acesso exclusivo ao Gerente.'}
        allowed = {
            'GET': r'/(categorias|medicamentos|lotes|apoio|apoio/alertas|lotes-excluidos|historico|alertas|pedidos|pedidos/\d+|conferencias/semana|conferencias/historico|auditoria|usuarios|notificacoes)',
            'POST': r'/(retiradas|itens|apoio|estoque/transferir|conferencias/\d+|pedidos/\d+/(status|conferir)|usuarios|usuarios/\d+/ativo|minha-senha|backup)',
            'PUT': r'/itens', 'DELETE': r'/(itens|apoio)',
        }
        if method not in allowed or not re.fullmatch(allowed[method], endpoint):
            return 404, {'erro': 'Operação não disponível.'}
        if self.user and self.user.get('trocar_senha') and endpoint != '/minha-senha':
            return 403, {'erro': 'Altere a senha inicial para continuar.'}
        result = self.remote(method, path, body)
        if endpoint == '/minha-senha' and result[0] == 200:
            self.user['trocar_senha'] = False
        return result


def create_server(bridge, web_root, port=0):
    root = Path(web_root).resolve()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send_bytes(self, status, content, content_type):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def json(self, status, value):
            self.send_bytes(status, json.dumps(value, ensure_ascii=False, allow_nan=False).encode(), 'application/json; charset=utf-8')

        def handle_request(self):
            origin = f'http://127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') != origin[7:]:
                return self.json(403, {'erro': 'Endereço local inválido.'})
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                return self.json(403, {'erro': 'Origem inválida.'})
            if self.headers.get('Origin') not in (None, origin):
                return self.json(403, {'erro': 'Origem inválida.'})
            endpoint = parse.urlsplit(self.path).path
            if endpoint.startswith('/api/'):
                if not hmac.compare_digest(self.headers.get('X-Sistfarma-Key', ''), bridge.key):
                    return self.json(403, {'erro': 'Sessão local inválida. Reabra o aplicativo.'})
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if length < 0 or length > 1024 * 1024:
                        return self.json(413, {'erro': 'Solicitação muito grande.'})
                    body = json.loads(self.rfile.read(length)) if length else None
                    if body is not None and not isinstance(body, dict):
                        raise ValueError('Dados inválidos.')
                    if self.command == 'GET':
                        status, result = bridge.dispatch(self.command, self.path[4:], body)
                    else:
                        with bridge.lock:
                            status, result = bridge.dispatch(self.command, self.path[4:], body)
                    return self.json(status, result)
                except (ValueError, OSError) as exc:
                    return self.json(400, {'erro': str(exc) if isinstance(exc, ValueError) else 'Não foi possível salvar a configuração.'})
            if self.command != 'GET':
                return self.json(405, {'erro': 'Método não permitido.'})
            if endpoint == '/bootstrap.js':
                value = {'key': bridge.key, 'mode': bridge.mode, 'version': VERSION}
                return self.send_bytes(200, ('window.SISTFARMA=' + json.dumps(value) + ';').encode(), 'text/javascript; charset=utf-8')
            target = (root / (parse.unquote(endpoint).lstrip('/') or 'index.html')).resolve()
            if root not in target.parents or not target.is_file():
                return self.json(404, {'erro': 'Arquivo não encontrado.'})
            kind = mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
            self.send_bytes(200, target.read_bytes(), kind + ('; charset=utf-8' if kind.startswith('text/') else ''))

        do_GET = do_POST = do_PUT = do_DELETE = handle_request

    server = http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server


def main(mode='gestor'):
    parser = argparse.ArgumentParser()
    parser.add_argument('--classico', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--server')
    args = parser.parse_args()
    if args.classico:
        if mode == 'gestor':
            from gerente_farmacia_140 import App
        else:
            from cliente_farmacia import App
        App().mainloop()
        return
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    bridge = Bridge(mode, server=args.server)
    server = create_server(bridge, base / 'web', args.port)
    url = f'http://127.0.0.1:{server.server_port}/'
    if not args.no_browser:
        webbrowser.open(url)
        def idle_watch():
            while time.monotonic() - bridge.last_seen < 300:
                time.sleep(20)
            server.shutdown()
        threading.Thread(target=idle_watch, daemon=True).start()
    else:
        print(url, flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
