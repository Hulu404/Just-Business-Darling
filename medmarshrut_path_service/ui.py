"""Small local browser views; tokens stay in page memory and are not persisted."""

STYLE = """<style>body{font:16px system-ui;max-width:920px;margin:2rem auto;padding:0 1rem;color:#183047;background:#f6f9fb}h1{font-size:1.7rem}section,article{background:white;border:1px solid #d9e3e9;border-radius:10px;padding:1rem;margin:1rem 0}input,button{font:inherit;padding:.55rem;margin:.2rem}input{max-width:95%}button{background:#166b83;color:white;border:0;border-radius:5px;cursor:pointer}.muted{color:#526674}.error{color:#a33232}ul{padding-left:1.3rem}li{margin:.5rem 0}</style>"""

PATIENT = """<!doctype html><html lang=ru><meta charset=utf-8><meta name=viewport content='width=device-width, initial-scale=1'><title>Мой маршрут</title>""" + STYLE + """
<h1>Мой маршрут</h1><p class=muted>Локальное демо. Введите псевдоним и выданный порталом токен.</p>
<section><input id=ref placeholder='Псевдоним пациента' autocomplete=off><input id=token type=password placeholder='Токен' autocomplete=off><button id=load>Показать</button></section><main id=result></main>
<script>
const result=document.getElementById('result');
function el(tag,text,parent){const n=document.createElement(tag);n.textContent=text;parent.append(n);return n}
document.getElementById('load').onclick=async()=>{result.replaceChildren();try{
 const ref=document.getElementById('ref').value,token=document.getElementById('token').value;
 const response=await fetch('/v1/patient/'+encodeURIComponent(ref),{headers:{Authorization:'Bearer '+token}});
 if(!response.ok)throw Error('Доступ не получен ('+response.status+')');
 const data=await response.json();if(!data.episodes.length){el('p','Эпизоды не найдены',result);return}
 for(const ep of data.episodes){const card=el('article','',result);el('h2','Эпизод '+ep.episode_id,card);
 el('h3','Что сделать сейчас',card);el('p',ep.do_now?ep.do_now.description+' — '+ep.do_now.status+(ep.do_now.appointment_at?' ('+ep.do_now.appointment_at+')':''):'Сейчас нет активного действия',card);
 el('h3','История плана',card);const list=el('ul','',card);for(const s of ep.plan_history)el('li','Цикл '+s.cycle+': '+s.description+' — '+s.status,list)}
}catch(e){el('p',e.message,result).className='error'}};
</script></html>"""

STAFF = """<!doctype html><html lang=ru><meta charset=utf-8><meta name=viewport content='width=device-width, initial-scale=1'><title>Очередь координатора</title>""" + STYLE + """
<h1>Очередь координатора</h1><section><input id=token type=password placeholder='Токен сотрудника' autocomplete=off><button id=load>Обновить</button></section><main id=result></main>
<script>
const result=document.getElementById('result');function el(tag,text,parent){const n=document.createElement(tag);n.textContent=text;parent.append(n);return n}
async function api(path,options={}){const response=await fetch(path,{...options,headers:{Authorization:'Bearer '+document.getElementById('token').value,...(options.headers||{})}});if(!response.ok)throw Error('Ошибка '+response.status);return response.json()}
document.getElementById('load').onclick=async()=>{result.replaceChildren();try{
 const [queue,metrics]=await Promise.all([api('/v1/staff/queue'),api('/v1/staff/metrics')]);
 const metric=el('section','',result);el('h2','Показатели',metric);el('pre',JSON.stringify(metrics,null,2),metric);
 el('h2','Случаи для продолжения',result);if(!queue.cases.length)el('p','Очередь пуста',result);
 for(const item of queue.cases){const card=el('article','',result);el('h3',item.episode_id+' — '+item.status,card);el('p','Причины: '+item.reasons.join(', '),card);el('p','Действия: '+item.actions.join(', '),card);
 const button=el('button','Открыть случай',card);button.onclick=async()=>{try{const ep=await api('/v1/episodes/'+item.episode_id);const pre=card.querySelector('pre')||el('pre','',card);pre.textContent=JSON.stringify({plan_steps:ep.plan_steps,audit_events:ep.audit_events},null,2)}catch(e){el('p',e.message,card).className='error'}}}
}catch(e){el('p',e.message,result).className='error'}};
</script></html>"""
