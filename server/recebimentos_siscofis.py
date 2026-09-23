"""Estoque segregado: somente uma liberação transacional cria saldo utilizável."""
import hashlib
import json
import math
from datetime import datetime
from flask import request, jsonify


class Conflito(ValueError):
    pass


def numero(value, label, positive=False):
    if isinstance(value, bool):
        raise ValueError(label + ' inválida.')
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(label + ' inválida.')
    if not math.isfinite(result) or result > 1e12 or result < 0 or (positive and result <= 0):
        raise ValueError(label + ' deve ser ' + ('maior que zero.' if positive else 'zero ou maior.'))
    return result


def instalar(app, conn_factory, lock, agora, exigir_login, categorias):
    c = conn_factory()
    try:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS recebimentos_siscofis (
          id INTEGER PRIMARY KEY AUTOINCREMENT, categoria TEXT NOT NULL,
          medicamento TEXT NOT NULL, ficha TEXT NOT NULL, validade TEXT,
          comprimidos_cartela INTEGER, quantidade_recebida REAL NOT NULL,
          saldo_pendente REAL NOT NULL CHECK(saldo_pendente>=0),
          quantidade_liberada REAL NOT NULL DEFAULT 0,
          observacao TEXT NOT NULL DEFAULT '', estado TEXT NOT NULL DEFAULT 'PENDENTE',
          versao INTEGER NOT NULL DEFAULT 1, criado_em TEXT NOT NULL,
          criado_por TEXT NOT NULL, atualizado_em TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS operacoes_siscofis (
          chave TEXT PRIMARY KEY, assinatura TEXT NOT NULL, resposta TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS liberacoes_siscofis (
          id INTEGER PRIMARY KEY AUTOINCREMENT, recebimento_id INTEGER NOT NULL,
          lote_id INTEGER NOT NULL, quantidade REAL NOT NULL, data TEXT NOT NULL,
          usuario TEXT NOT NULL, referencia TEXT NOT NULL DEFAULT '',
          categoria TEXT, medicamento TEXT, ficha TEXT, validade TEXT,
          FOREIGN KEY(recebimento_id) REFERENCES recebimentos_siscofis(id));
        ''')
        c.commit()
    finally:
        c.close()

    def autorizado():
        user, err = exigir_login()
        if err:
            return None, err
        if user.get('perfil') not in ('gerente', 'administrador') or user.get('trocar_senha'):
            return None, (jsonify(erro='Acesso de gestão com senha pessoal necessário.'), 403)
        return user, None

    def dados():
        d = request.get_json(force=True)
        if not isinstance(d, dict):
            raise ValueError('Solicitação inválida.')
        return d

    def produto(d):
        cat, med, ficha = (str(d.get(k) or '').strip() for k in ('categoria', 'medicamento', 'ficha'))
        if cat not in categorias or not med or not ficha:
            raise ValueError('Preencha categoria, produto e ficha/lote.')
        val = str(d.get('validade') or '').strip()
        if val:
            try:
                val = datetime.strptime(val, '%d/%m/%Y').strftime('%d/%m/%Y')
            except ValueError:
                raise ValueError('Validade inválida. Use dia/mês/ano.')
        cartela = d.get('comprimidos_cartela')
        if cartela not in (None, ''):
            n = numero(cartela, 'Quantidade por cartela', True)
            if n != int(n):
                raise ValueError('Comprimidos por cartela deve ser inteiro.')
            cartela = int(n)
        else:
            cartela = None
        return cat, med, ficha, val, cartela

    def audit(c, user, action, entity_id, detail):
        c.execute('INSERT INTO auditoria(data,usuario,acao,entidade,entidade_id,detalhes) VALUES(?,?,?,?,?,?)',
                  (agora(), user['usuario'], action, 'recebimentos_siscofis', entity_id,
                   json.dumps(detail, ensure_ascii=False)))

    def transacao(action, d, user, execute):
        key = str(d.get('operacao_id') or '')
        if not 16 <= len(key) <= 100:
            raise ValueError('Identificador da operação inválido. Reabra o formulário.')
        signature = hashlib.sha256(json.dumps([action, user['usuario'], d], sort_keys=True,
                                             allow_nan=False).encode()).hexdigest()
        with lock:
            c = conn_factory()
            try:
                c.execute('BEGIN IMMEDIATE')
                old = c.execute('SELECT * FROM operacoes_siscofis WHERE chave=?', (key,)).fetchone()
                if old:
                    if old['assinatura'] != signature:
                        raise Conflito('Operação já utilizada com outros dados. Atualize a lista.')
                    return json.loads(old['resposta'])
                result = execute(c)
                c.execute('INSERT INTO operacoes_siscofis VALUES(?,?,?)',
                          (key, signature, json.dumps(result, ensure_ascii=False)))
                c.commit()
                return result
            except Exception:
                c.rollback()
                raise
            finally:
                c.close()

    def resposta(fn):
        try:
            return jsonify(**fn())
        except Conflito as e:
            return jsonify(erro=str(e)), 409
        except (ValueError, TypeError, OverflowError) as e:
            return jsonify(erro=str(e)), 400

    @app.route('/recebimentos', methods=['GET', 'POST'])
    def recebimentos():
        user, err = autorizado()
        if err:
            return err
        if request.method == 'GET':
            c = conn_factory()
            try:
                rows = c.execute("SELECT * FROM recebimentos_siscofis WHERE estado='PENDENTE' ORDER BY id DESC").fetchall()
                return jsonify(recebimentos=[dict(r) for r in rows], versao_recurso=1)
            finally:
                c.close()
        def criar():
            d = dados()
            cat, med, ficha, val, cartela = produto(d)
            qty = numero(d.get('estoque_inicial'), 'Quantidade recebida', True)
            def execute(c):
                now = agora()
                cur = c.execute('''INSERT INTO recebimentos_siscofis
                    (categoria,medicamento,ficha,validade,comprimidos_cartela,quantidade_recebida,
                    saldo_pendente,observacao,criado_em,criado_por,atualizado_em)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                    (cat, med, ficha, val, cartela, qty, qty, str(d.get('observacao') or ''), now, user['usuario'], now))
                audit(c, user, 'CADASTRO_AGUARDANDO_SISCOFIS', cur.lastrowid, d)
                return {'ok': True, 'id': cur.lastrowid}
            return transacao('criar', d, user, execute)
        return resposta(criar)

    @app.route('/recebimentos/<int:rid>', methods=['PUT', 'DELETE'])
    def editar_recebimento(rid):
        user, err = autorizado()
        if err:
            return err
        def alterar():
            d = dados()
            def execute(c):
                old = c.execute('SELECT * FROM recebimentos_siscofis WHERE id=?', (rid,)).fetchone()
                if not old or old['estado'] != 'PENDENTE' or old['versao'] != d.get('versao'):
                    raise Conflito('O recebimento foi alterado ou liberado. Atualize a lista antes de continuar.')
                if request.method == 'DELETE':
                    if not str(d.get('motivo') or '').strip():
                        raise ValueError('Informe o motivo do cancelamento.')
                    c.execute("UPDATE recebimentos_siscofis SET estado='CANCELADO',versao=versao+1,atualizado_em=? WHERE id=?", (agora(), rid))
                    audit(c, user, 'CANCELAR_RECEBIMENTO_SISCOFIS', rid, {'antes': dict(old), 'motivo': d['motivo']})
                else:
                    cat, med, ficha, val, cartela = produto(d)
                    qty = numero(d.get('saldo_pendente'), 'Saldo pendente', True)
                    c.execute('''UPDATE recebimentos_siscofis SET categoria=?,medicamento=?,ficha=?,validade=?,
                        comprimidos_cartela=?,saldo_pendente=?,observacao=?,versao=versao+1,atualizado_em=? WHERE id=?''',
                        (cat, med, ficha, val, cartela, qty, str(d.get('observacao') or ''), agora(), rid))
                    audit(c, user, 'EDITAR_RECEBIMENTO_SISCOFIS', rid, {'antes': dict(old), 'depois': d})
                return {'ok': True}
            return transacao(request.method + '/' + str(rid), d, user, execute)
        return resposta(alterar)

    @app.route('/recebimentos/liberar', methods=['POST'])
    def liberar():
        user, err = autorizado()
        if err:
            return err
        def processar():
            d = dados()
            items = d.get('itens')
            if not isinstance(items, list) or not 1 <= len(items) <= 500:
                raise ValueError('Selecione entre 1 e 500 recebimentos.')
            if any(not isinstance(i, dict) or type(i.get('id')) is not int for i in items):
                raise ValueError('Seleção inválida.')
            if len({i['id'] for i in items}) != len(items):
                raise ValueError('Recebimento repetido na seleção.')
            def execute(c):
                released = []
                for item in items:
                    row = c.execute('SELECT * FROM recebimentos_siscofis WHERE id=?', (item['id'],)).fetchone()
                    if not row or row['estado'] != 'PENDENTE' or row['versao'] != item.get('versao'):
                        raise Conflito('Um recebimento mudou ou já foi liberado. Nenhum item foi liberado; atualize a lista.')
                    qty = numero(item.get('quantidade'), 'Quantidade a liberar', True)
                    if qty > row['saldo_pendente']:
                        raise Conflito('Quantidade maior que o saldo aguardando conferência. Nenhum item foi liberado.')
                    target = c.execute('''SELECT * FROM lotes WHERE ativo=1 AND categoria=? AND medicamento=?
                        AND ficha=? AND COALESCE(validade,'')=? AND COALESCE(comprimidos_cartela,0)=? ORDER BY id LIMIT 1''',
                        (row['categoria'], row['medicamento'], row['ficha'], row['validade'] or '', row['comprimidos_cartela'] or 0)).fetchone()
                    now = agora()
                    before = target['estoque_atual'] if target else 0
                    if target:
                        lid = target['id']
                        c.execute('UPDATE lotes SET estoque_inicial=estoque_inicial+?,estoque_atual=estoque_atual+?,atualizado_em=? WHERE id=?', (qty, qty, now, lid))
                    else:
                        cur = c.execute('''INSERT INTO lotes(categoria,medicamento,ficha,validade,comprimidos_cartela,
                            estoque_inicial,estoque_atual,criado_em,atualizado_em) VALUES(?,?,?,?,?,?,?,?,?)''',
                            (row['categoria'], row['medicamento'], row['ficha'], row['validade'], row['comprimidos_cartela'], qty, qty, now, now))
                        lid = cur.lastrowid
                    remaining = row['saldo_pendente'] - qty
                    c.execute('''UPDATE recebimentos_siscofis SET saldo_pendente=?,quantidade_liberada=quantidade_liberada+?,
                        estado=?,versao=versao+1,atualizado_em=? WHERE id=?''',
                        (remaining, qty, 'LIBERADO' if remaining == 0 else 'PENDENTE', now, row['id']))
                    reference = str(d.get('referencia') or '').strip()
                    c.execute('INSERT INTO liberacoes_siscofis(recebimento_id,lote_id,quantidade,data,usuario,referencia,categoria,medicamento,ficha,validade) VALUES(?,?,?,?,?,?,?,?,?,?)',
                              (row['id'], lid, qty, now, user['usuario'], reference, row['categoria'], row['medicamento'], row['ficha'], row['validade']))
                    c.execute('''INSERT INTO movimentacoes(data,lote_id,categoria,medicamento,ficha,solicitante,
                        quantidade,estoque_anterior,estoque_final,tipo,observacao) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                        (now, lid, row['categoria'], row['medicamento'], row['ficha'], user['usuario'], qty,
                         before, before + qty, 'ENTRADA_SISCOFIS', 'Recebimento #' + str(row['id']) + ' · ' + reference))
                    audit(c, user, 'LIBERAR_SISCOFIS_PARA_ESTOQUE', row['id'],
                          {'lote_id': lid, 'quantidade': qty, 'saldo_pendente': remaining, 'referencia': reference})
                    released.append({'recebimento_id': row['id'], 'lote_id': lid, 'quantidade': qty, 'saldo_pendente': remaining})
                return {'ok': True, 'liberados': released}
            return transacao('liberar', d, user, execute)
        return resposta(processar)

    @app.route('/recebimentos/historico')
    def historico_recebimentos():
        _, err = autorizado()
        if err:
            return err
        c = conn_factory()
        try:
            rows = c.execute('SELECT * FROM liberacoes_siscofis ORDER BY id DESC LIMIT 2000').fetchall()
            return jsonify(liberacoes=[dict(r) for r in rows])
        finally:
            c.close()
