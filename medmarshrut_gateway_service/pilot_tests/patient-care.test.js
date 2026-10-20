import test from 'node:test';
import assert from 'node:assert/strict';
import { handlePatientError, ERROR_TEXTS } from '../web/pilot/js/screens/patient-errors.js';
import { safe } from '../web/pilot/js/ui.js';
import { SHELL } from '../web/pilot/js/texts.js';
import { CARE, CARE_TEXTS, demoDate } from '../web/pilot/js/mocks-care.js';
import { PATIENT } from '../web/pilot/js/mocks-patient.js';
import { render as retest, formatCareDate } from '../web/pilot/js/screens/patient-retest.js';
import { render as after } from '../web/pilot/js/screens/patient-after.js';
import { render as step } from '../web/pilot/js/screens/patient-step.js';
import { beginRender } from '../web/pilot/js/screens/patient-state.js';
import { formatText } from '../web/pilot/js/screens/patient-state.js';

// Event/markup harness only; layout and native keyboard behavior belong to web-check.
class View {
  innerHTML = '';
  nodes = new Map();
  listeners = new Map();
  attributes = new Map();
  isConnected = true;
  disabled = false;
  querySelector(selector) {
    if (selector === '.patient-feedback' && !this.innerHTML.includes('patient-feedback')) return null;
    if (!this.nodes.has(selector)) this.nodes.set(selector, new View());
    return this.nodes.get(selector);
  }
  insertAdjacentHTML(position, html) { this.innerHTML += html; }
  addEventListener(type, handler) { this.listeners.set(type, handler); }
  emit(type) { return this.listeners.get(type)?.({ preventDefault() {} }); }
  setAttribute(key, value) { this.attributes.set(key, value); }
  removeAttribute(key) { this.attributes.delete(key); }
  focus() { this.focused = true; }
}
function fixture() {
  const view = new View(), routes = [], calls = [];
  const ctx = {
    safe, texts: SHELL, params: { token: 'demo-care' },
    go: path => routes.push(path), retry: () => calls.push('retry'),
    clinic: { phone: '+7 000 000-00-00' },
  };
  return { view, ctx, routes, calls };
}
const SESSION_TEXTS = { ...PATIENT['demo-active'].texts, ...CARE_TEXTS };
for (const [status, code, key] of [
  [404, 'link_not_found', 'link_not_found'],
  [503, 'not_configured', 'not_configured'],
  [0, 'network', 'network'],
  [500, 'server_error', 'server'],
  [502, 'bad_gateway', 'server'],
]) {
  test(`patient error ${status} ${code} has approved copy and a recovery action`, () => {
    const f = fixture();
    assert.equal(handlePatientError({ status, code, message: '<b>private</b>' }, f.view, f.ctx, SESSION_TEXTS), true);
    assert.ok(f.view.innerHTML.includes(ERROR_TEXTS[`err.${key}.title`]));
    assert.ok(f.view.innerHTML.includes(ERROR_TEXTS[`err.${key}.body`]));
    assert.doesNotMatch(f.view.innerHTML, /private/);
    assert.doesNotMatch(f.view.innerHTML, /danger|error-red|!/);
    if (['network', 'server'].includes(key)) {
      assert.doesNotMatch(f.view.innerHTML, /tel:/);
      const button = f.view.querySelector('[data-patient-retry]');
      button.emit('click');
      button.emit('click');
      assert.deepEqual(f.calls, ['retry']);
      assert.equal(button.disabled, true);
      if (key === 'network') assert.equal(button.textContent, ERROR_TEXTS['err.network.pending']);
    } else {
      assert.match(f.view.innerHTML, /href="tel:\+70000000000"/);
      assert.doesNotMatch(f.view.innerHTML, /data-patient-retry/);
    }
  });
}
test('error copy from SHELL wins over session texts and the local fallback', () => {
  const f = fixture();
  f.ctx.texts = { ...SHELL, 'err.link_not_found.title': 'Из оболочки' };
  handlePatientError({ status: 404, code: 'link_not_found' }, f.view, f.ctx, { 'err.link_not_found.title': 'Из сессии' });
  assert.match(f.view.innerHTML, /Из оболочки/);
  assert.doesNotMatch(f.view.innerHTML, /Из сессии/);
});
test('the local error fallback repeats the designer SHELL copy exactly', () => {
  // p4-p8.md, «Ошибки до ответа сессии»: те же строки фронтенд кладёт в texts.js (SHELL)
  assert.deepEqual(Object.keys(ERROR_TEXTS).sort(), [
    'err.call.no_phone', 'err.invalid_input',
    'err.link_not_found.body', 'err.link_not_found.title',
    'err.network.action', 'err.network.body', 'err.network.pending', 'err.network.title',
    'err.not_configured.body', 'err.not_configured.title',
    'err.server.action', 'err.server.body', 'err.server.title',
  ]);
  assert.equal(ERROR_TEXTS['err.invalid_input'], CARE_TEXTS['err.invalid_input']);
  for (const [key, value] of Object.entries(SHELL)) {
    if (key.startsWith('err.')) assert.equal(value, ERROR_TEXTS[key]);
  }
});
test('a known phone without session call copy falls back to the no-phone line', () => {
  const f = fixture();
  handlePatientError({ status: 503, code: 'not_configured' }, f.view, f.ctx);
  assert.doesNotMatch(f.view.innerHTML, /tel:/);
  assert.ok(f.view.innerHTML.includes(ERROR_TEXTS['err.call.no_phone']));
});
for (const [code, suffix] of [
  ['not_active', ''], ['consent_required', ''], ['choice_required', '/goal'], ['request_exists', '/status'],
]) {
  test(`409 ${code} returns to the required screen`, () => {
    const f = fixture();
    assert.equal(handlePatientError({ status: 409, code }, f.view, f.ctx), true);
    assert.deepEqual(f.routes, [`#/p/demo-care${suffix}`]);
  });
}
test('422 preserves the form and selection and focuses its inline message', () => {
  const f = fixture();
  f.view.innerHTML = '<form><input type="radio" checked><div class="patient-feedback"></div></form>';
  const original = f.view.innerHTML;
  const selected = f.view.querySelector('input');
  assert.equal(handlePatientError({ status: 422, code: 'invalid_input' }, f.view, f.ctx), true);
  assert.equal(f.view.innerHTML, original);
  assert.equal(f.view.querySelector('input'), selected);
  assert.match(f.view.querySelector('.patient-feedback').innerHTML, /note/);
  assert.equal(f.view.querySelector('.patient-feedback').focused, true);
});
test('422 creates feedback if the caller has not provided a feedback slot', () => {
  const f = fixture();
  f.view.innerHTML = '<form>selected</form>';
  handlePatientError({ status: 422, code: 'invalid_input' }, f.view, f.ctx);
  assert.match(f.view.innerHTML, /<form>selected<\/form>/);
  assert.match(f.view.innerHTML, /patient-feedback/);
});
test('errors without a known clinic do not invent a phone', () => {
  const f = fixture();
  delete f.ctx.clinic;
  handlePatientError({ status: 404, code: 'link_not_found' }, f.view, f.ctx);
  assert.doesNotMatch(f.view.innerHTML, /tel:/);
});
test('patient error strings are escaped and unknown errors remain unhandled', () => {
  const f = fixture();
  f.ctx.texts = { ...SHELL, 'err.link_not_found.title': '<b>demo</b>' };
  handlePatientError({ status: 404, code: 'link_not_found' }, f.view, f.ctx);
  assert.match(f.view.innerHTML, /&lt;b&gt;demo&lt;\/b&gt;/);
  assert.equal(handlePatientError({ status: 403, code: 'other' }, f.view, f.ctx), false);
  assert.equal(handlePatientError(new Error('programming error'), f.view, f.ctx), false);
});

