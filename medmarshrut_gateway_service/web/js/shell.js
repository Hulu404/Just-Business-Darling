import { PAGES } from './actions.js';
import { awaitingOutcome, queueInfo, waitingOn } from './domain.js';
import { icon } from './icons.js';
import { appointments, documents, home, intake, messages, pharmacy, plan, result, review } from './pages/patient.js';
import { services } from './pages/services.js';
import { isRescanPage, modebar } from './rescan-ui.js';
import { isPhonePage } from './rescan-phone.js';
import { analytics, comms, inbox, pharmacyAdmin, requests, rules, scheduling } from './pages/staff.js';
import { health, sessions, state, ui } from './state.js';
import { $, badge, errorNote, loadingCards, renderModal, safe, serviceBanner } from './ui.js';

/* ---------- Каркас: меню, шапка, отрисовка ---------- */
export const NAVS = {
  patient:[['rsHome','home','Главная'],['rsCare','pharmacy','Лечение'],['rsCalendar','calendar','Календарь'],['rsBook','route','Запись'],['rsProfile','doc','Профиль']],
  staff:[['inbox','inbox','Обращения'],['scheduling','clock','Запись и сопровождение'],['requests','doctor','Связь с врачами'],['comms','message','Связь с пациентами'],['partners','link','Партнёры'],['pharmacyAdmin','pharmacy','Аптека и заказы'],['rules','sliders','Маршруты и правила'],['analytics','bars','Аналитика']],
  doctor:[['rsToday','home','Сегодня'],['rsStudies','scan','Исследования'],['rsPatients','route','Пациенты'],['rsVisits','calendar','Приёмы'],['rsSettings','sliders','Настройки']],
  partner:[['incoming','inbox','Входящие направления']]
};
export const HOME = {patient:'rsHome', staff:'inbox', doctor:'rsToday', partner:'incoming'};
export const roleName = () => state.role === 'patient' ? 'Пациент' : state.role === 'staff' ? 'Клиника' : state.role === 'partner' ? 'Клиника-партнёр' : 'Врач';
export function navCount(id){
  if (state.role === 'patient'){
    if (id === 'messages') return state.messages.filter(m => m.unread).length;
    if (id === 'pharmacy') return Object.values(state.cart).reduce((a, b) => a + b, 0);
  }
  if (state.role === 'staff'){
    if (id === 'inbox') return state.pathCounts?.inbox || 0;
    if (id === 'requests') return state.requests.filter(r => r.status === 'open' && waitingOn(r) === 'staff').length;
    if (id === 'pharmacyAdmin') return state.orders.filter(o => o.status === 'Собирается').length;
  }
  if (state.role === 'partner' && id === 'incoming') return state.partnerIncoming || 0;
  return 0;
}
export function pageTitle(){
  const t = {home:'Главная', intake:'Новое обращение', review:'Проверка данных', result:'Ваш МедМаршрут', plan:'Мой план', imaging:'Что на снимке', appointments:'Записи', messages:'Сообщения', pharmacy:'Аптека', documents:'Документы', inbox:'Обращения', case:'Карточка обращения', scheduling:'Запись и сопровождение', requests:'Связь с врачами', comms:'Связь с пациентами', partners:'Партнёры', pharmacyAdmin:'Аптека и заказы', rules:'Маршруты и правила', analytics:'Аналитика', services:'Карта сервисов', incoming:'Входящие направления', referral:'Входящее направление'};
  return t[state.page] || 'МедМаршрут';
}
export function renderShell(){
  /* Кабинет rescan: прежние боковая панель и шапка скрыты, на месте шапки — полоса с логотипом и тем же #role */
  if (isRescanPage() || isPhonePage()){
    $('#sidebar').className = 'sidebar';
    $('#sidebar').innerHTML = '';
    $('#topbar').className = 'modebar';
    $('#topbar').innerHTML = modebar(roleSelect());
    return;
  }
  $('#topbar').className = 'topbar';
  const nav = NAVS[state.role] || NAVS.patient;
  const parent = {case:'inbox', referral:'incoming'}[state.page] || state.page;
  const item = ([id, ic, label]) => { const n = navCount(id); return `<button data-nav="${id}" class="${parent === id ? 'active' : ''}"><span class="icon">${icon(ic)}</span>${label}${n ? `<span class="count">${n}</span>` : ''}</button>`; };
  $('#sidebar').className = 'sidebar' + (ui.mobileOpen ? ' open' : '');
  $('#sidebar').innerHTML = `<div class="brand"><span class="brandmark">+</span><div>МедМаршрут<small>Демо-стенд</small></div></div>
    <div class="rolebox"><label for="role">Режим просмотра</label>${roleSelect()}</div>
    <nav class="nav">${nav.map(item).join('')}${state.role === 'patient' ? `<button data-action="new"><span class="icon">${icon('plus')}</span>Новое обращение</button>` : ''}<div class="navsep"></div>${item(['services', 'map', 'Карта сервисов'])}</nav>
    <div class="sidefoot">Демо клиники «Линия здоровья».<br>Все пациенты, записи и цифры в прототипе вымышленные.<br><button data-action="reset">Сбросить демо</button></div>`;
  $('#topbar').innerHTML = `<div style="display:flex;align-items:center;gap:12px"><button class="mobilemenu" data-action="menu" aria-label="Меню">${icon('menu')}</button><strong>${safe(pageTitle())}</strong></div><div class="topright">${badge(roleName())}<span class="muted hidem" style="font-size:13px">Демо-режим</span></div>`;
}
/* В списке ролей только пациент и врач; окна сотрудника и партнёра открываются по адресу (#/staff/…, #/partner/…) */
const roleSelect = () => `<select id="role"><option value="patient" ${state.role === 'patient' ? 'selected' : ''}>Пациент</option><option value="doctor" ${state.role === 'doctor' ? 'selected' : ''}>Врач</option>${['staff', 'partner'].includes(state.role) ? `<option value="${state.role}" selected>${roleName()}</option>` : ''}</select>`;
export function render(){
  const fn = PAGES[state.page] || PAGES[HOME[state.role]];
  const html = sessionGate() || fn();
  document.body.classList.toggle('m-clinic', isRescanPage());
  document.body.classList.toggle('m-phone', isPhonePage());
  renderShell();
  renderBanner();
  $('#view').innerHTML = html;
  renderModal();
}

/* ---------- Дополнения продукта: сессия роли и состояние сервисов ---------- */
/* Пока сессии роли нет, на месте экрана заглушка или ошибка с «Повторить» */
function sessionGate(){
  const s = sessions[state.role];
  if (!s || s.status === 'loading') return loadingCards(3);
  if (s.status === 'error') return errorNote(s.message, 'sessionRetry');
  return '';
}
const SERVICE_NAMES = {image:'Сервис «Что на снимке?»', path:'Сервис маршрута', clinic:'Сервис клиники'};
export function renderBanner(){
  const down = health.status === 'ok' ? Object.entries(health.data.services).filter(([, x]) => x.status !== 'up').map(([k]) => k) : [];
  $('#banner').innerHTML = down.map(k => serviceBanner(`${SERVICE_NAMES[k] || k} недоступен. Данные могут быть неполными.`)).join('');
}
