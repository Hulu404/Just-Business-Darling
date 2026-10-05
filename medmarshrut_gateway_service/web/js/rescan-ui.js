/* Кабинет врача rescan (задание 12): композиция prototype/rescan-app-standalone.html на данных шлюза.
   Экраны #/doctor/rsToday … rsSettings рисуются в #view внутри #clinic; полоса с логотипом и списком ролей —
   на месте прежней шапки (#topbar). Стили — rescan.css, всё под #clinic и префиксом c-. */
import { api } from './api.js';
import { health, sessions, state, ui } from './state.js';
import { go, safe } from './ui.js';
import { installStudyActions, rsStudies, studyNeeds } from './rescan-studies.js';
import { installCaseActions } from './rescan-cases.js';
import { installVisitActions, rsVisits, visitNeeds } from './rescan-visits.js';
import { installPatientActions, patientNeeds, rsPatients } from './rescan-patients.js';
import { installPlanActions } from './rescan-plan.js';
import { installTodayActions, rsToday, todayNeeds } from './rescan-today.js';

export const RS_PAGES = ['rsToday', 'rsStudies', 'rsPatients', 'rsVisits', 'rsSettings'];
export const isRescanPage = () => state.role === 'doctor' && RS_PAGES.includes(state.page);

/* ---------- Значки и логотип образца ---------- */
const KI = {
  cat:'M5 3h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM16 3h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2h-3a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM16 14h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2h-3a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2zM5 14h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2z',
  users:'M9.2 10.9a3.4 3.4 0 1 0 0-6.8 3.4 3.4 0 0 0 0 6.8zM16.4 4.2a3 3 0 0 1 0 5.8M3 19.6c0-3 2.8-5.2 6.2-5.2s6.2 2.2 6.2 5.2M18.3 14.4c1.7.4 2.8 1.6 2.8 3.4',
  cal:'M8 2.5v3M16 2.5v3M3.5 9.1h17M21 8.5V17c0 3-1.5 5-5 5H8c-3.5 0-5-2-5-5V8.5c0-3 1.5-5 5-5h8c3.5 0 5 2 5 5z',
  set:'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2 12.9v-1.8c0-1 .9-1.9 1.9-1.9 1.8 0 2.6-1.3 1.6-2.9-.5-.9-.2-2.1.7-2.6l1.7-1c.8-.5 1.8-.2 2.3.6l.1.2c.9 1.6 2.4 1.6 3.3 0l.1-.2c.5-.8 1.5-1.1 2.3-.6l1.7 1c.9.5 1.2 1.7.7 2.6-1 1.6-.2 2.9 1.6 2.9 1 0 1.9.8 1.9 1.9v1.8c0 1-.9 1.9-1.9 1.9-1.8 0-2.6 1.3-1.6 2.9.5.9.2 2.1-.7 2.6l-1.7 1c-.8.5-1.8.2-2.3-.6l-.1-.2c-.9-1.6-2.4-1.6-3.3 0l-.1.2c-.5.8-1.5 1.1-2.3.6l-1.7-1c-.9-.5-1.2-1.7-.7-2.6 1-1.6.2-2.9-1.6-2.9-1 0-1.9-.9-1.9-1.9z',
  search:'M11.5 21a9.5 9.5 0 1 0 0-19 9.5 9.5 0 0 0 0 19zM22 22l-2-2',
  bell:'M12 6.4v3.3M12 2c-3.7 0-6.6 3-6.6 6.6v2.1c0 .7-.3 1.7-.6 2.3l-1.3 2.1c-.8 1.3-.2 2.8 1.2 3.3 4.7 1.6 9.8 1.6 14.5 0 1.3-.4 1.9-2 1.2-3.3l-1.3-2.1c-.4-.6-.6-1.6-.6-2.3V8.6C18.6 5 15.6 2 12 2zM15.3 19c0 1.8-1.5 3.3-3.3 3.3-.9 0-1.7-.4-2.3-1-.6-.6-1-1.4-1-2.3',
  hosp:'M2 22h20M3 22V6c0-2 1-3 3-3h12c2 0 3 1 3 3v16M9 22v-4h6v4M12 7v6M9 10h6',
  steth:'M6 3H5a2 2 0 0 0-2 2v4a5 5 0 0 0 10 0V5a2 2 0 0 0-2-2h-1M8 14v1a6 6 0 0 0 12 0v-2M20 13a2 2 0 1 0 0-4 2 2 0 0 0 0 4z',
  scan:'M2 9V6.5C2 4 4 2 6.5 2H9M15 2h2.5C20 2 22 4 22 6.5V9M22 16v1.5c0 2.5-2 4.5-4.5 4.5H16M9 22H6.5C4 22 2 20 2 17.5V15M7 12h10',
  check:'M5 12l5 5L20 7', l:'M15 19l-7-7 7-7', r:'M9 5l7 7-7 7'
};
export const k = (n, s = 22, w = 1.5) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${KI[n]}"/></svg>`;
const star = (cx, cy, t, q) => `M${cx - t},${cy - t} Q${cx},${cy - q} ${cx + t},${cy - t} Q${cx + q},${cy} ${cx + t},${cy + t} Q${cx},${cy + q} ${cx - t},${cy + t} Q${cx - q},${cy} ${cx - t},${cy - t}Z`;
export function logo(size, word){
  const c = [25, 31.1], R = 11.31;
  const pt = a => { a = a * Math.PI / 180; return (c[0] + R * Math.cos(a)).toFixed(2) + ',' + (c[1] + R * Math.sin(a)).toFixed(2); };
  const mark = `<svg class="rs-mark" width="${size}" height="${size}" viewBox="10.6 16.6 28.8 28.8" aria-hidden="true" fill="none"><path d="${star(30.35, 23, 5.7, .75)}" fill="currentColor"/><path d="${star(19.65, 39.2, 5.7, .75)}" fill="currentColor"/><path d="M${pt(167.75)} A${R},${R} 0 0 1 ${pt(232)}M${pt(-12.25)} A${R},${R} 0 0 1 ${pt(52)}" stroke="currentColor" stroke-width="1.15" stroke-linecap="round"/></svg>`;
  return word ? `<span class="rs-logo">${mark}<span>rescan</span></span>` : mark;
}

