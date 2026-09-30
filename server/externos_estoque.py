"""Consulta e edição identificada dos lotes externos do servidor existente."""
from datetime import datetime
import math

from flask import jsonify, request


def instalar(app, conn, lock, agora, exigir_login, audit):
    def serialize(row):
        return {key: row[key] for key in ('id', 'material', 'lote', 'validade',
                'estoque_inicial', 'estoque_atual', 'observacao')}

    @app.route('/apoio/detalhes', methods=['GET'])
    def apoio_detalhes():
        _, erro = exigir_login()
        if erro:
            return erro
        with lock:
            with conn() as db:
                rows = db.execute('SELECT * FROM apoio WHERE ativo=1 ORDER BY material,lote,id').fetchall()
                return jsonify(itens=[serialize(row) for row in rows])

    @app.route('/apoio/<int:item_id>', methods=['PUT', 'DELETE'])
    def apoio_item(item_id):
        usuario, erro = exigir_login()
        if erro:
            return erro
        data = request.get_json(force=True) or {}
        if request.method == 'PUT':
            material = str(data.get('material') or '').strip()
            lote = str(data.get('lote') or '').strip()
            observacao = str(data.get('observacao') or '').strip()
            validade = str(data.get('validade') or '').strip()
            if not material or not lote or len(material) > 240 or len(lote) > 120 or len(observacao) > 2000:
                return jsonify(erro='Informe material, lote e observação dentro dos limites permitidos.'), 400
            if validade:
                try:
                    validade = datetime.strptime(validade, '%d/%m/%Y').strftime('%d/%m/%Y')
                except ValueError:
                    return jsonify(erro='Validade inválida. Use dd/mm/aaaa.'), 400
            try:
                inicial = float(data['estoque_inicial'])
                atual = float(data['estoque_atual'])
                if not math.isfinite(inicial) or not math.isfinite(atual) or min(inicial, atual) < 0:
                    raise ValueError()
            except (ValueError, TypeError, KeyError):
                return jsonify(erro='Quantidades devem ser números finitos e não negativos.'), 400
        with lock:
            with conn() as db:
                row = db.execute('SELECT * FROM apoio WHERE id=? AND ativo=1', (item_id,)).fetchone()
                if row is None:
                    return jsonify(erro='Lote externo não encontrado.'), 404
                if request.method == 'DELETE':
                    db.execute('UPDATE apoio SET ativo=0,atualizado_em=? WHERE id=?', (agora(), item_id))
                    action = 'EXCLUSAO_EXTERNO'
                else:
                    db.execute('''UPDATE apoio SET material=?,lote=?,validade=?,estoque_inicial=?,
                        estoque_atual=?,observacao=?,atualizado_em=? WHERE id=?''',
                        (material, lote, validade or None, inicial, atual, observacao, agora(), item_id))
                    action = 'EDICAO_EXTERNO'
                db.commit()
            audit(action, 'apoio', item_id, 'Lote externo: ' + str(row['material']) + ' / ' + str(row['lote']))
        return jsonify(ok=True, id=item_id)
