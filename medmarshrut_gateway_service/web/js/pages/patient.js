import { CATS, DEMO, PARTNERS, PHARMACIES, PRODUCTS, RX_STOCK, SCHEME, scenarios, slotsFor } from '../demo-data.js';
import { addLog, byKey, currentStep, ep, mkStep, myEpisodes, refKey, slotFull, slotLine, studyOf, title, whereBadge, wherePartner } from '../domain.js';
import { icon } from '../icons.js';
import { patientName, state } from '../state.js';
import { badge, btn, lc, modalHead, navBtn, openModal, plural, rub, safe, uc } from '../ui.js';

/* =====================================================================
   Экраны пациента
   ===================================================================== */
export const P_STATUS = {open:['Нужно записаться','orange'], offered:['Клиника предложила время','blue'], confirmed:['Вы записаны',''], attended:['Ждём итог врача','blue'], completed:['Выполнено','gray'], refused:['Отложено','red'], superseded:['Заменён','gray']};
export const REASONS = ['Уже есть запись в другой клинике', 'Нет удобного времени', 'Дорого', 'Хочу сначала обсудить с врачом', 'Другая причина'];
export const ROOMS = {therapist:'кабинет 214 на втором этаже', gp:'кабинет 214 на втором этаже', therapist2:'кабинет 214 на втором этаже', attending:'кабинет 214 на втором этаже', pulmo:'кабинет 216 на втором этаже', labs:'процедурный кабинет 105 на первом этаже', xray2:'кабинет рентгена 118 на первом этаже', usbreast:'кабинет УЗИ 207 на втором этаже', mammolog:'кабинет 209 на втором этаже', ortho:'кабинет 301 на третьем этаже', ortho2:'кабинет 301 на третьем этаже'};

/* Что пациенту делать по эпизоду прямо сейчас */
export function patientNext(e){
  const s = currentStep(e);
  if (e.urgent) return {head:'Обратитесь за срочной помощью', text:'Вы отметили тревожный признак. Не ждите плановой записи: позвоните 103 или 112.', buttons:'<a class="btn danger" href="tel:103">Позвонить 103</a><a class="btn secondary" href="tel:112">Позвонить 112</a>'};
  if (e.status === 'manual_review') return {head:'Врач уточняет следующий шаг', text:'Мы напишем, как только план будет готов. Обычно это занимает до двух часов.', buttons:''};
  if (e.status === 'completed') return {head:'План выполнен', text:'Новых шагов нет. Если что-то изменится, напишите координатору.', buttons:navBtn('Написать в клинику', 'messages', 'secondary')};
  if (e.status === 'closed') return {head:'Сопровождение остановлено', text:e.reason || '', buttons:''};
  if (!s) return {head:'Активных шагов нет', text:'', buttons:''};
  const key = refKey(e, s), p = wherePartner(s);
  if (s.status === 'refused') return {head:title(s), text:'Вы отложили этот шаг. Координатор свяжется с вами, а вернуться к записи можно в любой момент.', buttons:btn('Вернуться к записи', 'reopen', '', {key})};
  if (s.status === 'open') return {head:title(s), text:`${s.overdue ? 'Срок прошёл ' + s.due : s.due ? 'Срок: ' + s.due : 'Выберите удобное время'}. ${p ? 'Услугу оказывает клиника-партнёр: направление и заключение передадим сами.' : 'Ближайшее время: ' + lc(slotLine(slotsFor(s.service)[0])) + '.'}`, buttons:btn('Выбрать время', 'book', '', {key}) + btn('Не сейчас', 'later', 'ghost', {key})};
  if (s.status === 'offered') return {head:title(s), text:`Клиника предлагает: ${lc(slotFull(s.slot))}.`, buttons:btn('Подтвердить', 'accept', '', {key}) + btn('Другое время', 'book', 'secondary', {key}) + btn('Не сейчас', 'later', 'ghost', {key})};
  if (s.status === 'confirmed') return {head:title(s), text:`Вы записаны: ${lc(slotFull(s.slot))}.`, buttons:btn('Перенести', 'book', 'secondary', {key}) + btn('Отменить запись', 'unbook', 'ghost', {key})};
  if (s.status === 'attended') return {head:title(s), text:'Визит состоялся. Врач вносит итог, после этого план обновится.', buttons:''};
  return {head:title(s), text:'', buttons:''};
}

export function patientHero(){
  const base = {h1:'Поможем понять,<br>что делать дальше', lead:'Расскажите о своей ситуации. Мы поможем подготовиться к обращению и найти подходящий путь к специалисту.', buttons:btn('Начать обращение →', 'new') + btn('Как это работает', 'how', 'secondary'), artTitle:'Ваш будущий план', art:[['Следующий шаг', 'Понятно'], ['Запись', 'С реальными слотами'], ['Подготовка', 'В одном месте']]};
  const e = myEpisodes().find(x => x.kind === 'imaging' && !['completed', 'closed'].includes(x.status));
  if (!e) return base;
  const st = studyOf(e), d = DEMO[st.kind], s = currentStep(e);
  if (e.status === 'manual_review') return {h1:d.ready, lead:'Врач подтвердил заключение и сейчас уточняет следующий шаг. Мы напишем, как только план будет готов.', buttons:navBtn('Что на снимке →', 'imaging') + navBtn('Открыть план', 'plan', 'secondary'), artTitle:'Ваш следующий шаг', art:[['Что сделать', 'Пока ничего'], ['Кто решает', 'Врач клиники'], ['Обычно занимает', 'До двух часов']]};
  if (!s) return base;
  const key = refKey(e, s);
  if (s.status === 'refused') return {h1:'Запись отложена', lead:`Вы отложили шаг «${safe(lc(title(s)))}». Вернуться к нему можно в любой момент.`, buttons:btn('Вернуться к записи', 'reopen', '', {key}) + navBtn('Открыть план', 'plan', 'secondary'), artTitle:'Отложенный шаг', art:[['Что сделать', title(s)], ['Срок', uc(s.due) || 'По плану']]};
  if (s.status === 'open') return {h1:s.cycle === 1 ? d.ready : 'Врач обновил ваш план', lead:s.cycle === 1 ? `Врач подтвердил заключение ${safe(st.confirmedAt)}. Мы объяснили его простыми словами и подобрали следующий шаг.` : 'После приёма появились новые шаги. Запишитесь на ближайший.', buttons:(s.cycle === 1 ? navBtn('Что на снимке →', 'imaging') : navBtn('Открыть план →', 'plan')) + btn('Выбрать время', 'book', 'secondary', {key}), artTitle:'Ваш следующий шаг', art:[['Что сделать', title(s)], ['Срок', uc(s.due) || 'По плану'], ['Ближайшее время', slotLine(slotsFor(s.service)[0])]]};
  if (s.status === 'offered') return {h1:'Клиника предложила время', lead:`${safe(title(s))}: ${safe(lc(slotFull(s.slot)))}.`, buttons:btn('Подтвердить', 'accept', '', {key}) + btn('Другое время', 'book', 'secondary', {key}), artTitle:'Ваш следующий шаг', art:[['Что сделать', 'Подтвердить запись'], ['Когда', slotLine(s.slot)], ['Где', s.slot.place]]};
  if (s.status === 'confirmed') return {h1:'Вы записаны', lead:`${safe(title(s))}: ${safe(lc(slotFull(s.slot)))}.`, buttons:navBtn('Открыть план →', 'plan') + navBtn('Что на снимке', 'imaging', 'secondary'), artTitle:'Ближайший визит', art:[['Когда', slotLine(s.slot)], ['Где', s.slot.place], ['С собой', 'Паспорт и полис']]};
  return {h1:'Приём состоялся', lead:'Врач вносит итог приёма. Как только план обновится, мы напишем.', buttons:navBtn('Открыть план →', 'plan'), artTitle:'Ваш следующий шаг', art:[['Что сделать', 'Пока ничего'], ['Кто решает', 'Лечащий врач']]};
}