/* ---------- Шрифт: только если файл лежит на машине (GET /api/health → brand_font) ---------- */
let fontRequested = false;
function ensureBrandFont(){
  if (fontRequested || !health.data?.brand_font || typeof FontFace === 'undefined') return;
  fontRequested = true;
  const face = new FontFace('Stolzl', 'url(/assets/fonts/Stolzl-Regular.otf)');
  face.load().then(f => document.fonts.add(f)).catch(() => {});  // без шрифта кабинет на системном стеке
}

/* ---------- Данные экранов: {status:'loading'|'ok'|'error', data, message} ---------- */
const LOADERS = {
  studies:() => api('GET', '/api/doctor/studies', {role:'doctor'}).then(b => b.studies || []),
  patients:() => api('GET', '/api/staff/patients', {role:'doctor'}).then(b => b.patients || []),
  episodes:() => api('GET', '/api/staff/episodes', {role:'doctor'}).then(b => b.episodes || []),
  visits:() => api('GET', '/api/doctor/visits', {role:'doctor'}).then(b => b.visits || []),
  manual:() => api('GET', '/api/staff/studies/manual', {role:'doctor'}),
  assistant:() => api('GET', '/api/assistant/status', {role:'doctor'}),
  catalog:() => api('GET', '/api/catalog', {role:'doctor'}),
  rules:() => api('GET', '/api/staff/rules', {role:'doctor'})
};
/* Открытое исследование по таймеру не перечитывается: правка врача не должна пропасть */
const NEEDS = {rsToday:todayNeeds, rsStudies:studyNeeds, rsPatients:patientNeeds, rsVisits:visitNeeds, rsSettings:() => ['assistant']};
export const rs = {};
const inflight = {};
let rerender = () => {};
export const setRescanRender = fn => { rerender = fn; };
export const redraw = () => rerender();

