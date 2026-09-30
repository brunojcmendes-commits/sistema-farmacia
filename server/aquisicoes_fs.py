"""Aquisições FS, cadastro de empresas e itens solicitados/autorizados do PAASSEx."""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from flask import jsonify, request


TIPOS = {
    "consumo": "3.3.90.30",
    "consumo_duradouro": "",  # Classificação depende do objeto concreto.
    "servico_pj": "3.3.90.39",
    "servico_pf": "3.3.90.36",
    "permanente": "4.4.90.52",
}
CAMPOS = (
    "material", "tipo", "requisicao_numero", "requisicao_data",
    "empenho_numero", "empenho_data", "empresa_id", "previsao_entrega",
    "rastreio", "entrega_data", "liquidacao_numero", "liquidacao_data",
    "observacao",
)
DATAS = ("requisicao_data", "empenho_data", "previsao_entrega",
         "entrega_data", "liquidacao_data")


def _texto(valor, limite=500):
    return str(valor or "").strip()[:limite]


def _data(valor):
    value = _texto(valor, 10)
    if value:
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValueError("Informe datas válidas no formato AAAA-MM-DD.")
    return value


def _valor(value, label='Valor', optional=False):
    raw = _texto(value, 40).replace(',', '.')
    if optional and not raw: return ''
    try:
        n = Decimal(raw)
        if not n.is_finite() or n < 0 or n.as_tuple().exponent < -2: raise ValueError()
        return str(n.quantize(Decimal('0.01')))
    except (InvalidOperation, ValueError):
        raise ValueError(label + ' deve ser positivo ou zero, com até duas casas decimais.')


def _ncs(c):
    rows = [dict(r) for r in c.execute('SELECT * FROM notas_credito_fs ORDER BY data DESC,id DESC')]
    spent = {}
    for r in c.execute('SELECT nc_id,preco_total FROM aquisicoes_fs_itens WHERE nc_id IS NOT NULL'):
        if r['preco_total']:
            spent[r['nc_id']] = spent.get(r['nc_id'],Decimal('0')) + Decimal(r['preco_total'])
    for row in rows:
        used = spent.get(row['id'],Decimal('0'))
        row['utilizado'] = str(used.quantize(Decimal('0.01')))
        row['saldo'] = str((Decimal(row['valor'])-used).quantize(Decimal('0.01')))
    return rows


def _status(row):
    result = dict(row)
    empenho = result.get("empenho_data")
    entrega = result.get("entrega_data")
    prazo = (date.fromisoformat(empenho) + timedelta(days=30)) if empenho else None
    result["prazo_30_dias"] = prazo.isoformat() if prazo else ""
    result["dias_restantes"] = (prazo - date.today()).days if prazo and not entrega else None
    if result.get("liquidacao_data"):
        result["etapa"] = "LIQUIDADO"
    elif entrega:
        result["etapa"] = "ENTREGUE"
    elif empenho:
        result["etapa"] = "AGUARDANDO_ENTREGA"
    elif result.get("requisicao_numero") or result.get("requisicao_data"):
        result["etapa"] = "REQUISITADO"
    else:
        result["etapa"] = "CADASTRO_INICIAL"
    result["alerta"] = ("ATRASADO" if result["dias_restantes"] is not None and result["dias_restantes"] < 0
                        else "PROXIMO" if result["dias_restantes"] is not None and result["dias_restantes"] <= 7
                        else "EM_PRAZO" if result["dias_restantes"] is not None else "")
    return result


