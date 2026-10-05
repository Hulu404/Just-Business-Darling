/* Этап 04/1: экраны маршрута читают сервис пути через шлюз. */
import { api } from './api.js';
import { state, sessions } from './state.js';
import { badge, btn, closeModal, errorNote, go, loadingCards, modalHead, navBtn, openModal, safe, toast } from './ui.js';
import { render } from './shell.js';
import { demoSource, manualStudiesBlock } from './imaging-ui.js';
import { caseClinicActions, caseClinicBlocks } from './clinic-ui.js';

const routePages = new Set(['home', 'plan', 'appointments', 'inbox', 'case', 'scheduling']);
export const isPathPage = () => routePages.has(state.page) && (state.role === 'patient' || state.role === 'staff');
const path = {role:null, status:'loading', items:[], requests:[], message:'', slots:[], slotStatus:'loading', slotMessage:'', slotKey:''};
const fmt = value => { if (!value) return ''; const d = new Date(value); return Number.isNaN(+d) ? String(value) : new Intl.DateTimeFormat('ru-RU', {day:'numeric', month:'long', hour:'2-digit', minute:'2-digit'}).format(d); };
export const current = e => e.steps.find(s => !['completed', 'superseded', 'closed'].includes(s.status));
const keyOf = (e, s) => `${e.id}:${s.id}`;
const byKey = key => { const [id, stepId] = String(key || '').split(':'); const e = path.items.find(x => x.id === id); return [e, e?.steps.find(s => s.id === stepId)]; };
export const statusName = status => ({open:'Нужно записаться', offered:'Предложена запись', confirmed:'Вы записаны', attended:'Ждём итог врача', completed:'Выполнено', cancelled:'Запись отменена', lost_contact:'Нет связи с пациентом', closed:'Закрыт', manual_review:'Врач уточняет план', paused:'Отложено', active:'В работе', superseded:'Заменён'})[status] || status;
const tone = status => ({open:'orange', offered:'blue', attended:'blue', manual_review:'orange', paused:'red', cancelled:'red', completed:'gray', closed:'gray', superseded:'gray'})[status] || '';
const header = (eyebrow, title, description = '') => `<div class="pagehead"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1>${description ? `<p>${description}</p>` : ''}</div></div>`;
const ready = () => path.role === state.role && path.status === 'ok';
const gate = () => !ready() ? path.status === 'error' ? errorNote(path.message, 'pathRetry') : loadingCards() : '';
const empty = text => `<div class="panel empty"><h3>${text}</h3></div>`;
const stepTitle = s => safe(s.description || 'Шаг плана');

export async function refreshPath(){
  if (!isPathPage() || sessions[state.role]?.status !== 'ok') return;
  const role = state.role;
  if (path.role !== role){ path.role = role; path.status = 'loading'; path.items = []; path.slots = []; }
  else if (path.status === 'error') path.status = 'loading';
  render();
  try {
    const route = role === 'patient' ? '/api/patient/episodes' : '/api/staff/episodes';
    const data = await api('GET', route, {role});
    if (state.role !== role) return;
    path.items = data.episodes || [];
    path.requests = data.patient_requests || [];
    state.pathCounts = {inbox:path.items.filter(e => e.status === 'manual_review' || e.status === 'paused' ||
      e.callback || ['open','attended'].includes(current(e)?.status)).length};
    path.status = 'ok'; path.message = '';
    if (state.page === 'appointments') await loadSlots();
  } catch (err){
    if (state.role !== role) return;
    path.status = 'error'; path.message = 'Не удалось загрузить маршрут. ' + err.message;
  }
  if (state.role === role) render();
}

async function loadSlots(){
  const pair = selectedStep();
  if (!pair) { path.slots = []; path.slotStatus = 'ok'; return; }
  const [e, s] = pair;
  const key = keyOf(e, s);
  path.slotKey = key; path.slotStatus = 'loading'; path.slots = [];
  render();
  try {
    const route = `/api/slots?episode=${encodeURIComponent(e.id)}&step=${encodeURIComponent(s.id)}`;
    const data = await api('GET', route, {role:state.role});
    if (path.slotKey !== key) return;
    path.slots = data.slots || []; path.slotStatus = 'ok'; path.slotMessage = '';
  } catch (err){ path.slotStatus = 'error'; path.slotMessage = 'Не удалось загрузить время. ' + err.message; }
  render();
}

