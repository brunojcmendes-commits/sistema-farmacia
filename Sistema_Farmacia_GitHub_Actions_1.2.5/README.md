# Sistema Farmacia 1.2.5

Projeto do Gerente Farmacia e Cliente Farmacia para Windows.

## Gerar o instalador automaticamente

1. Abra a aba **Actions** do repositorio.
2. Selecione **Gerar instalador Windows**.
3. Clique em **Run workflow** e confirme.
4. Aguarde a execucao ficar verde.
5. Abra a execucao e baixe o artefato **Sistema-Farmacia-Windows-1.2.5**.
6. Extraia o ZIP baixado para obter `Sistema_Farmacia_Setup_1.2.5.exe`.

O instalador e produzido em um Windows Server 2022 pelo GitHub Actions. Os
aplicativos sao empacotados com PyInstaller e nao exigem Python no computador
do usuario. O Inno Setup cria atalhos e desinstalacao e permite escolher entre
Gerente Farmacia e Cliente Farmacia.

## Servidor

O servidor nao faz parte deste instalador. Os aplicativos usam por padrao:

`http://10.56.121.182:5000`

