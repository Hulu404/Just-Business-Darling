/* Запуск: адрес окна задаёт роль и экран (#/staff/case), сессия роли создаётся в шлюзе, состояние сервисов — из /api/health */
import { createSession, getHealth, sessionExtras } from './api.js';
import { ACTIONS, PAGES } from './actions.js';
import { render, renderBanner, renderShell } from './shell.js';
import { freshState, health, hooks, sessions, setState, state, ui } from './state.js';
import { installPathActions, isPathPage, pathAppointments, pathCase, pathHome, pathInbox, pathPlan, pathScheduling, refreshPath } from './path-ui.js';
import { installPathExtra, pathAnalytics, pathDoctor, pathRules, refreshPathExtra } from './path-extra.js';
import { imagingPage, installImagingActions, isImagingListPage, readingPage, refreshImaging, studyPage } from './imaging-ui.js';
import { analyticsClinicBlock, documentsReferrals, incomingPage, installClinicActions, isClinicPage, partnersPage, referralPage, refreshClinic } from './clinic-ui.js';
import { documents } from './pages/patient.js';
import { RESCAN_PAGES, installRescanActions, isRescanPage, refreshRescan, setRescanRender } from './rescan-ui.js';

const ROLES = ['patient', 'staff', 'doctor', 'partner'];
const DEFAULT_PARTNER = 'clinic-partner-1';
const HEALTH_EVERY = 15000;
Object.assign(PAGES, {home:pathHome, plan:pathPlan, appointments:pathAppointments,
                      inbox:pathInbox, case:pathCase, scheduling:pathScheduling,
                      doctor:pathDoctor, rules:pathRules, analytics:pathAnalytics,
                      imaging:imagingPage, reading:readingPage, study:studyPage,
                      partners:partnersPage, incoming:incomingPage, referral:referralPage,
                      documents:() => documents() + documentsReferrals(),
                      analytics:() => pathAnalytics() + analyticsClinicBlock(), ...RESCAN_PAGES});
installPathActions(ACTIONS);
installPathExtra(ACTIONS);
installImagingActions(ACTIONS);
installClinicActions(ACTIONS);
installRescanActions(ACTIONS);
/* Перерисовка кабинета по приходу данных не сбрасывает фокус и курсор в поле поиска */
setRescanRender(() => {
  const active = document.activeElement, id = active && active.id, at = active && active.selectionStart;
  render();
  const field = id && document.getElementById(id);
  if (field && field !== active && field.tagName === 'INPUT'){ field.focus({preventScroll:true}); try { field.setSelectionRange(at, at); } catch (err){} }
});
const refreshData = () => { refreshPath(); refreshPathExtra(); refreshImaging(); refreshClinic(); refreshRescan(); };
const sessionRequests = {};

/* Окно клиники-партнёра хранит клинику в адресе: #/partner/incoming?clinic=clinic-partner-2 */
function parseHash(){
  const m = /^#\/([a-z]+)\/([A-Za-z]+)(?:\?clinic=([a-z0-9-]+))?$/.exec(location.hash);
  if (!m || !ROLES.includes(m[1]) || !Object.prototype.hasOwnProperty.call(PAGES, m[2])) return null;
  return m[1] === 'partner' ? {role:m[1], page:m[2], partnerClinic:m[3] || DEFAULT_PARTNER} : {role:m[1], page:m[2]};
}
const hashOf = () => `#/${state.role}/${state.page}${state.role === 'partner' ? '?clinic=' + (state.partnerClinic || DEFAULT_PARTNER) : ''}`;

/* Сессия роли окна. Пока её нет, shell показывает заглушку; при ошибке — блок с «Повторить» */
async function ensureSession(role){
  if (role === 'partner'){
    state.partnerClinic = state.partnerClinic || DEFAULT_PARTNER;
    sessionExtras.partner = {clinic_id:state.partnerClinic};
    /* Кука у роли партнёра одна: окно другой клиники открывает свою сессию заново */
    if (sessions.partner?.status === 'ok' && sessions.partner.data?.clinic_id !== state.partnerClinic) delete sessions.partner;
  }
  const current = sessions[role];
  if (current?.status === 'ok') return;
  if (current?.status === 'loading') return sessionRequests[role];
  sessions[role] = {status:'loading', data:null, message:''};
  if (state.role === role) render();
  sessionRequests[role] = (async () => { try {
    /* Окно без сессии в памяти открывает свою: так первая загрузка не упирается в 401 */
    sessions[role] = {status:'ok', data:await createSession(role), message:''};
  } catch (err){
    sessions[role] = {status:'error', data:null, message:'Не удалось открыть сессию. ' + err.message};
  }
  if (state.role === role) render(); })();
  return sessionRequests[role];
}

/* Назад, вперёд и ручная правка адреса */
function applyRoute(){
  const route = parseHash();
  if (!route) history.replaceState(null, '', hashOf());
  else if (route.role !== state.role || route.page !== state.page || (route.partnerClinic || null) !== (state.role === 'partner' ? state.partnerClinic : null)){
    Object.assign(state, route);
    ui.mobileOpen = false; ui.modal = null;
  }
  render();
  window.scrollTo(0, 0);
  ensureSession(state.role).then(refreshData);
}

/* go() из прототипа меняет экран сразу; адрес и сессия догоняют здесь */
hooks.navigate = () => {
  if (location.hash !== hashOf()) history.pushState(null, '', hashOf());
  ensureSession(state.role).then(refreshData);
};

let lastHealth = '';
async function refreshHealth(){
  try {
    Object.assign(health, {status:'ok', data:await getHealth(state.role), message:''});
  } catch (err){
    Object.assign(health, {status:'error', data:null, message:'Не удалось узнать состояние сервисов. ' + err.message});
  }
  const snapshot = JSON.stringify(health);
  if (snapshot === lastHealth) return;
  lastHealth = snapshot;
  renderBanner();
  renderShell();  // в списке ролей — клиники-партнёры из /api/health
  if (state.page === 'services' && !ui.modal) render();
  else if (isRescanPage()) ACTIONS.rsRender();  // «Настройки» и шрифт кабинета — из /api/health
}

ACTIONS.sessionRetry = () => { delete sessions[state.role]; ensureSession(state.role); };
ACTIONS.healthRetry = () => { Object.assign(health, {status:'loading', data:null, message:''}); lastHealth = ''; render(); refreshHealth(); };

setState(freshState());
const start = parseHash();
if (start) Object.assign(state, start);
else history.replaceState(null, '', hashOf());
window.addEventListener('popstate', applyRoute);
render();
ensureSession(state.role).then(refreshData);
refreshHealth();
setInterval(refreshHealth, HEALTH_EVERY);
setInterval(() => { if (isPathPage()) refreshPath(); }, HEALTH_EVERY);
setInterval(refreshPathExtra, HEALTH_EVERY);
setInterval(() => { if (isImagingListPage()) refreshImaging(); }, HEALTH_EVERY);
setInterval(() => { if (isClinicPage() && state.page !== 'referral') refreshClinic(); }, HEALTH_EVERY);
setInterval(() => { if (isRescanPage()) refreshRescan(); }, HEALTH_EVERY);
