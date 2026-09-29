/** Aquisições FS: client for the server-backed, staged purchase workflow. */
export function createAquisicoesFS({api,esc,table,panel,field,formDialog,printHtml,toast,S,render}) {
  const tipos = {
    consumo:'Consumo · 3.3.90.30', consumo_duradouro:'Consumo duradouro · classificação a confirmar',
    servico_pj:'Serviço PJ · 3.3.90.39', servico_pf:'Serviço PF · 3.3.90.36',
    permanente:'Permanente · 4.4.90.52'
  };
  const shortDate = value => value ? value.split('-').reverse().join('/') : '—';
  const tabs = [['aquisicoes','Aquisições FS'],['empresas','Empresas'],['paassex','PAASSEx']];
  function button(label,action,id) {
    return `<button class="button secondary small" data-fs="${action}" data-id="${id}">${label}</button>`;
  }
  async function load() {
    try {
      const [a,e,p]=await Promise.all([api('/aquisicoes-fs'),api('/empresas-fs'),api('/paassex')]);
      S.aquisicoesFS=a.aquisicoes; S.empresasFS=e.empresas; S.paassex=p.itens;
      delete S.errors.aquisicoesFS;
    } catch(err) {
      S.errors.aquisicoesFS=err.message; S.aquisicoesFS=S.empresasFS=S.paassex=null;
    }
    if(S.area==='acquisitions')render();
  }
  function tabBar() {
    return `<div class="toolbar fs-tabs">${tabs.map(([id,label]) =>
      `<button class="button ${S.fsTab===id?'':'secondary'}" data-fs="tab" data-id="${id}">${label}</button>`).join('')}</div>`;
  }
  function acquisitionStatus(item) {
    if(item.alerta==='ATRASADO')return '<span class="badge danger">Entrega atrasada</span>';
    if(item.alerta==='PROXIMO')return '<span class="badge warning">Prazo em até 7 dias</span>';
    return `<span class="badge ${item.etapa==='ENTREGUE'||item.etapa==='LIQUIDADO'?'success':'neutral'}">${esc({
      CADASTRO_INICIAL:'Cadastro inicial',REQUISITADO:'Requisitado',AGUARDANDO_ENTREGA:'Aguardando entrega',
      ENTREGUE:'Entregue',LIQUIDADO:'Liquidado'
    }[item.etapa]||item.etapa)}</span>`;
  }
  function renderAcquisitions() {
    const rows=S.aquisicoesFS||[];
    const overdue=rows.filter(x=>x.alerta==='ATRASADO').length;
    const soon=rows.filter(x=>x.alerta==='PROXIMO').length;
    const done=rows.filter(x=>x.entrega_data).length;
    return `<div class="cards fs-metrics"><div class="metric"><span>Aquisições</span><strong>${rows.length}</strong></div>
      <div class="metric"><span>Entrega atrasada</span><strong>${overdue}</strong></div>
      <div class="metric"><span>Até 7 dias</span><strong>${soon}</strong></div>
      <div class="metric"><span>Entregues</span><strong>${done}</strong></div></div>
      <div class="toolbar"><span class="subtle">Cadastre dados parciais e complete as etapas pelo botão Editar.</span>
      <button class="button" data-fs="new-acquisition">+ Nova aquisição</button>
      <button class="button secondary" data-fs="print-acquisitions">Imprimir relatório</button></div>
      ${panel('Acompanhamento',S.aquisicoesFS===null?errorView():
        table(['Material / serviço','Tipo','Requisição','Empenho','Empresa','Prazo 30 dias','Rastreio','Entrega','Situação',''],
          rows.map(x=>[`<b>${esc(x.material)}</b>`,esc(tipos[x.tipo]||'—'),
            esc(x.requisicao_numero||'—'),esc(x.empenho_numero||'—'),esc(x.empresa_nome||'—'),
            shortDate(x.prazo_30_dias),esc(x.rastreio||'—'),shortDate(x.entrega_data),
            acquisitionStatus(x),button('Editar','edit-acquisition',x.id)])))}`;
  }
  function renderCompanies() {
    return `<div class="toolbar"><button class="button" data-fs="new-company">+ Cadastrar empresa</button>
      <button class="button secondary" data-fs="print-companies">Imprimir relatório</button></div>
      ${panel('Empresas cadastradas',S.empresasFS===null?errorView():
        table(['Empresa','CNPJ','Telefone','E-mail',''],(S.empresasFS||[]).map(x=>[
          esc(x.nome),esc(x.cnpj),esc(x.telefone),esc(x.email),button('Editar','edit-company',x.id)])))}`;
  }
  function renderPaassex() {
    const rows=S.paassex||[], filter=S.fsYear||'';
    const requested=rows.filter(x=>!x.autorizado&&(!filter||String(x.ano)===filter));
    const approved=rows.filter(x=>x.autorizado&&(!filter||String(x.ano)===filter));
    const years=[...new Set(rows.map(x=>x.ano))].sort((a,b)=>b-a);
    const options=years.map(x=>`<option value="${x}" ${String(x)===filter?'selected':''}>${x}</option>`).join('');
    return `<div class="toolbar"><button class="button" data-fs="new-paassex">+ Cadastrar item solicitado</button>
      <label class="field">Ano<select id="fsYear"><option value="">Todos</option>${options}</select></label>
      <button class="button secondary" data-fs="print-paassex">Imprimir relatório</button></div>
      ${panel('Itens solicitados',S.paassex===null?errorView():
        table(['Selecionar','Ano','Item','Descrição','Situação'],requested.map(x=>[
          `<input type="checkbox" data-paass-select="${x.id}" aria-label="Selecionar ${esc(x.nome)}" ${S.fsSelected?.has(x.id)?'checked':''}>`,
          esc(x.ano),esc(x.nome),esc(x.descricao),'Solicitado']))+
          '<div class="actions"><button class="button" data-fs="authorize">Autorizar selecionados</button></div>')}
      ${panel('Itens autorizados',S.paassex===null?errorView():
        table(['Ano','Item','Descrição','Autorizado em',''],approved.map(x=>[
          esc(x.ano),esc(x.nome),esc(x.descricao),esc(x.autorizado_em||'—'),
          button('Voltar a solicitado','revoke',x.id)])))}`;
  }
  function errorView() {
    return `<div class="empty">Não foi possível carregar: ${esc(S.errors.aquisicoesFS||'Atualize o servidor.')}</div>`;
  }
  function renderArea() {
    S.fsTab=S.fsTab||'aquisicoes';
    document.querySelector('#content').innerHTML=tabBar()+
      (S.fsTab==='empresas'?renderCompanies():S.fsTab==='paassex'?renderPaassex():renderAcquisitions());
  }
  function companyForm(id, returnToAcquisition) {
    const company=id?S.empresasFS.find(x=>x.id===id):null;
    formDialog(company?'Editar empresa':'Cadastrar empresa',
      `<div class="form-grid">${field('Nome / razão social','nome',company?.nome||'','text','required')}
      ${field('CNPJ','cnpj',company?.cnpj||'','text','maxlength="24"')}
      ${field('Telefone','telefone',company?.telefone||'','text','maxlength="40"')}
      ${field('E-mail','email',company?.email||'','email','maxlength="240"')}</div>`,
      async data=>{const result=await api('/empresas-fs'+(id?'/'+id:''),id?'PUT':'POST',data);await load();toast('Empresa salva.');
        if(returnToAcquisition)setTimeout(()=>acquisitionForm(returnToAcquisition.id, {...returnToAcquisition.data,empresa_id:result.id}),0);});
  }
  function acquisitionForm(id, draft) {
    const item=draft||(id?S.aquisicoesFS.find(x=>x.id===id):{});
    const options='<option value="">Selecione, se já definido</option>'+
      (S.empresasFS||[]).map(x=>`<option value="${x.id}" ${String(item.empresa_id)===String(x.id)?'selected':''}>${esc(x.nome)}</option>`).join('');
    const types='<option value="">A classificar</option>'+
      Object.entries(tipos).map(([key,label])=>`<option value="${key}" ${item.tipo===key?'selected':''}>${esc(label)}</option>`).join('');
    formDialog(id?'Editar aquisição':'Nova aquisição',
      `<p class="subtle">Você pode salvar com informações parciais. O alerta é calculado somente após informar a data do empenho.</p>
      <div class="form-grid">${field('Material / serviço','material',item.material||'','text','required maxlength="240"')}
      <label class="field">Tipo e código<select name="tipo">${types}</select></label>
      ${field('Requisição nº','requisicao_numero',item.requisicao_numero||'')}
      ${field('Data da requisição','requisicao_data',item.requisicao_data||'','date')}
      ${field('Empenho nº','empenho_numero',item.empenho_numero||'')}
      ${field('Data do empenho','empenho_data',item.empenho_data||'','date')}
      <label class="field">Empresa<select name="empresa_id">${options}</select></label>
      <div class="field"><span>Cadastro de empresas</span><button type="button" class="button secondary small" data-fs="new-company">+ Cadastrar empresa</button></div>
      ${field('Previsão de entrega','previsao_entrega',item.previsao_entrega||'','date')}
      ${field('Localizador / rastreio','rastreio',item.rastreio||'','text','placeholder="Código dos Correios ou transportadora"')}
      ${field('Data da entrega','entrega_data',item.entrega_data||'','date')}
      ${field('Liquidação / nota nº','liquidacao_numero',item.liquidacao_numero||'')}
      ${field('Data da liquidação','liquidacao_data',item.liquidacao_data||'','date')}
      <label class="field wide">Observações<textarea name="observacao" maxlength="1000">${esc(item.observacao||'')}</textarea></label></div>`,
      async data=>{await api('/aquisicoes-fs'+(id?'/'+id:''),id?'PUT':'POST',data);await load();toast('Aquisição salva.');});
  }
  function paassexForm() {
    formDialog('Cadastrar item solicitado · PAASSEx',
      `<div class="form-grid">${field('Ano','ano',new Date().getFullYear(),'number','required min="2000" max="2100"')}
      ${field('Nome do item','nome','','text','required maxlength="240"')}
      <label class="field wide">Descrição<textarea name="descricao" required maxlength="2000"></textarea></label></div>`,
      async data=>{await api('/paassex','POST',data);await load();toast('Item solicitado cadastrado.');});
  }
  async function click(button) {
    const {fs,id}=button.dataset;
    if(!fs)return false;
    if(fs==='tab'){S.fsTab=id;render();return true}
    if(fs==='new-company'){
      const acquisition=document.querySelector('#modalForm [name="material"]');
      companyForm(undefined,acquisition?{id:S.fsEditingAcquisition,data:Object.fromEntries(new FormData(acquisition.form))}:null);
      return true;
    }
    if(fs==='edit-company'){companyForm(Number(id));return true}
    if(fs==='new-acquisition'){S.fsEditingAcquisition=undefined;acquisitionForm();return true}
    if(fs==='edit-acquisition'){S.fsEditingAcquisition=Number(id);acquisitionForm(Number(id));return true}
    if(fs==='new-paassex'){paassexForm();return true}
    if(fs==='authorize'||fs==='revoke'){
      const ids=fs==='revoke'?[Number(id)]:[...(S.fsSelected||[])];
      if(!ids.length)throw Error('Selecione ao menos um item solicitado.');
      await api('/paassex/autorizacoes','POST',{ids,autorizado:fs==='authorize'});
      S.fsSelected?.clear();await load();toast('Situação do PAASSEx atualizada.');return true;
    }
    if(fs.startsWith('print-')){
      const type=fs.slice(6);
      if(type==='aquisicoes')printHtml('Aquisições FS',table(['Material','Tipo','Requisição','Empenho','Empresa','Prazo 30 dias','Rastreio','Entrega','Situação'],
        (S.aquisicoesFS||[]).map(x=>[esc(x.material),esc(tipos[x.tipo]||'—'),esc(x.requisicao_numero||'—'),
          esc(x.empenho_numero||'—'),esc(x.empresa_nome||'—'),shortDate(x.prazo_30_dias),
          esc(x.rastreio||'—'),shortDate(x.entrega_data),acquisitionStatus(x)])));
      if(type==='companies')printHtml('Empresas',table(['Nome','CNPJ','Telefone','E-mail'],
        (S.empresasFS||[]).map(x=>[esc(x.nome),esc(x.cnpj),esc(x.telefone),esc(x.email)])));
      if(type==='paassex')printHtml('PAASSEx',`<h2>Itens solicitados</h2>`+
        table(['Ano','Item','Descrição'],(S.paassex||[]).filter(x=>!x.autorizado).map(x=>[esc(x.ano),esc(x.nome),esc(x.descricao)]))+
        `<h2>Itens autorizados</h2>`+
        table(['Ano','Item','Descrição','Autorizado em'],(S.paassex||[]).filter(x=>x.autorizado).map(x=>[
          esc(x.ano),esc(x.nome),esc(x.descricao),esc(x.autorizado_em||'—')])));
      return true;
    }
    return false;
  }
  function change(element) {
    if(element.id==='fsYear'){S.fsYear=element.value;render();return true}
    if(element.matches('[data-paass-select]')){
      S.fsSelected=S.fsSelected||new Set();
      element.checked?S.fsSelected.add(Number(element.dataset.paassSelect)):
        S.fsSelected.delete(Number(element.dataset.paassSelect));
      return true;
    }
    return false;
  }
  return {load,render:renderArea,click,change};
}
