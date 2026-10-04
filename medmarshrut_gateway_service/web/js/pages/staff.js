import { DEMO, PHARMACIES, RULES, SERVICES, TRIGGERS, scenarios, slotsFor } from '../demo-data.js';
import { analyze, byKey, currentStep, ep, highlight, live, queueInfo, refKey, slotFull, slotLine, studyOf, title, waitingOn, whereBadge } from '../domain.js';
import { icon } from '../icons.js';
import { intake } from './patient.js';
import { staffFirstName, staffName, state } from '../state.js';
import { badge, btn, lc, modalHead, navBtn, openModal, plural, rub, safe } from '../ui.js';

/* =====================================================================
   Экраны сотрудника клиники (часть из них видит и врач)
   ===================================================================== */
export const S_STATUS = {open:['Не записан','orange'], offered:['Предложена запись','blue'], confirmed:['Записан',''], attended:['Ждёт итога врача','blue'], completed:['Выполнено','gray'], refused:['Отложен пациентом','red'], superseded:['Заменён','gray']};
export const who = f => f === 'staff' ? staffName() : 'Врач';

export function nextStepLabel(e){
  if (e.status === 'manual_review') return e.suggest && e.suggest.length ? 'Вариант: ' + e.suggest.map(sv => lc(SERVICES[sv].title)).join(' и ') : 'Нужен план врача';
  const s = currentStep(e);
  return s ? title(s) : '—';
}
export function inbox(){
  const all = state.episodes.map(e => [e, queueInfo(e)]);
  const tab = state.sel.inboxTab;
  const shown = all.filter(([, q]) => tab === 'all' || (tab === 'need' && q.need) || (tab === 'calm' && !q.need));
  const count = fn => all.filter(([e, q]) => fn(e, q)).length;
  return `<div class="pagehead"><div><div class="eyebrow">${state.role === 'doctor' ? 'Обращения клиники' : 'Рабочее место координатора'}</div><h1>Обращения</h1><p>После каждого подтверждённого заключения здесь появляется обращение с рекомендованным следующим шагом. Видно, что мешает пациенту дойти до записи.</p></div></div>
    <div class="grid four" style="margin-bottom:18px">
      <div class="card"><div class="metric">${count((e, q) => q.need)}</div><span class="muted">ждут действия</span></div>
      <div class="card"><div class="metric">${count((e, q) => q.group === 'offer')}</div><span class="muted">пациент не записан</span></div>
      <div class="card"><div class="metric">${count(e => e.status === 'manual_review') + count((e, q) => q.group === 'outcome')}</div><span class="muted">ждут решения врача</span></div>
      <div class="card"><div class="metric">${count((e, q) => q.label === 'Просрочено' || q.label === 'Отложено')}</div><span class="muted">просрочено или отложено</span></div>
    </div>
    <div class="tabs">${[['need', 'Ждут действия'], ['calm', 'Идут по плану'], ['all', 'Все']].map(([id, label]) => `<button class="tab ${tab === id ? 'active' : ''}" data-action="inboxTab" data-id="${id}">${label}</button>`).join('')}</div>
    <div class="tablewrap"><table><thead><tr><th>Пациент</th><th>Исследование или обращение</th><th>Следующий шаг</th><th>Что мешает</th><th>Статус</th><th></th></tr></thead><tbody>
      ${shown.map(([e, q]) => `<tr><td><strong>${safe(e.patient)}</strong>${e.mine ? '<small>из личного кабинета</small>' : ''}</td><td>${safe(e.title)}<small>${safe(e.opened)}</small></td><td>${safe(nextStepLabel(e))}</td><td>${safe(q.reason)}</td><td>${badge(q.label, q.tone)}</td><td><button class="btn secondary small" data-case="${safe(e.id)}">Открыть</button></td></tr>`).join('') || '<tr><td colspan="6" class="muted">В этом разделе пусто.</td></tr>'}
    </tbody></table></div>
    <div class="note" style="margin-top:17px">Тест: в режиме пациента запишитесь на приём, отложите шаг или заполните новое обращение, затем вернитесь сюда. Статус и причина изменятся.</div>`;
}

