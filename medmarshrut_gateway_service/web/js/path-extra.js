/* Задание 04: правила и аналитика координатора на данных сервиса пути. Работа врача — в кабинете rescan (задание 12). */
import {api} from './api.js';
import {state, sessions} from './state.js';
import {badge, btn, errorNote, loadingCards, safe, toast} from './ui.js';
import {render} from './shell.js';

const data = {status:'loading', role:null, page:null, rules:null, metrics:null, dry:null, message:''};
const head = (title, text) => `<div class="pagehead"><div><div class="eyebrow">Демо-стенд</div><h1>${title}</h1><p>${text}</p></div></div>`;
const gate = () => data.status === 'error' ? errorNote(data.message, 'pathExtraRetry') : loadingCards();
const ready = () => data.status === 'ok' && data.role === state.role && data.page === state.page;
const route = () => state.role === 'staff' && ['rules','analytics'].includes(state.page);

export async function refreshPathExtra(){
  if (!route() || sessions[state.role]?.status !== 'ok') return;
  const role = state.role, page = state.page;
  data.status = 'loading'; data.role = role; data.page = page; render();
  try {
    if (page === 'rules') data.rules = await api('GET','/api/staff/rules',{role});
    else data.metrics = await api('GET','/api/staff/metrics',{role});
    data.status = 'ok'; data.message = '';
  } catch (err) { data.status = 'error'; data.message = 'Не удалось загрузить данные. ' + err.message; }
  if (role === state.role && page === state.page) render();
}

/* Вид исследования по-русски: коды сервиса пути не показываем */
const studyLabel = type => ({ct:'КТ', mr:'МРТ', mammography:'Маммография', xray:'Рентгенография'})[type] || type;
const reason = value => ({rule_not_approved:'Правило ещё не утверждено клиникой: нужен план врача',
  unknown_finding_code:'Для этой находки в клинике нет правила', no_approved_rule:'Правило есть, но не для этого исследования',
  unsupported_protocol:'Для такого исследования в клинике нет маршрутов'})[value] || value;
export function pathRules(){
  const intro = head('Маршруты и правила','Маршрутизатор применяет только утверждённые правила.');
  if (!ready()) return intro + gate();
  const rules = data.rules?.rules || [];
  return intro + `<div class="note">Версия ${safe(data.rules?.version)}. Правила утверждает клиника. Они меняются в файле правил вместе с версией.</div>
    <div class="sectionhead"><h2>Правила маршрута после исследований</h2></div><div class="tablewrap"><table><thead><tr><th>Исследование</th><th>Находка</th><th>Следующий шаг</th><th>Статус</th></tr></thead><tbody>
    ${rules.map(r => `<tr><td>${safe(studyLabel(r.study_type))} · ${safe(r.anatomy)} · ${safe(r.protocol_name)}</td><td>${safe(r.finding_code)}</td>
      <td>${r.steps.map(s => safe(s.description)).join(' + ') || 'План врача'}</td><td>${badge(r.approved ? 'Утверждено' : 'Черновик',r.approved ? '' : 'orange')}</td></tr>`).join('')}</tbody></table></div>
    <div class="sectionhead"><h2>Проверить правило</h2></div><div class="panel"><div class="field"><label for="pathRule">Исследование и находка</label>
    <select id="pathRule">${rules.map((r,i) => `<option value="${i}">${safe(studyLabel(r.study_type))} · ${safe(r.finding_code)}</option>`).join('')}</select></div>
    <div class="actions">${btn('Проверить','pathDryRun')}</div>${data.dry ? `<div class="note" style="margin-top:14px">${data.dry.manual_reason ? safe(reason(data.dry.manual_reason)) :
      data.dry.steps.map(s => safe(s.description)).join(' → ')}</div>` : ''}</div>`;
}

export function pathAnalytics(){
  const intro = head('Аналитика','Данные демо-стенда.');
  if (!ready()) return intro + gate();
  const m = data.metrics || {}, f = m.funnel || {}, n = Math.max(1,f.reports || 0);
  const rows = [['Подтверждённые заключения',f.reports || 0],['Активные маршруты',f.active || 0],
    ['Есть запись или выполненный шаг',f.booked || 0],['Завершены',f.completed || 0]];
  const c = state.calc || {n:0,base:0,target:0,check:0};
  const extra = Math.max(0,Math.round(c.n*(c.target-c.base)/100));
  return intro + `<div class="grid three"><div class="card"><div class="metric">${f.reports || 0}</div><span class="muted">заключений</span></div>
    <div class="card"><div class="metric">${m.attended_visits || 0}</div><span class="muted">визитов состоялось</span></div>
    <div class="card"><div class="metric">${m.unfinished_episodes || 0}</div><span class="muted">маршрутов не завершено</span></div></div>
    <div class="sectionhead"><h2>Воронка</h2></div><div class="panel">${rows.map(([label,value]) => `<div class="funnelrow"><div class="miniRow"><strong>${label}</strong><span>${value}</span></div><div class="bar"><i style="width:${Math.round(value/n*100)}%"></i></div></div>`).join('')}</div>
    <div class="sectionhead"><h2>Оценка эффекта для клиники</h2></div><div class="panel"><p>Поля ниже — ваши допущения.</p><div class="calc">${[['n','Заключений в месяц'],['base','Доходят сейчас, %'],['target','Доходят с сервисом, %'],['check','Средний чек, ₽']].map(([key,label]) =>
      `<div class="field"><label for="c${key}">${label}</label><input id="c${key}" type="number" min="0" data-calc="${key}" value="${safe(c[key])}"></div>`).join('')}</div>
      <div class="calcout" id="calcOut"><div><span>Дополнительных визитов в месяц</span><div class="metric">${extra}</div></div>
      <div><span>Дополнительная выручка в месяц</span><div class="metric">${(extra*c.check).toLocaleString('ru-RU')} ₽</div></div>
      <div><span>За год</span><div class="metric">${(extra*c.check*12).toLocaleString('ru-RU')} ₽</div></div></div></div>`;
}

export function installPathExtra(actions){
  actions.pathExtraRetry = refreshPathExtra;
  actions.pathDryRun = async () => { const r = data.rules?.rules?.[Number(document.querySelector('#pathRule')?.value)]; if (!r) return;
    try { data.dry = await api('POST','/api/staff/rules/dry-run',{role:state.role,body:{study_type:r.study_type,
      anatomy:r.anatomy,protocol_name:r.protocol_name,finding_code:r.finding_code}}); render(); }
    catch (err) { toast(err.message); } };
}
