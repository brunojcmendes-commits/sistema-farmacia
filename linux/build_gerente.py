"""Empacota Gestor Farmácia HTML para Ubuntu 22.04, online e offline."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from build_clientes import ROOT, VERSION, portable_python, write


def package(folder, offline=False):
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / 'DEBIAN').mkdir()
        app = root / 'opt/gerente-farmacia'
        source = app / 'src'
        source.mkdir(parents=True)
        for name in ('desktop_bridge.py', 'gestor_html.py', 'gerente_farmacia_140.py',
                     'gerente_farmacia.py', 'farmacia_api.py', 'requests.py',
                     'Gerente_Farmacia.png'):
            shutil.copy2(ROOT / 'windows/src' / name, source / name)
        shutil.copytree(ROOT / 'windows/web', app / 'web',
                        ignore=shutil.ignore_patterns('__pycache__'))
        if offline:
            portable_python(app)
        icon = root / 'usr/share/icons/hicolor/256x256/apps/gerente-farmacia.png'
        icon.parent.mkdir(parents=True)
        shutil.copy2(ROOT / 'windows/src/Gerente_Farmacia.png', icon)
        launch = '''#!/bin/sh
set -eu
'''
        if offline:
            launch += '''export PYTHONHOME=/opt/gerente-farmacia/runtime
export PYTHONNOUSERSITE=1
exec /opt/gerente-farmacia/runtime/bin/python3 /opt/gerente-farmacia/src/gestor_html.py "$@"
'''
        else:
            launch += 'exec /usr/bin/python3 /opt/gerente-farmacia/src/gestor_html.py "$@"\n'
        write(root / 'usr/bin/gerente-farmacia', launch, 0o755)
        write(root / 'usr/share/applications/gerente-farmacia.desktop', '''[Desktop Entry]
Type=Application
Name=Gestor Farmácia
Comment=Gestão de estoque e pedidos
Exec=gerente-farmacia
Icon=gerente-farmacia
Terminal=false
Categories=Office;MedicalSoftware;
StartupNotify=true
''')
        write(root / 'DEBIAN/control', f'''Package: farmacia-gerente
Version: {VERSION}
Section: office
Priority: optional
Architecture: {'amd64' if offline else 'all'}
Maintainer: SISTFARMA
Depends: {'libc6 (>= 2.17)' if offline else 'python3 (>= 3.8)'}
Description: Gestor Farmacia HTML {'offline' if offline else 'online'} para Ubuntu 22.04
 Interface local e {'Python portatil incluidos' if offline else 'biblioteca padrao Python do sistema'}.
 A conexao com o Servidor Farmacia usa a rede configurada pelo gestor.
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
        filename = f'Gerente_Farmacia_Ubuntu_22.04_{"Offline" if offline else "Online"}_{VERSION}_{"amd64" if offline else "all"}.deb'
        output = folder / filename
        subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(root), str(output)], check=True)
        return output


if __name__ == '__main__':
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else 'dist/clientes-linux').resolve()
    folder.mkdir(parents=True, exist_ok=True)
    print(package(folder))
    print(package(folder, offline=True))