/* ---------- Карточка обращения ---------- */
export function sourceBlock(e){
  if (e.kind === 'intake'){
    return `<div class="panel"><h3>Исходные сведения</h3><div class="miniRow"><span>Описание</span><strong style="max-width:65%">${safe(state.symptoms || 'Не указано')}</strong></div><div class="miniRow"><span>Срок</span><strong>${safe(state.duration || 'Не указан')}</strong></div><div class="miniRow"><span>Документ</span><strong>${safe(state.documentName || 'Нет')}</strong></div><div class="miniRow"><span>Предпочтение</span><strong>${{private:'Платно', dms:'ДМС', oms:'ОМС'}[state.channel]}</strong></div></div>`;
  }
  const st = studyOf(e), d = DEMO[st.kind], res = analyze(st.conclusion, d.modality);
  return `<div class="panel"><h3>Заключение по исследованию</h3><p style="margin-bottom:12px">${d.title} · ${lc(safe(st.date))}</p>
    <div class="chips" style="margin-bottom:12px"><span class="chip">Черновик: <b>${st.uploaded ? 'ИИ-модель сервиса, снимок загрузил пациент' : 'ИИ-сервис «Третье мнение», демо'}</b></span><span class="chip">Подтвердил: <b>${safe(st.confirmedBy)}</b></span>${st.edited ? '<span class="chip">Черновик <b>исправлен врачом</b></span>' : ''}</div>
    <div class="quote">${highlight(st.conclusion)}</div>
    <div class="tlgroup" style="margin-top:16px">Что извлечено из текста</div><div class="chips">${res.facts.map(([k, v]) => `<span class="chip">${k}: <b>${safe(v)}</b></span>`).join('')}</div>
    <div class="actions">${btn('Открыть снимок и черновик ИИ', 'studyOpen', 'ghost small', {id:st.id})}</div></div>`;
}
export function recBlock(e){
  if (e.kind === 'intake'){
    return `<div class="panel"><h3>Предложенный маршрут</h3><p style="margin:0">${e.urgent ? 'Пациент отметил тревожный признак. Система показала экран срочного обращения.' : 'Демонстрационный вариант: первичная консультация терапевта. При необходимости маршрут меняет врач.'}</p></div>`;
  }
  if (e.status === 'manual_review'){
    const req = state.requests.find(r => r.episodeId === e.id && r.kind === 'route' && r.status === 'open');
    const has = e.suggest && e.suggest.length;
    const acts = state.role === 'doctor' ? (has ? btn('Подтвердить маршрут', 'routeOk', '', {id:e.id}) : '') + btn('Задать свой план', 'planOpen', 'secondary', {id:e.id}) : req ? btn('Открыть запрос врачу', 'reqOpen', 'secondary', {id:req.id}) : btn('Запросить решение врача', 'askDoctor', '', {id:e.id});
    return `<div class="panel"><h3>Рекомендация следующего шага</h3><div class="note warn">${safe(e.reason)}</div>${has ? `<p style="margin:14px 0 0">Вариант маршрутизатора: <strong style="color:var(--ink)">${e.suggest.map(sv => lc(SERVICES[sv].title)).join(' и ')}</strong>. Пациент увидит план только после решения врача.</p>` : ''}<div class="actions">${acts}</div></div>`;
  }
  const cycle = e.steps.length ? Math.max(...e.steps.map(s => s.cycle)) : 1;
  const last = e.steps.filter(s => s.cycle === cycle && s.status !== 'superseded');
  const rule = RULES.find(r => r.id === e.ruleId);
  const by = last[0] ? last[0].by : '';
  const alt = last[0] && slotsFor(last[0].service).find(x => x.partner);
  const head = last.length > 1 ? `<ul class="steplist">${last.map(s => `<li>${safe(title(s))}<span>${safe(s.due || 'по плану')}</span></li>`).join('')}</ul>` : `<strong style="font-size:21px;line-height:1.3;display:block">${last.map(title).join('') || 'Шагов нет'}</strong>`;
  return `<div class="panel"><h3>Рекомендация следующего шага</h3>${head}
    <dl class="kv" style="margin-top:14px">${last.length > 1 ? '' : `<dt>Срок</dt><dd>${safe((last[0] && last[0].due) || (rule && rule.due) || 'по плану')}</dd>`}<dt>Основание</dt><dd>${safe(by)}${by.startsWith('Правило') ? ' · утверждено клиникой' : ''}</dd><dt>Учтено из карты</dt><dd>${e.profile.map(safe).join(' · ')}</dd><dt>Если нет времени</dt><dd>${alt ? `${safe(alt.place)}: ${safe(lc(alt.date))}, ${safe(alt.time)}` : 'Другой филиал или помощь координатора'}</dd></dl>
    <p class="muted" style="margin:14px 0 0;font-size:13.5px">Срок задаёт правило клиники или врач. Оценка модели на срочность не влияет.</p></div>`;
}
export function staffStep(e, s, isCur, isLast){
  const partnerWait = s.status === 'attended' && s.slot && s.slot.partner;
  const [lab, tone] = s.overdue && live(s) ? ['Просрочено', 'red'] : partnerWait ? ['Ждём результат партнёра', 'blue'] : S_STATUS[s.status];
  const dot = s.status === 'completed' ? `<span class="dot done">${icon('check')}</span>` : `<span class="dot ${s.status === 'refused' || s.overdue ? 'bad' : isCur ? 'now' : ''}"></span>`;
  const meta = [];
  if (s.slot) meta.push(safe(slotFull(s.slot)));
  if (s.due && !s.slot) meta.push((s.overdue ? 'Срок прошёл ' : 'Срок: ') + safe(s.due));
  meta.push('Кто назначил: ' + safe(lc(s.by)));
  if (s.outcome) meta.push('Итог: ' + safe(s.outcome));
  return `<div class="tlitem ${isLast ? 'last' : ''}">${dot}<div><div class="tlhead"><strong>${safe(title(s))}</strong>${badge(lab, tone)}${whereBadge(s)}</div><div class="tlmeta">${meta.join('<br>')}</div></div></div>`;
}
export function planBlock(e){
  const shown = e.steps, cur = currentStep(e);
  let rows = `<div class="tlitem ${shown.length ? '' : 'last'}"><span class="dot done">${icon('check')}</span><div><div class="tlhead"><strong>${e.kind === 'imaging' ? 'Заключение подтверждено врачом' : 'Обращение из личного кабинета'}</strong></div><div class="tlmeta">${safe(e.opened)}</div></div></div>`;
  let cycle = 0;
  shown.forEach((s, i) => {
    if (s.cycle !== cycle){ cycle = s.cycle; rows += `<div class="tlgroup">Цикл ${cycle} · ${cycle === 1 ? 'после заключения' : 'после итога приёма'}</div>`; }
    rows += staffStep(e, s, cur === s, i === shown.length - 1);
  });
  return `<div class="panel"><h3 style="margin-bottom:16px">План и шаги</h3>${rows}</div>`;
}
export function staffActions(e){
  const s = currentStep(e), q = queueInfo(e), key = s ? refKey(e, s) : '';
  let b = '';
  if (e.status === 'manual_review'){
    const req = state.requests.find(r => r.episodeId === e.id && r.kind === 'route' && r.status === 'open');
    b = e.urgent ? '' : req ? btn('Открыть запрос врачу', 'reqOpen', '', {id:req.id}) : btn('Запросить решение врача', 'askDoctor', '', {id:e.id});
  } else if (e.status === 'paused' && s){
    b = btn('Предложить другое время', 'slotList', '', {key, mode:'offer'}) + btn('Вернуть в работу', 'reopen', 'secondary', {key}) + btn('Остановить сопровождение', 'stopEp', 'ghost', {id:e.id});
  } else if (s && s.status === 'open'){
    b = btn('Предложить время', 'slotList', '', {key, mode:'offer'}) + btn('Записать по звонку', 'slotList', 'secondary', {key, mode:'staff'});
  } else if (s && s.status === 'offered'){
    b = btn('Записать по звонку', 'slotList', '', {key, mode:'staff'}) + btn('Предложить другое время', 'slotList', 'secondary', {key, mode:'offer'});
  } else if (s && s.status === 'confirmed'){
    b = btn('Визит состоялся', 'attend', '', {key}) + btn('Отменить запись', 'unbook', 'secondary', {key});
  } else if (s && s.status === 'attended'){
    b = btn('Напомнить врачу про итог', 'nudgeDoctor', '', {id:e.id});
  } else if (!s && e.status === 'active'){
    b = btn('Запросить решение врача', 'askDoctor', '', {id:e.id});
  }
  const done = ['completed', 'closed'].includes(e.status);
  return `<div class="panel"><h3>Что сделать сейчас</h3><p>${safe(q.reason)}</p><div class="actions">${b}${done ? '' : btn('Написать пациенту', 'writeOpen', 'secondary', {id:e.id})}</div></div>`;
}
export function doctorActions(e){
  const s = e.steps.find(x => ['attended', 'confirmed'].includes(x.status) && !(x.slot && x.slot.partner));
  let b = '', text = 'Маршрутизатор только предлагает шаг. План меняет врач.';
  if (e.urgent){ text = 'Пациент отметил тревожный признак и увидел экран срочной помощи.'; }
  else if (e.status === 'manual_review'){
    text = e.reason;
    b = (e.suggest && e.suggest.length ? btn('Подтвердить маршрут', 'routeOk', '', {id:e.id}) : '') + btn('Задать свой план', 'planOpen', e.suggest && e.suggest.length ? 'secondary' : '', {id:e.id});
  } else if (s){
    text = s.status === 'attended' ? 'Визит состоялся. Внесите итог: от него зависят следующие шаги.' : `Пациент записан: ${lc(slotLine(s.slot))}.`;
    b = btn('Внести итог приёма', 'planOpen', '', {id:e.id, step:s.id});
  } else if (!['completed', 'closed'].includes(e.status)){
    b = btn('Изменить план', 'planOpen', 'secondary', {id:e.id});
  }
  return `<div class="panel"><h3>Решение врача</h3><p>${safe(text)}</p><div class="actions">${b}${btn('Написать координатору', 'reqNew', 'secondary', {id:e.id})}</div></div>`;
}
export function casePage(){
  const e = ep(state.sel.episode) || state.episodes[0];
  const q = queueInfo(e);
  const sent = state.outbox.filter(o => o.episodeId === e.id).slice(0, 3);
  const reqs = state.requests.filter(r => r.episodeId === e.id);
  return `<div class="pagehead"><div><div class="eyebrow">Карточка обращения</div><h1>${safe(e.patient)}</h1><p>${safe(e.title)} · открыто ${lc(safe(e.opened))}</p></div><div class="actions">${badge(q.label, q.tone)}${navBtn('← К очереди', 'inbox', 'secondary')}</div></div>
    <div class="twocol"><div class="stack">${sourceBlock(e)}${recBlock(e)}${planBlock(e)}</div>
      <div class="stack">${state.role === 'doctor' ? doctorActions(e) : staffActions(e)}
        <div class="panel"><h3>Связь</h3>${sent.length ? sent.map(o => `<div class="rowline"><div><strong>${safe(o.event)}</strong><div class="meta">Пациенту · ${safe(o.t)} · ${safe(o.channel)}</div></div>${badge(o.status, o.status.startsWith('Прочитано') ? '' : 'gray')}</div>`).join('') : '<p>Пациенту пока ничего не отправляли.</p>'}
          ${reqs.map(r => `<div class="rowline"><div><strong>${safe(r.subject)}</strong><div class="meta">${r.from === 'staff' ? 'Запрос врачу' : 'Запрос от врача'} · ${safe(r.t)}</div></div><button class="btn ghost small" data-action="reqOpen" data-id="${safe(r.id)}">${r.status === 'closed' ? 'Закрыт' : 'Открыть'}</button></div>`).join('')}</div>
        <div class="panel"><h3>Журнал</h3><div class="log">${e.log.slice().reverse().map(l => `<div><time>${safe(l.t)}</time><span><b>${safe(l.who)}.</b> ${safe(l.text)}</span></div>`).join('')}</div></div>
        <div class="note">Действия в демо меняют статус обращения. Звонки и настоящие сообщения не выполняются.</div></div></div>`;
}
export function slotListModal(key, mode){
  const [e, s] = byKey(key);
  openModal(`${modalHead(mode === 'offer' ? 'Предложить время пациенту' : 'Записать по звонку', title(s))}<p>${safe(e.patient)} · срок: ${safe(s.due || 'по плану')}</p>
    ${slotsFor(s.service).map(x => `<div class="slot"><div><strong>${safe(x.date)}, ${safe(x.time)}</strong><div>${safe(x.who)}</div><div class="meta">${safe(x.place)} · ${safe(x.format)}</div>${x.partner ? `<div style="margin-top:6px">${badge('Клиника-партнёр', 'violet')}</div>` : ''}</div><div class="slotprice">${safe(x.price)}</div>${btn('Выбрать', 'slotAsk', 'small', {key, slot:x.id, mode})}</div>`).join('')}`, true);
}
export function writeModal(id){
  const e = ep(id), s = currentStep(e);
  const text = !s ? `Здравствуйте! Это ${staffFirstName()} из клиники «Линия здоровья». ` : s.status === 'confirmed' ? `Здравствуйте! Это ${staffFirstName()} из клиники «Линия здоровья». Напоминаю о записи: ${lc(title(s))}, ${lc(slotLine(s.slot))}.` : `Здравствуйте! Это ${staffFirstName()} из клиники «Линия здоровья». Напоминаю про следующий шаг: ${lc(title(s))}${s.due ? ', срок ' + s.due : ''}. Могу записать вас сама: напишите, когда удобно.`;
  openModal(`${modalHead('Связь с пациентом', safe(e.patient))}<div class="field"><label for="wrText">Сообщение</label><textarea id="wrText">${safe(text)}</textarea><small>Канал подберётся по настройкам пациента: приложение, SMS или мессенджер.</small></div><div class="actions">${btn('Отправить', 'writeSend', '', {id})}${btn('Отмена', 'close', 'secondary')}</div>`);
}

