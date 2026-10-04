"""Small local browser views for the medications marketplace."""

STYLE = """<style>body{font:16px system-ui;max-width:980px;margin:2rem auto;padding:0 1rem;color:#183047;background:#f6f9fb}h1{font-size:1.7rem}section,article{background:white;border:1px solid #d9e3e9;border-radius:10px;padding:1rem;margin:1rem 0}input,button{font:inherit;padding:.5rem;margin:.2rem}input{max-width:95%}button{background:#166b83;color:white;border:0;border-radius:5px;cursor:pointer}.muted{color:#526674}.error{color:#a33232}a{color:#166b83}ul{padding-left:1.3rem}li{margin:.4rem 0}table{width:100%;border-collapse:collapse}td,th{padding:.4rem;border-bottom:1px solid #e6eef2;text-align:left}.pay{margin-top:.6rem;padding:.7rem;background:#e6f0f4;border-radius:6px}.pay a{font-weight:600}</style>"""

PATIENT = """<!doctype html><html lang=ru><meta charset=utf-8><meta name=viewport content='width=device-width, initial-scale=1'><title>Лекарства по рецепту</title>""" + STYLE + """
<h1>Лекарства по рецепту</h1><p class=muted>Показываются только препараты, соответствующие вашему подтверждённому рецепту. Оплата и доставка — на стороне аптеки-партнёра.</p>
<section><input id=ref placeholder='Псевдоним пациента' autocomplete=off><input id=token type=password placeholder='Токен' autocomplete=off><button id=load>Показать</button></section>
<main id=result></main>
<script>
const result=document.getElementById('result');
function el(tag,text,parent){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;parent.append(n);return n}
async function api(path,options={}){const r=await fetch(path,{...options,headers:{Authorization:'Bearer '+document.getElementById('token').value,...(options.headers||{})}});if(!r.ok)throw Error('Ошибка '+r.status);return r.json()}
document.getElementById('load').onclick=async()=>{result.replaceChildren();try{
 const data=await api('/v1/offers');
 if(!data.prescriptions.length){el('p','Рецепты не найдены',result);return}
 for(const p of data.prescriptions){const card=el('article','',result);el('h2','Рецепт '+p.id,card);
  el('p','Врач: '+p.physician_id+', действует до '+p.expires_at,card);
  el('p','Заключение: '+p.conclusion,card);
  const offers=await api('/v1/prescriptions/'+p.id+'/offers');
  for(const item of offers.offers){const block=el('div','',card);
   el('h3',item.inn+' '+item.form+' '+item.strength,block);
   el('p','Назначено: '+item.quantity+' шт., '+item.dosage+', '+item.duration_days+' дней',block);
   if(item.reason){el('p','Нет в наличии у партнёров: '+item.reason,block).className='error';continue}
   const table=el('table','',block);
   const hdr=el('tr','',table);el('th','Аптека',hdr);el('th','Препарат',hdr);el('th','Цена',hdr);el('th','Наличие',hdr);el('th','',hdr);
   for(const opt of item.options){const tr=el('tr','',table);
    el('td',opt.pharmacy_name,tr);el('td',opt.trade_name+(opt.is_substitution?' (аналог)':''),tr);
    el('td',opt.price+' '+opt.currency,tr);el('td',String(opt.stock),tr);
    const td=el('td','',tr);const btn=el('button','Заказать',td);
    btn.onclick=async()=>{try{
     const order=await api('/v1/orders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prescription_id:p.id,pharmacy_id:opt.pharmacy_id,items:[{medication_id:opt.medication_id,quantity:item.quantity}]})});
     const done=el('div','pay',block);
     el('p','Заказ '+order.id+' создан: '+order.status+', сумма '+order.total+' '+order.currency,done);
     if(order.redirect_url){const link=el('a','Перейти к оплате в '+opt.pharmacy_name+' →',done);link.href=order.redirect_url;link.target='_blank';link.rel='noopener';el('p','Откроется сайт аптеки-партнёра. Здесь оплата не проводится.',done).className='muted'}
    }catch(e){el('p',e.message,block).className='error'}}}
  }
 }
}catch(e){el('p',e.message,result).className='error'}};
</script></html>"""

STAFF = """<!doctype html><html lang=ru><meta charset=utf-8><meta name=viewport content='width=device-width, initial-scale=1'><title>Заказы аптеки</title>""" + STYLE + """
<h1>Заказы аптеки</h1><section><input id=token type=password placeholder='Токен сотрудника' autocomplete=off><button id=load>Обновить</button></section><main id=result></main>
<script>
const result=document.getElementById('result');function el(tag,text,parent){const n=document.createElement(tag);n.textContent=text;parent.append(n);return n}
async function api(path,options={}){const r=await fetch(path,{...options,headers:{Authorization:'Bearer '+document.getElementById('token').value,...(options.headers||{})}});if(!r.ok)throw Error('Ошибка '+r.status);return r.json()}
document.getElementById('load').onclick=async()=>{result.replaceChildren();try{
 const [queue,metrics]=await Promise.all([api('/v1/staff/queue'),api('/v1/staff/metrics')]);
 const m=el('section','',result);el('h2','Показатели',m);el('pre',JSON.stringify(metrics,null,2),m);
 el('h2','Очередь заказов',result);if(!queue.cases.length)el('p','Заказов нет',result);
 for(const item of queue.cases){const card=el('article','',result);el('h3',item.order_id+' — '+item.status,card);el('p','Аптека: '+item.pharmacy_id+', пациент: '+item.patient_ref,card);el('p','Сумма: '+item.total+' '+item.currency,card);
  const actions=el('div','',card);
  for(const action of ['confirm','ready','picked_up','cancel','fail']){const b=el('button',action,actions);b.onclick=async()=>{try{await api('/v1/orders/'+item.order_id+'/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});document.getElementById('load').click()}catch(e){el('p',e.message,card).className='error'}}}
 }
}catch(e){el('p',e.message,result).className='error'}};
</script></html>"""