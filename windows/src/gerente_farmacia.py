"""
Gerente Farmácia
------------------
Interface para a equipe da farmácia: cadastrar medicamentos/materiais
(lotes), consultar histórico de retiradas, gerar relatórios em PDF e ver
alertas de validade. Fala com o servidor pela rede.

Requisitos:
    pip install requests reportlab --break-system-packages
"""

import os
import threading
from datetime import datetime, time

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

from farmacia_api import (
    NOME_INSTITUICAO, CATEGORIAS, PASTA_COMPROVANTES,
    FORMATO_DATA_HORA, FORMATO_DATA,
    COR_PRIMARIA, COR_PRIMARIA_HOVER, COR_DESTAQUE, COR_FUNDO, COR_FUNDO_CARTAO,
    COR_TEXTO, COR_BORDA, COR_FONTE_CABECALHO, COR_ERRO, COR_URGENTE,
    EstoqueAPICliente, ErroConexao,
    carregar_config, salvar_config, montar_url,
    gerar_pdf_relatorio, gerar_pdf_resumo_consumo, tocar_bipe_local, chave_ordenacao_texto,
)

INTERVALO_NOTIFICACOES_MS = 5000  # a cada 5s consulta se chegou pedido novo
VERSAO_APP = "1.2.5"
SERVIDOR_CENTRAL_PADRAO = "http://10.56.121.182:5000"

def configurar_rolagem_tabela(frame, tree):
    """Adiciona rolagem vertical e horizontal sem reduzir a área útil da tabela."""
    frame.grid_rowconfigure(0,weight=1);frame.grid_columnconfigure(0,weight=1)
    tree.grid(row=0,column=0,sticky="nsew")
    vertical=ttk.Scrollbar(frame,orient="vertical",command=tree.yview)
    horizontal=ttk.Scrollbar(frame,orient="horizontal",command=tree.xview)
    vertical.grid(row=0,column=1,sticky="ns");horizontal.grid(row=1,column=0,sticky="ew")
    tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)

class BotaoArredondado(tk.Canvas):
    """Botão leve, sem dependências externas, com cantos arredondados."""
    def __init__(self,parent,text,command,cor=COR_PRIMARIA,cor_hover=COR_PRIMARIA_HOVER,**kwargs):
        super().__init__(parent,height=36,highlightthickness=0,bg=parent.cget('bg'),cursor='hand2',**kwargs)
        self.command=command;self.cor=cor;self.cor_hover=cor_hover;self.texto=text
        self.bind('<Configure>',lambda e:self._desenhar(self.cor));self.bind('<Enter>',lambda e:self._desenhar(self.cor_hover));self.bind('<Leave>',lambda e:self._desenhar(self.cor));self.bind('<Button-1>',lambda e:self.command())
    def _desenhar(self,cor):
        self.delete('all');w=max(self.winfo_width(),80);h=34;r=14
        self.create_arc(1,1,2*r,2*r,start=90,extent=180,fill=cor,outline=cor)
        self.create_arc(w-2*r-1,1,w-1,2*r,start=-90,extent=180,fill=cor,outline=cor)
        self.create_rectangle(r,1,w-r,h,fill=cor,outline=cor)
        self.create_text(w/2,h/2,text=self.texto,fill='white',font=('Segoe UI',9,'bold'))

