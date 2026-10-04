import { title } from './domain.js';
import { render } from './shell.js';
import { hooks, state, ui } from './state.js';

export const $ = s => document.querySelector(s);
export const $$ = s => [...document.querySelectorAll(s)];
export const safe = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const rub = n => Number(n).toLocaleString('ru-RU') + ' ₽';
export const plural = (n, f) => { const a = Math.abs(n) % 100, b = a % 10; return a > 10 && a < 20 ? f[2] : b > 1 && b < 5 ? f[1] : b === 1 ? f[0] : f[2]; };
/* Первая буква в строчную, если слово не аббревиатура (КТ, УЗИ, МРТ остаются как есть) */
export const uc = s => s ? s[0].toUpperCase() + s.slice(1) : s;
export const lc = s => (s && s.length > 1 && s[1] === s[1].toLowerCase() && s[1] !== s[1].toUpperCase()) ? s[0].toLowerCase() + s.slice(1) : s;
export const badge = (text, tone = '') => `<span class="badge ${tone}">${safe(text)}</span>`;
export const btn = (label, action, kind = '', data = {}) => `<button class="btn ${kind}" data-action="${action}"${Object.entries(data).map(([k, v]) => ` data-${k}="${safe(v)}"`).join('')}>${label}</button>`;
export const navBtn = (label, page, kind = '') => `<button class="btn ${kind}" data-nav="${page}">${label}</button>`;

export function toast(msg){
  $('#toast').innerHTML = `<div class="toast" role="status">${safe(msg)}</div>`;
  clearTimeout(ui.toastTimer);
  ui.toastTimer = setTimeout(() => { $('#toast').innerHTML = ''; }, 3800);
}
export function openModal(html, wide){ ui.modal = {html, wide}; renderModal(); }
export function closeModal(){ ui.modal = null; renderModal(); }
export function renderModal(){
  $('#overlay').innerHTML = ui.modal ? `<div class="modalshade"><div class="modal ${ui.modal.wide ? 'wide' : ''}" role="dialog" aria-modal="true">${ui.modal.html}</div></div>` : '';
}
export const modalHead = (eyebrow, title) => `<div class="modalhead"><div>${eyebrow ? `<div class="eyebrow">${eyebrow}</div>` : ''}<h2>${title}</h2></div><button class="xbtn" data-action="close" aria-label="Закрыть">×</button></div>`;
export function go(page){ state.page = page; ui.mobileOpen = false; ui.modal = null; render(); window.scrollTo(0, 0); hooks.navigate(); }

/* ---------- Состояния, которых в прототипе не было: загрузка, ошибка, сервис недоступен ---------- */
/* Загрузка: карточки-заглушки на месте содержимого */
export const loadingCards = (n = 3) => `<div class="grid three" aria-busy="true" aria-label="Загружаем">${Array.from({length:n}, () => '<div class="card skeleton"><span></span><span></span><span></span></div>').join('')}</div>`;
/* Загрузка внутри строки: короткая заглушка вместо значения */
export const loadingLine = () => '<span class="skeletonline" aria-label="Загружаем"></span>';
/* Ошибка: что случилось и кнопка «Повторить» */
export const errorNote = (message, action, data = {}) => `<div class="note red errornote" role="alert"><p>${safe(message)}</p>${btn('Повторить', action, 'secondary small', data)}</div>`;
/* Сервис недоступен: полоса под шапкой */
export const serviceBanner = text => `<div class="servicebanner" role="status">${safe(text)}</div>`;
