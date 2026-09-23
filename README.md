# SISTFARMA · Dashboard 1.4.1

Continuação do Gestor e do Cliente Farmácia, com interface local em verde oliva e branco. O executável abre a interface no navegador e usa o servidor já existente. Os recursos visuais são incluídos no instalador e não dependem de internet/CDN.

## Uso

Instale `Sistema_Farmacia_Setup_1.4.1.exe` e escolha Gerente, Cliente ou ambos. O instalador mantém a identidade do programa anterior, sem incluir ou substituir o banco do servidor. O endereço padrão é `http://10.56.121.242:5000`; um endereço já salvo em `config_cliente.json` é preservado e pode ser alterado em **Configurações**.

O Gestor exige as contas existentes. Auditoria e Usuários são exclusivos do Gerente, também na ponte local. O Cliente mantém a solicitação por P/G, Nome de Guerra e OM. A versão clássica continua acessível em Configurações e com `--classico`.

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

A interface usa os contratos do servidor SQLite 1.3.0 e não modifica sua estrutura. A consulta de conferência semanal usa a seleção já realizada pelo servidor. O histórico antigo pode não incluir entradas por cadastro de lote; o gráfico mostra apenas os movimentos retornados e calcula o sentido por saldo anterior/final. Os comprovantes do Cliente HTML ficam disponíveis na sessão; a versão clássica mantém suas rotinas anteriores de arquivos.

Os testes de integração foram executados em uma base temporária, com o código do servidor 1.3.0 e dados fictícios. Não foi realizado acesso ao servidor operacional `10.56.121.242:5000`. A distribuição automática deste ramo gera instalador Windows x64. Os fontes continuam compatíveis com Python 3.8+ em Ubuntu/Mint; não há novo pacote DEB nesta entrega.

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