class CartaoPainel(tk.Canvas):
    def __init__(self,parent,titulo,variavel,command,**kwargs):
        super().__init__(parent,height=108,highlightthickness=0,bg=COR_FUNDO,cursor='hand2',**kwargs)
        self.titulo=titulo;self.variavel=variavel;self.command=command
        self.bind('<Configure>',self._desenhar);self.bind('<Button-1>',lambda e:self.command())
        self.variavel.trace_add('write',lambda *_:self._desenhar())
    def _desenhar(self,event=None):
        self.delete('all');w=max(self.winfo_width(),120);h=104;r=16;fill=COR_FUNDO_CARTAO
        self.create_arc(1,1,2*r,2*r,start=90,extent=90,fill=fill,outline=COR_BORDA)
        self.create_arc(w-2*r-1,1,w-1,2*r,start=0,extent=90,fill=fill,outline=COR_BORDA)
        self.create_arc(1,h-2*r-1,2*r,h-1,start=180,extent=90,fill=fill,outline=COR_BORDA)
        self.create_arc(w-2*r-1,h-2*r-1,w-1,h-1,start=270,extent=90,fill=fill,outline=COR_BORDA)
        self.create_rectangle(r,1,w-r,h-1,fill=fill,outline=fill);self.create_rectangle(1,r,w-1,h-r,fill=fill,outline=fill)
        self.create_text(w/2,30,text=self.titulo,fill=COR_TEXTO,font=('Segoe UI',9,'bold'),width=max(80,w-18))
        self.create_text(w/2,70,text=self.variavel.get(),fill=COR_PRIMARIA,font=('Segoe UI',22,'bold'))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        if os.name != "nt":
            try:self.tk.call("tk", "scaling", 1.0)
            except tk.TclError:pass
        self.title(f"Gerente Farmácia — versão {VERSAO_APP}")
        try:
            self._icone_app=tk.PhotoImage(file=os.path.join(os.path.dirname(os.path.abspath(__file__)),"Gerente_Farmacia.png"));self.iconphoto(True,self._icone_app)
        except Exception:pass
        largura_tela, altura_tela = self.winfo_screenwidth(), self.winfo_screenheight()
        largura = min(1280, max(760, largura_tela - 30))
        altura = min(800, max(520, altura_tela - 90))
        self.geometry(f"{largura}x{altura}+0+0")
        self.minsize(min(760, largura_tela - 20), min(520, altura_tela - 70))
        self.configure(bg=COR_FUNDO)

        os.makedirs(PASTA_COMPROVANTES, exist_ok=True)

        self._resultado_busca = []
        self.api = None
        self._ultimo_notificacao_id = None
        self._servidor_local_thread = None
        self._servidor_local_iniciado = False
        self.usuario_logado = None

        self._configurar_estilo()
        self._montar_interface()

        self._carregar_ou_pedir_servidor()

    # ------------------------------ estilo ------------------------------

    def _configurar_estilo(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=COR_FUNDO)
        style.configure("Cartao.TFrame", background=COR_FUNDO_CARTAO, relief="flat")
        style.configure("TLabel", background=COR_FUNDO, foreground=COR_TEXTO, font=("Segoe UI", 10))
        style.configure("Cartao.TLabel", background=COR_FUNDO_CARTAO, foreground=COR_TEXTO, font=("Segoe UI", 10))
        compacto = self.winfo_screenwidth() < 1100
        style.configure(
            "Titulo.TLabel", background=COR_PRIMARIA, foreground=COR_FONTE_CABECALHO,
            font=("Segoe UI", 13 if compacto else 16, "bold"), padding=(10 if compacto else 16, 8 if compacto else 12),
        )
        style.configure("Rodape.TLabel", background=COR_FUNDO, foreground="#AAB79A", font=("Segoe UI", 8))
        style.configure(
            "TButton", background=COR_PRIMARIA, foreground="white",
            font=("Segoe UI", 8 if compacto else 10, "bold"), padding=5 if compacto else 8, borderwidth=0,
        )
        style.map("TButton", background=[("active", COR_PRIMARIA_HOVER), ("disabled", COR_BORDA)])
        style.configure(
            "Secundario.TButton", background=COR_DESTAQUE, foreground="#11180E",
            font=("Segoe UI", 8 if compacto else 9, "bold"), padding=4 if compacto else 6,
        )
        style.map("Secundario.TButton", background=[("active", "#9CAE6C")])

        style.configure("TCombobox", padding=4, fieldbackground="#F7F6EC", foreground="#242B1C")
        style.configure("TEntry", padding=4, fieldbackground="#F7F6EC", foreground="#242B1C")

        style.configure("TNotebook", background=COR_FUNDO, borderwidth=0, tabmargins=(8, 8, 8, 0))
        style.configure(
            "TNotebook.Tab", background=COR_FUNDO_CARTAO, foreground=COR_TEXTO,
            font=("Segoe UI", 8 if compacto else 10, "bold"), padding=(7 if compacto else 16, 5 if compacto else 8),
        )
        style.map("TNotebook.Tab", background=[("selected", COR_PRIMARIA)], foreground=[("selected", "white")])

        style.configure(
            "Treeview", background="#FFFFFF", fieldbackground="#FFFFFF", foreground="#242B1C",
            rowheight=24, font=("Segoe UI", 9),
        )
        style.configure("Treeview.Heading", background=COR_PRIMARIA, foreground="white", font=("Segoe UI", 9, "bold"))
        style.map("Treeview.Heading", background=[("active", COR_PRIMARIA_HOVER)])
        style.map(
            "Treeview",
            background=[("selected", COR_DESTAQUE), ("!selected", "#FFFFFF")],
            foreground=[("selected", "#FFFFFF"), ("!selected", "#242B1C")],
        )

    # ---------------------------- construção -----------------------------

    def _montar_interface(self):
        cabecalho = tk.Frame(self, bg=COR_PRIMARIA)
        cabecalho.pack(fill="x")
        ttk.Label(cabecalho, text=f"GERENTE FARMÁCIA   ·   v{VERSAO_APP}", style="Titulo.TLabel").pack(anchor="w")

        barra_status = ttk.Frame(self, style="TFrame")
        barra_status.pack(fill="x", padx=12, pady=(8, 0))
        self.lbl_status_servidor = ttk.Label(barra_status, text="Servidor: não configurado", style="TLabel")
        self.lbl_status_servidor.pack(side="left")
        self.lbl_usuario = ttk.Label(barra_status, text="Acesso: aguardando login", style="TLabel")
        self.lbl_usuario.pack(side="left", padx=(18,0))
        barra_acoes=tk.Frame(self,bg=COR_FUNDO);barra_acoes.pack(fill="x",padx=12,pady=(6,0))
        self.btn_entrar=BotaoArredondado(barra_acoes,text="Entrar",command=self._entrar_ou_configurar,width=90);self.btn_entrar.pack(side='left')
        self.btn_auditoria=BotaoArredondado(barra_acoes,text="Auditoria",command=self._abrir_auditoria,width=100)
        self.btn_usuarios=BotaoArredondado(barra_acoes,text="Usuários",command=self._abrir_usuarios,width=90)
        self.btn_sair=BotaoArredondado(barra_acoes,text="Sair",command=self._logout,width=65)
        BotaoArredondado(barra_acoes,text="Configurar servidor",command=self._configurar_servidor,width=140).pack(side="right")
        BotaoArredondado(barra_acoes,text="Testar conexão",command=self._testar_conexao_manual,width=115).pack(side="right",padx=(0,6))

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=12, pady=12)

        aba_dashboard = ttk.Frame(notebook, style="TFrame")
        aba_cadastro = ttk.Frame(notebook, style="TFrame")
        aba_pedidos = ttk.Frame(notebook, style="TFrame")
        aba_historico = ttk.Frame(notebook, style="TFrame")
        aba_alertas = ttk.Frame(notebook, style="TFrame")
        aba_apoio = ttk.Frame(notebook, style="TFrame")
        aba_excluidos = ttk.Frame(notebook, style="TFrame")
        self.aba_auditoria = ttk.Frame(notebook,style="TFrame")
        notebook.add(aba_dashboard, text="  Painel  ")
        self.aba_lotes_index = notebook.index("end")
        notebook.add(aba_cadastro, text="  Lotes  ")
        self.aba_pedidos_index = notebook.index("end")
        notebook.add(aba_pedidos, text="  Pedidos  ")
        notebook.add(aba_historico, text="  Histórico e Relatórios  ")
        self.aba_alertas_index = notebook.index("end")
        notebook.add(aba_alertas, text="  Alertas de Validade  ")
        self.aba_externos_index = notebook.index("end")
        notebook.add(aba_apoio, text="  Lotes Externos  ")
        notebook.add(aba_excluidos, text="  Lotes Excluídos  ")
        self.notebook = notebook

        self._montar_aba_dashboard(aba_dashboard)
        self._montar_aba_cadastro(aba_cadastro)
        self._montar_aba_pedidos(aba_pedidos)
        self._montar_aba_historico(aba_historico)
        self._montar_aba_alertas(aba_alertas)
        self._montar_aba_apoio(aba_apoio)
        self._montar_aba_excluidos(aba_excluidos)
        self._montar_aba_auditoria(self.aba_auditoria)

        ttk.Label(self, text=f"Comprovantes salvos em: {PASTA_COMPROVANTES}", style="Rodape.TLabel").pack(
            anchor="w", padx=16, pady=(0, 8)
        )

    def _montar_aba_dashboard(self, aba):
        topo=ttk.Frame(aba,style="Cartao.TFrame",padding=16); topo.pack(fill="x",padx=8,pady=8)
        ttk.Label(topo,text="Visão geral do estoque",style="Cartao.TLabel",font=("Segoe UI",14,"bold")).pack(side="left")
        ttk.Button(topo,text="Atualizar painel",command=self._atualizar_dashboard).pack(side="right")
        ttk.Button(topo,text="Criar backup",style="Secundario.TButton",command=self._backup).pack(side="right",padx=8)
        self.dashboard_cards=tk.Frame(aba,bg=COR_FUNDO); self.dashboard_cards.pack(fill="x",padx=8,pady=8)
        self.dashboard_vars=[tk.StringVar(value="—") for _ in range(5)]
        titulos=["Lotes cadastrados","Lotes sem estoque","Validades críticas","Pedidos pendentes","Lotes externos / críticos"]
        comandos=[self._abrir_lotes_dashboard,self._mostrar_lotes_sem_estoque,self._abrir_validades_dashboard,self._abrir_pedidos_dashboard,self._abrir_externos_dashboard]
        for i,(t,cmd) in enumerate(zip(titulos,comandos)):
            c=CartaoPainel(self.dashboard_cards,t,self.dashboard_vars[i],cmd);c.grid(row=0,column=i,sticky="nsew",padx=5);self.dashboard_cards.grid_columnconfigure(i,weight=1)
        self._atualizar_dashboard()

    def _atualizar_dashboard(self):
        if not self.api:return
        try:
            lotes=[]
            for cat in CATEGORIAS:lotes.extend(self.api.listar_lotes(cat))
            alertas=self.api.listar_alertas_validade(120); pedidos=self.api.listar_pedidos(False);externos=self.api.listar_apoio();alertas_ext=self.api.listar_alertas_apoio(120)
            self._lotes_dashboard=lotes
            self.dashboard_vars[0].set(len(lotes)); self.dashboard_vars[1].set(sum(1 for l in lotes if float(l.get("estoque_atual") or 0)<=0)); self.dashboard_vars[2].set(len(alertas)); self.dashboard_vars[3].set(len(pedidos));self.dashboard_vars[4].set(f"{len(externos)} / {len(alertas_ext)}")
        except Exception: pass

    def _abrir_lotes_dashboard(self):self.notebook.select(self.aba_lotes_index)
    def _abrir_validades_dashboard(self):self._buscar_alertas();self.notebook.select(self.aba_alertas_index)
    def _abrir_pedidos_dashboard(self):self._buscar_pedidos();self.notebook.select(self.aba_pedidos_index)
    def _abrir_externos_dashboard(self):self._buscar_apoio();self.notebook.select(self.aba_externos_index)

    def _mostrar_lotes_sem_estoque(self):
        lotes=[l for l in getattr(self,'_lotes_dashboard',[]) if float(l.get('estoque_atual') or 0)<=0]
        janela=tk.Toplevel(self);janela.title("Lotes sem estoque");janela.geometry("820x430");janela.minsize(600,320);janela.configure(bg=COR_FUNDO);janela.transient(self)
        ttk.Label(janela,text="Lotes sem estoque — selecione e abra para editar ou excluir",style="TLabel",font=("Segoe UI",11,"bold")).pack(anchor="w",padx=12,pady=12)
        tabela=ttk.Frame(janela);tabela.pack(fill='both',expand=True,padx=12)
        cols=('categoria','med','ficha','validade','estoque');tree=ttk.Treeview(tabela,columns=cols,show='headings',selectmode='browse')
        for c,t,w in zip(cols,['Categoria','Medicamento/Material','Ficha','Validade','Estoque'],[190,300,100,110,80]):tree.heading(c,text=t);tree.column(c,width=w,anchor='center')
        for idx,l in enumerate(lotes):tree.insert('','end',iid=str(idx),values=(l['categoria'],l['medicamento'],l['ficha'],l.get('validade') or '-',l.get('estoque_atual',0)))
        configurar_rolagem_tabela(tabela,tree)
        def abrir():
            sel=tree.selection()
            if not sel:messagebox.showwarning('Lotes sem estoque','Selecione um lote.',parent=janela);return
            l=lotes[int(sel[0])];self.var_categoria.set(l['categoria']);self._atualizar_lista_lotes(l['categoria']);self.notebook.select(self.aba_lotes_index);janela.destroy()
            for iid in self.tree_lotes.get_children():
                v=self.tree_lotes.item(iid,'values')
                if str(v[0])==str(l['medicamento']) and str(v[1])==str(l['ficha']):self.tree_lotes.selection_set(iid);self.tree_lotes.focus(iid);self.tree_lotes.see(iid);break
        botoes=ttk.Frame(janela,style='TFrame');botoes.pack(fill='x',padx=12,pady=10)
        ttk.Button(botoes,text='← Voltar / Fechar',style='Secundario.TButton',command=janela.destroy).pack(side='right')
        ttk.Button(botoes,text='Abrir lote para editar ou excluir',command=abrir).pack(side='right',padx=(0,8));tree.bind('<Double-1>',lambda e:abrir())

    def _backup(self):
        if not self._servidor_configurado():return
        try:r=self.api.fazer_backup(); messagebox.showinfo("Backup",f"Backup criado no servidor:\n{r.get('arquivo','')}")
        except ErroConexao as e:messagebox.showerror("Backup",str(e))

    # ------------------------ aba: pedidos agrupados e fluxo de atendimento -----------------------

    def _montar_aba_pedidos(self, aba):
        topo = ttk.Frame(aba, style="Cartao.TFrame", padding=16)
        topo.pack(fill="x", padx=8, pady=(8, 4))

        ttk.Label(topo,text="Pedidos recebidos — selecione um pedido para consultar ou avançar a situação",style="Cartao.TLabel",font=("Segoe UI",10,"bold")).pack(side="left")

        self.var_filtro_pedidos = tk.StringVar(value="Pendentes")
        combo_filtro_pedidos = ttk.Combobox(
            topo, textvariable=self.var_filtro_pedidos,
            values=["Todos","Pendentes","Novo","Em separação","Pronto","Entregue","Cancelado"],state="readonly",width=16,
        )
        combo_filtro_pedidos.pack(side="right", padx=(0, 8))
        combo_filtro_pedidos.bind("<<ComboboxSelected>>", lambda e: self._buscar_pedidos())
        ttk.Button(topo, text="Atualizar", style="Secundario.TButton", command=self._buscar_pedidos).pack(
            side="right", padx=(0, 8)
        )

        tabela_frame = ttk.Frame(aba, style="TFrame")
        tabela_frame.pack(fill="both", expand=True, padx=8, pady=4)

        colunas=("numero","data","nome","pg","om","itens","status","atualizado_por")
        titulos = {
            "numero":"Pedido","data":"Data","nome":"Solicitante","pg":"P/G","om":"OM","itens":"Itens","status":"Situação","atualizado_por":"Última alteração",
        }
        larguras = {
            "numero":70,"data":120,"nome":190,"pg":80,"om":150,"itens":65,"status":125,"atualizado_por":150,
        }

        self.tree_pedidos = ttk.Treeview(tabela_frame, columns=colunas, show="headings", selectmode="browse")
        for col in colunas:
            self.tree_pedidos.heading(col, text=titulos[col])
            self.tree_pedidos.column(col, width=larguras[col], anchor="center")
        configurar_rolagem_tabela(tabela_frame,self.tree_pedidos)

        self.tree_pedidos.tag_configure("ENTREGUE",foreground="#58723a")
        self.tree_pedidos.tag_configure("CANCELADO",foreground=COR_ERRO)
        self.tree_pedidos.tag_configure("PRONTO",foreground="#8a6500")
        self.tree_pedidos.bind("<Double-1>",lambda e:self._ver_itens_pedido())

        rodape = ttk.Frame(aba, style="TFrame")
        rodape.pack(fill="x", padx=8, pady=(4, 8))
        self.lbl_total_pedidos = ttk.Label(rodape, text="", style="TLabel")
        self.lbl_total_pedidos.pack(side="left")
        ttk.Button(rodape,text="Cancelar pedido",style="Secundario.TButton",command=lambda:self._alterar_status_pedido("CANCELADO")).pack(side="right",padx=(6,0))
        ttk.Button(rodape,text="Marcar entregue",command=lambda:self._alterar_status_pedido("ENTREGUE")).pack(side="right",padx=(6,0))
        ttk.Button(rodape,text="Marcar pronto",style="Secundario.TButton",command=lambda:self._alterar_status_pedido("PRONTO")).pack(side="right",padx=(6,0))
        ttk.Button(rodape,text="Iniciar separação",style="Secundario.TButton",command=lambda:self._alterar_status_pedido("EM_SEPARACAO")).pack(side="right",padx=(6,0))
        ttk.Button(rodape,text="Ver itens",style="Secundario.TButton",command=self._ver_itens_pedido).pack(side="right",padx=(6,0))

    def _filtro_pedidos_atual(self):
        return {"Todos":None,"Pendentes":"PENDENTES","Novo":"NOVO","Em separação":"EM_SEPARACAO","Pronto":"PRONTO","Entregue":"ENTREGUE","Cancelado":"CANCELADO"}.get(self.var_filtro_pedidos.get())

    def _buscar_pedidos(self):
        if not self.api:
            return
        try:
            pedidos=self.api.listar_pedidos(status=self._filtro_pedidos_atual())
        except ErroConexao as e:
            messagebox.showerror("Erro de conexão", str(e))
            return

        for item in self.tree_pedidos.get_children():
            self.tree_pedidos.delete(item)

        self._pedidos_por_id={}
        nomes_status={"NOVO":"Novo","EM_SEPARACAO":"Em separação","PRONTO":"Pronto","ENTREGUE":"Entregue","CANCELADO":"Cancelado"}
        for p in pedidos:
            self._pedidos_por_id[str(p['id'])]=p
            self.tree_pedidos.insert(
                "","end",iid=str(p["id"]),values=(f"#{p['id']}",p["data"],p.get("nome",p.get("solicitante","")),p.get("pg",""),p.get("om",""),p.get("quantidade_itens",len(p.get('itens',[]))),nomes_status.get(p['status'],p['status']),p.get('atualizado_por','')),tags=(p['status'],),
            )

        self.lbl_total_pedidos.configure(text=f"{len(pedidos)} pedido(s) — {self.var_filtro_pedidos.get()}")

    def _pedido_selecionado(self):
        sel=self.tree_pedidos.selection()
        if not sel:messagebox.showwarning("Pedidos","Selecione um pedido na lista.");return None
        return self._pedidos_por_id.get(sel[0])

    def _alterar_status_pedido(self,status):
        pedido=self._pedido_selecionado()
        if not pedido:return
        nomes={"EM_SEPARACAO":"Em separação","PRONTO":"Pronto","ENTREGUE":"Entregue","CANCELADO":"Cancelado"}
        if status=='CANCELADO' and not messagebox.askyesno("Cancelar pedido",f"Cancelar o pedido #{pedido['id']}?\n\nO estoque será devolvido automaticamente aos lotes utilizados."):return
        try:self.api.alterar_status_pedido(pedido['id'],status)
        except ErroConexao as e:messagebox.showerror("Pedido",str(e));return
        self._buscar_pedidos();self._atualizar_dashboard();messagebox.showinfo("Pedido",f"Pedido #{pedido['id']} atualizado para: {nomes.get(status,status)}.")

    def _ver_itens_pedido(self):
        pedido=self._pedido_selecionado()
        if not pedido:return
        try:pedido=self.api.obter_pedido(pedido['id'])
        except ErroConexao as e:messagebox.showerror("Pedido",str(e));return
        janela=tk.Toplevel(self);janela.title(f"Itens do pedido #{pedido['id']}");janela.geometry("820x430");janela.minsize(600,320);janela.configure(bg=COR_FUNDO);janela.transient(self)
        cab=ttk.Frame(janela,style="Cartao.TFrame",padding=14);cab.pack(fill="x",padx=10,pady=10)
        ttk.Label(cab,text=f"Pedido #{pedido['id']} — {pedido['solicitante']} — {pedido.get('pg','')} — {pedido.get('om','')}",style="Cartao.TLabel",font=("Segoe UI",11,"bold")).pack(anchor="w")
        ttk.Label(cab,text=f"Solicitado em {pedido['data']} | Situação: {pedido['status'].replace('_',' ')} | Última alteração: {pedido.get('atualizado_por','')} em {pedido.get('atualizado_em','')}",style="Cartao.TLabel").pack(anchor="w",pady=(5,0))
        tabela=ttk.Frame(janela);tabela.pack(fill="both",expand=True,padx=10,pady=(0,10))
        cols=("categoria","medicamento","fichas","quantidade","situacao");tree=ttk.Treeview(tabela,columns=cols,show="headings")
        for c,t,w in zip(cols,["Categoria","Medicamento/Produto","Ficha(s)/Lote(s)","Quantidade","Situação"],[170,270,140,90,170]):tree.heading(c,text=t);tree.column(c,width=w,anchor="center")
        for item in pedido.get('itens',[]):
            situacao='Atendido' if item.get('status')=='ATENDIDO' else 'Cancelado — sem estoque'
            tree.insert("","end",values=(item['categoria'],item['medicamento'],item.get('fichas',''),item['quantidade'],situacao),tags=('cancelado_item',) if item.get('status')!='ATENDIDO' else ())
        tree.tag_configure('cancelado_item',foreground=COR_ERRO)
        configurar_rolagem_tabela(tabela,tree);ttk.Button(janela,text="Fechar",command=janela.destroy).pack(pady=(0,10))

    def _montar_aba_cadastro(self, aba):
        cartao = ttk.Frame(aba, style="Cartao.TFrame", padding=24)
        cartao.pack(fill="x", padx=8, pady=8, anchor="n")

        ttk.Label(cartao, text="Categoria:", style="Cartao.TLabel").grid(row=0, column=0, sticky="w", pady=6)
        self.var_categoria = tk.StringVar()
        combo_categoria = ttk.Combobox(
            cartao, textvariable=self.var_categoria, values=CATEGORIAS, state="readonly", width=36
        )
        combo_categoria.grid(row=0, column=1, sticky="w", pady=6)

        ttk.Label(cartao, text="Medicamento/Material:", style="Cartao.TLabel").grid(row=1, column=0, sticky="w", pady=6)
        self.var_medicamento = tk.StringVar()
        ttk.Entry(cartao, textvariable=self.var_medicamento, width=38).grid(row=1, column=1, sticky="w", pady=6)

        ttk.Label(cartao, text="Data de validade (dd/mm/aaaa):", style="Cartao.TLabel").grid(row=2, column=0, sticky="w", pady=6)
        self.var_validade = tk.StringVar()
        ttk.Entry(cartao, textvariable=self.var_validade, width=38).grid(row=2, column=1, sticky="w", pady=6)
        ttk.Label(
            cartao, text="(deixe em branco se não aplicável, ex: alguns materiais)",
            style="Cartao.TLabel", font=("Segoe UI", 8),
        ).grid(row=3, column=1, sticky="w")

        ttk.Label(cartao, text="Número da ficha:", style="Cartao.TLabel").grid(row=4, column=0, sticky="w", pady=6)
        self.var_ficha = tk.StringVar()
        ttk.Entry(cartao, textvariable=self.var_ficha, width=38).grid(row=4, column=1, sticky="w", pady=6)
        ttk.Label(
            cartao, text="(identifica este lote — pode repetir o medicamento com fichas diferentes)",
            style="Cartao.TLabel", font=("Segoe UI", 8),
        ).grid(row=5, column=1, sticky="w")

        ttk.Label(cartao, text="Estoque inicial:", style="Cartao.TLabel").grid(row=6, column=0, sticky="w", pady=6)
        self.var_estoque_inicial = tk.StringVar()
        ttk.Entry(cartao, textvariable=self.var_estoque_inicial, width=38).grid(row=6, column=1, sticky="w", pady=6)

        ttk.Button(cartao, text="Cadastrar Lote", command=self._cadastrar_lote).grid(
            row=7, column=0, columnspan=2, pady=(18, 0), sticky="ew"
        )

        # Lista de lotes já cadastrados na categoria (ajuda a evitar duplicidade e a conferir)
        linha_titulo_lista = ttk.Frame(aba, style="TFrame")
        linha_titulo_lista.pack(fill="x", padx=8, pady=(12, 4))
        ttk.Label(linha_titulo_lista, text="Lotes cadastrados na categoria selecionada:", style="TLabel",
                  font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Button(linha_titulo_lista, text="Editar lote", style="Secundario.TButton", command=self._editar_lote_selecionado).pack(side="right")
        ttk.Button(
            linha_titulo_lista, text="Excluir lote selecionado", style="Secundario.TButton",
            command=self._excluir_lote_selecionado,
        ).pack(side="right", padx=(0,8))
        ttk.Label(linha_titulo_lista, text="Pesquisar:", style="TLabel").pack(side="left", padx=(20,6))
        self.var_busca_lote = tk.StringVar()
        ent_busca = ttk.Entry(linha_titulo_lista, textvariable=self.var_busca_lote, width=28)
        ent_busca.pack(side="left")
        ent_busca.bind("<KeyRelease>", lambda e: self._atualizar_lista_lotes(self.var_categoria.get(), self.var_busca_lote.get().strip()))
        ttk.Button(
            linha_titulo_lista, text="Atualizar lista", style="Secundario.TButton",
            command=lambda: self._atualizar_lista_lotes(self.var_categoria.get()),
        ).pack(side="right", padx=(0, 8))

        frame_lista = ttk.Frame(aba, style="TFrame")
        frame_lista.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        colunas = ("medicamento", "ficha", "validade", "inicial", "atual")
        titulos = {"medicamento": "Medicamento", "ficha": "Ficha", "validade": "Validade",
                   "inicial": "Estoque Inicial", "atual": "Estoque Atual"}
        larguras = {"medicamento": 320, "ficha": 110, "validade": 110, "inicial": 110, "atual": 110}
        self.tree_lotes = ttk.Treeview(frame_lista, columns=colunas, show="headings", selectmode="browse")
        for col in colunas:
            self.tree_lotes.heading(col, text=titulos[col])
            self.tree_lotes.column(col, width=larguras[col], anchor="w" if col == "medicamento" else "center")
        configurar_rolagem_tabela(frame_lista,self.tree_lotes)
        self.tree_lotes.tag_configure("vermelho",foreground=COR_ERRO)
        self.tree_lotes.tag_configure("laranja",foreground="#D2691E")
        self.tree_lotes.tag_configure("verde",foreground="#2E7D32")

        combo_categoria.bind("<<ComboboxSelected>>", self._on_categoria_cadastro_selecionada)

    def _on_categoria_cadastro_selecionada(self, event=None):
        if not self.api:
            return
        categoria = self.var_categoria.get()
        self._atualizar_lista_lotes(categoria)

    def _atualizar_lista_lotes(self, categoria, busca=""):
        if not categoria:
            messagebox.showwarning("Atenção", "Selecione uma categoria primeiro.")
            return
        try:
            lotes = self.api.listar_lotes(categoria)
        except ErroConexao as e:
            messagebox.showerror("Erro de conexão", str(e))
            return
        for item in self.tree_lotes.get_children():
            self.tree_lotes.delete(item)
        termo=chave_ordenacao_texto(busca)
        for l in sorted(lotes, key=lambda x: (chave_ordenacao_texto(x["medicamento"]), str(x["ficha"]))):
            if termo and termo not in chave_ordenacao_texto(str(l["medicamento"])) and termo not in chave_ordenacao_texto(str(l["ficha"])):
                continue
            tag=""
            if l.get("validade"):
                try:
                    dias=(datetime.strptime(l["validade"],FORMATO_DATA).date()-datetime.now().date()).days
                    tag="vermelho" if dias<=90 else "laranja" if dias<=120 else "verde"
                except ValueError:pass
            self.tree_lotes.insert(
                "", "end",
                values=(l["medicamento"], l["ficha"], l["validade"] or "-", l["estoque_inicial"], l["estoque_atual"]),
                tags=(tag,) if tag else (),
            )

    def _excluir_lote_selecionado(self):
        if not self._servidor_configurado():
            return
        selecionado = self.tree_lotes.selection()
        if not selecionado:
            messagebox.showwarning("Atenção", "Selecione um lote na lista primeiro.")
            return

        valores = self.tree_lotes.item(selecionado[0], "values")
        medicamento, ficha, validade_exibida, estoque_inicial, estoque_atual = valores
        validade = None if validade_exibida == "-" else validade_exibida
        categoria = self.var_categoria.get()

        aviso_extra = ""
        try:
            if float(estoque_atual) > 0:
                aviso_extra = (
                    f"\n\nATENÇÃO: esse lote ainda tem {estoque_atual} em estoque. "
                    "Excluir remove o lote da lista, mas não desfaz retiradas já feitas dele."
                )
        except (TypeError, ValueError):
            pass

        confirmar = messagebox.askyesno(
            "Excluir lote",
            f"Excluir o lote de '{medicamento}' (ficha {ficha}"
            + (f", validade {validade}" if validade else "")
            + f")?{aviso_extra}",
        )
        if not confirmar:
            return

        motivo = simpledialog.askstring("Motivo da exclusão", "Informe o motivo da exclusão:", initialvalue="Exclusão manual", parent=self) or "Exclusão manual"
        try:
            self.api.excluir_lote(categoria, medicamento, ficha, validade, motivo)
        except ErroConexao as e:
            messagebox.showerror("Erro de conexão", str(e))
            return

        messagebox.showinfo("Lote excluído", f"Lote de '{medicamento}' (ficha {ficha}) excluído.")
        self._atualizar_lista_lotes(categoria)

    def _editar_lote_selecionado(self):
        if not self._servidor_configurado(): return
        sel=self.tree_lotes.selection()
        if not sel: messagebox.showwarning("Atenção","Selecione um lote."); return
        vals=self.tree_lotes.item(sel[0],"values")
        categoria=self.var_categoria.get(); medicamento,ficha,validade,ini,atual=vals
        if validade=="-": validade=""
        janela=tk.Toplevel(self); janela.title("Editar lote"); janela.configure(bg=COR_FUNDO_CARTAO); janela.transient(self); janela.grab_set()
        campos=[("Medicamento/Material",medicamento),("Ficha",ficha),("Validade",validade),("Estoque Inicial",ini),("Estoque Atual",atual)]
        vars_=[]
        for i,(rot,val) in enumerate(campos):
            ttk.Label(janela,text=rot,style="Cartao.TLabel").grid(row=i,column=0,sticky="w",padx=12,pady=6)
            v=tk.StringVar(value=str(val)); vars_.append(v); ttk.Entry(janela,textvariable=v,width=34).grid(row=i,column=1,padx=12,pady=6)
        def salvar():
            try:
                if vars_[2].get().strip(): datetime.strptime(vars_[2].get().strip(),FORMATO_DATA)
                ni=float(vars_[3].get().replace(",",".")); na=float(vars_[4].get().replace(",","."))
                self.api.editar_lote(categoria,medicamento,ficha,validade,vars_[0].get().strip(),vars_[1].get().strip(),vars_[2].get().strip(),ni,na)
            except ValueError: messagebox.showerror("Erro","Verifique data e estoques.",parent=janela); return
            except ErroConexao as e: messagebox.showerror("Erro",str(e),parent=janela); return
            janela.destroy(); self._atualizar_lista_lotes(categoria,self.var_busca_lote.get().strip()); messagebox.showinfo("Sucesso","Lote atualizado.")
        ttk.Button(janela,text="← Voltar / Fechar",style="Secundario.TButton",command=janela.destroy).grid(row=5,column=0,pady=12,padx=(12,6),sticky="ew")
        ttk.Button(janela,text="Salvar alterações",command=salvar).grid(row=5,column=1,pady=12,padx=(6,12),sticky="ew")

    def _cadastrar_lote(self):
        if not self._servidor_configurado():
            return
        categoria = self.var_categoria.get()
        medicamento = self.var_medicamento.get().strip()
        validade = self.var_validade.get().strip()
        ficha = self.var_ficha.get().strip()
        estoque_str = self.var_estoque_inicial.get().strip()

        if not categoria:
            messagebox.showwarning("Atenção", "Selecione a categoria.")
            return
        if not medicamento:
            messagebox.showwarning("Atenção", "Informe o medicamento/material.")
            return
        if not ficha:
            messagebox.showwarning("Atenção", "Informe o número da ficha (identifica o lote).")
            return
        if validade:
            try:
                datetime.strptime(validade, FORMATO_DATA)
            except ValueError:
                messagebox.showerror("Erro", "Data de validade inválida. Use o formato dd/mm/aaaa.")
                return
        try:
            estoque_inicial = float(estoque_str.replace(",", "."))
        except ValueError:
            messagebox.showerror("Erro", "Estoque inicial inválido.")
            return

        try:
            resultado = self.api.cadastrar_lote(categoria, medicamento, ficha, estoque_inicial, validade or None)
        except ErroConexao as e:
            messagebox.showerror("Erro de conexão", str(e))
            return

        if resultado.get("mesclado"):
            messagebox.showinfo(
                "Estoque somado",
                f"Já existia um lote de '{medicamento}' com a ficha {ficha} e a mesma validade — "
                f"somei {estoque_inicial} a ele.\nEstoque atual desse lote agora: {resultado['estoque_atual']}.",
            )
        else:
            messagebox.showinfo(
                "Sucesso",
                f"Lote de '{medicamento}' (ficha {ficha}) cadastrado com {estoque_inicial} em estoque.",
            )
        self.var_medicamento.set("")
        self.var_validade.set("")
        self.var_ficha.set("")
        self.var_estoque_inicial.set("")
        self._atualizar_lista_lotes(categoria)

    # ------------------------ aba: histórico / relatórios -----------------------

    def _montar_aba_historico(self, aba):
        filtros = ttk.Frame(aba, style="Cartao.TFrame", padding=16)
        filtros.pack(fill="x", padx=8, pady=(8, 4))

        ttk.Label(filtros, text="Categoria:", style="Cartao.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.var_filtro_categoria = tk.StringVar(value="Todas")
        ttk.Combobox(
            filtros, textvariable=self.var_filtro_categoria, values=["Todas"] + CATEGORIAS,
            state="readonly", width=18,
        ).grid(row=0, column=1, sticky="w", padx=(0, 12))

        ttk.Label(filtros, text="Nº Ficha:", style="Cartao.TLabel").grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.var_filtro_ficha = tk.StringVar()
        ttk.Entry(filtros, textvariable=self.var_filtro_ficha, width=10).grid(row=0, column=3, sticky="w", padx=(0, 12))

        ttk.Label(filtros, text="Medicamento:", style="Cartao.TLabel").grid(row=0, column=4, sticky="w", padx=(0, 6))
        self.var_filtro_medicamento = tk.StringVar()
        ttk.Entry(filtros, textvariable=self.var_filtro_medicamento, width=16).grid(row=0, column=5, sticky="w", padx=(0, 12))

        ttk.Label(filtros, text="Solicitante:", style="Cartao.TLabel").grid(row=0, column=6, sticky="w", padx=(0, 6))
        self.var_filtro_solicitante = tk.StringVar()
        ttk.Entry(filtros, textvariable=self.var_filtro_solicitante, width=16).grid(row=0, column=7, sticky="w")

        ttk.Label(filtros, text="Data início (dd/mm/aaaa):", style="Cartao.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )
        self.var_filtro_data_inicio = tk.StringVar()
        ttk.Entry(filtros, textvariable=self.var_filtro_data_inicio, width=14).grid(row=1, column=1, sticky="e", pady=(10, 0))

        ttk.Label(filtros, text="Data fim (dd/mm/aaaa):", style="Cartao.TLabel").grid(
            row=1, column=2, columnspan=2, sticky="w", pady=(10, 0)
        )
        self.var_filtro_data_fim = tk.StringVar()
        ttk.Entry(filtros, textvariable=self.var_filtro_data_fim, width=14).grid(row=1, column=3, sticky="w", pady=(10, 0))

        botoes_filtro = ttk.Frame(filtros, style="Cartao.TFrame")
        botoes_filtro.grid(row=1, column=6, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(botoes_filtro, text="Buscar", command=self._buscar_historico).pack(side="left", padx=(0, 6))
        ttk.Button(
            botoes_filtro, text="Limpar", style="Secundario.TButton", command=self._limpar_filtros_historico
        ).pack(side="left")

        tabela_frame = ttk.Frame(aba, style="TFrame")
        tabela_frame.pack(fill="both", expand=True, padx=8, pady=4)

        colunas = ("categoria", "data", "medicamento", "ficha", "solicitante", "retirada", "anterior", "final")
        titulos = {
            "categoria": "Categoria", "data": "Data", "medicamento": "Medicamento", "ficha": "Nº Ficha",
            "solicitante": "Solicitante", "retirada": "Retirada", "anterior": "Estoque Ant.", "final": "Estoque Final",
        }
        larguras = {
            "categoria": 130, "data": 110, "medicamento": 260, "ficha": 70,
            "solicitante": 120, "retirada": 70, "anterior": 90, "final": 90,
        }

        self.tree = ttk.Treeview(tabela_frame, columns=colunas, show="headings", selectmode="browse")
        for col in colunas:
            self.tree.heading(col, text=titulos[col])
            self.tree.column(col, width=larguras[col], anchor="center")
        configurar_rolagem_tabela(tabela_frame,self.tree)

        acoes = ttk.Frame(aba, style="TFrame")
        acoes.pack(fill="x", padx=8, pady=(4, 8))
        ttk.Button(acoes, text="Exportar relatório filtrado em PDF", command=self._exportar_relatorio_pdf).pack(side="left")
        ttk.Button(
            acoes, text="Exportar resumo por medicamento em PDF", style="Secundario.TButton",
            command=self._exportar_resumo_consumo_pdf,
        ).pack(side="left", padx=(8, 0))

        self.lbl_total_resultados = ttk.Label(acoes, text="", style="TLabel")
        self.lbl_total_resultados.pack(side="right")

    def _montar_aba_alertas(self, aba):
        topo = ttk.Frame(aba, style="Cartao.TFrame", padding=16)
        topo.pack(fill="x", padx=8, pady=(8, 4))

        ttk.Label(
            topo, text="Alertas exibidos: até 90 dias vermelho | 91 a 120 dias laranja", style="Cartao.TLabel",
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left")
        ttk.Button(topo, text="Atualizar", command=self._buscar_alertas).pack(side="right")

        tabela_frame = ttk.Frame(aba, style="TFrame")
        tabela_frame.pack(fill="both", expand=True, padx=8, pady=4)

        colunas = ("categoria", "medicamento", "ficha", "validade", "situacao", "estoque")
        titulos = {
            "categoria": "Categoria", "medicamento": "Medicamento", "ficha": "Ficha",
            "validade": "Validade", "situacao": "Situação", "estoque": "Estoque",
        }
        larguras = {"categoria": 150, "medicamento": 280, "ficha": 90, "validade": 100, "situacao": 170, "estoque": 90}

        self.tree_alertas = ttk.Treeview(tabela_frame, columns=colunas, show="headings", selectmode="browse")
        for col in colunas:
            self.tree_alertas.heading(col, text=titulos[col])
            self.tree_alertas.column(col, width=larguras[col], anchor="center")
        configurar_rolagem_tabela(tabela_frame,self.tree_alertas)

        self.tree_alertas.tag_configure("vermelho", foreground=COR_ERRO)
        self.tree_alertas.tag_configure("laranja", foreground="#D2691E")
        self.tree_alertas.tag_configure("verde", foreground="#2E7D32")

        rodape = ttk.Frame(aba, style="TFrame")
        rodape.pack(fill="x", padx=8, pady=(4, 8))
        self.lbl_total_alertas = ttk.Label(rodape, text="", style="TLabel")
        self.lbl_total_alertas.pack(side="left")

    def _montar_aba_apoio(self, aba):
        topo=ttk.Frame(aba,style="Cartao.TFrame",padding=14); topo.pack(fill="x",padx=8,pady=8)
        ttk.Label(topo,text="LOTES EXTERNOS — controle de materiais recebidos externamente, estoque e validade",style="Cartao.TLabel",font=("Segoe UI",11,"bold")).grid(row=0,column=0,columnspan=7,sticky="w",padx=4,pady=(0,8))
        labels=[("Material",22),("Lote",13),("Validade",11),("Estoque",9),("Observação",18)]
        self.vars_apoio=[]
        for i,(lab,w) in enumerate(labels):
            ttk.Label(topo,text=lab,style="Cartao.TLabel").grid(row=1,column=i,sticky="w",padx=4)
            v=tk.StringVar(); self.vars_apoio.append(v); ttk.Entry(topo,textvariable=v,width=w).grid(row=2,column=i,padx=4,pady=4)
        ttk.Button(topo,text="Cadastrar lote externo",command=self._cadastrar_apoio).grid(row=2,column=5,padx=6)
        ttk.Button(topo,text="Atualizar",style="Secundario.TButton",command=self._buscar_apoio).grid(row=2,column=6)
        frame=ttk.Frame(aba); frame.pack(fill="both",expand=True,padx=8,pady=4)
        cols=("material","lote","validade","ini","atual","obs"); self.tree_apoio=ttk.Treeview(frame,columns=cols,show="headings")
        for c,t,w in zip(cols,["Material","Lote","Validade","Estoque Inicial","Estoque Atual","Observação"],[280,120,110,120,110,280]): self.tree_apoio.heading(c,text=t); self.tree_apoio.column(c,width=w,anchor="center")
        configurar_rolagem_tabela(frame,self.tree_apoio)
        self.tree_apoio.tag_configure('vermelho',foreground=COR_ERRO);self.tree_apoio.tag_configure('laranja',foreground='#D2691E');self.tree_apoio.tag_configure('verde',foreground='#2E7D32')
        rodape=ttk.Frame(aba);rodape.pack(fill='x',padx=8,pady=(4,8));self.lbl_externos=ttk.Label(rodape,text='');self.lbl_externos.pack(side='left');ttk.Button(rodape,text='Excluir lote externo selecionado',style='Secundario.TButton',command=self._excluir_apoio_selecionado).pack(side='right')
        self._buscar_apoio()

    def _cadastrar_apoio(self):
        if not self._servidor_configurado(): return
        material,lote,validade,estoque,obs=[v.get().strip() for v in self.vars_apoio]
        try: datetime.strptime(validade,FORMATO_DATA) if validade else None; estoque=float(estoque.replace(",",".")); self.api.cadastrar_apoio(material,lote,validade,estoque,obs)
        except (ValueError,ErroConexao) as e: messagebox.showerror("Erro",str(e)); return
        for v in self.vars_apoio:v.set("")
        self._buscar_apoio()

    def _buscar_apoio(self):
        if not self.api:return
        try: itens=self.api.listar_apoio()
        except ErroConexao:return
        for i in self.tree_apoio.get_children():self.tree_apoio.delete(i)
        hoje=datetime.now().date();criticos=0
        for x in itens:
            tag=''
            if x['Validade']:
                try:
                    dias=(datetime.strptime(x['Validade'],FORMATO_DATA).date()-hoje).days
                    if dias<=90:tag='vermelho';criticos+=1
                    elif dias<=120:tag='laranja';criticos+=1
                    else:tag='verde'
                except ValueError:pass
            self.tree_apoio.insert("", "end", values=(x["Material"],x["Lote"],x["Validade"] or "-",x["Estoque Inicial"],x["Estoque Atual"],x["Observação"] or ""),tags=(tag,) if tag else ())
        self.lbl_externos.configure(text=f'{len(itens)} lote(s) externo(s) — {criticos} validade(s) crítica(s)')

    def _excluir_apoio_selecionado(self):
        sel=self.tree_apoio.selection()
        if not sel:messagebox.showwarning('Lotes Externos','Selecione um lote externo.');return
        valores=self.tree_apoio.item(sel[0],'values');material,lote=valores[0],valores[1]
        if not messagebox.askyesno('Excluir lote externo',f"Excluir '{material}', lote {lote}?"):return
        try:self.api.excluir_apoio(material,lote)
        except ErroConexao as e:messagebox.showerror('Erro',str(e));return
        self._buscar_apoio();self._atualizar_dashboard()

    def _montar_aba_excluidos(self, aba):
        topo=ttk.Frame(aba,style="Cartao.TFrame",padding=12); topo.pack(fill="x",padx=8,pady=8)
        ttk.Label(topo,text="Histórico de lotes excluídos — os dados não são apagados, apenas arquivados.",style="Cartao.TLabel",font=("Segoe UI",10,"bold")).pack(side="left")
        ttk.Button(topo,text="Atualizar",command=self._buscar_excluidos).pack(side="right")
        frame=ttk.Frame(aba); frame.pack(fill="both",expand=True,padx=8,pady=4)
        cols=("data","categoria","med","ficha","validade","ini","atual","motivo"); self.tree_excluidos=ttk.Treeview(frame,columns=cols,show="headings")
        for c,t,w in zip(cols,["Data","Categoria","Medicamento","Ficha","Validade","Inicial","Atual","Motivo"],[130,160,260,100,100,90,90,240]):self.tree_excluidos.heading(c,text=t);self.tree_excluidos.column(c,width=w,anchor="center")
        configurar_rolagem_tabela(frame,self.tree_excluidos)
        self._buscar_excluidos()

    def _buscar_excluidos(self):
        if not self.api:return
        try: itens=self.api.listar_lotes_excluidos()
        except ErroConexao:return
        for i in self.tree_excluidos.get_children():self.tree_excluidos.delete(i)
        for x in itens:self.tree_excluidos.insert("","end",values=tuple(x.get(k,"") or "" for k in ["Data Exclusão","Categoria","Medicamento","Ficha","Validade","Estoque Inicial","Estoque Atual","Motivo"]))

    # ------------------------------ servidor / conexão --------------------------------

    def _carregar_ou_pedir_servidor(self):
        config = carregar_config()
        servidor_url = str(config.get("servidor_url", "")).strip()
        if not servidor_url or "127.0.0.1" in servidor_url or "localhost" in servidor_url.lower():
            servidor_url = SERVIDOR_CENTRAL_PADRAO
            config["servidor_url"] = servidor_url
            config["iniciar_servidor_local"] = False
            salvar_config(config)
        self.api = EstoqueAPICliente(servidor_url)
        self._atualizar_status_servidor(testar=True)

    def _iniciar_servidor_local(self, perguntar_auto=False):
        """Inicia o Flask em segundo plano e usa este computador como servidor.

        O cliente Farmácia continua sendo a janela principal; não é necessário
        abrir uma segunda janela de servidor.
        """
        if self._servidor_local_iniciado:
            self._atualizar_status_servidor(testar=True, avisar=True)
            return

        try:
            # Se outro servidor local já estiver rodando, a thread falhará ao
            # tentar ocupar a porta. O teste abaixo evita iniciar duas vezes
            # dentro do próprio aplicativo.
            def callback_log(msg):
                print(f"[Servidor local] {msg}")

            def rodar():
                try:
                    servidor_estoque.iniciar_servidor(log_callback=callback_log)
                except Exception as exc:
                    print(f"[Servidor local] erro ao iniciar: {exc}")

            self._servidor_local_thread = threading.Thread(
                target=rodar, name="ServidorEstoqueLocal", daemon=True
            )
            self._servidor_local_thread.start()
            self._servidor_local_iniciado = True

            url_local = montar_url(f"127.0.0.1:{servidor_estoque.PORTA}")
            self.api = EstoqueAPICliente(url_local)
            config = carregar_config()
            config.update({
                "servidor_url": url_local,
                "iniciar_servidor_local": True,
            })
            salvar_config(config)
            self.lbl_status_servidor.configure(
                text="Servidor: iniciando neste computador..."
            )

            # O Flask precisa de alguns instantes para subir. Fazemos novas
            # tentativas sem bloquear a interface.
            self._aguardar_servidor_local(0)
        except Exception as exc:
            messagebox.showerror("Servidor local", f"Não foi possível iniciar o servidor local.\n\n{exc}")

    def _aguardar_servidor_local(self, tentativa):
        if not self._servidor_local_iniciado or not self.api:
            return
        if self.api.testar_conexao():
            self._atualizar_status_servidor(testar=True)
            return
        if tentativa < 20:
            self.after(250, lambda: self._aguardar_servidor_local(tentativa + 1))
        else:
            self.lbl_status_servidor.configure(
                text="Servidor local: não foi possível confirmar a inicialização"
            )
            messagebox.showerror(
                "Servidor local",
                "O servidor local não respondeu na porta 5000.\n\n"
                "Verifique se a porta está livre e se o firewall do Windows/Linux não está bloqueando o programa."
            )


    def _abrir_configuracoes(self):
        """Abre as configurações do Gerente Farmácia."""
        config = carregar_config()
        janela = tk.Toplevel(self)
        janela.title("Configurações — Gerente Farmácia")
        janela.configure(bg=COR_FUNDO_CARTAO)
        janela.resizable(False, False)
        janela.transient(self)
        janela.grab_set()

        tk.Label(
            janela, text="Configurações do Gerente Farmácia", bg=COR_PRIMARIA, fg="white",
            font=("Segoe UI", 13, "bold"), anchor="w", padx=14, pady=10,
        ).pack(fill="x")

        corpo = tk.Frame(janela, bg=COR_FUNDO_CARTAO)
        corpo.pack(fill="both", expand=True, padx=18, pady=16)

        var_auto = tk.BooleanVar(value=bool(config.get("iniciar_servidor_local", False)))
        ttk.Checkbutton(
            corpo, text="Iniciar servidor automaticamente ao abrir o Gerente Farmácia",
            variable=var_auto,
        ).pack(anchor="w", pady=(0, 8))

        tk.Label(
            corpo,
            text="Quando ativada, esta opção inicia o servidor local em segundo plano\n"
                 "e conecta automaticamente o Gerente Farmácia a este computador.",
            bg=COR_FUNDO_CARTAO, fg=COR_TEXTO, justify="left",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(0, 14))

        status = "ATIVADO" if var_auto.get() else "DESATIVADO"
        lbl = tk.Label(corpo, text=f"Inicialização automática: {status}",
                       bg=COR_FUNDO_CARTAO, fg=COR_TEXTO, font=("Segoe UI", 9, "bold"))
        lbl.pack(anchor="w", pady=(0, 12))

        def atualizar_status(*_):
            lbl.configure(text=f"Inicialização automática: {'ATIVADO' if var_auto.get() else 'DESATIVADO'}")
        var_auto.trace_add("write", atualizar_status)

        botoes = tk.Frame(corpo, bg=COR_FUNDO_CARTAO)
        botoes.pack(fill="x")

        def salvar():
            nova = carregar_config()
            nova["iniciar_servidor_local"] = bool(var_auto.get())
            # Se o usuário desativar, mantém o endereço salvo para uso manual.
            salvar_config(nova)
            janela.destroy()
            self.lbl_status_servidor.configure(
                text=("Servidor: inicialização automática ativada"
                      if var_auto.get() else "Servidor: inicialização automática desativada")
                if not self.api else self.lbl_status_servidor.cget("text")
            )

        ttk.Button(botoes, text="Cancelar", style="Secundario.TButton",
                   command=janela.destroy).pack(side="right")
        ttk.Button(botoes, text="💾 Salvar", command=salvar).pack(side="right", padx=(0, 8))

        janela.update_idletasks()
        largura, altura = janela.winfo_reqwidth(), janela.winfo_reqheight()
        x = self.winfo_rootx() + (self.winfo_width() - largura) // 2
        y = self.winfo_rooty() + (self.winfo_height() - altura) // 2
        janela.geometry(f"{largura}x{altura}+{max(0,x)}+{max(0,y)}")

    def _configurar_servidor(self):
        atual = self.api.servidor_url if self.api else ""
        endereco = simpledialog.askstring(
            "Endereço do servidor",
            "Informe o endereço do computador-servidor (IP mostrado na janela do servidor).\n"
            "Servidor central: 10.56.121.182:5000",
            initialvalue=atual.replace("http://", "").replace("https://", ""),
            parent=self,
        )
        if not endereco:
            return
        url = montar_url(endereco)
        self.api = EstoqueAPICliente(url)
        config = carregar_config()
        config["servidor_url"] = url
        salvar_config(config)
        self._atualizar_status_servidor(testar=True)

    def _testar_conexao_manual(self):
        self._atualizar_status_servidor(testar=True, avisar=True)

    def _atualizar_status_servidor(self, testar=False, avisar=False):
        if not self.api:
            self.lbl_status_servidor.configure(text="Servidor: não configurado")
            return
        if testar:
            ok = self.api.testar_conexao()
            situacao = "Conectado" if ok else "Offline / inacessível"
            self.lbl_status_servidor.configure(text=f"Servidor: {self.api.servidor_url}  —  {situacao}")
            if ok:
                if not self.usuario_logado:
                    self.after(100,self._abrir_login)
                self.after(300, lambda: self._buscar_alertas(mostrar_popup=True))
                self.after(500, self._atualizar_dashboard)
                self.after(500, self._sincronizar_notificacoes)
            if avisar:
                if ok:
                    messagebox.showinfo("Conexão", "Conectado ao servidor com sucesso.")
                else:
                    messagebox.showerror(
                        "Conexão",
                        "Não foi possível conectar ao servidor.\n\n"
                        "Verifique:\n"
                        "- se o servidor está ligado e com a janela aberta;\n"
                        "- se este computador está na mesma rede Wi-Fi/local;\n"
                        "- se o endereço configurado está correto.",
                    )
        else:
            self.lbl_status_servidor.configure(text=f"Servidor: {self.api.servidor_url}")

    def _servidor_configurado(self) -> bool:
        if not self.api:
            messagebox.showwarning("Atenção", "Configure o endereço do servidor primeiro.")
            self._configurar_servidor()
            return False
        return True

    # ------------------------------ usuários e auditoria --------------------------------

    def _entrar_ou_configurar(self):
        if not self.api:
            messagebox.showinfo('Acesso','Configure primeiro o endereço do servidor da Farmácia.',parent=self);self._configurar_servidor();return
        if not self.api.testar_conexao():
            messagebox.showerror('Acesso','Servidor inacessível. Verifique o endereço e a rede.',parent=self);return
        self._abrir_login()

    def _abrir_login(self):
        if not self.api or self.usuario_logado:return
        janela=tk.Toplevel(self);janela.title('Entrar — Gerente Farmácia');janela.configure(bg=COR_FUNDO_CARTAO);janela.resizable(False,False);janela.transient(self);janela.grab_set()
        tk.Label(janela,text='Acesso ao Gerente Farmácia',bg=COR_PRIMARIA,fg='white',font=('Segoe UI',15,'bold'),padx=28,pady=18).pack(fill='x')
        corpo=tk.Frame(janela,bg=COR_FUNDO_CARTAO,padx=28,pady=22);corpo.pack(fill='both',expand=True)
        tk.Label(corpo,text='Usuário',bg=COR_FUNDO_CARTAO,fg=COR_TEXTO,anchor='w').pack(fill='x');var_u=tk.StringVar(value=carregar_config().get('ultimo_usuario',''));e_u=ttk.Entry(corpo,textvariable=var_u,width=34);e_u.pack(fill='x',pady=(4,12))
        tk.Label(corpo,text='Senha',bg=COR_FUNDO_CARTAO,fg=COR_TEXTO,anchor='w').pack(fill='x');var_s=tk.StringVar();e_s=ttk.Entry(corpo,textvariable=var_s,show='●',width=34);e_s.pack(fill='x',pady=(4,16))
        erro=tk.StringVar();tk.Label(corpo,textvariable=erro,bg=COR_FUNDO_CARTAO,fg=COR_ERRO).pack(fill='x')
        def entrar(event=None):
            try:self.usuario_logado=self.api.login(var_u.get().strip(),var_s.get());
            except ErroConexao as exc:erro.set(str(exc));return
            cfg=carregar_config();cfg['ultimo_usuario']=self.usuario_logado['usuario'];salvar_config(cfg);janela.destroy();self._apos_login()
        BotaoArredondado(corpo,text='ENTRAR',command=entrar,width=240).pack(fill='x',pady=(10,0))
        janela.bind('<Return>',entrar);janela.protocol('WM_DELETE_WINDOW',self.destroy);janela.update_idletasks();janela.geometry(f"360x310+{self.winfo_rootx()+250}+{self.winfo_rooty()+120}")
        (e_s if var_u.get() else e_u).focus_set()

    def _apos_login(self):
        u=self.usuario_logado;perfil='Gerente' if u['perfil']=='gerente' else 'Administrador';self.lbl_usuario.configure(text=f"Acesso: {u['nome']} ({perfil})")
        self.btn_entrar.pack_forget()
        self.btn_sair.pack(side='right',padx=(0,8))
        if u['perfil']=='gerente':
            self.btn_auditoria.pack(side='right',padx=(0,8));self.btn_usuarios.pack(side='right',padx=(0,8))
            if str(self.aba_auditoria) not in self.notebook.tabs():self.notebook.add(self.aba_auditoria,text='  Auditoria  ')
            self._buscar_auditoria()
        if u.get('trocar_senha'):
            messagebox.showwarning('Troca de senha','Por segurança, altere a senha inicial agora.',parent=self)
            self._alterar_senha_obrigatoria()

    def _alterar_senha_obrigatoria(self):
        while True:
            senha=simpledialog.askstring('Nova senha','Digite uma nova senha (mínimo de 6 caracteres):',show='●',parent=self)
            if senha is None:self._logout();return
            confirma=simpledialog.askstring('Confirmar senha','Digite a nova senha novamente:',show='●',parent=self)
            if senha!=confirma:messagebox.showerror('Senha','As senhas não coincidem.',parent=self);continue
            try:self.api.alterar_minha_senha(senha);self.usuario_logado['trocar_senha']=False;messagebox.showinfo('Senha','Senha alterada com sucesso.',parent=self);return
            except ErroConexao as exc:messagebox.showerror('Senha',str(exc),parent=self)

    def _logout(self):
        if self.api:self.api.logout()
        self.usuario_logado=None;self.lbl_usuario.configure(text='Acesso: aguardando login')
        for b in (self.btn_sair,self.btn_usuarios,self.btn_auditoria):b.pack_forget()
        if str(self.aba_auditoria) in self.notebook.tabs():self.notebook.forget(self.aba_auditoria)
        self.btn_entrar.pack(side='left')
        self._abrir_login()

    def _abrir_usuarios(self):
        if not self.usuario_logado or self.usuario_logado.get('perfil')!='gerente':return
        j=tk.Toplevel(self);j.title('Gerenciar Administradores');j.geometry('780x500');j.minsize(620,380);j.configure(bg=COR_FUNDO);j.transient(self)
        topo=ttk.Frame(j,style='Cartao.TFrame',padding=14);topo.pack(fill='x',padx=10,pady=10)
        campos=[]
        for i,(rot,w) in enumerate((('Nome completo',24),('Usuário',16),('Senha inicial',16))):
            ttk.Label(topo,text=rot,style='Cartao.TLabel').grid(row=0,column=i,padx=4,sticky='w');v=tk.StringVar();campos.append(v);ttk.Entry(topo,textvariable=v,width=w,show='●' if i==2 else '').grid(row=1,column=i,padx=4,pady=4)
        tabela=ttk.Frame(j);tabela.pack(fill='both',expand=True,padx=10,pady=(0,10));tree=ttk.Treeview(tabela,columns=('id','nome','usuario','perfil','ativo','ultimo'),show='headings');configurar_rolagem_tabela(tabela,tree)
        for c,t,w in (('id','ID',45),('nome','Nome',210),('usuario','Usuário',130),('perfil','Perfil',120),('ativo','Ativo',60),('ultimo','Último acesso',150)):tree.heading(c,text=t);tree.column(c,width=w,anchor='center')
        def atualizar():
            for x in tree.get_children():tree.delete(x)
            try:
                for u in self.api.listar_usuarios():tree.insert('', 'end',values=(u['id'],u['nome'],u['usuario'],u['perfil'],'Sim' if u['ativo'] else 'Não',u.get('ultimo_acesso') or ''))
            except ErroConexao as exc:messagebox.showerror('Usuários',str(exc),parent=j)
        def criar():
            try:self.api.criar_usuario(campos[1].get().strip(),campos[0].get().strip(),campos[2].get(),'administrador');[v.set('') for v in campos];atualizar()
            except ErroConexao as exc:messagebox.showerror('Usuários',str(exc),parent=j)
        def alterar_ativo(ativo):
            selecionado=tree.selection()
            if not selecionado:messagebox.showwarning('Administradores','Selecione um Administrador.',parent=j);return
            valores=tree.item(selecionado[0],'values')
            if valores[3]!='administrador':messagebox.showwarning('Administradores','A conta Gerente não pode ser alterada.',parent=j);return
            try:self.api.ativar_usuario(int(valores[0]),ativo);atualizar()
            except ErroConexao as exc:messagebox.showerror('Administradores',str(exc),parent=j)
        ttk.Button(topo,text='Criar Administrador',command=criar).grid(row=1,column=3,padx=8);atualizar()
        acoes=ttk.Frame(j,style='TFrame');acoes.pack(fill='x',padx=10,pady=(0,10))
        ttk.Button(acoes,text='Reativar selecionado',style='Secundario.TButton',command=lambda:alterar_ativo(True)).pack(side='right')
        ttk.Button(acoes,text='Bloquear selecionado',command=lambda:alterar_ativo(False)).pack(side='right',padx=(0,8))
        ttk.Button(acoes,text='← Voltar / Fechar',style='Secundario.TButton',command=j.destroy).pack(side='left')

    def _montar_aba_auditoria(self,aba):
        topo=ttk.Frame(aba,style='Cartao.TFrame',padding=16);topo.pack(fill='x',padx=8,pady=(8,4))
        ttk.Label(topo,text='Auditoria do sistema — acesso exclusivo do Gerente',style='Cartao.TLabel',font=('Segoe UI',11,'bold')).pack(side='left')
        ttk.Button(topo,text='Atualizar',command=self._buscar_auditoria).pack(side='right')
        tabela=ttk.Frame(aba);tabela.pack(fill='both',expand=True,padx=8,pady=4)
        self.tree_auditoria=ttk.Treeview(tabela,columns=('data','usuario','acao','entidade','id','detalhes'),show='headings');configurar_rolagem_tabela(tabela,self.tree_auditoria)
        for c,t,w in (('data','Data/hora',135),('usuario','Usuário',120),('acao','Ação',170),('entidade','Área',110),('id','Registro',70),('detalhes','Detalhes',420)):self.tree_auditoria.heading(c,text=t);self.tree_auditoria.column(c,width=w,anchor='w')
        self.lbl_auditoria=ttk.Label(aba,text='');self.lbl_auditoria.pack(anchor='w',padx=8,pady=(4,8))

    def _buscar_auditoria(self):
        if not self.usuario_logado or self.usuario_logado.get('perfil')!='gerente':return
        for iid in self.tree_auditoria.get_children():self.tree_auditoria.delete(iid)
        try:
            registros=self.api.listar_auditoria()
            for r in registros:self.tree_auditoria.insert('', 'end',values=(r['data'],r['usuario'],r['acao'],r['entidade'],r.get('entidade_id') or '',r.get('detalhes') or ''))
            self.lbl_auditoria.configure(text=f'{len(registros)} registro(s) de auditoria')
        except ErroConexao as exc:messagebox.showerror('Auditoria',str(exc),parent=self)

    def _abrir_auditoria(self):
        if not self.usuario_logado or self.usuario_logado.get('perfil')!='gerente':return
        self._buscar_auditoria();self.notebook.select(self.aba_auditoria)

    # ------------------------------ notificações de pedidos --------------------------------

    def _sincronizar_notificacoes(self):
        """Chamado uma vez ao conectar: define o ponto de partida (não avisa
        sobre pedidos que já existiam antes de abrir o programa) e inicia
        o polling periódico."""
        if not self.api:
            return
        try:
            resposta = self.api.obter_notificacoes()
            self._ultimo_notificacao_id = resposta["ultimo_id"]
        except ErroConexao:
            self._ultimo_notificacao_id = 0
        self._buscar_pedidos()
        self.after(INTERVALO_NOTIFICACOES_MS, self._verificar_notificacoes_periodicamente)

    def _verificar_notificacoes_periodicamente(self):
        if not self.api or self._ultimo_notificacao_id is None:
            self.after(INTERVALO_NOTIFICACOES_MS, self._verificar_notificacoes_periodicamente)
            return
        try:
            resposta = self.api.obter_notificacoes(desde=self._ultimo_notificacao_id)
            eventos = resposta["eventos"]
            self._ultimo_notificacao_id = resposta["ultimo_id"]
        except ErroConexao:
            eventos = []  # falha silenciosa -- não interrompe o uso normal do programa

        for evento in eventos:
            self._mostrar_aviso_pedido(evento)

        if eventos:
            self._buscar_pedidos()  # atualiza a aba Pedidos automaticamente quando chega pedido novo

        self.after(INTERVALO_NOTIFICACOES_MS, self._verificar_notificacoes_periodicamente)

    def _mostrar_aviso_pedido(self, evento: dict):
        tocar_bipe_local()

        itens_texto = "\n".join(
            f"  • {i['medicamento']} ({i['categoria']}) — {i['quantidade']}"
            + (" — CANCELADO: SEM ESTOQUE" if i.get('status')=='CANCELADO_SEM_ESTOQUE' else "")
            for i in evento["itens"]
        )

        aviso = tk.Toplevel(self)
        aviso.title("Novo pedido")
        aviso.configure(bg=COR_FUNDO_CARTAO)
        aviso.attributes("-topmost", True)
        aviso.resizable(False, False)

        tk.Label(
            aviso, text="🔔 Novo pedido recebido", bg=COR_PRIMARIA, fg="white",
            font=("Segoe UI", 11, "bold"), anchor="w", padx=12, pady=8,
        ).pack(fill="x")

        corpo = tk.Frame(aviso, bg=COR_FUNDO_CARTAO)
        corpo.pack(fill="both", expand=True, padx=14, pady=10)
        tk.Label(
            corpo, text=f"Solicitante: {evento['solicitante']}   —   {evento['data']}",
            bg=COR_FUNDO_CARTAO, fg=COR_TEXTO, font=("Segoe UI", 9, "bold"), anchor="w",
        ).pack(anchor="w", pady=(0, 6))
        tk.Label(
            corpo, text=itens_texto, bg=COR_FUNDO_CARTAO, fg=COR_TEXTO,
            font=("Segoe UI", 9), justify="left", anchor="w",
        ).pack(anchor="w")

        ttk.Button(corpo, text="OK", command=aviso.destroy).pack(anchor="e", pady=(10, 0))

        # Posiciona no canto inferior direito da tela e fecha sozinho depois de um tempo
        aviso.update_idletasks()
        largura, altura = aviso.winfo_reqwidth(), aviso.winfo_reqheight()
        x = self.winfo_screenwidth() - largura - 24
        y = self.winfo_screenheight() - altura - 80
        aviso.geometry(f"{largura}x{altura}+{x}+{y}")

        aviso.after(10000, lambda: aviso.destroy() if aviso.winfo_exists() else None)

    # ------------------------------ eventos: histórico --------------------------------

    def _parse_data_filtro(self, texto: str, fim_do_dia: bool):
        texto = texto.strip()
        if not texto:
            return None
        try:
            data = datetime.strptime(texto, FORMATO_DATA)
        except ValueError:
            raise ValueError(f"Data inválida: '{texto}'. Use o formato dd/mm/aaaa.")
        if fim_do_dia:
            data = datetime.combine(data.date(), time(23, 59, 59))
        return data

    def _buscar_historico(self):
        if not self._servidor_configurado():
            return

        categoria = self.var_filtro_categoria.get()
        ficha = self.var_filtro_ficha.get().strip()
        medicamento = self.var_filtro_medicamento.get().strip()
        solicitante = self.var_filtro_solicitante.get().strip()

        try:
            data_inicio = self._parse_data_filtro(self.var_filtro_data_inicio.get(), fim_do_dia=False)
            data_fim = self._parse_data_filtro(self.var_filtro_data_fim.get(), fim_do_dia=True)
        except ValueError as e:
            messagebox.showerror("Data inválida", str(e))
            return

        try:
            registros = self.api.buscar_movimentacoes(
                categoria=categoria if categoria != "Todas" else None,
                data_inicio=data_inicio, data_fim=data_fim,
                ficha=ficha or None, medicamento=medicamento or None, solicitante=solicitante or None,
            )
        except ErroConexao as e:
            messagebox.showerror("Erro de conexão", str(e))
            return

        self._resultado_busca = registros
        for item in self.tree.get_children():
            self.tree.delete(item)
        for r in registros:
            self.tree.insert(
                "", "end",
                values=(r["categoria"], r["data"], r["medicamento"], r["ficha"], r.get("solicitante") or "-",
                        r["retirada"], r["estoque_anterior"], r["estoque_final"]),
            )
        self.lbl_total_resultados.configure(text=f"{len(registros)} registro(s) encontrado(s)")

    def _limpar_filtros_historico(self):
        self.var_filtro_categoria.set("Todas")
        self.var_filtro_ficha.set("")
        self.var_filtro_medicamento.set("")
        self.var_filtro_solicitante.set("")
        self.var_filtro_data_inicio.set("")
        self.var_filtro_data_fim.set("")
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._resultado_busca = []
        self.lbl_total_resultados.configure(text="")

    def _montar_titulo_filtros_historico(self):
        partes_filtro = []
        if self.var_filtro_categoria.get() != "Todas":
            partes_filtro.append(self.var_filtro_categoria.get())
        if self.var_filtro_ficha.get().strip():
            partes_filtro.append(f"Ficha: {self.var_filtro_ficha.get().strip()}")
        if self.var_filtro_medicamento.get().strip():
            partes_filtro.append(f"Medicamento: {self.var_filtro_medicamento.get().strip()}")
        if self.var_filtro_solicitante.get().strip():
            partes_filtro.append(f"Solicitante: {self.var_filtro_solicitante.get().strip()}")
        if self.var_filtro_data_inicio.get().strip() or self.var_filtro_data_fim.get().strip():
            partes_filtro.append(
                f"{self.var_filtro_data_inicio.get().strip() or '...'} a "
                f"{self.var_filtro_data_fim.get().strip() or '...'}"
            )
        return " | ".join(partes_filtro) if partes_filtro else "Todos os registros"

    def _exportar_relatorio_pdf(self):
        if not self._resultado_busca:
            messagebox.showwarning("Atenção", "Faça uma busca antes de exportar o relatório.")
            return

        titulo_filtros = self._montar_titulo_filtros_historico()

        nome_sugerido = f"relatorio_estoque_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        caminho = filedialog.asksaveasfilename(
            initialdir=PASTA_COMPROVANTES, initialfile=nome_sugerido,
            defaultextension=".pdf", filetypes=[("Arquivo PDF", "*.pdf")],
        )
        if not caminho:
            return
        try:
            gerar_pdf_relatorio(caminho, titulo_filtros, self._resultado_busca)
        except Exception as e:
            messagebox.showerror("Erro ao gerar relatório", str(e))
            return
        messagebox.showinfo("Relatório gerado", f"Salvo em:\n{caminho}")

    def _exportar_resumo_consumo_pdf(self):
        if not self._resultado_busca:
            messagebox.showwarning(
                "Atenção",
                "Faça uma busca antes de exportar o resumo.\n\n"
                "Dica: para um resumo anual, filtre Data início 01/01/AAAA e "
                "Data fim 31/12/AAAA (deixe Categoria em 'Todas' para somar tudo).",
            )
            return

        titulo_filtros = self._montar_titulo_filtros_historico()

        nome_sugerido = f"resumo_consumo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        caminho = filedialog.asksaveasfilename(
            initialdir=PASTA_COMPROVANTES, initialfile=nome_sugerido,
            defaultextension=".pdf", filetypes=[("Arquivo PDF", "*.pdf")],
        )
        if not caminho:
            return
        try:
            gerar_pdf_resumo_consumo(caminho, titulo_filtros, self._resultado_busca)
        except Exception as e:
            messagebox.showerror("Erro ao gerar resumo", str(e))
            return
        messagebox.showinfo("Resumo gerado", f"Salvo em:\n{caminho}")

    # ------------------------------ eventos: alertas --------------------------------

    def _buscar_alertas(self, mostrar_popup=False):
        if not self.api:
            return
        try:
            alertas = self.api.listar_alertas_validade(dias=120)
        except ErroConexao as e:
            if mostrar_popup:
                return
            messagebox.showerror("Erro de conexão", str(e))
            return

        for item in self.tree_alertas.get_children():
            self.tree_alertas.delete(item)

        for a in alertas:
            if a["vencido"]:
                situacao = f"VENCIDO há {-a['dias_restantes']} dia(s)"
                tag = "vermelho"
            elif a["dias_restantes"] <= 90:
                situacao = f"Vence em {a['dias_restantes']} dia(s)"
                tag = "vermelho"
            elif a["dias_restantes"] <= 120:
                situacao = f"Vence em {a['dias_restantes']} dia(s)"
                tag = "laranja"
            else:
                situacao = f"Vence em {a['dias_restantes']} dia(s)"
                tag = "verde"
            self.tree_alertas.insert(
                "", "end",
                values=(a["categoria"], a["medicamento"], a["ficha"], a["validade"], situacao, a["estoque"]),
                tags=(tag,),
            )

        em_atencao=sum(1 for a in alertas if a['dias_restantes']<=120)
        self.lbl_total_alertas.configure(text=f"{em_atencao} lote(s) em atenção até 120 dias — lotes acima de 120 dias não são exibidos")

        if self.notebook is not None:
            texto_aba = "  Alertas de Validade  " if not em_atencao else f"  ⚠ Alertas de Validade ({em_atencao})  "
            self.notebook.tab(self.aba_alertas_index, text=texto_aba)

        if mostrar_popup and em_atencao:
            vencidos = sum(1 for a in alertas if a["vencido"])
            vermelhos=sum(1 for a in alertas if a['dias_restantes']<=90)
            laranjas=sum(1 for a in alertas if 90<a['dias_restantes']<=120)
            msg=f"{em_atencao} lote(s) exigem atenção: {vermelhos} vermelho(s) e {laranjas} laranja(s)"
            if vencidos:
                msg += f" ({vencidos} já vencido(s))"
            messagebox.showwarning("Alerta de validade", msg + ".\nVeja a aba 'Alertas de Validade' para detalhes.")


if __name__ == "__main__":
    app = App()
    app.mainloop()
