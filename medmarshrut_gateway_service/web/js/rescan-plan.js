/* Кабинет rescan: план врача (задание 12, цикл 7). «Назначить план» — для обращения на ручном разборе (manual-plan),
   «Изменить план» — для активного или отложенного (revise-plan). Шаги — из каталога клиники, как в path-extra.js:
   у шага не из каталога нет слотов, и пациент не запишется сам. Форма — карточка, черновик живёт в ui.rsPlan. */
import { api } from './api.js';
import { k, load, redraw, rs } from './rescan-ui.js';
import { state, ui } from './state.js';
import { safe, toast } from './ui.js';

const enc = encodeURIComponent;
const KINDS = [['appointment', 'Приём'], ['test', 'Исследование'], ['follow_up', 'Наблюдение'], ['care_coordination', 'Помощь координатора']];
const field = 'border:1.5px solid transparent;border-radius:12px;font:inherit;font-size:14px;background:var(--c-main);color:var(--c-fg)';

/* Шаги-кандидаты: черновик неутверждённого правила или продолжения из каталога по коду находки */
export function candidates(e){
  const report = e.source_report || {};
  const rule = (rs.rules?.data?.rules || []).find(r => r.study_type === report.study_type && r.anatomy === report.anatomy
    && r.protocol_name === report.protocol_name && r.finding_code === report.finding_code);
  if (rule && !rule.approved) return rule.steps.map(s => ({...s, checked:true}));
  const services = new Map((rs.catalog?.data?.services || []).map(s => [s.code, s]));
  return (rs.catalog?.data?.followups || []).filter(f => f.finding_code === report.finding_code).map(f => ({
    kind:services.get(f.service_code)?.kind || 'appointment', description:services.get(f.service_code)?.title || f.service_code,
    checked:f.is_default, due_days:f.due_days, due_note:f.due_note}));
}
/* Шаги из формы: отмеченные кандидаты и свой шаг. due_at — от момента открытия формы, если в каталоге есть срок */
export function chosenSteps(f, items, withDue){
  const steps = f.checked.map(i => items[i]).filter(Boolean);
  if (f.custom.trim()) steps.push({kind:f.kind, description:f.custom.trim()});
  return steps.map(s => withDue ? {kind:s.kind, description:s.description,
    due_at:Number.isInteger(s.due_days) ? new Date(Date.parse(f.at) + s.due_days * 86400000).toISOString() : null}
    : {kind:s.kind, description:s.description});
}
/* Поля «шаги из каталога, свой шаг, вид шага» — общие для итога приёма и плана врача */
export function stepFields(f, items, prefix){
  const rows = items.map((c, i) => `<label class="c-kv" style="justify-content:flex-start;gap:10px;cursor:pointer"><input type="checkbox" data-step-of="${prefix}" data-step-index="${i}"${f.checked.includes(i) ? ' checked' : ''}><span style="max-width:none;flex-shrink:1;display:flex;flex-direction:column"><span>${safe(c.description)}</span>${c.due_note ? `<small style="font-weight:400;color:var(--c-fg2)">${safe(c.due_note)}</small>` : ''}</span></label>`).join('');
  return `<div class="c-fld"><label>Следующие шаги</label><div class="c-kvs">${rows || '<span class="c-demo">Подходящих шагов в каталоге нет. Добавьте свой шаг ниже.</span>'}</div></div>
    <div class="c-fld"><label for="${prefix}Custom">Свой шаг, если нужен</label><input id="${prefix}Custom" maxlength="500" value="${safe(f.custom)}" style="height:44px;padding:0 14px;${field}"></div>
    <div class="c-fld"><label for="${prefix}Kind">Вид своего шага</label><select id="${prefix}Kind">${KINDS.map(([value, label]) => `<option value="${value}"${f.kind === value ? ' selected' : ''}>${label}</option>`).join('')}</select></div>
    <span class="c-demo">Шаг не из каталога пациент увидит, но записаться на него сам не сможет: время подберёт координатор.</span>`;
}
export const freshForm = items => ({at:new Date().toISOString(), custom:'', kind:'appointment', busy:false,
                                     checked:items.map((c, i) => c.checked ? i : -1).filter(i => i >= 0)});

