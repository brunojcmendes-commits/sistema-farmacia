"""Servidor de Estoque de Farmácia - SQLite / offline LAN."""
import os, sys, threading, shutil, sqlite3, socket, unicodedata, hashlib, hmac, secrets, json
from datetime import datetime, time as _time, timedelta
from flask import Flask, request, jsonify

PORTA=5000
VERSAO_SISTEMA='1.2.11'
CATEGORIAS=["Medicamentos Orais","Medicamentos Injetáveis","Medicamentos Controlados","Pomadas","Outros","Material/Medicamento Odontológico","Materiais","Soro"]
OM_LISTA=["9º B Sau","9º B Manut","18º B TRNP","Cmdo 9º GPT Log","Cia Cmdo"]
FORMATO_DATA_HORA="%d/%m/%Y %H:%M"; FORMATO_DATA="%d/%m/%Y"; DIAS_ALERTA_VALIDADE=90
BASE_DIR=os.environ.get('FARMACIA_DATA_DIR') or os.path.dirname(os.path.abspath(sys.argv[0])); os.makedirs(BASE_DIR, exist_ok=True); CAMINHO_BANCO=os.path.join(BASE_DIR,"farmacia.db")
CAMINHO_PLANILHA=os.path.join(BASE_DIR,"estoque_farmacia.xlsx")
_lock=threading.RLock(); LOG_CALLBACK=None; _notificacoes=[]; _proximo_notificacao_id=1; MAX_NOTIFICACOES=200
_sessoes={}; _contexto=threading.local(); DURACAO_SESSAO_HORAS=12

def chave_ordenacao_texto(t):
    s=unicodedata.normalize("NFKD",t or ""); return "".join(c for c in s if not unicodedata.combining(c)).lower()
def _log(m):
    try:
        if LOG_CALLBACK: LOG_CALLBACK(m); return
    except Exception: pass
    print(m,flush=True)
def tocar_bipe():
    try:
        import winsound; winsound.Beep(1200,220); winsound.Beep(1500,220)
    except Exception: print("\a",end="",flush=True)

def _agora(): return datetime.now().strftime(FORMATO_DATA_HORA)

def _data_brasileira(valor):
    """Converte datas de planilha/ISO para dd/mm/aaaa sem alterar vazios."""
    texto=str(valor or '').strip()
    if not texto:return None
    for formato in (FORMATO_DATA,'%Y-%m-%dT%H:%M:%S','%Y-%m-%d %H:%M:%S','%Y-%m-%d'):
        try:return datetime.strptime(texto,formato).strftime(FORMATO_DATA)
        except ValueError:pass
    try:return datetime.fromisoformat(texto.replace('Z','+00:00')).strftime(FORMATO_DATA)
    except ValueError:return texto

def _hash_senha(senha, salt=None):
    salt=salt or secrets.token_hex(16)
    digest=hashlib.pbkdf2_hmac('sha256',senha.encode('utf-8'),salt.encode('ascii'),180000).hex()
    return salt,digest

def _conn():
    c=sqlite3.connect(CAMINHO_BANCO, timeout=30); c.row_factory=sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON"); c.execute("PRAGMA journal_mode=WAL"); return c

