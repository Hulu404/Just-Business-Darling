/* Мок-ответы API пилота: повторяют контракт B6 (prompts/19, «Контракты») — пути без /v1, коды и тела ошибок.
   Данные: mocks-patient.js (P1–P6), mocks-care.js (P7, P8, ошибки; FE4). Здесь только логика ответов.
   Состояние (согласие, выбор, заявка, «я уже записан») живёт в памяти вкладки и сбрасывается перезагрузкой.
   Только синтетика: ни реальных телефонов, ни ФИО, ни секретов. */
import { PATIENT, BOOKING, BOOKING_TEXTS, BOOKING_CATALOG } from './mocks-patient.js';
import { CARE, CARE_TEXTS } from './mocks-care.js';

export { PATIENT };

/* Мок-вход сотрудников: логин → роль и имя. Пароль мок не проверяет, только что он не пустой; ни пароль,
   ни токены сотрудника в браузере не хранятся и в заголовки не попадают. Настоящий вход — сессия шлюза в FE5/FE6. */
export const STAFF = Object.freeze({
  'demo-doctor':Object.freeze({role:'doctor', display_name:'Демо-врач'}),
  'demo-manager':Object.freeze({role:'manager', display_name:'Демо-руководитель'})
});

/* Все мок-сессии по токену. FE4 может переопределить токен FE2/FE3 своим (например, demo-step-retest) */
const SESSIONS = Object.freeze({...PATIENT, ...BOOKING, ...CARE});
/* Токены сбоев: ответ одинаковый на любом пути пациента. demo-error-network — в api.js (сеть, status 0) */
const FAULT_TOKENS = Object.freeze({
  'demo-not-configured':{status:503, code:'not_configured', message:'Страница клиники ещё не настроена. Позвоните в клинику.'},
  'demo-error-500':{status:500, code:'server_error', message:'Сервис временно не отвечает. Попробуйте ещё раз через минуту.'}
});
const FALLBACK_TEXTS = PATIENT['demo-active'].texts;

/* ---------- Мок-ответы: { data } или { error: { status, code, message } } ---------- */

const consented = new Set();
const choices = new Map();
const requests = new Map();
const afterBooked = new Set();
let requestSeq = 0;

const ok = data => ({data});
const fail = (status, code, message) => ({error:{status, code, message}});
const NOT_FOUND = fail(404, 'not_found', 'Такого адреса в API нет.');
const LINK_NOT_FOUND = fail(404, 'link_not_found', 'Ссылка не найдена. Откройте ссылку из сообщения клиники ещё раз.');
const NOT_ACTIVE = fail(409, 'not_active', 'Ссылка больше не действует. Позвоните в клинику.');
const CONSENT_REQUIRED = fail(409, 'consent_required', 'Сначала подтвердите согласие.');
const CHOICE_REQUIRED = fail(409, 'choice_required', 'Сначала выберите цель визита.');
const REQUEST_EXISTS = fail(409, 'request_exists', 'Заявка уже отправлена. Дождитесь звонка администратора.');
const BAD_INPUT = fail(422, 'invalid_input', 'Запрос не подошёл. Обновите страницу и попробуйте ещё раз.');
const NOT_IN_LIST = fail(422, 'invalid_input', 'Такого варианта нет. Выберите из списка.');
const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const hasOnly = (body, keys) => Object.keys(body).every(key => keys.includes(key));
const isHttps = value => typeof value === 'string' && /^https:\/\/[^\s/\\]+/i.test(value);
const patientEntry = token => (token && Object.hasOwn(SESSIONS, token) ? SESSIONS[token] : null);
const needsConsent = (token, entry) => entry.consent_required !== false && !consented.has(token);
const UNFINISHED = new Set(['accepted', 'in_progress']);

const textsOf = entry => ({...BOOKING_TEXTS, ...CARE_TEXTS, ...(entry.texts || FALLBACK_TEXTS)});
const choiceOf = (token, entry) => (choices.has(token) ? choices.get(token) : entry.choice ?? null);
const requestOf = (token, entry) => (requests.has(token) ? requests.get(token) : entry.request ?? null);
const catalog = (entry, key) => entry[key] ?? BOOKING_CATALOG[key];

function afterVisitOf(token, entry){
  const after = entry.after_visit ?? null;
  return after && afterBooked.has(token) ? {...after, booked:true} : after;
}

function patientSession(token, entry){
  const texts = textsOf(entry);
  if (entry.state !== 'active') return ok({state:entry.state, clinic:entry.clinic, texts});
  return ok({
    state:entry.state, clinic:entry.clinic, consent_required:needsConsent(token, entry),
    doctor_step:entry.doctor_step ?? null, branches:entry.branches, goals:entry.goals,
    choice:choiceOf(token, entry), request:requestOf(token, entry),
    after_visit:afterVisitOf(token, entry), texts
  });
}

