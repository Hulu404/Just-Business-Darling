/* Мок-ответы API пилота (FE1). Данные пациента — mocks-patient.js (FE2, только данные). Только синтетика:
   ни реальных телефонов, ни ФИО, ни секретов. */
import { PATIENT } from './mocks-patient.js';

export { PATIENT };

/* Мок-вход сотрудников: логин → роль и имя. Пароль мок не проверяет, только что он не пустой; ни пароль,
   ни токены сотрудника в браузере не хранятся и в заголовки не попадают. Настоящий вход — сессия шлюза в FE5/FE6. */
export const STAFF = Object.freeze({
  'demo-doctor':Object.freeze({role:'doctor', display_name:'Демо-врач'}),
  'demo-manager':Object.freeze({role:'manager', display_name:'Демо-руководитель'})
});

/* ---------- Мок-ответы: { data } или { error: { status, code, message } } ---------- */

const consented = new Set();

const ok = data => ({data});
const fail = (status, code, message) => ({error:{status, code, message}});
const NOT_FOUND = fail(404, 'not_found', 'Такого адреса в API нет.');
const LINK_NOT_FOUND = fail(404, 'link_not_found', 'Ссылка не найдена. Откройте ссылку из сообщения клиники ещё раз.');
const NOT_ACTIVE = fail(409, 'not_active', 'Ссылка больше не действует. Позвоните в клинику.');
const BAD_INPUT = fail(422, 'invalid_input', 'Запрос не подошёл. Обновите страницу и попробуйте ещё раз.');
const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const hasOnly = (body, keys) => Object.keys(body).every(key => keys.includes(key));
const patientEntry = token => (token && Object.hasOwn(PATIENT, token) ? PATIENT[token] : null);
const needsConsent = (token, entry) => entry.consent_required !== false && !consented.has(token);

function patientSession(token){
  const entry = patientEntry(token);
  if (!entry) return LINK_NOT_FOUND;
  return ok({...entry, consent_required:needsConsent(token, entry)});
}

function patientConsent(token){
  const entry = patientEntry(token);
  if (!entry) return LINK_NOT_FOUND;
  if (entry.state !== 'active') return NOT_ACTIVE;
  consented.add(token);
  return ok({ok:true});
}

function patientChoice(token, body){
  const entry = patientEntry(token);
  if (!entry) return LINK_NOT_FOUND;
  if (entry.state !== 'active') return NOT_ACTIVE;
  if (needsConsent(token, entry)) return fail(409, 'consent_required', 'Сначала подтвердите согласие.');
  if (!isObject(body) || !hasOnly(body, ['branch_code', 'goal_id'])) return BAD_INPUT;
  const branch = body.branch_code ?? null;
  const goalKnown = (entry.goals || []).some(goal => goal.id === body.goal_id);
  const branchKnown = branch === null || (!entry.doctor_step && (entry.branches || []).some(item => item.code === branch));
  if (!goalKnown || !branchKnown) return fail(422, 'invalid_input', 'Такого варианта нет. Выберите из списка.');
  return ok({ok:true});
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
  if (route === 'GET /patient/session') return patientSession(token);
  if (route === 'POST /patient/consent') return patientConsent(token);
  if (route === 'POST /patient/choice') return patientChoice(token, body);
  if (route === 'POST /staff/login') return staffLogin(body);
  return NOT_FOUND;
}
