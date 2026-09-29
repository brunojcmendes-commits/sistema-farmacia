import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const source=await readFile(new URL('../windows/web/aquisicoes_fs.js',import.meta.url),'utf8');
const {createAquisicoesFS}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
let printed=null;
const fs=createAquisicoesFS({api:async()=>{},esc:x=>String(x??''),table:(headers,rows)=>JSON.stringify({headers,rows}),
 panel:()=>'',field:()=>'',formDialog:()=>{},printHtml:(title,html)=>{printed={title,html}},toast:()=>{},
 S:{aquisicoesFS:[{id:8,material:'Material A',empresa_nome:'Empresa Teste',itens:[
  {item:'1',codigo_catmat_catserv:'123',descricao:'Material A',unidade:'UN',quantidade:'10',nd_si:'3.3.90.30',preco_unitario:'25.00',preco_total:'250.00'},
  {item:'2',codigo_catmat_catserv:'456',descricao:'Material B',unidade:'CX',quantidade:'3',nd_si:'3.3.90.30',preco_unitario:'40.00',preco_total:'120.00'}]}]},render:()=>{}});
assert.equal(await fs.click({dataset:{fs:'print-acquisitions'}}),true);
assert.equal(printed.title,'Aquisições FS');
assert.match(printed.html,/Material A/);
assert.match(printed.html,/Material B/);
assert.match(printed.html,/123/);
assert.match(printed.html,/250,00/);
console.log('Aquisições FS: botão de impressão e itens do relatório OK.');