/* ---------- Запись и сопровождение ---------- */
export function scheduling(){
  const cols = [['offer', 'Предложить запись'], ['wait', 'Ждём ответ пациента'], ['booked', 'Записаны'], ['outcome', 'Ждём итог врача'], ['lost', 'Просрочено и на разборе']];
  const all = state.episodes.map(e => [e, queueInfo(e)]);
  return `<div class="pagehead"><div><div class="eyebrow">Операционная работа</div><h1>Запись и сопровождение</h1><p>Каждое обращение стоит в колонке того действия, которого от него ждут.</p></div></div>
    <div class="board">${cols.map(([g, label]) => { const items = all.filter(([, q]) => q.group === g); return `<div class="col"><h3>${label}<span>${items.length}</span></h3>${items.map(([e, q]) => `<button class="kcard" data-case="${safe(e.id)}"><strong>${safe(e.patient)}</strong><span style="color:var(--ink)">${safe(nextStepLabel(e))}</span><span>${safe(q.reason)}</span>${badge(q.label, q.tone)}</button>`).join('') || '<div class="colempty">Пусто</div>'}</div>`; }).join('')}</div>
    <div class="sectionhead"><h2>Контроль сопровождения</h2></div>
    <div class="panel"><ol class="routeSteps"><li><b>1</b><span>Проверить рекомендацию и доступность слотов в клинике и у партнёров.</span></li><li><b>2</b><span>Предложить запись или согласовать альтернативу с пациентом.</span></li><li><b>3</b><span>Убедиться, что врач получил выжимку до приёма.</span></li><li><b>4</b><span>После визита дождаться итога врача и записать пациента на следующий шаг.</span></li></ol></div>`;
}