export async function load(key){
  if (inflight[key]) return inflight[key];
  if (!rs[key]) rs[key] = {status:'loading', data:null, message:''};
  inflight[key] = (async () => {
    try { rs[key] = {status:'ok', data:await LOADERS[key](), message:''}; }
    catch (err){ rs[key] = {status:'error', data:rs[key].data, message:err.message}; }
    delete inflight[key];
    if (isRescanPage()) rerender();
  })();
  return inflight[key];
}
/* Перечитать данные открытого экрана: при переходе и по таймеру main.js (timer = true) */
export function refreshRescan(timer = false){
  if (!isRescanPage() || sessions.doctor?.status !== 'ok') return;
  (NEEDS[state.page] ? NEEDS[state.page](timer) : []).forEach(load);
}

/* ---------- Состояния: загрузка, ошибка с «Повторить», пусто ---------- */
const skeleton = (n = 2) => `<div class="c-col" aria-busy="true" aria-label="Загружаем">${'<div class="c-skel"></div>'.repeat(n)}</div>`;
const errorBox = (message, key) => `<div class="c-err" role="alert"><p>${safe(message)}</p><button class="c-btn sm" type="button" data-action="rsRetry" data-key="${safe(key)}">Повторить</button></div>`;
export const empty = (title, text) => `<div class="c-empty"><b>${safe(title)}</b><span>${safe(text)}</span></div>`;
/* Блок по источнику: пока данных нет — заглушка, ошибка без данных — «Повторить», иначе view(data) */
export function stateOf(key, view){
  const s = rs[key];
  if (!s || (s.status === 'loading' && s.data === null)) return skeleton();
  if (s.status === 'error' && s.data === null) return errorBox(s.message, key);
  return (s.status === 'error' ? errorBox('Не удалось обновить данные. ' + s.message, key) : '') + view(s.data);
}

