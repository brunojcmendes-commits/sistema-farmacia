"""
Módulo compartilhado entre os dois clientes (Farmácia e Solicitação):
comunicação com o servidor via HTTP, configuração do endereço do servidor,
e geração de PDFs (comprovante de pedido e relatório de histórico).
"""

import os
import sys
import json
import unicodedata
from datetime import datetime

import requests

# --------------------------------------------------------------------------
# Configuração
# --------------------------------------------------------------------------

NOME_INSTITUICAO = "Farmácia - Controle de Estoque"

CATEGORIAS = [
    "Medicamentos Orais",
    "Medicamentos Injetáveis",
    "Pomadas",
    "Outros",
    "Material/Medicamento Odontológico",
    "Materiais",
    "Soro",
]

if os.name == "nt":
    _dados_padrao = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "FarmaciaCliente",
    )
else:
    _dados_padrao = os.path.join(os.path.expanduser("~"), ".local", "share", "farmacia-cliente")
DIRETORIO_DADOS = os.environ.get("FARMACIA_CLIENT_DATA_DIR") or _dados_padrao
os.makedirs(DIRETORIO_DADOS, exist_ok=True)
PASTA_COMPROVANTES = os.path.join(DIRETORIO_DADOS, "comprovantes")
CAMINHO_CONFIG = os.path.join(DIRETORIO_DADOS, "config_cliente.json")

PORTA_PADRAO = 5000
OM_LISTA = ["9º B Sau", "9º B Manut", "18º B TRNP", "Cmdo 9º GPT Log", "Cia Cmdo"]
TIMEOUT_SEGUNDOS = 5

FORMATO_DATA_HORA = "%d/%m/%Y %H:%M"
FORMATO_DATA = "%d/%m/%Y"

# Paleta verde-oliva escura aprovada na pré-visualização.
COR_PRIMARIA = "#3B4A2A"
COR_PRIMARIA_HOVER = "#52683A"
COR_DESTAQUE = "#8FA760"
COR_FUNDO = "#11180E"
COR_FUNDO_CARTAO = "#1D2918"
COR_TEXTO = "#F3F1E5"
COR_BORDA = "#334624"
COR_FONTE_CABECALHO = "#F7F6EC"
COR_ERRO = "#8C3B2E"
COR_OK = "#3B4A2A"
COR_URGENTE = "#B8860B"


# --------------------------------------------------------------------------
# Cliente de API
# --------------------------------------------------------------------------

def chave_ordenacao_texto(texto: str) -> str:
    """Chave de ordenação que ignora acentos, para 'Água' ficar junto de
    'Agua' na ordem alfabética (em vez de ir parar no final da lista)."""
    if not texto:
        return ""
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return sem_acento.lower()


class ErroConexao(Exception):
    pass


