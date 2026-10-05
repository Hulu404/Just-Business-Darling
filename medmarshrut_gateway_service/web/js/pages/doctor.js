/* План врача и итог приёма из прежнего каркаса (экраны врача — в кабинете rescan) */
import { NEXT, SERVICES, partnerOnly } from '../demo-data.js';
import { ep, live, slotLine, stepOf, title } from '../domain.js';
import { btn, lc, modalHead, openModal, safe } from '../ui.js';

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
