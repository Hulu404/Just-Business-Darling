/* P4: выбор врача — #/p/<token>/doctors (старый адрес /next тоже сюда). Каркас и тексты — p4-p8.md.
   Здесь же общие куски P4–P6: цена, дата, фото или инициалы врача, загрузка с обработкой ошибок пациента. */
import { loadPatient, page, contact, backButton } from './patient-common.js';
import { patientPath, formatText } from './patient-state.js';

/* Ошибки пациента — общий обработчик FE4; P5 и P6 берут его отсюда */
import { handlePatientError } from './patient-errors.js';
export { handlePatientError };

/* ---------- Общее для P4–P6 ---------- */

const NBSP = String.fromCharCode(0x00A0);
const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

/* Цена: 250000 → «2 500 ₽», 150050 → «1 500,50 ₽». Не RUB, не число, 0 и меньше — null (строку не показываем) */
export function formatPrice(kopecks, currency) {
  if (currency !== 'RUB' || !Number.isInteger(kopecks) || kopecks <= 0) return null;
  const rubles = String(Math.floor(kopecks / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
  const rest = kopecks % 100;
  return `${rubles}${rest ? `,${String(rest).padStart(2, '0')}` : ''}${NBSP}₽`;
}

/* Наименьшая цена среди форматов, которые можно показать; нет таких — null */
export function minPrice(formats) {
  const prices = (formats || []).filter(item => formatPrice(item.price_kopecks, item.currency) !== null);
  if (!prices.length) return null;
  const lowest = prices.reduce((min, item) => (item.price_kopecks < min.price_kopecks ? item : min));
  return formatPrice(lowest.price_kopecks, lowest.currency);
}

/* Дата «17 ноября», другого года — «17 января 2027». created_at — в поясе браузера */
export function formatDate(value, now = new Date()) {
  const date = new Date(value);
  if (typeof value !== 'string' || Number.isNaN(date.getTime())) return null;
  const year = date.getFullYear() === now.getFullYear() ? '' : ` ${date.getFullYear()}`;
  return `${date.getDate()}${NBSP}${MONTHS[date.getMonth()]}${year}`;
}

/* Адрес оплаты — только схема https, без пробелов и кавычек */
export function isHttps(value) {
  if (typeof value !== 'string' || !/^https:\/\/[^\s"'<>\\]+$/i.test(value)) return false;
  try { return new URL(value).protocol === 'https:'; } catch { return false; }
}

/* Инициалы: первые буквы первых двух слов, заглавными */
export function initials(name) {
  return String(name ?? '').trim().split(/\s+/).filter(Boolean).slice(0, 2).map(word => word[0].toUpperCase()).join('');
}

/* Фото врача — только с нашего источника (/assets/…), иначе инициалы. Имя написано рядом, поэтому alt="" */
const samePhoto = url => typeof url === 'string' && /^\/assets\/[^\s"'<>\\?#]+$/.test(url) && !url.includes('..');
export function avatar(ctx, doctor) {
  const letters = `<span class="booking-avatar" aria-hidden="true">${ctx.safe(initials(doctor.name))}</span>`;
  if (!samePhoto(doctor.photo_url)) return letters;
  return `<span class="booking-avatar" aria-hidden="true"><img src="${ctx.safe(doctor.photo_url)}" alt=""
    data-initials="${ctx.safe(initials(doctor.name))}"></span>`;
}

/* Фото не загрузилось — инициалы на его месте */
export function wireAvatars(view) {
  for (const image of view.querySelectorAll?.('.booking-avatar img') ?? []) {
    image.addEventListener('error', () => { image.parentElement.textContent = image.dataset.initials; });
  }
}

/* Незавершённая заявка: P1, P4 и P5 ведут на P6. После booked и cancelled можно оставить новую */
export const hasOpenRequest = session => ['accepted', 'in_progress'].includes(session.request?.status);

/* Загрузка сессии и данных экрана; ошибки пациента — через handlePatientError, остальное — роутеру.
   load(data) → данные экрана; экран рисует draw(data, loaded). Пока шёл запрос, адрес сменился — ничего не рисуем */
export async function loadBooking(view, ctx, load, draw) {
  const address = globalThis.location?.hash;
  let data = null;
  const retry = () => loadBooking(view, ctx, load, draw);
  try {
    data = await loadPatient(view, ctx);
    if (!data) return;
    const loaded = await load(data);
    if (loaded === null || !data.current()) return;
    draw(data, loaded);
  } catch (err) {
    if (globalThis.location?.hash !== address || (data && !data.current())) return;
    const errorCtx = { ...ctx, clinic: data?.session.clinic, session: data?.session, retry };
    if (!handlePatientError(err, view, errorCtx, data?.texts ?? {})) throw err;
  }
}

/* ---------- P4 ---------- */

const TAGS = ['ordering', 'visited'];

function doctorCard(ctx, texts, token, doctor, price) {
  const tag = TAGS.includes(doctor.tag) && texts[`p4.tag.${doctor.tag}`]
    ? `<span class="booking-tag">${ctx.safe(texts[`p4.tag.${doctor.tag}`])}</span>` : '';
  const href = `${patientPath(token, 'request')}?doctor=${encodeURIComponent(doctor.id)}`;
  return `<li><a class="booking-doctor booking-doctor-link" href="${ctx.safe(href)}">
    ${avatar(ctx, doctor)}<span class="booking-doctor-main">
      <span class="booking-doctor-name">${ctx.safe(doctor.name)}</span>
      <span class="booking-doctor-specialty">${ctx.safe(doctor.specialty)}</span>
      ${tag}${price ? `<span class="booking-price">${ctx.safe(formatText(texts['p4.price_from'], { price }))}</span>` : ''}
    </span><span class="booking-doctor-action" aria-hidden="true">${ctx.safe(texts['p4.card.action'])} ›</span></a></li>`;
}

function drawEmpty(view, ctx, { session, token, texts }) {
  page(view, ctx, texts['p4.empty.title'], `<div class="card patient-card"><p>${ctx.safe(texts['p4.empty.body'])}</p>
    ${contact(ctx, texts, session.clinic)}
    <a href="${ctx.safe(patientPath(token, 'goal'))}">${ctx.safe(texts['p4.empty.change_goal'])}</a></div>`,
  '', backButton(ctx, texts, 'p4.back'));
}

function draw(view, ctx, data, { doctors, formats }) {
  const { token, texts } = data;
  if (!doctors.length) drawEmpty(view, ctx, data);
  else {
    const price = minPrice(formats);
    page(view, ctx, texts['p4.title'], `<ul class="booking-list">
      ${doctors.map(doctor => doctorCard(ctx, texts, token, doctor, price)).join('')}</ul>`,
    texts['p4.body'], backButton(ctx, texts, 'p4.back'));
    wireAvatars(view);
  }
  view.querySelector('[data-patient-back]').addEventListener('click', () => ctx.go(patientPath(token, 'goal')));
}

export async function render(view, ctx) {
  await loadBooking(view, ctx, async ({ session, token }) => {
    if (hasOpenRequest(session)) { ctx.go(patientPath(token, 'status')); return null; }
    const [list, catalog] = await Promise.all([ctx.api('GET', '/patient/doctors'), ctx.api('GET', '/patient/formats')]);
    return { doctors: Array.isArray(list.doctors) ? list.doctors : [], formats: Array.isArray(catalog.formats) ? catalog.formats : [] };
  }, (data, loaded) => draw(view, ctx, data, loaded));
}