export function home(){
  const h = patientHero();
  const unread = state.messages.filter(m => m.unread).length;
  const rx = state.prescriptions.filter(p => p.mine && p.status === 'issued').length;
  const pair = myEpisodes().map(e => [e, currentStep(e)]).find(x => x[1] && !['completed', 'closed'].includes(x[0].status));
  const planText = pair ? `${title(pair[1])} — ${lc(P_STATUS[pair[1].status][0])}` : 'Активных шагов нет';
  return `<section class="hero"><div><div class="eyebrow">Клиника «Линия здоровья»</div><h1>${h.h1}</h1><p class="lead">${h.lead}</p><div class="actions">${h.buttons}</div></div><div class="heroArt"><div class="eyebrow">${h.artTitle}</div>${h.art.map(([k, v]) => `<div class="miniRow"><span>${k}</span><strong>${safe(v)}</strong></div>`).join('')}</div></section>
    <div class="sectionhead"><h2>Сейчас у вас</h2></div>
    <div class="grid three">
      <article class="card clickable" tabindex="0" role="button" data-nav="plan"><div class="tile">${icon('route')}</div><h3>Мой план</h3><p>${safe(planText)}</p><div class="cardfoot">Открыть план →</div></article>
      <article class="card clickable" tabindex="0" role="button" data-nav="messages"><div class="tile blue">${icon('message')}</div><h3>Сообщения</h3><p>${unread ? `${unread} ${plural(unread, ['новое', 'новых', 'новых'])} от клиники` : 'Новых сообщений нет'}</p><div class="cardfoot">Открыть переписку →</div></article>
      <article class="card clickable" tabindex="0" role="button" data-nav="pharmacy"><div class="tile violet">${icon('pharmacy')}</div><h3>Аптека</h3><p>${rx ? `${rx} ${plural(rx, ['рецепт ждёт', 'рецепта ждут', 'рецептов ждут'])} получения` : 'Товары без рецепта и бронь по рецепту'}</p><div class="cardfoot">Перейти в аптеку →</div></article>
    </div>
    <div class="sectionhead"><h2>С чем помочь?</h2>${h.buttons.includes('data-action="how"') ? '<span class="muted">Выберите ситуацию</span>' : btn('Как это работает', 'how', 'ghost small')}</div>
    <div class="grid three">${Object.entries(scenarios).map(([id, x]) => `<article class="card clickable" tabindex="0" role="button" data-scenario="${id}"><div class="tile">${icon(x.icon)}</div><h3>${x.title}</h3><p>${x.desc}</p><div class="cardfoot">Продолжить →</div></article>`).join('')}</div>
    <div class="note" style="margin-top:20px">Сервис помогает организовать обращение. Если ситуация требует срочной помощи, обратитесь в экстренные службы по номерам 103 или 112.</div>`;
}

