// Run: node --test medmarshrut_gateway_service/pilot_tests/
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { choiceFor, chooseBranch, chooseGoal, patientPath, formatText,
  requiresEntry, selectedBranch, beginRender, doctorStepText } from '../web/pilot/js/screens/patient-state.js';
import { PATIENT } from '../web/pilot/js/mocks-patient.js';
import { api, useToken } from '../web/pilot/js/api.js';
import { contrastWithWhite } from '../web/pilot/js/theme.js';
import { SHELL } from '../web/pilot/js/texts.js';
import { render as entry } from '../web/pilot/js/screens/patient-entry.js';
import { render as step } from '../web/pilot/js/screens/patient-step.js';
import { render as goal } from '../web/pilot/js/screens/patient-goal.js';
import { render as next } from '../web/pilot/js/screens/patient-next.js';

test('all ten mock sessions use the exact patient copy from the design JSON', () => {
  const design = readFileSync(new URL('../../docs/rescan-pilot/design/p1-p3.md', import.meta.url), 'utf8');
  const texts = JSON.parse(design.match(/```json\s*([\s\S]*?)```/)[1]);
  assert.equal(Object.keys(PATIENT).length, 10);
  for (const session of Object.values(PATIENT)) {
    assert.deepEqual(session.texts, texts);
    assert.deepEqual(Object.keys(session).sort(), ['state', 'clinic', 'consent_required', 'doctor_step', 'branches', 'goals', 'texts'].sort());
    assert.deepEqual(session.branches.map(item => item.code), ['discuss', 'retest', 'followup']);
    for (const branch of session.branches) {
      assert.equal(branch.title, texts[`p2.branch.${branch.code}.title`]);
      assert.equal(branch.hint, texts[`p2.branch.${branch.code}.hint`]);
    }
    assert.deepEqual(session.goals, [
      { id: 'goal-discuss', title: 'Обсудить анализы с врачом' },
      { id: 'goal-retest', title: 'Пересдать анализы' },
      { id: 'goal-followup', title: 'Повторный приём у своего врача' },
      { id: 'goal-other', title: 'Другой вопрос к врачу' },
    ]);
  }
});

test('clinic themes exercise both FE1 contrast paths', () => {
  const a = PATIENT['demo-clinic-a'].clinic;
  const b = PATIENT['demo-clinic-b'].clinic;
  assert.deepEqual(Object.keys(a.theme).sort(), ['accent', 'logo_url', 'name']);
  assert.equal(a.theme.accent, '#1D5FD1');
  assert.equal(b.theme.accent, '#00A3AD');
  assert.ok(contrastWithWhite(a.theme.accent) >= 4.5);
  assert.ok(contrastWithWhite(b.theme.accent) < 4.5);
  assert.equal(a.phone, '+7 000 000-00-00');
  assert.equal(b.phone, undefined);
});

test('FE1 API reads patient data and owns token and consent handling', async () => {
  useToken('demo-consent');
  assert.equal((await api('GET', '/patient/session')).consent_required, true);
  await assert.rejects(api('POST', '/patient/choice', { branch_code: 'discuss', goal_id: 'goal-discuss' }), { code: 'consent_required' });
  assert.deepEqual(await api('POST', '/patient/consent'), { ok: true });
  assert.equal((await api('GET', '/patient/session')).consent_required, false);
  assert.deepEqual(await api('POST', '/patient/choice', { branch_code: 'discuss', goal_id: 'goal-discuss' }), { ok: true });
  useToken('demo-expired');
  await assert.rejects(api('POST', '/patient/consent'), { code: 'not_active' });
  useToken(null);
});

test('patient paths encode the token as one hash segment', () => {
  assert.equal(patientPath('demo/a?b', 'goal'), '#/p/demo%2Fa%3Fb/goal');
  assert.equal(patientPath('demo-active'), '#/p/demo-active');
});

test('a new patient has no inferred branch or goal', () => {
  assert.deepEqual(choiceFor('demo-empty'), { branch_code: null, goal_id: null });
});