class EstoqueDB:
    def __init__(self, caminho):
        global CAMINHO_BANCO
        CAMINHO_BANCO=caminho
        if not os.path.exists(caminho): self._criar()
        else: self._garantir()
    def _criar(self):
        c=_conn();
        c.executescript('''
        CREATE TABLE IF NOT EXISTS lotes(id INTEGER PRIMARY KEY AUTOINCREMENT,categoria TEXT NOT NULL,medicamento TEXT NOT NULL,ficha TEXT,apresentacao TEXT,comprimidos_cartela INTEGER,validade TEXT,estoque_inicial REAL NOT NULL DEFAULT 0,estoque_atual REAL NOT NULL DEFAULT 0,saida_total REAL NOT NULL DEFAULT 0,siscofis TEXT,observacao TEXT,ativo INTEGER NOT NULL DEFAULT 1,criado_em TEXT NOT NULL,atualizado_em TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS movimentacoes(id INTEGER PRIMARY KEY AUTOINCREMENT,data TEXT,lote_id INTEGER,categoria TEXT,medicamento TEXT,ficha TEXT,solicitante TEXT,quantidade REAL,estoque_anterior REAL,estoque_final REAL,tipo TEXT DEFAULT 'RETIRADA',observacao TEXT);
        CREATE TABLE IF NOT EXISTS lotes_excluidos(id INTEGER PRIMARY KEY AUTOINCREMENT,lote_id_original INTEGER,categoria TEXT,medicamento TEXT,ficha TEXT,apresentacao TEXT,validade TEXT,estoque_inicial REAL,estoque_restante REAL,motivo TEXT,excluido_em TEXT,excluido_por TEXT);
        CREATE TABLE IF NOT EXISTS apoio(id INTEGER PRIMARY KEY AUTOINCREMENT,material TEXT NOT NULL,lote TEXT,validade TEXT,estoque_inicial REAL DEFAULT 0,estoque_atual REAL DEFAULT 0,observacao TEXT,ativo INTEGER DEFAULT 1,criado_em TEXT,atualizado_em TEXT);
        CREATE TABLE IF NOT EXISTS pedidos(id INTEGER PRIMARY KEY,data TEXT,solicitante TEXT,pg TEXT,nome TEXT,om TEXT,categoria TEXT,medicamento TEXT,fichas TEXT,quantidade REAL,conferido TEXT,status TEXT DEFAULT 'HISTORICO',criado_em TEXT);
        CREATE TABLE IF NOT EXISTS pedido_itens(id INTEGER PRIMARY KEY AUTOINCREMENT,pedido_id INTEGER,categoria TEXT,medicamento TEXT,quantidade REAL,ficha TEXT);
        CREATE TABLE IF NOT EXISTS pedido_cabecalhos(id INTEGER PRIMARY KEY AUTOINCREMENT,data TEXT NOT NULL,solicitante TEXT NOT NULL,pg TEXT,om TEXT,status TEXT NOT NULL DEFAULT 'NOVO',criado_em TEXT NOT NULL,atualizado_em TEXT NOT NULL,atualizado_por TEXT,cancelado_em TEXT,cancelado_por TEXT);
        CREATE TABLE IF NOT EXISTS auditoria(id INTEGER PRIMARY KEY AUTOINCREMENT,data TEXT,usuario TEXT,acao TEXT,entidade TEXT,entidade_id INTEGER,detalhes TEXT);
        CREATE TABLE IF NOT EXISTS usuarios(id INTEGER PRIMARY KEY AUTOINCREMENT,usuario TEXT NOT NULL UNIQUE,nome TEXT NOT NULL,perfil TEXT NOT NULL DEFAULT 'administrador',senha_salt TEXT NOT NULL,senha_hash TEXT NOT NULL,ativo INTEGER NOT NULL DEFAULT 1,trocar_senha INTEGER NOT NULL DEFAULT 1,criado_em TEXT NOT NULL,ultimo_acesso TEXT);
        CREATE TABLE IF NOT EXISTS configuracoes(chave TEXT PRIMARY KEY,valor TEXT);
        ''')
        colunas_lotes={r[1] for r in c.execute("PRAGMA table_info(lotes)").fetchall()}
        if "comprimidos_cartela" not in colunas_lotes:
            c.execute("ALTER TABLE lotes ADD COLUMN comprimidos_cartela INTEGER")
        # Planilhas e versões antigas podiam gravar 2027-07-30T00:00:00.
        # Padroniza as validades existentes para dd/mm/aaaa uma única vez.
        for lote in c.execute("SELECT id,validade FROM lotes WHERE COALESCE(validade,'')<>''").fetchall():
            normalizada=_data_brasileira(lote["validade"])
            if normalizada and normalizada!=lote["validade"]:
                c.execute("UPDATE lotes SET validade=? WHERE id=?",(normalizada,lote["id"]))
        # Algumas instalações antigas criaram pedido_itens.pedido_id apontando
        # para a tabela legada "pedidos". A fila atual usa pedido_cabecalhos;
        # portanto, essa FK impedia a inclusão do item mesmo com o cabeçalho criado.
        fks_itens=c.execute("PRAGMA foreign_key_list(pedido_itens)").fetchall()
        if any(str(fk[2]).lower()!='pedido_cabecalhos' for fk in fks_itens):
            colunas_antigas={r[1] for r in c.execute("PRAGMA table_info(pedido_itens)").fetchall()}
            c.commit();c.execute("PRAGMA foreign_keys=OFF");c.execute("BEGIN IMMEDIATE")
            c.execute("ALTER TABLE pedido_itens RENAME TO pedido_itens_fk_antiga")
            c.execute('''CREATE TABLE pedido_itens(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pedido_id INTEGER,
                categoria TEXT,
                medicamento TEXT,
                quantidade REAL,
                ficha TEXT,
                fichas TEXT,
                movimentos_json TEXT,
                status TEXT DEFAULT 'ATENDIDO',
                motivo TEXT,
                FOREIGN KEY(pedido_id) REFERENCES pedido_cabecalhos(id)
            )''')
            nomes=['id','pedido_id','categoria','medicamento','quantidade','ficha','fichas','movimentos_json','status','motivo']
            presentes=[nome for nome in nomes if nome in colunas_antigas]
            if presentes:
                lista=','.join(presentes)
                c.execute(f"INSERT INTO pedido_itens({lista}) SELECT {lista} FROM pedido_itens_fk_antiga")
            c.execute("DROP TABLE pedido_itens_fk_antiga")
            c.commit();c.execute("PRAGMA foreign_keys=ON")
            _log('Migração concluída: chave estrangeira de pedido_itens corrigida.')
        colunas_itens={r[1] for r in c.execute("PRAGMA table_info(pedido_itens)").fetchall()}
        for nome,tipo in (("fichas","TEXT"),("movimentos_json","TEXT")):
            if nome not in colunas_itens:c.execute(f"ALTER TABLE pedido_itens ADD COLUMN {nome} {tipo}")
        colunas_itens={r[1] for r in c.execute("PRAGMA table_info(pedido_itens)").fetchall()}
        for nome,tipo in (("status","TEXT DEFAULT 'ATENDIDO'"),("motivo","TEXT")):
            if nome not in colunas_itens:c.execute(f"ALTER TABLE pedido_itens ADD COLUMN {nome} {tipo}")
        # Bancos criados por versões anteriores já possuíam a tabela de pedidos,
        # mas não necessariamente todas as colunas usadas pela fila atual.
        colunas_cabecalho={r[1] for r in c.execute("PRAGMA table_info(pedido_cabecalhos)").fetchall()}
        for nome,tipo in (
            ("pg","TEXT"),("om","TEXT"),("status","TEXT DEFAULT 'NOVO'"),
            ("criado_em","TEXT"),("atualizado_em","TEXT"),("atualizado_por","TEXT"),
            ("cancelado_em","TEXT"),("cancelado_por","TEXT"),
        ):
            if nome not in colunas_cabecalho:c.execute(f"ALTER TABLE pedido_cabecalhos ADD COLUMN {nome} {tipo}")
        if not c.execute("SELECT 1 FROM pedido_cabecalhos LIMIT 1").fetchone():
            antigos=c.execute("SELECT * FROM pedidos ORDER BY id").fetchall()
            for p in antigos:
                status='ENTREGUE' if p['conferido']=='Sim' else 'NOVO'
                cur=c.execute("INSERT INTO pedido_cabecalhos(data,solicitante,pg,om,status,criado_em,atualizado_em,atualizado_por) VALUES(?,?,?,?,?,?,?,?)",(p['data'] or p['criado_em'] or _agora(),p['nome'] or p['solicitante'] or 'Não informado',p['pg'] or '',p['om'] or '',status,p['criado_em'] or p['data'] or _agora(),p['criado_em'] or p['data'] or _agora(),'migração'))
                c.execute("INSERT INTO pedido_itens(pedido_id,categoria,medicamento,quantidade,ficha,fichas,movimentos_json) VALUES(?,?,?,?,?,?,?)",(cur.lastrowid,p['categoria'],p['medicamento'],p['quantidade'],p['fichas'],p['fichas'],''))
        if not c.execute("SELECT 1 FROM usuarios WHERE perfil='gerente' LIMIT 1").fetchone():
            salt,digest=_hash_senha('Gerente@123')
            c.execute("INSERT INTO usuarios(usuario,nome,perfil,senha_salt,senha_hash,ativo,trocar_senha,criado_em) VALUES(?,?,?,?,?,1,1,?)",('gerente','Gerente','gerente',salt,digest,_agora()))
        c.commit(); c.close()
    def _garantir(self): self._criar()
    def _audit(self,acao,entidade,eid=None,detalhes="",usuario=None):
        usuario=usuario or getattr(_contexto,'usuario','sistema')
        c=_conn(); c.execute("INSERT INTO auditoria(data,usuario,acao,entidade,entidade_id,detalhes) VALUES(?,?,?,?,?,?)",(_agora(),usuario,acao,entidade,eid,detalhes)); c.commit(); c.close()
    def autenticar(self,usuario,senha):
        c=_conn();r=c.execute("SELECT * FROM usuarios WHERE lower(usuario)=lower(?) AND ativo=1",(usuario,)).fetchone()
        if not r: c.close(); return None
        _,digest=_hash_senha(senha,r['senha_salt'])
        if not hmac.compare_digest(digest,r['senha_hash']): c.close(); return None
        c.execute("UPDATE usuarios SET ultimo_acesso=? WHERE id=?",(_agora(),r['id']));c.commit();c.close()
        return {'id':r['id'],'usuario':r['usuario'],'nome':r['nome'],'perfil':r['perfil'],'trocar_senha':bool(r['trocar_senha'])}
    def listar_usuarios(self):
        c=_conn();rows=c.execute("SELECT id,usuario,nome,perfil,ativo,criado_em,ultimo_acesso FROM usuarios ORDER BY nome").fetchall();c.close();return [dict(r) for r in rows]
    def criar_usuario(self,usuario,nome,senha,perfil='administrador'):
        if perfil!='administrador': raise ValueError('Somente contas de Administrador podem ser criadas.')
        if len(usuario)<3 or len(senha)<6: raise ValueError('Usuário deve ter 3 caracteres e senha ao menos 6.')
        salt,digest=_hash_senha(senha);c=_conn()
        try:cur=c.execute("INSERT INTO usuarios(usuario,nome,perfil,senha_salt,senha_hash,ativo,trocar_senha,criado_em) VALUES(?,?,?,?,?,1,1,?)",(usuario,nome,perfil,salt,digest,_agora()));c.commit()
        except sqlite3.IntegrityError: c.close();raise ValueError('Este nome de usuário já existe.')
        c.close();self._audit('CRIAR_USUARIO','usuarios',cur.lastrowid,f'{usuario}|{perfil}');return cur.lastrowid
    def alterar_senha(self,uid,nova_senha):
        if len(nova_senha)<6: raise ValueError('A senha deve possuir ao menos 6 caracteres.')
        salt,digest=_hash_senha(nova_senha);c=_conn();cur=c.execute("UPDATE usuarios SET senha_salt=?,senha_hash=?,trocar_senha=0 WHERE id=?",(salt,digest,uid));c.commit();c.close();self._audit('ALTERAR_SENHA','usuarios',uid);return cur.rowcount>0
    def ativar_usuario(self,uid,ativo):
        c=_conn();cur=c.execute("UPDATE usuarios SET ativo=? WHERE id=?",(1 if ativo else 0,uid));c.commit();c.close();self._audit('ATIVAR_USUARIO' if ativo else 'DESATIVAR_USUARIO','usuarios',uid);return cur.rowcount>0
    def listar_auditoria(self,limite=500):
        c=_conn();rows=c.execute("SELECT * FROM auditoria ORDER BY id DESC LIMIT ?",(max(1,min(int(limite),2000)),)).fetchall();c.close();return [dict(r) for r in rows]
    def listar_lotes(self,categoria,medicamento=None):
        c=_conn(); q="SELECT * FROM lotes WHERE ativo=1 AND categoria=?"; p=[categoria]
        if medicamento is not None: q+=" AND medicamento=?"; p.append(medicamento)
        q+=" ORDER BY medicamento, validade"; rows=c.execute(q,p).fetchall(); c.close()
        return [{"id":r["id"],"categoria":r["categoria"],"medicamento":r["medicamento"],"ficha":r["ficha"],"comprimidos_cartela":r["comprimidos_cartela"],"validade":_data_brasileira(r["validade"]),"estoque_inicial":r["estoque_inicial"],"estoque_atual":r["estoque_atual"]} for r in rows]
    def listar_medicamentos(self,categoria):
        rows=self.listar_lotes(categoria); ag={}
        for l in rows:
            x=ag.setdefault(l["medicamento"],{"medicamento":l["medicamento"],"estoque_total":0,"validade_mais_proxima":None,"comprimidos_por_cartela":[]}); x["estoque_total"]+=l["estoque_atual"] or 0
            comp=l.get("comprimidos_cartela")
            if comp and comp not in x["comprimidos_por_cartela"]:x["comprimidos_por_cartela"].append(comp)
            if l["estoque_atual"]>0 and l["validade"]:
                try:
                    if not x["validade_mais_proxima"] or datetime.strptime(l["validade"],FORMATO_DATA)<datetime.strptime(x["validade_mais_proxima"],FORMATO_DATA): x["validade_mais_proxima"]=l["validade"]
                except ValueError: pass
        for x in ag.values():x["comprimidos_por_cartela"].sort()
        return sorted(ag.values(),key=lambda x:chave_ordenacao_texto(x["medicamento"]))
    def _row(self,cat,med,ficha,validade=None):
        c=_conn(); r=c.execute("SELECT * FROM lotes WHERE ativo=1 AND categoria=? AND medicamento=? AND ficha=? AND COALESCE(validade,'')=COALESCE(?, '') LIMIT 1",(cat,med,str(ficha),validade)).fetchone(); c.close(); return r
    def cadastrar_lote(self,cat,med,ficha,validade,est,comprimidos_cartela=None):
        validade=_data_brasileira(validade)
        c=_conn(); r=c.execute("SELECT * FROM lotes WHERE ativo=1 AND categoria=? AND medicamento=? AND ficha=? AND COALESCE(validade,'')=COALESCE(?, '') LIMIT 1",(cat,med,str(ficha),validade)).fetchone(); now=_agora()
        if r:
            ni=(r["estoque_inicial"] or 0)+est; na=(r["estoque_atual"] or 0)+est
            c.execute("UPDATE lotes SET estoque_inicial=?,estoque_atual=?,comprimidos_cartela=COALESCE(?,comprimidos_cartela),atualizado_em=? WHERE id=?",(ni,na,comprimidos_cartela,now,r["id"])); merged=True; lid=r["id"]
        else:
            cur=c.execute("INSERT INTO lotes(categoria,medicamento,ficha,comprimidos_cartela,validade,estoque_inicial,estoque_atual,criado_em,atualizado_em) VALUES(?,?,?,?,?,?,?,?,?)",(cat,med,str(ficha),comprimidos_cartela,validade,est,est,now,now)); ni=na=est; merged=False; lid=cur.lastrowid
        c.commit(); c.close(); self._audit("CADASTRO_LOTE", "lotes", lid, f"{cat}|{med}|{ficha}|{validade}|{est}|{comprimidos_cartela or '-'} comp/cartela")
        return {"mesclado":merged,"estoque_inicial":ni,"estoque_atual":na}
    def excluir_lote(self,cat,med,ficha,validade=None,motivo="Exclusão manual",lote_id=None):
        c=_conn()
        if lote_id is not None:
            r=c.execute("SELECT * FROM lotes WHERE ativo=1 AND id=?",(int(lote_id),)).fetchone()
        else:
            r=c.execute("SELECT * FROM lotes WHERE ativo=1 AND categoria=? AND medicamento=? AND ficha=? AND COALESCE(validade,'')=COALESCE(?, '') LIMIT 1",(cat,med,str(ficha),validade)).fetchone()
        if not r: c.close(); return False
        c.execute("INSERT INTO lotes_excluidos(lote_id_original,categoria,medicamento,ficha,apresentacao,validade,estoque_inicial,estoque_restante,motivo,excluido_em,excluido_por) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(r["id"],r["categoria"],r["medicamento"],r["ficha"],r["apresentacao"],r["validade"],r["estoque_inicial"],r["estoque_atual"],motivo,_agora(),"sistema")); c.execute("UPDATE lotes SET ativo=0,atualizado_em=? WHERE id=?",(_agora(),r["id"])); c.commit(); c.close(); self._audit("EXCLUSAO_LOTE","lotes",r["id"],motivo); return True
    def editar_lote(self,cat,med,ficha,validade,nmed,nf,nval,ni,na,ncomp=None,lote_id=None):
        validade=_data_brasileira(validade);nval=_data_brasileira(nval)
        c=_conn()
        if lote_id is not None:
            r=c.execute("SELECT id FROM lotes WHERE ativo=1 AND id=?",(int(lote_id),)).fetchone()
        else:
            r=c.execute("SELECT id FROM lotes WHERE ativo=1 AND categoria=? AND medicamento=? AND ficha=? AND COALESCE(validade,'')=COALESCE(?, '') LIMIT 1",(cat,med,str(ficha),validade)).fetchone()
        if not r: c.close(); return False
        c.execute("UPDATE lotes SET medicamento=?,ficha=?,comprimidos_cartela=?,validade=?,estoque_inicial=?,estoque_atual=?,atualizado_em=? WHERE id=?",(nmed,nf,ncomp,nval or None,ni,na,_agora(),r["id"])); c.commit(); c.close(); self._audit("EDICAO_LOTE","lotes",r["id"],f"{med}->{nmed}; {ficha}->{nf}; {ncomp or '-'} comp/cartela"); return True
    def listar_lotes_excluidos(self):
        c=_conn(); rows=c.execute("SELECT * FROM lotes_excluidos ORDER BY id DESC").fetchall(); c.close(); return [{"Data Exclusão":r["excluido_em"],"Categoria":r["categoria"],"Medicamento":r["medicamento"],"Ficha":r["ficha"],"Validade":r["validade"],"Estoque Inicial":r["estoque_inicial"],"Estoque Atual":r["estoque_restante"],"Motivo":r["motivo"]} for r in rows]
    def listar_apoio(self):
        c=_conn(); rows=c.execute("SELECT * FROM apoio WHERE ativo=1 ORDER BY material,lote").fetchall(); c.close(); return [{"Material":r["material"],"Lote":r["lote"],"Validade":r["validade"],"Estoque Inicial":r["estoque_inicial"],"Estoque Atual":r["estoque_atual"],"Observação":r["observacao"]} for r in rows]
    def cadastrar_apoio(self,material,lote,validade,est,obs=""):
        c=_conn(); c.execute("INSERT INTO apoio(material,lote,validade,estoque_inicial,estoque_atual,observacao,criado_em,atualizado_em) VALUES(?,?,?,?,?,?,?,?)",(material,lote,validade or None,est,est,obs,_agora(),_agora())); c.commit(); c.close()
    def excluir_apoio(self,material,lote):
        c=_conn(); cur=c.execute("UPDATE apoio SET ativo=0,atualizado_em=? WHERE ativo=1 AND material=? AND lote=?",(_agora(),material,lote)); c.commit(); ok=cur.rowcount>0; c.close(); return ok
    def alertas_apoio(self,dias=90):
        hoje=datetime.now().date(); out=[]
        for x in self.listar_apoio():
            if not x["Validade"]: continue
            try:d=(datetime.strptime(str(x["Validade"]),FORMATO_DATA).date()-hoje).days
            except ValueError:continue
            if d<=dias: out.append({"material":x["Material"],"lote":x["Lote"],"validade":x["Validade"],"estoque":x["Estoque Atual"],"dias_restantes":d,"vencido":d<0})
        return sorted(out,key=lambda x:x["dias_restantes"])
    def registrar_retirada(self,cat,med,sol,qty):
        c=_conn(); rows=c.execute("SELECT * FROM lotes WHERE ativo=1 AND categoria=? AND medicamento=? AND estoque_atual>0",(cat,med)).fetchall()
        def key(r):
            try:d=datetime.strptime(r["validade"],FORMATO_DATA) if r["validade"] else datetime.max
            except ValueError:d=datetime.max
            return (d,r["estoque_atual"])
        rows=sorted(rows,key=key)
        qty=float(qty)
        if qty<=0: c.close(); raise ValueError('A quantidade deve ser maior que zero.')
        disponivel=sum(float(r['estoque_atual'] or 0) for r in rows)
        if disponivel<qty: c.close(); raise ValueError(f"Estoque insuficiente para '{med}'. Disponível: {disponivel:g}; solicitado: {qty:g}.")
        rem=qty; mov=[]; now=_agora()
        for r in rows:
            if rem<=0: break
            ant=float(r["estoque_atual"]); usado=min(ant,rem); fin=ant-usado; rem-=usado
            c.execute("UPDATE lotes SET estoque_atual=?,saida_total=saida_total+?,atualizado_em=? WHERE id=?",(fin,usado,now,r["id"]))
            c.execute("INSERT INTO movimentacoes(data,lote_id,categoria,medicamento,ficha,solicitante,quantidade,estoque_anterior,estoque_final,tipo) VALUES(?,?,?,?,?,?,?,?,?,?)",(now,r["id"],cat,med,r["ficha"],sol,usado,ant,fin,"RETIRADA"))
            mov.append({"lote_id":r["id"],"categoria":cat,"medicamento":med,"ficha":r["ficha"],"data":now,"solicitante":sol,"retirada":usado,"estoque_anterior":ant,"estoque_final":fin})
        c.commit(); c.close(); self._audit('RETIRADA','lotes',detalhes=f'{cat}|{med}|{qty:g}|{sol}'); return mov
    def buscar_movimentacoes(self,categoria=None,data_inicio=None,data_fim=None,ficha=None,medicamento=None,solicitante=None):
        c=_conn(); q="SELECT * FROM movimentacoes WHERE 1=1"; p=[]
        if categoria and categoria!="Todas":q+=" AND categoria=?";p.append(categoria)
        if data_inicio:q+=" AND data>=?";p.append(data_inicio.strftime(FORMATO_DATA_HORA))
        if data_fim:q+=" AND data<=?";p.append(data_fim.strftime(FORMATO_DATA_HORA))
        if ficha:q+=" AND lower(ficha) LIKE ?";p.append('%'+ficha.lower()+'%')
        if medicamento:q+=" AND lower(medicamento) LIKE ?";p.append('%'+medicamento.lower()+'%')
        if solicitante:q+=" AND lower(solicitante) LIKE ?";p.append('%'+solicitante.lower()+'%')
        q+=" ORDER BY id DESC"; rows=c.execute(q,p).fetchall(); c.close(); return [{"categoria":r["categoria"],"data":r["data"],"medicamento":r["medicamento"],"ficha":r["ficha"],"solicitante":r["solicitante"],"retirada":r["quantidade"],"estoque_anterior":r["estoque_anterior"],"estoque_final":r["estoque_final"]} for r in rows]
    def listar_alertas_validade(self,dias=90):
        hoje=datetime.now().date(); out=[]; c=_conn(); rows=c.execute("SELECT * FROM lotes WHERE ativo=1 AND validade IS NOT NULL AND validade<>''").fetchall(); c.close()
        for r in rows:
            try:d=(datetime.strptime(r["validade"],FORMATO_DATA).date()-hoje).days
            except ValueError:continue
            if d<=dias:out.append({"id":r["id"],"categoria":r["categoria"],"medicamento":r["medicamento"],"ficha":r["ficha"],"validade":r["validade"],"estoque":r["estoque_atual"],"dias_restantes":d,"vencido":d<0})
        return sorted(out,key=lambda x:x["dias_restantes"])
    def registrar_pedido_para_lista(self,nome,pg,om,itens,itens_cancelados=None):
        c=_conn();agora=_agora()
        itens_cancelados=itens_cancelados or [];status_cab='NOVO' if itens else 'CANCELADO'
        cur=c.execute("INSERT INTO pedido_cabecalhos(data,solicitante,pg,om,status,criado_em,atualizado_em,atualizado_por,cancelado_em,cancelado_por) VALUES(?,?,?,?,?,?,?,?,?,?)",(agora,nome,pg,om,status_cab,agora,agora,'Cliente Farmácia',agora if not itens else None,'sistema - sem estoque' if not itens else None))
        pid=cur.lastrowid
        for item in itens:
            fichas='; '.join(str(f) for f in item.get('fichas',[]))
            c.execute("INSERT INTO pedido_itens(pedido_id,categoria,medicamento,quantidade,ficha,fichas,movimentos_json,status,motivo) VALUES(?,?,?,?,?,?,?,?,?)",(pid,item['categoria'],item['medicamento'],item['quantidade'],fichas,fichas,json.dumps(item.get('movimentos',[]),ensure_ascii=False),'ATENDIDO',''))
        for item in itens_cancelados:
            c.execute("INSERT INTO pedido_itens(pedido_id,categoria,medicamento,quantidade,ficha,fichas,movimentos_json,status,motivo) VALUES(?,?,?,?,?,?,?,?,?)",(pid,item['categoria'],item['medicamento'],item['quantidade'],'','','','CANCELADO_SEM_ESTOQUE',item.get('motivo','Estoque insuficiente')))
        c.commit();c.close();self._audit('CRIAR_PEDIDO','pedidos',pid,f'{nome}|{len(itens)} item(ns)',usuario='Cliente Farmácia');return pid
    def estornar_resultados_sem_pedido(self,resultados,motivo):
        """Restaura o estoque se a baixa ocorreu, mas a criação do pedido falhou."""
        c=_conn()
        try:
            for item in resultados:
                for m in item.get('movimentos',[]):
                    lote=c.execute("SELECT * FROM lotes WHERE id=?",(m.get('lote_id'),)).fetchone()
                    if not lote:continue
                    qtd=float(m.get('retirada') or 0);anterior=float(lote['estoque_atual'] or 0);final=anterior+qtd
                    c.execute("UPDATE lotes SET estoque_atual=?,saida_total=MAX(0,saida_total-?),atualizado_em=? WHERE id=?",(final,qtd,_agora(),lote['id']))
                    c.execute("INSERT INTO movimentacoes(data,lote_id,categoria,medicamento,ficha,solicitante,quantidade,estoque_anterior,estoque_final,tipo,observacao) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(_agora(),lote['id'],m.get('categoria'),m.get('medicamento'),m.get('ficha'),m.get('solicitante'),qtd,anterior,final,'ESTORNO',motivo))
            c.commit()
        finally:c.close()
        self._audit('ESTORNO_PEDIDO_FALHOU','pedidos',detalhes=motivo,usuario='sistema')
    def listar_pedidos(self,status=None):
        c=_conn();q="SELECT * FROM pedido_cabecalhos";p=[]
        if status:
            if isinstance(status,(list,tuple)):q+=' WHERE status IN ('+','.join('?' for _ in status)+')';p.extend(status)
            else:q+=' WHERE status=?';p.append(status)
        q+=' ORDER BY id DESC';rows=c.execute(q,p).fetchall();out=[]
        for r in rows:
            itens=c.execute("SELECT id,categoria,medicamento,quantidade,COALESCE(fichas,ficha,'') AS fichas,movimentos_json,COALESCE(status,'ATENDIDO') AS status,COALESCE(motivo,'') AS motivo FROM pedido_itens WHERE pedido_id=? ORDER BY id",(r['id'],)).fetchall()
            out.append({'id':r['id'],'data':r['data'],'nome':r['solicitante'],'solicitante':r['solicitante'],'pg':r['pg'] or '','om':r['om'] or '','status':r['status'],'quantidade_itens':len(itens),'itens_atendidos':sum(1 for i in itens if i['status']=='ATENDIDO'),'itens_cancelados':sum(1 for i in itens if i['status']!='ATENDIDO'),'atualizado_em':r['atualizado_em'],'atualizado_por':r['atualizado_por'] or '','itens':[{'id':i['id'],'categoria':i['categoria'],'medicamento':i['medicamento'],'quantidade':i['quantidade'],'fichas':i['fichas'],'status':i['status'],'motivo':i['motivo']} for i in itens]})
        c.close();return out
    def obter_pedido(self,pid):
        pedidos=self.listar_pedidos()
        return next((p for p in pedidos if p['id']==pid),None)
    def alterar_status_pedido(self,pid,novo_status,usuario):
        validos=('NOVO','EM_SEPARACAO','PRONTO','ENTREGUE','CANCELADO')
        if novo_status not in validos:raise ValueError('Situação de pedido inválida.')
        c=_conn();cab=c.execute("SELECT * FROM pedido_cabecalhos WHERE id=?",(pid,)).fetchone()
        if not cab:c.close();return False
        anterior=cab['status']
        if anterior=='CANCELADO':c.close();raise ValueError('Pedido cancelado não pode ser reaberto.')
        if anterior=='ENTREGUE' and novo_status!='ENTREGUE':c.close();raise ValueError('Pedido entregue não pode voltar para uma etapa anterior.')
        if novo_status=='CANCELADO':
            itens=c.execute("SELECT * FROM pedido_itens WHERE pedido_id=?",(pid,)).fetchall()
            for item in itens:
                if (item['status'] or 'ATENDIDO')!='ATENDIDO':continue
                movimentos=json.loads(item['movimentos_json'] or '[]')
                if not movimentos:
                    c.close();raise ValueError('Este pedido antigo não possui rastreio suficiente para cancelamento automático.')
                for m in movimentos:
                    lote=c.execute("SELECT * FROM lotes WHERE id=?",(m.get('lote_id'),)).fetchone()
                    if not lote:
                        lote=c.execute("SELECT * FROM lotes WHERE categoria=? AND medicamento=? AND ficha=? ORDER BY id DESC LIMIT 1",(m.get('categoria'),m.get('medicamento'),str(m.get('ficha')))).fetchone()
                    if not lote:c.close();raise ValueError(f"Não foi possível localizar o lote da ficha {m.get('ficha')} para estorno.")
                    qtd=float(m.get('retirada') or 0);ant=float(lote['estoque_atual'] or 0);final=ant+qtd
                    c.execute("UPDATE lotes SET estoque_atual=?,saida_total=MAX(0,saida_total-?),atualizado_em=? WHERE id=?",(final,qtd,_agora(),lote['id']))
                    c.execute("INSERT INTO movimentacoes(data,lote_id,categoria,medicamento,ficha,solicitante,quantidade,estoque_anterior,estoque_final,tipo,observacao) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(_agora(),lote['id'],item['categoria'],item['medicamento'],lote['ficha'],cab['solicitante'],qtd,ant,final,'ESTORNO',f'Cancelamento do pedido #{pid}'))
        agora=_agora();c.execute("UPDATE pedido_cabecalhos SET status=?,atualizado_em=?,atualizado_por=?,cancelado_em=?,cancelado_por=? WHERE id=?",(novo_status,agora,usuario,agora if novo_status=='CANCELADO' else cab['cancelado_em'],usuario if novo_status=='CANCELADO' else cab['cancelado_por'],pid));c.commit();c.close()
        self._audit('ALTERAR_STATUS_PEDIDO','pedidos',pid,f'{anterior}->{novo_status}',usuario=usuario);return True

def _parse_data(t,fim_do_dia=False):
    if not t:return None
    d=datetime.strptime(t,FORMATO_DATA); return datetime.combine(d.date(),_time(23,59,59)) if fim_do_dia else d

def _sessao_atual():
    auth=request.headers.get('Authorization','')
    token=auth[7:].strip() if auth.lower().startswith('bearer ') else ''
    sessao=_sessoes.get(token)
    if not sessao:return None
    if sessao['expira']<datetime.now():
        _sessoes.pop(token,None);return None
    sessao['expira']=datetime.now()+timedelta(hours=DURACAO_SESSAO_HORAS)
    _contexto.usuario=sessao['usuario']['usuario']
    return sessao['usuario']

def _exigir_login():
    usuario=_sessao_atual()
    if usuario:return usuario,None
    return None,(jsonify(erro='Sessão inválida ou expirada.'),401)

def _exigir_gerente():
    usuario,erro=_exigir_login()
    if erro:return None,erro
    if usuario['perfil']!='gerente':return None,(jsonify(erro='Acesso restrito ao Gerente.'),403)
    return usuario,None

app=Flask(__name__); db=EstoqueDB(CAMINHO_BANCO)
@app.route('/login',methods=['POST'])
def login():
    d=request.get_json(force=True) or {};usuario=db.autenticar(str(d.get('usuario') or '').strip(),str(d.get('senha') or ''))
    if not usuario:
        db._audit('LOGIN_FALHOU','usuarios',detalhes=str(d.get('usuario') or ''),usuario=str(d.get('usuario') or 'desconhecido'))
        return jsonify(erro='Usuário ou senha inválidos.'),401
    token=secrets.token_urlsafe(32);_sessoes[token]={'usuario':usuario,'expira':datetime.now()+timedelta(hours=DURACAO_SESSAO_HORAS)};db._audit('LOGIN','usuarios',usuario['id'],usuario=usuario['usuario'])
    return jsonify(token=token,usuario=usuario)
@app.route('/logout',methods=['POST'])
def logout():
    auth=request.headers.get('Authorization','');token=auth[7:].strip() if auth.lower().startswith('bearer ') else '';_sessoes.pop(token,None);return jsonify(ok=True)
@app.route('/minha-senha',methods=['POST'])
def minha_senha():
    usuario,erro=_exigir_login()
    if erro:return erro
    d=request.get_json(force=True) or {}
    try:db.alterar_senha(usuario['id'],str(d.get('nova_senha') or ''))
    except ValueError as e:return jsonify(erro=str(e)),400
    usuario['trocar_senha']=False;return jsonify(ok=True)
@app.route('/usuarios',methods=['GET','POST'])
def usuarios():
    usuario,erro=_exigir_gerente()
    if erro:return erro
    if request.method=='GET':return jsonify(usuarios=db.listar_usuarios())
    d=request.get_json(force=True) or {}
    try:uid=db.criar_usuario(str(d.get('usuario') or '').strip(),str(d.get('nome') or '').strip(),str(d.get('senha') or ''),'administrador')
    except ValueError as e:return jsonify(erro=str(e)),400
    return jsonify(ok=True,id=uid)
@app.route('/usuarios/<int:uid>/ativo',methods=['POST'])
def usuario_ativo(uid):
    usuario,erro=_exigir_gerente()
    if erro:return erro
    if uid==usuario['id']:return jsonify(erro='O Gerente não pode desativar a própria conta.'),400
    c=_conn();alvo=c.execute('SELECT perfil FROM usuarios WHERE id=?',(uid,)).fetchone();c.close()
    if not alvo or alvo['perfil']!='administrador':return jsonify(erro='O Gerente somente pode alterar contas de Administrador.'),400
    d=request.get_json(force=True) or {};return jsonify(ok=db.ativar_usuario(uid,bool(d.get('ativo'))))
@app.route('/auditoria')
def auditoria():
    usuario,erro=_exigir_gerente()
    if erro:return erro
    return jsonify(registros=db.listar_auditoria(request.args.get('limite',500,type=int)))
@app.route('/backup',methods=['POST'])
def backup():
    usuario,erro=_exigir_login()
    if erro:return erro
    with _lock:
        pasta=os.path.join(BASE_DIR,'backups');os.makedirs(pasta,exist_ok=True);dest=os.path.join(pasta,f'farmacia_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db');shutil.copy2(CAMINHO_BANCO,dest)
    return jsonify(ok=True,arquivo=dest)
@app.route('/ping')
def ping():return jsonify(status='ok',servidor='estoque-farmacia',versao=VERSAO_SISTEMA,banco='sqlite',offline=True)
@app.route('/categorias')
def categorias():return jsonify(categorias=CATEGORIAS)
@app.route('/medicamentos')
def medicamentos():
    cat=request.args.get('categoria');
    if not cat:return jsonify(erro="Parâmetro 'categoria' é obrigatório."),400
    with _lock:return jsonify(medicamentos=db.listar_medicamentos(cat))
@app.route('/lotes')
def lotes():
    cat=request.args.get('categoria');med=request.args.get('medicamento');
    if not cat:return jsonify(erro="Parâmetro 'categoria' é obrigatório."),400
    with _lock:return jsonify(lotes=db.listar_lotes(cat,med))
@app.route('/apoio',methods=['GET','POST','DELETE'])
def apoio():
    with _lock:
        if request.method=='GET':return jsonify(itens=db.listar_apoio())
        usuario,erro=_exigir_login()
        if erro:return erro
        d=request.get_json(force=True) or {}
        if request.method=='DELETE':return (jsonify(ok=True) if db.excluir_apoio(str(d.get('material') or '').strip(),str(d.get('lote') or '').strip()) else (jsonify(erro='Material não encontrado.'),404))
        try:est=float(d.get('estoque_inicial'))
        except: return jsonify(erro='Estoque inválido.'),400
        db.cadastrar_apoio(str(d.get('material') or '').strip(),str(d.get('lote') or '').strip(),str(d.get('validade') or '').strip(),est,str(d.get('observacao') or ''));return jsonify(ok=True)
@app.route('/apoio/alertas')
def apoio_alertas():
    with _lock:return jsonify(alertas=db.alertas_apoio(request.args.get('dias',90,type=int)))
@app.route('/lotes-excluidos')
def excluidos():
    with _lock:return jsonify(lotes=db.listar_lotes_excluidos())
@app.route('/itens',methods=['PUT'])
def editar():
    usuario,erro=_exigir_login()
    if erro:return erro
    d=request.get_json(force=True) or {}
    try:ni=float(d.get('novo_estoque_inicial'));na=float(d.get('novo_estoque_atual'))
    except:return jsonify(erro='Estoque inválido.'),400
    try:ncomp=int(d.get('novos_comprimidos_cartela')) if str(d.get('novos_comprimidos_cartela') or '').strip() else None
    except:return jsonify(erro='Número de comprimidos por cartela inválido.'),400
    if ncomp is not None and ncomp<=0:return jsonify(erro='Comprimidos por cartela deve ser maior que zero.'),400
    with _lock:ok=db.editar_lote(d.get('categoria'),d.get('medicamento'),str(d.get('ficha') or ''),d.get('validade') or None,d.get('novo_medicamento'),str(d.get('nova_ficha') or ''),d.get('nova_validade') or None,ni,na,ncomp,d.get('lote_id'))
    return jsonify(ok=True) if ok else (jsonify(erro='Lote não encontrado.'),404)
@app.route('/itens',methods=['POST'])
def cadastrar():
    usuario,erro=_exigir_login()
    if erro:return erro
    d=request.get_json(force=True) or {};cat=d.get('categoria');med=str(d.get('medicamento') or '').strip();f=str(d.get('ficha') or '').strip();val=str(d.get('validade') or '').strip()
    if cat not in CATEGORIAS or not med or not f:return jsonify(erro='Categoria, medicamento e ficha são obrigatórios.'),400
    try:est=float(d.get('estoque_inicial'))
    except:return jsonify(erro='Estoque inicial inválido.'),400
    try:comp=int(d.get('comprimidos_cartela')) if str(d.get('comprimidos_cartela') or '').strip() else None
    except:return jsonify(erro='Número de comprimidos por cartela inválido.'),400
    if comp is not None and comp<=0:return jsonify(erro='Comprimidos por cartela deve ser maior que zero.'),400
    with _lock:r=db.cadastrar_lote(cat,med,f,val or None,est,comp)
    return jsonify(ok=True,**r)
@app.route('/itens',methods=['DELETE'])
def excluir():
    usuario,erro=_exigir_login()
    if erro:return erro
    d=request.get_json(force=True) or {};cat=d.get('categoria');med=str(d.get('medicamento') or '').strip();f=str(d.get('ficha') or '').strip();val=str(d.get('validade') or '').strip() or None;mot=str(d.get('motivo') or 'Exclusão manual').strip()
    with _lock:ok=db.excluir_lote(cat,med,f,val,mot,d.get('lote_id'))
    return jsonify(ok=True) if ok else (jsonify(erro='Lote não encontrado.'),404)
@app.route('/retiradas',methods=['POST'])
def retiradas():
    d=request.get_json(force=True) or {};sol=str(d.get('solicitante') or d.get('nome') or '').strip();pg=str(d.get('pg') or '').strip();om=str(d.get('om') or '').strip();items=d.get('itens') or []
    if not sol or not items:return jsonify(erro='Nome e ao menos um item são obrigatórios.'),400
    results=[];cancelados=[];agora=_agora();c=None
    with _lock:
        try:
            c=_conn();c.execute('BEGIN IMMEDIATE')
            for item in items:
                cat=item.get('categoria');med=item.get('medicamento')
                try:q=float(item.get('quantidade_retirada'))
                except ValueError:raise ValueError(f"Quantidade inválida para '{med}'.")
                if q<=0:raise ValueError('A quantidade deve ser maior que zero.')
                lotes=c.execute("SELECT * FROM lotes WHERE ativo=1 AND categoria=? AND medicamento=? AND estoque_atual>0",(cat,med)).fetchall()
                def ordem_lote(lote):
                    try:validade=datetime.strptime(lote['validade'],FORMATO_DATA) if lote['validade'] else datetime.max
                    except ValueError:validade=datetime.max
                    return (validade,float(lote['estoque_atual'] or 0))
                lotes=sorted(lotes,key=ordem_lote);disponivel=sum(float(l['estoque_atual'] or 0) for l in lotes)
                if disponivel<q:
                    cancelados.append({'medicamento':med,'categoria':cat,'quantidade':q,'disponivel':disponivel,'motivo':f'Estoque insuficiente. Disponível: {disponivel:g}; solicitado: {q:g}.'});continue
                restante=q;movimentos=[]
                for lote in lotes:
                    if restante<=0:break
                    anterior=float(lote['estoque_atual']);retirada=min(anterior,restante);final=anterior-retirada;restante-=retirada
                    c.execute("UPDATE lotes SET estoque_atual=?,saida_total=saida_total+?,atualizado_em=? WHERE id=?",(final,retirada,agora,lote['id']))
                    cur_mov=c.execute("INSERT INTO movimentacoes(data,lote_id,categoria,medicamento,ficha,solicitante,quantidade,estoque_anterior,estoque_final,tipo) VALUES(?,?,?,?,?,?,?,?,?,?)",(agora,lote['id'],cat,med,lote['ficha'],sol,retirada,anterior,final,'RETIRADA'))
                    movimentos.append({'movimentacao_id':cur_mov.lastrowid,'lote_id':lote['id'],'categoria':cat,'medicamento':med,'ficha':lote['ficha'],'data':agora,'solicitante':sol,'retirada':retirada,'estoque_anterior':anterior,'estoque_final':final})
                results.append({'medicamento':med,'categoria':cat,'movimentos':movimentos})
            resumo=[]
            for x in results:
                total=sum(m['retirada'] for m in x['movimentos']);fichas=[m['ficha'] for m in x['movimentos']]
                resumo.append({'medicamento':x['medicamento'],'categoria':x['categoria'],'quantidade':total,'fichas':fichas,'movimentos':x['movimentos']})
            status_cab='NOVO' if resumo else 'CANCELADO'
            cur=c.execute("INSERT INTO pedido_cabecalhos(data,solicitante,pg,om,status,criado_em,atualizado_em,atualizado_por,cancelado_em,cancelado_por) VALUES(?,?,?,?,?,?,?,?,?,?)",(agora,sol,pg,om,status_cab,agora,agora,'Cliente Farmácia',agora if not resumo else None,'sistema - sem estoque' if not resumo else None))
            pedido_id=cur.lastrowid
            for item in resumo:
                fichas='; '.join(str(f) for f in item['fichas'])
                c.execute("INSERT INTO pedido_itens(pedido_id,categoria,medicamento,quantidade,ficha,fichas,movimentos_json,status,motivo) VALUES(?,?,?,?,?,?,?,?,?)",(pedido_id,item['categoria'],item['medicamento'],item['quantidade'],fichas,fichas,json.dumps(item['movimentos'],ensure_ascii=False),'ATENDIDO',''))
            for item in cancelados:
                c.execute("INSERT INTO pedido_itens(pedido_id,categoria,medicamento,quantidade,ficha,fichas,movimentos_json,status,motivo) VALUES(?,?,?,?,?,?,?,?,?)",(pedido_id,item['categoria'],item['medicamento'],item['quantidade'],'','','','CANCELADO_SEM_ESTOQUE',item['motivo']))
            c.commit();c.close();c=None
        except ValueError as exc:
            if c:c.rollback();c.close()
            return jsonify(erro=str(exc)),400
        except Exception as exc:
            if c:c.rollback();c.close()
            _log(f'ERRO TRANSACIONAL AO REGISTRAR PEDIDO: {type(exc).__name__}: {exc}')
            return jsonify(erro=f'Pedido não registrado; nenhuma baixa foi mantida. Erro do servidor: {exc}'),500
    tocar_bipe()
    try:db._audit('CRIAR_PEDIDO','pedidos',pedido_id,f'{sol}|{len(results)} item(ns)',usuario='Cliente Farmácia')
    except Exception as exc:_log(f'Aviso: auditoria do pedido #{pedido_id} falhou: {exc}')
    global _proximo_notificacao_id
    itens_aviso=resumo+[dict(x,status='CANCELADO_SEM_ESTOQUE') for x in cancelados];ev={'id':_proximo_notificacao_id,'pedido_id':pedido_id,'data':agora,'solicitante':sol,'itens':itens_aviso};_proximo_notificacao_id+=1;_notificacoes.append(ev)
    avisos=[]
    hoje=datetime.now().date()
    for x in results:
        for m in x['movimentos']:
            c=_conn();v=c.execute('SELECT validade FROM lotes WHERE id=(SELECT lote_id FROM movimentacoes WHERE categoria=? AND medicamento=? AND ficha=? ORDER BY id DESC LIMIT 1)',(m['categoria'],m['medicamento'],m['ficha'])).fetchone();c.close()
            try:
                if v and v[0] and datetime.strptime(v[0],FORMATO_DATA).date()<hoje:avisos.append(f"ATENÇÃO: {m['medicamento']} — ficha {m['ficha']} está vencido desde {v[0]}.")
            except ValueError:pass
    return jsonify(solicitante=sol,pg=pg,om=om,pedido_id=pedido_id,itens=results,itens_cancelados=cancelados,avisos=avisos)
@app.route('/notificacoes')
def notificacoes():
    desde=request.args.get('desde',type=int)
    with _lock:return jsonify(eventos=[] if desde is None else [e for e in _notificacoes if e['id']>desde],ultimo_id=_notificacoes[-1]['id'] if _notificacoes else 0)
@app.route('/historico')
def historico():
    try:a=_parse_data(request.args.get('data_inicio'));b=_parse_data(request.args.get('data_fim'),True)
    except:return jsonify(erro='Data inválida. Use o formato dd/mm/aaaa.'),400
    with _lock:r=db.buscar_movimentacoes(request.args.get('categoria'),a,b,request.args.get('ficha') or None,request.args.get('medicamento') or None,request.args.get('solicitante') or None)
    return jsonify(registros=r)
@app.route('/alertas')
def alertas():
    with _lock:return jsonify(alertas=db.listar_alertas_validade(request.args.get('dias',90,type=int)))
@app.route('/pedidos')
def pedidos():
    status=(request.args.get('status') or '').strip().upper()
    if status=='PENDENTES':status=['NOVO','EM_SEPARACAO','PRONTO']
    elif status=='TODOS' or not status:status=None
    with _lock:return jsonify(pedidos=db.listar_pedidos(status))
@app.route('/pedidos/<int:pid>')
def pedido_detalhe(pid):
    usuario,erro=_exigir_login()
    if erro:return erro
    with _lock:p=db.obter_pedido(pid)
    return jsonify(pedido=p) if p else (jsonify(erro='Pedido não encontrado.'),404)
@app.route('/pedidos/<int:pid>/status',methods=['POST'])
def pedido_status(pid):
    usuario,erro=_exigir_login()
    if erro:return erro
    d=request.get_json(force=True) or {};novo=str(d.get('status') or '').strip().upper()
    try:
        with _lock:found=db.alterar_status_pedido(pid,novo,usuario['usuario'])
    except ValueError as e:return jsonify(erro=str(e)),400
    return jsonify(ok=True) if found else (jsonify(erro='Pedido não encontrado.'),404)
@app.route('/pedidos/<int:pid>/conferir',methods=['POST'])
def conferir(pid):
    usuario,erro=_exigir_login()
    if erro:return erro
    d=request.get_json(force=True) or {};ok=bool(d.get('conferido',True));
    try:
        with _lock:found=db.alterar_status_pedido(pid,'ENTREGUE' if ok else 'NOVO',usuario['usuario'])
    except ValueError as e:return jsonify(erro=str(e)),400
    return jsonify(ok=True) if found else (jsonify(erro='Pedido não encontrado.'),404)

def obter_ip_local():
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect(('10.255.255.255',1));ip=s.getsockname()[0];s.close();return ip
    except:return '127.0.0.1'
def obter_linhas_banner_inicial():
    return ['='*64,' SERVIDOR DE ESTOQUE DE FARMÁCIA — SQLITE','='*64,f' Banco: {CAMINHO_BANCO}',' Endereço para os computadores clientes usarem:',f'     http://{obter_ip_local()}:{PORTA}',' Modo: OFFLINE / REDE LOCAL',' Backups: pasta backups/ no diretório do sistema','= '*32]
def iniciar_servidor(host='0.0.0.0',port=None,log_callback=None):
    global LOG_CALLBACK;LOG_CALLBACK=log_callback;_log(f'Servidor SQLite iniciando na porta {port or PORTA}');app.run(host=host,port=port or PORTA,debug=False,use_reloader=False,threaded=True)
from recursos_estoque_130 import instalar as _instalar_recursos_130
_instalar_recursos_130(app,db,_conn,_lock,_agora,_exigir_login,FORMATO_DATA)
if __name__=='__main__':iniciar_servidor()
