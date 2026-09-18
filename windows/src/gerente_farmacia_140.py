"""SISTFARMA / Gestor Farmácia 1.4.0

Camada visual evolutiva sobre a base 1.3.2.
Preserva as rotinas de estoque, pedidos, conferência, auditoria e API existentes,
adicionando menu lateral e painel analítico sem alterar o banco de dados.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk

import gerente_farmacia as legado

VERSAO_APP = "1.4.0"
legado.VERSAO_APP = VERSAO_APP

COR_MENU = "#33421F"
COR_MENU_ATIVO = "#657A3A"
COR_MENU_HOVER = "#53672E"
COR_CARTAO = "#FFFFFF"
COR_TEXTO_SUAVE = "#6B7462"


class GraficoCanvas(tk.Canvas):
    def __init__(self, parent, titulo, altura=220):
        super().__init__(parent, height=altura, bg=COR_CARTAO, highlightthickness=1,
                         highlightbackground=legado.COR_BORDA)
        self.titulo = titulo
        self.dados = []
        self.tipo = "barras"
        self.bind("<Configure>", lambda _e: self.redesenhar())

    def atualizar(self, dados, tipo="barras"):
        self.dados = list(dados or [])
        self.tipo = tipo
        self.redesenhar()

    def redesenhar(self):
        self.delete("all")
        w=max(260,self.winfo_width()); h=max(180,self.winfo_height())
        self.create_text(16,16,anchor="nw",text=self.titulo,fill=legado.COR_TEXTO,
                         font=("Segoe UI",11,"bold"))
        if not self.dados:
            self.create_text(w/2,h/2,text="Sem dados para o período",
                             fill=COR_TEXTO_SUAVE,font=("Segoe UI",10))
            return
        margem_x=38; topo=50; base=h-36
        valores=[max(0,float(v or 0)) for _,v in self.dados]
        vmax=max(valores) if valores else 1
        vmax=vmax or 1
        n=len(self.dados)
        if self.tipo=="linha":
            pontos=[]
            for i,(rotulo,valor) in enumerate(self.dados):
                x=margem_x+(w-margem_x-18)*(i/max(1,n-1))
                y=base-(base-topo)*(float(valor or 0)/vmax)
                pontos.extend([x,y])
                self.create_oval(x-3,y-3,x+3,y+3,fill=legado.COR_DESTAQUE,outline="")
                if n<=8:self.create_text(x,base+14,text=str(rotulo)[:8],font=("Segoe UI",7),fill=COR_TEXTO_SUAVE)
            if len(pontos)>=4:self.create_line(*pontos,fill=legado.COR_PRIMARIA,width=3,smooth=True)
        else:
            espaco=max(1,(w-margem_x-18)/n); largura=max(10,espaco*.58)
            for i,(rotulo,valor) in enumerate(self.dados):
                x=margem_x+i*espaco+espaco/2
                y=base-(base-topo)*(float(valor or 0)/vmax)
                self.create_rectangle(x-largura/2,y,x+largura/2,base,
                                      fill=legado.COR_PRIMARIA,outline="")
                self.create_text(x,y-9,text=f"{float(valor):g}",font=("Segoe UI",7,"bold"),
                                 fill=legado.COR_TEXTO)
                self.create_text(x,base+14,text=str(rotulo)[:13],font=("Segoe UI",7),
                                 fill=COR_TEXTO_SUAVE,width=max(45,espaco))
        self.create_line(margem_x,base,w-18,base,fill=legado.COR_BORDA)


class App(legado.App):
    def __init__(self):
        self._dashboard140_pronto=False
        super().__init__()
        self.title(f"Gestor Farmácia — SISTFARMA {VERSAO_APP}")
        self._instalar_menu_lateral()
        self._instalar_dashboard_analitico()
        self._dashboard140_pronto=True
        self.after(300,self._atualizar_dashboard)

    def _indice_por_nome(self, *nomes):
        alvos=[n.casefold() for n in nomes]
        for i,texto in enumerate(getattr(self.notebook,"_textos",[])):
            t=str(texto).strip().casefold()
            if any(a in t for a in alvos):return i
        return None

    def _abrir_area(self,*nomes):
        indice=self._indice_por_nome(*nomes)
        if indice is not None:self.notebook.select(indice)

    def _instalar_menu_lateral(self):
        try:self.notebook.barra.pack_forget()
        except Exception:pass
        self.notebook.pack_forget()
        self._menu=tk.Frame(self,bg=COR_MENU,width=205)
        self._menu.pack(side="left",fill="y",padx=(12,0),pady=12)
        self._menu.pack_propagate(False)
        self.notebook.pack(side="left",fill="both",expand=True,padx=12,pady=12)

        tk.Label(self._menu,text="SISTFARMA",bg=COR_MENU,fg="white",
                 font=("Segoe UI",15,"bold")).pack(anchor="w",padx=18,pady=(18,2))
        tk.Label(self._menu,text=f"Gestor Farmácia  {VERSAO_APP}",bg=COR_MENU,
                 fg="#DDE6CF",font=("Segoe UI",8)).pack(anchor="w",padx=18,pady=(0,16))

        itens=[
            ("Painel",lambda:self._abrir_area("painel")),
            ("Estoque",lambda:self._abrir_area("lotes")),
            ("Pedidos",lambda:self._abrir_area("pedidos")),
            ("Lotes / Validades",lambda:self._abrir_area("alertas")),
            ("Medicamentos Controlados",lambda:self._abrir_area("controlados")),
            ("Externos",lambda:self._abrir_area("externos")),
            ("Conferência",lambda:self._abrir_area("confer")),
            ("Auditoria",self._abrir_auditoria),
            ("Usuários",self._abrir_usuarios),
            ("Relatórios",lambda:self._abrir_area("histórico","relatórios")),
            ("Configurações",self._configurar_servidor),
        ]
        self._botoes_menu={}
        for nome,cmd in itens:
            b=tk.Button(self._menu,text=nome,command=cmd,anchor="w",relief="flat",bd=0,
                        bg=COR_MENU,fg="white",activebackground=COR_MENU_HOVER,
                        activeforeground="white",font=("Segoe UI",9,"bold"),
                        padx=18,pady=8,cursor="hand2")
            b.pack(fill="x",padx=7,pady=1)
            self._botoes_menu[nome]=b
        self._atualizar_menu_permissoes()

    def _atualizar_menu_permissoes(self):
        b=getattr(self,"_botoes_menu",{}).get("Auditoria")
        if not b:return
        gerente=bool(self.usuario_logado and self.usuario_logado.get("perfil")=="gerente")
        b.configure(state="normal" if gerente else "disabled",
                    disabledforeground="#8E987F")

    def _apos_login(self):
        super()._apos_login()
        self._atualizar_menu_permissoes()

    def _logout(self):
        super()._logout()
        self._atualizar_menu_permissoes()

    def _instalar_dashboard_analitico(self):
        indice=self._indice_por_nome("painel")
        if indice is None:return
        aba=self.notebook._paginas[indice]
        # Ajusta os cinco indicadores para a especificação 1.4.0.
        titulos=["Total de itens em estoque","Itens sem estoque","Validades críticas",
                 "Pedidos pendentes","Conferências pendentes"]
        comandos=[self._abrir_lotes_dashboard,self._abrir_lotes_dashboard,
                  self._abrir_validades_dashboard,self._abrir_pedidos_dashboard,
                  lambda:self._abrir_area("confer")]
        cards=[w for w in self.dashboard_cards.winfo_children() if isinstance(w,legado.CartaoPainel)]
        for card,titulo,cmd in zip(cards,titulos,comandos):
            card.titulo=titulo;card.command=cmd;card._desenhar()

        self._area_graficos=tk.Frame(aba,bg=legado.COR_FUNDO)
        self._area_graficos.pack(fill="both",expand=True,padx=8,pady=(0,8))
        for c in range(2):self._area_graficos.grid_columnconfigure(c,weight=1,uniform="graficos")
        self.grafico_validade=GraficoCanvas(self._area_graficos,"Situação das validades")
        self.grafico_mov=GraficoCanvas(self._area_graficos,"Movimentações — últimos 7 dias")
        self.grafico_saida=GraficoCanvas(self._area_graficos,"Itens com maior saída")
        self.grafico_solicitados=GraficoCanvas(self._area_graficos,"Medicamentos mais solicitados")
        self.grafico_validade.grid(row=0,column=0,sticky="nsew",padx=(0,5),pady=5)
        self.grafico_mov.grid(row=0,column=1,sticky="nsew",padx=(5,0),pady=5)
        self.grafico_saida.grid(row=1,column=0,sticky="nsew",padx=(0,5),pady=5)
        self.grafico_solicitados.grid(row=1,column=1,sticky="nsew",padx=(5,0),pady=5)

    @staticmethod
    def _quantidade_lote(lote):
        for k in ("Estoque Atual","estoque_atual","quantidade","Quantidade","estoque"):
            try:
                if k in lote:return float(lote.get(k) or 0)
            except Exception:pass
        return 0.0

    @staticmethod
    def _dias_validade(lote):
        valor=lote.get("Validade") or lote.get("validade")
        if not valor:return None
        for fmt in ("%d/%m/%Y","%Y-%m-%d","%Y-%m-%dT%H:%M:%S"):
            try:return (datetime.strptime(str(valor)[:19],fmt).date()-datetime.now().date()).days
            except ValueError:pass
        return None

    def _dados_movimentacoes(self):
        try:movs=self.api.buscar_movimentacoes()
        except Exception:return [],[]
        dias=[(datetime.now().date()-timedelta(days=i)) for i in range(6,-1,-1)]
        por_dia=defaultdict(float); saidas=Counter()
        for m in movs or []:
            data=m.get("Data") or m.get("data") or m.get("data_hora") or m.get("Data/Hora")
            dt=None
            if data:
                for fmt in ("%d/%m/%Y %H:%M:%S","%d/%m/%Y","%Y-%m-%dT%H:%M:%S","%Y-%m-%d %H:%M:%S"):
                    try:dt=datetime.strptime(str(data)[:19],fmt);break
                    except ValueError:pass
            qtd=m.get("Quantidade") or m.get("quantidade") or m.get("quantidade_retirada") or m.get("Retirada") or 0
            try:q=float(qtd or 0)
            except Exception:q=0
            tipo=str(m.get("Tipo") or m.get("tipo") or "").casefold()
            if dt and dt.date() in dias:por_dia[dt.date()]+=abs(q)
            if "sa" in tipo or q<0:
                nome=m.get("Medicamento") or m.get("medicamento") or m.get("Material") or "Item"
                saidas[str(nome)]+=abs(q)
        serie=[(d.strftime("%d/%m"),por_dia[d]) for d in dias]
        return serie,saidas.most_common(6)

    def _dados_mais_solicitados(self):
        """Soma as quantidades pedidas por medicamento/produto no histórico de pedidos."""
        try:pedidos=self.api.listar_pedidos()
        except Exception:return []
        totais=Counter()
        for p in pedidos or []:
            for item in p.get("itens",[]) or []:
                nome=item.get("medicamento") or item.get("Medicamento") or item.get("produto") or item.get("Produto")
                qtd=item.get("quantidade") or item.get("quantidade_retirada") or item.get("Quantidade") or 0
                try:q=float(qtd or 0)
                except Exception:q=0
                if nome:totais[str(nome)]+=abs(q)
        # Fallback: usa movimentações de saída quando o endpoint de pedidos não devolve itens históricos.
        if not totais:
            try:movs=self.api.buscar_movimentacoes()
            except Exception:movs=[]
            for m in movs or []:
                tipo=str(m.get("Tipo") or m.get("tipo") or "").casefold()
                qtd=m.get("Retirada") or m.get("quantidade_retirada") or m.get("Quantidade") or m.get("quantidade") or 0
                try:q=float(qtd or 0)
                except Exception:q=0
                if "sa" in tipo or q>0:
                    nome=m.get("Medicamento") or m.get("medicamento") or m.get("Material") or m.get("produto")
                    if nome:totais[str(nome)]+=abs(q)
        return totais.most_common(8)

    def _atualizar_dashboard(self):
        if not self.api:return
        try:
            lotes=[]
            for cat in legado.CATEGORIAS:lotes.extend(self.api.listar_lotes(cat))
            alertas=self.api.listar_alertas_validade(120)
            pedidos=self.api.listar_pedidos(False)
            try:confs=self.api.listar_conferencias_semana(5)
            except Exception:confs=[]
            total=sum(self._quantidade_lote(x) for x in lotes)
            sem=sum(1 for x in lotes if self._quantidade_lote(x)<=0)
            criticos=sum(1 for x in alertas or [] if (self._dias_validade(x) is None or self._dias_validade(x)<=90))
            pendentes=len(pedidos or [])
            conf_pend=sum(1 for x in confs or [] if not (x.get("resultado") or x.get("Resultado")))
            valores=[total,sem,criticos,pendentes,conf_pend]
            for var,v in zip(self.dashboard_vars,valores):var.set(f"{v:g}" if isinstance(v,float) else str(v))

            validade={"Crítico":0,"Atenção":0,"Regular":0}
            for lote in lotes:
                dias=self._dias_validade(lote)
                if dias is None:continue
                if dias<=90:validade["Crítico"]+=1
                elif dias<=120:validade["Atenção"]+=1
                else:validade["Regular"]+=1
            if getattr(self,"_dashboard140_pronto",False):
                self.grafico_validade.atualizar(list(validade.items()))
                serie,saidas=self._dados_movimentacoes()
                self.grafico_mov.atualizar(serie,"linha")
                self.grafico_saida.atualizar(saidas)
                self.grafico_solicitados.atualizar(self._dados_mais_solicitados())
        except Exception:
            # Mantém o Gestor utilizável mesmo se um endpoint analítico estiver indisponível.
            try:super()._atualizar_dashboard()
            except Exception:pass


if __name__ == "__main__":
    app=App()
    app.mainloop()