/* Кнопка под карточкой обращения: только для статусов, где план врача что-то меняет */
export function planButton(e){
  if (!e) return '';
  if (e.status === 'manual_review') return `<button class="c-btn" type="button" data-action="rsPlanOpen" data-id="${safe(e.id)}" data-mode="manual">Назначить план</button>`;
  if (['active', 'paused'].includes(e.status)) return `<button class="c-btn gh" type="button" data-action="rsPlanOpen" data-id="${safe(e.id)}" data-mode="revise">Изменить план</button>`;
  return '';
}
const episodeOf = id => (rs.episodes?.data || []).find(e => e.id === id);
export function planCard(e){
  const f = ui.rsPlan;
  if (!f || !e || f.id !== e.id) return '';
  const items = candidates(e), manual = f.mode === 'manual';
  return `<div class="c-card c-dec" id="rsPlan" style="background:var(--c-pill)"><div class="c-ch"><span><h2>${manual ? 'План врача' : 'Изменить план'}</h2><span class="sub">${safe(e.patient)} · ${safe(e.title)}</span></span></div>
    ${e.reason ? `<div class="c-next"><span>${manual ? 'Почему нужен план' : 'Причина'}</span><b>${safe(e.reason)}</b></div>` : ''}
    ${manual ? '' : `<div class="c-fld"><label for="rsPlanReason">Почему меняется план</label><input id="rsPlanReason" maxlength="500" value="${safe(f.reason)}" style="height:44px;padding:0 14px;${field}"></div>`}
    ${stepFields(f, items, 'rsPlan')}
    <div class="c-act"><button class="c-btn" type="button" data-action="rsPlanSave"${f.busy ? ' disabled' : ''}>${k('check', 16, 2.2)}${f.busy ? 'Сохраняем…' : 'Сохранить план'}</button><button class="c-btn gh" type="button" data-action="rsPlanClose">Отмена</button></div>
    <span class="c-demo">Пациент и координатор увидят новые шаги сразу после сохранения.</span></div>`;
}

export function installPlanActions(ACTIONS){
  ACTIONS.rsPlanOpen = d => {
    const e = episodeOf(d.id);
    if (!e) return toast('Обращение не найдено. Обновите страницу.');
    ui.rsPlan = {id:d.id, mode:d.mode, reason:'', ...freshForm(candidates(e))};
    redraw();
    document.getElementById('rsPlan')?.scrollIntoView({block:'nearest'});
  };
  ACTIONS.rsPlanClose = () => { ui.rsPlan = null; redraw(); };
  ACTIONS.rsPlanSave = async () => {
    const f = ui.rsPlan, e = f && episodeOf(f.id);
    if (!e || f.busy) return;
    const manual = f.mode === 'manual';
    const steps = chosenSteps(f, candidates(e), !manual);
    if (!steps.length) return toast('Отметьте шаг из каталога или напишите свой.');
    if (!manual && !f.reason.trim()) return toast('Напишите, почему меняется план.');
    f.busy = true; redraw();
    try {
      await api('POST', `/api/doctor/episodes/${enc(e.id)}/${manual ? 'manual-plan' : 'revise-plan'}`,
                {role:'doctor', body:manual ? {steps} : {reason:f.reason.trim(), steps}});
    } catch (err){ f.busy = false; redraw(); toast(err.message); return; }  // черновик остаётся в форме
    ui.rsPlan = null;
    toast('План сохранён. Пациент видит новые шаги');
    await Promise.all([load('episodes'), load('studies')]);
  };
  const edit = fn => { if (ui.rsPlan) fn(ui.rsPlan); };
  document.addEventListener('input', e => {
    if (e.target.id === 'rsPlanCustom') edit(f => { f.custom = e.target.value; });
    if (e.target.id === 'rsPlanReason') edit(f => { f.reason = e.target.value; });
  });
  document.addEventListener('change', e => {
    if (e.target.id === 'rsPlanKind') edit(f => { f.kind = e.target.value; });
    if (e.target.dataset && e.target.dataset.stepOf === 'rsPlan') edit(f => {
      const i = Number(e.target.dataset.stepIndex);
      f.checked = e.target.checked ? [...new Set([...f.checked, i])] : f.checked.filter(x => x !== i);
    });
  });
}
export const planOpen = () => !!ui.rsPlan && (state.page === 'rsPatients' || state.page === 'rsStudies');
