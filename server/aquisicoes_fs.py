"""Aquisições FS, cadastro de empresas e itens solicitados/autorizados do PAASSEx."""
from datetime import date, timedelta
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
        CREATE INDEX IF NOT EXISTS idx_aquisicoes_empenho ON aquisicoes_fs(empenho_data);
        CREATE INDEX IF NOT EXISTS idx_paassex_ano ON paassex_itens(ano);
        """)
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
                return jsonify(aquisicoes=[_status(r) for r in rows])
            finally:
                c.close()
        return salvar_aquisicao(None, usuario)

    def salvar_aquisicao(ident, usuario):
        try:
            d = body()
            data = {k: _texto(d.get(k), 1000 if k == "observacao" else 240) for k in CAMPOS}
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

    @app.route("/paassex", methods=["GET", "POST"])
    def paassex():
        usuario, erro = autorizado()
        if erro:
            return erro
        if request.method == "GET":
            c = conn_factory()
            try:
                return jsonify(itens=[dict(r) for r in c.execute("SELECT * FROM paassex_itens ORDER BY ano DESC,id DESC")])
            finally:
                c.close()
        try:
            d = body()
            ano = int(d.get("ano"))
            nome, descricao = _texto(d.get("nome"), 240), _texto(d.get("descricao"), 2000)
            if not 2000 <= ano <= 2100 or not nome or not descricao:
                raise ValueError("Informe ano, nome e descrição do item.")
            with lock:
                c = conn_factory()
                try:
                    cur = c.execute("INSERT INTO paassex_itens(ano,nome,descricao,criado_em,atualizado_em) VALUES(?,?,?,?,?)",
                                    (ano, nome, descricao, agora(), agora()))
                    c.commit()
                    ident = cur.lastrowid
                finally:
                    c.close()
            audit("SOLICITAR_ITEM_PAASSEX", "paassex_itens", ident, nome, usuario=usuario["usuario"])
            return jsonify(ok=True, id=ident)
        except (ValueError, TypeError) as exc:
            return jsonify(erro=str(exc)), 400

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