function selectedStep(){
  const pair = byKey(state.sel.book);
  if (pair[0] && pair[1]) return pair;
  return path.items.flatMap(e => e.steps.map(s => [e, s])).find(([e, s]) =>
    e.status === 'active' && ['open', 'offered'].includes(s.status) && current(e) === s);
}

function patientStep(e, s){
  const isCurrent = current(e) === s;
  const action = e.status === 'active' && isCurrent && ['open', 'offered'].includes(s.status);
  const buttons = action ? `${btn(s.status === 'offered' ? 'Другое время' : 'Выбрать время', 'pathChoose', 'secondary small', {key:keyOf(e,s)})}
    ${s.status === 'offered' ? btn('Подтвердить предложенное время', 'pathConfirm', 'small', {key:keyOf(e,s)}) : ''}
    ${btn('Не сейчас', 'pathAsk', 'ghost small', {key:keyOf(e,s), intent:'later'})}` :
    s.status === 'confirmed' ? btn('Попросить координатора', 'pathAsk', 'secondary small', {key:keyOf(e,s), intent:'other_time'}) : '';
  return `<div class="tlitem"><span class="dot ${s.status === 'completed' ? 'done' : ''}"></span><div><div class="tlhead"><strong>${stepTitle(s)}</strong>${badge(statusName(s.status), tone(s.status))}</div>
    <div class="tlmeta">${s.due_at ? 'Срок: ' + safe(fmt(s.due_at)) : ''}${s.appointment_at ? '<br>Запись: ' + safe(fmt(s.appointment_at)) : ''}</div>
    ${!isCurrent && s.status === 'open' ? '<div class="note">После предыдущего шага</div>' : ''}${buttons ? `<div class="actions">${buttons}</div>` : ''}</div></div>`;
}

function patientCard(e){
  const step = current(e);
  return `<div class="panel" style="margin-bottom:18px"><div class="pagehead"><div>${badge(statusName(e.status), tone(e.status))}<h2>${safe(e.title)}</h2><p>Открыто ${safe(fmt(e.created_at))}</p></div></div>
    <div class="resultmain"><div class="eyebrow">Следующий шаг</div><strong class="big">${step ? stepTitle(step) : e.status === 'manual_review' ? 'Врач уточняет план' : 'План выполнен'}</strong></div>
    <div class="tlgroup">Что уже сделано и что впереди</div>${e.steps.map(s => patientStep(e,s)).join('')}
    <details><summary>Заключение врача</summary><p>${safe(e.conclusion || '')}</p></details>
    ${e.explanation ? `<div class="note"><strong>Что увидели</strong><p>${safe(e.explanation.seen)}</p><strong>Что это значит</strong><p>${safe(e.explanation.means)}</p></div>` : ''}</div>`;
}

export function pathHome(){
  const intro = header('Клиника «Линия здоровья»', 'Поможем понять,<br>что делать дальше', 'Ваш план и запись после подтверждённого заключения врача.');
  if (!ready()) return intro + gate();
  const e = path.items.find(x => !['completed','closed'].includes(x.status)) || path.items[0];
  const s = e && current(e);
  return intro + `<div class="grid three"><article class="card clickable" data-nav="plan"><h3>Мой план</h3><p>${s ? stepTitle(s) : 'Активных шагов нет'}</p><div class="cardfoot">Открыть план →</div></article>
    <article class="card clickable" data-nav="appointments"><h3>Записи</h3><p>${s?.appointment_at ? safe(fmt(s.appointment_at)) : 'Выберите удобное время'}</p><div class="cardfoot">Перейти к записи →</div></article>
    <article class="card clickable" data-nav="messages"><h3>Сообщения</h3><p>Напишите координатору</p><div class="cardfoot">Открыть переписку →</div></article></div>
    <div class="note" style="margin-top:20px">Данные демо-стенда. Если нужна срочная помощь, звоните 103 или 112.</div>`;
}

export function pathPlan(){
  const intro = header('Ваше сопровождение', 'Мой план', 'Все шаги после исследования и приёма в одном месте.');
  if (!ready()) return intro + gate();
  return intro + (path.items.length ? path.items.map(patientCard).join('') : empty('Пока нет активного маршрута'));
}

