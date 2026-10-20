// Only the current tab remembers a choice. The session API owns consent and access.
const choices = new Map();
const renders = new WeakMap();

export function choiceFor(token) {
  return { ...(choices.get(token) || { branch_code: null, goal_id: null }) };
}

export function chooseBranch(token, branch) {
  const current = choiceFor(token);
  choices.set(token, { branch_code: branch, goal_id: current.branch_code === branch ? current.goal_id : null });
}

export function chooseGoal(token, goal) {
  choices.set(token, { ...choiceFor(token), goal_id: goal });
}

export function patientPath(token, screen = '') {
  return `#/p/${encodeURIComponent(token)}${screen ? `/${screen}` : ''}`;
}

export function requiresEntry(session) {
  return session.state !== 'active' || session.consent_required !== false;
}

export function selectedBranch(token, session) {
  if (session.doctor_step) return null;
  const code = choiceFor(token).branch_code;
  return session.branches.some(branch => branch.code === code) ? code : null;
}

export function formatText(template, values = {}) {
  return String(template ?? '').replace(/\{(\w+)\}/g, (placeholder, key) =>
    Object.hasOwn(values, key) ? String(values[key]) : placeholder);
}

export function doctorStepText(session) {
  const step = session.doctor_step;
  if (!step || !['discuss', 'retest', 'followup'].includes(step.code)) return null;
  if (step.code === 'retest' && (!Number.isInteger(step.retest_weeks) || step.retest_weeks < 1)) return null;
  const template = session.texts[`p2.${step.code}.title`];
  if (!template) return null;
  const n = step.retest_weeks;
  const form = n % 10 === 1 && n % 100 !== 11 ? 'one'
    : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? 'few' : 'many';
  return formatText(template, { weeks_text: formatText(session.texts[`p2.retest.weeks.${form}`], { n }) });
}

export function beginRender(view) {
  const marker = {};
  renders.set(view, marker);
  return () => renders.get(view) === marker && view.isConnected !== false;
}
