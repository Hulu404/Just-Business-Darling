import { DEMO, NEXT, SCHEME, SERVICES, partnerOnly } from '../demo-data.js';
import { awaitingOutcome, ep, highlight, live, slotLine, stepOf, studyOf, title } from '../domain.js';
import { nextStepLabel } from './staff.js';
import { state } from '../state.js';
import { badge, btn, lc, modalHead, navBtn, openModal, plural, safe } from '../ui.js';

/* =====================================================================
   Экраны врача и карта сервисов
   ===================================================================== */
export const studyBadge = st => ({processing:badge('Обрабатывается', 'blue'), awaiting:badge('Ждёт проверки', 'orange'), confirmed:badge('Подтверждено врачом'), manual:badge('Ручное описание', 'gray')}[st.status]);
export const aiSummary = st => { const f = DEMO[st.kind].findings[0]; return f ? `ИИ: ${lc(f.label)}, ${safe(f.place)}. Оценка модели ${safe(f.conf)}` : 'ИИ: находок выше порога нет'; };

export function reading(){
  const wait = state.studies.filter(s => s.status === 'awaiting');
  const done = state.studies.filter(s => s.status === 'confirmed');
  return `<div class="pagehead"><div><div class="eyebrow">Сервис «Что на снимке?»</div><h1>Черновики ИИ на проверку</h1><p>ИИ готовит черновик заключения, врач его подтверждает. До этого ни пациент, ни координатор результата не видят.</p></div></div>
    <div class="grid three" style="margin-bottom:18px"><div class="card"><div class="metric">${wait.length}</div><span class="muted">${plural(wait.length, ['ждёт', 'ждут', 'ждут'])} проверки</span></div><div class="card"><div class="metric">${done.length}</div><span class="muted">подтверждено</span></div><div class="card"><div class="metric">${done.filter(s => s.edited).length}</div><span class="muted">черновиков исправлено врачом</span></div></div>
    <div class="sectionhead" style="margin-top:8px"><h2>Ждут проверки</h2></div>
    ${wait.length ? `<div class="grid two">${wait.map(st => `<div class="card">${studyBadge(st)}<h3 style="margin-top:13px">${safe(st.patient)}</h3><p>${DEMO[st.kind].title} · ${lc(safe(st.date))}<br>${safe(aiSummary(st))}</p><div class="actions">${btn('Открыть снимок', 'studyOpen', 'small', {id:st.id})}</div></div>`).join('')}</div>` : '<div class="panel empty"><h3>Всё проверено</h3><p>Новые исследования появятся здесь, когда придут из РИС или от пациента.</p></div>'}
    <div class="sectionhead"><h2>Подтверждённые</h2></div>
    <div class="tablewrap"><table><thead><tr><th>Пациент</th><th>Исследование</th><th>Находка</th><th>Что дальше</th><th></th></tr></thead><tbody>
      ${done.map(st => { const e = st.episodeId && ep(st.episodeId); return `<tr><td><strong>${safe(st.patient)}</strong></td><td>${DEMO[st.kind].title}<small>${safe(st.date)}</small></td><td>${DEMO[st.kind].findings[0] ? DEMO[st.kind].findings[0].label : 'Изменений не выявлено'}${st.edited ? '<small>черновик исправлен</small>' : ''}</td><td>${e ? safe(nextStepLabel(e)) : 'Маршрут не нужен'}</td><td>${btn('Открыть', 'studyOpen', 'secondary small', {id:st.id})}</td></tr>`; }).join('')}
    </tbody></table></div>`;
}