/* ---------- Что на снимке ---------- */
export function patientStudy(st){
  const d = DEMO[st.kind];
  const head = (b, tone) => `${badge(b, tone)}<h2 style="margin-top:11px">${d.title}</h2><p>${safe(st.source)} · ${safe(st.date)}${st.file ? ` · файл «${safe(st.file)}»` : ''}</p>`;
  if (st.status === 'processing' || st.status === 'awaiting'){
    const stage = st.status === 'processing' ? 1 : 2;
    const names = ['Файлы приняты', 'ИИ готовит черновик', 'Врач проверяет', 'Результат и план'];
    return `<div class="panel">${head(st.status === 'processing' ? 'Обрабатывается' : 'Ждёт врача', 'blue')}<div class="steps" style="margin:18px 0 14px">${names.map((n, i) => `${i ? '<span class="sep"></span>' : ''}<span class="step ${i <= stage ? 'on' : ''}"><b>${i + 1}</b>${n}</span>`).join('')}</div><p style="margin:0">${st.status === 'processing' ? 'Проверяем файлы и готовим черновик заключения.' : 'Черновик готов, его проверяет врач-рентгенолог. Результат и план появятся здесь, а мы пришлём сообщение. Обычно это занимает до двух часов.'}</p></div>`;
  }
  if (st.status === 'manual') return `<div class="panel">${head('Врач описывает сам', 'orange')}<p style="margin:0">Врач решил описать этот снимок без черновика ИИ. Заключение появится здесь, и мы пришлём сообщение.</p></div>`;
  const e = st.episodeId ? ep(st.episodeId) : null;
  const nx = st.noRoute ? {head:'Сейчас ничего делать не нужно', text:'Напомним о плановом обследовании через 12 месяцев.', buttons:''} : e ? patientNext(e) : {head:'', text:'', buttons:''};
  return `<div class="panel">${head('Подтверждено врачом')}
    <div class="explain">
      <div class="viewer">${SCHEME[d.scheme](d.findings.length > 0)}<div class="cap"><span>${d.findings.length ? 'Схема: где врач отметил изменение' : 'Схема снимка'}</span><span>Не медицинское изображение</span></div></div>
      <div class="stack">
        <div><div class="eyebrow">Что увидели</div><p class="plain">${d.seen}</p></div>
        <div><div class="eyebrow">Что это значит</div><p class="plain">${d.means}</p></div>
        <div class="resultmain" style="padding:20px"><div class="eyebrow">Что дальше</div><strong style="font-size:20px">${safe(nx.head)}</strong><p style="margin:7px 0 0">${safe(nx.text)}</p>${nx.buttons ? `<div class="actions" style="margin-top:14px">${nx.buttons}</div>` : ''}</div>
      </div>
    </div>
    <details class="more"><summary>Заключение врача полностью</summary><div class="quote">${safe(st.conclusion).replace(/\n+/g, '<br>')}<br><br><span class="muted">${safe(st.confirmedBy)}, подтверждено ${safe(st.confirmedAt)}</span></div></details>
  </div>`;
}
export function imaging(){
  const list = state.studies.filter(s => s.mine);
  return `<div class="pagehead"><div><div class="eyebrow">Сервис «Что на снимке?»</div><h1>Мои исследования</h1><p>Заключение появляется здесь после того, как его подтвердил врач. Рядом — объяснение простыми словами и следующий шаг.</p></div><div class="actions">${btn(icon('plus') + 'Загрузить снимок', 'uploadOpen')}</div></div>
    <div class="stack">${list.map(patientStudy).join('') || '<div class="panel empty"><h3>Исследований пока нет</h3><p>Загрузите снимок или заключение из другой клиники.</p></div>'}</div>
    <div class="note" style="margin-top:18px">ИИ не ставит диагноз. Он помогает врачу описать снимок, а нам — подобрать следующий шаг. Заключение всегда подтверждает врач. Объяснения в демо условные: в продукте их тексты утверждает клиника.</div>`;
}
export function uploadModal(){
  openModal(`${modalHead('Сервис «Что на снимке?»', 'Загрузить снимок или заключение')}
    <p>Подойдёт исследование из другой клиники. ИИ подготовит черновик, врач его проверит, и вы получите объяснение и план.</p>
    <div class="field"><label for="upKind">Что за исследование</label><select id="upKind"><option value="xray">Рентгенография</option><option value="ct">КТ</option><option value="mg">Маммография</option><option value="mri">МРТ</option></select></div>
    <div class="field" style="margin-top:14px"><label for="upFile">Файл</label><input id="upFile" type="file" accept=".zip,.dcm,.pdf,image/*"><small>Архив DICOM, PDF или фото заключения. В демо файл никуда не отправляется: сохраняется только его имя.</small></div>
    <label class="checkline" style="margin-top:14px"><input type="checkbox" id="upConsent"><span>Разрешаю передать исследование врачу клиники «Линия здоровья» для описания</span></label>
    <div class="actions">${btn('Отправить врачу', 'upload')}${btn('Отмена', 'close', 'secondary')}</div>`);
}

/* ---------- Мой план ---------- */
export function visitDay(s){
  if (!s.slot) return '';
  if (s.slot.format === 'Онлайн') return '<strong>В день визита.</strong> Ссылка на видеоприём придёт сюда и в SMS за 15 минут до начала.';
  if (s.slot.partner) return `<strong>В день визита.</strong> ${safe(PARTNERS[s.slot.partner].name)} — партнёр клиники. Направление и заключение уже там, с собой нужен только паспорт. Результат вернётся в ваш план.`;
  return `<strong>В день визита.</strong> ${safe(s.slot.place)}: регистратура на первом этаже, затем ${ROOMS[s.service] || 'кабинет укажем в напоминании'}. Приходите за 10 минут, с собой паспорт и полис.${s.service === 'labs' ? ' Как подготовиться к анализам, напишем в напоминании.' : ''}`;
}
export function planStep(e, s, isCur, isLast){
  const [lab, tone] = s.overdue && s.status === 'open' ? ['Срок прошёл', 'red'] : P_STATUS[s.status];
  const dot = s.status === 'completed' ? `<span class="dot done">${icon('check')}</span>` : `<span class="dot ${s.status === 'refused' || s.overdue ? 'bad' : isCur ? 'now' : ''}"></span>`;
  const meta = [];
  if (s.slot) meta.push(safe(slotFull(s.slot)) + (s.slot.price ? ' · ' + s.slot.price : ''));
  else if (s.due) meta.push((s.overdue ? 'Срок прошёл ' : 'Срок: ') + safe(s.due));
  if (s.outcome) meta.push('Итог приёма: ' + safe(s.outcome));
  const key = refKey(e, s);
  let acts = '';
  if (!isCur && e.status === 'active'){
    if (s.status === 'open') acts = btn('Выбрать время', 'book', 'secondary small', {key});
    if (s.status === 'offered') acts = btn('Подтвердить', 'accept', 'small', {key}) + btn('Другое время', 'book', 'secondary small', {key});
    if (s.status === 'confirmed') acts = btn('Перенести', 'book', 'secondary small', {key}) + btn('Отменить', 'unbook', 'ghost small', {key});
  }
  return `<div class="tlitem ${isLast ? 'last' : ''}">${dot}<div><div class="tlhead"><strong>${safe(title(s))}</strong>${badge(lab, tone)}${whereBadge(s)}</div><div class="tlmeta">${meta.join('<br>')}</div>${s.status === 'confirmed' ? `<div class="note" style="margin-top:10px">${visitDay(s)}</div>` : ''}${acts ? `<div class="actions">${acts}</div>` : ''}</div></div>`;
}
export function planEpisode(e){
  const st = e.kind === 'imaging' ? studyOf(e) : null;
  const nx = patientNext(e), cur = currentStep(e);
  const [lab, tone] = e.urgent ? ['Нужна срочная помощь', 'red'] : {active:['В работе', ''], manual_review:['Врач уточняет план', 'orange'], paused:['Отложено', 'red'], completed:['План выполнен', 'gray'], closed:['Остановлено', 'gray']}[e.status];
  const shown = e.steps.filter(s => s.status !== 'superseded');
  let rows = `<div class="tlitem ${shown.length ? '' : 'last'}"><span class="dot done">${icon('check')}</span><div><div class="tlhead"><strong>${st ? 'Исследование и заключение' : 'Обращение заполнено'}</strong></div><div class="tlmeta">${st ? `${DEMO[st.kind].title} · заключение подтвердил ${safe(st.confirmedBy)}` : 'Ответы из анкеты переданы в клинику'}</div>${st ? `<div class="actions">${navBtn('Что на снимке', 'imaging', 'ghost small')}</div>` : ''}</div></div>`;
  let cycle = 0;
  shown.forEach((s, i) => {
    if (s.cycle !== cycle){ cycle = s.cycle; rows += `<div class="tlgroup">Этап ${cycle} · ${cycle === 1 ? (st ? 'после исследования' : 'по вашему обращению') : 'после приёма врача'}</div>`; }
    rows += planStep(e, s, cur === s, i === shown.length - 1);
  });
  return `<div class="panel" style="margin-bottom:18px">
    <div class="pagehead" style="margin-bottom:16px"><div>${badge(lab, tone)}<h2 style="margin-top:11px">${safe(e.title)}</h2><p style="margin:0">${st ? 'Маршрут после исследования' : 'Маршрут по вашему обращению'} · открыт ${safe(lc(e.opened))}</p></div></div>
    <div class="resultmain" style="margin-bottom:22px"><div class="eyebrow">Следующий шаг</div><strong class="big">${safe(nx.head)}</strong>${nx.text ? `<p style="margin:11px 0 0">${safe(nx.text)}</p>` : ''}${nx.buttons ? `<div class="actions">${nx.buttons}</div>` : ''}</div>
    <div class="tlgroup">Что уже сделано и что впереди</div>${rows}
  </div>`;
}
export function plan(){
  const mine = myEpisodes();
  return `<div class="pagehead"><div><div class="eyebrow">Ваше сопровождение</div><h1>Мой план</h1><p>Все шаги после исследования и приёма в одном месте: в клинике и у партнёров.</p></div><div class="actions">${btn('Новое обращение', 'new')}</div></div>
    ${mine.length ? mine.map(planEpisode).join('') : `<div class="empty panel"><h2>Пока нет активного маршрута</h2><p>Начните с описания ситуации.</p>${btn('Создать маршрут', 'new')}</div>`}`;
}

