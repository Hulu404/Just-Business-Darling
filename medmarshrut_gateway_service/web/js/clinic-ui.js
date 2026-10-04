/* Задание 06: карта пациента, сеть клиник и направления на сервисе клиники через шлюз.
   Партнёру показываем ровно то, что отдал сервис для его токена: ничего не добавляем из других источников. */
import { api } from './api.js';
import { PHARMACIES } from './demo-data.js';
import { icon } from './icons.js';
import { health, sessions, state, ui } from './state.js';
import { $, badge, btn, closeModal, errorNote, go, loadingCards, modalHead, openModal, plural, safe, toast } from './ui.js';
import { render } from './shell.js';

const enc = encodeURIComponent;
const fmt = value => { if (!value) return ''; const d = new Date(value); return Number.isNaN(+d) ? String(value) : new Intl.DateTimeFormat('ru-RU', {day:'numeric', month:'long', year:'numeric'}).format(d); };
const head = (eyebrow, title, text = '') => `<div class="pagehead"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1>${text ? `<p>${text}</p>` : ''}</div></div>`;
export const REF_STATUS = {proposed:['Ждёт ответа партнёра', 'orange'], accepted:['Принято партнёром', 'blue'], completed:['Услуга оказана', ''],
                           rejected:['Отклонено партнёром', 'red'], cancelled:['Отменено', 'gray']};
const refBadge = status => badge(...(REF_STATUS[status] || [status, 'gray']));
const KINDS = {diagnosis:'Диагноз', allergy:'Аллергия', medication:'Лекарства', surgery:'Операция', family_history:'Семейный анамнез',
               risk_factor:'Фактор риска', note:'Заметка', measurement:'Измерение', lab:'Анализ'};
const SEX = {M:'мужской', F:'женский', X:'не указан'};
const age = birth => { if (!birth) return null; const b = new Date(birth), n = new Date(); let a = n.getFullYear() - b.getFullYear(); if (n < new Date(n.getFullYear(), b.getMonth(), b.getDate())) a--; return a; };

/* ---------- Загрузка ---------- */
const page = {key:'', status:'loading', message:'', data:{}};
const PAGES_HERE = {staff:['partners', 'analytics'], partner:['incoming', 'referral'], patient:['documents']};
export const isClinicPage = () => (PAGES_HERE[state.role] || []).includes(state.page);
const keyNow = () => `${state.role}:${state.partnerClinic || ''}:${state.page}:${state.page === 'referral' ? state.sel.partnerPatient : ''}`;
const ready = () => page.key === keyNow() && page.status === 'ok';
const gate = () => page.key === keyNow() && page.status === 'error' ? errorNote(page.message, 'clinicRetry') : loadingCards();

export async function refreshClinic(){
  if (!isClinicPage() || sessions[state.role]?.status !== 'ok') return;
  const key = keyNow(), role = state.role;
  if (page.key !== key){ Object.assign(page, {key, status:'loading', message:'', data:{}}); render(); }
  try {
    let data;
    if (state.page === 'partners'){
      const [network, refs] = await Promise.all([api('GET', '/api/staff/network', {role}), api('GET', '/api/staff/referrals', {role})]);
      data = {network, referrals:refs.referrals || []};
    } else if (state.page === 'analytics') data = {network:await api('GET', '/api/staff/network', {role})};
    else if (state.page === 'incoming') data = {referrals:(await api('GET', '/api/partner/referrals', {role})).referrals || []};
    else if (state.page === 'referral'){
      const [card, refs] = await Promise.all([api('GET', `/api/partner/patients/${enc(state.sel.partnerPatient || '')}/card`, {role}),
                                              api('GET', '/api/partner/referrals', {role})]);
      data = {card, referrals:refs.referrals || []};
    } else if (state.page === 'documents') data = {referrals:(await api('GET', '/api/patient/documents', {role})).referrals || []};
    if (keyNow() !== key) return;
    Object.assign(page, {status:'ok', message:'', data});
    if (role === 'partner') state.partnerIncoming = (data.referrals || []).filter(r => r.to_clinic_id === state.partnerClinic && r.status === 'proposed').length;
  } catch (err){
    if (keyNow() !== key) return;
    Object.assign(page, {status:'error', message:'Не удалось загрузить данные клиники. ' + err.message});
  }
  if (!ui.modal) render();
}

