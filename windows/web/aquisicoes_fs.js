/** Aquisições FS: client for the server-backed, staged purchase workflow. */
export function createAquisicoesFS({api,esc,table,panel,field,formDialog,printHtml,toast,S,render}) {
  const tipos = {
    consumo:'Consumo · 3.3.90.30', consumo_duradouro:'Consumo duradouro · classificação a confirmar',
    servico_pj:'Serviço PJ · 3.3.90.39', servico_pf:'Serviço PF · 3.3.90.36',
    permanente:'Permanente · 4.4.90.52'
  };
  const shortDate = value => value ? value.split('-').reverse().join('/') : '—';
  const money = value => value!==''&&value!==null&&value!==undefined ? Number(value).toLocaleString('pt-BR',{style:'currency',currency:'BRL'}) : '—';
  const tabs = [['aquisicoes','Aquisições FS'],['empresas','Empresas'],['ncs','NCs'],['paassex','PAASSEx']];
  const ncTipos={consumo:'Consumo',servico:'Serviço',permanente:'Permanente'};
  const sum=rows=>rows.reduce((total,x)=>total+(Number(x.valor)||0),0);
  const ncById=id=>(S.ncsFS||[]).find(x=>x.id===Number(id));
  function button(label,action,id) {
    return `<button class="button secondary small" data-fs="${action}" data-id="${id}">${label}</button>`;
  }
  async function load() {
    try {
      const [a,e,n,p]=await Promise.all([api('/aquisicoes-fs'),api('/empresas-fs'),api('/ncs-fs'),api('/paassex')]);
      S.aquisicoesFS=a.aquisicoes; S.empresasFS=e.empresas; S.ncsFS=n.ncs; S.paassex=p.itens;
      delete S.errors.aquisicoesFS;
    } catch(err) {
      S.errors.aquisicoesFS=err.message; S.aquisicoesFS=S.empresasFS=S.ncsFS=S.paassex=null;
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
        table(['Itens / material','Tipo','Requisição','Empenho','Empresa','Prazo 30 dias','Rastreio','Entrega','Situação',''],
          rows.map(x=>[`<b>${esc(x.material)}</b><small>${x.itens?.length||1} item(ns)</small>`,esc(tipos[x.tipo]||'—'),
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
  function renderNcs() {
    return `<div class="toolbar"><button class="button" data-fs="new-nc">+ Cadastrar NC</button></div>
      ${panel('Notas de crédito',S.ncsFS===null?errorView():
        table(['Data','Tipo','UG','Número','Valor','Utilizado','Crédito restante',''],(S.ncsFS||[]).map(x=>[
          shortDate(x.data),esc(ncTipos[x.tipo]||x.tipo),esc(x.ug),esc(x.numero),money(x.valor),
          money(x.utilizado),Number(x.saldo)<0?'<span class="danger-text">Excedido: '+money(-Number(x.saldo))+'</span>':money(x.saldo),
          button('Editar','edit-nc',x.id)])))}`;
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
        table(['Selecionar','Ano','Item','Descrição','Valor','Pregão',''],requested.map(x=>[
          `<input type="checkbox" data-paass-select="${x.id}" aria-label="Selecionar ${esc(x.nome)}" ${S.fsSelected?.has(x.id)?'checked':''}>`,
          esc(x.ano),esc(x.nome),esc(x.descricao),money(x.valor),esc(x.pregao||'—'),button('Editar','edit-paassex',x.id)]))+
          `<p class="fs-total">Total solicitado: <strong>${money(sum(requested))}</strong></p><div class="actions"><button class="button" data-fs="authorize">Autorizar selecionados</button></div>`)}
      ${panel('Itens autorizados',S.paassex===null?errorView():
        table(['Ano','Item','Descrição','Valor','Pregão','Autorizado em',''],approved.map(x=>[
          esc(x.ano),esc(x.nome),esc(x.descricao),money(x.valor),esc(x.pregao||'—'),esc(x.autorizado_em||'—'),
          button('Editar','edit-paassex',x.id)+' '+button('Voltar a solicitado','revoke',x.id)]))+
          `<p class="fs-total">Total autorizado: <strong>${money(sum(approved))}</strong></p>`)}`;
  }
  function errorView() {
    return `<div class="empty">Não foi possível carregar: ${esc(S.errors.aquisicoesFS||'Atualize o servidor.')}</div>`;
  }
  function renderArea() {
    S.fsTab=S.fsTab||'aquisicoes';
    document.querySelector('#content').innerHTML=tabBar()+
      (S.fsTab==='empresas'?renderCompanies():S.fsTab==='ncs'?renderNcs():S.fsTab==='paassex'?renderPaassex():renderAcquisitions());
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
  function ncForm(id,returnToAcquisition) {
    const nc=id?ncById(id):null;
    formDialog(nc?'Editar NC':'Cadastrar NC',
      `<div class="form-grid">${field('Data da NC','data',nc?.data||'','date','required')}
      <label class="field">Tipo<select name="tipo" required><option value="">Selecione</option>${Object.entries(ncTipos).map(([key,label])=>
        `<option value="${key}" ${nc?.tipo===key?'selected':''}>${label}</option>`).join('')}</select></label>
      ${field('UG','ug',nc?.ug||'','text','required maxlength="120"')}
      ${field('Número','numero',nc?.numero||'','text','required maxlength="120"')}
      ${field('Valor (R$)','valor',nc?.valor||'','number','required min="0" step="0.01"')}</div>`,
      async data=>{const result=await api('/ncs-fs'+(id?'/'+id:''),id?'PUT':'POST',data);
        await load();toast('NC salva.');
        if(returnToAcquisition)setTimeout(()=>acquisitionForm(returnToAcquisition.id,
          {...returnToAcquisition.data,itens:returnToAcquisition.data.itens.map((item,index)=>
            index===returnToAcquisition.itemIndex?{...item,nc_id:result.id}:item)}),0);});
  }
  const itemKeys=['item','codigo_catmat_catserv','descricao','unidade','quantidade','nd_si','preco_unitario','nc_id'];
  function itemRow(item={}) {
    return `<div class="fs-item" data-fs-item><div class="fs-item-head"><strong>Item <span data-item-index></span></strong>
      <button type="button" class="button secondary small" data-fs="remove-item">Remover</button></div>
      <div class="form-grid">${field('ITEM','item',item.item||'','text','maxlength="20"')}
      ${field('CÓD CatMat/CatServ','codigo_catmat_catserv',item.codigo_catmat_catserv||'','text','maxlength="120"')}
      ${field('Descrição do material / serviço','descricao',item.descricao||'','text','required maxlength="1000"')}
      ${field('UND','unidade',item.unidade||'','text','maxlength="120"')}
      ${field('QTD','quantidade',item.quantidade||'','number','min="0" step="any"')}
      ${field('ND / S.I.','nd_si',item.nd_si||'','text','maxlength="120"')}
      ${field('P. UNT','preco_unitario',item.preco_unitario||'','number','min="0" step="0.01"')}
      <label class="field">NC do item<select name="nc_id"><option value="">Sem NC</option>${(S.ncsFS||[]).map(n=>
        `<option value="${n.id}" ${String(item.nc_id||'')===String(n.id)?'selected':''}>${esc(n.numero)} · ${esc(n.ug)} · ${money(n.valor)}</option>`).join('')}</select></label>
      <label class="field">P. TOTAL<input data-item-total readonly value="${esc(item.preco_total||'')}" aria-label="Preço total calculado"></label></div></div>`;
  }
  function collectItems() {
    return [...document.querySelectorAll('#modalForm [data-fs-item]')].map(row=>
      Object.fromEntries(itemKeys.map(key=>[key,row.querySelector(`[name="${key}"]`).value])));
  }
  function renumberItems() {
    document.querySelectorAll('#modalForm [data-fs-item]').forEach((row,i)=>{
      row.querySelector('[data-item-index]').textContent=i+1;
      if(!row.querySelector('[name="item"]').value)row.querySelector('[name="item"]').placeholder=String(i+1);
    });
  }
  function acquisitionForm(id, draft) {
    const item=draft||(id?S.aquisicoesFS.find(x=>x.id===id):{});
    const options='<option value="">Selecione, se já definido</option>'+
      (S.empresasFS||[]).map(x=>`<option value="${x.id}" ${String(item.empresa_id)===String(x.id)?'selected':''}>${esc(x.nome)}</option>`).join('');
    const types='<option value="">A classificar</option>'+
      Object.entries(tipos).map(([key,label])=>`<option value="${key}" ${item.tipo===key?'selected':''}>${esc(label)}</option>`).join('');
    const items=draft?.itens||item.itens||[{item:'1',descricao:item.material||''}];
    formDialog(id?'Editar aquisição':'Nova aquisição',
      `<p class="subtle">Você pode salvar com informações parciais. O alerta é calculado somente após informar a data do empenho.</p>
      <div class="fs-items"><h3>Itens desta aquisição</h3><p class="subtle">Cadastre vários itens para a mesma empresa. O preço total é calculado pela quantidade e preço unitário.</p>
      <div id="fsItemRows">${items.map(itemRow).join('')}</div>
      <button type="button" class="button secondary" data-fs="add-item">+ Adicionar item</button>
      <button type="button" class="button secondary" data-fs="new-nc">+ Cadastrar NC</button></div>
      <div class="form-grid"><input type="hidden" name="material" value="${esc(item.material||'')}">
      <label class="field">Resumo do material / serviço<input value="${esc(item.material||items[0]?.descricao||'')}" disabled></label>
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
      async data=>{data.itens=collectItems();data.material=data.itens[0]?.descricao||data.material;
        await api('/aquisicoes-fs'+(id?'/'+id:''),id?'PUT':'POST',data);await load();toast('Aquisição salva.');});
    renumberItems();
  }
  function paassexForm(id) {
    const item=id?(S.paassex||[]).find(x=>x.id===id):null;
    formDialog(item?'Editar item · PAASSEx':'Cadastrar item solicitado · PAASSEx',
      `<div class="form-grid">${field('Ano','ano',item?.ano||new Date().getFullYear(),'number','required min="2000" max="2100"')}
      ${field('Nome do item','nome',item?.nome||'','text','required maxlength="240"')}
      ${field('Valor (R$)','valor',item?.valor||'','number','min="0" step="0.01"')}
      ${field('Pregão','pregao',item?.pregao||'','text','maxlength="120"')}
      <label class="field wide">Descrição<textarea name="descricao" required maxlength="2000">${esc(item?.descricao||'')}</textarea></label></div>`,
      async data=>{await api('/paassex'+(id?'/'+id:''),id?'PUT':'POST',data);
        await load();toast('Item PAASSEx salvo.');});
  }
  async function click(button) {
    const {fs,id}=button.dataset;
    if(!fs)return false;
    if(fs==='tab'){S.fsTab=id;render();return true}
    if(fs==='new-company'){
      const acquisition=document.querySelector('#modalForm [name="material"]');
      companyForm(undefined,acquisition?{id:S.fsEditingAcquisition,data:{...Object.fromEntries(new FormData(acquisition.form)),itens:collectItems()}}:null);
      return true;
    }
    if(fs==='add-item'){document.querySelector('#fsItemRows').insertAdjacentHTML('beforeend',itemRow());renumberItems();return true}
    if(fs==='remove-item'){
      if(document.querySelectorAll('#fsItemRows [data-fs-item]').length<=1)throw Error('Mantenha ao menos um item.');
      button.closest('[data-fs-item]').remove();renumberItems();return true;
    }
    if(fs==='new-nc'){
      const acquisition=document.querySelector('#modalForm [name="material"]');
      const itemRow=button.closest('[data-fs-item]');
      ncForm(undefined,acquisition?{id:S.fsEditingAcquisition,itemIndex:itemRow?
        [...document.querySelectorAll('#fsItemRows [data-fs-item]')].indexOf(itemRow):0,
        data:{...Object.fromEntries(new FormData(acquisition.form)),itens:collectItems()}}:null);
      return true;
    }
    if(fs==='edit-nc'){ncForm(Number(id));return true}
    if(fs==='edit-company'){companyForm(Number(id));return true}
    if(fs==='new-acquisition'){S.fsEditingAcquisition=undefined;acquisitionForm();return true}
    if(fs==='edit-acquisition'){S.fsEditingAcquisition=Number(id);acquisitionForm(Number(id));return true}
    if(fs==='new-paassex'){paassexForm();return true}
    if(fs==='edit-paassex'){paassexForm(Number(id));return true}
    if(fs==='authorize'||fs==='revoke'){
      const ids=fs==='revoke'?[Number(id)]:[...(S.fsSelected||[])];
      if(!ids.length)throw Error('Selecione ao menos um item solicitado.');
      await api('/paassex/autorizacoes','POST',{ids,autorizado:fs==='authorize'});
      S.fsSelected?.clear();await load();toast('Situação do PAASSEx atualizada.');return true;
    }
    if(fs.startsWith('print-')){
      const type=fs.slice(6);
      if(type==='acquisitions')printHtml('Aquisições FS',(S.aquisicoesFS||[]).map(x=>
        `<section class="fs-print-acquisition"><h2>Aquisição ${x.id} · ${esc(x.empresa_nome||'Empresa a definir')}</h2>
        <p>Tipo: ${esc(tipos[x.tipo]||'—')} · Requisição: ${esc(x.requisicao_numero||'—')} · Empenho: ${esc(x.empenho_numero||'—')} · Data do empenho: ${shortDate(x.empenho_data)} · Prazo: ${shortDate(x.prazo_30_dias)}</p>
        <p>Localizador / rastreio: ${esc(x.rastreio||'—')} · Entrega: ${shortDate(x.entrega_data)} · Situação: ${acquisitionStatus(x)}</p>
        ${table(['ITEM','CÓD CatMat/CatServ','Descrição do material / serviço','UND','QTD','ND / S.I.','P. UNT','P. TOTAL','NC'],
          (x.itens||[]).map(i=>[esc(i.item),esc(i.codigo_catmat_catserv),esc(i.descricao),esc(i.unidade),esc(i.quantidade),esc(i.nd_si),money(i.preco_unitario),money(i.preco_total),esc(ncById(i.nc_id)?.numero||'—')]))}
        <p>Liquidação: ${esc(x.liquidacao_numero||'—')} · Observações: ${esc(x.observacao||'—')}</p></section>`).join('')+'<h2>Saldo das notas de crédito</h2>'+table(['NC','Data','Tipo','UG','Valor da NC','Itens cadastrados','Crédito restante'],(S.ncsFS||[]).map(n=>[esc(n.numero),shortDate(n.data),esc(ncTipos[n.tipo]||n.tipo),esc(n.ug),money(n.valor),money(n.utilizado),Number(n.saldo)<0?'Excedido: '+money(-Number(n.saldo)):money(n.saldo)])));
      if(type==='companies')printHtml('Empresas',table(['Nome','CNPJ','Telefone','E-mail'],
        (S.empresasFS||[]).map(x=>[esc(x.nome),esc(x.cnpj),esc(x.telefone),esc(x.email)])));
      if(type==='paassex'){
        const requested=(S.paassex||[]).filter(x=>!x.autorizado),approved=(S.paassex||[]).filter(x=>x.autorizado);
        printHtml('PAASSEx',`<h2>Itens solicitados</h2>`+
          table(['Ano','Item','Descrição','Valor','Pregão'],requested.map(x=>[esc(x.ano),esc(x.nome),esc(x.descricao),money(x.valor),esc(x.pregao||'—')]))+
          `<p>Total solicitado: <strong>${money(sum(requested))}</strong></p><h2>Itens autorizados</h2>`+
          table(['Ano','Item','Descrição','Valor','Pregão','Autorizado em'],approved.map(x=>[
            esc(x.ano),esc(x.nome),esc(x.descricao),money(x.valor),esc(x.pregao||'—'),esc(x.autorizado_em||'—')]))+
          `<p>Total autorizado: <strong>${money(sum(approved))}</strong></p>`);
      }
      return true;
    }
    return false;
  }
  function change(element) {
    const row=element.closest('[data-fs-item]');
    if(row&&['quantidade','preco_unitario'].includes(element.name)){
      const qty=Number(row.querySelector('[name="quantidade"]').value),price=Number(row.querySelector('[name="preco_unitario"]').value);
      row.querySelector('[data-item-total]').value=row.querySelector('[name="quantidade"]').value&&row.querySelector('[name="preco_unitario"]').value?(qty*price).toFixed(2):'';
      return true;
    }
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
