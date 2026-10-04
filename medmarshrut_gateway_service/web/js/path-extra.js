/* Задание 04: работа врача, правила и аналитика на данных сервиса пути. */
import {api} from './api.js';
import {state, sessions} from './state.js';
import {badge, btn, closeModal, errorNote, loadingCards, modalHead, openModal, safe, toast} from './ui.js';
import {render} from './shell.js';

const data = {status:'loading', role:null, page:null, visits:[], episodes:[], rules:null, catalog:null, metrics:null, dry:null, message:''};
const fmt = v => v ? new Date(v).toLocaleString('ru-RU') : '';
const head = (title, text) => `<div class="pagehead"><div><div class="eyebrow">Демо-стенд</div><h1>${title}</h1><p>${text}</p></div></div>`;
const gate = () => data.status === 'error' ? errorNote(data.message, 'pathExtraRetry') : loadingCards();
const ready = () => data.status === 'ok' && data.role === state.role && data.page === state.page;
const route = () => state.role === 'doctor' && ['doctor','case'].includes(state.page) || state.role === 'staff' && ['rules','analytics'].includes(state.page);

export async function refreshPathExtra(){
  if (!route() || sessions[state.role]?.status !== 'ok') return;
  const role = state.role, page = state.page;
  data.status = 'loading'; data.role = role; data.page = page; render();
  try {
    if (page === 'doctor' || page === 'case') {
      const [visits, episodes, rules, catalog] = await Promise.all([
        api('GET','/api/doctor/visits',{role}), api('GET','/api/staff/episodes',{role}),
        api('GET','/api/staff/rules',{role}), api('GET','/api/catalog',{role})]);
      data.visits = visits.visits || []; data.episodes = episodes.episodes || [];
      data.rules = rules; data.catalog = catalog;
      state.doctorVisitCount = data.visits.filter(v => v.episode.steps.find(s => s.id === v.step_id)?.status === 'attended').length;
    } else if (page === 'rules') data.rules = await api('GET','/api/staff/rules',{role});
    else data.metrics = await api('GET','/api/staff/metrics',{role});
    data.status = 'ok'; data.message = '';
  } catch (err) { data.status = 'error'; data.message = 'Не удалось загрузить данные. ' + err.message; }
  if (role === state.role && page === state.page) render();
}

export function pathDoctor(){
  const intro = head('Мои пациенты','После приёма внесите итог, чтобы план пациента обновился.');
  if (!ready()) return intro + gate();
  const card = item => { const e = item.episode, s = e.steps.find(x => x.id === item.step_id);
    return `<div class="card">${badge(s?.status === 'attended' ? 'Ждём итог врача' : 'Записан на приём', 'orange')}
      <h3>${safe(e.patient)}</h3><p>${safe(s?.description)} · ${safe(fmt(s?.appointment_at))}</p><div class="actions">
      <button class="btn secondary small" data-case="${safe(e.id)}">Открыть карточку</button>
      ${btn('Итог приёма','pathOutcomeOpen','small',{id:e.id,step:s.id})}</div></div>`; };
  const waiting = data.visits.filter(v => v.episode.steps.find(s => s.id === v.step_id)?.status === 'attended');
  const booked = data.visits.filter(v => v.episode.steps.find(s => s.id === v.step_id)?.status === 'confirmed');
  return intro + `<div class="sectionhead"><h2>Ждут итога приёма</h2></div><div class="grid two">${waiting.map(card).join('') || '<div class="note">Итоги внесены.</div>'}</div>
    <div class="sectionhead"><h2>Записаны на приём</h2></div><div class="grid two">${booked.map(card).join('') || '<div class="note">Записей пока нет.</div>'}</div>`;
}

const reason = value => ({rule_not_approved:'Правило ещё не утверждено клиникой: нужен план врача',
  unknown_finding_code:'Для этой находки в клинике нет правила', no_approved_rule:'Правило есть, но не для этого исследования',
  unsupported_protocol:'Для такого исследования в клинике нет маршрутов'})[value] || value;
