"""
Cliente Farmácia
----------------------
Tela simples para quem vai retirar medicamentos/materiais: escolhe a
categoria, o medicamento (vê o estoque disponível e a validade mais
próxima), a quantidade, e pode adicionar mais itens ao mesmo pedido antes
de enviar. Fala com o servidor pela rede.

Requisitos:
    pip install requests reportlab --break-system-packages
"""

import os
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

from farmacia_api import (
    NOME_INSTITUICAO, CATEGORIAS, PASTA_COMPROVANTES,
    COR_PRIMARIA, COR_PRIMARIA_HOVER, COR_DESTAQUE, COR_FUNDO, COR_FUNDO_CARTAO,
    COR_TEXTO, COR_BORDA, COR_FONTE_CABECALHO, COR_ERRO, COR_URGENTE, OM_LISTA,
    EstoqueAPICliente, ErroConexao,
    carregar_config, salvar_config, montar_url,
    gerar_pdf_comprovante_pedido,
)

VERSAO_APP="1.2.5"
SERVIDOR_CENTRAL_PADRAO="http://10.56.121.182:5000"
POSTOS_GRADUACOES=["Sd Ev","Sd","Cb","3º Sgt","2º Sgt","1º Sgt","ST","Asp","2º Ten","1º Ten","Cap","Maj","TC","Cel","Gen"]