/* ---------- Каркас: полоса, шапка, рельса ---------- */
const NAV = [['rsToday', 'cat', 'Сегодня'], ['rsStudies', 'scan', 'Исследования'], ['rsPatients', 'users', 'Пациенты'], ['rsVisits', 'cal', 'Приёмы']];
const greet = () => { const h = new Date().getHours(); return h >= 5 && h < 12 ? 'Доброе утро' : h >= 12 && h < 17 ? 'Добрый день' : h >= 17 && h < 23 ? 'Добрый вечер' : 'Доброй ночи'; };
const today = () => { const t = new Date().toLocaleDateString('ru-RU', {weekday:'short', day:'numeric', month:'long'}); return t.charAt(0).toUpperCase() + t.slice(1); };
const doctorName = () => sessions.doctor?.data?.name || 'Врач';
const initials = name => name.split(/[\s,]+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');
export const head = (title, sub, right = '') => `<div class="c-h"><div><h1>${title}</h1>${sub ? `<p>${sub}</p>` : ''}</div>${right}</div>`;

/* Полоса над кабинетом: логотип и тот же список ролей #role, что в боковой панели прежнего каркаса */
export const modebar = roleSelect => `<div class="wm">${logo(22, true)}</div><div class="rolebox"><label for="role">Режим просмотра</label>${roleSelect}</div>`;

/* ---------- Колокольчик: лента из новых исследований и журнала эпизодов ---------- */
const FEED_DOT = {step_confirmed:'#1866A0', step_attended:'#06D6A0', outcome_confirmed:'#06D6A0'};
const feedText = {step_confirmed:'записался', step_attended:'был на приёме', outcome_confirmed:'итог приёма внесён'};
function feedEvents(){
  const studies = rs.studies?.data || [], episodes = rs.episodes?.data || [], events = [];
  studies.filter(s => s.status === 'awaiting_physician')
    .forEach(s => events.push({title:'Новое исследование: ' + s.patient, sub:s.title, at:s.created_at, dot:'#FDAF04'}));
  episodes.forEach(e => (e.audit_events || []).forEach(a => {
    if (!FEED_DOT[a.event_type]) return;
    const step = (e.steps || []).find(s => s.id === (a.details || {}).step_id);
    events.push({title:e.patient + ', ' + feedText[a.event_type], sub:step ? step.description : e.title, at:a.occurred_at, dot:FEED_DOT[a.event_type]});
  }));
  return events.sort((a, b) => String(b.at).localeCompare(String(a.at))).slice(0, 10);
}
function feedPanel(){
  if (!ui.rsFeed) return '';
  const pending = (rs.studies?.status === 'loading' && !rs.studies.data) || (rs.episodes?.status === 'loading' && !rs.episodes.data) || (!rs.studies && !rs.episodes);
  const events = feedEvents();
  const body = pending ? '<div class="c-skel" style="min-height:48px"></div>'
    : events.length ? events.map(e => `<div style="display:flex;gap:10px;font-size:12px"><span style="width:8px;height:8px;border-radius:50%;margin-top:5px;flex-shrink:0;background:${e.dot}"></span><span><b style="font-weight:600;display:block">${safe(e.title)}</b><span style="color:#5B6370">${safe(e.sub)}</span></span></div>`).join('')
    : empty('Лента пока пуста', 'Здесь появятся новые исследования, записи и визиты пациентов.');
  return `<div class="c-feed" role="dialog" aria-label="Уведомления"><b style="font-size:14px">Уведомления</b>${body}</div>`;
}
function cabinet(body){
  const name = doctorName();
  const fresh = (rs.studies?.data || []).filter(s => s.status === 'awaiting_physician').length;  // точка на колокольчике и «Исследованиях»
  const dot = '<span class="bd"></span>';
  const rail = NAV.map(([id, ic, label]) => `<button class="c-ri" type="button" data-nav="${id}" aria-label="${label}" title="${label}"${state.page === id ? ' aria-current="page"' : ''}>${k(ic, 24)}${id === 'rsStudies' && fresh ? dot : ''}</button>`).join('');
  return `<div id="clinic"><div class="c-app"><div class="c-logo">${logo(34)}</div>
    <div class="c-top"><div class="c-greet"><b>${greet()}, ${safe(name)}</b><span class="c-meta"><span>${k('cal', 14, 1.7)}${safe(today())}</span><span>${k('hosp', 14, 1.7)}Клиника «Линия здоровья»</span><span>${k('steth', 14, 1.7)}Врач</span><span class="demo">демо-стенд</span></span></div>
      <label class="c-search">${k('search', 18)}<input id="rsQuery" placeholder="Найти пациента" value="${safe(ui.rsQuery || '')}" aria-label="Найти пациента" autocomplete="off"></label>
      <button class="c-ib" type="button" data-action="rsFeed" aria-label="Уведомления" aria-expanded="${ui.rsFeed ? 'true' : 'false'}">${k('bell', 22)}${fresh ? dot : ''}</button>
      <span class="c-me" title="${safe(name)}" style="font-weight:600;color:var(--c-blue)">${safe(initials(name))}</span></div>
    <nav class="c-rail" aria-label="Разделы">${rail}<span class="c-sep"></span><button class="c-ri" type="button" data-nav="rsSettings" aria-label="Настройки" title="Настройки"${state.page === 'rsSettings' ? ' aria-current="page"' : ''}>${k('set', 24)}</button></nav>
    <section class="c-main">${feedPanel()}${body}</section></div></div>`;
}

/* ---------- «Настройки»: состояние трёх сервисов, режим снимков, ИИ-помощник, число клиник-партнёров ---------- */
const MODE_LABEL = {'demo-scripted':'сценарный разбор, демо', 'model':'локальная модель', 'no-model':'без модели'};
/* МИС, РИС, каналы пациентов и аптеки на стенде не подключены (решение владельца задания) */
const NOT_CONNECTED = [['МИС клиники', 'Карта, назначения и визиты'], ['РИС и PACS', 'Исследования и протоколы'],
  ['Каналы пациентов', 'Telegram, SMS, почта'], ['Аптеки-партнёры', 'Бронь и выдача по рецепту']];
const setCard = (title, tone, label, desc) => `<div class="c-card"><b style="font-size:15px">${safe(title)}</b><span class="c-s ${tone}" style="align-self:flex-start;min-width:0">${safe(label)}</span><span style="font-size:12px;color:var(--c-fg2)">${safe(desc)}</span></div>`;
function svcCard(title, key, desc){
  const service = health.data?.services?.[key];
  const [tone, label] = !service ? ['grey', 'нет данных'] : service.status === 'up' ? ['green', 'работает'] : ['red', 'недоступен'];
  return setCard(title, tone, label, desc);
}
const healthError = () => `<div class="c-err" role="alert"><p>${safe(health.message)}</p><button class="c-btn sm" type="button" data-action="healthRetry">Повторить</button></div>`;
function rsSettings(){
  const intro = head('Настройки', 'Что подключено на стенде');
  if (health.status === 'error') return intro + healthError();
  if (health.status !== 'ok' || !health.data) return intro + skeleton(3);
  const mode = MODE_LABEL[health.data.imaging_mode] || health.data.imaging_mode;
  const partners = (health.data.partner_clinics || []).length;
  return intro + stateOf('assistant', a => `<div class="c-g3">
    ${svcCard('Сервис «Что на снимке?»', 'image', 'Приём снимков и проверка врачом')}
    ${svcCard('Сервис маршрута', 'path', 'Правила клиники и следующий шаг')}
    ${svcCard('Сервис клиники', 'clinic', 'Карта пациента, сеть, направления')}
    ${setCard('Режим снимков', 'blue', mode, 'Как стенд разбирает исследования')}
    ${setCard('ИИ-помощник', a.enabled ? 'green' : 'grey', a.enabled ? 'включён' : 'выключен: нет ключа API', 'Формулировка врачу, пояснение пациенту')}
    ${setCard('Клиники-партнёры', partners ? 'green' : 'grey', String(partners), 'Запись к специалистам')}
    ${NOT_CONNECTED.map(([title, desc]) => setCard(title, 'grey', 'не подключено на стенде', desc)).join('')}</div>`);
}
const SCREENS = {rsToday, rsStudies, rsPatients, rsVisits, rsSettings};
export const RESCAN_PAGES = Object.fromEntries(RS_PAGES.map(id => [id, () => {
  if (state.role !== 'doctor') return '<div class="note">Этот раздел открывается в окне врача. Выберите «Врач» в списке ролей.</div>';
  ensureBrandFont();
  return cabinet(SCREENS[id]());
}]));

/* ---------- Действия ---------- */
export function installRescanActions(ACTIONS){
  ACTIONS.rsRetry = d => { rs[d.key] = {status:'loading', data:null, message:''}; rerender(); load(d.key); };
  /* Колокольчик работает на любом экране: при открытии подтянуть источники ленты */
  ACTIONS.rsFeed = () => { ui.rsFeed = !ui.rsFeed; if (ui.rsFeed){ load('studies'); load('episodes'); } rerender(); };
  ACTIONS.rsRender = () => rerender();
  installStudyActions(ACTIONS);
  installCaseActions(ACTIONS);
  installVisitActions(ACTIONS);
  installPatientActions(ACTIONS);
  installPlanActions(ACTIONS);
  installTodayActions(ACTIONS);
  /* Поиск пациента: текст живёт в ui.rsQuery, в «Пациентах» список фильтруется сразу, Enter открывает «Пациентов» */
  document.addEventListener('input', e => { if (e.target.id !== 'rsQuery') return; ui.rsQuery = e.target.value; if (state.page === 'rsPatients') rerender(); });
  document.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.id === 'rsQuery' && state.page !== 'rsPatients') go('rsPatients'); });
}
