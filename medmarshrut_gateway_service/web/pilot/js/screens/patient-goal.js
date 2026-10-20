import { loadPatient, page, feedback, showFeedback, backButton } from './patient-common.js';
import { patientPath, choiceFor, chooseGoal, selectedBranch, doctorStepText } from './patient-state.js';

export async function render(view, ctx) {
  const data = await loadPatient(view, ctx);
  if (!data) return;
  const { session, token, texts, current } = data;
  if (session.doctor_step && !doctorStepText(session)) { ctx.go(patientPath(token, 'step')); return; }
  const branch = selectedBranch(token, session);
  if (!session.doctor_step && branch === null) { ctx.go(patientPath(token, 'step')); return; }
  let selected = session.goals.find(goal => goal.id === choiceFor(token).goal_id)?.id ?? null;
  page(view, ctx, texts['p3.title'], `<form class="patient-form">
    <fieldset class="patient-options"><legend class="sr-only">${ctx.safe(texts['p3.title'])}</legend>
    ${session.goals.map(goal => `<label class="card patient-option">
      <input type="radio" name="goal" value="${ctx.safe(goal.id)}" ${goal.id === selected ? 'checked' : ''} required>
      <span class="patient-option-title">${ctx.safe(goal.title)}</span></label>`).join('')}</fieldset>
    ${feedback()}<button class="btn" type="submit" ${selected === null ? 'disabled' : ''}>${ctx.safe(texts['p3.action'])}</button>
    <p class="patient-muted patient-small" data-patient-choose ${selected === null ? '' : 'hidden'}>${ctx.safe(texts['p3.choose'])}</p></form>`, texts['p3.body'], backButton(ctx, texts));
  const form = view.querySelector('form');
  const active = () => current() && form.isConnected !== false;
  const button = form.querySelector('button[type="submit"]');
  const options = form.querySelector('fieldset');
  let busy = false;
  form.addEventListener('change', event => {
    if (busy || event.target.name !== 'goal') return;
    selected = session.goals.find(goal => goal.id === event.target.value)?.id ?? null;
    button.disabled = selected === null;
    view.querySelector('[data-patient-choose]').hidden = selected !== null;
  });
  view.querySelector('[data-patient-back]').addEventListener('click', () => ctx.go(patientPath(token, 'step')));
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || selected === null) return;
    busy = true;
    button.disabled = true;
    button.textContent = texts['p3.pending'];
    options.disabled = true;
    form.setAttribute('aria-busy', 'true');
    try {
      const response = await ctx.api('POST', '/patient/choice', { branch_code: branch, goal_id: selected });
      if (!active()) return;
      if (response.ok !== true) throw new Error('choice_not_saved');
      chooseGoal(token, selected);
      ctx.go(patientPath(token, 'next'));
    } catch {
      if (active()) showFeedback(view, ctx, texts['p3.error']);
    } finally {
      if (active()) {
        busy = false;
        button.disabled = selected === null;
        button.textContent = texts['p3.action'];
        options.disabled = false;
        form.removeAttribute('aria-busy');
      }
    }
  });
}
