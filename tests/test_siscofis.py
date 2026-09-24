import concurrent.futures
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid

ROOT = Path(__file__).resolve().parents[1]


class SiscofisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        cls.url = 'http://127.0.0.1:' + str(port)
        cls.token = ''
        cls.process = subprocess.Popen([sys.executable, str(ROOT/'tests/run_siscofis_server.py'), cls.temp.name, str(port)], stdout=subprocess.DEVNULL)
        for _ in range(120):
            try:
                with urlopen(cls.url + '/ping', timeout=1):
                    break
            except OSError:
                time.sleep(.1)
        else:
            cls.process.terminate()
            raise RuntimeError('Servidor de teste não iniciou')
        _, login = cls.call('/login', 'POST', {'usuario': 'gerente', 'senha': 'TesteSiscofis!42'})
        cls.token = login['token']

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=15)
        cls.temp.cleanup()

    @classmethod
    def call(cls, path, method='GET', body=None, auth=True):
        headers = {'Content-Type': 'application/json'}
        if auth:
            headers['Authorization'] = 'Bearer ' + cls.token
        req = Request(cls.url + path, data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
        try:
            with urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read())
        except HTTPError as e:
            return e.code, json.loads(e.read())

    def create(self, qty=100, localizador=''):
        name = 'Teste-' + uuid.uuid4().hex
        body = {'categoria': 'Materiais', 'medicamento': name, 'ficha': 'LOTE-1', 'validade': '01/01/2030',
                'estoque_inicial': qty, 'localizador': localizador, 'operacao_id': uuid.uuid4().hex}
        code, result = self.call('/recebimentos', 'POST', body)
        self.assertEqual(code, 200, result)
        return {'id': result['id'], 'versao': 1, 'quantidade': qty}, name, body

    def release(self, items, key=None):
        return self.call('/recebimentos/liberar', 'POST', {'itens': items, 'operacao_id': key or uuid.uuid4().hex, 'referencia': 'QA'})

    def stock(self, name):
        code, result = self.call('/lotes?categoria=Materiais', auth=False)
        self.assertEqual(code, 200)
        return sum(l['estoque_atual'] for l in result['lotes'] if l['medicamento'] == name)

    def test_blocked_in_catalog_withdrawals_and_existing_data_preserved(self):
        item, name, _ = self.create()
        self.assertEqual(self.stock(name), 0)
        self.assertEqual(self.stock('Estoque anterior preservado'), 17)
        code, result = self.call('/retiradas', 'POST', {'pg': 'Cb', 'solicitante': 'Teste', 'om': 'QA',
            'itens': [{'categoria': 'Materiais', 'medicamento': name, 'quantidade_retirada': 1}]}, auth=False)
        self.assertEqual(code, 200, result)
        self.assertFalse(result.get('itens'))
        self.assertEqual(result['itens_cancelados'][0]['medicamento'], name)
        self.assertEqual(result['itens_cancelados'][0]['disponivel'], 0)
        self.assertEqual(self.stock(name), 0)
        _, data = self.call('/recebimentos')
        self.assertEqual(next(r for r in data['recebimentos'] if r['id'] == item['id'])['saldo_pendente'], 100)

    def test_partial_release_retry_and_final_merge(self):
        item, name, body = self.create()
        self.assertEqual(self.call('/recebimentos', 'POST', body)[1]['id'], item['id'])
        item['quantidade'] = 40
        key = uuid.uuid4().hex
        code, first = self.release([item], key)
        self.assertEqual(code, 200, first)
        self.assertEqual(self.release([item], key), (200, first))
        self.assertEqual(self.stock(name), 40)
        self.assertEqual(first['liberados'][0]['saldo_pendente'], 60)
        self.assertEqual(self.release([item])[0], 409)
        item.update(versao=2, quantidade=60)
        self.assertEqual(self.release([item])[0], 200)
        self.assertEqual(self.stock(name), 100)
        _, data = self.call('/recebimentos')
        self.assertNotIn(item['id'], [r['id'] for r in data['recebimentos']])
        _, history = self.call('/recebimentos/historico')
        releases = [r for r in history['liberacoes'] if r['recebimento_id'] == item['id']]
        self.assertEqual(sum(r['quantidade'] for r in releases), 100)
        self.assertEqual(len({r['lote_id'] for r in releases}), 1)

    def test_batch_is_atomic_and_invalid_quantities_rejected(self):
        one, name, _ = self.create()
        two, _, _ = self.create()
        two['quantidade'] = 101
        self.assertEqual(self.release([one, two])[0], 409)
        self.assertEqual(self.stock(name), 0)
        self.assertEqual(self.release([one, one])[0], 400)
        for value in (0, -1, 'NaN', 'Infinity', True):
            self.assertEqual(self.release([{**one, 'quantidade': value}])[0], 400)
        self.assertEqual(self.stock(name), 0)

    def test_concurrent_release_cannot_duplicate_stock(self):
        item, name, _ = self.create()
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.release([item]), range(2)))
        self.assertEqual(sorted(r[0] for r in results), [200, 409])
        self.assertEqual(self.stock(name), 100)

    def test_edit_cancel_auth_and_immutable_history(self):
        item, name, body = self.create()
        self.assertEqual(self.call('/recebimentos', auth=False)[0], 401)
        self.assertEqual(self.call('/recebimentos/liberar', 'POST', {}, auth=False)[0], 401)
        self.assertEqual(self.release([{**item, 'quantidade': 20}])[0], 200)
        edit = {**body, 'medicamento': name+' corrigido', 'saldo_pendente': 70, 'versao': 2, 'operacao_id': uuid.uuid4().hex}
        self.assertEqual(self.call('/recebimentos/'+str(item['id']), 'PUT', edit)[0], 200)
        _, history = self.call('/recebimentos/historico')
        self.assertEqual(next(r for r in history['liberacoes'] if r['recebimento_id'] == item['id'])['medicamento'], name)
        cancel = {'versao': 3, 'motivo': 'Devolução', 'operacao_id': uuid.uuid4().hex}
        self.assertEqual(self.call('/recebimentos/'+str(item['id']), 'DELETE', cancel)[0], 200)
        self.assertEqual(self.stock(name), 20)
        self.assertEqual(self.release([{**item, 'versao': 4}])[0], 409)
        _, audit = self.call('/auditoria')
        self.assertTrue(any(r['acao'] == 'LIBERAR_SISCOFIS_PARA_ESTOQUE' for r in audit['registros']))

    def test_localizador_on_create_edit_order_and_pending_release(self):
        name = 'Localização ' + uuid.uuid4().hex
        def register(location, qty):
            code, result = self.call('/itens-localizados', 'POST', {'categoria': 'Materiais',
                'medicamento': name, 'ficha': 'SAME', 'validade': '01/01/2030',
                'estoque_inicial': qty, 'localizador': location, 'operacao_id': uuid.uuid4().hex})
            self.assertEqual(code, 200, result)
            return result['id']
        first, second = register('Sala A · P1', 2), register('Sala B · P2', 5)
        self.assertNotEqual(first, second)
        self.assertEqual(self.call('/localizadores', auth=False)[0], 401)
        _, stock = self.call('/lotes?categoria=Materiais', auth=False)
        self.assertNotIn('localizador', next(r for r in stock['lotes'] if r['id'] == first))
        code, order = self.call('/retiradas', 'POST', {'pg': 'Cb', 'solicitante': 'QA', 'om': 'Teste',
            'itens': [{'categoria': 'Materiais', 'medicamento': name, 'quantidade_retirada': 5}]}, auth=False)
        self.assertEqual(code, 200, order)
        _, found = self.call('/pedidos/'+str(order['pedido_id'])+'/localizadores')
        locations = found['itens'][0]['localizadores']
        self.assertEqual({r['localizador']: r['quantidade'] for r in locations}, {'Sala A · P1': 2, 'Sala B · P2': 3})
        self.assertEqual(self.call('/itens-localizados', 'PUT', {'lote_id': first, 'categoria': 'Materiais',
            'medicamento': name, 'ficha': 'SAME', 'validade': '01/01/2030', 'estoque_inicial': 2,
            'estoque_atual': 0, 'localizador': 'Sala C · P3', 'operacao_id': uuid.uuid4().hex})[0], 200)
        _, changed = self.call('/pedidos/'+str(order['pedido_id'])+'/localizadores')
        self.assertEqual(changed['itens'][0]['localizadores'][0]['localizador'], 'Sala C · P3')
        pending, pending_name, _ = self.create(qty=10, localizador='Aguardando · S1')
        self.assertEqual(self.release([{**pending, 'quantidade': 4}])[0], 200)
        _, rows = self.call('/recebimentos')
        row = next(r for r in rows['recebimentos'] if r['id'] == pending['id'])
        self.assertEqual(row['localizador'], 'Aguardando · S1')
        self.assertEqual(self.call('/recebimentos/'+str(pending['id']), 'PUT', {'categoria': 'Materiais',
            'medicamento': pending_name, 'ficha': 'LOTE-1', 'validade': '01/01/2030',
            'saldo_pendente': 6, 'versao': 2, 'localizador': 'Liberado · E2',
            'operacao_id': uuid.uuid4().hex})[0], 200)
        self.assertEqual(self.release([{**pending, 'versao': 3, 'quantidade': 6}])[0], 200)
        _, all_lots = self.call('/lotes?categoria=Materiais')
        ids = [r['id'] for r in all_lots['lotes'] if r['medicamento'] == pending_name]
        _, locs = self.call('/localizadores')
        self.assertEqual({r['localizador'] for r in locs['localizadores'] if r['id'] in ids},
                         {'Aguardando · S1', 'Liberado · E2'})


