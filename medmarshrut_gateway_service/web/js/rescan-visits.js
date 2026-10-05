/* Кабинет rescan, раздел «Приёмы» (задание 12, цикл 6): визиты пациентов из сервиса пути, место и специалист записи,
   календарь месяца и итог приёма. Визит отмечает координатор, итог вносит врач: без итога пациент не получит следующий шаг. */
import { api } from './api.js';
import { k, empty, head, load, redraw, rs, stateOf } from './rescan-ui.js';
import { state, ui } from './state.js';
import { $, safe, toast } from './ui.js';
import { candidates, chosenSteps, freshForm, stepFields } from './rescan-plan.js';

const enc = encodeURIComponent;
const fmt = value => { if (!value) return ''; const d = new Date(value); return Number.isNaN(+d) ? String(value) : new Intl.DateTimeFormat('ru-RU', {day:'numeric', month:'long', hour:'2-digit', minute:'2-digit'}).format(d); };
const initials = name => String(name || '').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('') || '?';
const FORMATS = {in_person:'очно', online:'онлайн', telemedicine:'онлайн'};

/* Форма итога: {id, step, event, at, summary, checked:[индексы], custom, kind, busy} — переживает перерисовку */
export function visitNeeds(timer){ return timer && ui.rsOutcome ? [] : ['visits', 'catalog', 'rules']; }

const stepOf = v => v.episode.steps.find(s => s.id === v.step_id) || {};
/* Сначала ждущие итога, затем по времени записи */
const ordered = list => [...list].sort((a, b) => (stepOf(b).status === 'attended') - (stepOf(a).status === 'attended')
  || String(stepOf(a).appointment_at || '').localeCompare(String(stepOf(b).appointment_at || '')));

function place(v){
  const a = v.appointment;
  /* Записи нет в слотах клиники: у партнёра или внесена без слота. Место не выдумываем */
  if (!a) return '<span>Место не указано</span><small style="font-size:11px;color:var(--c-fg3)">запись не через расписание клиники</small>';
  return `<span>${safe(a.place || 'Место не указано')}</span><small style="font-size:11px;color:var(--c-fg3)">${safe([a.specialist, FORMATS[a.format] || a.format].filter(Boolean).join(' · '))}</small>`;
}
function row(v){
  const s = stepOf(v), waiting = s.status === 'attended', open = ui.rsOutcome && ui.rsOutcome.id === v.episode.id && ui.rsOutcome.step === s.id;
  return `<tr${waiting ? ' class="live"' : ''} data-episode="${safe(v.episode.id)}" data-step="${safe(s.id)}">
    <td><div class="c-pp"><span class="c-av" style="display:grid;place-items:center;font-weight:600;color:var(--c-blue)">${safe(initials(v.episode.patient))}</span><span><b>${safe(v.episode.patient)}</b><small>${safe(v.episode.title)}</small></span></div></td>
    <td style="white-space:normal;min-width:160px">${safe(s.description)}</td><td style="white-space:normal;min-width:110px">${safe(fmt(s.appointment_at)) || '—'}</td>
    <td style="white-space:normal;min-width:140px"><span style="display:flex;flex-direction:column;font-size:13px">${place(v)}</span></td>
    <td><span style="display:flex;flex-direction:column;align-items:flex-start;gap:6px"><span class="c-s ${waiting ? 'amber' : 'blue'}">${waiting ? 'Пришёл, ждёт итога' : 'Записан'}</span>
      <button class="c-btn ${open ? '' : 'gh '}sm" type="button" data-action="rsOutcomeOpen" data-id="${safe(v.episode.id)}" data-step="${safe(s.id)}">Итог приёма</button></span></td></tr>`;
}

/* Календарь текущего месяца: дни с визитами, сегодняшний день — синим */
function calendar(list){
  const now = new Date(), y = now.getFullYear(), m = now.getMonth();
  const days = new Set(list.map(v => new Date(stepOf(v).appointment_at)).filter(d => !Number.isNaN(+d) && d.getFullYear() === y && d.getMonth() === m).map(d => d.getDate()));
  const lead = (new Date(y, m, 1).getDay() + 6) % 7, total = new Date(y, m + 1, 0).getDate();
  let cells = ['П', 'В', 'С', 'Ч', 'П', 'С', 'В'].map(x => `<span class="h">${x}</span>`).join('') + '<span></span>'.repeat(lead);
  for (let d = 1; d <= total; d++){
    const today = d === now.getDate();
    cells += `<span class="${days.has(d) ? 'ev' : ''}"${today ? ' style="background:#1866A0;color:#fff"' : ''}${days.has(d) ? ' title="Есть приёмы"' : ''}>${d}</span>`;
  }
  const title = new Intl.DateTimeFormat('ru-RU', {month:'long', year:'numeric'}).format(now).replace(' г.', '');
  return `<div class="c-card"><div class="c-ch"><span class="c-hdr" style="gap:10px"><span class="ic" style="width:36px;height:36px">${k('cal', 18)}</span><b style="font-size:16px">${safe(title.charAt(0).toUpperCase() + title.slice(1))}</b></span></div>
    <div class="c-cal">${cells}</div><div class="c-demo">Отмечены дни с приёмами ваших пациентов.</div></div>`;
}

