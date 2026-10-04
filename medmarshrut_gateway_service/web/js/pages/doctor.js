import { DEMO, NEXT, SERVICES, partnerOnly } from '../demo-data.js';
import { awaitingOutcome, ep, live, slotLine, stepOf, studyOf, title } from '../domain.js';
import { state } from '../state.js';
import { badge, btn, lc, modalHead, openModal, safe } from '../ui.js';

/* =====================================================================
   Экраны врача (снимки — в imaging-ui.js)
   ===================================================================== */
export function doctor(){
  const visits = state.episodes.flatMap(e => e.steps.filter(s => s.status === 'confirmed' && s.slot && !s.slot.partner).map(s => [e, s]));
  const today = visits.filter(([, s]) => s.slot.date === 'Сегодня'), later = visits.filter(([, s]) => s.slot.date !== 'Сегодня');
  const out = awaitingOutcome();
  const why = e => { const st = e.kind === 'imaging' ? studyOf(e) : null; if (!st) return 'Со слов пациента: ' + safe(state.symptoms || 'не указано'); const f = DEMO[st.kind].findings[0]; return `${DEMO[st.kind].title}: ${f ? lc(f.label) + ', ' + f.place : 'изменений не выявлено'}`; };
  const card = ([e, s], tag, tone) => `<div class="card">${badge(tag, tone)}<h3 style="margin-top:13px">${safe(e.patient)}</h3><p>${safe(title(s))}, ${safe(lc(slotLine(s.slot)))}<br>${why(e)}</p><div class="actions"><button class="btn secondary small" data-case="${safe(e.id)}">Открыть карточку</button>${btn('Итог приёма', 'planOpen', 'small', {id:e.id, step:s.id})}</div></div>`;
  return `<div class="pagehead"><div><div class="eyebrow">Перед приёмом и после него</div><h1>Мои пациенты</h1><p>Перед приёмом врач видит заключение и то, что уже сделано. После приёма вносит итог, и план пациента обновляется.</p></div></div>
    <div class="sectionhead" style="margin-top:0"><h2>Ждут итога приёма</h2></div>
    ${out.length ? `<div class="grid two">${out.map(x => card(x, 'Визит состоялся: нужен итог', 'orange')).join('')}</div>` : '<div class="note">Итоги по всем состоявшимся визитам внесены.</div>'}
    <div class="sectionhead"><h2>Сегодня на приёме</h2></div>
    ${today.length ? `<div class="grid two">${today.map(x => card(x, 'Сегодня, ' + x[1].slot.time, 'blue')).join('')}</div>` : '<div class="note">На сегодня записей нет.</div>'}
    ${later.length ? `<div class="sectionhead"><h2>Ближайшие дни</h2></div><div class="grid two">${later.map(x => card(x, slotLine(x[1].slot), 'gray')).join('')}</div>` : ''}
    <div class="note" style="margin-top:18px">В рабочем продукте этот экран может быть частью медицинской информационной системы клиники.</div>`;
}
export function planModal(id, stepId){
  const e = ep(id), s = stepId ? stepOf(e, stepId) : null;
  const taken = e.steps.filter(live).map(x => x.service);
  const opts = (NEXT[e.ruleId] || NEXT.own).filter(o => !taken.includes(o[0]) || (s && o[0] === s.service));
  const summary = {'XR-INF':'Осмотр, аускультация. Назначено лечение и контроль.', 'CT-NOD':'Очаг без признаков роста, наблюдение.', 'MG-ADD':'Осмотр, направлена на дообследование.', 'MR-MEN':'Осмотр колена, консервативное лечение.'}[e.ruleId] || 'Осмотр, даны рекомендации.';
  openModal(`${modalHead(s ? 'Итог приёма' : 'План врача', safe(e.patient))}
    ${s ? `<p>${safe(title(s))} · ${safe(lc(slotLine(s.slot)))}</p><div class="field"><label for="outSummary">Краткий итог</label><textarea id="outSummary" style="min-height:74px">${summary}</textarea></div>` : `<p>${safe(e.title)}. Шаги увидят пациент и координатор.</p>`}
    <div class="field" style="margin-top:14px"><label>Следующие шаги</label>${opts.map(([sv, due, on]) => `<label class="checkline" style="margin-bottom:8px"><input type="checkbox" data-next="${safe(sv)}" ${on ? 'checked' : ''}><span><strong>${SERVICES[sv].title}</strong><br><span class="muted">${due}${partnerOnly(sv) ? ' · клиника-партнёр' : ''}</span></span></label>`).join('') || '<p style="margin:0">Все подходящие шаги уже есть в плане.</p>'}</div>
    ${s ? `<label class="checkline" style="margin-top:6px"><input type="checkbox" id="outRx" ${e.ruleId === 'XR-INF' ? 'checked' : ''}><span><strong>Выписать электронный рецепт</strong><br><span class="muted">Пациент увидит его в разделе «Аптека» и забронирует препараты в аптеке-партнёре</span></span></label>` : ''}
    <div class="note" style="margin-top:14px">Новые шаги появляются только после решения врача. Маршрутизатор сам план не меняет.</div>
    <div class="actions">${btn('Сохранить', 'planSave', '', {id, step:stepId || ''})}${btn('Отмена', 'close', 'secondary')}</div>`, true);
}