class InstallerTests(unittest.TestCase):
    def test_schema_upgrade_preserves_existing_lots_and_pending_receipts(self):
        sys.path.insert(0, str(ROOT/'server/base'))
        spec = importlib.util.spec_from_file_location('locator', ROOT/'server/localizador_estoque.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.path.pop(0)
        class App:
            def route(self, *_args, **_kwargs):
                return lambda fn: fn
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'farmacia.db'
            with closing(sqlite3.connect(path)) as c:
                c.executescript('''CREATE TABLE lotes(id INTEGER PRIMARY KEY, medicamento TEXT, estoque_atual REAL);
                    CREATE TABLE recebimentos_siscofis(id INTEGER PRIMARY KEY, medicamento TEXT, saldo_pendente REAL);
                    INSERT INTO lotes VALUES(1,'Anterior',17);
                    INSERT INTO recebimentos_siscofis VALUES(2,'Pendente',8);''')
            def conn():
                c = sqlite3.connect(path)
                c.row_factory = sqlite3.Row
                return c
            for _ in range(2):
                module.instalar(App(), conn, threading.RLock(), lambda: '', lambda: ({},None), [])
            with closing(conn()) as c:
                self.assertEqual(c.execute('SELECT medicamento,estoque_atual,localizador FROM lotes').fetchone()[:], ('Anterior',17,''))
                self.assertEqual(c.execute('SELECT medicamento,saldo_pendente,localizador FROM recebimentos_siscofis').fetchone()[:], ('Pendente',8,''))

    def test_extension_patch_backup_idempotence_and_removal(self):
        spec = importlib.util.spec_from_file_location('siscofis_installer', ROOT/'server/instalar_extensao.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'opt/farmacia-servidor/servidor_estoque.py'
            source.parent.mkdir(parents=True)
            shutil.copy2(ROOT/'server/base/servidor_estoque.py', source)
            original = source.read_bytes()
            database = root/'var/lib/farmacia-servidor/farmacia.db'
            database.parent.mkdir(parents=True)
            with closing(sqlite3.connect(database)) as c:
                c.execute('CREATE TABLE estoque(valor INTEGER)')
                c.execute('INSERT INTO estoque VALUES(17)')
                c.commit()
            backup = module.atualizar(root)
            self.assertEqual((backup/source.name).read_bytes(), original)
            with closing(sqlite3.connect(backup/'farmacia-servico.db')) as c:
                self.assertEqual(c.execute('SELECT valor FROM estoque').fetchone()[0], 17)
            self.assertIsNone(module.atualizar(root))
            module.atualizar(root, remove=True)
            self.assertEqual(source.read_bytes(), original)
            previous = "# BEGIN SISTFARMA SISCOFIS 1.4.2\nfrom recebimentos_siscofis import instalar as _instalar_siscofis\n_instalar_siscofis(app, _conn, _lock, _agora, _exigir_login, CATEGORIAS)\n# END SISTFARMA SISCOFIS 1.4.2\n"
            marker = "if __name__=='__main__':iniciar_servidor()"
            source.write_text(original.decode().replace(marker, previous+marker), encoding='utf-8')
            module.atualizar(root)
            self.assertIn(module.START, source.read_text())
            self.assertNotIn('SISCOFIS 1.4.2', source.read_text())
            module.atualizar(root, remove=True)
            self.assertEqual(source.read_bytes(), original)
            source.write_text('unsupported server')
            with self.assertRaises(RuntimeError):
                module.atualizar(root)
            self.assertEqual(source.read_text(), 'unsupported server')


if __name__ == '__main__':
    unittest.main()