export function pathAppointments(){
  const intro = header('Расписание клиники', 'Выбрать запись', 'Время на демо-стенде учебное.');
  if (!ready()) return intro + gate();
  const booked = path.items.flatMap(e => e.steps.filter(s => s.status === 'confirmed').map(s => [e,s]));
  const bookedHtml = booked.map(([e,s]) => `<div class="note"><strong>Вы записаны:</strong> ${stepTitle(s)} — ${safe(fmt(s.appointment_at))}. ${btn('Попросить координатора', 'pathAsk', 'ghost small', {key:keyOf(e,s), intent:'other_time'})}</div>`).join('');
  const pair = selectedStep();
  if (!pair) return intro + bookedHtml + empty('Сейчас записываться не на что');
  const [e,s] = pair;
  const slotBlock = path.slotStatus === 'loading' ? loadingCards(2) : path.slotStatus === 'error' ? errorNote(path.slotMessage, 'pathSlotsRetry') :
    path.slots.map(x => `<div class="slot"><div><strong>${safe(fmt(x.starts_at))}</strong><div>${safe(x.specialist)}</div><div class="meta">${safe(x.place)} · ${safe(x.format)}</div></div>
      ${btn('Выбрать', 'pathBook', 'small', {key:keyOf(e,s), slot:x.id})}</div>`).join('') || '<p>Свободного времени пока нет. Попросите координатора помочь с записью.</p>';
  return intro + bookedHtml + `<div class="twocol"><div class="panel"><h2>${stepTitle(s)}</h2><p>Слоты демо-стенда, запись сохраняется в плане.</p>${slotBlock}</div>
    <div class="stack"><div class="panel"><h3>Нет подходящего времени?</h3><p>Координатор проверит другие варианты и свяжется с вами.</p>${btn('Попросить координатора', 'pathAsk', 'secondary', {key:keyOf(e,s), intent:'callback'})}</div></div></div>`;
}

export const staffReason = e => e.reason || (e.status === 'active' ? current(e)?.status === 'open' ? 'Пациент не выбрал время' : current(e)?.status === 'attended' ? 'Ждём итог врача' : 'Идёт по плану' : statusName(e.status));
const staffNeed = e => e.status === 'manual_review' || e.status === 'paused' || e.callback || ['open','attended'].includes(current(e)?.status);
function staffRow(e){ const s = current(e); return `<tr><td><strong>${safe(e.patient)}</strong></td><td>${safe(e.title)}<small>${safe(fmt(e.created_at))}</small></td><td>${s ? stepTitle(s) : '—'}</td><td>${safe(staffReason(e))}</td><td>${badge(statusName(e.status), tone(e.status))}</td><td><button class="btn secondary small" data-case="${safe(e.id)}">Открыть</button></td></tr>`; }

export function pathInbox(){
  const intro = header('Рабочее место координатора', 'Обращения', 'После подтверждённого заключения здесь появляется обращение с планом.');
  if (!ready()) return intro + gate();
  const need = path.items.filter(staffNeed).length;
  const manual = path.items.filter(e => e.status === 'manual_review').length;
  return intro + `<div class="grid four" style="margin-bottom:18px"><div class="card"><div class="metric">${need}</div><span class="muted">ждут действия</span></div><div class="card"><div class="metric">${path.items.filter(e => current(e)?.status === 'open').length}</div><span class="muted">пациент не записан</span></div><div class="card"><div class="metric">${manual}</div><span class="muted">ждут решения врача</span></div><div class="card"><div class="metric">${path.items.filter(e => e.status === 'paused').length}</div><span class="muted">отложено</span></div></div>
    <div class="tablewrap"><table><thead><tr><th>Пациент</th><th>Исследование</th><th>Следующий шаг</th><th>Что мешает</th><th>Статус</th><th></th></tr></thead><tbody>${path.items.map(staffRow).join('') || '<tr><td colspan="6">Обращений пока нет.</td></tr>'}</tbody></table></div>${manualStudiesBlock()}`;
}