/* ---------- Сотрудник: «Партнёры» ---------- */
export function partnersPage(){
  const tab = ['clinics', 'refs', 'pharm'].includes(state.sel.partnersTab) ? state.sel.partnersTab : 'clinics';
  const refs = ready() ? page.data.referrals : [];
  const intro = `<div class="pagehead"><div><div class="eyebrow">Путь пациента за пределами клиники</div><h1>Партнёры</h1><p>Если услуги нет или нет времени, пациент идёт к партнёру с направлением и возвращается с результатом в тот же план.</p></div></div>
    <div class="tabs">${[['clinics', 'Клиники-партнёры'], ['refs', `Направления${ready() ? ' · ' + refs.length : ''}`], ['pharm', 'Аптеки-партнёры']].map(([id, label]) => `<button class="tab ${tab === id ? 'active' : ''}" data-action="partnersTab" data-id="${id}">${label}</button>`).join('')}</div>`;
  if (tab === 'pharm') return intro + `<div class="grid three">${PHARMACIES.map(x => `<div class="card"><div class="tile">${icon('pharmacy')}</div><h3>${safe(x.name)}</h3><p>${safe(x.addr)} · ${safe(x.dist)}</p><dl class="kv" style="margin-top:14px"><dt>Наличие</dt><dd>Обновляется через API</dd><dt>Рецепты</dt><dd>Принимает электронные</dd></dl></div>`).join('')}</div><div class="note" style="margin-top:16px">Аптеки — демо до задания 07.</div>`;
  if (!ready()) return intro + gate();
  if (tab === 'clinics'){
    const {network} = page.data, counts = network.referral_counts || {};
    const partners = (network.clinics || []).filter(c => c.id !== network.home_clinic_id);
    return intro + `<div class="grid two">${partners.map(c => { const n = counts[c.id] || {sent:0, accepted:0}; return `<div class="card"><div class="tile violet">${icon('link')}</div><h3>${safe(c.name)}</h3><p>Сеть «${safe(c.network)}»${(network.partners || []).includes(c.id) ? ' · действующий партнёр' : ''}</p><dl class="kv" style="margin-top:14px"><dt>Направлено</dt><dd>${n.sent}</dd><dt>Принято партнёром</dt><dd>${n.accepted}</dd></dl></div>`; }).join('') || '<div class="panel empty"><h3>Партнёров пока нет</h3></div>'}</div>
      <div class="note" style="margin-top:16px">Сеть клиник: версия ${safe(network.network_version)}. Числа — по направлениям в сервисе клиники.</div>`;
  }
  const row = r => { const who = r.link ? `<button class="linkbtn" data-case="${safe(r.link.episode_id)}">${safe(r.patient_ref)}</button>` : `<strong>${safe(r.patient_ref)}</strong>`;
    return `<tr><td>${who}<small>${safe(fmt(r.created_at))}</small></td><td>${safe(r.reason)}</td><td>${safe(r.direction === 'outgoing' ? r.to_clinic_name : 'от: ' + r.from_clinic_name)}</td><td>${refBadge(r.status)}${r.decision_note ? `<small>${safe(r.decision_note)}</small>` : ''}</td><td>${r.direction === 'outgoing' && ['proposed', 'accepted'].includes(r.status) ? btn('Отменить', 'referralCancel', 'secondary small', {id:r.id}) : ''}</td></tr>`; };
  return intro + `<div class="tablewrap"><table><thead><tr><th>Пациент</th><th>Причина</th><th>Партнёр</th><th>Статус</th><th></th></tr></thead><tbody>${refs.map(row).join('') || '<tr><td colspan="5">Направлений пока нет.</td></tr>'}</tbody></table></div>
    <div class="note" style="margin-top:16px">Пациент не выпадает из плана: когда партнёр оказал услугу, координатор отмечает визит, а врач вносит итог.</div>`;
}

