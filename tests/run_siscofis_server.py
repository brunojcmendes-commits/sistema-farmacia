"""Servidor real com base descartável, usado exclusivamente pelos testes."""
from pathlib import Path
import os
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'server'))
sys.path.insert(0, str(root / 'server/base'))
os.environ['FARMACIA_DATA_DIR'] = sys.argv[1]
import servidor_estoque as s
from recebimentos_siscofis import instalar
from localizador_estoque import instalar as instalar_localizador

salt, digest = s._hash_senha('TesteSiscofis!42')
c = s._conn()
c.execute("UPDATE usuarios SET senha_salt=?,senha_hash=?,trocar_senha=0 WHERE usuario='gerente'", (salt, digest))
c.commit()
c.close()
s.db.cadastrar_lote('Materiais', 'Estoque anterior preservado', 'ANTES', '01/01/2030', 17, None)
instalar(s.app, s._conn, s._lock, s._agora, s._exigir_login, s.CATEGORIAS)
instalar_localizador(s.app, s._conn, s._lock, s._agora, s._exigir_login, s.CATEGORIAS)
s.iniciar_servidor('127.0.0.1', int(sys.argv[2]))
