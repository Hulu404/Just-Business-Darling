import { DEMO, PARTNERS, PHARMACIES, PRODUCTS, RX_STOCK, scenarios, slotsFor } from './demo-data.js';
import { addLog, analyze, attendStep, bookStep, byKey, confirmRoute, createEpisodeFromStudy, currentStep, ep, live, mkRequest, myEpisodes, notify, offerStep, pushMsg, refKey, refuseStep, reopenStep, savePlan, slotLine, stepOf, studyOf, title, unbookStep, upsertReferral } from './domain.js';
import { doctor, planModal, reading, study } from './pages/doctor.js';
import { REASONS, appointments, cartTotal, checkoutModal, createOwnEpisode, documents, home, imaging, intake, laterModal, messages, pharmacy, plan, result, review, slotAskModal, summaryText, uploadModal } from './pages/patient.js';
import { services } from './pages/services.js';
import { REF_FLOW, analytics, calcOut, casePage, comms, inbox, partners, pharmacyAdmin, reqNewModal, requests, rules, sampleText, scheduling, slotListModal, who, writeModal } from './pages/staff.js';
import { HOME, render, renderShell } from './shell.js';
import { freshState, patientName, setState, staffName, state, ui } from './state.js';
import { $, $$, btn, closeModal, go, lc, modalHead, navBtn, openModal, plural, rub, safe, toast } from './ui.js';

/* =====================================================================
   Действия и события
   ===================================================================== */
export const PAGES = {home, intake, review, result, plan, imaging, appointments, messages, pharmacy, documents, inbox, case:casePage, scheduling, requests, comms, partners, pharmacyAdmin, rules, analytics, reading, study, doctor, services};
export let orderNo = 1040, reserveNo = 217;
export const actor = () => state.role === 'patient' ? 'Пациент' : state.role === 'doctor' ? 'Врач' : staffName();
export const clearIntake = () => { Object.assign(state, {symptoms:'', duration:'', redflag:false, doctor:'', wait:'', documentName:'', documentNotes:'', routeCreated:false}); state.episodes = state.episodes.filter(e => e.id !== 'own'); };

export function formValues(){
  const data = new FormData($('#intakeForm'));
  return {symptoms:data.get('symptoms') || '', duration:data.get('duration') || '', city:data.get('city') || '', age:data.get('age'), channel:data.get('channel'), doctor:data.get('doctor') || state.doctor, wait:data.get('wait') || state.wait, redflag:data.has('redflag')};
}
export function advanceReferral(r){
  const i = REF_FLOW.indexOf(r.status);
  const e = r.episodeId && ep(r.episodeId), s = e && stepOf(e, r.stepId);
  if (i === 0 && s){ slotListModal(refKey(e, s), 'staff'); return; }
  if (i < 0 || i >= REF_FLOW.length - 1) return;
  r.status = REF_FLOW[i + 1];
  if (s && r.status === 'Услуга оказана'){ s.status = 'attended'; addLog(e, PARTNERS[r.partner].name, 'Услуга оказана: ' + title(s)); }
  if (s && r.status === 'Результат получен'){
    s.status = 'completed'; s.outcome = 'Результат от партнёра получен';
    addLog(e, PARTNERS[r.partner].name, 'Результат передан в клинику: ' + title(s));
    notify(e, 'Результат от партнёра', `Результат от партнёра уже в вашем плане: ${lc(title(s))}. Врач посмотрит его и назначит следующий шаг.`, [['Открыть план', 'nav', 'plan']]);
    if (!e.steps.some(live)){
      e.status = 'manual_review'; e.suggest = []; e.reason = 'Пришёл результат от партнёра: врач назначает следующий шаг';
      mkRequest(e, 'staff', 'route', 'Результат от партнёра', `${e.patient}: пришёл результат от партнёра (${lc(title(s))}). Посмотрите и назначьте следующий шаг.`);
    }
  }
  render();
  toast('Направление: ' + lc(r.status));
}