/* ---------- Записи ---------- */
export function bookable(){
  const out = [];
  myEpisodes().forEach(e => {
    if (['completed', 'closed', 'manual_review'].includes(e.status)) return;
    e.steps.forEach(s => { if (['open', 'offered', 'refused'].includes(s.status) || (s.status === 'confirmed' && state.sel.book === refKey(e, s))) out.push([e, s]); });
  });
  return out;
}
export function appointments(){
  const list = bookable();
  const cur = list.find(([e, s]) => refKey(e, s) === state.sel.book) || list[0];
  const booked = myEpisodes().flatMap(e => e.steps.filter(s => s.status === 'confirmed').map(s => [e, s]));
  const head = `<div class="pagehead"><div><div class="eyebrow">Расписание клиники и партнёров</div><h1>Выбрать запись</h1><p>Слоты здесь вымышленные. В рабочем продукте они приходят из расписания клиники и клиник-партнёров.</p></div></div>`;
  const bookedHtml = booked.map(([e, s]) => `<div class="note" style="margin-bottom:12px"><strong>Вы записаны:</strong> ${safe(lc(title(s)))} — ${lc(safe(slotFull(s.slot)))}. ${btn('Перенести', 'book', 'ghost small', {key:refKey(e, s)})}${btn('Отменить', 'unbook', 'ghost small', {key:refKey(e, s)})}</div>`).join('');
  if (!cur) return head + bookedHtml + `<div class="panel empty"><h3>Сейчас записываться не на что</h3><p>Новые шаги появятся после приёма или нового исследования.</p>${navBtn('Открыть мой план', 'plan', 'secondary')}</div>`;
  const [e, s] = cur, key = refKey(e, s), tab = state.sel.slotTab;
  const all = slotsFor(s.service);
  const shown = all.filter(x => tab === 'all' || (tab === 'own' && !x.partner && x.format !== 'Онлайн') || (tab === 'partner' && x.partner) || (tab === 'online' && x.format === 'Онлайн'));
  const chooser = list.length > 1 ? `<div class="field" style="margin-bottom:16px"><label>На что записываемся</label><div class="choiceRow">${list.map(([e2, s2]) => `<button class="choice ${s2 === s ? 'selected' : ''}" data-action="book" data-key="${safe(refKey(e2, s2))}">${safe(title(s2))}</button>`).join('')}</div></div>` : '';
  return head + bookedHtml + chooser + `<div class="twocol"><div class="panel"><h2>${safe(title(s))}</h2><p>${s.overdue ? 'Срок прошёл ' + safe(s.due) : s.due ? 'Срок: ' + safe(s.due) : 'Выберите удобное время'}${s.status === 'confirmed' ? ' · сейчас вы записаны: ' + lc(slotLine(s.slot)) : ''}</p>
      <div class="tabs">${[['all', 'Все'], ['own', 'Наша клиника'], ['partner', 'Клиники-партнёры'], ['online', 'Онлайн']].map(([id, label]) => `<button class="tab ${tab === id ? 'active' : ''}" data-action="slotTab" data-id="${id}">${label}</button>`).join('')}</div>
      ${shown.map(x => `<div class="slot"><div><strong>${safe(x.date)}, ${safe(x.time)}</strong><div>${safe(x.who)}</div><div class="meta">${safe(x.place)} · ${safe(x.format)}</div>${x.partner ? `<div style="margin-top:6px">${badge('Клиника-партнёр', 'violet')}</div>` : ''}${s.status === 'offered' && s.slot && s.slot.id === x.id ? `<div style="margin-top:6px">${badge('Предложено клиникой', 'blue')}</div>` : ''}</div><div class="slotprice">${safe(x.price)}</div>${btn('Выбрать', 'slotAsk', 'small', {key, slot:x.id, mode:'patient'})}</div>`).join('') || '<p style="margin:14px 0 0">В этом разделе свободного времени нет. Посмотрите вкладку «Все».</p>'}
    </div>
    <div class="stack"><div class="panel"><h3>Нет подходящего времени?</h3><p>Координатор клиники проверит другие варианты, в том числе у партнёров, и свяжется с вами.</p>${btn('Попросить координатора', 'callback', 'secondary', {id:e.id})}</div><div class="note warn">При наличии тревожных признаков не ожидайте плановой записи. Для экстренной помощи: 103 или 112.</div></div></div>`;
}
export function slotAskModal(key, slotId, mode){
  const [e, s] = byKey(key);
  const x = slotsFor(s.service).find(z => z.id === slotId);
  const heads = {patient:'Подтверждение записи', offer:'Предложить время пациенту', staff:'Записать по звонку'};
  openModal(`${modalHead(heads[mode], `${safe(x.date)}, ${safe(x.time)}`)}<p><strong style="color:var(--ink)">${safe(title(s))}</strong><br>${safe(x.who)}<br>${safe(x.place)} · ${safe(x.format)} · ${safe(x.price)}</p>
    ${x.partner ? `<div class="note" style="margin-bottom:12px"><strong>${safe(PARTNERS[x.partner].name)}</strong> — партнёр клиники. ${mode === 'patient' ? 'Мы передадим туда направление и заключение по снимку, а результат вернётся в ваш план.' : 'Партнёр получит направление и заключение, результат вернётся в эпизод.'}</div>` : ''}
    <div class="note">${mode === 'offer' ? 'Пациент получит сообщение с кнопкой подтверждения. В демо оно появится в режиме пациента.' : 'Это демонстрационная запись. В расписание клиники она не попадает.'}</div>
    <div class="actions">${btn(mode === 'offer' ? 'Отправить предложение' : 'Подтвердить', 'slotConfirm', '', {key, slot:slotId, mode})}${btn('Назад', 'close', 'secondary')}</div>`);
}
export function laterModal(key){
  const [, s] = byKey(key);
  openModal(`${modalHead('Отложить шаг', title(s))}<p>Подскажите, что мешает записаться. Координатор увидит причину и предложит другой вариант.</p>
    ${REASONS.map((r, i) => `<label class="radio"><input type="radio" name="reason" value="${r}" ${i === 1 ? 'checked' : ''}><span>${r}</span></label>`).join('')}
    <div class="actions">${btn('Отправить', 'laterSend', '', {key})}${btn('Назад', 'close', 'secondary')}</div>`);
}

