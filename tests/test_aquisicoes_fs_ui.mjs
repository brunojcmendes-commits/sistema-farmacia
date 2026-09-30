import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const source=await readFile(new URL('../windows/web/aquisicoes_fs.js',import.meta.url),'utf8');
const {createAquisicoesFS}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
let printed=null;
const fs=createAquisicoesFS({api:async()=>{},esc:x=>String(x??''),table:(headers,rows)=>JSON.stringify({headers,rows}),
 panel:()=>'',field:()=>'',formDialog:()=>{},printHtml:(title,html)=>{printed={title,html}},toast:()=>{},
 S:{ncsFS:[{id:7,numero:'NC-07',data:'2026-09-30',tipo:'consumo',ug:'160001',valor:'2000.00',utilizado:'1500.00',saldo:'500.00'}],paassex:[{ano:2026,nome:'A',descricao:'Solicitado',valor:'750.00',pregao:'PE-01',autorizado:0},{ano:2026,nome:'B',descricao:'Autorizado',valor:'850.00',pregao:'PE-02',autorizado:1}],aquisicoesFS:[{id:8,material:'Material A',empresa_nome:'Empresa Teste',itens:[
  {item:'1',codigo_catmat_catserv:'123',descricao:'Material A',unidade:'UN',quantidade:'10',nd_si:'3.3.90.30',preco_unitario:'25.00',preco_total:'250.00',nc_id:7},
  {item:'2',codigo_catmat_catserv:'456',descricao:'Material B',unidade:'CX',quantidade:'3',nd_si:'3.3.90.30',preco_unitario:'40.00',preco_total:'120.00'}]}]},render:()=>{}});
assert.equal(await fs.click({dataset:{fs:'print-acquisitions'}}),true);
assert.equal(printed.title,'Aquisições FS');
assert.match(printed.html,/Material A/);
assert.match(printed.html,/Material B/);
assert.match(printed.html,/123/);
assert.match(printed.html,/250,00/);
assert.match(printed.html,/NC-07/);
assert.match(printed.html,/500,00/);
assert.equal(await fs.click({dataset:{fs:'print-paassex'}}),true);
assert.match(printed.html,/750,00/);
assert.match(printed.html,/850,00/);
assert.match(printed.html,/PE-02/);
console.log('Aquisições FS: botão de impressão e itens do relatório OK.');