function careFixture(token = 'demo-retest-before') {
  const f = fixture();
  f.session = structuredClone(CARE[token]);
  f.ctx.params.token = token;
  f.ctx.theme = { apply() {} };
  f.ctx.api = async (method, path, body) => {
    f.calls.push({ method, path, body });
    return method === 'GET' ? f.session : { ok: true };
  };
  return f;
}
test('care dates use the clinic calendar date and reject missing or invalid dates', () => {
  assert.equal(formatCareDate('2026-11-17', 2026), '17 ноября');
  assert.equal(formatCareDate('2028-02-29', 2028), '29 февраля');
  assert.equal(formatCareDate('2027-01-17', 2026), '17 января 2027');
  for (const value of [null, '', '2026-02-30', '2026-11-17T00:00:00Z', '<b>demo</b>']) {
    assert.equal(formatCareDate(value), null);
  }
});
for (const state of ['before', 'today', 'overdue']) {
  test(`P7 ${state} uses server state, date and memo and opens goal selection`, async () => {
    const f = careFixture(`demo-retest-${state}`);
    f.session.doctor_step.due_date = '2026-11-17';
    await retest(f.view, f.ctx);
    assert.ok(f.view.innerHTML.includes(formatText(CARE_TEXTS[`p7.${state}.body`], { date: formatCareDate('2026-11-17') })));
    for (const n of [1, 2, 3]) assert.ok(f.view.innerHTML.includes(CARE_TEXTS[`p7.memo.${n}`]));
    if (state !== 'today') assert.match(f.view.innerHTML, /17 ноября/);
    assert.doesNotMatch(f.view.innerHTML, /overdue|countdown|timer|danger/);
    f.view.querySelector('[data-care-book]').emit('click');
    assert.deepEqual(f.routes, [`#/p/demo-retest-${state}/goal`]);
  });
}
test('P7 does not calculate or invent a missing doctor date or state', async () => {
  for (const changes of [{ due_date: null }, { retest_state: null }]) {
    const f = careFixture();
    Object.assign(f.session.doctor_step, changes);
    await retest(f.view, f.ctx);
    assert.doesNotMatch(f.view.innerHTML, /data-care-book/);
    assert.ok(f.view.innerHTML.includes(CARE_TEXTS['p7.none.title']));
  }
});
test('P2 retest leads to P7 while other doctor steps still lead to P3', async () => {
  for (const code of ['retest', 'discuss', 'followup']) {
    const f = careFixture();
    f.session.doctor_step.code = code;
    await step(f.view, f.ctx);
    if (code === 'retest') assert.match(f.view.innerHTML, /Когда пересдавать/);
    f.view.querySelector(code === 'retest' ? '[data-patient-retest]' : '[data-patient-next]').emit('click');
    assert.deepEqual(f.routes, [`#/p/demo-retest-before/${code === 'retest' ? 'retest' : 'goal'}`]);
  }
});
test('P2 retest without the P7 entry copy shows no empty button', async () => {
  const f = careFixture();
  delete f.session.texts['p7.entry'];
  await step(f.view, f.ctx);
  assert.doesNotMatch(f.view.innerHTML, /data-patient-retest/);
});
test('P7 and P8 show no clinic call and no countdown', async () => {
  for (const [screen, token] of [[retest, 'demo-retest-overdue'], [after, 'demo-after-visit']]) {
    const f = careFixture(token);
    await screen(f.view, f.ctx);
    assert.doesNotMatch(f.view.innerHTML, /tel:|осталось|прошло|просроч/i);
  }
});
test('P8 displays the step, memo, demo label and both booking actions', async () => {
  const f = careFixture('demo-after-visit');
  await after(f.view, f.ctx);
  assert.match(f.view.innerHTML, /демо/i);
  assert.ok(f.view.innerHTML.includes(CARE_TEXTS['p8.memo.1']));
  assert.ok(f.view.innerHTML.includes(f.session.after_visit.step.doctor_name));
  f.view.querySelector('[data-care-book]').emit('click');
  assert.deepEqual(f.routes, ['#/p/demo-after-visit/goal']);
  await f.view.querySelector('[data-care-booked]').emit('click');
  assert.deepEqual(f.calls[1], { method: 'POST', path: '/patient/after-visit/booked', body: undefined });
  assert.ok(f.view.querySelector('[data-care-actions]').innerHTML.includes(CARE_TEXTS['p8.booked.done']));
  assert.equal(f.view.querySelector('[data-care-confirmation]').focused, true);
  assert.ok(f.view.innerHTML.includes(CARE_TEXTS['p8.retest.title']));
  assert.doesNotMatch(f.view.querySelector('[data-care-actions]').innerHTML, /data-care-book/);
});
test('P8 already booked renders acknowledgement without posting or booking buttons', async () => {
  const f = careFixture('demo-after-booked');
  await after(f.view, f.ctx);
  assert.ok(f.view.innerHTML.includes(CARE_TEXTS['p8.booked.already']));
  assert.doesNotMatch(f.view.innerHTML, /data-care-book/);
  assert.equal(f.calls.length, 1);
});
test('P8 absent step offers the next step without inventing a recommendation', async () => {
  for (const value of [null, { step: null, booked: false }, { step: { code: 'unknown', due_date: null, doctor_name: null }, booked: false }]) {
    const f = careFixture('demo-after-visit');
    f.session.after_visit = value;
    await after(f.view, f.ctx);
    assert.doesNotMatch(f.view.innerHTML, /data-care-book/);
    assert.ok(f.view.innerHTML.includes(CARE_TEXTS['p8.empty.title']));
    f.view.querySelector('[data-care-step]').emit('click');
    assert.deepEqual(f.routes, ['#/p/demo-after-visit/step']);
  }
});
test('P8 displays all named doctor steps and escapes clinic copy', async () => {
  for (const code of ['observe', 'retest', 'specialist', 'none']) {
    const f = careFixture('demo-after-visit');
    f.session.after_visit.step.code = code;
    f.session.after_visit.step.doctor_name = '<b>demo</b>';
    f.session.texts['p8.memo.1'] = '<b>memo</b>';
    await after(f.view, f.ctx);
    assert.ok(f.view.innerHTML.includes(CARE_TEXTS[`p8.${code}.title`]));
    assert.match(f.view.innerHTML, /&lt;b&gt;demo&lt;\/b&gt;/);
    assert.match(f.view.innerHTML, /&lt;b&gt;memo&lt;\/b&gt;/);
    assert.doesNotMatch(f.view.innerHTML, /<b>/);
  }
});
test('P8 serializes clicks and acknowledges only a successful response', async () => {
  const f = careFixture('demo-after-visit');
  await after(f.view, f.ctx);
  let resolve, posts = 0;
  f.ctx.api = () => { posts++; return new Promise(done => { resolve = done; }); };
  const button = f.view.querySelector('[data-care-booked]');
  const first = button.emit('click');
  await button.emit('click');
  assert.equal(posts, 1);
  assert.equal(button.disabled, true);
  assert.equal(f.view.querySelector('[data-care-book]').disabled, true);
  resolve({ ok: false });
  await first;
  assert.equal(button.disabled, false);
  assert.doesNotMatch(f.view.innerHTML, /Хорошо, напоминать не будем/);
});
test('P8 a stale successful response cannot replace a newer screen', async () => {
  const f = careFixture('demo-after-visit');
  await after(f.view, f.ctx);
  let resolve;
  f.ctx.api = () => new Promise(done => { resolve = done; });
  const pending = f.view.querySelector('[data-care-booked]').emit('click');
  beginRender(f.view);
  f.view.innerHTML = '<p>new screen</p>';
  resolve({ ok: true });
  await pending;
  assert.equal(f.view.innerHTML, '<p>new screen</p>');
});
for (const error of [{ status: 0, code: 'network' }, { status: 500, code: 'server_error' }]) {
  test(`P8 ${error.code} keeps the step and enables another save attempt`, async () => {
    const f = careFixture('demo-after-visit');
    await after(f.view, f.ctx);
    f.ctx.api = async () => { throw error; };
    const button = f.view.querySelector('[data-care-booked]');
    await button.emit('click');
    assert.ok(f.view.innerHTML.includes(CARE_TEXTS['p8.retest.title']));
    assert.equal(button.disabled, false);
    assert.equal(f.view.querySelector('[data-care-book]').disabled, false);
    assert.ok(f.view.querySelector('.patient-feedback').innerHTML.includes(CARE_TEXTS['p8.booked.error']));
    assert.deepEqual(f.routes, []);
  });
}
test('P8 access errors still return through the shared error handler', async () => {
  const f = careFixture('demo-after-visit');
  await after(f.view, f.ctx);
  f.ctx.api = async () => { throw { status: 409, code: 'not_active' }; };
  await f.view.querySelector('[data-care-booked]').emit('click');
  assert.deepEqual(f.routes, ['#/p/demo-after-visit']);
});
test('P8 not_configured shows clinic contact instead of an ordinary save failure', async () => {
  const f = careFixture('demo-after-visit');
  await after(f.view, f.ctx);
  f.ctx.api = async () => { throw { status: 503, code: 'not_configured' }; };
  await f.view.querySelector('[data-care-booked]').emit('click');
  assert.ok(f.view.innerHTML.includes(ERROR_TEXTS['err.not_configured.title']));
  assert.match(f.view.innerHTML, /href="tel:\+70000000000"/);
});
test('retry without a callback rerenders the current hash, including its screen', () => {
  const f = fixture();
  delete f.ctx.retry;
  const previous = globalThis.location;
  try {
    globalThis.location = { hash: '#/p/demo-care/retest' };
    handlePatientError({ status: 0, code: 'network' }, f.view, f.ctx);
    f.view.querySelector('[data-patient-retry]').emit('click');
    assert.deepEqual(f.routes, ['#/p/demo-care/retest']);
  } finally {
    if (previous === undefined) delete globalThis.location;
    else globalThis.location = previous;
  }
});
test('no care or error copy uses prohibited patient terms or temporary design strings', () => {
  for (const value of [...Object.values(CARE_TEXTS), ...Object.values(ERROR_TEXTS)]) {
    assert.doesNotMatch(value, /расшифров|риск|срочн|отклонени|диагноз|TODO design|!/iu);
  }
});
for (const screen of [retest, after]) {
  test(`${screen === retest ? 'P7' : 'P8'} enforces consent and inactive session entry`, async () => {
    for (const changes of [{ consent_required: true }, { state: 'expired' }]) {
      const f = careFixture();
      Object.assign(f.session, changes);
      await screen(f.view, f.ctx);
      assert.deepEqual(f.routes, ['#/p/demo-retest-before']);
      assert.doesNotMatch(f.view.innerHTML, /data-care-book/);
    }
  });
  test(`${screen === retest ? 'P7' : 'P8'} handles a failed session load`, async () => {
    const f = careFixture();
    f.ctx.api = async () => { throw { status: 0, code: 'network' }; };
    await screen(f.view, f.ctx);
    assert.ok(f.view.innerHTML.includes(ERROR_TEXTS['err.network.title']));
  });
}
test('care mock dates follow today so each state stays the same over time', () => {
  assert.equal(CARE['demo-retest-before'].doctor_step.due_date, demoDate(28));
  assert.equal(CARE['demo-retest-today'].doctor_step.due_date, demoDate(0));
  assert.equal(CARE['demo-retest-overdue'].doctor_step.due_date, demoDate(-10));
  assert.ok(demoDate(-10) < demoDate(0) && demoDate(0) < demoDate(28));
  for (const state of ['before', 'today', 'overdue']) {
    const step = CARE[`demo-retest-${state}`].doctor_step;
    assert.equal(step.retest_state, state);
    assert.equal(step.doctor_name, 'Иванова Анна Петровна');
  }
  assert.equal(CARE['demo-after-visit'].after_visit.booked, false);
  assert.equal(CARE['demo-after-booked'].after_visit.booked, true);
  assert.equal(CARE['demo-after-visit'].after_visit.step.due_date, demoDate(28));
});
test('demo-step-retest keeps its FE2 step and only gains a date and state', () => {
  const original = PATIENT['demo-step-retest'];
  const extended = CARE['demo-step-retest'];
  assert.deepEqual(extended.doctor_step, { ...original.doctor_step, due_date: demoDate(28), retest_state: 'before' });
  assert.deepEqual(extended.clinic, original.clinic);
  assert.deepEqual(extended.goals, original.goals);
  assert.deepEqual(extended.branches, original.branches);
  for (const [key, value] of Object.entries(original.texts)) assert.equal(extended.texts[key], value);
});
test('care data provides isolated synthetic sessions', () => {
  assert.notEqual(CARE['demo-retest-before'].doctor_step, CARE['demo-retest-today'].doctor_step);
  assert.notEqual(CARE['demo-after-visit'].after_visit, CARE['demo-after-booked'].after_visit);
  for (const session of Object.values(CARE)) {
    assert.equal(session.state, 'active');
    assert.equal(session.clinic.phone, '+7 000 000-00-00');
    assert.equal(session.choice, null);
    assert.equal(session.request, null);
    for (const [key, value] of Object.entries(CARE_TEXTS)) assert.equal(session.texts[key], value);
  }
});
