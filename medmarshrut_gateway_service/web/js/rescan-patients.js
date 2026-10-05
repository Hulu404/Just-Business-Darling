/* Кабинет rescan, раздел «Пациенты» (задание 12, цикл 7): карты пациентов клиники и их маршруты.
   Статусы и формулировки — из statusName и staffReason, как у координатора. Карта и анамнез — из сервиса клиники. */
import { api } from './api.js';
import { KINDS, age } from './clinic-ui.js';
import { current, staffReason, statusName } from './path-ui.js';
import { k, empty, head, load, redraw, rs, stateOf } from './rescan-ui.js';
import { planButton, planCard } from './rescan-plan.js';
import { state, ui } from './state.js';
import { plural, safe, toast } from './ui.js';

const enc = encodeURIComponent;
const fmt = value => { if (!value) return ''; const d = new Date(value); return Number.isNaN(+d) ? String(value) : new Intl.DateTimeFormat('ru-RU', {day:'numeric', month:'long', hour:'2-digit', minute:'2-digit'}).format(d); };
const day = value => { if (!value) return ''; const d = new Date(value); return Number.isNaN(+d) ? String(value) : new Intl.DateTimeFormat('ru-RU', {day:'numeric', month:'long'}).format(d); };
const initials = name => String(name || '').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('') || '?';
const FACTS = ['diagnosis', 'risk_factor', 'allergy'];
const FILTERS = [['all', 'Все'], ['att', 'Требуют внимания'], ['way', 'В пути'], ['done', 'Дошли']];

/* Карты пациентов по patient_ref: {status, data, message}; запись в анамнез — черновик в ui.rsAnam */
const cards = {};
export function patientNeeds(timer){ return timer && (ui.rsPlan || ui.rsAnam?.text) ? [] : ['patients', 'episodes', 'catalog', 'rules']; }

/* Последнее обращение пациента; позиция на пути: 1 заключение, 2 шаг назначен, 3 записан, 4 пришёл */
export const latest = (episodes, ref) => episodes.filter(e => e.patient_ref === ref).sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))[0];
export const attention = e => !!e && (['manual_review', 'paused'].includes(e.status) || current(e)?.status === 'attended');
export const reached = e => !!e && (e.status === 'completed' || e.steps.some(s => ['attended', 'completed'].includes(s.status)));
function stage(e){
  if (!e) return 0;
  if (reached(e)) return 4;
  const s = current(e);
  return s && ['offered', 'confirmed'].includes(s.status) ? 3 : e.status === 'manual_review' ? 1 : 2;
}
const dots = n => `<span class="c-dots4" title="${['Нет маршрута', 'Заключение', 'Шаг назначен', 'Записан', 'Пришёл'][n]}">${[1, 2, 3, 4].map(i => `<i class="${i <= n ? 'on' : ''}${i === n && n < 4 ? ' cur' : ''}"></i>`).join('')}</span>`;
const tone = e => !e ? 'grey' : attention(e) ? 'amber' : e.status === 'completed' || e.status === 'closed' ? 'green' : 'blue';
const pill = e => `<span class="c-s ${tone(e)}">${safe(e ? statusName(e.status) : 'Нет маршрута')}</span>`;
/* Срок: due_at шага; у шага по правилу он пустой, а срок написан в описании — дату не вычисляем */
/* Шаг ручного разбора сервис пути описывает служебным текстом: врачу показываем, что от него нужно */
const stepText = s => !s ? '—' : s.kind === 'manual_review' ? 'План назначит врач' : s.description;
const due = s => !s || s.kind === 'manual_review' ? '' : s.due_at ? 'до ' + day(s.due_at) : s.appointment_at ? 'запись ' + fmt(s.appointment_at) : 'срок — в описании шага';