/* ---------- Связь врач — клиника (общий экран для двух ролей) ---------- */
export function requests(){
  const me = state.role === 'doctor' ? 'doctor' : 'staff';
  const list = state.requests;
  const cur = list.find(r => r.id === state.sel.request) || list[0];
  const mark = r => r.status === 'closed' ? badge('Закрыт', 'gray') : waitingOn(r) === me ? badge('Ждёт вашего ответа', 'orange') : badge(me === 'staff' ? 'Ждём врача' : 'Ждём клинику', 'blue');
  const e = cur && ep(cur.episodeId);
  let quick = '';
  if (cur && cur.status === 'open' && e){
    if (me === 'doctor' && e.status === 'manual_review') quick = (e.suggest && e.suggest.length ? btn('Подтвердить маршрут', 'routeOk', 'small', {id:e.id}) : '') + btn('Задать свой план', 'planOpen', 'secondary small', {id:e.id});
    if (me === 'staff' && cur.kind === 'book') quick = `<button class="btn small" data-case="${safe(e.id)}">Перейти к записи</button>`;
  }
  const thread = !cur ? '<div class="panel empty"><h3>Запросов пока нет</h3></div>' : `<div class="panel"><div class="pagehead" style="margin-bottom:14px"><div>${mark(cur)}<h2 style="margin-top:11px">${safe(cur.subject)}</h2><p style="margin:0">${e ? `<button class="linkbtn" data-case="${safe(e.id)}">${safe(e.patient)} · ${safe(e.title)}</button>` : ''}</p></div></div>
      <div class="chat">${cur.msgs.map(m => `<div class="msg ${m.from === me ? 'me' : ''}"><div class="when">${m.from === me ? 'Вы' : who(m.from)} · ${safe(m.t)}</div><p>${safe(m.text)}</p></div>`).join('')}</div>
      ${quick ? `<div class="actions">${quick}</div>` : ''}
      ${cur.status === 'open' ? `<div class="composer"><input id="reqText" placeholder="Ответить" autocomplete="off">${btn('Отправить', 'reqSend', '', {id:cur.id})}</div><div class="actions" style="margin-top:12px">${btn('Закрыть запрос', 'reqClose', 'ghost small', {id:cur.id})}</div>` : '<div class="note" style="margin-top:16px">Запрос закрыт. Переписка осталась в журнале обращения.</div>'}</div>`;
  return `<div class="pagehead"><div><div class="eyebrow">Сервис «Врач — клиника»</div><h1>${me === 'doctor' ? 'Связь с клиникой' : 'Связь с врачами'}</h1><p>${me === 'doctor' ? 'Координаторы просят подтвердить маршрут или уточнить заключение. Вы передаёте им, кого и куда записать.' : 'Врач подтверждает маршрут и передаёт, кого записать после приёма. Каждый запрос привязан к обращению.'}</p></div><div class="actions">${btn(icon('plus') + 'Новый запрос', 'reqNew')}</div></div>
    <div class="split"><div>${list.map(r => { const ee = ep(r.episodeId); return `<button class="reqitem ${cur && r.id === cur.id ? 'active' : ''}" data-action="reqOpen" data-id="${safe(r.id)}">${mark(r)}<strong>${safe(r.subject)}</strong><span class="sub">${safe(ee ? ee.patient : '')} · ${r.from === me ? 'от вас' : 'от ' + (r.from === 'staff' ? 'координатора' : 'врача')} · ${safe(r.t)}</span></button>`; }).join('')}</div>${thread}</div>`;
}
export function reqNewModal(id){
  const me = state.role === 'doctor' ? 'doctor' : 'staff';
  const topics = me === 'doctor' ? ['Записать пациента', 'Нужен слот у партнёра', 'Позвонить пациенту', 'Другое'] : ['Подтвердить маршрут', 'Уточнить заключение', 'Перенести приём', 'Другое'];
  const open = state.episodes.filter(e => !['completed', 'closed'].includes(e.status));
  openModal(`${modalHead('Сервис «Врач — клиника»', me === 'doctor' ? 'Запрос координаторам' : 'Запрос врачу')}
    <div class="field"><label for="rqEp">Обращение</label><select id="rqEp">${open.map(e => `<option value="${safe(e.id)}" ${e.id === id ? 'selected' : ''}>${safe(e.patient)} · ${safe(e.title)}</option>`).join('')}</select></div>
    <div class="field" style="margin-top:14px"><label for="rqTopic">Тема</label><select id="rqTopic">${topics.map(t => `<option>${t}</option>`).join('')}</select></div>
    <div class="field" style="margin-top:14px"><label for="rqText">Что нужно</label><textarea id="rqText" placeholder="Коротко и по делу"></textarea></div>
    <div class="actions">${btn('Отправить', 'reqCreate')}${btn('Отмена', 'close', 'secondary')}</div>`);
}

