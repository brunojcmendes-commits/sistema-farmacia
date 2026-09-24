"""Atualiza apenas o ponto de extensão do servidor já instalado; nunca troca sua base."""
import argparse
from datetime import datetime
from pathlib import Path
import os
import shutil
import sqlite3

START = '# BEGIN SISTFARMA SISCOFIS 1.4.4'
END = '# END SISTFARMA SISCOFIS 1.4.4'
HOOK = START + '''
from recebimentos_siscofis import instalar as _instalar_siscofis
_instalar_siscofis(app, _conn, _lock, _agora, _exigir_login, CATEGORIAS)
from localizador_estoque import instalar as _instalar_localizador
_instalar_localizador(app, _conn, _lock, _agora, _exigir_login, CATEGORIAS)
from externos_estoque import instalar as _instalar_externos
_instalar_externos(app, _conn, _lock, _agora, _exigir_login, db._audit)
''' + END + '\n'


def atualizar(root=Path('/'), remove=False):
    root = Path(root)
    source = root / 'opt/farmacia-servidor/servidor_estoque.py'
    original = source.read_text(encoding='utf-8')
    text = original
    for version in ('1.4.2', '1.4.3', '1.4.4'):
        first = '# BEGIN SISTFARMA SISCOFIS ' + version
        last = '# END SISTFARMA SISCOFIS ' + version
        if first in text:
            begin = text.index(first)
            end = text.index(last, begin) + len(last)
            text = text[:begin] + text[end:].lstrip('\n')
    if not remove:
        for required in ('def _conn(', 'def _exigir_login(', 'CATEGORIAS=', 'from recursos_estoque_130 import instalar'):
            if required not in text:
                raise RuntimeError('Servidor incompatível. Nenhum arquivo foi alterado: ' + required)
        marker = "if __name__=='__main__':iniciar_servidor()"
        if text.count(marker) != 1:
            raise RuntimeError('Inicialização do servidor não reconhecida. Nenhum arquivo foi alterado.')
        text = text.replace(marker, HOOK + marker)
    compile(text, str(source), 'exec')
    if text == original:
        return None
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = root / 'var/backups/sistfarma-siscofis' / stamp
    backup.mkdir(parents=True, mode=0o700)
    shutil.copy2(source, backup / source.name)
    for name, path in [('servico', root / 'var/lib/farmacia-servidor/farmacia.db'),
                       ('local', source.parent / 'farmacia.db')]:
        if path.is_file():
            src = sqlite3.connect(path)
            dst = sqlite3.connect(backup / ('farmacia-' + name + '.db'))
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
    stat = source.stat()
    tmp = source.with_suffix('.py.siscofis-tmp')
    try:
        tmp.write_text(text, encoding='utf-8')
        os.chmod(tmp, stat.st_mode)
        if hasattr(os, 'chown') and os.geteuid() == 0:
            os.chown(tmp, stat.st_uid, stat.st_gid)
        os.replace(tmp, source)
    finally:
        if tmp.exists():
            tmp.unlink()
    return backup


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('/'))
    parser.add_argument('--remove', action='store_true')
    args = parser.parse_args()
    backup = atualizar(args.root, args.remove)
    print('Extensão atualizada. Backup: ' + str(backup) if backup else 'Extensão já configurada.')