export const ACTIONS = {
  menu(){ ui.mobileOpen = !ui.mobileOpen; renderShell(); },
  close(){ closeModal(); },
  reset(){ const {role, page} = state; setState(freshState()); Object.assign(state, {role, page}); ui.mobileOpen = false; ui.modal = null; orderNo = 1040; reserveNo = 217; render(); window.scrollTo(0, 0); toast('Демо возвращено к началу'); },

  /* --- новое обращение (первая версия) --- */
  new(){ clearIntake(); state.scenario = 'symptoms'; state.role = 'patient'; go('intake'); },
  newDocument(){ state.scenario = 'document'; go('intake'); },
  how(){
    openModal(`${modalHead('', 'Как работает МедМаршрут')}<ol><li>Вы проходите исследование или рассказываете о ситуации. Снимок из другой клиники можно загрузить.</li><li>ИИ готовит черновик заключения, врач его подтверждает. Мы объясняем результат простыми словами.</li><li>Вы видите следующий шаг и записываетесь в клинике или у партнёра.</li><li>После приёма врач обновляет план. Рецепт и аптека — там же.</li></ol><p>Для сотрудников клиники есть очередь обращений, связь с врачом и пациентом, контроль качества.</p><div class="actions">${btn('Начать', 'new')}${navBtn('Карта сервисов', 'services', 'secondary')}</div>`);
  },
  createRoute(){ toast('Пока недоступно на стенде'); }, // Задание 07
  bookOwn(){ const e = ep('own'), s = e && currentStep(e); if (s){ state.sel.book = refKey(e, s); state.sel.slotTab = 'all'; go('appointments'); } else go('plan'); },
  async copySummary(){
    try { await navigator.clipboard.writeText(summaryText()); toast('Выжимка скопирована'); }
    catch (err){ openModal(`${modalHead('', 'Выжимка для врача')}<textarea style="width:100%;height:260px">${safe(summaryText())}</textarea>`); }
  },
  summary(){ openModal(`${modalHead('', 'Выжимка для врача')}<p>Проверьте содержание перед передачей врачу.</p><textarea style="width:100%;height:260px">${safe(summaryText())}</textarea><div class="actions">${btn('Скопировать', 'copySummary')}</div>`); },
  noSlots(){
    openModal(`${modalHead('Если записи нет', 'Проверим другие варианты')}<ol><li>Другой филиал или время.</li><li>Клиника-партнёр: направление и заключение передадим сами.</li><li>Дистанционная консультация, если это уместно.</li><li>Помощь координатора клиники.</li></ol><div class="note warn">Если состояние изменилось или вызывает тревогу, не ориентируйтесь на дату плановой записи.</div><div class="actions">${btn('Запросить помощь координатора', 'coordinator')}${btn('Посмотреть время', 'bookOwn', 'secondary')}</div>`);
  },
  coordinator(){ const e = ep('own') || myEpisodes()[0]; if (e) ACTIONS.callback({id:e.id}); else { closeModal(); toast('Задача добавлена в очередь клиники'); } },
  removeDoc(){ state.documentName = ''; render(); toast('Документ убран из обращения'); },

  /* --- запись --- */
  book(d){ state.sel.book = d.key; state.sel.slotTab = 'all'; state.role = 'patient'; go('appointments'); },
  slotTab(d){ state.sel.slotTab = d.id; render(); },
  slotAsk(d){ slotAskModal(d.key, d.slot, d.mode); },
  slotList(d){ slotListModal(d.key, d.mode); },
  slotConfirm(d){
    const [e, s] = byKey(d.key);
    const slot = slotsFor(s.service).find(x => x.id === d.slot);
    closeModal();
    if (d.mode === 'offer'){ offerStep(e, s, slot); render(); toast('Предложение отправлено пациенту'); }
    else if (d.mode === 'staff'){ bookStep(e, s, slot, 'staff'); render(); toast('Пациент записан: ' + lc(slotLine(slot))); }
    else { bookStep(e, s, slot, 'patient'); state.sel.book = null; go('plan'); toast('Демонстрационная запись сохранена'); }
  },
  accept(d){ const [e, s] = byKey(d.key); if (s && s.status === 'offered'){ bookStep(e, s, s.slot, 'patient'); toast('Запись подтверждена'); } go('plan'); },
  unbook(d){ const [e, s] = byKey(d.key); if (s && s.status === 'confirmed'){ unbookStep(e, s, actor()); toast('Запись отменена'); } render(); },
  later(d){ laterModal(d.key); },
  laterSend(d){
    const [e, s] = byKey(d.key);
    const r = $('input[name=reason]:checked');
    const reason = r ? r.value : REASONS[4];
    refuseStep(e, s, reason);
    pushMsg('patient', 'Пока откладываю запись: ' + lc(reason) + '.');
    closeModal(); go('plan'); toast('Координатор увидит причину и предложит другой вариант');
  },
  reopen(d){
    const [e, s] = byKey(d.key);
    if (!s) return;
    reopenStep(e, s, actor());
    if (state.role === 'patient'){ state.sel.book = d.key; state.sel.slotTab = 'all'; go('appointments'); }
    else { render(); toast('Шаг снова в работе'); }
  },
  callback(d){
    const e = ep(d.id) || myEpisodes()[0];
    if (!e) return;
    e.callback = true;
    addLog(e, 'Пациент', 'Просит перезвонить');
    pushMsg('patient', 'Перезвоните мне, пожалуйста.');
    closeModal(); render(); toast('Задача добавлена в очередь клиники');
  },

  /* --- сообщения пациента --- */
  msgSend(){
    const i = $('#msgText'), text = i && i.value.trim();
    if (!text) return;
    pushMsg('patient', text);
    const e = myEpisodes().find(x => !['completed', 'closed'].includes(x.status)) || myEpisodes()[0];
    if (e){ e.callback = true; addLog(e, 'Пациент', 'Сообщение координатору: ' + text); }
    render();
  },
  msgAct(d){
    const k = d.kind, a = d.arg;
    if (k === 'nav'){ go(a); return; }
    if (k === 'rxTab'){ ACTIONS.rxTab(); return; }
    if (k === 'orders'){ state.sel.pharmTab = 'orders'; go('pharmacy'); return; }
    if (k === 'callback'){ ACTIONS.callback({id:a}); return; }
    const [e, s] = byKey(a);
    const stale = () => { go('plan'); toast('Этот шаг уже изменился: открыли план'); };
    if (!e || !s || ['manual_review', 'completed', 'closed'].includes(e.status)){ stale(); return; }
    if (k === 'accept'){ if (s.status === 'offered') ACTIONS.accept({key:a}); else stale(); return; }
    if (k === 'later'){ if (['open', 'offered'].includes(s.status)) laterModal(a); else stale(); return; }
    if (k === 'book'){
      if (s.status === 'refused') reopenStep(e, s, 'Пациент');
      if (['open', 'offered', 'confirmed'].includes(s.status)){ state.sel.book = a; state.sel.slotTab = 'all'; go('appointments'); } else stale();
    }
  },

  /* --- аптека --- */
  pharmTab(d){ state.sel.pharmTab = d.id; render(); },
  rxTab(){ state.role = 'patient'; state.sel.pharmTab = 'rx'; go('pharmacy'); },
  cat(d){ state.sel.cat = d.id; render(); },
  cartAdd(d){ state.cart[d.id] = (state.cart[d.id] || 0) + 1; render(); },
  cartDec(d){ const q = (state.cart[d.id] || 0) - 1; if (q > 0) state.cart[d.id] = q; else delete state.cart[d.id]; render(); },
  checkoutOpen(){ checkoutModal(); },
  checkout(){
    const r = $('input[name=place]:checked'), id = r ? r.value : 'ph0';
    const place = id === 'delivery' ? 'Доставка курьером' : PHARMACIES.find(x => x.id === id).name;
    const items = Object.entries(state.cart).map(([pid, q]) => PRODUCTS.find(x => x.id === pid).name + (q > 1 ? ` × ${q}` : '')).join(', ');
    const o = {id:'З-' + (++orderNo), type:'otc', patient:patientName(), mine:true, items, total:rub(cartTotal() + (id === 'delivery' ? 250 : 0)), place, status:'Собирается'};
    state.orders.unshift(o); state.cart = {}; state.sel.pharmTab = 'orders';
    closeModal(); render(); toast(`Заказ ${o.id} оформлен`);
  },
  rxReserve(d){
    const p = state.prescriptions.find(x => x.id === d.id), ph = PHARMACIES.find(x => x.id === d.ph);
    p.status = 'reserved'; p.pharmacy = ph.id; p.code = String(4800 + (++ui.seq % 100));
    state.orders.unshift({id:'Б-0' + (++reserveNo), type:'rx', patient:p.patient, mine:p.mine, items:`Рецепт № ${p.number}, ${p.items.length} ${plural(p.items.length, ['препарат', 'препарата', 'препаратов'])}`, total:RX_STOCK[ph.id][1], place:ph.name, status:'Забронировано', rxId:p.id});
    render(); toast('Бронь оформлена, код выдачи ' + p.code);
  },
  rxCancel(d){ const p = state.prescriptions.find(x => x.id === d.id); state.orders = state.orders.filter(o => o.rxId !== p.id); p.status = 'issued'; p.pharmacy = null; p.code = null; render(); toast('Бронь отменена'); },
  orderAdvance(d){
    const o = state.orders.find(x => x.id === d.id);
    const next = o.type === 'otc' ? {'Собирается':'Готов к выдаче', 'Готов к выдаче':'Выдан'}[o.status] : {'Забронировано':'Выдан'}[o.status];
    if (!next) return;
    o.status = next;
    if (o.type === 'rx' && next === 'Выдан'){ const p = state.prescriptions.find(x => x.id === o.rxId); if (p) p.status = 'done'; }
    if (o.mine && next === 'Готов к выдаче') pushMsg('clinic', `Заказ ${o.id} готов к выдаче: ${lc(o.place)}.`, [['Мои заказы', 'orders', '']]);
    render(); toast('Статус: ' + lc(next));
  },

  /* --- что на снимке --- */
  uploadOpen(){ state.role = 'patient'; go('imaging'); uploadModal(); },
  upload(){
    toast('Пока недоступно на стенде'); // Задание 05
  },
  studyOpen(d){ state.sel.study = d.id; go('study'); },
  studyConfirm(d){
    toast('Пока недоступно на стенде'); // Задание 05
  },
  studyManual(){ toast('Пока недоступно на стенде'); }, // Задание 05

  /* --- координатор --- */
  inboxTab(d){ state.sel.inboxTab = d.id; render(); },
  attend(d){ const [e, s] = byKey(d.key); attendStep(e, s); render(); toast('Визит отмечен. Обращение ждёт итога врача'); },
  stopEp(d){
    const e = ep(d.id);
    e.steps.filter(live).forEach(s => { s.status = 'superseded'; });
    e.status = 'closed'; e.reason = 'Сопровождение остановлено: ' + lc(e.reason || 'по решению клиники');
    addLog(e, staffName(), e.reason);
    render(); toast('Сопровождение остановлено');
  },
  askDoctor(d){
    const e = ep(d.id), st = e.kind === 'imaging' ? studyOf(e) : null;
    if (e.status === 'active'){ e.status = 'manual_review'; e.suggest = []; e.reason = 'Активных шагов нет: нужен план врача'; }
    const r = mkRequest(e, 'staff', 'route', 'Подтвердить маршрут', `${e.patient}${st ? ', ' + lc(DEMO[st.kind].title) : ''}. ${e.reason}.`);
    addLog(e, staffName(), 'Запрос врачу: подтвердить маршрут');
    state.sel.request = r.id;
    render(); toast('Запрос отправлен врачу');
  },
  nudgeDoctor(d){
    const e = ep(d.id);
    const r = mkRequest(e, 'staff', 'other', 'Нужен итог приёма', `${e.patient}: визит состоялся, а итога приёма пока нет. Без него не можем записать пациента дальше.`);
    addLog(e, staffName(), 'Напоминание врачу: нужен итог приёма');
    state.sel.request = r.id;
    render(); toast('Напоминание отправлено врачу');
  },
  writeOpen(d){ writeModal(d.id); },
  writeSend(d){
    const e = ep(d.id), text = $('#wrText').value.trim(), s = currentStep(e);
    if (!text){ toast('Сообщение пустое'); return; }
    state.outbox.unshift({t:'Только что', patient:e.patient, event:'Сообщение координатора', channel:'Приложение', status:'Доставлено', episodeId:e.id});
    if (e.mine) pushMsg('clinic', text, s && ['open', 'offered'].includes(s.status) ? [['Выбрать время', 'book', refKey(e, s)]] : []);
    e.callback = false;
    addLog(e, staffName(), 'Сообщение пациенту: ' + text);
    closeModal(); render(); toast('Сообщение отправлено');
  },
  refAdvance(d){ advanceReferral(state.referrals.find(x => x.id === d.id)); },
  refStep(d){ const [e, s] = byKey(d.key); advanceReferral(state.referrals.find(x => x.episodeId === e.id && x.stepId === s.id) || upsertReferral(e, s, 'Записан у партнёра')); },
  partnersTab(d){ state.sel.partnersTab = d.id; render(); },
  ruleToggle(d){
    state.ruleApproved[d.id] = !state.ruleApproved[d.id];
    if (state.sandbox.result) state.sandbox.result = analyze(state.sandbox.text);
    render();
    toast(state.ruleApproved[d.id] ? `Правило ${d.id} утверждено: новые заключения пойдут по нему` : `Правило ${d.id} в черновике: такие случаи уйдут на ручной разбор`);
  },
  sample(d){ state.sel.sample = d.id; state.sandbox.text = sampleText(d.id); state.sandbox.result = analyze(state.sandbox.text); render(); },
  sandboxRun(){ state.sandbox.text = $('#sbText').value; state.sandbox.result = analyze(state.sandbox.text); render(); },
  funnel(d){ state.sel.funnel = d.id; render(); },

  /* --- врач — клиника --- */
  reqOpen(d){ state.sel.request = d.id; if (state.page !== 'requests') go('requests'); else render(); },
  reqSend(d){
    const r = state.requests.find(x => x.id === d.id), i = $('#reqText'), text = i && i.value.trim();
    if (!r || !text) return;
    r.msgs.push({from:state.role === 'doctor' ? 'doctor' : 'staff', t:'Только что', text});
    render();
  },
  reqClose(d){ const r = state.requests.find(x => x.id === d.id); if (r) r.status = 'closed'; render(); toast('Запрос закрыт'); },
  reqNew(d){ reqNewModal(d.id || ''); },
  reqCreate(){
    const e = ep($('#rqEp').value), text = $('#rqText').value.trim(), topic = $('#rqTopic').value;
    if (!e || !text){ toast('Опишите, что нужно'); return; }
    const me = state.role === 'doctor' ? 'doctor' : 'staff';
    const r = mkRequest(e, me, 'other', topic, text);
    addLog(e, who(me), 'Запрос: ' + lc(topic));
    state.sel.request = r.id;
    closeModal(); go('requests'); toast('Запрос отправлен');
  },
  routeOk(d){
    const e = ep(d.id);
    if (!e || e.status !== 'manual_review') return;
    confirmRoute(e);
    render(); toast('Маршрут подтверждён. Пациент получил план, координатор — задачу на запись');
  },
  planOpen(d){ planModal(d.id, d.step || ''); },
  planSave(d){
    const e = ep(d.id), s = d.step ? stepOf(e, d.step) : null;
    const chosen = $$('[data-next]:checked').map(i => i.dataset.next);
    const rx = $('#outRx') ? $('#outRx').checked : false;
    const summary = $('#outSummary') ? ($('#outSummary').value.trim() || 'Итог внесён') : '';
    if (s && s.status === 'confirmed') attendStep(e, s);
    savePlan(e, s, chosen, rx, summary);
    closeModal(); render();
    toast(chosen.length ? 'Сохранено. Пациент видит новые шаги, координатор получил задачу на запись' : 'Сохранено. Новых шагов нет');
  }
};