class EstoqueAPICliente:
    def __init__(self, servidor_url: str):
        self.servidor_url = servidor_url.rstrip("/")

    def _url(self, caminho):
        return f"{self.servidor_url}{caminho}"

    def login(self, usuario, senha):
        try:r=requests.post(self._url('/login'),json={'usuario':usuario,'senha':senha},timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException:raise ErroConexao('Não foi possível conectar ao servidor para entrar.')
        if r.status_code!=200:raise ErroConexao(r.json().get('erro','Usuário ou senha inválidos.'))
        dados=r.json();requests.set_bearer_token(dados['token']);return dados['usuario']

    def logout(self):
        try:requests.post(self._url('/logout'),timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException:pass
        requests.set_bearer_token('')

    def alterar_minha_senha(self,nova_senha):
        try:r=requests.post(self._url('/minha-senha'),json={'nova_senha':nova_senha},timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException:raise ErroConexao('Não foi possível alterar a senha.')
        if r.status_code!=200:raise ErroConexao(r.json().get('erro','Erro ao alterar a senha.'))
        return r.json()

    def listar_usuarios(self):
        try:r=requests.get(self._url('/usuarios'),timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException:raise ErroConexao('Não foi possível consultar usuários.')
        if r.status_code!=200:raise ErroConexao(r.json().get('erro','Acesso negado.'))
        return r.json()['usuarios']

    def criar_usuario(self,usuario,nome,senha,perfil='administrador'):
        try:r=requests.post(self._url('/usuarios'),json={'usuario':usuario,'nome':nome,'senha':senha,'perfil':'administrador'},timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException:raise ErroConexao('Não foi possível criar o usuário.')
        if r.status_code!=200:raise ErroConexao(r.json().get('erro','Erro ao criar usuário.'))
        return r.json()

    def ativar_usuario(self,uid,ativo):
        try:r=requests.post(self._url(f'/usuarios/{uid}/ativo'),json={'ativo':ativo},timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException:raise ErroConexao('Não foi possível atualizar o usuário.')
        if r.status_code!=200:raise ErroConexao(r.json().get('erro','Erro ao atualizar usuário.'))
        return r.json()

    def listar_auditoria(self,limite=500):
        try:r=requests.get(self._url('/auditoria'),params={'limite':limite},timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException:raise ErroConexao('Não foi possível consultar a auditoria.')
        if r.status_code!=200:raise ErroConexao(r.json().get('erro','Acesso negado.'))
        return r.json()['registros']

    def fazer_backup(self):
        try: r=requests.post(self._url("/backup"),timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException: raise ErroConexao("Não foi possível criar o backup.")
        if r.status_code!=200: raise ErroConexao(r.json().get("erro","Erro ao criar backup."))
        return r.json()

    def testar_conexao(self):
        try:
            r = requests.get(self._url("/ping"), timeout=TIMEOUT_SEGUNDOS)
            return r.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def listar_medicamentos(self, categoria: str):
        """Retorna lista agregada por medicamento: nome, estoque_total, validade_mais_proxima."""
        try:
            r = requests.get(self._url("/medicamentos"), params={"categoria": categoria}, timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException:
            raise ErroConexao(
                "Não foi possível conectar ao servidor. Verifique se ele está "
                "ligado e se o endereço configurado está correto."
            )
        if r.status_code != 200:
            raise ErroConexao(r.json().get("erro", "Erro ao consultar medicamentos."))
        return r.json()["medicamentos"]

    def listar_lotes(self, categoria: str, medicamento: str = None):
        params = {"categoria": categoria}
        if medicamento:
            params["medicamento"] = medicamento
        try:
            r = requests.get(self._url("/lotes"), params=params, timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException:
            raise ErroConexao("Não foi possível conectar ao servidor para consultar os lotes.")
        if r.status_code != 200:
            raise ErroConexao(r.json().get("erro", "Erro ao consultar lotes."))
        return r.json()["lotes"]

    def lote_existe(self, categoria: str, medicamento: str, ficha: str) -> bool:
        lotes = self.listar_lotes(categoria, medicamento)
        return any(str(l["ficha"]) == str(ficha) for l in lotes)

    def cadastrar_lote(self, categoria: str, medicamento: str, ficha: str,
                        estoque_inicial: float, validade: str = None,
                        comprimidos_cartela: int = None):
        """Retorna dict {mesclado, estoque_inicial, estoque_atual}. Se um lote
        com a mesma Categoria+Medicamento+Ficha+Validade já existir, o servidor
        soma a quantidade a ele em vez de criar um lote novo (mesclado=True).
        Mesma ficha com validade diferente cria um lote separado normalmente."""
        try:
            r = requests.post(
                self._url("/itens"),
                json={
                    "categoria": categoria, "medicamento": medicamento, "ficha": ficha,
                    "estoque_inicial": estoque_inicial, "validade": validade or "",
                    "comprimidos_cartela": comprimidos_cartela or "",
                },
                timeout=TIMEOUT_SEGUNDOS,
            )
        except requests.exceptions.RequestException:
            raise ErroConexao("Não foi possível conectar ao servidor para cadastrar o lote.")
        if r.status_code != 200:
            raise ErroConexao(r.json().get("erro", "Erro ao cadastrar lote."))
        return r.json()

    def excluir_lote(self, categoria: str, medicamento: str, ficha: str, validade: str = None, motivo: str = "Exclusão manual"):
        try:
            r = requests.delete(
                self._url("/itens"),
                json={
                    "categoria": categoria, "medicamento": medicamento,
                    "ficha": ficha, "validade": validade or "", "motivo": motivo,
                },
                timeout=TIMEOUT_SEGUNDOS,
            )
        except requests.exceptions.RequestException:
            raise ErroConexao("Não foi possível conectar ao servidor para excluir o lote.")
        if r.status_code != 200:
            raise ErroConexao(r.json().get("erro", "Erro ao excluir lote."))
        return True

    def editar_lote(self, categoria, medicamento, ficha, validade, novo_medicamento, nova_ficha, nova_validade, novo_estoque_inicial, novo_estoque_atual, novos_comprimidos_cartela=None):
        try:
            r=requests.put(self._url("/itens"),json={"categoria":categoria,"medicamento":medicamento,"ficha":ficha,"validade":validade or "","novo_medicamento":novo_medicamento,"nova_ficha":nova_ficha,"nova_validade":nova_validade or "","novo_estoque_inicial":novo_estoque_inicial,"novo_estoque_atual":novo_estoque_atual,"novos_comprimidos_cartela":novos_comprimidos_cartela or ""},timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException: raise ErroConexao("Não foi possível editar o lote.")
        if r.status_code!=200: raise ErroConexao(r.json().get("erro","Erro ao editar lote."))
        return r.json()

    def listar_lotes_excluidos(self):
        try: r=requests.get(self._url("/lotes-excluidos"),timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException: raise ErroConexao("Não foi possível consultar lotes excluídos.")
        if r.status_code!=200: raise ErroConexao(r.json().get("erro","Erro."))
        return r.json()["lotes"]

    def listar_apoio(self):
        try: r=requests.get(self._url("/apoio"),timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException: raise ErroConexao("Não foi possível consultar materiais de apoio.")
        if r.status_code!=200: raise ErroConexao(r.json().get("erro","Erro."))
        return r.json()["itens"]

    def cadastrar_apoio(self, material,lote,validade,estoque_inicial,observacao=""):
        try: r=requests.post(self._url("/apoio"),json={"material":material,"lote":lote,"validade":validade or "","estoque_inicial":estoque_inicial,"observacao":observacao},timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException: raise ErroConexao("Não foi possível cadastrar material de apoio.")
        if r.status_code!=200: raise ErroConexao(r.json().get("erro","Erro."))
        return r.json()

    def excluir_apoio(self,material,lote):
        try: r=requests.delete(self._url("/apoio"),json={"material":material,"lote":lote},timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException: raise ErroConexao("Não foi possível excluir material de apoio.")
        if r.status_code!=200: raise ErroConexao(r.json().get("erro","Erro."))
        return r.json()

    def listar_alertas_apoio(self,dias=90):
        try: r=requests.get(self._url("/apoio/alertas"),params={"dias":dias},timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException: raise ErroConexao("Não foi possível consultar validade do apoio.")
        if r.status_code!=200: raise ErroConexao(r.json().get("erro","Erro."))
        return r.json()["alertas"]

    def registrar_pedido(self, solicitante: str, itens: list, pg: str = "", om: str = ""):
        """itens: lista de {categoria, medicamento, quantidade_retirada}.
        Retorna o dict de resposta do servidor: {solicitante, itens: [{medicamento, categoria, movimentos}]}"""
        try:
            r = requests.post(
                self._url("/retiradas"),
                json={"solicitante": solicitante, "pg": pg, "om": om, "itens": itens},
                timeout=TIMEOUT_SEGUNDOS,
            )
        except requests.exceptions.RequestException:
            raise ErroConexao(
                "Não foi possível conectar ao servidor para registrar o pedido. "
                "O pedido NÃO foi salvo."
            )
        if r.status_code != 200:
            raise ErroConexao(r.json().get("erro", "Erro ao registrar pedido."))
        return r.json()

    def buscar_movimentacoes(self, categoria=None, data_inicio=None, data_fim=None,
                              ficha=None, medicamento=None, solicitante=None):
        params = {}
        if categoria:
            params["categoria"] = categoria
        if ficha:
            params["ficha"] = ficha
        if medicamento:
            params["medicamento"] = medicamento
        if solicitante:
            params["solicitante"] = solicitante
        if data_inicio:
            params["data_inicio"] = data_inicio.strftime(FORMATO_DATA)
        if data_fim:
            params["data_fim"] = data_fim.strftime(FORMATO_DATA)

        try:
            r = requests.get(self._url("/historico"), params=params, timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException:
            raise ErroConexao("Não foi possível conectar ao servidor para buscar o histórico.")
        if r.status_code != 200:
            raise ErroConexao(r.json().get("erro", "Erro ao buscar histórico."))
        return r.json()["registros"]

    def listar_alertas_validade(self, dias: int = 90):
        try:
            r = requests.get(self._url("/alertas"), params={"dias": dias}, timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException:
            raise ErroConexao("Não foi possível conectar ao servidor para consultar os alertas.")
        if r.status_code != 200:
            raise ErroConexao(r.json().get("erro", "Erro ao consultar alertas."))
        return r.json()["alertas"]

    def obter_notificacoes(self, desde: int = None):
        """Consulta a fila de pedidos recentes. desde=None sincroniza o
        ponto de partida (retorna só o último id, sem trazer histórico).
        desde=<id> retorna os eventos novos a partir daquele id."""
        params = {}
        if desde is not None:
            params["desde"] = desde
        try:
            r = requests.get(self._url("/notificacoes"), params=params, timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException:
            raise ErroConexao("Não foi possível conectar ao servidor para consultar notificações.")
        if r.status_code != 200:
            raise ErroConexao(r.json().get("erro", "Erro ao consultar notificações."))
        return r.json()

    def listar_pedidos(self, conferido: bool = None, status: str = None):
        """Lista pedidos agrupados. Mantém o parâmetro antigo por compatibilidade."""
        params = {}
        if status:
            params["status"] = status
        elif conferido is True:
            params["status"] = "ENTREGUE"
        elif conferido is False:
            params["status"] = "PENDENTES"
        try:
            r = requests.get(self._url("/pedidos"), params=params, timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException:
            raise ErroConexao("Não foi possível conectar ao servidor para consultar os pedidos.")
        if r.status_code != 200:
            raise ErroConexao(r.json().get("erro", "Erro ao consultar pedidos."))
        return r.json()["pedidos"]

    def obter_pedido(self, pedido_id: int):
        try:r=requests.get(self._url(f"/pedidos/{pedido_id}"),timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException:raise ErroConexao("Não foi possível consultar os itens do pedido.")
        if r.status_code!=200:raise ErroConexao(r.json().get("erro","Erro ao consultar pedido."))
        return r.json()["pedido"]

    def alterar_status_pedido(self, pedido_id: int, status: str):
        try:r=requests.post(self._url(f"/pedidos/{pedido_id}/status"),json={"status":status},timeout=TIMEOUT_SEGUNDOS)
        except requests.exceptions.RequestException:raise ErroConexao("Não foi possível atualizar a situação do pedido.")
        if r.status_code!=200:raise ErroConexao(r.json().get("erro","Erro ao atualizar pedido."))
        return r.json()

    def marcar_pedido_conferido(self, pedido_id: int, conferido: bool):
        try:
            r = requests.post(
                self._url(f"/pedidos/{pedido_id}/conferir"),
                json={"conferido": conferido}, timeout=TIMEOUT_SEGUNDOS,
            )
        except requests.exceptions.RequestException:
            raise ErroConexao("Não foi possível conectar ao servidor para atualizar o pedido.")
        if r.status_code != 200:
            raise ErroConexao(r.json().get("erro", "Erro ao atualizar o pedido."))
        return r.json()


def tocar_bipe_local():
    """Toca um bipe neste computador (usado pelo Cliente Farmácia ao
    receber um aviso de pedido novo). Windows usa winsound; em outros
    sistemas cai para o beep de terminal como alternativa."""
    try:
        import winsound
        winsound.Beep(900, 150)
        winsound.Beep(1300, 150)
    except ImportError:
        print("\a", end="", flush=True)
    except RuntimeError:
        print("\a", end="", flush=True)


# --------------------------------------------------------------------------
# Configuração do endereço do servidor
# --------------------------------------------------------------------------

def carregar_config():
    if os.path.exists(CAMINHO_CONFIG):
        try:
            with open(CAMINHO_CONFIG, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def salvar_config(config: dict):
    with open(CAMINHO_CONFIG, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def montar_url(endereco: str) -> str:
    endereco = endereco.strip()
    if not endereco:
        return ""
    if not endereco.startswith("http://") and not endereco.startswith("https://"):
        endereco = f"http://{endereco}"
    if ":" not in endereco.split("//", 1)[1]:
        endereco = f"{endereco}:{PORTA_PADRAO}"
    return endereco


# --------------------------------------------------------------------------
# Geração de PDF
# --------------------------------------------------------------------------


def _pdf_escape(text):
    return str(text).replace('\\','\\\\').replace('(','\\(').replace(')','\\)')

def _write_simple_pdf(path, title, lines):
    # PDF mínimo, sem dependências externas; compatível com leitores comuns.
    from textwrap import wrap
    pages=[]; page=[]
    for line in [title, ''] + [str(x) for x in lines]:
        for part in wrap(line, 105) or ['']:
            if len(page)>=48: pages.append(page); page=[]
            page.append(part)
    pages.append(page)
    objs=[]; page_ids=[]; content_ids=[]
    for pg in pages:
        commands=['BT','/F1 9 Tf','40 800 Td']
        for i,line in enumerate(pg):
            if i: commands.append('0 -15 Td')
            commands.append(f'({_pdf_escape(line)}) Tj')
        commands.append('ET'); stream='\n'.join(commands).encode('latin-1','replace')
        content_ids.append(len(objs)+1); objs.append((b'<< /Length %d >>\nstream\n'%len(stream)+stream+b'\nendstream',False))
        page_ids.append(len(objs)+1); objs.append((b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents %d 0 R /Resources << /Font << /F1 3 0 R >> >> >>'%content_ids[-1],False))
    # Rebuild with stable object numbers: catalog=1, pages=2, font=3, then page/content pairs
    out=bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n'); offsets=[0]
    page_nums=[]; content_nums=[]; num=4
    for _ in pages: page_nums.append(num); content_nums.append(num+1); num+=2
    objects={1:b'<< /Type /Catalog /Pages 2 0 R >>',2:b'<< /Type /Pages /Kids ['+b' '.join(f'{n} 0 R'.encode() for n in page_nums)+b'] /Count '+str(len(pages)).encode()+b' >>',3:b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'}
    for idx,pg in enumerate(pages):
        commands=['BT','/F1 9 Tf','40 800 Td']
        for i,line in enumerate(pg):
            if i: commands.append('0 -15 Td')
            commands.append(f'({_pdf_escape(line)}) Tj')
        commands.append('ET'); stream='\n'.join(commands).encode('latin-1','replace')
        objects[page_nums[idx]]=f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {content_nums[idx]} 0 R /Resources << /Font << /F1 3 0 R >> >> >>'.encode()
        objects[content_nums[idx]]=b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream'
    for n in range(1,num):
        offsets.append(len(out)); out += f'{n} 0 obj\n'.encode()+objects[n]+b'\nendobj\n'
    xref=len(out); out += f'xref\n0 {num}\n0000000000 65535 f \n'.encode()
    for off in offsets[1:]: out += f'{off:010d} 00000 n \n'.encode()
    out += f'trailer\n<< /Size {num} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    with open(path,'wb') as f:f.write(out)

def gerar_pdf_comprovante_pedido(caminho_pdf: str, solicitante: str, resultado_itens: list):
    lines=[f'Solicitante: {solicitante}', f'Data/Hora: {datetime.now().strftime(FORMATO_DATA_HORA)}','']
    for item in resultado_itens:
        for m in item.get('movimentos',[]):
            lines.append(f"{m.get('medicamento','')} | {m.get('categoria','')} | Ficha: {m.get('ficha','')} | Retirado: {m.get('retirada','')}")
    lines += ['', '________________________________________    ________________________________________','Responsável pela retirada                         Responsável pela farmácia']
    _write_simple_pdf(caminho_pdf,'FARMÁCIA - COMPROVANTE DE SOLICITAÇÃO DE ESTOQUE',lines)

def gerar_pdf_relatorio(caminho_pdf: str, titulo_filtros: str, registros: list):
    lines=[f'Relatório de Movimentações — {titulo_filtros}','Categoria | Data | Medicamento | Ficha | Solicitante | Retirada | Ant. | Final']
    for r in registros:
        lines.append(f"{r.get('categoria','')} | {r.get('data','')} | {r.get('medicamento','')} | {r.get('ficha','')} | {r.get('solicitante','-')} | {r.get('retirada','')} | {r.get('estoque_anterior','')} | {r.get('estoque_final','')}")
    lines.append(f'Total de registros: {len(registros)} — gerado em {datetime.now().strftime(FORMATO_DATA_HORA)}')
    _write_simple_pdf(caminho_pdf,'FARMÁCIA - RELATÓRIO DE MOVIMENTAÇÕES',lines)

def agregar_consumo_por_medicamento(registros: list) -> list:
    """Soma a quantidade retirada por Categoria+Medicamento a partir de uma
    lista de registros de histórico (mesmo formato de buscar_movimentacoes).
    Retorna lista ordenada da maior para a menor quantidade total."""
    agregados = {}
    for r in registros:
        chave = (r["categoria"], r["medicamento"])
        info = agregados.setdefault(chave, {
            "categoria": r["categoria"], "medicamento": r["medicamento"],
            "quantidade_total": 0, "num_retiradas": 0,
        })
        info["quantidade_total"] += r["retirada"]
        info["num_retiradas"] += 1
    return sorted(agregados.values(), key=lambda x: x["quantidade_total"], reverse=True)


def gerar_pdf_resumo_consumo(caminho_pdf: str, titulo_filtros: str, registros: list):
    resumo=agregar_consumo_por_medicamento(registros)
    lines=[f'Resumo de Consumo por Medicamento — {titulo_filtros}','Categoria | Medicamento | Quantidade Total | Nº Retiradas']
    for item in resumo:
        lines.append(f"{item['categoria']} | {item['medicamento']} | {item['quantidade_total']} | {item['num_retiradas']}")
    total=sum(item['quantidade_total'] for item in resumo)
    lines.append(f'{len(resumo)} medicamento(s)/material(is) — {total} unidade(s) retiradas — gerado em {datetime.now().strftime(FORMATO_DATA_HORA)}')
    _write_simple_pdf(caminho_pdf,'FARMÁCIA - RESUMO DE CONSUMO',lines)
