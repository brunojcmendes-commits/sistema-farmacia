"""Recursos 1.3.0: controlados, transferências e conferência semanal."""
import random
from datetime import datetime
from flask import request, jsonify

CONTROLADOS = "Medicamentos Controlados"


def instalar(app, db, conn_factory, lock, agora, exigir_login, formato_data):
    def preparar_banco():
        c = conn_factory()
        c.executescript('''
        CREATE TABLE IF NOT EXISTS conferencias_estoque(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semana TEXT NOT NULL,
            lote_id INTEGER NOT NULL,
            categoria TEXT NOT NULL,
            medicamento TEXT NOT NULL,
            ficha TEXT,
            validade TEXT,
            estoque_virtual REAL NOT NULL,
            estoque_fisico REAL,
            diferenca REAL,
            resultado TEXT NOT NULL DEFAULT 'PENDENTE',
            pg TEXT,
            nome_guerra TEXT,
            observacao TEXT,
            conferido_em TEXT,
            criado_em TEXT NOT NULL,
            UNIQUE(semana,lote_id)
        );
        CREATE INDEX IF NOT EXISTS idx_conferencias_semana ON conferencias_estoque(semana);
        CREATE INDEX IF NOT EXISTS idx_conferencias_lote ON conferencias_estoque(lote_id);
        ''')
        c.commit(); c.close()

    preparar_banco()

    def semana_atual():
        ano, semana, _ = datetime.now().isocalendar()
        return f"{ano}-S{semana:02d}"

    def usuario_ou_erro():
        usuario, erro = exigir_login()
        return usuario, erro

    def selecionar_semana(c, semana, quantidade=5):
        existentes = c.execute(
            "SELECT COUNT(*) FROM conferencias_estoque WHERE semana=?", (semana,)
        ).fetchone()[0]
        if existentes:
            return
        lotes = c.execute('''
            SELECT l.*,
                   MAX(ce.conferido_em) ultima_conferencia,
                   SUM(CASE WHEN ce.resultado IN ('DIVERGENTE','AJUSTADO') THEN 1 ELSE 0 END) divergencias
            FROM lotes l
            LEFT JOIN conferencias_estoque ce ON ce.lote_id=l.id
            WHERE l.ativo=1 AND l.estoque_atual>0
            GROUP BY l.id
        ''').fetchall()
        lotes = list(lotes)
        random.shuffle(lotes)
        lotes.sort(key=lambda r: (
            0 if not r['ultima_conferencia'] else 1,
            -int(r['divergencias'] or 0),
            r['ultima_conferencia'] or '',
        ))
        for lote in lotes[:max(1, min(int(quantidade), 50))]:
            c.execute('''INSERT OR IGNORE INTO conferencias_estoque
                (semana,lote_id,categoria,medicamento,ficha,validade,estoque_virtual,criado_em)
                VALUES(?,?,?,?,?,?,?,?)''', (
                semana,lote['id'],lote['categoria'],lote['medicamento'],lote['ficha'],
                lote['validade'],lote['estoque_atual'],agora()
            ))

    @app.route('/estoque/transferir', methods=['POST'])
    def transferir_estoque_130():
        usuario, erro = usuario_ou_erro()
        if erro: return erro
        d = request.get_json(force=True) or {}
        try: lote_id = int(d.get('lote_id'))
        except (TypeError, ValueError): return jsonify(erro='Lote inválido.'), 400
        destino = str(d.get('destino') or '').strip().lower()
        mover_tudo = bool(d.get('mover_tudo'))
        try: quantidade = float(d.get('quantidade') or 0)
        except (TypeError, ValueError): return jsonify(erro='Quantidade inválida.'), 400
        if destino not in ('controlados','externos'):
            return jsonify(erro='Destino inválido.'), 400
        with lock:
            c = conn_factory()
            try:
                c.execute('BEGIN IMMEDIATE')
                lote = c.execute("SELECT * FROM lotes WHERE id=? AND ativo=1",(lote_id,)).fetchone()
                if not lote: raise ValueError('Lote não encontrado.')
                saldo = float(lote['estoque_atual'] or 0)
                qtd = saldo if mover_tudo else quantidade
                if qtd <= 0: raise ValueError('Informe uma quantidade maior que zero.')
                if qtd > saldo: raise ValueError(f'Quantidade superior ao saldo disponível ({saldo:g}).')
                origem = lote['categoria']; now = agora()
                if destino == 'controlados':
                    if origem == CONTROLADOS: raise ValueError('O lote já está em Medicamentos Controlados.')
                    if qtd == saldo:
                        c.execute("UPDATE lotes SET categoria=?,atualizado_em=? WHERE id=?",(CONTROLADOS,now,lote_id))
                        destino_id=lote_id
                    else:
                        c.execute("UPDATE lotes SET estoque_atual=estoque_atual-?,atualizado_em=? WHERE id=?",(qtd,now,lote_id))
                        alvo=c.execute('''SELECT * FROM lotes WHERE ativo=1 AND categoria=? AND medicamento=?
                            AND ficha=? AND COALESCE(validade,'')=COALESCE(?, '') LIMIT 1''',
                            (CONTROLADOS,lote['medicamento'],lote['ficha'],lote['validade'])).fetchone()
                        if alvo:
                            c.execute("UPDATE lotes SET estoque_inicial=estoque_inicial+?,estoque_atual=estoque_atual+?,atualizado_em=? WHERE id=?",(qtd,qtd,now,alvo['id']))
                            destino_id=alvo['id']
                        else:
                            cur=c.execute('''INSERT INTO lotes(categoria,medicamento,ficha,apresentacao,comprimidos_cartela,
                                validade,estoque_inicial,estoque_atual,saida_total,siscofis,observacao,ativo,criado_em,atualizado_em)
                                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(CONTROLADOS,lote['medicamento'],lote['ficha'],lote['apresentacao'],
                                lote['comprimidos_cartela'],lote['validade'],qtd,qtd,0,lote['siscofis'],lote['observacao'],1,now,now))
                            destino_id=cur.lastrowid
                    destino_nome=CONTROLADOS
                else:
                    c.execute("UPDATE lotes SET estoque_atual=estoque_atual-?,atualizado_em=? WHERE id=?",(qtd,now,lote_id))
                    alvo=c.execute("SELECT * FROM apoio WHERE ativo=1 AND material=? AND lote=? AND COALESCE(validade,'')=COALESCE(?, '') LIMIT 1",
                        (lote['medicamento'],lote['ficha'],lote['validade'])).fetchone()
                    if alvo:
                        c.execute("UPDATE apoio SET estoque_inicial=estoque_inicial+?,estoque_atual=estoque_atual+?,atualizado_em=? WHERE id=?",(qtd,qtd,now,alvo['id']))
                        destino_id=alvo['id']
                    else:
                        cur=c.execute("INSERT INTO apoio(material,lote,validade,estoque_inicial,estoque_atual,observacao,ativo,criado_em,atualizado_em) VALUES(?,?,?,?,?,?,1,?,?)",
                            (lote['medicamento'],lote['ficha'],lote['validade'],qtd,qtd,'Transferido do estoque principal',now,now))
                        destino_id=cur.lastrowid
                    destino_nome='Lotes Externos'
                c.execute('''INSERT INTO movimentacoes(data,lote_id,categoria,medicamento,ficha,solicitante,
                    quantidade,estoque_anterior,estoque_final,tipo,observacao) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                    (now,lote_id,origem,lote['medicamento'],lote['ficha'],usuario['usuario'],qtd,saldo,saldo-qtd,
                     'TRANSFERENCIA_SAIDA',f'Destino: {destino_nome}; registro {destino_id}'))
                c.commit()
            except ValueError as exc:
                c.rollback(); c.close(); return jsonify(erro=str(exc)),400
            except Exception:
                c.rollback(); c.close(); raise
            c.close()
            db._audit('TRANSFERIR_ESTOQUE','lotes',lote_id,
                f'{origem} -> {destino_nome}; quantidade={qtd:g}',usuario=usuario['usuario'])
        return jsonify(ok=True,quantidade=qtd,destino=destino_nome)

    @app.route('/conferencias/semana')
    def conferencias_semana_130():
        usuario, erro = usuario_ou_erro()
        if erro: return erro
        semana = str(request.args.get('semana') or semana_atual())
        quantidade = request.args.get('quantidade',5,type=int)
        with lock:
            c=conn_factory(); selecionar_semana(c,semana,quantidade); c.commit()
            rows=c.execute("SELECT * FROM conferencias_estoque WHERE semana=? ORDER BY id",(semana,)).fetchall();c.close()
        return jsonify(semana=semana,conferencias=[dict(r) for r in rows])

    @app.route('/conferencias/<int:cid>',methods=['POST'])
    def registrar_conferencia_130(cid):
        usuario, erro = usuario_ou_erro()
        if erro: return erro
        d=request.get_json(force=True) or {};pg=str(d.get('pg') or '').strip();nome=str(d.get('nome_guerra') or '').strip()
        if not pg or not nome:return jsonify(erro='Informe P/G e Nome de Guerra.'),400
        try:fisico=float(d.get('estoque_fisico'))
        except (TypeError,ValueError):return jsonify(erro='Quantidade física inválida.'),400
        if fisico<0:return jsonify(erro='A quantidade física não pode ser negativa.'),400
        ajustar=bool(d.get('ajustar'));obs=str(d.get('observacao') or '').strip()
        with lock:
            c=conn_factory()
            try:
                c.execute('BEGIN IMMEDIATE');conf=c.execute("SELECT * FROM conferencias_estoque WHERE id=?",(cid,)).fetchone()
                if not conf:raise ValueError('Conferência não encontrada.')
                lote=c.execute("SELECT * FROM lotes WHERE id=? AND ativo=1",(conf['lote_id'],)).fetchone()
                if not lote:raise ValueError('Lote não está mais ativo.')
                virtual=float(lote['estoque_atual'] or 0);dif=fisico-virtual
                resultado='OK' if dif==0 else ('AJUSTADO' if ajustar else 'DIVERGENTE')
                if ajustar and dif!=0:
                    c.execute("UPDATE lotes SET estoque_atual=?,atualizado_em=? WHERE id=?",(fisico,agora(),lote['id']))
                    c.execute('''INSERT INTO movimentacoes(data,lote_id,categoria,medicamento,ficha,solicitante,
                        quantidade,estoque_anterior,estoque_final,tipo,observacao) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                        (agora(),lote['id'],lote['categoria'],lote['medicamento'],lote['ficha'],f'{pg} {nome}',abs(dif),virtual,fisico,'AJUSTE_CONFERENCIA',obs))
                c.execute('''UPDATE conferencias_estoque SET estoque_virtual=?,estoque_fisico=?,diferenca=?,resultado=?,
                    pg=?,nome_guerra=?,observacao=?,conferido_em=? WHERE id=?''',(virtual,fisico,dif,resultado,pg,nome,obs,agora(),cid))
                c.commit()
            except ValueError as exc:c.rollback();c.close();return jsonify(erro=str(exc)),404
            c.close();db._audit('CONFERENCIA_ESTOQUE','conferencias',cid,f'{pg} {nome}; virtual={virtual:g}; físico={fisico:g}; {resultado}',usuario=usuario['usuario'])
        return jsonify(ok=True,resultado=resultado,diferenca=dif)

    @app.route('/conferencias/historico')
    def historico_conferencias_130():
        usuario, erro = usuario_ou_erro()
        if erro:return erro
        inicio=str(request.args.get('inicio') or '').strip();fim=str(request.args.get('fim') or '').strip()
        c=conn_factory();q="SELECT * FROM conferencias_estoque WHERE resultado<>'PENDENTE'";p=[]
        if inicio:q+=" AND conferido_em>=?";p.append(inicio)
        if fim:q+=" AND conferido_em<=?";p.append(fim)
        q+=" ORDER BY id DESC";rows=c.execute(q,p).fetchall();c.close()
        return jsonify(conferencias=[dict(r) for r in rows])

    return preparar_banco