/* ---------- Сообщения ---------- */
export function messages(){
  const fresh = new Set(state.messages.filter(m => m.unread).map(m => m.id));
  state.messages.forEach(m => { m.unread = false; });
  const bubble = m => `<div class="msg ${m.from === 'patient' ? 'me' : ''} ${fresh.has(m.id) ? 'new' : ''}"><div class="when">${m.from === 'patient' ? 'Вы' : 'Клиника «Линия здоровья»'} · ${safe(m.t)}</div><p>${safe(m.text)}</p>${m.actions.length ? `<div class="actions">${m.actions.map(([label, kind, arg], i) => `<button class="btn ${i ? 'secondary' : ''} small" data-action="msgAct" data-kind="${kind}" data-arg="${safe(arg)}">${label}</button>`).join('')}</div>` : ''}</div>`;
  const n = state.notify;
  return `<div class="pagehead"><div><div class="eyebrow">Связь с клиникой</div><h1>Сообщения</h1><p>Клиника пишет, когда готов результат, пора записаться или изменился план. Ответить можно прямо здесь.</p></div></div>
    <div class="twocol"><div class="panel"><div class="chat">${state.messages.map(bubble).join('')}</div>
        <div class="composer"><input id="msgText" placeholder="Напишите координатору" autocomplete="off">${btn('Отправить', 'msgSend')}</div></div>
      <div class="stack"><div class="panel"><h3>Как вам писать</h3>
          ${[['app', 'В приложении'], ['sms', 'SMS'], ['messenger', 'В мессенджере'], ['quiet', 'Не беспокоить с 21:00 до 9:00']].map(([id, label]) => `<label class="checkline" style="margin-bottom:9px"><input type="checkbox" data-notify="${id}" ${n[id] ? 'checked' : ''}><span>${label}</span></label>`).join('')}
        </div>
        <div class="panel"><h3>Ваш координатор</h3><p>Наталья. Отвечает с 8:00 до 20:00, обычно в течение часа.</p>${btn('Перезвоните мне', 'callback', 'secondary', {id:(myEpisodes()[0] || {}).id || ''})}</div>
        <div class="note">В демо сообщения никуда не уходят. Ответ координатора можно написать в режиме сотрудника клиники.</div></div></div>`;
}

