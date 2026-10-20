import { beginRender, patientPath, requiresEntry, formatText } from './patient-state.js';
import { skeleton } from '../ui.js';
import { handlePatientError } from './patient-errors.js';

export async function loadPatient(view, ctx, entry = false) {
  const current = beginRender(view);
  view.innerHTML = skeleton();
  const loading = view.firstElementChild;
  let session;
  try {
    session = await ctx.api('GET', '/patient/session');
  } catch (err) {
    /* Ошибки сессии — экраны из каркаса ошибок пациента; что не из контракта, показывает роутер */
    if (!current()) return null;
    if (handlePatientError(err, view, ctx)) return null;
    throw err;
  }
  if (!current() || view.firstElementChild !== loading) return null;
  const token = ctx.params.token;
  const theme = { ...session.clinic.theme, name: session.clinic.name };
  ctx.theme.apply(theme);
  if (!entry && requiresEntry(session)) {
    ctx.go(patientPath(token));
    return null;
  }
  return { session, token, texts: session.texts, current };
}

export function page(view, ctx, title, content, intro = '', before = '') {
  view.innerHTML = `<section class="patient-page" aria-labelledby="patient-title">
    ${before}<header class="patient-heading"><h1 id="patient-title" tabindex="-1">${ctx.safe(title)}</h1>
    ${intro ? `<p class="patient-muted">${ctx.safe(intro)}</p>` : ''}</header>${content}</section>`;
  view.querySelector('h1').focus({ preventScroll: true });
}

/* Номер не переносится посередине: пробелы и дефисы — неразрывные */
const NBSP = String.fromCharCode(0x00A0);
const NB_HYPHEN = String.fromCharCode(0x2011);
const unbreakable = text => text.replace(/ /g, NBSP).replace(/-/g, NB_HYPHEN);

export function contact(ctx, texts, clinic) {
  const phone = String(clinic.phone ?? '');
  const target = phone.replace(/[\s()-]/g, '');
  const number = /^\+[0-9]{7,15}$/.test(target)
    ? `<a class="btn patient-contact" href="${ctx.safe(`tel:${target}`)}">${ctx.safe(formatText(texts['p1.call.action'], { clinic_phone: unbreakable(phone) }))}</a>`
    : `<p>${ctx.safe(texts['p1.call.no_phone'])}</p>`;
  return `<div class="patient-help">${number}</div>`;
}

export function feedback() {
  return `<div class="patient-feedback" role="alert" tabindex="-1"></div>`;
}

export function showFeedback(view, ctx, message) {
  const area = view.querySelector('.patient-feedback');
  area.innerHTML = `<p class="note">${ctx.safe(message)}</p>`;
  area.focus({ preventScroll: true });
}

export function backButton(ctx, texts, key = 'p3.back') {
  return `<button class="btn text" type="button" data-patient-back>${ctx.safe(texts[key])}</button>`;
}