function rows(patients, episodes){
  const q = (ui.rsQuery || '').trim().toLowerCase(), f = ui.rsFilter || 'all';
  return patients.map(p => ({p, e:latest(episodes, p.patient_ref)}))
    .filter(({p}) => !q || String(p.full_name).toLowerCase().includes(q))
    .filter(({e}) => f === 'all' || (f === 'att' ? attention(e) : f === 'done' ? reached(e) : !!e && e.status === 'active' && !attention(e) && !reached(e)));
}
function table(list, selected){
  if (!list.length) return `<div class="c-tw"><table class="c-tbl"><tbody><tr><td style="color:var(--c-fg3)">Никого нет в этом фильтре.</td></tr></tbody></table></div>`;
  return `<div class="c-tw"><table class="c-tbl"><thead><tr><th>Пациент</th><th>Исследование</th><th>Путь</th><th>Шаг</th><th>Статус</th></tr></thead><tbody>${list.map(({p, e}) => {
    const s = e && current(e), years = age(p.birth_date);
    return `<tr class="${p.patient_ref === selected ? 'live' : ''}" data-action="rsPatientPick" data-ref="${safe(p.patient_ref)}">
      <td><button type="button" class="c-pp c-plain" data-action="rsPatientPick" data-ref="${safe(p.patient_ref)}"><span class="c-av" style="display:grid;place-items:center;font-weight:600;color:var(--c-blue)">${safe(initials(p.full_name))}</span><span><b>${safe(p.full_name)}</b><small>${years != null ? `${years} ${plural(years, ['год', 'года', 'лет'])}` : ''}</small></span></button></td>
      <td style="white-space:normal;min-width:140px">${e ? safe(e.title) : '—'}</td><td>${dots(stage(e))}</td>
      <td style="white-space:normal;min-width:160px">${safe(stepText(s))}${due(s) ? `<br><small style="color:var(--c-fg3)">${safe(due(s))}</small>` : ''}</td>
      <td>${pill(e)}${e ? `<br><small style="color:var(--c-fg3);white-space:normal">${safe(staffReason(e))}</small>` : ''}</td></tr>`;
  }).join('')}</tbody></table></div>`;
}

function loadCard(ref){
  cards[ref] = {status:'loading', data:cards[ref]?.data || null, message:''};
  api('GET', `/api/staff/patients/${enc(ref)}/card`, {role:'doctor'})
    .then(data => { cards[ref] = {status:'ok', data, message:''}; }, err => { cards[ref] = {status:'error', data:null, message:'Не удалось открыть карту пациента. ' + err.message}; })
    .then(() => { if (state.page === 'rsPatients') redraw(); });
}
function cardFacts(ref){
  const c = cards[ref];
  if (!c || (c.status === 'loading' && !c.data)) return '<div class="c-skel" style="min-height:60px"></div>';
  if (c.status === 'error') return `<div class="c-err" role="alert"><p>${safe(c.message)}</p><button class="c-btn sm" type="button" data-action="rsCardRetry" data-ref="${safe(ref)}">Повторить</button></div>`;
  const all = c.data.anamnesis || [];
  const line = a => `<div class="c-kv"><span>${safe(KINDS[a.kind] || a.kind)}</span><span>${safe(a.text)}${a.shareable ? '' : ' <small style="color:var(--c-fg3)">(только своя клиника)</small>'}</span></div>`;
  const facts = all.filter(a => FACTS.includes(a.kind)), other = all.filter(a => !FACTS.includes(a.kind)).slice(-5);
  return `<div class="c-fld"><label>Учтено из карты</label><div class="c-kvs">${facts.map(line).join('') || '<span class="c-demo">Диагнозов, факторов риска и аллергий в карте нет.</span>'}</div></div>
    ${other.length ? `<div class="c-fld"><label>Другие записи анамнеза</label><div class="c-kvs">${other.map(line).join('')}</div></div>` : ''}`;
}
function anamnesisForm(ref){
  const a = ui.rsAnam && ui.rsAnam.ref === ref ? ui.rsAnam : {kind:'note', text:'', share:false, busy:false};
  return `<div class="c-fld"><label for="rsAnText">Запись в анамнез</label>
    <select id="rsAnKind" aria-label="Вид записи">${Object.entries(KINDS).map(([key, label]) => `<option value="${key}"${a.kind === key ? ' selected' : ''}>${label}</option>`).join('')}</select>
    <textarea id="rsAnText" maxlength="4000" style="min-height:70px;border:1.5px solid transparent;border-radius:12px;padding:10px 12px;font:inherit;font-size:13px;resize:vertical;background:var(--c-main);color:var(--c-fg)">${safe(a.text)}</textarea>
    <label style="display:flex;gap:8px;align-items:center;font-size:13px;color:var(--c-fg)"><input type="checkbox" id="rsAnShare"${a.share ? ' checked' : ''}>Показывать клиникам-партнёрам</label></div>
    <div class="c-act"><button class="c-btn gh sm" type="button" data-action="rsAnamnesisAdd" data-ref="${safe(ref)}"${a.busy ? ' disabled' : ''}>${a.busy ? 'Сохраняем…' : 'Добавить в анамнез'}</button></div>`;
}
function patientCard(p, e){
  const s = e && current(e), years = age(p.birth_date), job = e?.source_report?.source_report_id;
  if (!cards[p.patient_ref]) queueMicrotask(() => { if (!cards[p.patient_ref]) loadCard(p.patient_ref); });
  /* Две карточки под таблицей: сводка и план врача; карта клиники и запись в анамнез */
  return `<div class="c-grid" id="rsPatientCard"><div class="c-card c-pcard"><div style="display:flex;align-items:center;gap:16px"><div class="c-pav" style="width:84px;height:84px;margin:0;display:grid;place-items:center;font-size:26px;color:var(--c-blue);flex-shrink:0">${safe(initials(p.full_name))}</div>
      <div><b class="nm" style="font-size:20px;font-weight:400">${safe(p.full_name)}</b><div style="font-size:12px;color:var(--c-fg2)">${years != null ? `${years} ${plural(years, ['год', 'года', 'лет'])}` : 'Возраст не указан'}</div></div></div>
    <div class="c-kvs">${[['Исследование', e ? `${e.title}, ${day(e.created_at)}` : 'Нет обращений'], ['Шаг', stepText(s)], ['Срок', due(s) || '—'],
      ['Статус', e ? `${statusName(e.status)} · ${staffReason(e)}` : 'Нет маршрута']].map(([a, b]) => `<div class="c-kv"><span>${a}</span><span>${safe(b)}</span></div>`).join('')}</div>
    <div class="c-act">${job ? `<button class="c-btn gh" type="button" data-action="rsStudyOpen" data-id="${safe(job)}">Открыть исследование</button>` : ''}${planButton(e)}</div>
    ${planCard(e)}</div>
    <div class="c-card"><div class="c-ch"><span><h2>Карта пациента</h2><span class="sub">сервис клиники «Линия здоровья»</span></span></div>${cardFacts(p.patient_ref)}${anamnesisForm(p.patient_ref)}</div></div>`;
}

