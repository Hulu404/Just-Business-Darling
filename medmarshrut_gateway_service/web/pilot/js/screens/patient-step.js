import { loadPatient, page, contact } from './patient-common.js';
import { patientPath, chooseBranch, selectedBranch, doctorStepText } from './patient-state.js';

export async function render(view, ctx) {
  const data = await loadPatient(view, ctx);
  if (!data) return;
  const { session, token, texts } = data;
  const step = session.doctor_step;
  if (step) {
    const template = doctorStepText(session);
    if (!template) {
      page(view, ctx, ctx.texts.error.title, `<div class="card patient-card"><p>${ctx.safe(ctx.texts.error.body)}</p>${contact(ctx, texts, session.clinic)}</div>`);
      return;
    }
    chooseBranch(token, null);
    const author = step.doctor_name ? `<div class="patient-author"><p class="patient-eyebrow patient-muted">${ctx.safe(texts['p2.doctor.label'])}</p>
      <p class="patient-doctor">${ctx.safe(step.doctor_name)}</p></div>` : '';
    page(view, ctx, template, `<div class="card patient-card">
      <p>${ctx.safe(texts[`p2.${step.code}.body`])}</p>
      <button type="button" class="btn" data-patient-next>${ctx.safe(texts['p2.step.action'])}</button></div>`, '', author);
    view.querySelector('[data-patient-next]').addEventListener('click', () => ctx.go(patientPath(token, 'goal')));
  } else {
    let selected = selectedBranch(token, session);
    page(view, ctx, texts['p2.branches.title'], `<form class="patient-form">
      <fieldset class="patient-options"><legend class="sr-only">${ctx.safe(texts['p2.branches.title'])}</legend>
      ${session.branches.map((branch, index) => `<label class="card patient-option">
        <input type="radio" name="branch" value="${ctx.safe(branch.code)}" ${selected === branch.code ? 'checked' : ''} required aria-describedby="branch-hint-${index}">
        <span><span class="patient-option-title">${ctx.safe(branch.title)}</span>
        <span class="patient-muted patient-option-hint" id="branch-hint-${index}">${ctx.safe(branch.hint)}</span></span></label>`).join('')}</fieldset>
      <button type="submit" class="btn" ${selected === null ? 'disabled' : ''}>${ctx.safe(texts['p2.branches.action'])}</button>
      <p class="patient-muted patient-small" data-patient-choose ${selected === null ? '' : 'hidden'}>${ctx.safe(texts['p2.branches.choose'])}</p></form>`, texts['p2.branches.body']);
    const form = view.querySelector('form');
    const button = form.querySelector('button[type="submit"]');
    form.addEventListener('change', event => {
      if (event.target.name !== 'branch') return;
      selected = session.branches.find(branch => branch.code === event.target.value)?.code ?? null;
      button.disabled = selected === null;
      view.querySelector('[data-patient-choose]').hidden = selected !== null;
    });
    form.addEventListener('submit', event => {
      event.preventDefault();
      if (selected === null) return;
      chooseBranch(token, selected);
      ctx.go(patientPath(token, 'goal'));
    });
  }
}