export function study(){
  const st = state.studies.find(x => x.id === state.sel.study) || state.studies[0];
  const d = DEMO[st.kind], f = d.findings[0];
  const canEdit = state.role === 'doctor' && st.status === 'awaiting';
  const e = st.episodeId && ep(st.episodeId);
  const back = state.role === 'doctor' ? navBtn('← К списку', 'reading', 'secondary') : state.role === 'staff' ? (e ? `<button class="btn secondary" data-case="${safe(e.id)}">← К обращению</button>` : navBtn('← К обращениям', 'inbox', 'secondary')) : navBtn('← Назад', 'imaging', 'secondary');
  const under = d.scheme === 'ct' && f
    ? `<input type="range" id="slice" min="130" max="154" value="142" aria-label="Номер среза"><div class="cap"><span id="sliceLabel">Срез 142 из 310</span><span>Находка на срезах 139–145</span></div><div class="cap"><span>${d.files}</span><span>Схема, не медицинское изображение</span></div>`
    : `<div class="cap"><span>${d.files}</span><span>Схема, не медицинское изображение</span></div>`;
  const text = st.status === 'confirmed' ? st.conclusion : d.draft;
  return `<div class="pagehead"><div><div class="eyebrow">Сервис «Что на снимке?»</div><h1>${safe(st.patient)}</h1><p>${d.title} · ${lc(safe(st.date))} · ${safe(st.source)}</p></div><div class="actions">${studyBadge(st)}${back}</div></div>
    <div class="twocol study"><div class="stack"><div class="viewer">${SCHEME[d.scheme](!!f, f ? f.conf : '')}${under}</div>
        <div class="note">Модель отмечает только те находки, на которые её проверяли. ${d.modality === 'mg' ? 'Категорию BI-RADS сервис не присваивает: её указывает врач.' : 'Если протокол или область не подходят модели, исследование сразу уходит на ручное описание.'}</div></div>
      <div class="stack"><div class="panel"><h3>Находки ИИ</h3>
          ${d.findings.length ? d.findings.map(x => `<div class="finding"><span class="dot now"></span><span><strong>${safe(x.label)}</strong><small>${safe(x.place)}</small><small>Оценка модели: ${safe(x.conf)}</small></span></div>`).join('') : '<p>Находок выше порога нет. Такое исследование всё равно смотрит врач.</p>'}
          <dl class="kv" style="margin-top:14px"><dt>Черновик готовил</dt><dd>${st.uploaded ? 'ИИ-модель сервиса, снимок загрузил пациент' : 'ИИ-сервис «Третье мнение», демо-интеграция'}</dd><dt>Файлы</dt><dd>${d.files}${st.file ? ' · ' + safe(st.file) : ''}</dd><dt>Проверка DICOM</dt><dd>Серия полная, протокол подходит модели</dd></dl></div>
        <div class="panel"><h3>${canEdit ? 'Черновик заключения' : 'Заключение'}</h3>
          ${canEdit ? `<div class="field"><textarea id="draft" style="min-height:190px" aria-label="Текст заключения">${safe(d.draft)}</textarea><small>Каждая фраза черновика построена из находки ИИ. Правьте текст как обычно: дальше пойдёт только то, что вы подтвердите.</small></div><div class="actions">${btn('Подтвердить заключение', 'studyConfirm', '', {id:st.id})}${btn('Описать без ИИ', 'studyManual', 'secondary', {id:st.id})}</div>`
            : st.status === 'confirmed' ? `<div class="quote">${highlight(text)}</div><p style="margin:12px 0 0">${safe(st.confirmedBy)}, подтверждено ${safe(st.confirmedAt)}${st.edited ? ' · черновик ИИ исправлен' : ''}</p>${e && state.role !== 'patient' ? `<div class="actions"><button class="btn secondary small" data-case="${safe(e.id)}">Открыть обращение</button></div>` : st.noRoute ? '<p style="margin:10px 0 0">Маршрут не нужен: пациент получил результат и напоминание через 12 месяцев.</p>' : ''}`
            : `<p style="margin:0">${st.status === 'manual' ? 'Врач описывает исследование без черновика ИИ.' : 'Заключение появится после проверки врачом.'}</p>`}
        </div></div></div>`;
}

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

