/* P7: пересдача — #/p/<token>/retest (FE4). Каркас и тексты — docs/rescan-pilot/design/p4-p8.md, «P7».
   Дата и состояние (before, today, overdue) приходят с сервера; экран их не пересчитывает и не считает дни. */
import { loadPatient, page, backButton } from './patient-common.js';
import { patientPath, formatText } from './patient-state.js';
import { handlePatientError } from './patient-errors.js';

const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const RETEST_STATES = ['before', 'today', 'overdue'];

/* «17 ноября», в другом году — «17 января 2027». due_date — дата без времени в поясе клиники:
   разбираем строку, без перевода в пояс браузера. Не дата — null */
export function formatCareDate(value, currentYear = new Date().getFullYear()) {
  const parts = typeof value === 'string' ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(value) : null;
  if (!parts) return null;
  const [year, month, day] = parts.slice(1).map(Number);
  const check = new Date(Date.UTC(year, month - 1, day));
  if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day) return null;
  const text = `${day} ${MONTHS[month - 1]}`;
  return year === currentYear ? text : `${text} ${year}`;
}

/* Сессия пациента с обработкой ошибок: null — экран уже показал ошибку или ушёл на другой адрес */
export async function loadCare(view, ctx, render) {
  const pending = loadPatient(view, ctx);
  const loading = view.firstElementChild;
  try {
    return await pending;
  } catch (err) {
    if (view.isConnected === false || view.firstElementChild !== loading) return null;
    if (!handlePatientError(err, view, { ...ctx, retry: () => render(view, ctx) })) throw err;
    return null;
  }
}

export function doctorAuthor(ctx, texts, name) {
  return name ? `<div class="patient-author"><p class="patient-eyebrow patient-muted">${ctx.safe(texts['p2.doctor.label'])}</p>
    <p class="patient-doctor">${ctx.safe(name)}</p></div>` : '';
}

function renderNone(view, ctx, token, texts) {
  page(view, ctx, texts['p7.none.title'], `<div class="card patient-card">
    <p>${ctx.safe(texts['p7.none.body'])}</p>
    <button type="button" class="btn" data-care-step>${ctx.safe(texts['p7.none.action'])}</button></div>`);
  view.querySelector('[data-care-step]').addEventListener('click', () => ctx.go(patientPath(token, 'step')));
}

export async function render(view, ctx) {
  const data = await loadCare(view, ctx, render);
  if (!data) return;
  const { session, token, texts } = data;
  const step = session.doctor_step;
  const date = formatCareDate(step?.due_date);
  if (step?.code !== 'retest' || !date || !RETEST_STATES.includes(step.retest_state)) {
    renderNone(view, ctx, token, texts);
    return;
  }
  const state = step.retest_state;
  page(view, ctx, formatText(texts[`p7.${state}.title`], { date }), `<div class="card patient-card patient-care-memo">
      <h2>${ctx.safe(texts['p7.memo.title'])}</h2>
      <ul>${[1, 2, 3].map(n => `<li>${ctx.safe(texts[`p7.memo.${n}`])}</li>`).join('')}</ul></div>
    <button class="btn" type="button" data-care-book>${ctx.safe(texts['p7.action'])}</button>`,
  formatText(texts[`p7.${state}.body`], { date }), backButton(ctx, texts, 'p7.back') + doctorAuthor(ctx, texts, step.doctor_name));
  view.querySelector('[data-care-book]').addEventListener('click', () => ctx.go(patientPath(token, 'goal')));
  view.querySelector('[data-patient-back]').addEventListener('click', () => ctx.go(patientPath(token, 'step')));
}
