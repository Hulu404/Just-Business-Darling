/* P6: заявка и её статус — #/p/<token>/status. Каркас и тексты — p4-p8.md.
   Цвет у всех статусов один: без зелёного «записан», красного «закрыта», таймеров и обещаний срока. */
import { page, contact } from './patient-common.js';
import { patientPath } from './patient-state.js';
import { loadBooking, formatDate } from './patient-doctors.js';

const STATUSES = ['accepted', 'in_progress', 'booked', 'cancelled'];
const PROGRESS = ['accepted', 'in_progress', 'booked'];

function progress(ctx, texts, status) {
  const at = PROGRESS.indexOf(status);
  return `<ol class="booking-progress">${PROGRESS.map((step, index) => {
    const state = index < at ? 'done' : index === at ? 'current' : 'next';
    const label = ctx.safe(texts[`p6.progress.${step}`]);
    return state === 'current'
      ? `<li class="is-current" aria-current="step">${label}<span class="sr-only"> — ${ctx.safe(texts['p6.progress.current'])}</span></li>`
      : `<li class="is-${state}">${label}</li>`;
  }).join('')}</ol>`;
}

function summary(ctx, texts, request) {
  const rows = [
    ['p6.summary.doctor', request.doctor_name],
    ['p6.summary.format', request.format_title],
    ['p6.summary.window', request.window_title],
    ['p6.summary.created', request.created_at ? formatDate(request.created_at) : null],
  ].filter(([, value]) => value !== null && value !== undefined && value !== '');
  if (!rows.length) return '';
  return `<dl class="card booking-summary">${rows.map(([key, value]) =>
    `<div><dt>${ctx.safe(texts[key])}</dt><dd>${ctx.safe(value)}</dd></div>`).join('')}</dl>`;
}

/* После booked и cancelled — текстовая кнопка «Оставить новую заявку» → P3 (решение координатора, задание 19) */
const FINISHED = ['booked', 'cancelled'];

function draw(view, ctx, { session, token, texts }) {
  const request = session.request;
  if (!STATUSES.includes(request.status)) {
    page(view, ctx, ctx.texts.error.title, `<div class="card patient-card"><p>${ctx.safe(ctx.texts.error.body)}</p>${contact(ctx, texts, session.clinic)}</div>`);
    return;
  }
  const steps = request.status === 'cancelled' ? '' : progress(ctx, texts, request.status);
  page(view, ctx, texts[`p6.${request.status}.title`], `${steps}${summary(ctx, texts, request)}
    ${contact(ctx, texts, session.clinic)}${FINISHED.includes(request.status) && texts['p6.new_request']
    ? `<button class="btn text" type="button" data-booking-new>${ctx.safe(texts['p6.new_request'])}</button>` : ''}
    <p class="note">${ctx.safe(texts['p6.revisit'])}</p>`,
  texts[`p6.${request.status}.body`]);
  view.querySelector('[data-booking-new]')?.addEventListener('click', () => ctx.go(patientPath(token, 'goal')));
}

export async function render(view, ctx) {
  await loadBooking(view, ctx, async ({ session, token }) => {
    if (!session.request) { ctx.go(patientPath(token, 'doctors')); return null; }
    return {};
  }, data => draw(view, ctx, data));
}