/* ---------- Аптека ---------- */
export const cartCount = () => Object.values(state.cart).reduce((a, b) => a + b, 0);
export const cartTotal = () => Object.entries(state.cart).reduce((a, [id, q]) => a + PRODUCTS.find(p => p.id === id).price * q, 0);
export const RX_STATUS = {issued:['Не получен', 'orange'], reserved:['Забронирован', 'blue'], done:['Получен', 'gray']};
export function pharmacyOtc(){
  const cat = state.sel.cat, n = cartCount();
  const items = PRODUCTS.filter(p => cat === 'all' || p.cat === cat);
  return `<div class="chips" style="margin-bottom:16px">${CATS.map(([id, label]) => `<button class="chip ${cat === id ? 'selected' : ''}" data-action="cat" data-id="${id}">${label}</button>`).join('')}</div>
    <div class="products">${items.map(p => { const q = state.cart[p.id] || 0; return `<div class="product"><div class="tile">${icon(p.icon)}</div><strong>${safe(p.name)}</strong><small>${safe(p.form)}${p.drug ? ' · лекарство без рецепта' : ''}</small><div class="price">${rub(p.price)}</div>${q ? `<div class="qty"><button data-action="cartDec" data-id="${safe(p.id)}" aria-label="Убрать одну штуку">−</button><span>${q}</span><button data-action="cartAdd" data-id="${safe(p.id)}" aria-label="Добавить ещё">+</button></div>` : btn('В корзину', 'cartAdd', 'secondary small', {id:p.id})}</div>`; }).join('')}</div>
    ${n ? `<div class="cartbar"><span>${icon('cart')} В корзине ${n} ${plural(n, ['товар', 'товара', 'товаров'])} на ${rub(cartTotal())}</span>${btn('Оформить', 'checkoutOpen', 'small')}</div>` : ''}
    <div class="note" style="margin-top:18px">Продавец — аптека-партнёр с лицензией: МедМаршрут передаёт ей заказ и сам лекарства не продаёт. У лекарств есть противопоказания, перед применением прочитайте инструкцию или спросите врача.</div>`;
}
export function pharmacyRx(){
  const list = state.prescriptions.filter(p => p.mine);
  if (!list.length) return `<div class="panel empty"><h3>Рецептов пока нет</h3><p>Электронный рецепт появится здесь, когда врач выпишет его на приёме.</p></div>`;
  return list.map(p => {
    const [lab, tone] = RX_STATUS[p.status];
    const ph = p.pharmacy && PHARMACIES.find(x => x.id === p.pharmacy);
    return `<div class="panel" style="margin-bottom:16px"><div class="pagehead" style="margin-bottom:14px"><div>${badge(lab, tone)}<h2 style="margin-top:11px">Рецепт № ${safe(p.number)}</h2></div></div>
      <dl class="kv"><dt>Врач</dt><dd>${safe(p.doctor)}</dd><dt>Выписан</dt><dd>${safe(lc(p.date))}, действует ${safe(p.valid)}</dd><dt>Препараты</dt><dd>${p.items.map(([a, b]) => `${a}, ${b}`).join('<br>')}</dd></dl>
      ${p.status === 'issued' ? `<div class="tlgroup" style="margin-top:20px">Где получить</div>${PHARMACIES.map(x => `<div class="rowline"><div><strong>${safe(x.name)}</strong><div class="meta">${safe(x.addr)} · ${safe(x.dist)}</div></div><div style="text-align:right"><strong>${safe(RX_STOCK[x.id][1])}</strong><div class="meta">${safe(RX_STOCK[x.id][0])}</div></div>${btn('Забронировать', 'rxReserve', 'small', {id:p.id, ph:x.id})}</div>`).join('')}` : ''}
      ${p.status === 'reserved' ? `<div class="note" style="margin-top:18px"><strong>Бронь в аптеке: ${safe(ph.name)}.</strong> ${safe(ph.addr)}. Код выдачи ${safe(p.code)}, бронь держат три дня. Возьмите паспорт: препарат выдадут по рецепту.</div><div class="actions">${btn('Отменить бронь', 'rxCancel', 'ghost small', {id:p.id})}</div>` : ''}
      ${p.status === 'done' ? `<div class="note" style="margin-top:18px">Препараты получены в аптеке: ${ph ? ph.name : ''}.</div>` : ''}</div>`;
  }).join('') + `<div class="note">Рецептурные препараты аптека выдаёт только по рецепту и только в аптеке. Рецепт видит та аптека-партнёр, которую вы выбрали. Названия препаратов в демо условные.</div>`;
}
export function pharmacyOrders(){
  const list = state.orders.filter(o => o.mine);
  if (!list.length) return `<div class="panel empty"><h3>Заказов пока нет</h3><p>Здесь появятся заказы без рецепта и брони по рецепту.</p></div>`;
  return `<div class="panel">${list.map(o => `<div class="rowline"><div><strong>${o.type === 'rx' ? 'Бронь' : 'Заказ'} ${safe(o.id)}</strong><div class="meta">${safe(o.items)} · ${safe(o.place)}</div></div><div class="slotprice">${safe(o.total)}</div>${badge(o.status, o.status === 'Выдан' ? 'gray' : o.status === 'Готов к выдаче' ? '' : 'blue')}</div>`).join('')}</div>`;
}
export function pharmacy(){
  const tab = state.sel.pharmTab;
  const rx = state.prescriptions.filter(p => p.mine && p.status === 'issued').length;
  const mineOrders = state.orders.filter(o => o.mine).length;
  const tabs = [['otc', 'Без рецепта'], ['rx', 'По рецепту' + (rx ? ` · ${rx}` : '')], ['orders', 'Мои заказы' + (mineOrders ? ` · ${mineOrders}` : '')]];
  return `<div class="pagehead"><div><div class="eyebrow">Аптеки-партнёры</div><h1>Аптека</h1><p>Товары без рецепта можно забрать в клинике в день приёма. Рецептурные препараты — забронировать в аптеке рядом.</p></div></div>
    <div class="tabs">${tabs.map(([id, label]) => `<button class="tab ${tab === id ? 'active' : ''}" data-action="pharmTab" data-id="${id}">${label}</button>`).join('')}</div>
    ${tab === 'otc' ? pharmacyOtc() : tab === 'rx' ? pharmacyRx() : pharmacyOrders()}`;
}
export function checkoutModal(){
  const visit = myEpisodes().flatMap(e => e.steps).find(s => s.status === 'confirmed' && s.slot && !s.slot.partner && s.slot.format !== 'Онлайн');
  const opts = [['ph0', PHARMACIES[0].name, visit ? `Заберу в день приёма: ${safe(lc(slotLine(visit.slot)))}` : 'Центральный филиал, выдача сегодня после 15:00'], ['ph1', PHARMACIES[1].name, `${safe(PHARMACIES[1].addr)} · ${safe(PHARMACIES[1].dist)}`], ['ph2', PHARMACIES[2].name, `${safe(PHARMACIES[2].addr)} · ${safe(PHARMACIES[2].dist)}`], ['delivery', 'Доставка курьером', 'Завтра с 10:00 до 14:00, 250 ₽']];
  const lines = Object.entries(state.cart).map(([id, q]) => { const p = PRODUCTS.find(x => x.id === id); return `<div class="miniRow"><span>${safe(p.name)} × ${q}</span><strong>${rub(p.price * q)}</strong></div>`; }).join('');
  openModal(`${modalHead('Заказ без рецепта', 'Как получить заказ')}${lines}<div class="miniRow"><span>Итого</span><strong>${rub(cartTotal())}</strong></div>
    <div style="margin-top:14px">${opts.map(([id, name, sub], i) => `<label class="radio"><input type="radio" name="place" value="${id}" ${i === 0 ? 'checked' : ''}><span><strong>${name}</strong><br><span class="muted">${sub}</span></span></label>`).join('')}</div>
    <div class="note">Оплата при получении. В демо заказ никуда не уходит.</div>
    <div class="actions">${btn('Оформить заказ', 'checkout')}${btn('Назад', 'close', 'secondary')}</div>`);
}

/* ---------- Документы ---------- */
export function documents(){
  const studies = state.studies.filter(s => s.mine && s.status === 'confirmed');
  const rx = state.prescriptions.filter(p => p.mine);
  const rows = [
    ...studies.map(s => `<div class="slot"><div><strong>Заключение: ${lc(DEMO[s.kind].title)}</strong><div class="meta">${safe(s.date)} · подтвердил ${safe(s.confirmedBy)}</div></div>${navBtn('Открыть', 'imaging', 'secondary small')}</div>`),
    ...rx.map(p => `<div class="slot"><div><strong>Рецепт № ${safe(p.number)}</strong><div class="meta">${safe(p.doctor)} · ${safe(lc(p.date))} · действует ${safe(p.valid)}</div></div>${btn('Открыть', 'rxTab', 'secondary small')}</div>`),
    ...(state.documentName ? [`<div class="slot"><div><strong>${safe(state.documentName)}</strong><div class="meta">Добавлен к обращению из анкеты · в прототипе сохраняется только имя файла</div></div>${btn('Убрать', 'removeDoc', 'secondary small')}</div>`] : [])
  ];
  return `<div class="pagehead"><div><div class="eyebrow">Ваши материалы</div><h1>Документы</h1><p>Заключения по исследованиям, рецепты и файлы, которые вы добавили к обращению.</p></div></div>
    <div class="panel">${rows.join('') || '<div class="empty"><h3>Документов пока нет</h3><p>Добавьте документ в анкете нового обращения.</p></div>'}<div class="actions">${btn('Новое обращение с документом', 'newDocument', 'secondary')}${btn('Загрузить снимок', 'uploadOpen', 'secondary')}</div></div>`;
}

