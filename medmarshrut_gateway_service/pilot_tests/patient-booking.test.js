// FE3: P4–P6 и моки по контракту B6. Run: node --test medmarshrut_gateway_service/pilot_tests/
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { PATIENT, BOOKING, BOOKING_TEXTS, BOOKING_CATALOG } from '../web/pilot/js/mocks-patient.js';
import { respond } from '../web/pilot/js/mocks.js';
import { api, useToken, ApiError } from '../web/pilot/js/api.js';
import { SHELL } from '../web/pilot/js/texts.js';
import { render as entry } from '../web/pilot/js/screens/patient-entry.js';
import { render as doctors, formatPrice, minPrice, formatDate, isHttps, initials, avatar } from '../web/pilot/js/screens/patient-doctors.js';
import { render as request } from '../web/pilot/js/screens/patient-request.js';
import { render as status } from '../web/pilot/js/screens/patient-status.js';

const NBSP = ' ';
const design = readFileSync(new URL('../../docs/rescan-pilot/design/p4-p8.md', import.meta.url), 'utf8');
const designTexts = JSON.parse(design.match(/```json\s*([\s\S]*?)```/)[1]);
const safe = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[char]);

// A small event target for contract tests; actual DOM/layout are checked with Playwright.
class View {
  innerHTML = '';
  nodes = new Map();
  listeners = new Map();
  attributes = new Map();
  disabled = false;
  hidden = false;
  querySelector(selector) {
    if (!this.nodes.has(selector)) this.nodes.set(selector, new View());
    return this.nodes.get(selector);
  }
  querySelectorAll() { return []; }
  addEventListener(type, handler) { this.listeners.set(type, handler); }
  emit(type, target = {}) { return this.listeners.get(type)?.({ preventDefault() {}, target }); }
  setAttribute(name, value) { this.attributes.set(name, value); }
  removeAttribute(name) { this.attributes.delete(name); }
  focus() {}
}

