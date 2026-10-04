'use strict';
// Temporary gateway page. The window's role lives in the address (#role=staff): no localStorage, no sessionStorage.

const ROLE_TITLES = {patient: 'Пациент', staff: 'Сотрудник', doctor: 'Врач', partner: 'Партнёр'};
const SERVICE_TITLES = {image: 'Сервис снимков', path: 'Сервис пути', clinic: 'Сервис клиники'};
const IMAGING_TITLES = {
  'demo-scripted': 'Снимки: демо-сценарий — признаки заданы заранее, снимок не анализируется.',
  'model': 'Снимки: подключена локальная модель.',
  'no-model': 'Снимки: модель не подключена, каждое исследование уходит на ручной разбор.'
};

const $ = id => document.getElementById(id);

function windowRole() {
  const match = /(?:^|[#&])role=(patient|staff|doctor|partner)(?:&|$)/.exec(location.hash);
  return match ? match[1] : null;
}

async function api(method, path, body) {
  const headers = {};
  const role = windowRole();
  if (role) headers['X-MM-Role'] = role;
  if (method !== 'GET') headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {method, headers, body: body ? JSON.stringify(body) : undefined,
                                      credentials: 'same-origin', cache: 'no-store'});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error((data.error && data.error.message) || 'Шлюз не ответил. Проверьте, что стенд запущен.');
    error.status = response.status;
    throw error;
  }
  return data;
}

function setWindowRole(role) {
  // replaceState does not fire hashchange, so restore() does not race with the session request.
  history.replaceState(null, '', location.pathname + (role ? '#role=' + role : ''));
}

function showError(message) {
  $('error').textContent = message || '';
  $('error').hidden = !message;
}

function showSession(session) {
  $('current').hidden = !session;
  $('chooser').hidden = Boolean(session);
  if (!session) return;
  $('current-role').textContent = ROLE_TITLES[session.role] + ' · демо-роль';
  $('current-name').textContent = session.name;
  $('current-extra').textContent = session.role === 'patient' ? 'Псевдоним: ' + session.patient_ref
                                                               : 'Клиника: ' + session.clinic_id;
  document.title = 'МедМаршрут — ' + ROLE_TITLES[session.role];
}

async function choose(role) {
  showError('');
  setWindowRole(role);
  const body = {role};
  if (role === 'patient') body.patient_ref = $('patient-ref').value.trim();
  if (role === 'partner') body.clinic_id = $('partner-clinic').value;
  try {
    showSession(await api('POST', '/api/session', body));
  } catch (error) {
    setWindowRole(null);
    showSession(null);
    showError(error.message);
  }
}

async function logout() {
  showError('');
  try { await api('DELETE', '/api/session'); } catch (error) { /* the session is gone either way */ }
  setWindowRole(null);
  showSession(null);
  document.title = 'МедМаршрут';
}

async function restore() {
  if (!windowRole()) { showSession(null); return; }
  try {
    showSession(await api('GET', '/api/session'));
  } catch (error) {
    showSession(null);
    if (error.status !== 401) showError(error.message);
  }
}

function cell(row, value) {
  const td = document.createElement('td');
  if (value instanceof Node) td.appendChild(value); else td.textContent = value;
  row.appendChild(td);
}

async function refreshHealth() {
  const body = $('services');
  try {
    const health = await api('GET', '/api/health');
    $('imaging-mode').textContent = IMAGING_TITLES[health.imaging_mode] || '';
    body.replaceChildren();
    for (const [name, info] of Object.entries(health.services)) {
      const row = document.createElement('tr');
      const badge = document.createElement('span');
      badge.className = info.status === 'up' ? 'badge' : 'badge red';
      badge.textContent = info.status === 'up' ? 'работает' : 'недоступен';
      cell(row, SERVICE_TITLES[name] || name);
      cell(row, String(info.port));
      cell(row, badge);
      body.appendChild(row);
    }
    const down = Object.values(health.services).some(info => info.status !== 'up');
    $('health-note').textContent = down ? 'Часть сервисов недоступна. Перезапустите стенд: python start.py' : '';
  } catch (error) {
    body.replaceChildren();
    $('health-note').textContent = 'Шлюз недоступен. Проверьте, что стенд запущен: python start.py';
  }
}

document.querySelectorAll('[data-role]').forEach(button => button.addEventListener('click', () => choose(button.dataset.role)));
$('logout').addEventListener('click', logout);
window.addEventListener('hashchange', restore);
restore();
refreshHealth();
setInterval(refreshHealth, 5000);
