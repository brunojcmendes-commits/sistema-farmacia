# SISTFARMA · Dashboard 1.4.4

Continuação do Gestor e do Cliente Farmácia, com interface local em verde oliva e branco. O executável abre a interface no navegador e usa o servidor já existente. Os recursos visuais são incluídos no instalador e não dependem de internet/CDN.

## Uso

Instale `Sistema_Farmacia_Setup_1.4.4.exe` e escolha Gerente, Cliente ou ambos. O instalador mantém a identidade do programa anterior, sem incluir ou substituir o banco do servidor. O endereço padrão é `http://10.56.121.242:5000`; um endereço já salvo em `config_cliente.json` é preservado e pode ser alterado em **Configurações**.

## Clientes Linux 1.4.4

`linux/build_clientes.py` gera quatro instaladores `.deb`: Ubuntu 22.04 e Mint 20.3, nas opções Online e Offline. Os dois usam a interface HTML atual do Cliente e guardam as configurações pessoais em `~/.local/share/farmacia-cliente`. A opção Online depende do Python 3 da distribuição. A opção Offline inclui um runtime Python 3.12 compatível com glibc 2.17 e biblioteca padrão, sem depender do Python instalado; necessita de navegador gráfico no desktop. Para gerar os pacotes offline, indique `SISTFARMA_PORTABLE_PYTHON` apontando para esse executável portátil. Instale Online com `sudo apt install ./arquivo.deb` e Offline com `sudo dpkg -i ./arquivo.deb`.

O servidor Ubuntu tem duas rotas: `server/build_full_deb.py` cria instalação completa para um computador novo; `server/build_deb.py` cria a atualização da instalação 1.3.0/1.4.x existente. São alternativas. O pacote completo não contém banco SQLite e a atualização faz backup antes de modificar o código do servidor existente. O Cliente precisa da rede local/VPN para alcançar o servidor em ambos os modos.

O Gestor exige as contas existentes. Auditoria e Usuários são exclusivos do Gerente, também na ponte local. O Cliente mantém a solicitação por P/G, Nome de Guerra e OM. A versão clássica continua acessível em Configurações e com `--classico`.

## Aguardando conferência / SISCOFIS

O campo **Localizador** registra onde está o produto (por exemplo, sala e prateleira). Ele pode ser pesquisado e editado no estoque disponível e em **Aguardando conferência / SISCOFIS**. Na liberação parcial, cada quantidade conserva o localizador informado naquele momento. No pedido do Gestor, **Ver pedido** mostra o localizador e a quantidade de cada lote que atendeu a solicitação, inclusive quando a saída veio de locais diferentes. O comprovante do Cliente continua sem expor o endereço interno do estoque. Lotes antigos sem localizador podem ser preenchidos pela edição.

No cadastro do lote, marque **Colocar produto em conferência / SISCOFIS**. O recebimento é armazenado em tabela separada no servidor: não entra no catálogo do Cliente, no estoque disponível, nas validades do estoque nem na conferência física semanal. Clientes clássicos também não conseguem consumir esse saldo.

Na nova aba, selecione um ou mais recebimentos e escolha **Liberar selecionados ao estoque**. Confirme as quantidades autorizadas (total ou parcial) e, opcionalmente, uma referência documental. A operação transfere o saldo em uma única transação e registra entrada, responsável e data. O saldo restante permanece bloqueado. Há busca, edição, cancelamento justificado, impressão e histórico de liberações. A seleção em lote abrange somente os itens visíveis selecionados na lista filtrada.

Gerente e Administrador podem cadastrar, editar e liberar. A Auditoria completa continua exclusiva do Gerente. Alterações concorrentes exigem atualizar a lista; repetição da mesma operação não duplica o saldo.

## Lotes externos

Na aba **Externos**, o Gestor pode editar material, lote, validade, estoque inicial, saldo atual e observação. As observações aparecem diretamente na lista e participam da busca. Edição e exclusão usam o ID do registro, para não afetar outro lote com o mesmo nome e número.

Validades seguem as faixas do estoque: até 90 dias (incluindo vencidos) e de 91 a 120 dias. Os alertas de validade contam somente lotes externos com saldo; **estoque baixo** indica 5 unidades ou menos, incluindo saldo zerado. A aba oferece filtros e contadores próprios, e o Painel mostra um resumo clicável desses alertas. Lotes externos permanecem separados do estoque disponível para pedidos.

### Atualização do servidor — necessária para o novo recurso