/* Экран на настоящем моке: ctx.api идёт в respond() с токеном, как api.js, но без задержки */
function fixture(token, query = {}) {
  const calls = [], routes = [];
  const view = new View();
  const ctx = {
    params: { token }, query, texts: SHELL, safe,
    theme: { apply() {} },
    go: route => routes.push(route),
    api: async (method, path, body) => {
      calls.push({ method, path, body });
      const result = respond(method, path, structuredClone(body), { token });
      if (result.error) throw new ApiError(result.error.status, result.error.code, result.error.message);
      return structuredClone(result.data);
    },
  };
  return { view, ctx, calls, routes };
}
const choose = (token, goal = 'goal-discuss', branch = null) => respond('POST', '/patient/choice', { branch_code: branch, goal_id: goal }, { token });
const order = html => [...html.matchAll(/booking-doctor-name">([^<]*)</g)].map(found => found[1]);

test('P4–P6 mock copy matches the designer JSON word for word', () => {
  const booking = Object.fromEntries(Object.entries(designTexts).filter(([key]) => /^p[456]\./.test(key)));
  // p6.new_request — решение координатора («Оставить новую заявку»), в p4-p8.md ключа пока нет
  const { 'p6.new_request': newRequest, ...fromDesign } = BOOKING_TEXTS;
  assert.deepEqual(fromDesign, booking);
  assert.equal(newRequest, 'Оставить новую заявку');
  const session = respond('GET', '/patient/session', undefined, { token: 'demo-active' }).data;
  for (const [key, value] of Object.entries(booking)) assert.equal(session.texts[key], value);
});

test('SHELL holds every pre-session error string from the designer', () => {
  const shell = JSON.parse(design.match(/```json\s*([\s\S]*?)```/g)[1].replace(/```json|```/g, ''));
  for (const [key, value] of Object.entries(shell)) assert.equal(SHELL[key], value, key);
});

test('FE3 mock tokens exist and the catalogue has one doctor per tag', () => {
  for (const token of ['demo-no-doctors', 'demo-paid-format', 'demo-request-accepted', 'demo-request-in-progress',
    'demo-request-booked', 'demo-request-cancelled']) assert.ok(Object.hasOwn(BOOKING, token), token);
  assert.deepEqual(BOOKING_CATALOG.doctors.map(doctor => doctor.tag), ['ordering', 'visited', null]);
  assert.equal(Object.keys(PATIENT).length, 10);
});

test('session follows B6: choice and request fields, closed links show only state, clinic and texts', () => {
  const active = respond('GET', '/patient/session', undefined, { token: 'demo-request-booked' }).data;
  assert.equal(active.request.status, 'booked');
  assert.deepEqual(active.choice, { branch_code: null, goal_id: 'goal-discuss' });
  for (const key of ['doctors', 'formats', 'windows']) assert.equal(Object.hasOwn(active, key), false);
  const closed = respond('GET', '/patient/session', undefined, { token: 'demo-expired' }).data;
  assert.deepEqual(Object.keys(closed).sort(), ['clinic', 'state', 'texts']);
});

test('mock errors repeat B6 codes and bodies', () => {
  const error = (method, path, token, body) => respond(method, path, body, { token }).error;
  assert.deepEqual(error('GET', '/patient/doctors', 'no-such-link'), { status: 404, code: 'link_not_found', message: error('GET', '/patient/session', 'no-such-link').message });
  assert.equal(error('GET', '/patient/doctors', 'demo-expired').code, 'not_active');
  assert.equal(error('GET', '/patient/doctors', 'demo-step-followup').code, 'choice_required');
  assert.equal(error('GET', '/patient/formats', 'demo-step-followup').code, 'choice_required');
  assert.equal(error('POST', '/patient/requests', 'demo-request-in-progress', {}).code, 'request_exists');
  assert.equal(error('GET', '/patient/session', 'demo-not-configured').status, 503);
  assert.equal(error('GET', '/patient/session', 'demo-not-configured').code, 'not_configured');
  assert.equal(error('GET', '/patient/session', 'demo-error-500').status, 500);
  assert.equal(error('POST', '/patient/choice', 'demo-step-followup', { branch_code: 'discuss', goal_id: 'goal-discuss' }).code, 'invalid_input');
  assert.equal(error('POST', '/patient/choice', 'demo-active', { goal_id: 'goal-discuss' }).code, 'invalid_input');
});

test('request body is strict: extra fields and values outside the lists are 422', () => {
  choose('demo-step-followup');
  const post = body => respond('POST', '/patient/requests', body, { token: 'demo-step-followup' });
  assert.equal(post({ doctor_id: 'doc-other', format_id: 'fmt-clinic', window_code: 'any', comment: 'x' }).error.code, 'invalid_input');
  assert.equal(post({ doctor_id: 'doc-x', format_id: 'fmt-clinic', window_code: 'any' }).error.code, 'invalid_input');
  assert.equal(post({ doctor_id: 'doc-other', format_id: 'fmt-clinic', window_code: 'night' }).error.code, 'invalid_input');
  const created = post({ doctor_id: 'doc-other', format_id: 'fmt-clinic', window_code: 'any' }).data;
  assert.equal(created.status, 'accepted');
  assert.equal(created.payment_url, null);
  assert.equal(post({ doctor_id: 'doc-other', format_id: 'fmt-clinic', window_code: 'any' }).error.code, 'request_exists');
  assert.equal(respond('GET', '/patient/session', undefined, { token: 'demo-step-followup' }).data.request.status, 'accepted');
});

test('formats hide the payment address and windows come from data', () => {
  choose('demo-paid-format');
  const paid = respond('GET', '/patient/formats', undefined, { token: 'demo-paid-format' }).data;
  assert.deepEqual(paid.formats.map(item => item.has_payment), [false, false, true]);
  assert.ok(paid.formats.every(item => !Object.hasOwn(item, 'payment_url')));
  choose('demo-clinic-b', 'goal-discuss', 'discuss');
  const b = respond('GET', '/patient/formats', undefined, { token: 'demo-clinic-b' }).data;
  assert.deepEqual(b.windows.map(item => item.code), ['weekday_am', 'weekday_pm', 'weekend']);
});

test('network failure is an ApiError with status 0 for demo-error-network', async () => {
  useToken('demo-error-network');
  await assert.rejects(api('GET', '/patient/session'), { status: 0, code: 'network' });
  useToken(null);
});

test('after-visit booked is a mock-only path that needs an after_visit step', () => {
  assert.equal(respond('POST', '/patient/after-visit/booked', undefined, { token: 'demo-active' }).error.code, 'invalid_input');
  assert.equal(respond('POST', '/patient/after-visit/booked', undefined, { token: 'demo-expired' }).error.code, 'not_active');
});

test('price formatting follows the designer rules', () => {
  assert.equal(formatPrice(250000, 'RUB'), `2${NBSP}500${NBSP}₽`);
  assert.equal(formatPrice(90000, 'RUB'), `900${NBSP}₽`);
  assert.equal(formatPrice(150050, 'RUB'), `1${NBSP}500,50${NBSP}₽`);
  assert.equal(formatPrice(0, 'RUB'), null);
  assert.equal(formatPrice(1000, 'USD'), null);
  assert.equal(formatPrice(null, 'RUB'), null);
  assert.equal(minPrice([{ price_kopecks: 0, currency: 'RUB' }, { price_kopecks: 180000, currency: 'RUB' }, { price_kopecks: 5000, currency: 'EUR' }]), `1${NBSP}800${NBSP}₽`);
  assert.equal(minPrice([]), null);
});

test('dates, initials and https checks', () => {
  const now = new Date(2026, 9, 20);
  assert.equal(formatDate('2026-11-17T10:00:00', now), `17${NBSP}ноября`);
  assert.equal(formatDate('2027-01-17T10:00:00', now), `17${NBSP}января 2027`);
  assert.equal(formatDate('not a date', now), null);
  assert.equal(initials('Иванова Анна Петровна'), 'ИА');
  assert.equal(initials('Терапевт'), 'Т');
  assert.equal(isHttps('https://example-clinic.ru/pay'), true);
  for (const url of ['http://example-clinic.ru/pay', 'javascript:alert(1)', '//example-clinic.ru', 'https://a b', null]) assert.equal(isHttps(url), false, String(url));
});

test('doctor photo only from our own /assets/, otherwise initials', () => {
  const ctx = { safe };
  assert.match(avatar(ctx, { name: 'Иванова Анна', photo_url: '/assets/pilot/doc.png' }), /<img src="\/assets\/pilot\/doc\.png" alt=""/);
  for (const photo_url of ['https://cdn.example.ru/a.png', '//cdn.example.ru/a.png', '/assets/../x.png', 'data:image/png;base64,AA', null]) {
    const html = avatar(ctx, { name: 'Иванова Анна', photo_url });
    assert.doesNotMatch(html, /<img/, String(photo_url));
    assert.match(html, />ИА</);
  }
});

test('P4 keeps the response order, shows tags and the lowest price on every card', async () => {
  choose('demo-step-discuss');
  const f = fixture('demo-step-discuss');
  await doctors(f.view, f.ctx);
  assert.deepEqual(order(f.view.innerHTML), BOOKING_CATALOG.doctors.map(doctor => doctor.name));
  assert.equal((f.view.innerHTML.match(/booking-tag/g) || []).length, 2);
  assert.ok(f.view.innerHTML.includes(BOOKING_TEXTS['p4.tag.ordering']));
  assert.ok(f.view.innerHTML.includes(BOOKING_TEXTS['p4.tag.visited']));
  assert.equal((f.view.innerHTML.match(new RegExp(`от 900${NBSP}₽`, 'g')) || []).length, 3);
  assert.match(f.view.innerHTML, /href="#\/p\/demo-step-discuss\/request\?doctor=doc-visited"/);
  assert.doesNotMatch(f.view.innerHTML, /<input|<textarea/);
});

test('P4 follows a reordered response instead of sorting on its own', async () => {
  const f = fixture('demo-step-discuss');
  const original = f.ctx.api;
  f.ctx.api = async (method, path, body) => {
    const data = await original(method, path, body);
    if (path === '/patient/doctors') data.doctors.reverse();
    return data;
  };
  await doctors(f.view, f.ctx);
  assert.deepEqual(order(f.view.innerHTML), BOOKING_CATALOG.doctors.map(doctor => doctor.name).reverse());
});

test('P4 with no doctors offers a clinic call and another goal', async () => {
  choose('demo-no-doctors');
  const f = fixture('demo-no-doctors');
  await doctors(f.view, f.ctx);
  assert.ok(f.view.innerHTML.includes(BOOKING_TEXTS['p4.empty.title']));
  assert.match(f.view.innerHTML, /href="tel:\+70000000000"/);
  assert.match(f.view.innerHTML, /href="#\/p\/demo-no-doctors\/goal"/);
  assert.doesNotMatch(f.view.innerHTML, /booking-doctor-name/);
});

for (const token of ['demo-request-accepted', 'demo-request-in-progress']) {
  test(`P4, P5 and P1 lead to P6 while the request is open (${token})`, async () => {
    for (const screen of [doctors, request]) {
      const f = fixture(token, { doctor: 'doc-other' });
      await screen(f.view, f.ctx);
      assert.deepEqual(f.routes, [`#/p/${token}/status`]);
      assert.equal(f.calls.length, 1);
    }
    const g = fixture(token);
    await entry(g.view, g.ctx);
    await g.view.querySelector('form').emit('submit');
    assert.deepEqual(g.routes, [`#/p/${token}/status`]);
  });
}

for (const token of ['demo-request-booked', 'demo-request-cancelled']) {
  test(`a finished request does not block a new one (${token})`, async () => {
    const f = fixture(token);
    await doctors(f.view, f.ctx);
    assert.deepEqual(f.routes, []);
    assert.equal(order(f.view.innerHTML).length, 3);
    const g = fixture(token);
    await entry(g.view, g.ctx);
    await g.view.querySelector('form').emit('submit');
    assert.deepEqual(g.routes, [`#/p/${token}/step`]);
  });
}

test('P4 before a goal is chosen goes back to P3', async () => {
  const f = fixture('demo-step-retest');
  await doctors(f.view, f.ctx);
  assert.deepEqual(f.routes, ['#/p/demo-step-retest/goal']);
});

test('P5 sends only the picked values, nothing preselected, then opens P6', async () => {
  choose('demo-active', 'goal-other', 'discuss');
  const f = fixture('demo-active', { doctor: 'doc-other' });
  await request(f.view, f.ctx);
  assert.equal((f.view.innerHTML.match(/type="radio"/g) || []).length, 3 + 4);
  assert.doesNotMatch(f.view.innerHTML, /\bchecked\b|<textarea|type="text"/);
  assert.ok(f.view.innerHTML.includes(BOOKING_TEXTS['p5.confirm_note']));
  const form = f.view.querySelector('form');
  await form.emit('submit');
  assert.equal(f.calls.length, 3);
  form.emit('change', { name: 'format', value: 'fmt-online' });
  await form.emit('submit');
  assert.equal(f.calls.length, 3);
  form.emit('change', { name: 'window', value: 'evening' });
  await form.emit('submit');
  assert.deepEqual(f.calls[3], { method: 'POST', path: '/patient/requests', body: { doctor_id: 'doc-other', format_id: 'fmt-online', window_code: 'evening' } });
  assert.deepEqual(f.routes, ['#/p/demo-active/status']);
});

test('a repeated request goes to P6', async () => {
  choose('demo-step-followup');
  const f = fixture('demo-step-followup', { doctor: 'doc-other' });
  f.ctx.api = async (method, path) => {
    if (path === '/patient/session') return { ...respond('GET', path, undefined, { token: 'demo-step-followup' }).data, request: null };
    if (method === 'POST') throw new ApiError(409, 'request_exists', 'exists');
    return respond(method, path, undefined, { token: 'demo-step-followup' }).data;
  };
  await request(f.view, f.ctx);
  const form = f.view.querySelector('form');
  form.emit('change', { name: 'format', value: 'fmt-clinic' });
  form.emit('change', { name: 'window', value: 'any' });
  await form.emit('submit');
  assert.deepEqual(f.routes, ['#/p/demo-step-followup/status']);
});

test('P5 with a paid format shows the https payment link in a new tab', async () => {
  choose('demo-paid-format');
  const f = fixture('demo-paid-format', { doctor: 'doc-ordering' });
  await request(f.view, f.ctx);
  assert.ok(f.view.innerHTML.includes(BOOKING_TEXTS['p5.format.prepay']));
  const form = f.view.querySelector('form');
  form.emit('change', { name: 'format', value: 'fmt-quick' });
  form.emit('change', { name: 'window', value: 'morning' });
  await form.emit('submit');
  assert.deepEqual(f.routes, []);
  assert.match(f.view.innerHTML, /<a class="btn" href="https:\/\/example-clinic\.ru\/pay\/quick-answer" target="_blank" rel="noopener noreferrer">/);
  assert.match(f.view.innerHTML, /href="#\/p\/demo-paid-format\/status"/);
});

test('P5 never links to a payment address that is not https', async () => {
  for (const payment_url of ['http://example-clinic.ru/pay', 'javascript:alert(1)', '//example-clinic.ru/pay']) {
    const f = fixture('demo-step-discuss', { doctor: 'doc-other' });
    const original = f.ctx.api;
    f.ctx.api = async (method, path, body) => (method === 'POST' ? { request_id: 'r', status: 'accepted', payment_url } : original(method, path, body));
    await request(f.view, f.ctx);
    const form = f.view.querySelector('form');
    form.emit('change', { name: 'format', value: 'fmt-clinic' });
    form.emit('change', { name: 'window', value: 'any' });
    await form.emit('submit');
    assert.deepEqual(f.routes, ['#/p/demo-step-discuss/status'], payment_url);
    assert.doesNotMatch(f.view.innerHTML, /target="_blank"/);
  }
});

test('P5 keeps the choice on 422 and on a network error', async () => {
  for (const [error, key] of [[new ApiError(422, 'invalid_input', 'x'), 'err.invalid_input'], [new ApiError(0, 'network', 'x'), 'p5.error']]) {
    const f = fixture('demo-step-discuss', { doctor: 'doc-other' });
    const original = f.ctx.api;
    f.ctx.api = async (method, path, body) => { if (method === 'POST') throw error; return original(method, path, body); };
    await request(f.view, f.ctx);
    const form = f.view.querySelector('form');
    form.emit('change', { name: 'format', value: 'fmt-clinic' });
    form.emit('change', { name: 'window', value: 'any' });
    await form.emit('submit');
    assert.deepEqual(f.routes, []);
    const texts = respond('GET', '/patient/session', undefined, { token: 'demo-step-discuss' }).data.texts;
    // err.invalid_input приходит из mocks-care.js (FE4); до слияния — общий текст P5
    const expected = texts[key] ?? texts['p5.error'];
    assert.ok(expected);
    assert.ok(f.view.querySelector('.patient-feedback').innerHTML.includes(expected), key);
    assert.equal(form.querySelector('button[type="submit"]').disabled, false);
  }
});

test('P5 with an unknown doctor offers the list again', async () => {
  const f = fixture('demo-step-discuss', { doctor: 'doc-gone' });
  await request(f.view, f.ctx);
  assert.ok(f.view.innerHTML.includes(BOOKING_TEXTS['p5.no_doctor.title']));
  assert.doesNotMatch(f.view.innerHTML, /<form/);
});

for (const [token, state] of [['demo-request-accepted', 'accepted'], ['demo-request-in-progress', 'in_progress'],
  ['demo-request-booked', 'booked'], ['demo-request-cancelled', 'cancelled']]) {
  test(`P6 shows the ${state} request calmly with a clinic call`, async () => {
    const f = fixture(token);
    await status(f.view, f.ctx);
    assert.ok(f.view.innerHTML.includes(BOOKING_TEXTS[`p6.${state}.title`]));
    assert.ok(f.view.innerHTML.includes(BOOKING_TEXTS[`p6.${state}.body`]));
    assert.match(f.view.innerHTML, /href="tel:\+70000000000"/);
    const finished = state === 'booked' || state === 'cancelled';
    assert.equal((f.view.innerHTML.match(/<button/g) || []).length, finished ? 1 : 0);
    assert.equal(f.view.innerHTML.includes(BOOKING_TEXTS['p6.new_request']), finished);
    if (finished) {
      f.view.querySelector('[data-booking-new]').emit('click');
      assert.deepEqual(f.routes, [`#/p/${token}/goal`]);
    }
    assert.doesNotMatch(f.view.innerHTML, /red|green|#[Ee]0|таймер/);
    assert.equal(f.view.innerHTML.includes('booking-progress'), state !== 'cancelled');
    if (state !== 'cancelled') assert.match(f.view.innerHTML, /aria-current="step"/);
    assert.ok(f.view.innerHTML.includes('Иванова Анна Петровна'));
  });
}

test('P6 without a request goes to P4', async () => {
  const f = fixture('demo-clinic-a');
  await status(f.view, f.ctx);
  assert.deepEqual(f.routes, ['#/p/demo-clinic-a/doctors']);
});

test('patient errors on P4–P6 are handled, not thrown to the router', async () => {
  for (const [token, title] of [['demo-not-configured', SHELL['err.not_configured.title']], ['demo-error-500', SHELL['err.server.title']]]) {
    const f = fixture(token);
    await doctors(f.view, f.ctx);
    assert.ok(f.view.innerHTML.includes(safe(title)), token);
  }
  const f = fixture('demo-expired');
  await status(f.view, f.ctx);
  assert.deepEqual(f.routes, ['#/p/demo-expired']);
});

test('server values cross the escaping boundary on P4', async () => {
  const f = fixture('demo-step-discuss');
  const original = f.ctx.api;
  f.ctx.api = async (method, path, body) => {
    const data = await original(method, path, body);
    if (path === '/patient/doctors') data.doctors[0] = { ...data.doctors[0], name: '<b>demo</b>', id: '"x' };
    return data;
  };
  await doctors(f.view, f.ctx);
  assert.doesNotMatch(f.view.innerHTML, /<b>/);
  assert.match(f.view.innerHTML, /&lt;b&gt;demo&lt;\/b&gt;/);
  assert.match(f.view.innerHTML, /doctor=%22x/);
});
