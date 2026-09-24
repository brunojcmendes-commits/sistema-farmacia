"""Instalador completo do Servidor Farmácia para uma instalação nova em Ubuntu."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from instalar_extensao import HOOK

here = Path(__file__).resolve().parent
output = Path(sys.argv[1]).resolve()
output.parent.mkdir(parents=True, exist_ok=True)

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    root.chmod(0o755)
    control = root / 'DEBIAN'
    control.mkdir()
    target = root / 'opt/farmacia-servidor'
    target.mkdir(parents=True)
    for name in ('flask.py', 'recursos_estoque_130.py'):
        shutil.copy2(here / 'base' / name, target / name)
    for name in ('recebimentos_siscofis.py', 'localizador_estoque.py', 'externos_estoque.py'):
        shutil.copy2(here / name, target / name)
    source = (here / 'base/servidor_estoque.py').read_text(encoding='utf-8')
    marker = "if __name__=='__main__':iniciar_servidor()"
    if source.count(marker) != 1:
        raise RuntimeError('Marcador de inicialização não encontrado.')
    source = source.replace(marker, HOOK + marker)
    compile(source, str(target / 'servidor_estoque.py'), 'exec')
    (target / 'servidor_estoque.py').write_text(source, encoding='utf-8')
    service = root / 'lib/systemd/system/farmacia-servidor.service'
    service.parent.mkdir(parents=True)
    service.write_text('''[Unit]
Description=Servidor Farmácia - Controle de Estoque
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/farmacia-servidor
Environment=FARMACIA_DATA_DIR=/var/lib/farmacia-servidor
ExecStart=/usr/bin/python3 /opt/farmacia-servidor/servidor_estoque.py
Restart=always
RestartSec=3
User=farmacia
Group=farmacia

[Install]
WantedBy=multi-user.target
''')
    (control / 'control').write_text('''Package: farmacia-servidor
Version: 1.4.4
Section: misc
Priority: optional
Architecture: all
Depends: python3 (>= 3.8)
Conflicts: farmacia-conferencia-siscofis
Maintainer: SISTFARMA
Description: Servidor Farmacia completo com conferencia e localizadores
 Instalacao nova Ubuntu 22.04, sem incluir banco de dados no pacote.
 O banco de uma instalacao existente permanece em /var/lib/farmacia-servidor.
''')
    (control / 'preinst').write_text('''#!/bin/sh
set -eu
if [ "$1" = upgrade ] && command -v systemctl >/dev/null && [ -d /run/systemd/system ]; then
  systemctl stop farmacia-servidor || true
fi
db=/var/lib/farmacia-servidor/farmacia.db
if [ -f "$db" ]; then
  mkdir -p /var/backups/sistfarma-servidor
  STAMP=$(date +%Y%m%d-%H%M%S)
  export SISTFARMA_BACKUP_DB="$db" SISTFARMA_BACKUP_OUT="/var/backups/sistfarma-servidor/antes_1.4.4_${STAMP}.db"
  python3 - <<'PYBACKUP'
import os, sqlite3
source = sqlite3.connect(os.environ['SISTFARMA_BACKUP_DB'])
dest = sqlite3.connect(os.environ['SISTFARMA_BACKUP_OUT'])
try:
    source.backup(dest)
finally:
    dest.close()
    source.close()
PYBACKUP
fi
''')
    (control / 'postinst').write_text('''#!/bin/sh
set -eu
if [ "$1" = configure ]; then
  if ! id farmacia >/dev/null 2>&1; then
    useradd --system --home /var/lib/farmacia-servidor --shell /usr/sbin/nologin farmacia
  fi
  mkdir -p /var/lib/farmacia-servidor
  chown -R farmacia:farmacia /var/lib/farmacia-servidor
  if command -v systemctl >/dev/null && [ -d /run/systemd/system ]; then
    systemctl daemon-reload
    systemctl enable farmacia-servidor.service
    systemctl restart farmacia-servidor.service
  fi
fi
''')
    for name in ('preinst', 'postinst'):
        (control / name).chmod(0o755)
    subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(root), str(output)], check=True)
print(output)