test('choices remain separate for different demo links', () => {
  chooseBranch('demo-one', 'book');
  chooseGoal('demo-one', 'visit');
  assert.deepEqual(choiceFor('demo-two'), { branch_code: null, goal_id: null });
  assert.deepEqual(choiceFor('demo-one'), { branch_code: 'book', goal_id: 'visit' });
});

test('changing a branch clears the old goal', () => {
  chooseBranch('demo-change', 'book');
  chooseGoal('demo-change', 'visit');
  chooseBranch('demo-change', 'later');
  assert.equal(choiceFor('demo-change').goal_id, null);
});

test('returned choices cannot mutate state', () => {
  choiceFor('demo-copy').goal_id = 'visit';
  assert.equal(choiceFor('demo-copy').goal_id, null);
});

for (const state of ['expired', 'stopped', 'unsubscribed', 'unknown']) {
  test(`${state} links cannot open later steps`, () => {
    assert.equal(requiresEntry({ state, consent_required: false }), true);
  });
}

test('consent is required even on a direct goal link', () => {
  assert.equal(requiresEntry({ state: 'active', consent_required: true }), true);
  assert.equal(requiresEntry({ state: 'active', consent_required: false }), false);
});

test('doctor steps send a null branch, without retaining an earlier choice', () => {
  chooseBranch('demo-doctor', 'book');
  assert.equal(selectedBranch('demo-doctor', { doctor_step: { code: 'discuss' } }), null);
});

test('a removed branch cannot be submitted', () => {
  chooseBranch('demo-removed', 'book');
  assert.equal(selectedBranch('demo-removed', { doctor_step: null, branches: [] }), null);
});

test('an available branch is preserved', () => {
  chooseBranch('demo-kept', 'book');
  assert.equal(selectedBranch('demo-kept', { doctor_step: null, branches: [{ code: 'book' }] }), 'book');
});

test('template substitution leaves escaping to the rendering boundary', () => {
  assert.equal(formatText('In {weeks}: {name}', { weeks: 4, name: '<b>demo</b>' }), 'In 4: <b>demo</b>');
});

test('an earlier asynchronous render cannot overwrite a newer screen', () => {
  const view = {};
  const old = beginRender(view);
  const current = beginRender(view);
  assert.equal(old(), false);
  assert.equal(current(), true);
});

