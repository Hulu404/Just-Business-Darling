import { loadPatient, page, contact, feedback, showFeedback } from './patient-common.js';
import { patientPath } from './patient-state.js';

export async function render(view, ctx) {
  const data = await loadPatient(view, ctx, true);
  if (!data) return;
  const { session, token, texts, current } = data;
  if (session.state !== 'active') {
    const known = ['expired', 'stopped', 'unsubscribed'].includes(session.state);
    const title = known ? texts[`p1.${session.state}.title`] : ctx.texts.error.title;
    const body = known ? texts[`p1.${session.state}.body`] : ctx.texts.error.body;
    page(view, ctx, title, `<div class="card patient-card"><p>${ctx.safe(body)}</p>${contact(ctx, texts, session.clinic)}</div>`);
    return;
  }
  const consent = session.consent_required !== false;
  const prefix = consent ? 'p1.consent' : 'p1.active';
  const privacy = session.clinic.privacy_url;
  const policy = typeof privacy === 'string' && /^(?:https?:\/\/|\/(?!\/))[^\s\\]+$/i.test(privacy)
    ? `<a href="${ctx.safe(privacy)}">${ctx.safe(texts['p1.consent.policy_link'])}</a>` : '';
  page(view, ctx, texts[`${prefix}.title`], `<form class="card patient-card" data-patient-entry>
    <p>${ctx.safe(texts[`${prefix}.body`])}</p>
    ${consent ? `<p class="patient-muted">${ctx.safe(texts['p1.consent.revoke'])}</p>${policy}` : ''}
    ${feedback()}<button class="btn" type="submit">${ctx.safe(texts[`${prefix}.action`])}</button>
    ${consent ? '' : `<p class="note">${ctx.safe(texts['p1.active.privacy'])}</p>`}</form>`);
  const form = view.querySelector('form');
  const active = () => current() && form.isConnected !== false;
  const button = form.querySelector('button');
  let busy = false;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    if (!consent) { ctx.go(patientPath(token, 'step')); return; }
    busy = true;
    button.disabled = true;
    button.textContent = texts['p1.consent.pending'];
    form.setAttribute('aria-busy', 'true');
    try {
      const response = await ctx.api('POST', '/patient/consent');
      if (!active()) return;
      if (response.ok !== true) throw new Error('consent_not_saved');
      ctx.go(patientPath(token, 'step'));
    } catch {
      if (active()) showFeedback(view, ctx, texts['p1.consent.error']);
    } finally {
      if (active()) {
        busy = false;
        button.disabled = false;
        button.textContent = texts['p1.consent.action'];
        form.removeAttribute('aria-busy');
      }
    }
  });
}