document.addEventListener('submit', e => {
  if (e.target.id === 'intakeForm'){ e.preventDefault(); Object.assign(state, formValues()); go('review'); }
});
document.addEventListener('change', e => {
  const t = e.target;
  if (t.id === 'role'){ state.role = t.value; go(HOME[state.role]); return; }
  if (t.id === 'docFile'){ state.documentName = t.files && t.files[0] ? t.files[0].name : ''; toast(state.documentName ? 'Имя файла добавлено к обращению' : 'Файл не выбран'); return; }
  if (t.dataset.rule){ state.rules[t.dataset.rule] = t.checked; toast('Настройка сохранена до обновления страницы'); }
  if (t.dataset.trigger){ state.triggers[t.dataset.trigger] = t.checked; toast(t.checked ? 'Сценарий включён' : 'Сценарий выключен'); }
  if (t.dataset.notify){ state.notify[t.dataset.notify] = t.checked; toast('Настройка уведомлений сохранена'); }
});
document.addEventListener('input', e => {
  const t = e.target;
  if (t.id === 'slice'){
    const v = Number(t.value), k = 1 - Math.abs(v - 142) * 0.012;
    $('#sliceLabel').textContent = `Срез ${v} из 310`;
    const mark = $('#ctMark'), lungs = $('#ctLungs');
    if (mark) mark.style.display = Math.abs(v - 142) <= 3 ? '' : 'none';
    if (lungs) lungs.setAttribute('transform', `translate(180 152) scale(${k.toFixed(3)}) translate(-180 -152)`);
  }
  if (t.dataset.calc){ state.calc[t.dataset.calc] = Math.max(0, Number(t.value) || 0); $('#calcOut').innerHTML = calcOut(); }
  if (t.id === 'sbText') state.sandbox.text = t.value;
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && ui.modal){ closeModal(); return; }
  if (e.key === 'Enter' && e.target.id === 'msgText'){ e.preventDefault(); ACTIONS.msgSend(); }
  if (e.key === 'Enter' && e.target.id === 'reqText'){ e.preventDefault(); const b = $('[data-action=reqSend]'); if (b) b.click(); }
  if ((e.key === 'Enter' || e.key === ' ') && e.target.classList && e.target.classList.contains('clickable')){ e.preventDefault(); e.target.click(); }
});
document.addEventListener('click', e => {
  if (e.target.classList && e.target.classList.contains('modalshade')){ closeModal(); return; }
  if (ui.mobileOpen && !e.target.closest('#sidebar') && !e.target.closest('.mobilemenu')){ ui.mobileOpen = false; renderShell(); }
  const t = e.target.closest('[data-nav],[data-action],[data-scenario],[data-channel],[data-case],[data-jump]');
  if (!t) return;
  const d = t.dataset;
  if (d.nav){ go(d.nav); return; }
  if (d.jump){
    const [role, page, tab] = d.jump.split(':');
    state.role = role;
    if (page === 'pharmacy' && tab) state.sel.pharmTab = tab;
    if (page === 'partners' && tab) state.sel.partnersTab = tab;
    if (page === 'appointments') state.sel.slotTab = 'all';
    go(page); return;
  }
  if (d.scenario){
    const x = scenarios[d.scenario];
    if (x.direct === 'upload'){ ACTIONS.uploadOpen(); return; }
    if (x.direct === 'pharmacy'){ state.sel.pharmTab = 'otc'; go('pharmacy'); return; }
    if (state.page === 'home') clearIntake();
    else if ($('#intakeForm')) Object.assign(state, formValues());
    state.scenario = d.scenario; go('intake'); return;
  }
  if (d.channel){ state.channel = d.channel; render(); return; }
  if (d.case){ state.sel.episode = d.case; go('case'); return; }
  const fn = ACTIONS[d.action];
  if (fn) fn(d, t);
});
