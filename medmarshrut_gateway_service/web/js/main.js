/* Запуск: адрес окна задаёт роль и экран (#/staff/case), сессия роли создаётся в шлюзе, состояние сервисов — из /api/health */
import { createSession, getHealth } from './api.js';
import { ACTIONS, PAGES } from './actions.js';
import { render, renderBanner } from './shell.js';
import { freshState, health, hooks, sessions, setState, state, ui } from './state.js';

const ROLES = ['patient', 'staff', 'doctor'];
const HEALTH_EVERY = 15000;

function parseHash(){
  const m = /^#\/([a-z]+)\/([A-Za-z]+)$/.exec(location.hash);
  return m && ROLES.includes(m[1]) && Object.prototype.hasOwnProperty.call(PAGES, m[2]) ? {role:m[1], page:m[2]} : null;
}
const hashOf = () => `#/${state.role}/${state.page}`;

/* Сессия роли окна. Пока её нет, shell показывает заглушку; при ошибке — блок с «Повторить» */
async function ensureSession(role){
  const current = sessions[role];
  if (current && current.status !== 'error') return;
  sessions[role] = {status:'loading', data:null, message:''};
  if (state.role === role) render();
  try {
    /* Окно без сессии в памяти открывает свою: так первая загрузка не упирается в 401 */
    sessions[role] = {status:'ok', data:await createSession(role), message:''};
  } catch (err){
    sessions[role] = {status:'error', data:null, message:'Не удалось открыть сессию. ' + err.message};
  }
  if (state.role === role) render();
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
  ensureSession(state.role);
}

/* go() из прототипа меняет экран сразу; адрес и сессия догоняют здесь */
hooks.navigate = () => {
  if (location.hash !== hashOf()) history.pushState(null, '', hashOf());
  ensureSession(state.role);
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
ensureSession(state.role);
refreshHealth();
setInterval(refreshHealth, HEALTH_EVERY);
