/* Роутер пилота на hash-адресах: токен пациента не уходит на сервер в адресе запроса страницы.
   Экран — модуль с export function render(view, ctx); ctx = { api, go, safe, theme, params, texts }.
   Экран не трогает адрес и тему напрямую: только ctx.go('/путь' или '#/путь') и ctx.theme.apply(...).
   ctx.texts — тексты оболочки (SHELL из texts.js); тексты пациента приходят в ответе сессии.
   ROUTES: pattern — RegExp по пути без '#', именованные группы → ctx.params; load — динамический import(),
   который возвращает объект с render. Ошибку экрана (исключение из render) показывает роутер. */
import { api, useToken, ApiError } from './api.js';
import { theme } from './theme.js';
import { SHELL } from './texts.js';
import { safe, skeleton, errorState, notFound } from './ui.js';

const TOKEN = '(?<token>[A-Za-z0-9_-]{1,128})';
const staff = name => () => import('./staff.js').then(module => module.screens[name]);

export const ROUTES = [
  {pattern:new RegExp(`^/p/${TOKEN}$`), area:'patient', load:() => import('./screens/patient-entry.js')},
  {pattern:new RegExp(`^/p/${TOKEN}/step$`), area:'patient', load:() => import('./screens/patient-step.js')},
  {pattern:new RegExp(`^/p/${TOKEN}/goal$`), area:'patient', load:() => import('./screens/patient-goal.js')},
  {pattern:new RegExp(`^/p/${TOKEN}/next$`), area:'patient', load:() => import('./screens/patient-next.js')},
  {pattern:/^\/staff\/login$/, area:'staff', load:staff('login')},
  {pattern:/^\/doctor$/, area:'staff', load:staff('doctor')},
  {pattern:/^\/clinic$/, area:'staff', load:staff('clinic')}
];

/* Путь из адреса: '#/p/abc/step?x=1' → '/p/abc/step'. Битая кодировка — пустой путь («такой страницы нет») */
export function currentPath(){
  try {
    return decodeURIComponent(window.location.hash.replace(/^#/, '').split('?')[0]);
  } catch {
    return '';
  }
}

export function match(path){
  for (const route of ROUTES){
    const found = route.pattern.exec(path);
    if (found) return {route, params:{...(found.groups || {})}};
  }
  return null;
}

/* Переход: go('/p/abc/step') или go('#/p/abc/step'). Тот же адрес — перерисовка экрана */
export function go(path){
  const bare = String(path).replace(/^#/, '');
  const target = '#' + (bare.startsWith('/') ? bare : '/' + bare);
  if (window.location.hash === target) renderCurrent();
  else window.location.hash = target;
}

let generation = 0;
let lastToken;

/* Фокус на содержимое после перехода, если экран не поставил его сам (например, на заголовок) */
function focusView(view){
  if (!view.contains(document.activeElement)) view.focus({preventScroll:true});
}

/* Тема: у пациента — сброс только при смене токена (экран применит тему клиники), у остальных — наша тема */
function prepareShell(area, params){
  const token = area === 'patient' ? params.token : null;
  if (area !== 'patient') theme.reset();
  else if (token !== lastToken) theme.reset({brand:''});
  lastToken = token;
  useToken(token);
  const bar = document.getElementById('staff-bar');
  if (bar){ bar.hidden = true; bar.replaceChildren(); }
}

function showError(view, err){
  if (err instanceof ApiError && err.status === 404){
    view.innerHTML = notFound();
    return;
  }
  if (!(err instanceof ApiError)) console.error('pilot: экран не открылся', err);
  view.innerHTML = errorState();
  view.querySelector('[data-action="retry"]')?.addEventListener('click', renderCurrent);
}

export async function renderCurrent(){
  const view = document.getElementById('view');
  const ticket = ++generation;
  const found = match(currentPath());
  window.scrollTo(0, 0);
  if (!found){
    prepareShell('shell', {});
    view.innerHTML = notFound();
    focusView(view);
    return;
  }
  const {route, params} = found;
  prepareShell(route.area, params);
  view.innerHTML = skeleton();
  try {
    const screen = await route.load();
    if (ticket !== generation) return;
    if (!screen || typeof screen.render !== 'function') throw new Error('экран без render');
    const ctx = Object.freeze({api, go, safe, theme, params:Object.freeze(params), texts:SHELL});
    await screen.render(view, ctx);
  } catch (err){
    if (ticket !== generation) return;
    showError(view, err);
  }
  if (ticket === generation) focusView(view);
}

export function start(){
  window.addEventListener('hashchange', renderCurrent);
  renderCurrent();
}
