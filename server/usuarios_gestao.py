"""Recuperação de senha e exclusão de administradores pelo Gerente."""
from flask import request, jsonify


def instalar(app, conn_factory, exigir_gerente, hash_senha, sessoes, audit):
    @app.route('/usuarios/<int:uid>/senha', methods=['POST'])
    def redefinir_senha_usuario(uid):
        usuario, erro = exigir_gerente()
        if erro:
            return erro
        if uid == usuario['id']:
            return jsonify(erro='Use Alterar minha senha para a própria conta.'), 400
        d = request.get_json(force=True) or {}
        nova = str(d.get('nova_senha') or '')
        if len(nova) < 6:
            return jsonify(erro='A senha deve possuir ao menos 6 caracteres.'), 400
        c = conn_factory()
        try:
            alvo = c.execute("SELECT perfil FROM usuarios WHERE id=?", (uid,)).fetchone()
            if not alvo or alvo['perfil'] != 'administrador':
                return jsonify(erro='Somente a senha de um Administrador pode ser redefinida.'), 400
            salt, digest = hash_senha(nova)
            c.execute("UPDATE usuarios SET senha_salt=?,senha_hash=?,trocar_senha=1 WHERE id=?",
                      (salt, digest, uid))
            c.commit()
        finally:
            c.close()
        for token, sessao in list(sessoes.items()):
            if sessao['usuario']['id'] == uid:
                sessoes.pop(token, None)
        audit('REDEFINIR_SENHA_USUARIO', 'usuarios', uid, usuario=usuario['usuario'])
        return jsonify(ok=True)

    @app.route('/usuarios/<int:uid>', methods=['DELETE'])
    def excluir_usuario(uid):
        usuario, erro = exigir_gerente()
        if erro:
            return erro
        if uid == usuario['id']:
            return jsonify(erro='Não é possível excluir a própria conta.'), 400
        c = conn_factory()
        try:
            alvo = c.execute("SELECT usuario,perfil FROM usuarios WHERE id=?", (uid,)).fetchone()
            if not alvo or alvo['perfil'] != 'administrador':
                return jsonify(erro='Somente contas de Administrador podem ser excluídas.'), 400
            nome = alvo['usuario']
            c.execute("DELETE FROM usuarios WHERE id=?", (uid,))
            c.commit()
        finally:
            c.close()
        for token, sessao in list(sessoes.items()):
            if sessao['usuario']['id'] == uid:
                sessoes.pop(token, None)
        audit('EXCLUIR_USUARIO', 'usuarios', uid, nome, usuario=usuario['usuario'])
        return jsonify(ok=True)