// A small event target for contract tests; actual DOM/layout are checked with Playwright.
class View {
  innerHTML = '';
  nodes = new Map();
  listeners = new Map();
  attributes = new Map();
  checked = false;
  disabled = false;
  querySelector(selector) {
    if (!this.nodes.has(selector)) this.nodes.set(selector, new View());
    return this.nodes.get(selector);
  }
  addEventListener(type, handler) { this.listeners.set(type, handler); }
  emit(type, target = {}) { return this.listeners.get(type)?.({ preventDefault() {}, target }); }
  setAttribute(name, value) { this.attributes.set(name, value); }
  removeAttribute(name) { this.attributes.delete(name); }
  focus() {}
}
function fixture(token = 'demo-active') {
  const session = structuredClone(PATIENT[token]);
  const calls = [], routes = [], themes = [];
  const view = new View();
  const ctx = {
    params: { token }, texts: SHELL,
    safe: value => String(value ?? '').replace(/[&<>"']/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[char]),
    theme: { apply: theme => themes.push(theme) },
    go: route => routes.push(route),
    api: async (method, path, body) => {
      calls.push({ method, path, body });
      return method === 'GET' ? session : { ok: true };
    },
  };
  return { view, ctx, session, calls, routes, themes };
}

for (const state of ['expired', 'stopped', 'unsubscribed']) {
  test(`${state} entry explains the state and only offers clinic contact`, async () => {
    const f = fixture(`demo-${state}`);
    await entry(f.view, f.ctx);
    assert.ok(f.view.innerHTML.includes(f.session.texts[`p1.${state}.body`]));
    assert.match(f.view.innerHTML, /href="tel:\+70000000000"/);
    assert.doesNotMatch(f.view.innerHTML, /<button|<form/);
  });
}

test('entry posts consent only after the explicit consent button is pressed', async () => {
  const f = fixture('demo-consent');
  await entry(f.view, f.ctx);
  assert.doesNotMatch(f.view.innerHTML, /<input/);
  assert.ok(f.view.innerHTML.includes(f.session.texts['p1.consent.action']));
  const form = f.view.querySelector('form');
  assert.equal(f.calls.length, 1);
  await form.emit('submit');
  assert.deepEqual(f.calls[1], { method: 'POST', path: '/patient/consent', body: undefined });
  assert.deepEqual(f.routes, ['#/p/demo-consent/step']);
});

test('failed consent stays on entry and allows another attempt', async () => {
  const f = fixture('demo-consent');
  await entry(f.view, f.ctx);
  f.ctx.api = async () => { throw new Error('unavailable'); };
  const form = f.view.querySelector('form');
  await form.emit('submit');
  assert.deepEqual(f.routes, []);
  assert.ok(f.view.querySelector('.patient-feedback').innerHTML.includes(f.session.texts['p1.consent.error']));
  assert.equal(form.querySelector('button').disabled, false);
});

test('closed clinic without a phone uses the approved fallback copy', async () => {
  const f = fixture('demo-clinic-b');
  f.session.state = 'stopped';
  await entry(f.view, f.ctx);
  assert.ok(f.view.innerHTML.includes(f.session.texts['p1.call.no_phone']));
  assert.doesNotMatch(f.view.innerHTML, /tel:|<button|<form/);
});

test('consent prevents double posting and shows the approved pending copy', async () => {
  const f = fixture('demo-consent');
  await entry(f.view, f.ctx);
  let resolve;
  f.ctx.api = () => { f.calls.push('consent'); return new Promise(done => { resolve = done; }); };
  const form = f.view.querySelector('form');
  const pending = form.emit('submit');
  await form.emit('submit');
  assert.equal(f.calls.length, 2);
  assert.equal(form.querySelector('button').textContent, f.session.texts['p1.consent.pending']);
  assert.equal(form.querySelector('button').disabled, true);
  resolve({ ok: true });
  await pending;
  assert.deepEqual(f.routes, ['#/p/demo-consent/step']);
});

test('retest uses the approved Russian week forms', () => {
  const session = structuredClone(PATIENT['demo-step-retest']);
  for (const [weeks, text] of [[1, '1 неделю'], [2, '2 недели'], [4, '4 недели'], [8, '8 недель'], [11, '11 недель'], [12, '12 недель'], [14, '14 недель'], [21, '21 неделю'], [22, '22 недели']]) {
    session.doctor_step.retest_weeks = weeks;
    assert.equal(doctorStepText(session), session.texts['p2.retest.title'].replace('{weeks_text}', text));
  }
});

test('a doctor without a name has no empty author label', async () => {
  const f = fixture('demo-step-discuss');
  f.session.doctor_step.doctor_name = null;
  await step(f.view, f.ctx);
  assert.doesNotMatch(f.view.innerHTML, /patient-eyebrow/);
});

for (const code of ['discuss', 'retest', 'followup']) {
  test(`doctor ${code} step displays clinic text and an escaped author`, async () => {
    const f = fixture(`demo-step-${code}`);
    f.session.doctor_step.doctor_name = '<b>demo</b>';
    await step(f.view, f.ctx);
    assert.ok(f.view.innerHTML.includes(doctorStepText(f.session)));
    assert.match(f.view.innerHTML, /&lt;b&gt;demo&lt;\/b&gt;/);
    assert.doesNotMatch(f.view.innerHTML, /type="radio"/);
  });
}

test('no doctor step offers exactly three branches, with no default', async () => {
  const f = fixture();
  await step(f.view, f.ctx);
  assert.equal((f.view.innerHTML.match(/type="radio"/g) || []).length, 3);
  assert.doesNotMatch(f.view.innerHTML, /\bchecked\b/);
  const form = f.view.querySelector('form');
  await form.emit('submit');
  assert.deepEqual(f.routes, []);
  form.emit('change', { name: 'branch', value: f.session.branches[1].code });
  await form.emit('submit');
  assert.equal(choiceFor('demo-active').branch_code, f.session.branches[1].code);
  assert.deepEqual(f.routes, ['#/p/demo-active/goal']);
});

test('goal shows four options and sends only the selected branch and goal', async () => {
  const f = fixture();
  chooseBranch('demo-active', f.session.branches[0].code);
  await goal(f.view, f.ctx);
  assert.equal((f.view.innerHTML.match(/type="radio"/g) || []).length, 4);
  const form = f.view.querySelector('form');
  await form.emit('submit');
  assert.equal(f.calls.length, 1);
  form.emit('change', { name: 'goal', value: f.session.goals[2].id });
  await form.emit('submit');
  assert.deepEqual(f.calls[1], { method: 'POST', path: '/patient/choice', body: {
    branch_code: f.session.branches[0].code, goal_id: f.session.goals[2].id,
  } });
  assert.deepEqual(f.routes, ['#/p/demo-active/next']);
});

test('a direct goal link without a branch returns to step', async () => {
  const f = fixture('demo-clinic-a');
  await goal(f.view, f.ctx);
  assert.deepEqual(f.routes, ['#/p/demo-clinic-a/step']);
});

test('a failed choice does not advance or clear the selection', async () => {
  const f = fixture('demo-step-discuss');
  await goal(f.view, f.ctx);
  f.ctx.api = async () => { throw new Error('unavailable'); };
  const form = f.view.querySelector('form');
  form.emit('change', { name: 'goal', value: f.session.goals[0].id });
  await form.emit('submit');
  assert.deepEqual(f.routes, []);
  assert.equal(form.querySelector('button[type="submit"]').disabled, false);
  assert.equal(form.querySelector('fieldset').disabled, false);
  assert.ok(f.view.querySelector('.patient-feedback').innerHTML.includes(f.session.texts['p3.error']));
});

test('double submission sends one choice request', async () => {
  const f = fixture('demo-step-followup');
  await goal(f.view, f.ctx);
  let resolve;
  f.ctx.api = () => {
    f.calls.push('choice');
    return new Promise(done => { resolve = done; });
  };
  const form = f.view.querySelector('form');
  form.emit('change', { name: 'goal', value: f.session.goals[0].id });
  const pending = form.emit('submit');
  await form.emit('submit');
  assert.equal(f.calls.length, 2);
  resolve({ ok: true });
  await pending;
  assert.deepEqual(f.routes, ['#/p/demo-step-followup/next']);
});

for (const screen of [step, goal, next]) {
  test(`later screen ${screen.name} requires consent`, async () => {
    const f = fixture('demo-consent');
    await screen(f.view, f.ctx);
    assert.deepEqual(f.routes, ['#/p/demo-consent']);
    assert.equal(f.calls.length, 1);
  });
}

test('all clinic content crosses the escaping boundary', async () => {
  const f = fixture('demo-clinic-b');
  f.session.texts['p1.active.title'] = '<b>demo</b>';
  f.session.texts['p1.active.body'] = '<b>demo</b>';
  await entry(f.view, f.ctx);
  assert.doesNotMatch(f.view.innerHTML, /<b>/);
  assert.match(f.view.innerHTML, /&lt;b&gt;demo&lt;\/b&gt;/);
  assert.deepEqual(f.themes[0], { ...f.session.clinic.theme, name: f.session.clinic.name });
});

test('a direct goal link with an unknown doctor step cannot submit a choice', async () => {
  const f = fixture('demo-step-discuss');
  f.session.doctor_step.code = 'unknown';
  await goal(f.view, f.ctx);
  assert.deepEqual(f.routes, ['#/p/demo-step-discuss/step']);
});

test('a doctor retest without a valid week count cannot proceed', async () => {
  const f = fixture('demo-step-retest');
  f.session.doctor_step.retest_weeks = null;
  await goal(f.view, f.ctx);
  assert.deepEqual(f.routes, ['#/p/demo-step-retest/step']);
});

test('a completed request from a detached form cannot navigate away from a newer screen', async () => {
  const f = fixture('demo-step-discuss');
  await goal(f.view, f.ctx);
  let resolve;
  f.ctx.api = () => new Promise(done => { resolve = done; });
  const form = f.view.querySelector('form');
  form.emit('change', { name: 'goal', value: f.session.goals[0].id });
  const pending = form.emit('submit');
  form.isConnected = false;
  resolve({ ok: true });
  await pending;
  assert.deepEqual(f.routes, []);
});