function outcomeCard(list){
  const f = ui.rsOutcome;
  const v = f && list.find(x => x.episode.id === f.id && stepOf(x).id === f.step);
  if (!v) return '';
  const s = stepOf(v), items = candidates(v.episode);
  return `<div class="c-card c-dec" id="rsOutcome"><div class="c-ch"><span><h2>Итог приёма</h2><span class="sub">${safe(v.episode.patient)} · ${safe(s.description)}${s.appointment_at ? ' · ' + safe(fmt(s.appointment_at)) : ''}</span></span></div>
    <div class="c-fld"><label for="rsOutSummary">Краткий итог</label><textarea id="rsOutSummary" maxlength="1000" style="min-height:90px;border:1.5px solid transparent;border-radius:12px;padding:10px 12px;font:inherit;font-size:13px;resize:vertical;background:var(--c-main);color:var(--c-fg)">${safe(f.summary)}</textarea></div>
    ${stepFields(f, items, 'rsOut')}
    <div class="c-act"><button class="c-btn" type="button" data-action="rsOutcomeSave"${f.busy ? ' disabled' : ''}>${k('check', 16, 2.2)}${f.busy ? 'Сохраняем…' : 'Сохранить итог'}</button><button class="c-btn gh" type="button" data-action="rsOutcomeClose">Отмена</button></div>
    <span class="c-demo">Новые шаги появляются у пациента только после вашего решения.</span></div>`;
}

export function rsVisits(){
  return head('Приёмы', 'Куда записались ваши пациенты. Визит отмечает координатор, итог приёма вносите вы') +
    stateOf('visits', raw => {
      const list = ordered(raw);
      const table = list.length ? `<div class="c-tw"><table class="c-tbl"><thead><tr><th>Пациент</th><th>Шаг</th><th>Дата</th><th>Место</th><th>Статус</th></tr></thead><tbody>${list.map(row).join('')}</tbody></table></div>`
        : empty('Записей нет', 'Когда пациент или координатор запишет пациента, визит появится здесь.');
      /* Таблица на всю ширину: пять колонок и кнопка не помещаются рядом с календарём. Форма итога и календарь — под ней */
      const form = outcomeCard(list);
      return `<div class="c-card" style="padding:10px">${table}</div>${form ? `<div class="c-grid">${form}${calendar(list)}</div>` : `<div class="c-grid"><div class="c-card"><div class="c-ch"><span><h2>Итог приёма</h2><span class="sub">после визита</span></span></div><span style="font-size:13px;color:var(--c-fg2)">Когда пациент пришёл, нажмите «Итог приёма» в его строке: опишите приём и выберите следующие шаги. Без итога пациент не получит следующий шаг.</span></div>${calendar(list)}</div>`}`;
    });
}

export function installVisitActions(ACTIONS){
  ACTIONS.rsOutcomeOpen = d => {
    const v = (rs.visits?.data || []).find(x => x.episode.id === d.id && x.step_id === d.step);
    if (!v) return toast('Визит не найден. Обновите страницу.');
    ui.rsOutcome = {id:d.id, step:d.step, event:crypto.randomUUID(), summary:'', ...freshForm(candidates(v.episode))};
    redraw();
    const card = $('#rsOutcome');
    if (card) card.scrollIntoView({block:'nearest'});
  };
  ACTIONS.rsOutcomeClose = () => { ui.rsOutcome = null; redraw(); load('visits'); };
  ACTIONS.rsOutcomeSave = async () => {
    const f = ui.rsOutcome, v = f && (rs.visits?.data || []).find(x => x.episode.id === f.id && x.step_id === f.step);
    if (!v || f.busy) return;
    if (!f.summary.trim()) return toast('Напишите краткий итог приёма.');
    const next = chosenSteps(f, candidates(v.episode), true);
    f.busy = true; redraw();
    try {
      await api('POST', `/api/doctor/episodes/${enc(f.id)}/steps/${enc(f.step)}/outcome`, {role:'doctor', body:{event_id:f.event, summary:f.summary.trim(), next_steps:next}});
    } catch (err){ f.busy = false; redraw(); toast(err.message); return; }  // текст итога остаётся в форме
    ui.rsOutcome = null;
    toast(next.length ? 'Итог сохранён. Пациент видит следующий шаг' : 'Итог сохранён');
    await load('visits');
  };
  const field = (e, fn) => { if (ui.rsOutcome && state.page === 'rsVisits') fn(ui.rsOutcome, e.target); };
  document.addEventListener('input', e => {
    if (e.target.id === 'rsOutSummary') field(e, (f, t) => { f.summary = t.value; });
    if (e.target.id === 'rsOutCustom') field(e, (f, t) => { f.custom = t.value; });
  });
  document.addEventListener('change', e => {
    if (e.target.id === 'rsOutKind') field(e, (f, t) => { f.kind = t.value; });
    if (e.target.dataset && e.target.dataset.stepOf === 'rsOut') field(e, (f, t) => {
      const i = Number(t.dataset.stepIndex);
      f.checked = t.checked ? [...new Set([...f.checked, i])] : f.checked.filter(x => x !== i);
    });
  });
}