export function rsPatients(){
  return head('Пациенты', 'Путь каждого пациента: исследование, шаг, срок и статус') + stateOf('patients', patients => stateOf('episodes', episodes => {
    if (!patients.length) return empty('Пациентов нет', 'Карты пациентов клиники появятся здесь.');
    const count = patients.filter(p => attention(latest(episodes, p.patient_ref))).length;
    const filters = `<div class="c-fl" role="group" aria-label="Фильтр">${FILTERS.map(([id, label]) => `<button type="button" data-action="rsFilter" data-id="${id}" aria-pressed="${(ui.rsFilter || 'all') === id}">${label}${id === 'att' && count ? ` <b>${count}</b>` : ''}</button>`).join('')}</div>`;
    const list = rows(patients, episodes);
    if (!ui.rsPatient || !patients.some(p => p.patient_ref === ui.rsPatient)) ui.rsPatient = (list[0] || {p:patients[0]}).p.patient_ref;
    const p = patients.find(x => x.patient_ref === ui.rsPatient);
    const search = ui.rsQuery ? `<span class="c-demo">Поиск: «${safe(ui.rsQuery)}»</span>` : '';
    return `${filters}${search}<div class="c-card" style="padding:10px">${table(list, ui.rsPatient)}</div>${patientCard(p, latest(episodes, p.patient_ref))}`;
  }));
}

export function installPatientActions(ACTIONS){
  ACTIONS.rsFilter = d => { ui.rsFilter = d.id; redraw(); };
  ACTIONS.rsPatientPick = d => {
    if (ui.rsPatient !== d.ref){ ui.rsPatient = d.ref; ui.rsPlan = null; redraw(); }
    document.getElementById('rsPatientCard')?.scrollIntoView({block:'nearest', behavior:'smooth'});
  };
  ACTIONS.rsCardRetry = d => { loadCard(d.ref); redraw(); };
  ACTIONS.rsAnamnesisAdd = async d => {
    const a = ui.rsAnam && ui.rsAnam.ref === d.ref ? ui.rsAnam : (ui.rsAnam = {ref:d.ref, kind:'note', text:'', share:false, busy:false});
    if (a.busy) return;
    if (!a.text.trim()) return toast('Напишите текст записи.');
    a.busy = true; redraw();
    try {
      await api('POST', `/api/staff/patients/${enc(d.ref)}/anamnesis`, {role:'doctor', body:{kind:a.kind, text:a.text.trim(), shareable:a.share}});
    } catch (err){ a.busy = false; redraw(); toast(err.message); return; }  // текст остаётся в поле
    ui.rsAnam = null;
    toast('Запись добавлена в анамнез');
    loadCard(d.ref);
  };
  const anam = fn => { const ref = ui.rsPatient; if (!ref) return; if (!ui.rsAnam || ui.rsAnam.ref !== ref) ui.rsAnam = {ref, kind:'note', text:'', share:false, busy:false}; fn(ui.rsAnam); };
  document.addEventListener('input', e => { if (e.target.id === 'rsAnText') anam(a => { a.text = e.target.value; }); });
  document.addEventListener('change', e => {
    if (e.target.id === 'rsAnKind') anam(a => { a.kind = e.target.value; });
    if (e.target.id === 'rsAnShare') anam(a => { a.share = e.target.checked; });
  });
}
