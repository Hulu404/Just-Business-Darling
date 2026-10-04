/* Обёртка над fetch для шлюза: роль окна в X-MM-Role, JSON, ошибки шлюза, новая сессия при 401 */

export class ApiError extends Error {
  constructor(status, code, message){ super(message); this.status = status; this.code = code; }
}

async function send(method, path, role, body){
  const headers = {'X-MM-Role': role};
  if (method !== 'GET') headers['Content-Type'] = 'application/json';
  let response;
  try {
    response = await fetch(path, {method, headers, body:body === undefined ? undefined : JSON.stringify(body),
                                  credentials:'same-origin', cache:'no-store'});
  } catch (err){
    throw new ApiError(0, 'gateway_unavailable', 'Шлюз не отвечает. Проверьте, что стенд запущен: python start.py');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok){
    const error = data.error || {};
    throw new ApiError(response.status, error.code || 'error', error.message || 'Шлюз ответил ошибкой. Попробуйте ещё раз.');
  }
  return data;
}

/* Поля новой сессии по ролям: окно партнёра открывает сессию своей клиники (main.js задаёт clinic_id) */
export const sessionExtras = {};
export const createSession = (role, extra = sessionExtras[role] || {}) => send('POST', '/api/session', role, {role, ...extra});

/* Запрос от имени роли. Если сессии роли нет или она истекла, создаёт её и повторяет запрос один раз */
export async function api(method, path, {role, body} = {}){
  try {
    return await send(method, path, role, body);
  } catch (err){
    if (err.status !== 401 || (method === 'POST' && path === '/api/session')) throw err;
    await createSession(role);
    return send(method, path, role, body);
  }
}

export const getHealth = role => send('GET', '/api/health', role);

/* Не-JSON запросы: архив исследования в теле (application/zip) и срез PNG в ответе.
   Тег <img> не отправит X-MM-Role, поэтому картинка приходит через fetch и показывается blob:-адресом */
async function sendRaw(method, path, role, file){
  const headers = {'X-MM-Role': role};
  if (file) headers['Content-Type'] = 'application/zip';
  let response;
  try {
    response = await fetch(path, {method, headers, body:file || undefined, credentials:'same-origin', cache:'no-store'});
  } catch (err){
    throw new ApiError(0, 'gateway_unavailable', 'Шлюз не отвечает. Проверьте, что стенд запущен: python start.py');
  }
  if (!response.ok){
    const error = (await response.json().catch(() => ({}))).error || {};
    throw new ApiError(response.status, error.code || 'error', error.message || 'Шлюз ответил ошибкой. Попробуйте ещё раз.');
  }
  return response;
}
async function withSession(role, run){
  try { return await run(); }
  catch (err){ if (err.status !== 401) throw err; await createSession(role); return run(); }
}
export const uploadArchive = (path, role, file) => withSession(role, () => sendRaw('POST', path, role, file)).then(r => r.json());
export const imageUrl = (path, role) => withSession(role, () => sendRaw('GET', path, role)).then(r => r.blob()).then(b => URL.createObjectURL(b));
