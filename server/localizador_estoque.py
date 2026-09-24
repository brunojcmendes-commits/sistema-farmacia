"""Localização física dos lotes, sem expor endereços no catálogo do Cliente."""
import hashlib
import json
import math
from datetime import datetime
from flask import request, jsonify


def instalar(app, conn_factory, lock, agora, exigir_login, categorias):
    c = conn_factory()
    try:
        for table in ('lotes', 'recebimentos_siscofis'):
            columns = {r['name'] for r in c.execute('PRAGMA table_info(' + table + ')')}
            if 'localizador' not in columns:
                c.execute('ALTER TABLE ' + table + " ADD COLUMN localizador TEXT NOT NULL DEFAULT ''")
        c.execute('''CREATE TABLE IF NOT EXISTS operacoes_localizador
            (chave TEXT PRIMARY KEY, assinatura TEXT NOT NULL, resposta TEXT NOT NULL)''')
        c.commit()
    finally:
        c.close()

    def autorizado():
        user, error = exigir_login()
        if error:
            return None, error
        if user.get('perfil') not in ('gerente', 'administrador') or user.get('trocar_senha'):
            return None, (jsonify(erro='Acesso de gestão com senha pessoal necessário.'), 403)
        return user, None

    def texto(value, label, required=False, limit=160):
        value = str(value or '').strip()
        if len(value) > limit or (required and not value):
            raise ValueError(label + ' inválido.')
        return value

    def quantidade(value, label):
        if isinstance(value, bool):
            raise ValueError(label + ' inválido.')
        try:
            value = float(value)
        except (ValueError, TypeError):
            raise ValueError(label + ' inválido.')
        if not math.isfinite(value) or not 0 <= value <= 1e12:
            raise ValueError(label + ' deve ser um número não negativo.')
        return value

    def campos(d, editing=False):
        category = texto(d.get('categoria'), 'Categoria', True)
        if category not in categorias:
            raise ValueError('Categoria inválida.')
        med = texto(d.get('medicamento'), 'Produto', True)
        ficha = texto(d.get('ficha'), 'Ficha / lote', True)
        loc = texto(d.get('localizador'), 'Localizador', limit=120)
        expiry = texto(d.get('validade'), 'Validade', limit=10)
        if expiry:
            try:
                expiry = datetime.strptime(expiry, '%d/%m/%Y').strftime('%d/%m/%Y')
            except ValueError:
                raise ValueError('Validade inválida. Use dia/mês/ano.')
        units = d.get('comprimidos_cartela')
        if units in ('', None):
            units = None
        else:
            n = quantidade(units, 'Comprimidos por cartela')
            if n != int(n) or n == 0:
                raise ValueError('Comprimidos por cartela deve ser inteiro e maior que zero.')
            units = int(n)
        return category, med, ficha, expiry, units, loc

    def write(action, user, d, executor):
        key = texto(d.get('operacao_id'), 'Identificador da operação', True, 100)
        if len(key) < 16:
            raise ValueError('Identificador da operação inválido.')
        signature = hashlib.sha256(json.dumps([action, user['usuario'], d], sort_keys=True,
                                             allow_nan=False).encode()).hexdigest()
        with lock:
            c = conn_factory()
            try:
                c.execute('BEGIN IMMEDIATE')
                previous = c.execute('SELECT * FROM operacoes_localizador WHERE chave=?', (key,)).fetchone()
                if previous:
                    if previous['assinatura'] != signature:
                        return jsonify(erro='Operação já utilizada com outros dados.'), 409
                    return jsonify(**json.loads(previous['resposta']))
                result = executor(c)
                c.execute('INSERT INTO operacoes_localizador VALUES(?,?,?)',
                          (key, signature, json.dumps(result, ensure_ascii=False)))
                c.commit()
                return jsonify(**result)
            except ValueError as exc:
                c.rollback()
                return jsonify(erro=str(exc)), 400
            except Exception:
                c.rollback()
                raise
            finally:
                c.close()

    def audit(c, user, action, lid, detail):
        c.execute('INSERT INTO auditoria(data,usuario,acao,entidade,entidade_id,detalhes) VALUES(?,?,?,?,?,?)',
                  (agora(), user['usuario'], action, 'lotes', lid, detail))

    @app.route('/itens-localizados', methods=['POST', 'PUT'])
    def itens_localizados():
        user, error = autorizado()
        if error:
            return error
        d = request.get_json(force=True)
        if not isinstance(d, dict):
            return jsonify(erro='Solicitação inválida.'), 400
        try:
            if request.method == 'POST':
                cat, med, ficha, expiry, units, loc = campos(d)
                qty = quantidade(d.get('estoque_inicial'), 'Estoque inicial')

                def create(c):
                    row = c.execute('''SELECT * FROM lotes WHERE ativo=1 AND categoria=? AND medicamento=?
                      AND ficha=? AND COALESCE(validade,'')=? AND COALESCE(localizador,'')=? LIMIT 1''',
                        (cat, med, ficha, expiry, loc)).fetchone()
                    now = agora()
                    if row:
                        lid = row['id']
                        c.execute('''UPDATE lotes SET estoque_inicial=estoque_inicial+?,estoque_atual=estoque_atual+?,
                           comprimidos_cartela=COALESCE(?,comprimidos_cartela),atualizado_em=? WHERE id=?''',
                           (qty, qty, units, now, lid))
                    else:
                        cur = c.execute('''INSERT INTO lotes(categoria,medicamento,ficha,validade,comprimidos_cartela,
                           localizador,estoque_inicial,estoque_atual,criado_em,atualizado_em) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                           (cat, med, ficha, expiry or None, units, loc, qty, qty, now, now))
                        lid = cur.lastrowid
                    audit(c, user, 'CADASTRO_LOTE_LOCALIZADO', lid,
                          json.dumps({'quantidade': qty, 'localizador': loc, 'mesclado': bool(row)}, ensure_ascii=False))
                    return {'ok': True, 'id': lid, 'mesclado': bool(row)}
                return write('criar', user, d, create)

            try:
                lid = int(d['lote_id'])
            except (KeyError, ValueError, TypeError):
                raise ValueError('Lote inválido.')
            cat, med, ficha, expiry, units, loc = campos(d)
            initial = quantidade(d.get('estoque_inicial'), 'Estoque inicial')
            current = quantidade(d.get('estoque_atual'), 'Estoque atual')

            def edit(c):
                row = c.execute('SELECT * FROM lotes WHERE id=? AND ativo=1', (lid,)).fetchone()
                if not row:
                    raise ValueError('Lote não encontrado.')
                c.execute('''UPDATE lotes SET categoria=?,medicamento=?,ficha=?,validade=?,comprimidos_cartela=?,
                    localizador=?,estoque_inicial=?,estoque_atual=?,atualizado_em=? WHERE id=?''',
                    (cat, med, ficha, expiry or None, units, loc, initial, current, agora(), lid))
                audit(c, user, 'EDICAO_LOTE_LOCALIZADO', lid,
                      json.dumps({'localizador_anterior': row['localizador'], 'localizador': loc}, ensure_ascii=False))
                return {'ok': True, 'id': lid}
            return write('editar/' + str(lid), user, d, edit)
        except (ValueError, TypeError, OverflowError) as exc:
            return jsonify(erro=str(exc)), 400

    @app.route('/localizadores')
    def localizadores():
        _, error = autorizado()
        if error:
            return error
        c = conn_factory()
        try:
            return jsonify(localizadores=[dict(row) for row in
                c.execute('SELECT id,localizador FROM lotes WHERE ativo=1 ORDER BY id')])
        finally:
            c.close()

    @app.route('/pedidos/<int:pid>/localizadores')
    def localizadores_pedido(pid):
        _, error = autorizado()
        if error:
            return error
        c = conn_factory()
        try:
            if not c.execute('SELECT 1 FROM pedido_cabecalhos WHERE id=?', (pid,)).fetchone():
                return jsonify(erro='Pedido não encontrado.'), 404
            result = []
            items = c.execute('SELECT id,categoria,medicamento,movimentos_json FROM pedido_itens WHERE pedido_id=? ORDER BY id', (pid,))
            for item in items:
                try:
                    movements = json.loads(item['movimentos_json'] or '[]')
                except (ValueError, TypeError):
                    movements = []
                locations = []
                for move in movements if isinstance(movements, list) else []:
                    if not isinstance(move, dict) or type(move.get('lote_id')) is not int:
                        continue
                    lot = c.execute('SELECT ficha,localizador FROM lotes WHERE id=?', (move['lote_id'],)).fetchone()
                    locations.append({'ficha': move.get('ficha') or (lot['ficha'] if lot else ''),
                        'localizador': lot['localizador'] if lot else '',
                        'quantidade': move.get('retirada'), 'lote_id': move['lote_id']})
                result.append({'item_id': item['id'], 'localizadores': locations})
            return jsonify(itens=result)
        finally:
            c.close()