/* ---------- Новое обращение: анкета, проверка, маршрут (из первой версии) ---------- */
export const INTAKE = ['symptoms', 'document', 'noslots', 'after'];
export function stepbar(current){
  return `<div class="steps">${['Ситуация', 'Уточнение', 'Маршрут'].map((s, i) => `${i ? '<span class="sep"></span>' : ''}<span class="step ${i <= current ? 'on' : ''}"><b>${i + 1}</b>${s}</span>`).join('')}</div>`;
}
export const scenarioPicker = () => `<div class="choiceRow">${INTAKE.map(id => `<button class="choice ${state.scenario === id ? 'selected' : ''}" data-scenario="${id}">${scenarios[id].title}</button>`).join('')}</div>`;
export function intake(){
  const kind = INTAKE.includes(state.scenario) ? state.scenario : 'symptoms';
  const x = scenarios[kind];
  return `<div class="pagehead"><div><div class="eyebrow">Новое обращение</div><h1>${x.title}</h1><p class="lead">Ответьте на несколько вопросов. Вы сможете проверить сведения перед отправкой в клинику.</p></div></div>${stepbar(1)}
    <div class="panel"><div class="field full"><label>Ваша ситуация</label>${scenarioPicker()}</div>
    <form id="intakeForm" style="margin-top:24px"><div class="formgrid">
      <div class="field full"><label for="symptoms">${kind === 'document' ? 'Что вы хотите понять по документу?' : kind === 'noslots' ? 'Почему нужна запись?' : kind === 'after' ? 'Что рекомендовал врач?' : 'Что вас беспокоит?'}</label><textarea id="symptoms" name="symptoms" placeholder="Напишите своими словами">${safe(state.symptoms)}</textarea><small>Можно кратко. Врач увидит исходный текст.</small></div>
      <div class="field"><label for="duration">Когда это началось?</label><input id="duration" name="duration" value="${safe(state.duration)}" placeholder="Например, неделю назад"></div>
      <div class="field"><label for="city">Город</label><input id="city" name="city" value="${safe(state.city)}" placeholder="Город"></div>
      <div class="field"><label for="age">Возрастная группа</label><select id="age" name="age"><option value="adult" ${state.age === 'adult' ? 'selected' : ''}>Взрослый</option><option value="child" ${state.age === 'child' ? 'selected' : ''}>Ребёнок</option></select></div>
      <div class="field"><label for="channel">Предпочтительный способ обращения</label><select id="channel" name="channel"><option value="private" ${state.channel === 'private' ? 'selected' : ''}>Платно</option><option value="dms" ${state.channel === 'dms' ? 'selected' : ''}>ДМС</option><option value="oms" ${state.channel === 'oms' ? 'selected' : ''}>ОМС</option></select></div>
      ${kind === 'noslots' ? `<div class="field"><label for="doctor">К какому врачу нужно попасть?</label><input id="doctor" name="doctor" value="${safe(state.doctor)}" placeholder="Например, к терапевту"></div><div class="field"><label for="wait">Когда есть ближайшая запись?</label><input id="wait" name="wait" value="${safe(state.wait)}" placeholder="Например, через две недели"></div>` : ''}
      ${kind === 'document' || kind === 'after' ? `<div class="field full"><label for="docFile">Добавить документ</label><input id="docFile" type="file" accept=".pdf,image/*"><small>${state.documentName ? `Сейчас выбран: ${safe(state.documentName)}. ` : ''}В демо файл не загружается на сервер и не распознаётся автоматически. Снимки КТ, МРТ, маммографии и рентгена удобнее загрузить в разделе «Что на снимке».</small></div>` : ''}
      <div class="field full"><label class="checkline"><input type="checkbox" name="redflag" ${state.redflag ? 'checked' : ''}><span><strong>Есть резкое ухудшение или другой тревожный признак</strong><br><span class="muted">Отметьте, если считаете, что помощь может требоваться сейчас. В реальном сервисе здесь будут проверенные вопросы.</span></span></label></div>
    </div><div class="actions"><button class="btn" type="submit">Продолжить →</button><button class="btn ghost" type="button" data-nav="home">Вернуться на главную</button></div></form></div>`;
}
export function review(){
  return `<div class="pagehead"><div><div class="eyebrow">Шаг 2 из 3</div><h1>Проверьте данные</h1><p>Исправьте сведения, прежде чем мы составим маршрут.</p></div></div>${stepbar(1)}
    <div class="twocol"><div class="panel"><h3>Ваше обращение</h3>
        <div class="miniRow"><span>Ситуация</span><strong>${safe((scenarios[state.scenario] || scenarios.symptoms).title)}</strong></div>
        <div class="miniRow"><span>Описание</span><strong style="max-width:65%">${safe(state.symptoms || 'Не указано')}</strong></div>
        <div class="miniRow"><span>Началось</span><strong>${safe(state.duration || 'Не указано')}</strong></div>
        <div class="miniRow"><span>Город</span><strong>${safe(state.city)}</strong></div>
        <div class="miniRow"><span>Документ</span><strong>${safe(state.documentName || 'Не добавлен')}</strong></div>
        <div class="actions">${navBtn('Исправить ответы', 'intake', 'secondary')}</div></div>
      <div class="stack"><div class="panel"><h3>Что извлечено из документа?</h3><p>Для анализов и выписок распознавание в прототипе не подключено. Если нужно, вручную добавьте важные сведения для врача.</p><div class="field"><label for="documentNotes">Заметки по документу</label><textarea id="documentNotes" placeholder="Например, дата исследования и показатели, которые хотите обсудить">${safe(state.documentNotes)}</textarea></div></div>
        <div class="note">Не отправляйте реальные медицинские документы при тестировании прототипа. Сведения остаются в этой вкладке до обновления страницы.</div></div></div>
    <div class="actions">${btn('Составить маршрут →', 'createRoute')}</div>`;
}
export function routeByChannel(){
  const c = {private:['Платный приём', 'Выберите специалиста, филиал и доступное время в расписании клиники.'], dms:['Приём по ДМС', 'Проверьте, входит ли услуга в вашу программу и нужно ли согласование со страховой.'], oms:['Маршрут по ОМС', 'Уточните порядок обращения через поликлинику и необходимость направления.']}[state.channel];
  return `<h3>${c[0]}</h3><p>${c[1]}</p><ol class="routeSteps"><li><b>1</b><span>Уточните подходящий формат консультации.</span></li><li><b>2</b><span>Выберите запись или передайте запрос координатору.</span></li><li><b>3</b><span>Возьмите документы и выжимку для врача.</span></li></ol><div class="actions">${btn('Выбрать время', 'bookOwn')}</div>`;
}
export function result(){
  if (!state.routeCreated) return `<div class="empty"><h2>Маршрут пока не составлен</h2>${btn('Начать обращение', 'new')}</div>`;
  if (state.redflag) return `<div class="eyebrow">Проверка срочности</div><h1>Обратитесь за срочной помощью</h1><div class="note red"><strong>Вы отметили тревожный признак.</strong> Не ожидайте плановой записи через сервис. Позвоните 103 или 112 для получения экстренной помощи.</div><div class="actions"><a class="btn danger" href="tel:103">Позвонить 103</a><a class="btn secondary" href="tel:112">Позвонить 112</a>${navBtn('Исправить ответ', 'intake', 'ghost')}</div><div class="note" style="margin-top:25px">Это демонстрационный экран. Прототип не оценивает симптомы и не должен использоваться для принятия решений о здоровье.</div>`;
  return `<div class="pagehead"><div><div class="eyebrow">Персональный план обращения</div><h1>Ваш МедМаршрут</h1><p>По обращению «${safe((scenarios[state.scenario] || scenarios.symptoms).title)}»</p></div><div class="actions">${btn('Скопировать для врача', 'copySummary', 'secondary')}</div></div>
    <div class="resulttop"><div class="resultmain"><div class="eyebrow">Следующий шаг</div><strong class="big">${state.scenario === 'after' ? 'Уточнить план у лечащего врача' : 'Начать с консультации терапевта'}</strong><p style="margin:13px 0 0">Прототип показывает пример маршрута. В рабочем продукте этот вывод потребует медицинской проверки и правил клиники.</p><div class="actions">${btn('Посмотреть запись →', 'bookOwn')}${navBtn('Открыть мой план', 'plan', 'secondary')}</div></div>
      <div class="panel"><div class="eyebrow">По вашему обращению</div><div class="miniRow"><span>Возраст</span><strong>${state.age === 'child' ? 'Ребёнок' : 'Взрослый'}</strong></div><div class="miniRow"><span>Началось</span><strong>${safe(state.duration || 'Не указано')}</strong></div><div class="miniRow"><span>Город</span><strong>${safe(state.city || 'Не указан')}</strong></div><div class="miniRow"><span>Документ</span><strong>${safe(state.documentName || 'Нет')}</strong></div><div class="actions">${navBtn('Изменить ответы', 'intake', 'ghost small')}</div></div></div>
    <div class="sectionhead"><h2>Как можно обратиться</h2><span class="muted">Выберите удобный канал</span></div>
    <div class="tabs">${[['private', 'Платно'], ['dms', 'ДМС'], ['oms', 'ОМС']].map(([id, label]) => `<button class="tab ${state.channel === id ? 'active' : ''}" data-channel="${id}">${label}</button>`).join('')}</div>
    <div class="grid two"><div class="panel">${routeByChannel()}</div><div class="panel"><h3>Если записи нет</h3><p>Проверьте другой филиал, клинику-партнёра или формат консультации. Если доступные даты вам не подходят, передайте обращение координатору клиники.</p><div class="actions">${btn('Что делать без записи', 'noSlots', 'secondary')}</div></div></div>
    <div class="sectionhead"><h2>Подготовка к приёму</h2></div>
    <div class="grid three"><div class="card"><h3>Что взять</h3><p>Оригиналы анализов и выписок, список принимаемых лекарств, прошлые заключения по этой теме.</p></div><div class="card"><h3>Что спросить</h3><p>Какой следующий шаг? Нужно ли наблюдение? Когда повторно обращаться при изменении состояния?</p></div><div class="card"><h3>Для врача</h3><p>Краткая выжимка ваших ответов и документов. Перед отправкой её можно проверить.</p><div class="cardfoot">${btn('Посмотреть выжимку →', 'summary', 'ghost small')}</div></div></div>
    <div class="note warn" style="margin-top:20px">В этом прототипе медицинская логика демонстрационная. Он не оценивает симптомы и не должен использоваться для принятия решений о здоровье.</div>`;
}
export function summaryText(){
  return `МедМаршрут — выжимка для врача\nСитуация: ${(scenarios[state.scenario] || scenarios.symptoms).title}\nСо слов пациента: ${state.symptoms || 'не указано'}\nНачало: ${state.duration || 'не указано'}\nВозрастная группа: ${state.age === 'child' ? 'ребёнок' : 'взрослый'}\nДокумент: ${state.documentName || 'не добавлен'}\nЗаметки: ${state.documentNotes || 'нет'}\nПредпочтительный канал: ${{private:'платно', dms:'ДМС', oms:'ОМС'}[state.channel]}\nТревожный признак отмечен: ${state.redflag ? 'да' : 'нет'}\nДанные введены пациентом; требуют проверки врачом.`;
}
/* Обращение из анкеты становится таким же эпизодом, как маршрут после исследования */
export function createOwnEpisode(){
  state.episodes = state.episodes.filter(e => e.id !== 'own');
  const sc = scenarios[state.scenario] || scenarios.symptoms;
  const e = {id:'own', patient:patientName(), mine:true, kind:'intake', title:'Обращение: ' + lc(sc.title), opened:'Только что', status:'active', reason:'', ruleId:'own', profile:[state.age === 'child' ? 'Ребёнок' : 'Взрослый', {private:'Платный приём', dms:'Полис ДМС', oms:'Полис ОМС'}[state.channel], 'Город: ' + (state.city || 'не указан')], steps:[], log:[]};
  addLog(e, 'Пациент', 'Обращение заполнено в личном кабинете');
  if (state.redflag){ e.status = 'manual_review'; e.urgent = true; e.reason = 'Пациент отметил тревожный признак: показан экран срочной помощи'; addLog(e, 'Маршрутизатор', e.reason); }
  else { mkStep(e, state.scenario === 'after' ? 'attending' : 'gp', 1, 'Демо-маршрут из анкеты', ''); addLog(e, 'Маршрутизатор', 'Предложен демонстрационный маршрут: ' + lc(title(e.steps[0]))); }
  state.episodes.unshift(e);
}

