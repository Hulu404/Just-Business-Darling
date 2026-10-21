/* Ошибки пациента (FE4). Каркас и тексты — docs/rescan-pilot/design/p4-p8.md, «Ошибки пациента».
   handlePatientError(err, view, ctx, texts) → true, если ошибку обработали; false — ошибка не из контракта B6,
   её показывает вызывающий экран или роутер. err — ApiError { status, code }; message сервера не выводим.
   ctx.retry — перерисовать вызывающий экран (иначе повторяем текущий адрес); ctx.clinic или ctx.session.clinic —
   уже известная клиника, чтобы показать звонок. */
import { page, contact, feedback, showFeedback } from './patient-common.js';
import { patientPath } from './patient-state.js';

/* Строки, нужные до ответа сессии, живут в texts.js (SHELL) и берутся оттуда всегда.
   Здесь — запасная копия тех же строк дизайнера на случай, если в SHELL их нет. err.invalid_input приходит
   в texts сессии; запасная строка нужна, если клиника её не задала. */
export const ERROR_TEXTS = Object.freeze({
  'err.link_not_found.title': 'Ссылка не найдена',
  'err.link_not_found.body': 'Возможно, адрес скопировался не целиком или ссылка больше не действует. Откройте ссылку из сообщения ещё раз. Если не помогло, позвоните в клинику — администратор запишет вас к врачу.',
  'err.not_configured.title': 'Страница клиники ещё не настроена',
  'err.not_configured.body': 'Записаться здесь пока не получится. Позвоните в клинику — администратор запишет вас к врачу.',
  'err.network.title': 'Нет связи',
  'err.network.body': 'Проверьте интернет и нажмите «Повторить».',
  'err.network.action': 'Повторить',
  'err.network.pending': 'Проверяем…',
  'err.server.title': 'Сервис временно не отвечает',
  'err.server.body': 'Попробуйте ещё раз через минуту. Если не помогло, позвоните в клинику.',
  'err.server.action': 'Повторить',
  'err.call.no_phone': 'Номер телефона есть на сайте клиники.',
  'err.invalid_input': 'Этот вариант сейчас недоступен. Проверьте выбор и нажмите кнопку ещё раз.'
});

/* 409 без своего текста: переход на экран, который сам объясняет ситуацию. not_active — P1 по свежей сессии */
const TRANSITIONS = Object.freeze({ not_active: '', consent_required: '', choice_required: 'goal', request_exists: 'status' });

function errorKind(status, code) {
  if (status === 404 && code === 'link_not_found') return 'link_not_found';
  if (status === 503 && code === 'not_configured') return 'not_configured';
  if (status === 0 && code === 'network') return 'network';
  if (Number.isInteger(status) && status >= 500 && status <= 599) return 'server';
  return null;
}

/* Тексты: запасные < texts сессии < err.* из SHELL (ctx.texts) */
function errorCopy(ctx, texts) {
  const shell = Object.entries(ctx.texts || {}).filter(([key]) => key.startsWith('err.'));
  return { ...ERROR_TEXTS, ...texts, ...Object.fromEntries(shell) };
}

/* Звонок — только если телефон уже известен из сессии; иначе строка err.call.no_phone */
function callBlock(ctx, copy, clinic) {
  if (clinic?.phone && copy['p1.call.action']) {
    return contact(ctx, { ...copy, 'p1.call.no_phone': copy['err.call.no_phone'] }, clinic);
  }
  return `<div class="patient-help"><p>${ctx.safe(copy['err.call.no_phone'])}</p></div>`;
}

function onRetry(ctx, button, copy, kind) {
  return () => {
    if (button.disabled) return;
    button.disabled = true;
    if (kind === 'network') button.textContent = copy['err.network.pending'];
    if (ctx.retry) return ctx.retry();
    return ctx.go(globalThis.location?.hash || patientPath(ctx.params.token));
  };
}

export function handlePatientError(err, view, ctx, texts = {}) {
  const { status, code } = err || {};
  const copy = errorCopy(ctx, texts);
  if (status === 409) {
    if (!Object.hasOwn(TRANSITIONS, code)) return false;
    ctx.go(patientPath(ctx.params.token, TRANSITIONS[code]));
    return true;
  }
  if (status === 422 && code === 'invalid_input') {
    if (!view.querySelector('.patient-feedback')) view.insertAdjacentHTML('beforeend', feedback());
    showFeedback(view, ctx, copy['err.invalid_input']);
    return true;
  }
  const kind = errorKind(status, code);
  if (!kind) return false;
  const retry = kind === 'network' || kind === 'server';
  const action = retry
    ? `<button class="btn" type="button" data-patient-retry>${ctx.safe(copy[`err.${kind}.action`])}</button>`
    : callBlock(ctx, copy, ctx.clinic || ctx.session?.clinic || null);
  page(view, ctx, copy[`err.${kind}.title`], `<div class="card patient-card">
    <p>${ctx.safe(copy[`err.${kind}.body`])}</p>${action}</div>`);
  if (retry) {
    const button = view.querySelector('[data-patient-retry]');
    button.addEventListener('click', onRetry(ctx, button, copy, kind));
  }
  return true;
}