function staffActions(e){
  const s = current(e);
  if (state.role !== 'staff') return '';
  if (!s) return e.steps.every(x => ['completed','superseded'].includes(x.status)) && e.status === 'active' ?
    btn('Закрыть маршрут', 'pathStaffEpisodeOpen', '', {id:e.id, act:'close'}) : '';
  const key = keyOf(e,s);
  if (e.status === 'paused') return btn('Передать врачу для нового плана', 'pathStaffEpisodeOpen', 'secondary', {id:e.id, act:'stop'});
  if (s.kind === 'care_coordination' && s.status === 'open') return btn('Завершить организационный шаг', 'pathStaffComplete', '', {key});
  if (s.status === 'open') return btn('Предложить время', 'pathStaffSlots', '', {key, mode:'offer'}) + btn('Записать по звонку', 'pathStaffSlots', 'secondary', {key, mode:'confirm'});
  if (s.status === 'offered') return btn('Подтвердить по звонку', 'pathStaffAct', '', {key, act:'confirm'}) +
    btn('Отменить предложение', 'pathStaffAct', 'secondary', {key, act:'cancel'}) +
    btn('Нет связи', 'pathStaffAct', 'ghost', {key, act:'lost_contact'});
  if (s.status === 'confirmed') return btn('Визит состоялся', 'pathStaffAct', '', {key, act:'attend'}) +
    btn('Отменить запись', 'pathStaffAct', 'secondary', {key, act:'cancel'}) +
    btn('Пациент отказался', 'pathStaffAct', 'ghost', {key, act:'refuse'});
  return '';
}

export function pathCase(){
  const e = path.items.find(x => x.id === state.sel.episode) || path.items[0];
  const intro = header('Карточка обращения', e ? safe(e.patient) : 'Обращение', e ? safe(e.title) + ' · открыто ' + safe(fmt(e.created_at)) : '');
  if (!ready()) return intro + gate();
  if (!e) return intro + empty('Обращений пока нет');
  const report = e.source_report || {};
  return intro + `<div class="twocol"><div class="stack"><div class="panel"><h3>Заключение по исследованию</h3><p>${safe(report.conclusion)}</p>
      <dl class="kv"><dt>Исследование</dt><dd>${safe(e.title)}</dd><dt>Область</dt><dd>${safe(report.anatomy)}</dd><dt>Протокол</dt><dd>${safe(report.protocol_name)}</dd><dt>Код находки</dt><dd>${safe(report.finding_code)}</dd><dt>Подтвердил</dt><dd>${safe(report.physician_id)} · ${safe(fmt(report.confirmed_at))}</dd><dt>Источник черновика</dt><dd>${safe(report.source_model)}</dd></dl>${demoSource(report.source_model)}</div>
      <div class="panel"><h3>Рекомендация следующего шага</h3>${e.reason ? `<div class="note warn">${safe(e.reason)}</div>` : ''}<div class="tlgroup">План</div>${e.steps.map(s => `<div class="rowline"><div><strong>${stepTitle(s)}</strong><div class="meta">${safe(s.decision_source)} · ${safe(fmt(s.due_at))}</div></div>${badge(statusName(s.status), tone(s.status))}</div>`).join('') || '<p>План уточняет врач.</p>'}</div>${caseClinicBlocks(e)}</div>
      <div class="stack"><div class="panel"><h3>Что сделать сейчас</h3><p>${safe(staffReason(e))}</p><div class="actions">${staffActions(e)}</div>${caseClinicActions(e)}</div>
      ${path.requests.filter(r => r.episode_id === e.id).length ? `<div class="panel"><h3>Обращения пациента</h3>${path.requests.filter(r => r.episode_id === e.id).map(r => `<div class="rowline"><div><strong>${safe(r.intent)}</strong><div class="meta">${safe(fmt(r.created_at))}</div><p>${safe(r.body)}</p></div></div>`).join('')}</div>` : ''}
      <div class="panel"><h3>Журнал</h3><div class="log">${e.audit_events.map(a => `<div><time>${safe(fmt(a.occurred_at))}</time><span><b>${safe(a.actor)}</b> ${safe(a.event_type)}</span></div>`).join('')}</div></div></div></div>`;
}

export function pathScheduling(){
  const intro = header('Операционная работа', 'Запись и сопровождение', 'Каждое обращение стоит у того действия, которого от него ждут.');
  if (!ready()) return intro + gate();
  const groups = [['offer','Предложить запись',e => current(e)?.status === 'open'], ['wait','Ждём ответ пациента',e => current(e)?.status === 'offered'],
    ['booked','Записаны',e => current(e)?.status === 'confirmed'], ['outcome','Ждём итог врача',e => current(e)?.status === 'attended'],
    ['lost','Просрочено и на разборе',e => e.status === 'paused' || e.status === 'manual_review']];
  return intro + `<div class="board">${groups.map(([,label,filter]) => { const list = path.items.filter(filter); return `<div class="col"><h3>${label}<span>${list.length}</span></h3>${list.map(e => `<button class="kcard" data-case="${safe(e.id)}"><strong>${safe(e.patient)}</strong><span>${safe(current(e)?.description || '')}</span><span>${safe(staffReason(e))}</span></button>`).join('') || '<div class="colempty">Пусто</div>'}</div>`; }).join('')}</div>`;
}

