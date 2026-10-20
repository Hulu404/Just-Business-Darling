/* Общие куски разметки пилота: экранирование, загрузка, ошибка, «такой страницы нет», подпись «демо».
   Любое значение с сервера или из мока попадает в разметку только через safe(). Тексты — texts.js. */
import { SHELL } from './texts.js';

export const safe = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));

/* Загрузка: карточки-заглушки и скрытый текст для чтения с экрана. Класс .card.skeleton ждёт wait_ready в web_check.py */
export const skeleton = (count = 2) => `<div class="stack" aria-busy="true"><p class="sr-only" role="status" aria-live="polite">${safe(SHELL.loading)}</p>${
  Array.from({length:count}, () => '<div class="card skeleton" aria-hidden="true"><span></span><span></span><span></span></div>').join('')}</div>`;

/* Ошибка сервиса: что случилось, что делать, кнопка перезагрузить экран (data-action="retry") */
export const errorState = () => `<section class="card state" role="alert"><h1>${safe(SHELL.error.title)}</h1><p>${safe(SHELL.error.body)}</p>`
  + `<button type="button" class="btn block" data-action="retry">${safe(SHELL.error.action)}</button></section>`;

/* Нет такого адреса */
export const notFound = () => `<section class="card state"><h1>${safe(SHELL.not_found.title)}</h1><p>${safe(SHELL.not_found.body)}</p></section>`;

/* Заметка: нейтральный фон, без красного. role: status — заметка, alert — ошибка отправки */
export const note = (text, {role = 'status', id = ''} = {}) => `<p class="note" role="${safe(role)}"${id ? ` id="${safe(id)}"` : ''}>${safe(text)}</p>`;

/* Подпись «демо» для того, что на стенде имитируется */
export const demoTag = () => `<span class="demo-tag">${safe(SHELL.demo_badge)}</span>`;
