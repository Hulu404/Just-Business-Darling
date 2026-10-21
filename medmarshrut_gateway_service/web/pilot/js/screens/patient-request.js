/* P5: формат, удобное время, заявка, переход к оплате — #/p/<token>/request?doctor=<id>. Каркас и тексты — p4-p8.md.
   Свободного ввода нет: только радиокнопки из ответа сервиса. */
import { page, feedback, showFeedback, backButton } from './patient-common.js';
import { patientPath } from './patient-state.js';
import { loadBooking, hasOpenRequest, handlePatientError, avatar, wireAvatars, formatPrice, isHttps } from './patient-doctors.js';

function formatOption(ctx, texts, format, index) {
  const price = formatPrice(format.price_kopecks, format.currency);
  const hint = format.has_payment === true
    ? `<span class="patient-option-hint" id="format-hint-${index}">${ctx.safe(texts['p5.format.prepay'])}</span>` : '';
  return `<label class="card patient-option booking-format">
    <input type="radio" name="format" value="${ctx.safe(format.id)}" required${hint ? ` aria-describedby="format-hint-${index}"` : ''}>
    <span class="booking-format-text"><span class="patient-option-title">${ctx.safe(format.title)}</span>${hint}</span>
    <span class="booking-format-price">${price ? ctx.safe(price) : ''}</span></label>`;
}

function windowOption(ctx, slot) {
  return `<label class="card patient-option">
    <input type="radio" name="window" value="${ctx.safe(slot.code)}" required>
    <span class="patient-option-title">${ctx.safe(slot.title)}</span></label>`;
}

function drawNoDoctor(view, ctx, { token, texts }) {
  page(view, ctx, texts['p5.no_doctor.title'], `<div class="card patient-card"><p>${ctx.safe(texts['p5.no_doctor.body'])}</p>
    <button class="btn" type="button" data-booking-doctors>${ctx.safe(texts['p5.no_doctor.action'])}</button></div>`);
  view.querySelector('[data-booking-doctors]').addEventListener('click', () => ctx.go(patientPath(token, 'doctors')));
}

/* После 201 с адресом оплаты: экран остаётся, пациент вернётся во вкладку и откроет заявку */
export function drawPaid(view, ctx, { token, texts }, url) {
  page(view, ctx, texts['p5.paid.title'], `<div class="card patient-card"><p>${ctx.safe(texts['p5.paid.body'])}</p>
    <a class="btn" href="${ctx.safe(url)}" target="_blank" rel="noopener noreferrer">${ctx.safe(texts['p5.paid.action'])}</a>
    <p class="patient-muted patient-small">${ctx.safe(texts['p5.paid.new_tab'])}</p>
    <a href="${ctx.safe(patientPath(token, 'status'))}">${ctx.safe(texts['p5.paid.later'])}</a>
    <p class="note">${ctx.safe(texts['p5.paid.note'])}</p></div>`);
}

function drawForm(view, ctx, data, { doctor, formats, windows }) {
  const { session, token, texts, current } = data;
  page(view, ctx, texts['p5.title'], `<div class="card booking-doctor booking-doctor-static">
      ${avatar(ctx, doctor)}<span class="booking-doctor-main">
      <span class="patient-eyebrow patient-muted">${ctx.safe(texts['p5.doctor.label'])}</span>
      <span class="booking-doctor-name">${ctx.safe(doctor.name)}</span>
      <span class="booking-doctor-specialty">${ctx.safe(doctor.specialty)}</span></span></div>
    <form class="patient-form" novalidate>
      <fieldset class="patient-options"><legend class="booking-legend">${ctx.safe(texts['p5.format.legend'])}</legend>
      ${formats.map((format, index) => formatOption(ctx, texts, format, index)).join('')}</fieldset>
      <fieldset class="patient-options" aria-describedby="window-hint"><legend class="booking-legend">${ctx.safe(texts['p5.window.legend'])}</legend>
      <p class="patient-muted patient-small" id="window-hint">${ctx.safe(texts['p5.window.hint'])}</p>
      ${windows.map(slot => windowOption(ctx, slot)).join('')}</fieldset>
      <p class="note">${ctx.safe(texts['p5.confirm_note'])}</p>
      ${feedback()}<button class="btn" type="submit" disabled>${ctx.safe(texts['p5.action'])}</button>
      <p class="patient-muted patient-small" data-patient-choose>${ctx.safe(texts['p5.choose'])}</p></form>`,
  '', backButton(ctx, texts, 'p5.back'));
  wireAvatars(view);
  view.querySelector('[data-patient-back]').addEventListener('click', () => ctx.go(patientPath(token, 'doctors')));
  const form = view.querySelector('form');
  const button = form.querySelector('button[type="submit"]');
  const active = () => current() && form.isConnected !== false;
  const picked = { format: null, window: null };
  const ready = () => picked.format !== null && picked.window !== null;
  let busy = false;
  form.addEventListener('change', event => {
    const { name, value } = event.target || {};
    if (busy || !['format', 'window'].includes(name)) return;
    const known = name === 'format' ? formats.some(item => item.id === value) : windows.some(item => item.code === value);
    picked[name] = known ? value : null;
    button.disabled = !ready();
    view.querySelector('[data-patient-choose]').hidden = ready();
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !ready()) return;
    busy = true;
    button.disabled = true;
    button.textContent = texts['p5.pending'];
    form.setAttribute('aria-busy', 'true');
    try {
      const response = await ctx.api('POST', '/patient/requests', { doctor_id: doctor.id, format_id: picked.format, window_code: picked.window });
      if (!active()) return;
      if (isHttps(response.payment_url)) drawPaid(view, ctx, data, response.payment_url);
      else ctx.go(patientPath(token, 'status'));
    } catch (err) {
      if (!active()) return;
      if (err?.status === 422) showFeedback(view, ctx, texts['err.invalid_input'] ?? texts['p5.error']);
      else if (err?.status === 0 || !handlePatientError(err, view, { ...ctx, clinic: session.clinic, session }, texts)) {
        showFeedback(view, ctx, texts['p5.error']);
      }
    } finally {
      if (active() && form.isConnected !== false && view.contains?.(form) !== false) {
        busy = false;
        button.disabled = !ready();
        button.textContent = texts['p5.action'];
        form.removeAttribute('aria-busy');
      }
    }
  });
}

export async function render(view, ctx) {
  const wanted = ctx.query?.doctor ?? null;
  await loadBooking(view, ctx, async ({ session, token }) => {
    if (hasOpenRequest(session)) { ctx.go(patientPath(token, 'status')); return null; }
    const [list, catalog] = await Promise.all([ctx.api('GET', '/patient/doctors'), ctx.api('GET', '/patient/formats')]);
    const doctors = Array.isArray(list.doctors) ? list.doctors : [];
    return {
      doctor: doctors.find(item => item.id === wanted) ?? null,
      formats: Array.isArray(catalog.formats) ? catalog.formats : [],
      windows: Array.isArray(catalog.windows) ? catalog.windows : [],
    };
  }, (data, loaded) => (loaded.doctor ? drawForm(view, ctx, data, loaded) : drawNoDoctor(view, ctx, data)));
}