/* ---------- Связь клиника — пациент ---------- */
export function comms(){
  const o = state.outbox;
  const today = o.filter(x => /Сегодня|Только что/.test(x.t)).length;
  const read = o.filter(x => x.status.startsWith('Прочитано')).length;
  const silent = o.filter(x => /ответа нет/.test(x.status)).length;
  return `<div class="pagehead"><div><div class="eyebrow">Сервис «Клиника — пациент»</div><h1>Связь с пациентами</h1><p>Сообщения уходят сами, когда в обращении что-то меняется. Если пациент молчит, задача переходит координатору.</p></div></div>
    <div class="grid three" style="margin-bottom:18px"><div class="card"><div class="metric">${today}</div><span class="muted">отправлено сегодня</span></div><div class="card"><div class="metric">${read} из ${o.length}</div><span class="muted">прочитано</span></div><div class="card"><div class="metric">${silent}</div><span class="muted">без ответа: нужен звонок</span></div></div>
    <div class="tablewrap"><table><thead><tr><th>Когда</th><th>Пациент</th><th>Событие</th><th>Канал</th><th>Статус</th></tr></thead><tbody>
      ${o.map(x => `<tr><td>${safe(x.t)}</td><td>${x.episodeId ? `<button class="linkbtn" data-case="${safe(x.episodeId)}">${safe(x.patient)}</button>` : `<strong>${safe(x.patient)}</strong>`}</td><td>${safe(x.event)}</td><td>${safe(x.channel)}</td><td>${badge(x.status, x.status.startsWith('Прочитано') ? '' : /ответа нет/.test(x.status) ? 'orange' : 'gray')}</td></tr>`).join('')}
      </tbody></table></div>
    <div class="sectionhead"><h2>Когда пишем пациенту</h2><span class="muted">Сценарии можно выключить</span></div>
    <div class="trig">${TRIGGERS.map(([id, ev, when, what]) => `<label class="checkline"><input type="checkbox" data-trigger="${id}" ${state.triggers[id] ? 'checked' : ''}><span><strong>${ev}</strong> · ${when}<br><span class="muted">${what}</span></span></label>`).join('')}</div>
    <div class="note" style="margin-top:16px">Пациент сам выбирает канал и тихие часы. Текст заключения в SMS и мессенджеры не уходит: там только ссылка в личный кабинет.</div>`;
}

