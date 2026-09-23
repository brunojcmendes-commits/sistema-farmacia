import http.server
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib import request,error

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'windows/src'))
from desktop_bridge import Bridge,create_server,normalize_server,DEFAULT_SERVER

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.b=Bridge(directory=self.tmp.name)
        self.calls=[]
        def remote(method,path,body=None):
            self.calls.append((method,path,body))
            if path=='/login':return 200,{'token':'private-test-token','usuario':{'id':1,'nome':'Teste','perfil':'gerente','trocar_senha':False}}
            return 200,{'ok':True}
        self.b.remote=remote
    def tearDown(self):self.tmp.cleanup()
    def test_default_ip_and_config_preservation(self):
        self.assertEqual(self.b.server,DEFAULT_SERVER)
        self.b.config_path.write_text(json.dumps({'preferencia_existente':'manter','servidor_url':DEFAULT_SERVER}))
        self.b.save_server('10.0.0.8:5000')
        saved=json.loads(self.b.config_path.read_text())
        self.assertEqual(saved['preferencia_existente'],'manter')
        self.assertEqual(saved['servidor_url'],'http://10.0.0.8:5000')
        self.assertEqual(self.b.dispatch('GET','/pedidos')[0],401)
    def test_login_does_not_send_token_to_browser(self):
        code,result=self.b.dispatch('POST','/login',{'usuario':'teste','senha':'fixture'})
        self.assertEqual(code,200);self.assertNotIn('token',result)
        self.assertNotIn('token',self.b.metadata());self.assertEqual(self.b.token,'private-test-token')
    def test_permissions_enforced_before_forwarding(self):
        self.assertEqual(self.b.dispatch('GET','/auditoria')[0],401)
        self.b.user={'perfil':'administrador'}
        for path in ('/auditoria','/usuarios','/usuarios/4/ativo'):
            self.assertEqual(self.b.dispatch('GET',path)[0],403)
        self.assertFalse(self.calls)
        self.b.user={'perfil':'gerente','trocar_senha':True}
        self.assertEqual(self.b.dispatch('POST','/itens',{})[0],403)
        self.assertEqual(self.b.dispatch('POST','/minha-senha',{'nova_senha':'nova-senha'})[0],200)
        self.assertFalse(self.b.user['trocar_senha'])
    def test_client_cannot_access_management_even_if_remote_allows(self):
        self.b.mode='cliente'
        for method,path in [('GET','/pedidos'),('GET','/historico'),('POST','/itens'),('GET','/auditoria')]:
            self.assertEqual(self.b.dispatch(method,path,{})[0],403)
        self.assertFalse(self.calls)
        self.assertEqual(self.b.dispatch('POST','/retiradas',{'itens':[]})[0],200)
    def test_network_failure_is_not_empty_success_or_retried(self):
        class Offline:
            def __init__(self):self.calls=0
            def open(self,*a,**k):self.calls+=1;raise error.URLError('offline')
        b=Bridge(directory=self.tmp.name);b.opener=Offline()
        status,result=b.remote('GET','/lotes');self.assertEqual(status,502);self.assertFalse(result['resultado_incerto'])
        status,result=b.remote('POST','/retiradas',{});self.assertEqual(status,502);self.assertTrue(result['resultado_incerto']);self.assertEqual(b.opener.calls,2)
    def test_url_validation(self):
        self.assertEqual(normalize_server('10.56.121.242:5000'),DEFAULT_SERVER)
        for v in ('file:///tmp/a','http://host/path','http://user:password@host','http://host/?x=1'):
            with self.assertRaises(ValueError):normalize_server(v)
    def test_loopback_api_rejects_missing_key_and_cross_origin(self):
        root=Path(self.tmp.name)/'web';root.mkdir();(root/'index.html').write_text('test')
        srv=create_server(self.b,root);thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{srv.server_port}'
        try:
            for headers in ({},{'X-Sistfarma-Key':self.b.key,'Origin':'https://unrelated.invalid'}):
                with self.assertRaises(error.HTTPError) as caught:request.urlopen(request.Request(base+'/api/config',headers=headers))
                self.assertEqual(caught.exception.code,403)
            with request.urlopen(request.Request(base+'/api/config',headers={'X-Sistfarma-Key':self.b.key})) as r:
                self.assertEqual(json.load(r)['servidor_url'],DEFAULT_SERVER)
            with request.urlopen(base+'/bootstrap.js') as r:self.assertNotIn(b'private-test-token',r.read())
            with self.assertRaises(error.HTTPError):request.urlopen(base+'/%2e%2e/config_cliente.json')
        finally:srv.shutdown();srv.server_close();thread.join()

if __name__=='__main__':unittest.main()
