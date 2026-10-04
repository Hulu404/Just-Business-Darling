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

export const createSession = (role, extra = {}) => send('POST', '/api/session', role, {role, ...extra});

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
