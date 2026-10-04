/* Запуск: адрес окна задаёт роль и экран (#/staff/case), сессия роли создаётся в шлюзе, состояние сервисов — из /api/health */
import { createSession, getHealth } from './api.js';
import { ACTIONS, PAGES } from './actions.js';
import { render, renderBanner } from './shell.js';
import { freshState, health, hooks, sessions, setState, state, ui } from './state.js';
import { installPathActions, isPathPage, pathAppointments, pathCase, pathHome, pathInbox, pathPlan, pathScheduling, refreshPath } from './path-ui.js';
import { installPathExtra, pathAnalytics, pathDoctor, pathRules, refreshPathExtra } from './path-extra.js';

const ROLES = ['patient', 'staff', 'doctor'];
const HEALTH_EVERY = 15000;
Object.assign(PAGES, {home:pathHome, plan:pathPlan, appointments:pathAppointments,
                      inbox:pathInbox, case:pathCase, scheduling:pathScheduling,
                      doctor:pathDoctor, rules:pathRules, analytics:pathAnalytics});
installPathActions(ACTIONS);
installPathExtra(ACTIONS);
const sessionRequests = {};

function parseHash(){
  const m = /^#\/([a-z]+)\/([A-Za-z]+)$/.exec(location.hash);
  return m && ROLES.includes(m[1]) && Object.prototype.hasOwnProperty.call(PAGES, m[2]) ? {role:m[1], page:m[2]} : null;
}
const hashOf = () => `#/${state.role}/${state.page}`;

/* Сессия роли окна. Пока её нет, shell показывает заглушку; при ошибке — блок с «Повторить» */
async function ensureSession(role){
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
  else if (route.role !== state.role || route.page !== state.page){
    Object.assign(state, route);
    ui.mobileOpen = false; ui.modal = null;
  }
  render();
  window.scrollTo(0, 0);
  ensureSession(state.role).then(() => { refreshPath(); refreshPathExtra(); });
}

/* go() из прототипа меняет экран сразу; адрес и сессия догоняют здесь */
hooks.navigate = () => {
  if (location.hash !== hashOf()) history.pushState(null, '', hashOf());
  ensureSession(state.role).then(() => { refreshPath(); refreshPathExtra(); });
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
  if (state.page === 'services' && !ui.modal) render();
}

ACTIONS.sessionRetry = () => { delete sessions[state.role]; ensureSession(state.role); };
ACTIONS.healthRetry = () => { Object.assign(health, {status:'loading', data:null, message:''}); lastHealth = ''; render(); refreshHealth(); };

setState(freshState());
const start = parseHash();
if (start) Object.assign(state, start);
else history.replaceState(null, '', hashOf());
window.addEventListener('popstate', applyRoute);
render();
ensureSession(state.role).then(() => { refreshPath(); refreshPathExtra(); });
refreshHealth();
setInterval(refreshHealth, HEALTH_EVERY);
setInterval(() => { if (isPathPage()) refreshPath(); }, HEALTH_EVERY);
setInterval(refreshPathExtra, HEALTH_EVERY);
