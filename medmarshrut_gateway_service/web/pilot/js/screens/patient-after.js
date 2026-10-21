/* P8: шаг после визита — #/p/<token>/after (FE4, черновик B8, только мок, подписан «демо»).
   Каркас и тексты — docs/rescan-pilot/design/p4-p8.md, «P8». Данные — session.after_visit. */
import { page, feedback, showFeedback } from './patient-common.js';
import { patientPath, formatText } from './patient-state.js';
import { formatCareDate, loadCare, doctorAuthor } from './patient-retest.js';
import { handlePatientError } from './patient-errors.js';

const STEP_CODES = ['observe', 'retest', 'specialist', 'none'];

function renderEmpty(view, ctx, token, texts, demo) {
  page(view, ctx, texts['p8.empty.title'], `<div class="card patient-card">
    <p>${ctx.safe(texts['p8.empty.body'])}</p>
    <button type="button" class="btn" data-care-step>${ctx.safe(texts['p8.empty.action'])}</button></div>`, '', demo);
  view.querySelector('[data-care-step]').addEventListener('click', () => ctx.go(patientPath(token, 'step')));
}

function actionsMarkup(ctx, texts, booked) {
  if (booked) return `<p class="note" role="status">${ctx.safe(texts['p8.booked.already'])}</p>`;
  return `${feedback()}
    <button type="button" class="btn" data-care-book>${ctx.safe(texts['p8.action'])}</button>
    <button type="button" class="btn text" data-care-booked>${ctx.safe(texts['p8.booked.action'])}</button>`;
}

/* Сеть и сбой сервиса при отправке — заметка у кнопок, экран не меняем. Ошибки контракта — общий обработчик */
function showSaveError(err, view, ctx, data) {
  const status = err?.status;
  const formLevel = status === 0 || (status >= 500 && err?.code !== 'not_configured');
  const errorCtx = { ...ctx, clinic: data.session.clinic, retry: () => render(view, ctx) };
  if (formLevel || !handlePatientError(err, view, errorCtx, data.texts)) showFeedback(view, ctx, data.texts['p8.booked.error']);
}

function wireBooked(view, ctx, data) {
  const { token, texts, current } = data;
  const actions = view.querySelector('[data-care-actions]');
  const book = view.querySelector('[data-care-book]');
  const booked = view.querySelector('[data-care-booked]');
  const active = () => current() && booked.isConnected !== false;
  let busy = false;
  const setBusy = value => {
    busy = value;
    book.disabled = booked.disabled = value;
    booked.textContent = texts[value ? 'p8.booked.pending' : 'p8.booked.action'];
    if (value) booked.setAttribute('aria-busy', 'true');
    else booked.removeAttribute('aria-busy');
  };
  book.addEventListener('click', () => { if (!busy) ctx.go(patientPath(token, 'goal')); });
  booked.addEventListener('click', async () => {
    if (busy) return;
    setBusy(true);
    try {
      const response = await ctx.api('POST', '/patient/after-visit/booked');
      if (!active()) return;
      if (response?.ok !== true) throw new Error('after_visit_not_saved');
      actions.innerHTML = `<p class="note" role="status" tabindex="-1" data-care-confirmation>${ctx.safe(texts['p8.booked.done'])}</p>`;
      view.querySelector('[data-care-confirmation]').focus({ preventScroll: true });
      return;
    } catch (err) {
      if (!active()) return;
      showSaveError(err, view, ctx, data);
    }
    if (active()) setBusy(false);
  });
}

export async function render(view, ctx) {
  const data = await loadCare(view, ctx, render);
  if (!data) return;
  const { session, token, texts } = data;
  const after = session.after_visit;
  const demo = `<p class="note">${ctx.safe(texts['p8.demo'])}</p>`;
  const step = after?.step;
  if (!step || !STEP_CODES.includes(step.code)) {
    renderEmpty(view, ctx, token, texts, demo);
    return;
  }
  const date = formatCareDate(step.due_date);
  const booked = after.booked === true;
  page(view, ctx, texts[`p8.${step.code}.title`], `
    ${date ? `<p>${ctx.safe(formatText(texts['p8.due'], { date }))}</p>` : ''}
    <div class="card patient-card patient-care-memo"><h2>${ctx.safe(texts['p8.memo.title'])}</h2>
      <ul>${[1, 2].map(n => `<li>${ctx.safe(texts[`p8.memo.${n}`])}</li>`).join('')}</ul></div>
    <div class="patient-care-actions" data-care-actions>${actionsMarkup(ctx, texts, booked)}</div>`,
  texts[`p8.${step.code}.body`], demo + doctorAuthor(ctx, texts, step.doctor_name));
  if (!booked) wireBooked(view, ctx, data);
}