async function mutate(route, body, success){
  try { await api('POST', route, {role:state.role, body}); closeModal(); await refreshPath(); toast(success); }
  catch (err){ toast(err.message); await refreshPath(); }
}

export function installPathActions(actions){
  actions.pathRetry = () => refreshPath();
  actions.pathSlotsRetry = () => loadSlots();
  actions.pathChoose = d => { state.sel.book = d.key; go('appointments'); loadSlots(); };
  actions.pathBook = d => { const [e,s] = byKey(d.key); if (e && s) mutate(`/api/patient/episodes/${encodeURIComponent(e.id)}/steps/${encodeURIComponent(s.id)}/book`, {slot_id:d.slot}, 'Запись подтверждена'); };
  actions.pathConfirm = d => { const [e,s] = byKey(d.key); if (e && s) mutate(`/api/patient/episodes/${encodeURIComponent(e.id)}/steps/${encodeURIComponent(s.id)}/confirm`, {}, 'Запись подтверждена'); };
  actions.pathAsk = d => { const [e,s] = byKey(d.key); if (e && s) mutate(`/api/patient/episodes/${encodeURIComponent(e.id)}/steps/${encodeURIComponent(s.id)}/ask`, {intent:d.intent}, 'Координатор увидит ваше обращение'); };
  actions.pathStaffAct = d => { const [e,s] = byKey(d.key); if (e && s) mutate(`/api/staff/episodes/${encodeURIComponent(e.id)}/steps/${encodeURIComponent(s.id)}/${encodeURIComponent(d.act)}`, {}, 'Статус обновлён'); };
  actions.pathStaffSlots = async d => {
    const [e,s] = byKey(d.key); if (!e || !s) return;
    openModal(modalHead(d.mode === 'offer' ? 'Предложить время' : 'Записать по звонку', stepTitle(s)) + loadingCards(2));
    try {
      const data = await api('GET', `/api/slots?episode=${encodeURIComponent(e.id)}&step=${encodeURIComponent(s.id)}`, {role:state.role});
      openModal(modalHead('Демо-слоты', stepTitle(s)) + (data.slots || []).map(x => `<div class="slot"><div><strong>${safe(fmt(x.starts_at))}</strong><div>${safe(x.specialist)}</div><div class="meta">${safe(x.place)}</div></div>${btn('Выбрать', 'pathStaffPick', 'small', {key:d.key, mode:d.mode, slot:x.id})}</div>`).join('') || '<p>Свободного времени нет.</p>');
    } catch (err){ openModal(modalHead('', 'Время недоступно') + errorNote(err.message, 'pathStaffSlots', d)); }
  };
  actions.pathStaffPick = d => { const [e,s] = byKey(d.key); if (e && s) mutate(`/api/staff/episodes/${encodeURIComponent(e.id)}/steps/${encodeURIComponent(s.id)}/${d.mode}`, {slot_id:d.slot}, d.mode === 'offer' ? 'Предложение отправлено' : 'Запись подтверждена'); };
  actions.pathStaffComplete = d => { const [e,s] = byKey(d.key); if (e && s) mutate(`/api/staff/episodes/${encodeURIComponent(e.id)}/steps/${encodeURIComponent(s.id)}/complete`, {}, 'Шаг завершён'); };
  actions.pathStaffEpisodeOpen = d => openModal(`${modalHead('Обращение', d.act === 'close' ? 'Закрыть маршрут' : 'Остановить маршрут')}
    <div class="field"><label for="pathEpisodeReason">${d.act === 'close' ? 'Итог' : 'Причина'}</label><textarea id="pathEpisodeReason" maxlength="500"></textarea></div>
    <div class="actions">${btn('Подтвердить', 'pathStaffEpisodeSave', '', {id:d.id, act:d.act})}${btn('Отмена','close','secondary')}</div>`);
  actions.pathStaffEpisodeSave = d => { const value = document.querySelector('#pathEpisodeReason')?.value.trim(); if (!value) return toast('Укажите итог или причину.');
    mutate(`/api/staff/episodes/${encodeURIComponent(d.id)}/${d.act}`, {[d.act === 'close' ? 'outcome' : 'reason']:value}, 'Маршрут обновлён'); };
}
