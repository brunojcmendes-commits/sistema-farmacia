"""Fluxos reais HTTP em banco descartável do servidor offline."""
from datetime import date, timedelta
import unittest
import uuid
from test_siscofis import SiscofisTests


class AcquisitionTests(SiscofisTests):
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