class LinhaPedido:
    """Uma linha do pedido: categoria + medicamento + quantidade, com
    informação de estoque/validade exibida ao lado."""

    def __init__(self, app, container, ao_remover):
        self.app = app
        self.ao_remover = ao_remover
        self._medicamentos_cache = []  # lista de dicts vinda do servidor p/ a categoria atual

        self.frame = tk.Frame(container, bg=COR_FUNDO_CARTAO, bd=1, relief="solid",
                               highlightbackground=COR_BORDA)
        self.frame.pack(fill="x", pady=6)

        linha1 = tk.Frame(self.frame, bg=COR_FUNDO_CARTAO)
        linha1.pack(fill="x", padx=12, pady=(10, 4))

        tk.Label(linha1, text="Categoria:", bg=COR_FUNDO_CARTAO, fg=COR_TEXTO,
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w")
        self.var_categoria = tk.StringVar()
        self.combo_categoria = ttk.Combobox(
            linha1, textvariable=self.var_categoria, values=CATEGORIAS, state="readonly", width=26
        )
        self.combo_categoria.grid(row=0, column=1, sticky="w", padx=(6, 0))
        self.combo_categoria.bind("<<ComboboxSelected>>", self._on_categoria_selecionada)

        self.btn_remover = tk.Button(
            linha1, text="✕ Remover item", command=self._remover, bg=COR_ERRO, fg="white",
            font=("Segoe UI", 9, "bold"), relief="flat", padx=8,
        )
        self.btn_remover.grid(row=0, column=2, sticky="e", padx=(20, 0))
        linha1.grid_columnconfigure(2, weight=1)

        linha2 = tk.Frame(self.frame, bg=COR_FUNDO_CARTAO)
        linha2.pack(fill="x", padx=12, pady=(6, 4))

        tk.Label(linha2, text="Medicamento/Material:", bg=COR_FUNDO_CARTAO, fg=COR_TEXTO,
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w")
        self.var_medicamento = tk.StringVar()
        self.combo_medicamento = ttk.Combobox(
            linha2, textvariable=self.var_medicamento, values=[], state="normal", width=55
        )
        self.combo_medicamento.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(6, 0))
        self.combo_medicamento.bind("<<ComboboxSelected>>", self._on_medicamento_selecionado)
        self.combo_medicamento.bind("<KeyRelease>", self._filtrar_medicamentos)
        self.combo_medicamento.bind("<Return>", self._confirmar_medicamento_digitado)
        self.combo_medicamento.bind("<FocusOut>", self._confirmar_medicamento_digitado)

        tk.Label(linha2, text="Quantidade:", bg=COR_FUNDO_CARTAO, fg=COR_TEXTO,
                 font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=(8,0))
        self.var_quantidade = tk.StringVar()
        tk.Entry(linha2, textvariable=self.var_quantidade, width=10).grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(8,0))
        linha2.grid_columnconfigure(1,weight=1)

        self.var_nome_completo = tk.StringVar(value="Nome completo: selecione um medicamento/material.")
        self.lbl_nome_completo = tk.Label(
            self.frame, textvariable=self.var_nome_completo, bg=COR_FUNDO_CARTAO, fg=COR_TEXTO,
            font=("Segoe UI", 9, "bold"), anchor="w", justify="left", wraplength=760,
        )
        self.lbl_nome_completo.pack(fill="x", padx=12, pady=(4, 2))
        self.frame.bind("<Configure>",lambda e:self.lbl_nome_completo.configure(wraplength=max(300,e.width-28)))

        self.var_info = tk.StringVar(value="Selecione a categoria e o medicamento para ver o estoque disponível.")
        self.lbl_info = tk.Label(
            self.frame, textvariable=self.var_info, bg=COR_FUNDO_CARTAO, fg="#AAB79A",
            font=("Segoe UI", 8), anchor="w", justify="left",
        )
        self.lbl_info.pack(fill="x", padx=12, pady=(0, 10))

    def _on_categoria_selecionada(self, event=None):
        categoria = self.var_categoria.get()
        self.var_medicamento.set("")
        self.var_nome_completo.set("Nome completo: selecione um medicamento/material.")
        self.combo_medicamento["values"] = []
        self.var_info.set("Carregando medicamentos...")
        if not self.app.api:
            return
        try:
            medicamentos = self.app.api.listar_medicamentos(categoria)
        except ErroConexao as e:
            messagebox.showerror("Erro de conexão", str(e))
            self.var_info.set("Não foi possível carregar os medicamentos.")
            return
        self._medicamentos_cache = medicamentos
        self.combo_medicamento["values"] = [m["medicamento"] for m in medicamentos]
        self.var_info.set(f"{len(medicamentos)} medicamento(s)/material(is) disponível(is) nesta categoria.")

    def _filtrar_medicamentos(self, event=None):
        if event and event.keysym in ("Up","Down","Left","Right","Return","Tab","Escape"):
            return
        termo=self.var_medicamento.get().strip().casefold()
        nomes=[m["medicamento"] for m in self._medicamentos_cache]
        self.combo_medicamento["values"]=[n for n in nomes if termo in n.casefold()] if termo else nomes

    def _confirmar_medicamento_digitado(self, event=None):
        digitado=self.var_medicamento.get().strip()
        if not digitado:return
        exatos=[m["medicamento"] for m in self._medicamentos_cache if m["medicamento"].casefold()==digitado.casefold()]
        filtrados=[m["medicamento"] for m in self._medicamentos_cache if digitado.casefold() in m["medicamento"].casefold()]
        if exatos:self.var_medicamento.set(exatos[0]);self._on_medicamento_selecionado()
        elif len(filtrados)==1:self.var_medicamento.set(filtrados[0]);self._on_medicamento_selecionado()

    def _on_medicamento_selecionado(self, event=None):
        nome = self.var_medicamento.get()
        info = next((m for m in self._medicamentos_cache if m["medicamento"] == nome), None)
        if not info:
            return
        self.var_nome_completo.set(f"Nome completo: {nome}")
        texto = f"Estoque disponível: {info['estoque_total']}"
        if info["validade_mais_proxima"]:
            texto += f"   |   Validade mais próxima: {info['validade_mais_proxima']}"
        else:
            texto += "   |   Sem validade cadastrada"
        self.var_info.set(texto)

    def obter_dados(self):
        """Retorna (categoria, medicamento, quantidade) ou lança ValueError se inválido."""
        categoria = self.var_categoria.get()
        medicamento = self.var_medicamento.get().strip()
        quantidade_str = self.var_quantidade.get().strip()

        correspondentes=[m for m in self._medicamentos_cache if m["medicamento"].casefold()==medicamento.casefold()]
        if len(correspondentes)==1:
            medicamento=correspondentes[0]["medicamento"];self.var_medicamento.set(medicamento)
        if not categoria or not medicamento:
            raise ValueError("Selecione a categoria e o medicamento/material em todos os itens.")
        if not correspondentes:
            raise ValueError(f"Selecione '{medicamento}' na lista de medicamento/material pesquisada.")
        try:
            quantidade = float(quantidade_str.replace(",", "."))
        except ValueError:
            raise ValueError(f"Quantidade inválida para '{medicamento}'.")
        if quantidade <= 0:
            raise ValueError(f"A quantidade de '{medicamento}' precisa ser maior que zero.")

        estoque_disponivel = None
        info = next((m for m in self._medicamentos_cache if m["medicamento"] == medicamento), None)
        if info:
            estoque_disponivel = info["estoque_total"]

        return categoria, medicamento, quantidade, estoque_disponivel

    def _remover(self):
        self.frame.destroy()
        self.ao_remover(self)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        if os.name != "nt":
            try:self.tk.call("tk", "scaling", 1.0)
            except tk.TclError:pass
        self.title(f"Cliente Farmácia — versão {VERSAO_APP}")
        try:
            self._icone_app=tk.PhotoImage(file=os.path.join(os.path.dirname(os.path.abspath(__file__)),"Cliente_Farmacia.png"));self.iconphoto(True,self._icone_app)
        except Exception:pass
        largura_tela, altura_tela = self.winfo_screenwidth(), self.winfo_screenheight()
        largura = min(980, max(700, largura_tela - 30))
        altura = min(760, max(500, altura_tela - 90))
        self.geometry(f"{largura}x{altura}+0+0")
        self.minsize(min(700, largura_tela - 20), min(500, altura_tela - 70))
        self.configure(bg=COR_FUNDO)

        os.makedirs(PASTA_COMPROVANTES, exist_ok=True)

        self.api = None
        self.linhas = []
        self._ultimo_resultado = None
        self._ultimo_solicitante = None

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
        style.configure("TLabel", background=COR_FUNDO, foreground=COR_TEXTO, font=("Segoe UI", 10))
        style.configure(
            "Titulo.TLabel", background=COR_PRIMARIA, foreground=COR_FONTE_CABECALHO,
            font=("Segoe UI", 16, "bold"), padding=(16, 12),
        )
        style.configure("Rodape.TLabel", background=COR_FUNDO, foreground="#AAB79A", font=("Segoe UI", 8))
        style.configure(
            "TButton", background=COR_PRIMARIA, foreground="white",
            font=("Segoe UI", 10, "bold"), padding=8, borderwidth=0,
        )
        style.map("TButton", background=[("active", COR_PRIMARIA_HOVER), ("disabled", COR_BORDA)])
        style.configure(
            "Secundario.TButton", background=COR_DESTAQUE, foreground="#11180E",
            font=("Segoe UI", 9, "bold"), padding=6,
        )
        style.map("Secundario.TButton", background=[("active", "#9CAE6C")])
        style.configure("TEntry", padding=4, fieldbackground="#F7F6EC", foreground="#242B1C")
        style.configure("TCombobox", padding=4, fieldbackground="#F7F6EC", foreground="#242B1C")

    # ---------------------------- construção -----------------------------

    def _montar_interface(self):
        cabecalho = tk.Frame(self, bg=COR_PRIMARIA)
        cabecalho.pack(fill="x")
        ttk.Label(cabecalho, text=f"CLIENTE FARMÁCIA — SOLICITAÇÃO   ·   v{VERSAO_APP}", style="Titulo.TLabel").pack(anchor="w")

        barra_status = ttk.Frame(self, style="TFrame")
        barra_status.pack(fill="x", padx=12, pady=(8, 0))
        self.lbl_status_servidor = ttk.Label(barra_status, text="Servidor: não configurado", style="TLabel")
        self.lbl_status_servidor.pack(side="left")
        ttk.Button(
            barra_status, text="Configurar servidor", style="Secundario.TButton",
            command=self._configurar_servidor,
        ).pack(side="right")
        ttk.Button(
            barra_status, text="Testar conexão", style="Secundario.TButton",
            command=self._testar_conexao_manual,
        ).pack(side="right", padx=(0, 8))

        corpo = ttk.Frame(self, style="TFrame", padding=12)
        corpo.pack(fill="both", expand=True)

        cartao_solicitante = tk.Frame(corpo, bg=COR_FUNDO_CARTAO, bd=1, relief="solid", highlightbackground=COR_BORDA)
        cartao_solicitante.pack(fill="x", pady=(0, 12))
        tk.Label(cartao_solicitante, text="P/G:", bg=COR_FUNDO_CARTAO, fg=COR_TEXTO, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(12, 6), pady=12)
        self.var_pg = tk.StringVar()
        ttk.Combobox(cartao_solicitante,textvariable=self.var_pg,values=POSTOS_GRADUACOES,state="readonly",width=10).pack(side="left",padx=(0,10),pady=12)
        tk.Label(cartao_solicitante, text="NOME DE GUERRA:", bg=COR_FUNDO_CARTAO, fg=COR_TEXTO, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6), pady=12)
        self.var_solicitante = tk.StringVar()
        tk.Entry(cartao_solicitante, textvariable=self.var_solicitante, width=25, font=("Segoe UI", 10)).pack(side="left", padx=(0, 10), pady=12)
        tk.Label(cartao_solicitante, text="OM:", bg=COR_FUNDO_CARTAO, fg=COR_TEXTO, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6), pady=12)
        self.var_om = tk.StringVar()
        ttk.Combobox(cartao_solicitante, textvariable=self.var_om, values=OM_LISTA, state="readonly", width=20).pack(side="left", padx=(0, 12), pady=12)

        tk.Label(corpo, text="Itens do pedido:", bg=COR_FUNDO, fg=COR_PRIMARIA,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")

        # Área rolável para as linhas do pedido (caso a pessoa adicione muitos itens)
        canvas_frame = tk.Frame(corpo, bg=COR_FUNDO)
        canvas_frame.pack(fill="both", expand=True, pady=(4, 8))
        self._canvas = tk.Canvas(canvas_frame, bg=COR_FUNDO, highlightthickness=0)
        scroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=self._canvas.yview)
        self.frame_linhas = tk.Frame(self._canvas, bg=COR_FUNDO)
        self.frame_linhas.bind(
            "<Configure>", lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        )
        self._canvas_window=self._canvas.create_window((0, 0), window=self.frame_linhas, anchor="nw")
        self._canvas.bind("<Configure>",lambda e:self._canvas.itemconfigure(self._canvas_window,width=e.width))
        self._canvas.configure(yscrollcommand=scroll.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._canvas.bind("<Enter>",self._ativar_rolagem_itens)
        self._canvas.bind("<Leave>",self._desativar_rolagem_itens)

        ttk.Button(
            corpo, text="+ Adicionar outro medicamento", style="Secundario.TButton",
            command=self._adicionar_linha,
        ).pack(anchor="w", pady=(0, 12))

        botoes_finais = ttk.Frame(corpo, style="TFrame")
        botoes_finais.pack(fill="x")
        ttk.Button(botoes_finais, text="Registrar Solicitação", command=self._registrar_pedido).pack(
            side="left", fill="x", expand=True, padx=(0, 6)
        )
        self.btn_comprovante = ttk.Button(
            botoes_finais, text="Gerar Comprovante em PDF", style="Secundario.TButton",
            command=self._gerar_comprovante, state="disabled",
        )
        self.btn_comprovante.pack(side="left", fill="x", expand=True, padx=(6, 0))

        ttk.Label(self, text=f"Comprovantes salvos em: {PASTA_COMPROVANTES}", style="Rodape.TLabel").pack(
            anchor="w", padx=16, pady=(4, 8)
        )

        self._adicionar_linha()  # começa com uma linha pronta

    # ------------------------------ linhas do pedido --------------------------------

    def _adicionar_linha(self):
        linha = LinhaPedido(self, self.frame_linhas, self._remover_linha)
        self.linhas.append(linha)

    def _rolar_itens(self,event):
        delta=-1 if getattr(event,"num",None)==4 or getattr(event,"delta",0)>0 else 1
        self._canvas.yview_scroll(delta,"units")

    def _ativar_rolagem_itens(self,event=None):
        self._canvas.bind_all("<MouseWheel>",self._rolar_itens);self._canvas.bind_all("<Button-4>",self._rolar_itens);self._canvas.bind_all("<Button-5>",self._rolar_itens)

    def _desativar_rolagem_itens(self,event=None):
        self._canvas.unbind_all("<MouseWheel>");self._canvas.unbind_all("<Button-4>");self._canvas.unbind_all("<Button-5>")

    def _remover_linha(self, linha):
        if linha in self.linhas:
            self.linhas.remove(linha)
        if not self.linhas:
            self._adicionar_linha()

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
        salvar_config({"servidor_url": url})
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

    # ------------------------------ registrar pedido --------------------------------

    def _registrar_pedido(self):
        if not self._servidor_configurado():
            return

        solicitante = self.var_solicitante.get().strip()
        pg = self.var_pg.get().strip()
        om = self.var_om.get().strip()
        if not solicitante:
            messagebox.showwarning("Atenção", "Informe o NOME de quem está retirando.")
            return
        if not pg:
            messagebox.showwarning("Atenção", "Informe o P/G de quem está retirando.")
            return
        if not om:
            messagebox.showwarning("Atenção", "Selecione a OM.")
            return

        itens = []
        try:
            for linha in self.linhas:
                categoria, medicamento, quantidade, estoque_disponivel = linha.obter_dados()
                itens.append({"categoria": categoria, "medicamento": medicamento, "quantidade_retirada": quantidade})
        except ValueError as e:
            messagebox.showerror("Erro", str(e))
            return

        if not itens:
            messagebox.showwarning("Atenção", "Adicione ao menos um item ao pedido.")
            return

        try:
            resultado = self.api.registrar_pedido(solicitante, itens, pg=pg, om=om)
        except ErroConexao as e:
            messagebox.showerror("Erro de conexão", str(e))
            return

        self._ultimo_resultado = resultado
        self._ultimo_solicitante = solicitante
        self.btn_comprovante.configure(state="normal" if resultado.get("itens") else "disabled")

        linhas_resumo = []
        for item in resultado["itens"]:
            for m in item["movimentos"]:
                linhas_resumo.append(f"{m['medicamento']} (ficha {m['ficha']}): {m['retirada']}")
        avisos_validade=resultado.get('avisos') or []
        cancelados=resultado.get('itens_cancelados') or []
        texto=f"Pedido #{resultado.get('pedido_id','')} — Solicitante: {solicitante}\n\n"
        if linhas_resumo:texto+="ITENS ATENDIDOS:\n"+"\n".join(linhas_resumo)
        if cancelados:
            texto+=("\n\n" if linhas_resumo else "")+"ITENS CANCELADOS POR FALTA DE ESTOQUE:\n"+"\n".join(f"• {x['medicamento']}: solicitado {x['quantidade']}, disponível {x.get('disponivel',0)}" for x in cancelados)
        if avisos_validade:texto+='\n\n'+'\n'.join(avisos_validade)
        if cancelados or avisos_validade:messagebox.showwarning("Solicitação registrada com alerta",texto)
        else:messagebox.showinfo("Solicitação registrada",texto)

        # Limpa o pedido para o próximo
        for linha in list(self.linhas):
            linha.frame.destroy()
        self.linhas = []
        self._adicionar_linha()
        self.var_solicitante.set("")
        self.var_pg.set("")
        self.var_om.set("")

    def _gerar_comprovante(self):
        if not self._ultimo_resultado:
            return
        nome_arquivo = f"pedido_{self._ultimo_solicitante}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        nome_arquivo = "".join(c for c in nome_arquivo if c.isalnum() or c in "._- ")
        caminho = filedialog.asksaveasfilename(
            initialdir=PASTA_COMPROVANTES, initialfile=nome_arquivo,
            defaultextension=".pdf", filetypes=[("Arquivo PDF", "*.pdf")],
        )
        if not caminho:
            return
        try:
            gerar_pdf_comprovante_pedido(caminho, self._ultimo_solicitante, self._ultimo_resultado["itens"])
        except Exception as e:
            messagebox.showerror("Erro ao gerar PDF", str(e))
            return
        messagebox.showinfo("Comprovante gerado", f"Salvo em:\n{caminho}")


if __name__ == "__main__":
    app = App()
    app.mainloop()
