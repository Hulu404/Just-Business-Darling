"""Small local browser view for clinic staff; tokens stay in page memory."""

STYLE = """<style>body{font:16px system-ui;max-width:980px;margin:2rem auto;padding:0 1rem;color:#183047;background:#f6f9fb}h1{font-size:1.7rem}section,article{background:white;border:1px solid #d9e3e9;border-radius:10px;padding:1rem;margin:1rem 0}input,button,textarea{font:inherit;padding:.5rem;margin:.2rem}input,textarea{max-width:95%}button{background:#166b83;color:white;border:0;border-radius:5px;cursor:pointer}.muted{color:#526674}.error{color:#a33232}ul{padding-left:1.3rem}li{margin:.4rem 0}.tag{display:inline-block;background:#e6f0f4;color:#166b83;border-radius:4px;padding:.1rem .45rem;margin-right:.3rem;font-size:.85rem}</style>"""

STAFF = """<!doctype html><html lang=ru><meta charset=utf-8><meta name=viewport content='width=device-width, initial-scale=1'><title>Карта пациента клиники</title>""" + STYLE + """
<h1>Карта пациента клиники</h1><p class=muted>Локальное демо. Введите токен сотрудника клиники.</p>
<section><input id=token type=password placeholder='Токен сотрудника' autocomplete=off><button id=load>Загрузить</button></section>
<main id=result></main>
<script>
const result=document.getElementById('result');
function el(tag,text,parent){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;parent.append(n);return n}
async function api(path,options={}){const r=await fetch(path,{...options,headers:{Authorization:'Bearer '+document.getElementById('token').value,...(options.headers||{})}});if(!r.ok)throw Error('Ошибка '+r.status);return r.json()}
document.getElementById('load').onclick=async()=>{result.replaceChildren();try{
 const [clinics,queue,metrics]=await Promise.all([api('/v1/clinics'),api('/v1/staff/queue'),api('/v1/staff/metrics')]);
 const c=el('section','',result);el('h2','Клиники сети',c);
 for(const item of clinics.clinics){const line=el('p','',c);el('span',item.name+' ('+item.id+')',line);if(item.network)el('span',' · '+item.network,line)}
 const m=el('section','',result);el('h2','Показатели',m);el('pre',JSON.stringify(metrics,null,2),m);
 el('h2','Очередь',result);if(!queue.cases.length)el('p','Очередь пуста',result);
 for(const item of queue.cases){const card=el('article','',result);el('h3',item.kind+' · '+item.patient_ref,card);
  el('p','referral '+item.referral_id,card);
    const button=el('button','Открыть карту',card);
  button.onclick=async()=>{try{const data=await api('/v1/patients/'+item.patient_id+'/card');
   const details=el('article','',card);el('h3','Карта пациента',details);
   el('pre',JSON.stringify(data,null,2),details)}
   catch(e){el('p',e.message,card).className='error'}}}
}catch(e){el('p',e.message,result).className='error'}};
</script></html>"""