function patientConsent(token){
  consented.add(token);
  return ok({ok:true});
}

function patientChoice(token, entry, body){
  if (!isObject(body) || !hasOnly(body, ['branch_code', 'goal_id'])) return BAD_INPUT;
  const branch = body.branch_code ?? null;
  const goalKnown = (entry.goals || []).some(goal => goal.id === body.goal_id);
  const branchKnown = entry.doctor_step
    ? branch === null
    : (entry.branches || []).some(item => item.code === branch);
  if (!goalKnown || !branchKnown) return NOT_IN_LIST;
  choices.set(token, {branch_code:branch, goal_id:body.goal_id});
  return ok({ok:true});
}

function patientDoctors(entry){
  return ok({doctors:catalog(entry, 'doctors').map(({id, name, specialty, photo_url, tag}) => ({id, name, specialty, photo_url, tag}))});
}

function patientFormats(entry){
  return ok({
    formats:catalog(entry, 'formats').map(({id, title, price_kopecks, currency, payment_url}) =>
      ({id, title, price_kopecks, currency, has_payment:isHttps(payment_url)})),
    windows:catalog(entry, 'windows').map(({code, title}) => ({code, title}))
  });
}

function patientRequest(token, entry, body){
  const current = requestOf(token, entry);
  if (current && UNFINISHED.has(current.status)) return REQUEST_EXISTS;
  if (!isObject(body) || !hasOnly(body, ['doctor_id', 'format_id', 'window_code'])) return BAD_INPUT;
  const doctor = catalog(entry, 'doctors').find(item => item.id === body.doctor_id);
  const format = catalog(entry, 'formats').find(item => item.id === body.format_id);
  const slot = catalog(entry, 'windows').find(item => item.code === body.window_code);
  if (!doctor || !format || !slot) return NOT_IN_LIST;
  requestSeq += 1;
  const request = {
    id:`req-mock-${requestSeq}`, status:'accepted', doctor_name:doctor.name, format_title:format.title,
    window_title:slot.title, created_at:new Date().toISOString()
  };
  requests.set(token, request);
  return ok({request_id:request.id, status:request.status, payment_url:isHttps(format.payment_url) ? format.payment_url : null});
}

/* P8, черновик B8: только мок, бэкенд этот путь сегодня не делает */
function afterVisitBooked(token, entry){
  if (!entry.after_visit) return NOT_IN_LIST;
  afterBooked.add(token);
  return ok({ok:true});
}

/* Пути пациента: что нужно до ответа. session — ничего; consent — активная ссылка; остальное — и согласие */
const PATIENT_ROUTES = Object.freeze({
  'GET /patient/session':{run:(token, entry) => patientSession(token, entry), active:false},
  'POST /patient/consent':{run:token => patientConsent(token), consent:false},
  'POST /patient/choice':{run:(token, entry, body) => patientChoice(token, entry, body)},
  'GET /patient/doctors':{run:(token, entry) => patientDoctors(entry), choice:true},
  'GET /patient/formats':{run:(token, entry) => patientFormats(entry), choice:true},
  'POST /patient/requests':{run:(token, entry, body) => patientRequest(token, entry, body), choice:true},
  'POST /patient/after-visit/booked':{run:(token, entry) => afterVisitBooked(token, entry)}
});

function patientRoute(spec, token, body){
  if (token && Object.hasOwn(FAULT_TOKENS, token)){
    const {status, code, message} = FAULT_TOKENS[token];
    return fail(status, code, message);
  }
  const entry = patientEntry(token);
  if (!entry) return LINK_NOT_FOUND;
  if (spec.active !== false && entry.state !== 'active') return NOT_ACTIVE;
  if (spec.active !== false && spec.consent !== false && needsConsent(token, entry)) return CONSENT_REQUIRED;
  if (spec.choice && !choiceOf(token, entry)) return CHOICE_REQUIRED;
  return spec.run(token, entry, body);
}

function staffLogin(body){
  if (!isObject(body) || !hasOnly(body, ['login', 'password'])) return BAD_INPUT;
  const login = typeof body.login === 'string' ? body.login.trim() : '';
  const password = typeof body.password === 'string' ? body.password : '';
  if (!login || !password) return fail(422, 'invalid_input', 'Введите логин и пароль.');
  const user = Object.hasOwn(STAFF, login) ? STAFF[login] : null;
  if (!user) return fail(401, 'invalid_credentials', 'Логин или пароль не подошли. Проверьте и попробуйте ещё раз.');
  return ok({role:user.role, display_name:user.display_name});
}

export function respond(method, path, body, {token} = {}){
  const route = `${method} ${path}`;
  if (Object.hasOwn(PATIENT_ROUTES, route)) return patientRoute(PATIENT_ROUTES[route], token, body);
  if (route === 'POST /staff/login') return staffLogin(body);
  return NOT_FOUND;
}