export function analyticsClinicBlock(){
  if (state.role !== 'staff') return '';
  if (!ready()) return page.key === keyNow() && page.status === 'error' ? errorNote(page.message, 'clinicRetry') : '';
  const m = page.data.network.metrics || {};
  return `<div class="sectionhead"><h2>Клиника</h2></div><div class="grid three"><div class="card"><div class="metric">${safe((m.patients_by_status || {}).active || 0)}</div><span class="muted">пациентов на сопровождении</span></div><div class="card"><div class="metric">${safe(m.referrals_outgoing || 0)}</div><span class="muted">направлено партнёрам</span></div><div class="card"><div class="metric">${safe(m.referrals_outgoing_accepted || 0)}</div><span class="muted">принято партнёрами</span></div></div>`;
}

/* ---------- Пациент: направления в «Документах» ---------- */
export function documentsReferrals(){
  if (!ready()) return gate();
  const refs = page.data.referrals;
  return `<div class="sectionhead"><h2>Направления</h2></div><div class="panel">${refs.map(r => `<div class="slot"><div><strong>${safe(r.to_clinic_name)}</strong><div class="meta">${safe(r.reason)} · ${safe(fmt(r.created_at))}</div></div>${refBadge(r.status)}</div>`).join('') || '<div class="empty"><h3>Направлений пока нет</h3><p>Если шаг плана выполняет клиника-партнёр, направление появится здесь.</p></div>'}</div>`;
}