/* ---------- Партнёры: экран в clinic-ui.js ---------- */

/* ---------- Аптека и заказы ---------- */
export function pharmacyAdmin(){
  const o = state.orders;
  const nextOf = x => x.type === 'otc' ? {'Собирается':'Готов к выдаче', 'Готов к выдаче':'Выдан'}[x.status] : {'Забронировано':'Выдан'}[x.status];
  return `<div class="pagehead"><div><div class="eyebrow">Маркетплейс и аптеки-партнёры</div><h1>Аптека и заказы</h1><p>Заказы без рецепта и брони по рецепту, которые пациенты оформили из своего плана.</p></div></div>
    <div class="grid three" style="margin-bottom:18px"><div class="card"><div class="metric">${o.filter(x => x.type === 'otc').length}</div><span class="muted">${plural(o.filter(x => x.type === 'otc').length, ['заказ', 'заказа', 'заказов'])} без рецепта</span></div><div class="card"><div class="metric">${o.filter(x => x.type === 'rx').length}</div><span class="muted">${plural(o.filter(x => x.type === 'rx').length, ['бронь', 'брони', 'броней'])} по рецепту</span></div><div class="card"><div class="metric">${o.filter(x => x.status !== 'Выдан').length}</div><span class="muted">ещё не выдано</span></div></div>
    <div class="tablewrap"><table><thead><tr><th>Номер</th><th>Пациент</th><th>Состав</th><th>Где выдают</th><th>Сумма</th><th>Статус</th><th></th></tr></thead><tbody>
      ${o.map(x => `<tr><td><strong>${safe(x.id)}</strong><small>${x.type === 'rx' ? 'по рецепту' : 'без рецепта'}</small></td><td>${safe(x.patient)}</td><td>${safe(x.items)}</td><td>${safe(x.place)}</td><td>${safe(x.total)}</td><td>${badge(x.status, x.status === 'Выдан' ? 'gray' : x.status === 'Готов к выдаче' ? '' : 'blue')}</td><td>${nextOf(x) ? btn(nextOf(x) === 'Выдан' ? 'Выдать' : 'Заказ собран', 'orderAdvance', 'secondary small', {id:x.id}) : ''}</td></tr>`).join('')}
    </tbody></table></div>
    <div class="note" style="margin-top:16px">Продавец в каждом заказе — аптека-партнёр. Клиника видит статус, а рецептурный препарат выдают в аптеке по рецепту.</div>`;
}