1. No computador Ubuntu/Mint que executa o **Servidor Farmácia**, instale `Servidor_Farmacia_Conferencia_SISCOFIS_1.4.4_all.deb` (`sudo dpkg -i Servidor_Farmacia_Conferencia_SISCOFIS_1.4.4_all.deb`). O servidor existente deve estar em `/opt/farmacia-servidor` e conter o módulo `recursos_estoque_130`.
2. O pacote faz backup consistente do SQLite e do código alterado em `/var/backups/sistfarma-siscofis/`, adiciona o módulo e reinicia o serviço `farmacia-servidor`. Não inclui banco vazio, não troca usuários e não precisa baixar dependências em Ubuntu 22.04/Mint compatível com Python 3.8+.
3. Nos computadores Windows, instale `Sistema_Farmacia_Setup_1.4.4.exe`. O endereço configurado continua preservado. Em servidor sem a extensão, o novo cadastro marcado é recusado com orientação de atualização; nunca cai silenciosamente no estoque disponível.

Este pacote DEB é uma extensão do **servidor**, não um instalador novo do Gestor/Cliente Linux. Um servidor com instalação/código diferente é recusado para preservar suas alterações. O módulo pode ser removido pelo gerenciador de pacotes: o estoque já liberado permanece e os registros pendentes continuam guardados no banco, indisponíveis para uso.

## Recursos integrados

- Indicadores clicáveis, estoque agrupado por produto e filtros por lote/categoria.
- Validades até 90 dias, 91–120 dias, acima de 120 dias e sem data válida; lotes vencidos são identificados. Os gráficos contam somente lotes com saldo.
- Movimentações registradas nos últimos sete dias e cinco produtos mais solicitados em 30 dias, excluindo pedidos/itens cancelados.
- Cadastro, edição e exclusão de lotes, seleção múltipla, comprimidos por cartela e transferências para Controlados/Externos pela API existente.
- Pedidos, detalhes, mudança de situação e estorno de cancelamento conforme as regras do servidor.
- Conferência semanal, histórico, ajustes e impressão.
- Auditoria, contas de administrador, estoque externo e relatórios com impressão/PDF pelo navegador.
- Cliente com busca local sem uma consulta por letra, carrinho e comprovante que distingue itens atendidos de itens cancelados por falta de estoque.

Falha de consulta aparece como indisponibilidade, nunca como saldo zero. Uma resposta incerta de operação não é repetida automaticamente. O fechamento da interface encerra o processo local após cinco minutos sem comunicação.

## Compatibilidade e limites

A interface mantém os contratos do servidor SQLite 1.3.0. A extensão SISCOFIS adiciona tabelas de recebimentos, liberações e controle de repetição, além de uma coluna `localizador` aos lotes e recebimentos existentes. Os registros e saldos existentes são preservados. A consulta de conferência semanal usa a seleção já realizada pelo servidor. O histórico antigo pode não incluir entradas por cadastro de lote; o gráfico mostra apenas os movimentos retornados e calcula o sentido por saldo anterior/final. Os comprovantes do Cliente HTML ficam disponíveis na sessão; a versão clássica mantém suas rotinas anteriores de arquivos.

Os testes de integração foram executados em uma base temporária, com o código do servidor 1.3.0 e dados fictícios. Não foi realizado acesso ao servidor operacional `10.56.121.242:5000`. A distribuição automática deste ramo gera instalador Windows x64. Os fontes continuam compatíveis com Python 3.8+ em Ubuntu/Mint; o DEB desta entrega atualiza somente o servidor para o recurso SISCOFIS.

## Desenvolvimento

```bash
python windows/src/gestor_html.py
python windows/src/cliente_html.py
python -m unittest discover -s tests -p 'test_*.py' -v
node tests/test_dashboard.mjs
```

Para teste local sem abrir navegador: `--no-browser --port PORTA --server http://IP:PORTA`. Nunca use a base operacional como base de testes.

Os clientes compartilham `windows/web` e `windows/src/desktop_bridge.py`. A ponte só escuta em `127.0.0.1`, mantém o token de autenticação no processo, verifica origem/chave local e encaminha apenas rotas permitidas. Configurações preservam as demais chaves do arquivo existente. Não há credenciais de produção no projeto.

O fluxo Windows executa os testes de cálculo/acesso e verifica a abertura dos dois executáveis e a presença dos recursos empacotados antes de gerar o instalador. Os direitos das fontes incluídas estão em `windows/web/fonts/LICENSE-DejaVu.txt`.

Os testes SISCOFIS exercitam a API real em banco temporário: bloqueio de retirada, liberação parcial, repetição, concorrência, rollback de lote, auditoria e atualização reversível do código. `server/base` contém a base 1.3.0 usada nesses testes; ela não é distribuída pelo DEB e não substitui o servidor instalado.
