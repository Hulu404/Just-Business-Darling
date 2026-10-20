/* API пилота rescan: api(method, path, body) → Promise с данными или ApiError { status, code, message }.
   Режим mock включён всегда на этапе FE1–FE2: ответы собирает mocks.js, сеть не трогаем.
   Режим live подключим, когда появится API пациента (B6) и вход сотрудников через сессию шлюза (FE5/FE6).
   Токен пациента экран не передаёт: роутер кладёт его сюда из адреса (#/p/<token>) через useToken(). */
import { respond } from './mocks.js';

export const MODE = 'mock';
const MOCK_DELAY_MS = 180;

export class ApiError extends Error {
  constructor(status, code, message){
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

let patientToken = null;

/* Токен пациента из адреса текущего экрана; null — экран не пациентский */
export function useToken(token){ patientToken = token || null; }

const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const copy = value => (value === undefined ? value : JSON.parse(JSON.stringify(value)));

export async function api(method, path, body){
  const verb = String(method || '').toUpperCase();
  if (MODE !== 'mock') throw new ApiError(503, 'live_disabled', 'Сервис ещё не подключён.');
  await wait(MOCK_DELAY_MS);
  const result = respond(verb, String(path || ''), copy(body), {token:patientToken});
  if (result.error){
    const {status, code, message} = result.error;
    throw new ApiError(status, code, message);
  }
  return copy(result.data);
}