def instalar(app, conn_factory, lock, agora, exigir_login, audit):
    con = conn_factory()
    try:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS empresas_fs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL,
          cnpj TEXT NOT NULL DEFAULT '', telefone TEXT NOT NULL DEFAULT '',
          email TEXT NOT NULL DEFAULT '', criado_em TEXT NOT NULL,
          atualizado_em TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS aquisicoes_fs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, material TEXT NOT NULL,
          tipo TEXT NOT NULL DEFAULT '', requisicao_numero TEXT NOT NULL DEFAULT '',
          requisicao_data TEXT NOT NULL DEFAULT '', empenho_numero TEXT NOT NULL DEFAULT '',
          empenho_data TEXT NOT NULL DEFAULT '', empresa_id INTEGER,
          previsao_entrega TEXT NOT NULL DEFAULT '', rastreio TEXT NOT NULL DEFAULT '',
          entrega_data TEXT NOT NULL DEFAULT '', liquidacao_numero TEXT NOT NULL DEFAULT '',
          liquidacao_data TEXT NOT NULL DEFAULT '', observacao TEXT NOT NULL DEFAULT '',
          criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL,
          FOREIGN KEY(empresa_id) REFERENCES empresas_fs(id) ON DELETE RESTRICT);
        CREATE TABLE IF NOT EXISTS paassex_itens (
          id INTEGER PRIMARY KEY AUTOINCREMENT, ano INTEGER NOT NULL,
          nome TEXT NOT NULL, descricao TEXT NOT NULL,
          autorizado INTEGER NOT NULL DEFAULT 0,
          criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL,
          autorizado_em TEXT NOT NULL DEFAULT '', autorizado_por TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS notas_credito_fs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL, tipo TEXT NOT NULL,
          ug TEXT NOT NULL, numero TEXT NOT NULL, valor TEXT NOT NULL,
          criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS aquisicoes_fs_itens (
          id INTEGER PRIMARY KEY AUTOINCREMENT, aquisicao_id INTEGER NOT NULL,
          posicao INTEGER NOT NULL, item TEXT NOT NULL DEFAULT '',
          codigo_catmat_catserv TEXT NOT NULL DEFAULT '', descricao TEXT NOT NULL DEFAULT '',
          unidade TEXT NOT NULL DEFAULT '', quantidade TEXT NOT NULL DEFAULT '',
          nd_si TEXT NOT NULL DEFAULT '', preco_unitario TEXT NOT NULL DEFAULT '',
          preco_total TEXT NOT NULL DEFAULT '', nc_id INTEGER,
          FOREIGN KEY(nc_id) REFERENCES notas_credito_fs(id) ON DELETE RESTRICT,
          FOREIGN KEY(aquisicao_id) REFERENCES aquisicoes_fs(id) ON DELETE CASCADE);
        CREATE INDEX IF NOT EXISTS idx_aquisicoes_itens ON aquisicoes_fs_itens(aquisicao_id,posicao);
        CREATE INDEX IF NOT EXISTS idx_aquisicoes_empenho ON aquisicoes_fs(empenho_data);
        CREATE INDEX IF NOT EXISTS idx_paassex_ano ON paassex_itens(ano);
        """)
        item_columns = {x[1] for x in con.execute('PRAGMA table_info(aquisicoes_fs_itens)')}
        if 'nc_id' not in item_columns:
            con.execute('ALTER TABLE aquisicoes_fs_itens ADD COLUMN nc_id INTEGER')
        pa_columns = {x[1] for x in con.execute('PRAGMA table_info(paassex_itens)')}
        if 'valor' not in pa_columns:
            con.execute("ALTER TABLE paassex_itens ADD COLUMN valor TEXT NOT NULL DEFAULT ''")
        if 'pregao' not in pa_columns:
            con.execute("ALTER TABLE paassex_itens ADD COLUMN pregao TEXT NOT NULL DEFAULT ''")
        con.commit()
    finally:
        con.close()

    def autorizado():
        usuario, erro = exigir_login()
        if erro:
            return None, erro
        if usuario.get("perfil") not in ("gerente", "administrador") or usuario.get("trocar_senha"):
            return None, (jsonify(erro="Acesso de gestão com senha pessoal necessário."), 403)
        return usuario, None

    def body():
        data = request.get_json(force=True)
        if not isinstance(data, dict):
            raise ValueError("Dados inválidos.")
        return data

    @app.route("/empresas-fs", methods=["GET", "POST"])
    def empresas_fs():
        usuario, erro = autorizado()
        if erro:
            return erro
        if request.method == "GET":
            c = conn_factory()
            try:
                return jsonify(empresas=[dict(r) for r in c.execute("SELECT * FROM empresas_fs ORDER BY nome")])
            finally:
                c.close()
        try:
            d = body()
            nome = _texto(d.get("nome"), 240)
            if not nome:
                raise ValueError("Informe o nome da empresa.")
            values = (nome, _texto(d.get("cnpj"), 24), _texto(d.get("telefone"), 40),
                      _texto(d.get("email"), 240), agora(), agora())
            with lock:
                c = conn_factory()
                try:
                    cur = c.execute("INSERT INTO empresas_fs(nome,cnpj,telefone,email,criado_em,atualizado_em) VALUES(?,?,?,?,?,?)", values)
                    c.commit()
                    ident = cur.lastrowid
                finally:
                    c.close()
            audit("CADASTRAR_EMPRESA_FS", "empresas_fs", ident, nome, usuario=usuario["usuario"])
            return jsonify(ok=True, id=ident)
        except ValueError as exc:
            return jsonify(erro=str(exc)), 400

    @app.route("/empresas-fs/<int:ident>", methods=["PUT"])
    def editar_empresa_fs(ident):
        usuario, erro = autorizado()
        if erro:
            return erro
        try:
            d = body()
            nome = _texto(d.get("nome"), 240)
            if not nome:
                raise ValueError("Informe o nome da empresa.")
            with lock:
                c = conn_factory()
                try:
                    cur = c.execute("UPDATE empresas_fs SET nome=?,cnpj=?,telefone=?,email=?,atualizado_em=? WHERE id=?",
                                    (nome, _texto(d.get("cnpj"), 24), _texto(d.get("telefone"), 40),
                                     _texto(d.get("email"), 240), agora(), ident))
                    c.commit()
                    found = cur.rowcount
                finally:
                    c.close()
            if not found:
                return jsonify(erro="Empresa não encontrada."), 404
            audit("EDITAR_EMPRESA_FS", "empresas_fs", ident, nome, usuario=usuario["usuario"])
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(erro=str(exc)), 400

    @app.route('/ncs-fs', methods=['GET','POST'])
    def notas_credito_fs():
        usuario, erro = autorizado()
        if erro: return erro
        if request.method == 'GET':
            c = conn_factory()
            try: return jsonify(ncs=_ncs(c))
            finally: c.close()
        return salvar_nc(None, usuario)

    def salvar_nc(ident, usuario):
        try:
            d = body()
            data, tipo = _data(d.get('data')), _texto(d.get('tipo'), 30)
            ug, numero = _texto(d.get('ug'), 120), _texto(d.get('numero'), 120)
            valor = _valor(d.get('valor'))
            if not data or tipo not in ('consumo','servico','permanente') or not ug or not numero:
                raise ValueError('Informe data, tipo, UG e número da NC.')
            with lock:
                c = conn_factory()
                try:
                    if ident is None:
                        cur = c.execute("""INSERT INTO notas_credito_fs
                            (data,tipo,ug,numero,valor,criado_em,atualizado_em)
                            VALUES(?,?,?,?,?,?,?)""", (data,tipo,ug,numero,valor,agora(),agora()))
                        ident = cur.lastrowid
                    else:
                        cur = c.execute("""UPDATE notas_credito_fs SET
                            data=?,tipo=?,ug=?,numero=?,valor=?,atualizado_em=? WHERE id=?""",
                            (data,tipo,ug,numero,valor,agora(),ident))
                        if not cur.rowcount: return jsonify(erro='NC não encontrada.'),404
                    c.commit()
                finally: c.close()
            audit('CADASTRAR_NC_FS' if request.method=='POST' else 'EDITAR_NC_FS',
                  'notas_credito_fs',ident,numero,usuario=usuario['usuario'])
            return jsonify(ok=True,id=ident)
        except (ValueError,TypeError) as exc:
            return jsonify(erro=str(exc)),400

    @app.route('/ncs-fs/<int:ident>',methods=['PUT'])
    def editar_nc_fs(ident):
        usuario, erro = autorizado()
        if erro: return erro
        return salvar_nc(ident,usuario)

    @app.route("/aquisicoes-fs", methods=["GET", "POST"])
    def aquisicoes_fs():
        usuario, erro = autorizado()
        if erro:
            return erro
        if request.method == "GET":
            c = conn_factory()
            try:
                rows = c.execute("""SELECT a.*,e.nome AS empresa_nome FROM aquisicoes_fs a
                    LEFT JOIN empresas_fs e ON e.id=a.empresa_id ORDER BY a.id DESC""")
                result = [_status(r) for r in rows]
                for acquisition in result:
                    acquisition['itens'] = [dict(x) for x in c.execute(
                        'SELECT * FROM aquisicoes_fs_itens WHERE aquisicao_id=? ORDER BY posicao,id', (acquisition['id'],))]
                    if not acquisition['itens'] and acquisition['material']:
                        acquisition['itens'] = [{'item':'1','codigo_catmat_catserv':'',
                            'descricao':acquisition['material'],'unidade':'','quantidade':'',
                            'nd_si':'','preco_unitario':'','preco_total':'','nc_id':None}]
                return jsonify(aquisicoes=result)
            finally:
                c.close()
        return salvar_aquisicao(None, usuario)

    def salvar_aquisicao(ident, usuario):
        try:
            d = body()
            data = {k: _texto(d.get(k), 1000 if k == "observacao" else 240) for k in CAMPOS}
            raw_items = d.get('itens')
            if raw_items is not None and (not isinstance(raw_items, list) or len(raw_items) > 200):
                raise ValueError('Lista de itens inválida ou acima de 200 itens.')
            items = []
            for index, raw in enumerate(raw_items or []):
                if not isinstance(raw, dict):
                    raise ValueError('Item inválido.')
                item = {key:_texto(raw.get(key), 1000 if key=='descricao' else 120)
                        for key in ('item','codigo_catmat_catserv','descricao','unidade','quantidade','nd_si','preco_unitario')}
                if not item['descricao']:
                    raise ValueError('Informe a descrição de cada item.')
                item['item'] = item['item'] or str(index+1)
                nc = raw.get('nc_id')
                try:
                    item['nc_id'] = int(nc) if nc else None
                    if item['nc_id'] is not None and item['nc_id'] <= 0: raise ValueError()
                except (ValueError,TypeError): raise ValueError('Selecione uma NC válida.')
                item['preco_total'] = ''
                if item['quantidade'] or item['preco_unitario']:
                    try:
                        qty = Decimal(item['quantidade'].replace(',','.')) if item['quantidade'] else None
                        price = Decimal(item['preco_unitario'].replace(',','.')) if item['preco_unitario'] else None
                        if qty is not None and (not qty.is_finite() or qty < 0): raise ValueError()
                        if price is not None and (not price.is_finite() or price < 0): raise ValueError()
                        if qty is not None and price is not None:
                            item['preco_total'] = str((qty * price).quantize(Decimal('0.01')))
                    except (InvalidOperation, ValueError):
                        raise ValueError('Quantidade e preço unitário devem ser números não negativos.')
                items.append(item)
            if items:
                data['material'] = data['material'] or items[0]['descricao'][:240]
            if not data["material"]:
                raise ValueError("Informe o material ou serviço.")
            if data["tipo"] and data["tipo"] not in TIPOS:
                raise ValueError("Tipo de material inválido.")
            for key in DATAS:
                data[key] = _data(data[key])
            empresa = data["empresa_id"]
            data["empresa_id"] = int(empresa) if empresa else None
            with lock:
                c = conn_factory()
                try:
                    if data["empresa_id"] and not c.execute("SELECT 1 FROM empresas_fs WHERE id=?", (data["empresa_id"],)).fetchone():
                        raise ValueError("Empresa não cadastrada.")
                    for item in items:
                        if item['nc_id'] is not None and not c.execute(
                                'SELECT 1 FROM notas_credito_fs WHERE id=?',(item['nc_id'],)).fetchone():
                            raise ValueError('NC não cadastrada.')
                    values = tuple(data[k] for k in CAMPOS)
                    if ident is None:
                        columns = ",".join(CAMPOS) + ",criado_em,atualizado_em"
                        cur = c.execute(f"INSERT INTO aquisicoes_fs({columns}) VALUES({','.join(['?'] * (len(CAMPOS) + 2))})",
                                        values + (agora(), agora()))
                        ident = cur.lastrowid
                    else:
                        cur = c.execute("UPDATE aquisicoes_fs SET " + ",".join(k + "=?" for k in CAMPOS) +
                                        ",atualizado_em=? WHERE id=?", values + (agora(), ident))
                        if not cur.rowcount:
                            return jsonify(erro="Aquisição não encontrada."), 404
                    if raw_items is not None:
                        c.execute('DELETE FROM aquisicoes_fs_itens WHERE aquisicao_id=?', (ident,))
                        for position, item in enumerate(items):
                            c.execute('''INSERT INTO aquisicoes_fs_itens
                                (aquisicao_id,posicao,item,codigo_catmat_catserv,descricao,unidade,quantidade,nd_si,preco_unitario,preco_total,nc_id)
                                VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (ident,position,*[item[k] for k in
                                    ('item','codigo_catmat_catserv','descricao','unidade','quantidade','nd_si','preco_unitario','preco_total','nc_id')]))
                    c.commit()
                finally:
                    c.close()
            audit("CADASTRAR_AQUISICAO_FS" if request.method == "POST" else "EDITAR_AQUISICAO_FS",
                  "aquisicoes_fs", ident, data["material"], usuario=usuario["usuario"])
            return jsonify(ok=True, id=ident)
        except (ValueError, TypeError) as exc:
            return jsonify(erro=str(exc)), 400

    @app.route("/aquisicoes-fs/<int:ident>", methods=["PUT"])
    def editar_aquisicao_fs(ident):
        usuario, erro = autorizado()
        if erro:
            return erro
        return salvar_aquisicao(ident, usuario)

    @app.route('/paassex',methods=['GET','POST'])
    def paassex():
        usuario, erro = autorizado()
        if erro: return erro
        if request.method == 'GET':
            c = conn_factory()
            try: return jsonify(itens=[dict(r) for r in c.execute(
                'SELECT * FROM paassex_itens ORDER BY ano DESC,id DESC')])
            finally: c.close()
        return salvar_paassex(None,usuario)

    def salvar_paassex(ident, usuario):
        try:
            d = body()
            ano = int(d.get('ano'))
            nome, descricao = _texto(d.get('nome'),240),_texto(d.get('descricao'),2000)
            valor, pregao = _valor(d.get('valor'),'Valor do item',optional=True),_texto(d.get('pregao'),120)
            if not 2000 <= ano <= 2100 or not nome or not descricao:
                raise ValueError('Informe ano, nome e descrição do item.')
            with lock:
                c = conn_factory()
                try:
                    if ident is None:
                        cur = c.execute("""INSERT INTO paassex_itens
                            (ano,nome,descricao,valor,pregao,criado_em,atualizado_em)
                            VALUES(?,?,?,?,?,?,?)""",(ano,nome,descricao,valor,pregao,agora(),agora()))
                        ident = cur.lastrowid
                    else:
                        cur = c.execute("""UPDATE paassex_itens SET
                            ano=?,nome=?,descricao=?,valor=?,pregao=?,atualizado_em=? WHERE id=?""",
                            (ano,nome,descricao,valor,pregao,agora(),ident))
                        if not cur.rowcount: return jsonify(erro='Item PAASSEx não encontrado.'),404
                    c.commit()
                finally: c.close()
            audit('SOLICITAR_ITEM_PAASSEX' if request.method=='POST' else 'EDITAR_ITEM_PAASSEX',
                  'paassex_itens',ident,nome,usuario=usuario['usuario'])
            return jsonify(ok=True,id=ident)
        except (ValueError,TypeError) as exc:
            return jsonify(erro=str(exc)),400

    @app.route('/paassex/<int:ident>',methods=['PUT'])
    def editar_paassex(ident):
        usuario, erro = autorizado()
        if erro: return erro
        return salvar_paassex(ident,usuario)

    @app.route("/paassex/autorizacoes", methods=["POST"])
    def autorizar_paassex():
        usuario, erro = autorizado()
        if erro:
            return erro
        try:
            d = body()
            ids = d.get("ids")
            if not isinstance(ids, list) or not ids or len(ids) > 500:
                raise ValueError("Selecione os itens solicitados.")
            ids = list(dict.fromkeys(int(i) for i in ids))
            if any(i <= 0 for i in ids):
                raise ValueError("Identificador inválido.")
            aprovado = bool(d.get("autorizado", True))
            with lock:
                c = conn_factory()
                try:
                    placeholders = ",".join("?" for _ in ids)
                    existentes = c.execute(f"SELECT id FROM paassex_itens WHERE id IN ({placeholders})", ids).fetchall()
                    if len(existentes) != len(ids):
                        raise ValueError("Um dos itens não foi encontrado.")
                    c.execute(f"UPDATE paassex_itens SET autorizado=?,autorizado_em=?,autorizado_por=?,atualizado_em=? WHERE id IN ({placeholders})",
                              (1 if aprovado else 0, agora() if aprovado else "",
                               usuario["usuario"] if aprovado else "", agora(), *ids))
                    c.commit()
                finally:
                    c.close()
            for ident in ids:
                audit("AUTORIZAR_ITEM_PAASSEX" if aprovado else "REVOGAR_ITEM_PAASSEX",
                      "paassex_itens", ident, usuario=usuario["usuario"])
            return jsonify(ok=True, quantidade=len(ids))
        except (ValueError, TypeError) as exc:
            return jsonify(erro=str(exc)), 400