export function pathRules(){
  const intro = head('Маршруты и правила','Маршрутизатор применяет только утверждённые правила.');
  if (!ready()) return intro + gate();
  const rules = data.rules?.rules || [];
  return intro + `<div class="note">Версия ${safe(data.rules?.version)}. Правила утверждает клиника. Они меняются в файле правил вместе с версией.</div>
    <div class="sectionhead"><h2>Правила маршрута после исследований</h2></div><div class="tablewrap"><table><thead><tr><th>Исследование</th><th>Находка</th><th>Следующий шаг</th><th>Статус</th></tr></thead><tbody>
    ${rules.map(r => `<tr><td>${safe(r.study_type)} · ${safe(r.anatomy)} · ${safe(r.protocol_name)}</td><td>${safe(r.finding_code)}</td>
      <td>${r.steps.map(s => safe(s.description)).join(' + ') || 'План врача'}</td><td>${badge(r.approved ? 'Утверждено' : 'Черновик',r.approved ? '' : 'orange')}</td></tr>`).join('')}</tbody></table></div>
    <div class="sectionhead"><h2>Проверить правило</h2></div><div class="panel"><div class="field"><label for="pathRule">Исследование и находка</label>
    <select id="pathRule">${rules.map((r,i) => `<option value="${i}">${safe(r.study_type)} · ${safe(r.finding_code)}</option>`).join('')}</select></div>
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

function candidates(e){
  const report = e.source_report || {};
  const rule = (data.rules?.rules || []).find(r => r.study_type === report.study_type && r.anatomy === report.anatomy &&
    r.protocol_name === report.protocol_name && r.finding_code === report.finding_code);
  if (rule && !rule.approved) return rule.steps.map(s => ({...s,checked:true}));
  const services = new Map((data.catalog?.services || []).map(s => [s.code,s]));
  return (data.catalog?.followups || []).filter(f => f.finding_code === report.finding_code).map(f => ({
    kind:services.get(f.service_code)?.kind || 'appointment',description:services.get(f.service_code)?.title || f.service_code,
    checked:f.is_default,due_days:f.due_days,due_note:f.due_note}));
}
const custom = () => `<div class="field"><label for="pathCustom">Другой шаг (если нужен)</label><input id="pathCustom" maxlength="500"></div>
  <div class="field"><label for="pathKind">Вид шага</label><select id="pathKind"><option value="appointment">Приём</option><option value="test">Исследование</option><option value="follow_up">Наблюдение</option><option value="care_coordination">Помощь координатора</option></select></div>`;
function chosen(items, full){
  const selected = [...document.querySelectorAll('[data-path-step]:checked')].map(el => items[Number(el.dataset.pathStep)]);
  const free = document.querySelector('#pathCustom')?.value.trim();
  if (free) selected.push({kind:document.querySelector('#pathKind').value,description:free});
  return selected.map(s => full ? {kind:s.kind,description:s.description,due_at:Number.isInteger(s.due_days) ?
    new Date(Date.parse(data.formAt)+s.due_days*86400000).toISOString() : null} : {kind:s.kind,description:s.description});
}
function form(e,step,mode){
  const items = candidates(e), event = mode === 'outcome' ? crypto.randomUUID() : '';
  const rows = items.map((s,i) => `<label class="checkline"><input type="checkbox" data-path-step="${i}" ${s.checked ? 'checked' : ''}><span><strong>${safe(s.description)}</strong>${s.due_note ? `<br><small>${safe(s.due_note)}</small>` : ''}</span></label>`).join('');
  openModal(`${modalHead(mode === 'outcome' ? 'Итог приёма' : 'План врача',safe(e.patient))}
    ${mode === 'outcome' ? `<div class="field"><label for="pathSummary">Краткий итог</label><textarea id="pathSummary" maxlength="1000"></textarea></div>` : ''}
    ${mode === 'revise' ? `<div class="field"><label for="pathReason">Почему меняется план</label><input id="pathReason" maxlength="500"></div>` : ''}
    <div class="field"><label>Следующие шаги</label>${rows || '<p>Добавьте шаг по решению врача.</p>'}</div>${custom()}
    ${mode === 'outcome' ? '<label class="checkline"><input type="checkbox" id="outRx"><span>Выписать электронный рецепт · демо</span></label>' : ''}
    <div class="note">Новые шаги появляются только после решения врача.</div>
    <div class="actions">${btn('Сохранить','pathDoctorSave','',{id:e.id,step:step?.id || '',mode,event})}${btn('Отмена','close','secondary')}</div>`,true);
  data.formItems = items;
  data.formAt = new Date().toISOString();
}
async function send(route,body){
  try { await api('POST',route,{role:state.role,body}); closeModal(); await refreshPathExtra(); toast('План обновлён'); }
  catch (err) { toast(err.message); }
}
export function installPathExtra(actions){
  actions.pathExtraRetry = refreshPathExtra;
  actions.pathDryRun = async () => { const r = data.rules?.rules?.[Number(document.querySelector('#pathRule')?.value)]; if (!r) return;
    try { data.dry = await api('POST','/api/staff/rules/dry-run',{role:state.role,body:{study_type:r.study_type,
      anatomy:r.anatomy,protocol_name:r.protocol_name,finding_code:r.finding_code}}); render(); }
    catch (err) { toast(err.message); } };
  actions.pathOutcomeOpen = d => { const e = data.episodes.find(x => x.id === d.id), s = e?.steps.find(x => x.id === d.step); if (e && s) form(e,s,'outcome'); };
  actions.pathPlanOpen = d => { const e = data.episodes.find(x => x.id === d.id); if (e) form(e,null,'manual'); };
  actions.pathReviseOpen = d => { const e = data.episodes.find(x => x.id === d.id); if (e) form(e,null,'revise'); };
  actions.pathDoctorSave = d => { const steps = chosen(data.formItems || [],d.mode !== 'manual');
    const root = `/api/doctor/episodes/${encodeURIComponent(d.id)}`;
    if (d.mode === 'outcome') send(`${root}/steps/${encodeURIComponent(d.step)}/outcome`,{event_id:d.event,
      summary:document.querySelector('#pathSummary')?.value.trim(),next_steps:steps});
    else if (d.mode === 'revise') send(`${root}/revise-plan`,{reason:document.querySelector('#pathReason')?.value.trim(),steps});
    else send(`${root}/manual-plan`,{steps}); };
}
