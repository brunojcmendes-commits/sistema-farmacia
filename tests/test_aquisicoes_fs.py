"""Fluxos reais HTTP em banco descartável do servidor offline."""
from datetime import date, timedelta
import unittest
import uuid
from test_siscofis import SiscofisTests


class AcquisitionTests(SiscofisTests):
    def test_multiple_items_same_company_and_partial_edit(self):
        company=self.call('/empresas-fs','POST',{'nome':'Empresa de dois itens'})[1]['id']
        items=[{'item':'1','codigo_catmat_catserv':'123456','descricao':'Material A',
                'unidade':'UN','quantidade':'10','nd_si':'3.3.90.30','preco_unitario':'25.00'},
               {'item':'2','codigo_catmat_catserv':'789012','descricao':'Material B',
                'unidade':'CX','quantidade':'3','nd_si':'3.3.90.30','preco_unitario':'40.00'}]
        code,created=self.call('/aquisicoes-fs','POST',{'empresa_id':company,'itens':items})
        self.assertEqual(code,200,created)
        ident=created['id']
        row=next(x for x in self.call('/aquisicoes-fs')[1]['aquisicoes'] if x['id']==ident)
        self.assertEqual([x['preco_total'] for x in row['itens']],['250.00','120.00'])
        self.assertEqual(row['empresa_nome'],'Empresa de dois itens')
        self.assertEqual(row['etapa'],'CADASTRO_INICIAL')
        self.assertEqual(row['material'],'Material A')
        updated={'empresa_id':company,'material':'Material A','itens':items,
                 'empenho_data':date.today().isoformat()}
        self.assertEqual(self.call('/aquisicoes-fs/'+str(ident),'PUT',updated)[0],200)
        row=next(x for x in self.call('/aquisicoes-fs')[1]['aquisicoes'] if x['id']==ident)
        self.assertEqual(len(row['itens']),2)
        self.assertEqual(row['etapa'],'AGUARDANDO_ENTREGA')
        self.assertEqual(self.call('/aquisicoes-fs','POST',{'itens':[{**items[0],'quantidade':'-1'}]})[0],400)
        self.assertEqual(self.call('/aquisicoes-fs','POST',{'itens':[{'descricao':''}]})[0],400)

    def test_staged_acquisition_company_and_deadline(self):
        code, company = self.call('/empresas-fs', 'POST',
                                  {'nome':'Fornecedor QA','cnpj':'00.000.000/0001-00','telefone':'123','email':'qa@example.org'})
        self.assertEqual(code, 200, company)
        cid=company['id']
        self.assertEqual(self.call('/empresas-fs/'+str(cid), 'PUT',
                                   {'nome':'Fornecedor Editado','cnpj':'00.000.000/0001-00','telefone':'456','email':'qa@example.org'})[0], 200)
        code, saved = self.call('/aquisicoes-fs', 'POST', {'material':'Material inicial'})
        self.assertEqual(code, 200, saved)
        ident=saved['id']
        row=next(x for x in self.call('/aquisicoes-fs')[1]['aquisicoes'] if x['id']==ident)
        self.assertEqual(row['etapa'], 'CADASTRO_INICIAL')
        self.assertEqual(row['prazo_30_dias'], '')
        today=date.today().isoformat()
        data={'material':'Material inicial','tipo':'consumo','empresa_id':cid,'requisicao_numero':'REQ-1',
              'empenho_numero':'NE-1','empenho_data':today,'rastreio':'BR123456789BR'}
        self.assertEqual(self.call('/aquisicoes-fs/'+str(ident),'PUT',data)[0],200)
        row=next(x for x in self.call('/aquisicoes-fs')[1]['aquisicoes'] if x['id']==ident)
        self.assertEqual(row['prazo_30_dias'],(date.today()+timedelta(days=30)).isoformat())
        self.assertEqual(row['empresa_nome'],'Fornecedor Editado')
        self.assertEqual(row['rastreio'],'BR123456789BR')
        self.assertEqual(row['etapa'],'AGUARDANDO_ENTREGA')
        self.assertEqual(self.call('/aquisicoes-fs/'+str(ident),'PUT',{**data,'entrega_data':today})[0],200)
        row=next(x for x in self.call('/aquisicoes-fs')[1]['aquisicoes'] if x['id']==ident)
        self.assertEqual(row['etapa'],'ENTREGUE')
        self.assertEqual(row['alerta'],'')
        self.assertEqual(self.call('/aquisicoes-fs','POST',{'material':'X','tipo':'invalido'})[0],400)

    def test_nc_balance_across_acquisitions_and_paassex_values(self):
        code, nc = self.call('/ncs-fs','POST',{'data':'2026-09-30','tipo':'consumo',
                                            'ug':'160001','numero':'NC-2026-01','valor':'2000.00'})
        self.assertEqual(code,200,nc)
        nc_id = nc['id']
        items=[{'descricao':'Material A','quantidade':'3','preco_unitario':'500.00',
                'nc_id':nc_id}]
        code, first = self.call('/aquisicoes-fs','POST',{'itens':items})
        self.assertEqual(code,200,first)
        rows = self.call('/ncs-fs')[1]['ncs']
        balance = next(row for row in rows if row['id']==nc_id)
        self.assertEqual(balance['utilizado'],'1500.00')
        self.assertEqual(balance['saldo'],'500.00')
        code, second = self.call('/aquisicoes-fs','POST',{'itens':[
            {'descricao':'Material B','quantidade':'2','preco_unitario':'100.00','nc_id':nc_id}]})
        self.assertEqual(code,200,second)
        balance = next(row for row in self.call('/ncs-fs')[1]['ncs'] if row['id']==nc_id)
        self.assertEqual(balance['saldo'],'300.00')
        self.assertEqual(self.call('/ncs-fs/'+str(nc_id),'PUT',
            {'data':'2026-09-30','tipo':'consumo','ug':'160001','numero':'NC-2026-01',
             'valor':'1900.00'})[0],200)
        self.assertEqual(next(row for row in self.call('/ncs-fs')[1]['ncs']
            if row['id']==nc_id)['saldo'],'200.00')
        self.assertEqual(self.call('/aquisicoes-fs','POST',{'itens':[
            {'descricao':'Material C','nc_id':999999}]})[0],400)
        code, pa = self.call('/paassex','POST',
            {'ano':2026,'nome':'Item solicitado','descricao':'Descrição','valor':'750.00','pregao':'PE-01'})
        self.assertEqual(code,200,pa)
        ident=pa['id']
        self.assertEqual(self.call('/paassex/autorizacoes','POST',
            {'ids':[ident],'autorizado':True})[0],200)
        self.assertEqual(self.call('/paassex/'+str(ident),'PUT',
            {'ano':2026,'nome':'Item solicitado','descricao':'Descrição atualizada',
             'valor':'850.00','pregao':'PE-02'})[0],200)
        saved=next(x for x in self.call('/paassex')[1]['itens'] if x['id']==ident)
        self.assertEqual((saved['autorizado'],saved['valor'],saved['pregao']),
                         (1,'850.00','PE-02'))
        self.assertEqual(self.call('/paassex/'+str(ident),'PUT',
            {'ano':2026,'nome':'Item','descricao':'Descrição','valor':'NaN'})[0],400)

    def test_paassex_selective_authorization(self):
        ids=[]
        for name in ('Primeiro','Segundo'):
            code, result=self.call('/paassex','POST',{'ano':2027,'nome':name,'descricao':'Solicitado'})
            self.assertEqual(code,200,result)
            ids.append(result['id'])
        self.assertEqual(self.call('/paassex/autorizacoes','POST',{'ids':[ids[0]],'autorizado':True})[0],200)
        items={x['id']:x for x in self.call('/paassex')[1]['itens']}
        self.assertEqual((items[ids[0]]['autorizado'],items[ids[1]]['autorizado']),(1,0))
        self.assertEqual(self.call('/paassex/autorizacoes','POST',{'ids':[ids[0],999999]})[0],400)
        self.assertEqual(self.call('/paassex/autorizacoes','POST',{'ids':[ids[0]],'autorizado':False})[0],200)

    def test_manager_resets_and_deletes_admin(self):
        username='qa_'+uuid.uuid4().hex[:10]
        code, created=self.call('/usuarios','POST',{'usuario':username,'nome':'Admin QA','senha':'OldSecret42'})
        self.assertEqual(code,200,created)
        uid=created['id']
        self.assertEqual(self.call('/usuarios/'+str(uid)+'/senha','POST',{'nova_senha':'NewSecret42'})[0],200)
        code, login=self.call('/login','POST',{'usuario':username,'senha':'NewSecret42'},auth=False)
        self.assertEqual(code,200,login)
        self.assertTrue(login['usuario']['trocar_senha'])
        self.assertEqual(self.call('/usuarios/'+str(uid),'DELETE')[0],200)
        self.assertEqual(self.call('/login','POST',{'usuario':username,'senha':'NewSecret42'},auth=False)[0],401)
        audit=self.call('/auditoria')[1]['registros']
        self.assertTrue(any(x['acao']=='REDEFINIR_SENHA_USUARIO' and x['entidade_id']==uid for x in audit))
        self.assertTrue(any(x['acao']=='EXCLUIR_USUARIO' and x['entidade_id']==uid for x in audit))


if __name__=='__main__':
    unittest.main()