/* ---------- Клиника-партнёр ---------- */
const clinicName = () => (health.data?.partner_clinics || []).find(c => c.clinic_id === state.partnerClinic)?.name || 'Клиника-партнёр';
export function incomingPage(){
  const intro = head(safe(clinicName()), 'Входящие направления', 'Направления от клиник сети. ФИО и контакт пациента открываются после того, как вы примете направление.');
  if (!ready()) return intro + gate();
  const refs = page.data.referrals.filter(r => r.to_clinic_id === state.partnerClinic);
  const count = s => refs.filter(r => r.status === s).length;
  return intro + `<div class="grid three" style="margin-bottom:18px"><div class="card"><div class="metric">${count('proposed')}</div><span class="muted">${plural(count('proposed'), ['ждёт', 'ждут', 'ждут'])} решения</span></div><div class="card"><div class="metric">${count('accepted')}</div><span class="muted">принято, услуга впереди</span></div><div class="card"><div class="metric">${count('completed')}</div><span class="muted">услуга оказана</span></div></div>
    <div class="tablewrap"><table><thead><tr><th>Пациент</th><th>Откуда</th><th>Причина</th><th>Статус</th><th></th></tr></thead><tbody>
    ${refs.map(r => `<tr><td><strong>${safe(r.patient_ref)}</strong><small>${safe(fmt(r.created_at))}</small></td><td>${safe(r.from_clinic_name)}</td><td>${safe(r.reason)}</td><td>${refBadge(r.status)}</td><td>${['proposed', 'accepted', 'completed'].includes(r.status) ? btn('Открыть', 'partnerOpen', 'secondary small', {patient:r.patient_id}) : ''}</td></tr>`).join('') || '<tr><td colspan="5">Входящих направлений пока нет.</td></tr>'}
    </tbody></table></div>`;
}
export function referralPage(){
  const back = `<button class="btn secondary" data-nav="incoming">← К направлениям</button>`;
  if (!ready()) return head('Входящее направление', 'Направление') + gate();
  const {card} = page.data, p = card.patient || {}, r = card.referral || {};
  const listed = page.data.referrals.find(x => x.id === r.id) || {};
  const opened = 'full_name' in p;
  const rows = [['Псевдоним', p.patient_ref], ['Домашняя клиника', p.home_clinic_name]].concat(opened ? [['ФИО', p.full_name], ['Дата рождения', fmt(p.birth_date)], ['Пол', SEX[p.sex] || p.sex || '—'], ['Контакт', p.contact]] : []);
  const anamnesis = (card.anamnesis || []).map(a => `<div class="rowline"><div><strong>${safe(KINDS[a.kind] || a.kind)}</strong><div class="meta">${safe(a.text)}</div></div></div>`).join('') || '<p style="margin:0">Клиника пока ничем не поделилась.</p>';
  const decide = r.status === 'proposed' ? `<div class="field"><label for="partnerNote">Комментарий</label><textarea id="partnerNote" maxlength="500" placeholder="Например: ждём пациента во вторник"></textarea></div><div class="actions">${btn('Принять', 'partnerAct', '', {id:r.id, act:'accept'})}${btn('Отклонить', 'partnerAct', 'secondary', {id:r.id, act:'reject'})}</div>`
    : r.status === 'accepted' ? `<div class="actions">${btn('Услуга оказана', 'partnerAct', '', {id:r.id, act:'complete'})}</div><p class="muted" style="font-size:13px">Клиника-отправитель увидит отметку. Визит в её плане отмечает координатор, итог вносит врач.</p>` : '';
  return `<div class="pagehead"><div><div class="eyebrow">Входящее направление · ${safe(listed.from_clinic_name || p.home_clinic_name)}</div><h1>${safe(opened ? p.full_name : p.patient_ref)}</h1><p>${safe(r.reason)}</p></div><div class="actions">${refBadge(r.status)}${back}</div></div>
    <div class="twocol"><div class="stack"><div class="panel"><h3>Что видно вашей клинике</h3><dl class="kv">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${safe(v || '—')}</dd>`).join('')}</dl>${opened ? '' : '<div class="note" style="margin-top:14px">ФИО и контакт откроются после принятия направления.</div>'}</div>
      <div class="panel"><h3>Анамнез, которым поделилась клиника</h3>${anamnesis}</div></div>
      <div class="stack"><div class="panel"><h3>Решение</h3>${r.decision_note ? `<p>Комментарий: ${safe(r.decision_note)}</p>` : ''}${decide || '<p style="margin:0">Решение принято.</p>'}</div></div></div>`;
}

/* ---------- Карточка обращения: карта, кандидаты, направления ---------- */
const caseData = {episodeId:null, status:'loading', message:'', card:null, candidates:null, referrals:[]};
async function loadCase(e){
  Object.assign(caseData, {episodeId:e.id, status:'loading', message:'', card:null, candidates:null, referrals:[]});
  const role = state.role;
  try {
    const [card, candidates, refs] = await Promise.all([
      e.patient_ref ? api('GET', `/api/staff/patients/${enc(e.patient_ref)}/card`, {role}).catch(err => ({error:err.message})) : null,
      api('GET', `/api/staff/episodes/${enc(e.id)}/route-candidates`, {role}),
      role === 'staff' ? api('GET', '/api/staff/referrals', {role}) : {referrals:[]}]);
    if (caseData.episodeId !== e.id) return;
    Object.assign(caseData, {status:'ok', card, candidates, referrals:(refs.referrals || []).filter(r => r.patient_ref === e.patient_ref)});
  } catch (err){
    if (caseData.episodeId !== e.id) return;
    Object.assign(caseData, {status:'error', message:'Не удалось загрузить данные клиники. ' + err.message});
  }
  if (!ui.modal) render();
}
export const resetCase = () => { caseData.episodeId = null; };
const current = e => e.steps.find(s => !['completed', 'superseded', 'closed'].includes(s.status));

export function caseClinicBlocks(e){
  if (caseData.episodeId !== e.id){ setTimeout(() => loadCase(e)); return loadingCards(1); }
  if (caseData.status === 'loading') return loadingCards(1);
  if (caseData.status === 'error') return errorNote(caseData.message, 'clinicCaseRetry');
  const card = caseData.card, p = card?.patient || {};
  const facts = (card?.anamnesis || []).filter(a => ['diagnosis', 'risk_factor', 'allergy'].includes(a.kind));
  const profile = !card ? '<p style="margin:0">В обращении нет пациента.</p>' : card.error ? `<p style="margin:0">${safe(card.error)}</p>`
    : `<dl class="kv"><dt>Пациент</dt><dd>${safe(p.full_name)}${age(p.birth_date) != null ? `, ${age(p.birth_date)} ${plural(age(p.birth_date), ['год', 'года', 'лет'])}` : ''}</dd><dt>Учтено из карты</dt><dd>${facts.map(a => `${safe(KINDS[a.kind])}: ${safe(a.text)}${a.shareable ? '' : ' <span class="muted">(только для своей клиники)</span>'}`).join('<br>') || 'Записей нет'}</dd></dl>`;
  const c = caseData.candidates || {}, list = c.candidates || [];
  const step = current(e);
  const canRefer = state.role === 'staff' && step && step.kind !== 'manual_review' && e.status === 'active';
  const candidate = x => { const ref = caseData.referrals.find(r => r.to_clinic_id === x.clinic_id && r.status !== 'cancelled' && r.status !== 'rejected');
    return `<div class="rowline"><div><strong>${safe(x.clinic_name || x.clinic_id)}</strong><div class="meta">${x.role === 'home' ? 'у нас' : 'нужно направление'}</div></div>${ref ? refBadge(ref.status) : x.role === 'partner' && canRefer ? btn('Направить к партнёру', 'referralOpen', 'secondary small', {id:e.id, step:step.id, clinic:x.clinic_id, name:x.clinic_name || x.clinic_id}) : ''}</div>`; };
  const alt = list.find(x => x.role === 'partner');
  const refs = caseData.referrals.map(r => `<div class="rowline"><div><strong>${safe(r.to_clinic_name)}</strong><div class="meta">${safe(r.reason)}${r.link ? '' : ' · без связи с шагом'}</div>${r.status === 'completed' ? '<div class="note" style="margin-top:8px">Партнёр сообщил: услуга оказана. Отметьте визит, когда подтвердите его.</div>' : ''}</div>${refBadge(r.status)}</div>`).join('');
  return `<div class="panel"><h3>Пациент по карте клиники</h3>${profile}</div>
    <div class="panel"><h3>Где выполнить шаг</h3>${c.reason_text ? `<div class="note warn">${safe(c.reason_text)}</div>` : ''}${list.map(candidate).join('')}
      <dl class="kv" style="margin-top:14px"><dt>Если нет времени</dt><dd>${alt ? `${safe(alt.clinic_name)} — по направлению` : 'Другой филиал или помощь координатора'}</dd></dl>
      ${refs ? `<div class="tlgroup">Направления пациента</div>${refs}` : ''}</div>`;
}
export function caseClinicActions(e){
  if (state.role !== 'staff' || caseData.episodeId !== e.id || caseData.status !== 'ok' || !e.patient_ref) return '';
  const step = current(e);
  const accepted = caseData.referrals.filter(r => r.status === 'accepted');
  const book = accepted.length && step && ['open', 'offered'].includes(step.status) && e.status === 'active'
    ? btn('Записать время у партнёра', 'partnerTimeOpen', 'secondary', {id:e.id, step:step.id}) : '';
  return `${book ? `<div class="actions">${book}</div>` : ''}
    <div class="tlgroup" style="margin-top:16px">Запись в анамнез</div>
    <div class="field"><label for="anKind">Вид</label><select id="anKind">${Object.entries(KINDS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></div>
    <div class="field" style="margin-top:10px"><label for="anText">Текст</label><textarea id="anText" maxlength="4000"></textarea></div>
    <label class="checkline" style="margin-top:10px"><input type="checkbox" id="anShare"><span>Показывать партнёрам</span></label>
    <div class="actions">${btn('Добавить в анамнез', 'anamnesisAdd', 'secondary', {ref:e.patient_ref, id:e.id})}</div>`;
}

/* ---------- Действия ---------- */
async function act(run, success, after){
  try { await run(); closeModal(); toast(success); }
  catch (err){ toast(err.message); }
  if (after) after();
  await refreshClinic();
}
export function installClinicActions(actions){
  actions.clinicRetry = () => refreshClinic();
  actions.clinicCaseRetry = () => { resetCase(); render(); };
  actions.partnersTab = d => { state.sel.partnersTab = d.id; render(); };
  actions.referralCancel = d => act(() => api('POST', `/api/staff/referrals/${enc(d.id)}/cancel`, {role:'staff', body:{}}), 'Направление отменено');
  actions.referralOpen = d => openModal(`${modalHead('Направление к партнёру', safe(d.name))}
    <div class="field"><label for="refReason">Причина направления</label><textarea id="refReason" maxlength="1000" placeholder="Например: контрольная КТ органов грудной клетки"></textarea><small>Партнёр увидит причину, псевдоним пациента и записи анамнеза с отметкой «показывать партнёрам».</small></div>
    <div class="actions">${btn('Направить', 'referralSend', '', d)}${btn('Отмена', 'close', 'secondary')}</div>`);
  actions.referralSend = d => {
    const reason = $('#refReason')?.value.trim();
    if (!reason) return toast('Укажите причину направления.');
    act(() => api('POST', `/api/staff/episodes/${enc(d.id)}/steps/${enc(d.step)}/referral`, {role:'staff', body:{to_clinic_id:d.clinic, reason}}),
        'Направление отправлено партнёру', resetCase);
  };
  actions.partnerTimeOpen = d => {
    const accepted = caseData.referrals.filter(r => r.status === 'accepted');
    openModal(`${modalHead('Запись у партнёра', 'Время, которое сообщил партнёр')}
      <div class="field"><label for="ptClinic">Клиника</label><select id="ptClinic">${accepted.map(r => `<option value="${safe(r.to_clinic_id)}">${safe(r.to_clinic_name)}</option>`).join('')}</select></div>
      <div class="field" style="margin-top:10px"><label for="ptTime">Дата и время</label><input id="ptTime" type="datetime-local"></div>
      <div class="note" style="margin-top:12px">Расписания партнёров на стенде пока нет: время вводится со слов партнёра.</div>
      <div class="actions">${btn('Записать', 'partnerTimeSave', '', d)}${btn('Отмена', 'close', 'secondary')}</div>`);
  };
  actions.partnerTimeSave = d => {
    const value = $('#ptTime')?.value, clinic = $('#ptClinic')?.value;
    if (!value) return toast('Укажите дату и время, которые сообщил партнёр.');
    const when = new Date(value);
    const off = -when.getTimezoneOffset(), sign = off >= 0 ? '+' : '-', pad = n => String(Math.abs(n)).padStart(2, '0');
    const iso = `${value.length === 16 ? value + ':00' : value}${sign}${pad(Math.trunc(off / 60))}:${pad(off % 60)}`;
    act(() => api('POST', `/api/staff/episodes/${enc(d.id)}/steps/${enc(d.step)}/confirm`, {role:'staff', body:{partner_time:iso, partner_clinic_id:clinic}}),
        'Запись у партнёра сохранена', () => { resetCase(); actions.pathRetry?.(); });
  };
  actions.anamnesisAdd = d => {
    const textValue = $('#anText')?.value.trim();
    if (!textValue) return toast('Напишите текст записи.');
    act(() => api('POST', `/api/staff/patients/${enc(d.ref)}/anamnesis`, {role:state.role, body:{kind:$('#anKind').value, text:textValue, shareable:$('#anShare').checked}}),
        'Запись добавлена в анамнез', resetCase);
  };
  actions.partnerOpen = d => { state.sel.partnerPatient = d.patient; go('referral'); };
  actions.partnerAct = d => {
    const note = $('#partnerNote')?.value.trim();
    act(() => api('POST', `/api/partner/referrals/${enc(d.id)}/${d.act}`, {role:'partner', body:note ? {note} : {}}),
        {accept:'Направление принято', reject:'Направление отклонено', complete:'Отмечено: услуга оказана'}[d.act]);
  };
}