/* ---------- Маршруты и правила ---------- */
export const SAMPLES = [['xray', 'Рентген'], ['ct', 'КТ'], ['mg', 'Маммография'], ['mri', 'МРТ'], ['norm', 'Без изменений'], ['other', 'Находка без правила']];
export const sampleText = id => id === 'other' ? 'МРТ головного мозга. В белом веществе лобных долей единичные очаги глиоза до 3 мм. Срединные структуры не смещены.\n\nЗаключение: единичные очаги глиоза в лобных долях.' : DEMO[id].draft;
export function sandboxResult(){
  const r = state.sandbox.result || (state.sandbox.text === sampleText(state.sel.sample) ? analyze(state.sandbox.text) : null);
  if (!r) return '<p style="margin:16px 0 0">Вставьте текст заключения или выберите пример, затем нажмите «Разобрать».</p>';
  const facts = `<div class="tlgroup" style="margin-top:18px">Что извлечено</div><div class="chips">${r.facts.map(([k, v]) => `<span class="chip">${k}: <b>${safe(v)}</b></span>`).join('') || '<span class="muted">Ничего не распознано</span>'}</div>`;
  let out;
  if (!r.rule) out = `<div class="note warn" style="margin-top:14px"><strong>Ручной разбор.</strong> Для такой находки правила нет. Обращение уйдёт врачу, пациент увидит план только после его решения.</div>`;
  else if (r.rule.id === 'NORM') out = `<div class="note" style="margin-top:14px"><strong>Правило NORM.</strong> ${r.rule.note}</div>`;
  else if (!r.approved) out = `<div class="note warn" style="margin-top:14px"><strong>Правило ${r.rule.id} найдено, но не утверждено клиникой.</strong> Вариант «${r.rule.steps.map(sv => lc(SERVICES[sv].title)).join(' и ')}» увидит только врач. Обращение уйдёт на ручной разбор.</div>`;
  else out = `<div class="resultmain" style="margin-top:14px;padding:18px"><div class="eyebrow">Следующий шаг · правило ${r.rule.id}, версия ${r.rule.version}</div><strong style="font-size:20px">${r.rule.steps.map(sv => SERVICES[sv].title).join(' + ')}</strong><p style="margin:7px 0 0">Срок: ${r.rule.due}. Пациент получит объяснение и предложение записи, координатор — обращение в очереди.</p></div>`;
  return facts + out;
}
export function rules(){
  return `<div class="pagehead"><div><div class="eyebrow">Настройки клиники</div><h1>Маршруты и правила</h1><p>Что делать после каждой находки, решает клиника. Маршрутизатор применяет только утверждённые правила.</p></div></div>
    <div class="sectionhead" style="margin-top:0"><h2>Правила маршрута после исследований</h2></div>
    <div class="tablewrap"><table><thead><tr><th>Правило</th><th>Исследование</th><th>Находка в заключении</th><th>Следующий шаг</th><th>Срок</th><th>Статус</th><th></th></tr></thead><tbody>
      ${RULES.map(r => { const ok = state.ruleApproved[r.id]; return `<tr><td><strong>${safe(r.id)}</strong><small>версия ${safe(r.version)}</small></td><td>${safe(r.study)}</td><td>${safe(r.finding)}</td><td>${r.steps.map(sv => SERVICES[sv].title).join(' + ') || 'Маршрут не нужен, напоминание через год'}</td><td style="white-space:nowrap">${safe(r.due || '—')}</td><td>${badge(ok ? 'Утверждено' : 'Черновик', ok ? '' : 'orange')}</td><td>${btn(ok ? 'В черновик' : 'Утвердить', 'ruleToggle', 'secondary small', {id:r.id})}</td></tr>`; }).join('')}
    </tbody></table></div>
    <div class="note warn" style="margin-top:14px">Правила в демо условные. Если подходящего утверждённого правила нет, обращение уходит на ручной разбор, а план назначает врач.</div>
    <div class="sectionhead"><h2>Проверить заключение</h2><span class="muted">Как маршрутизатор читает текст</span></div>
    <div class="panel"><div class="chips" style="margin-bottom:12px">${SAMPLES.map(([id, label]) => `<button class="chip ${state.sel.sample === id ? 'selected' : ''}" data-action="sample" data-id="${id}">${label}</button>`).join('')}</div>
      <div class="field"><label for="sbText">Текст заключения</label><textarea id="sbText" style="min-height:150px">${safe(state.sandbox.text)}</textarea></div>
      <div class="actions" style="margin-top:14px">${btn('Разобрать', 'sandboxRun')}</div>
      ${sandboxResult()}
      <p class="muted" style="margin:16px 0 0;font-size:13.5px">Демо ищет ключевые слова. В продукте заключение разбирает NLP-модель, а при сомнении случай уходит человеку.</p></div>
    <div class="sectionhead"><h2>Каналы и сопровождение</h2></div>
    <div class="grid two"><div class="panel"><h3>Доступные каналы</h3><div class="miniRow"><span>Частный приём</span>${badge('Включён')}</div><div class="miniRow"><span>ДМС</span>${badge('Включён')}</div><div class="miniRow"><span>ОМС</span>${badge('Справочный маршрут', 'orange')}</div><h3 style="margin-top:22px">Сценарии обращения</h3>${Object.values(scenarios).map(s => `<div class="miniRow"><span>${s.title}</span>${badge('Активен')}</div>`).join('')}</div>
      <div class="panel"><h3>Правила сопровождения</h3>${[['manual', 'Ручная проверка неоднозначных обращений'], ['alternate', 'Альтернативы при отсутствии слотов, включая партнёров'], ['followup', 'Напоминание о следующем шаге']].map(([id, label]) => `<label class="checkline" style="margin-bottom:10px"><input type="checkbox" data-rule="${id}" ${state.rules[id] ? 'checked' : ''}><span>${label}</span></label>`).join('')}<div class="note warn" style="margin-top:15px">Медицинские правила и вопросы о тревожных признаках проходят отдельное согласование. Эти переключатели показывают только интерфейс настройки.</div></div></div>`;
}

