import { loadPatient, page, backButton } from './patient-common.js';
import { patientPath } from './patient-state.js';

export async function render(view, ctx) {
  const data = await loadPatient(view, ctx);
  if (!data) return;
  const { token, texts } = data;
  page(view, ctx, texts['next.title'], `<div class="card patient-card">
    <p>${ctx.safe(texts['next.body'])}</p><p class="note">${ctx.safe(texts['next.saved'])}</p>
    ${backButton(ctx, texts, 'next.back')}</div>`);
  view.querySelector('[data-patient-back]').addEventListener('click', () => ctx.go(patientPath(token, 'goal')));
}
