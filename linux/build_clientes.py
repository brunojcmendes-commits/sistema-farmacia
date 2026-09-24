"""Empacota Cliente Farmácia HTML para Ubuntu 22.04 e Mint 20.3."""
from pathlib import Path
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.4.4'
TARGETS = [('Ubuntu_22.04', 'Ubuntu 22.04'), ('Mint_20.3', 'Linux Mint 20.3')]


def write(path, content, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    if mode:
        path.chmod(mode)


def portable_python(app):
    executable = Path(os.environ.get('SISTFARMA_PORTABLE_PYTHON',
                os.environ.get('CODEX_PRIMARY_RUNTIME_PYTHON', ''))).resolve()
    if not executable.is_file():
        raise RuntimeError('Informe SISTFARMA_PORTABLE_PYTHON para compilar o pacote offline.')
    version = subprocess.check_output([str(executable), '-c',
                'import sys;print("%d.%d" % sys.version_info[:2])'], text=True).strip()
    source = executable.parent.parent / 'lib' / ('python' + version)
    if not (source / 'encodings').is_dir():
        raise RuntimeError('Biblioteca padrão do Python portátil não encontrada.')
    versions = re.findall(r'GLIBC_(\d+)\.(\d+)', subprocess.check_output(
        ['readelf', '--version-info', str(executable)], text=True))
    if not versions or max((int(a), int(b)) for a, b in versions) > (2, 31):
        raise RuntimeError('Runtime exige glibc posterior à versão do Mint 20.3.')
    target = app / 'runtime'
    (target / 'bin').mkdir(parents=True)
    shutil.copy2(executable, target / 'bin/python3')
    shutil.copytree(source, target / 'lib' / ('python' + version),
        ignore=shutil.ignore_patterns('site-packages', '__pycache__', 'ensurepip',
            'idlelib', 'unittest', 'test', 'lib2to3', 'tkinter', 'turtledemo',
            'pydoc_data', 'venv', 'config-*', 'lib-dynload'))
    return version


def package(folder, target, label, offline=False):
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / 'DEBIAN').mkdir()
        app = root / 'opt/cliente-farmacia'
        source = app / 'src'
        source.mkdir(parents=True)
        for filename in ('desktop_bridge.py', 'cliente_html.py', 'cliente_farmacia.py',
                         'farmacia_api.py', 'requests.py', 'Cliente_Farmacia.png'):
            shutil.copy2(ROOT / 'windows/src' / filename, source / filename)
        shutil.copytree(ROOT / 'windows/web', app / 'web', ignore=shutil.ignore_patterns('__pycache__'))
        if offline:
            portable_python(app)
        icon = root / 'usr/share/icons/hicolor/256x256/apps/cliente-farmacia.png'
        icon.parent.mkdir(parents=True)
        shutil.copy2(ROOT / 'windows/src/Cliente_Farmacia.png', icon)
        write(root / 'usr/bin/cliente-farmacia', '''#!/bin/sh
set -eu
''' + ('''export PYTHONHOME=/opt/cliente-farmacia/runtime
export PYTHONNOUSERSITE=1
exec /opt/cliente-farmacia/runtime/bin/python3 /opt/cliente-farmacia/src/cliente_html.py "$@"
''' if offline else '''
exec /usr/bin/python3 /opt/cliente-farmacia/src/cliente_html.py "$@"
'''), 0o755)
        write(root / 'usr/share/applications/cliente-farmacia.desktop', '''[Desktop Entry]
Type=Application
Name=Cliente Farmácia
Comment=Solicitação de medicamentos e materiais
Exec=cliente-farmacia
Icon=cliente-farmacia
Terminal=false
Categories=Office;MedicalSoftware;
StartupNotify=true
''')
        write(root / 'DEBIAN/control', f'''Package: farmacia-solicitacao
Version: {VERSION}
Section: office
Priority: optional
Architecture: {'amd64' if offline else 'all'}
Maintainer: SISTFARMA
Depends: {'libc6 (>= 2.17)' if offline else 'python3 (>= 3.8)'}
Conflicts: farmacia-cliente (<< 1.2.6)
Replaces: farmacia-cliente (<< 1.2.6)
Description: Cliente Farmacia HTML {'offline' if offline else 'online'} para {label}
 Interface e {'Python 3.12 portatil incluidos' if offline else 'biblioteca padrao Python do sistema'}.
 A conexao com o Servidor Farmacia usa a rede configurada pelo operador.
''')
        write(root / 'DEBIAN/postinst', '''#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
''', 0o755)
        name = f'Cliente_Farmacia_{target}_{"Offline" if offline else "Online"}_{VERSION}_{"amd64" if offline else "all"}.deb'
        output = folder / name
        subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(root), str(output)], check=True)
        return output


def main():
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else 'dist/clientes-linux').resolve()
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for target, label in TARGETS:
        files += [package(folder, target, label), package(folder, target, label, offline=True)]
    write(folder / 'SHA256SUMS.txt', ''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in files))
    for path in files:
        print(path)


if __name__ == '__main__':
    main()