/* ---------- Аналитика ---------- */
export const FUNNELS = {
  imaging:[['Врач подтвердил заключение с находкой', 1248], ['Маршрутизатор предложил следующий шаг', 1173], ['Пациенту предложена запись', 1061], ['Пациент записался', 574], ['Визит состоялся', 487], ['Врач назначил следующий шаг', 312]],
  intake:[['Начали обращение', 1248], ['Заполнили анкету', 1011], ['Получили маршрут', 899], ['Выбрали запись', 574]]
};
export function calcOut(){
  const c = state.calc;
  const visits = Math.max(0, Math.round(c.n * (c.target - c.base) / 100));
  return `<div><span>Дополнительных визитов в месяц</span><div class="metric">${visits.toLocaleString('ru-RU')}</div></div><div><span>Дополнительная выручка в месяц</span><div class="metric">${rub(visits * c.check)}</div></div><div><span>За год</span><div class="metric">${rub(visits * c.check * 12)}</div></div>`;
}
export function analytics(){
  const kind = state.sel.funnel || 'imaging', f = FUNNELS[kind], top = f[0][1], c = state.calc;
  return `<div class="pagehead"><div><div class="eyebrow">Оценка продукта</div><h1>Аналитика</h1><p>Вымышленные данные для демонстрации будущих отчётов.</p></div></div>
    <div class="grid three"><div class="card"><div class="metric">1 248</div><span class="muted">заключений с находкой за месяц</span></div><div class="card"><div class="metric">46%</div><span class="muted">пациентов записались на следующий шаг</span></div><div class="card"><div class="metric">3 ч 20 мин</div><span class="muted">от заключения до предложения записи, медиана</span></div></div>
    <div class="sectionhead"><h2>Воронка</h2></div>
    <div class="tabs">${[['imaging', 'После исследований'], ['intake', 'Самостоятельные обращения']].map(([id, label]) => `<button class="tab ${kind === id ? 'active' : ''}" data-action="funnel" data-id="${id}">${label}</button>`).join('')}</div>
    <div class="panel">${f.map(([label, v], i) => { const pct = Math.round(v / top * 100); const prev = i ? Math.round(v / f[i - 1][1] * 100) : 100; return `<div class="funnelrow" title="${v.toLocaleString('ru-RU')} обращений${i ? ` · ${prev}% от предыдущего шага` : ''}"><div class="miniRow"><strong>${label}</strong><span>${v.toLocaleString('ru-RU')} · ${pct}%</span></div><div class="bar"><i style="width:${pct}%"></i></div></div>`; }).join('')}</div>
    <div class="sectionhead"><h2>По сервисам</h2></div>
    <div class="grid three">
      <div class="card"><div class="metric">6%</div><span class="muted">черновиков ИИ исправил врач · «Что на снимке?»</span></div>
      <div class="card"><div class="metric">4%</div><span class="muted">шагов просрочено · путь пациента</span></div>
      <div class="card"><div class="metric">42 мин</div><span class="muted">врач отвечает на запрос, медиана · врач — клиника</span></div>
      <div class="card"><div class="metric">31%</div><span class="muted">записей сделано из сообщения · клиника — пациент</span></div>
      <div class="card"><div class="metric">118</div><span class="muted">направлений к партнёрам, 76% вернулись с результатом</span></div>
      <div class="card"><div class="metric">272</div><span class="muted">заказа и брони в аптеках-партнёрах</span></div>
    </div>
    <div class="sectionhead"><h2>Качество и безопасность</h2></div>
    <div class="grid three"><div class="card"><div class="metric">8%</div><span class="muted">обращений ушло на ручной разбор</span></div><div class="card"><div class="metric">3,1%</div><span class="muted">маршрутов изменил врач</span></div><div class="card"><div class="metric">0</div><span class="muted">инцидентов в демонстрационных данных</span></div></div>
    <div class="sectionhead"><h2>Оценка эффекта для клиники</h2><span class="muted">Подставьте цифры своей клиники</span></div>
    <div class="panel"><div class="calc">
        <div class="field"><label for="cN">Заключений с находкой в месяц</label><input id="cN" type="number" min="0" step="50" data-calc="n" value="${c.n}"></div>
        <div class="field"><label for="cB">Доходят до следующего шага сейчас, %</label><input id="cB" type="number" min="0" max="100" data-calc="base" value="${c.base}"></div>
        <div class="field"><label for="cT">Доходят с сервисом, %</label><input id="cT" type="number" min="0" max="100" data-calc="target" value="${c.target}"></div>
        <div class="field"><label for="cC">Средний чек следующего шага, ₽</label><input id="cC" type="number" min="0" step="100" data-calc="check" value="${c.check}"></div>
      </div><div class="calcout" id="calcOut">${calcOut()}</div>
      <p class="muted" style="margin:16px 0 0;font-size:13.5px">Значения по умолчанию условные. Считаем только первый следующий шаг, без повторных визитов, партнёров и аптеки.</p></div>
    <div class="note" style="margin-top:18px">В рабочем продукте показатели считаются из реальных событий обращения. Рост записи оценивается вместе с качеством маршрутов и ручными исправлениями.</div>`;
}

