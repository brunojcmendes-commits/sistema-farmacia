"""Cria atualização offline para o servidor Ubuntu/Mint existente."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

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
    for name in ('recebimentos_siscofis.py', 'localizador_estoque.py', 'externos_estoque.py', 'instalar_extensao.py'):
        shutil.copy2(here / name, target / name)
    (control / 'control').write_text('''Package: farmacia-conferencia-siscofis
Version: 1.4.4
Section: misc
Priority: optional
Architecture: all
Depends: python3 (>= 3.8)
Maintainer: SISTFARMA
Description: Estoque segregado para conferencia e liberacao SISCOFIS
 Extensao offline para o Servidor Farmacia 1.3.0 existente.
 Preserva banco, usuarios, configuracoes e rotas anteriores.
''')
    (control / 'preinst').write_text('''#!/bin/sh
set -eu
test -f /opt/farmacia-servidor/servidor_estoque.py || { echo "Instale este pacote no computador do Servidor Farmácia existente." >&2; exit 1; }
grep -q 'from recursos_estoque_130 import instalar' /opt/farmacia-servidor/servidor_estoque.py || { echo "Servidor incompatível: necessário módulo de conferência 1.3.0." >&2; exit 1; }
''')
    (control / 'postinst').write_text('''#!/bin/sh
set -eu
if [ "$1" = configure ]; then
  active=0
  if command -v systemctl >/dev/null && [ -d /run/systemd/system ]; then
    if systemctl is-active --quiet farmacia-servidor; then active=1; systemctl stop farmacia-servidor; fi
  fi
  trap 'if [ "$active" = 1 ]; then systemctl start farmacia-servidor; fi' EXIT
  python3 /opt/farmacia-servidor/instalar_extensao.py
  if command -v systemctl >/dev/null && [ -d /run/systemd/system ]; then
    systemctl restart farmacia-servidor
    active=0
  fi
fi
''')
    (control / 'prerm').write_text('''#!/bin/sh
set -eu
if [ "$1" = remove ]; then
  python3 /opt/farmacia-servidor/instalar_extensao.py --remove
  if command -v systemctl >/dev/null && [ -d /run/systemd/system ]; then systemctl restart farmacia-servidor; fi
fi
''')
    for name in ('preinst', 'postinst', 'prerm'):
        (control / name).chmod(0o755)
    subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(root), str(output)], check=True)
print(output)
