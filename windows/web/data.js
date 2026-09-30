export const CATEGORIES=['Medicamentos Orais','Medicamentos Injetáveis','Medicamentos Controlados','Pomadas','Outros','Material/Medicamento Odontológico','Materiais','Soro'];
export const PENDING=['NOVO','EM_SEPARACAO','PRONTO'];
export const norm=v=>String(v??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
export const number=v=>Number.isFinite(Number(v))?Number(v):0;
export function dateValue(value){
 if(!value)return null;
 const s=String(value),br=s.match(/^(\d{2})\/(\d{2})\/(\d{4})(?:[ T](\d{2}):(\d{2}))?/),iso=s.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/);
 if(!br&&!iso)return null;
 const [y,m,d,hh,mm]=br?[+br[3],+br[2],+br[1],+(br[4]||0),+(br[5]||0)]:[+iso[1],+iso[2],+iso[3],+(iso[4]||0),+(iso[5]||0)];
 const dt=new Date(y,m-1,d,hh,mm);
 return dt.getFullYear()===y&&dt.getMonth()===m-1&&dt.getDate()===d&&hh<24&&mm<60?dt:null;
}
export function daysLeft(value,today=new Date()){
 const d=dateValue(value);if(!d)return null;
 return Math.round((Date.UTC(d.getFullYear(),d.getMonth(),d.getDate())-Date.UTC(today.getFullYear(),today.getMonth(),today.getDate()))/86400000);
}
export function validity(value,today=new Date()){
 const days=daysLeft(value,today);
 if(days===null)return {key:'unknown',label:'Sem data válida',tone:'neutral',days};
 if(days<0)return {key:'critical',label:'Vencido',tone:'danger',days};
 if(days<=90)return {key:'critical',label:days===0?'Vence hoje':'Até 90 dias',tone:'danger',days};
 if(days<=120)return {key:'attention',label:'91 a 120 dias',tone:'warning',days};
 return {key:'regular',label:'Acima de 120 dias',tone:'success',days};
}
export function externalAlerts(lots,today=new Date(),lowLimit=5){
 const result={critical:0,attention:0,low:0};
 for(const lot of lots){
  const stock=number(lot.estoque_atual);
  if(stock<=lowLimit)result.low++;
  if(stock>0){const status=validity(lot.validade,today).key;if(status==='critical'||status==='attention')result[status]++}
 }
 return result;
}
export function aggregateLots(lots){
 const map=new Map();
 for(const lot of lots){const key=lot.categoria+'\u0000'+lot.medicamento;let item=map.get(key);if(!item){item={key,categoria:lot.categoria,medicamento:lot.medicamento,estoque_total:0,lotes:[],comprimidos_por_cartela:[]};map.set(key,item)}item.estoque_total+=number(lot.estoque_atual);item.lotes.push(lot);if(lot.comprimidos_cartela&&!item.comprimidos_por_cartela.includes(lot.comprimidos_cartela))item.comprimidos_por_cartela.push(lot.comprimidos_cartela);}
 return [...map.values()].sort((a,b)=>a.medicamento.localeCompare(b.medicamento,'pt-BR'));
}
export function stockMetrics(lots,today=new Date()){
 const items=aggregateLots(lots),bins={critical:0,attention:0,regular:0,unknown:0};
 for(const lot of lots)if(number(lot.estoque_atual)>0)bins[validity(lot.validade,today).key]++;
 return {items:items.filter(x=>x.estoque_total>0).length,zero:items.filter(x=>x.estoque_total<=0).length,stockedLots:lots.filter(x=>number(x.estoque_atual)>0).length,bins};
}
export function movementDelta(m){
 if(m.estoque_anterior!==undefined&&m.estoque_final!==undefined)return number(m.estoque_final)-number(m.estoque_anterior);
 const t=norm(m.tipo);if(t.includes('entrada')||t.includes('estorno'))return number(m.quantidade);
 if(t.includes('saida')||t.includes('retirada'))return -number(m.quantidade??m.retirada);
 return 0;
}
export function movementsByDay(moves,today=new Date(),length=7){
 const rows=Array.from({length},(_,i)=>{const date=new Date(today.getFullYear(),today.getMonth(),today.getDate()-length+1+i);return {date,label:date.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'}),entrada:0,saida:0}});
 for(const m of moves){const dt=dateValue(m.data);if(!dt)continue;const row=rows.find(r=>r.date.toDateString()===dt.toDateString());if(!row)continue;const delta=movementDelta(m);row[delta>=0?'entrada':'saida']+=Math.abs(delta)}return rows;
}
export function topRequested(orders,today=new Date(),length=30){
 const start=new Date(today.getFullYear(),today.getMonth(),today.getDate()-length+1),end=new Date(today.getFullYear(),today.getMonth(),today.getDate()+1),map=new Map();
 for(const order of orders){const date=dateValue(order.data);if(!date||date<start||date>=end||order.status==='CANCELADO')continue;for(const item of order.itens||[]){if(String(item.status||'').startsWith('CANCELADO'))continue;const key=item.categoria+'\u0000'+item.medicamento;const x=map.get(key)||{name:item.medicamento,categoria:item.categoria,value:0};x.value+=number(item.quantidade);map.set(key,x)}}return [...map.values()].sort((a,b)=>b.value-a.value).slice(0,5);
}
export function filterLots(lots,{query='',category='',filter='all'}={}){
 const q=norm(query),zero=new Set(aggregateLots(lots).filter(x=>x.estoque_total<=0).map(x=>x.key));
 return lots.filter(l=>{if(category&&l.categoria!==category)return false;if(q&&!norm([l.medicamento,l.ficha,l.categoria,l.localizador].join(' ')).includes(q))return false;if(filter==='zero')return zero.has(l.categoria+'\u0000'+l.medicamento);if(filter==='positive')return number(l.estoque_atual)>0;if(filter==='all')return true;const v=validity(l.validade);if(number(l.estoque_atual)<=0)return false;return filter==='due'?['critical','attention'].includes(v.key):v.key===filter});
}
