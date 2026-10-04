import { actor } from './actions.js';
import { DEMO, MOD_LABEL, NEXT, PARTNERS, RULES, SERVICES, partnerOnly, slotsFor } from './demo-data.js';
import { doctor } from './pages/doctor.js';
import { pharmacy } from './pages/patient.js';
import { who } from './pages/staff.js';
import { staffName, state, ui } from './state.js';
import { badge, lc, safe } from './ui.js';

/* ---------- Доменные функции: эпизод, шаги, заключение ---------- */
export const ep = id => state.episodes.find(e => e.id === id);
export const stepOf = (e, id) => e && e.steps.find(s => s.id === id);
export const studyOf = e => state.studies.find(s => s.id === e.studyId);
export const title = s => (SERVICES[s.service] || {title:s.service}).title;
export const myEpisodes = () => state.episodes.filter(e => e.mine);
export const live = s => !['completed', 'superseded'].includes(s.status);
export const currentStep = e => e.steps.find(live) || null;
export const slotLine = slot => slot ? `${slot.date}, ${slot.time}` : '';
export const slotFull = slot => slot ? `${slot.date}, ${slot.time} · ${slot.who} · ${slot.place}` : '';
export const refKey = (e, s) => `${e.id}:${s.id}`;
export function byKey(key){ const [eid, sid] = String(key || '').split(':'); const e = ep(eid); return [e, stepOf(e, sid)]; }
export function wherePartner(s){
  if (s.slot) return s.slot.partner || null;
  const list = slotsFor(s.service);
  return list.every(x => x.partner) ? list[0].partner : null;
}
export const whereBadge = s => { const p = wherePartner(s); return p ? badge('Партнёр: ' + PARTNERS[p].name, 'violet') : ''; };

export function addLog(e, who, text){ e.log.push({t:'Только что', who, text}); }
export function pushMsg(from, text, actions){ state.messages.push({id:'m' + (++ui.seq), from, t:'Только что', text, actions:actions || [], unread:from === 'clinic'}); }
/* Сообщение пациенту от клиники: попадает в журнал отправок, а демо-пациенту ещё и в переписку */
export function notify(e, event, text, actions){
  state.outbox.unshift({t:'Только что', patient:e.patient, event, channel:'Приложение', status:'Доставлено', episodeId:e.id});
  if (e.mine) pushMsg('clinic', text, actions);
}
export function mkStep(e, service, cycle, by, due){
  const s = {id:e.id + 's' + (e.steps.length + 1), cycle, service, status:'open', due:due || '', by, slot:null};
  e.steps.push(s);
  return s;
}
export function upsertReferral(e, s, status){
  let r = state.referrals.find(x => x.episodeId === e.id && x.stepId === s.id);
  if (!r){ r = {id:'rf' + (++ui.seq), patient:e.patient, service:s.service, partner:wherePartner(s), status, episodeId:e.id, stepId:s.id}; state.referrals.unshift(r); }
  else { r.status = status; r.partner = wherePartner(s) || r.partner; }
  return r;
}
export function resume(e){ e.callback = false; if (e.status === 'paused'){ e.status = 'active'; e.reason = ''; } }

export function bookStep(e, s, slot, actor){
  s.status = 'confirmed'; s.slot = slot; s.overdue = false; resume(e);
  addLog(e, actor === 'patient' ? 'Пациент' : staffName(), `${actor === 'patient' ? 'Запись из личного кабинета' : 'Запись по звонку'}: ${title(s)} — ${lc(slotLine(slot))}`);
  if (slot.partner) upsertReferral(e, s, 'Записан у партнёра');
  notify(e, 'Подтверждение записи', `Вы записаны: ${lc(title(s))}, ${lc(slotLine(slot))}, ${slot.place}.${slot.partner ? ' Направление и заключение уже у партнёра.' : ''}`, [['Открыть план', 'nav', 'plan']]);
}
export function offerStep(e, s, slot){
  s.status = 'offered'; s.slot = slot; resume(e);
  addLog(e, staffName(), `Предложено время: ${title(s)} — ${lc(slotLine(slot))}`);
  notify(e, 'Предложена запись', `Предлагаем время: ${lc(title(s))}, ${lc(slotLine(slot))}, ${slot.place}. Подходит?`, [['Подтвердить', 'accept', refKey(e, s)], ['Другое время', 'book', refKey(e, s)]]);
}
export function attendStep(e, s){ s.status = 'attended'; addLog(e, 'Регистратура', 'Визит состоялся: ' + title(s)); }
export function unbookStep(e, s, who){
  const ref = state.referrals.find(r => r.episodeId === e.id && r.stepId === s.id && r.status === 'Записан у партнёра');
  if (ref){
    if (partnerOnly(s.service)) ref.status = 'Ожидает записи';
    else state.referrals = state.referrals.filter(r => r !== ref);
  }
  addLog(e, who, `Запись отменена: ${title(s)} — ${lc(slotLine(s.slot))}`);
  s.status = 'open'; s.slot = null;
}
export function refuseStep(e, s, reason){
  s.status = 'refused'; e.status = 'paused'; e.reason = reason;
  addLog(e, 'Пациент', 'Отложил шаг «' + title(s) + '»: ' + lc(reason));
}
export function reopenStep(e, s, who){
  s.status = 'open'; s.slot = null; resume(e); e.status = 'active'; e.reason = '';
  addLog(e, who, 'Шаг возвращён в работу: ' + title(s));
}
export function closeRequests(e, kind, text){
  state.requests.forEach(r => {
    if (r.episodeId === e.id && r.status === 'open' && (!kind || r.kind === kind)){
      r.msgs.push({from:'doctor', t:'Только что', text});
      r.status = 'closed';
    }
  });
}
export function mkRequest(e, from, kind, subject, text){
  const r = {id:'r' + (++ui.seq), episodeId:e.id, from, kind, subject, status:'open', t:'Только что', msgs:[{from, t:'Только что', text}]};
  state.requests.unshift(r);
  state.sel.request = r.id;
  return r;
}
export const waitingOn = r => r.msgs[r.msgs.length - 1].from === 'staff' ? 'doctor' : 'staff';

export function createPrescription(e){
  const p = {id:'rx' + (++ui.seq), number:'77-0' + ui.seq, patient:e.patient, mine:!!e.mine, doctor:'А. Соколова, терапевт', date:'Сегодня', valid:'60 дней', items:[['Препарат Б', 'таблетки, 14 шт.'], ['Препарат В', 'порошок для раствора, 10 пакетиков']], status:'issued', pharmacy:null, code:null, episodeId:e.id};
  state.prescriptions.unshift(p);
  return p;
}

/* Врач сохранил итог приёма или план: новые шаги появляются только отсюда */
export function savePlan(e, s, chosen, rx, summary){
  if (s){ s.status = 'completed'; s.outcome = summary; addLog(e, 'Врач', 'Итог приёма: ' + summary); }
  const cycle = e.steps.length ? Math.max(...e.steps.map(x => x.cycle)) + 1 : 1;
  const opts = NEXT[e.ruleId] || NEXT.own;
  chosen.forEach(sv => { const o = opts.find(x => x[0] === sv); mkStep(e, sv, cycle, 'Решение врача', o ? o[1] : ''); });
  const names = chosen.map(sv => SERVICES[sv].title);
  if (chosen.length){
    e.status = 'active'; e.reason = '';
    addLog(e, 'Врач', 'Следующие шаги: ' + names.map(lc).join('; '));
    closeRequests(e, 'route', 'План задан: ' + names.map(lc).join('; ') + '.');
    mkRequest(e, 'doctor', 'book', 'Записать на следующие шаги', `${e.patient}: ${names.map(lc).join('; ')}. Сроки указаны в плане.`);
  } else if (!e.steps.some(live)){
    e.status = 'completed';
    addLog(e, 'Врач', 'Следующих шагов нет: план выполнен');
    closeRequests(e, null, 'Следующих шагов нет, план выполнен.');
  }
  let text = chosen.length ? 'Врач обновил ваш план: ' + names.map(lc).join('; ') + '.' : 'Врач внёс итог приёма. Новых шагов нет.';
  const actions = [['Открыть план', 'nav', 'plan']];
  if (rx){ const p = createPrescription(e); addLog(e, 'Врач', 'Выписан электронный рецепт № ' + p.number); text += ' Рецепт уже в разделе «Аптека».'; actions.push(['К рецепту', 'rxTab', '']); }
  notify(e, 'План обновлён после приёма', text, actions);
}
export function confirmRoute(e){
  const rule = RULES.find(r => r.id === e.ruleId);
  (e.suggest || []).forEach(sv => mkStep(e, sv, 1, 'Решение врача', rule ? rule.due : ''));
  e.status = 'active'; e.reason = '';
  const names = (e.suggest || []).map(sv => lc(SERVICES[sv].title)).join('; ');
  addLog(e, 'Врач', 'Маршрут подтверждён: ' + names);
  closeRequests(e, 'route', 'Подтверждаю: ' + names + '.');
  const first = e.steps.find(live);
  notify(e, 'План готов', 'Врач подтвердил следующий шаг: ' + names + '. Выберите удобное время.', first ? [['Выбрать время', 'book', refKey(e, first)]] : []);
}

/* ---------- Разбор заключения: демо на ключевых словах ---------- */
export function detectModality(t){
  if (/маммограф/i.test(t)) return 'mg';
  if (/МРТ|МР-признак/i.test(t)) return 'mri';
  if (/(^|[^А-Яа-яЁё])КТ([^А-Яа-яЁё]|$)|компьютерн/.test(t)) return 'ct';
  if (/рентген/i.test(t)) return 'xray';
  return null;
}
export function extractFacts(t, modality, rule){
  const facts = [];
  if (modality) facts.push(['Исследование', MOD_LABEL[modality]]);
  const area = /молочн/i.test(t) ? 'молочная железа' : /колен/i.test(t) ? 'коленный сустав' : /лёгк|легк|грудн/i.test(t) ? 'лёгкие' : '';
  const right = /(^|[^а-яё])прав(ой|ого|ом|ая|ое|ый|ую)/i.test(t), left = /(^|[^а-яё])лев(ой|ого|ом|ая|ое|ый|ую)/i.test(t);
  if (area) facts.push(['Область', area + (right && !left ? ', справа' : left && !right ? ', слева' : '')]);
  if (rule) facts.push(['Находка', lc(rule.finding)]);
  const size = t.match(/(\d+(?:[.,]\d+)?)\s*мм/);
  if (size && rule && rule.id !== 'NORM') facts.push(['Размер', size[1] + ' мм']);
  return facts;
}
export function analyze(text, hint){
  const t = String(text || '');
  const modality = hint || detectModality(t);
  const norm = RULES[0].test.test(t);
  const rule = norm ? RULES[0] : (RULES.find(r => r.id !== 'NORM' && (!modality || r.modality === modality) && r.test.test(t)) || null);
  return {modality, rule, approved:rule ? !!state.ruleApproved[rule.id] : false, facts:extractFacts(t, modality, rule)};
}
export const MARK = /(инфильтр[а-яё]*(?:\s+лёгочной\s+ткани)?|очаг[а-яё]*|уплотнени[а-яё]*|мениск[а-яё]*|не\s+выявлено|\d+(?:[.,]\d+)?\s*мм)/gi;
export const highlight = text => safe(text).replace(MARK, '<mark>$1</mark>').replace(/\n+/g, '<br>');

/* Врач подтвердил заключение: создаём эпизод и маршрут */
export function createEpisodeFromStudy(st){
  const d = DEMO[st.kind];
  const res = analyze(st.conclusion, d.modality);
  if (res.rule && res.rule.id === 'NORM'){
    st.noRoute = true;
    state.outbox.unshift({t:'Только что', patient:st.patient, event:'Результат: изменений не найдено, напоминание через 12 месяцев', channel:'Приложение', status:'Доставлено', episodeId:null});
    if (st.mine) pushMsg('clinic', 'Результат готов: изменений, которые требуют действий, на снимке не нашли. О плановом обследовании напомним через 12 месяцев.', [['Что на снимке', 'nav', 'imaging']]);
    return null;
  }
  const e = {id:'e' + (++ui.seq), patient:st.patient, mine:!!st.mine, kind:'imaging', studyId:st.id, title:d.title, opened:'Только что', status:'active', reason:'', ruleId:res.rule ? res.rule.id : null,
    profile:st.uploaded ? ['47 лет', 'Полис ДМС', 'Снимок загружен пациентом'] : ['Данные карты придут из МИС'], steps:[], log:[]};
  addLog(e, 'Д. Ершов', 'Заключение подтверждено врачом' + (st.edited ? ', черновик ИИ исправлен' : ''));
  if (res.rule && res.approved){
    res.rule.steps.forEach(sv => mkStep(e, sv, 1, `Правило ${res.rule.id}, версия ${res.rule.version}`, res.rule.due));
    const names = res.rule.steps.map(sv => lc(SERVICES[sv].title)).join('; ');
    addLog(e, 'Маршрутизатор', `Следующий шаг по правилу ${res.rule.id}: ${names}, срок ${res.rule.due}`);
    notify(e, 'Заключение готово: объяснение и запись', `${d.ready}. Врач подтвердил заключение. Следующий шаг: ${names}, срок ${res.rule.due}.`, [['Что на снимке', 'nav', 'imaging'], ['Выбрать время', 'book', refKey(e, e.steps[0])]]);
  } else {
    e.status = 'manual_review';
    e.suggest = res.rule ? res.rule.steps.slice() : [];
    e.reason = res.rule ? `Правило ${res.rule.id} ещё не утверждено клиникой: нужен план врача` : 'Для такой находки правила нет: нужен план врача';
    addLog(e, 'Маршрутизатор', e.reason);
    mkRequest(e, 'staff', 'route', 'Подтвердить маршрут', `${e.patient}, ${lc(d.title)}. ${e.reason}.${e.suggest.length ? ' Вариант маршрутизатора: ' + e.suggest.map(sv => lc(SERVICES[sv].title)).join('; ') + '.' : ''}`);
    notify(e, 'Заключение готово: план уточняет врач', `${d.ready}. Врач подтвердил заключение и сейчас уточняет следующий шаг. Мы напишем, когда план будет готов.`, [['Что на снимке', 'nav', 'imaging']]);
  }
  state.episodes.unshift(e);
  st.episodeId = e.id;
  return e;
}

/* Очередь координатора: что мешает эпизоду двигаться */
export function queueInfo(e){
  if (e.status === 'completed') return {label:'Завершено', tone:'gray', reason:'План выполнен', group:'done', need:false};
  if (e.status === 'closed') return {label:'Остановлено', tone:'gray', reason:e.reason || 'Сопровождение остановлено', group:'done', need:false};
  if (e.status === 'manual_review') return {label:'Ручной разбор', tone:'orange', reason:e.reason || 'Нужен план врача', group:'lost', need:true};
  if (e.status === 'paused') return {label:'Отложено', tone:'red', reason:'Пациент отложил шаг: ' + lc(e.reason || 'причина не указана'), group:'lost', need:true};
  const cur = e.steps.filter(live);
  const over = cur.find(s => s.overdue);
  if (over) return {label:'Просрочено', tone:'red', reason:`Срок прошёл ${over.due}, пациент не записан`, group:'lost', need:true};
  if (e.callback) return {label:'Перезвонить', tone:'orange', reason:'Пациент просит перезвонить', group:'offer', need:true};
  const att = cur.find(s => s.status === 'attended');
  if (att && att.slot && att.slot.partner) return {label:'У партнёра', tone:'blue', reason:'Услуга у партнёра оказана, ждём результат', group:'outcome', need:true};
  if (att) return {label:'Ждёт итога врача', tone:'blue', reason:'Визит состоялся, итога приёма пока нет', group:'outcome', need:true};
  const open = cur.find(s => s.status === 'open');
  if (open) return {label:'Не записан', tone:'orange', reason:'Пациент не выбрал время' + (open.due ? '. Срок: ' + open.due : ''), group:'offer', need:true};
  const off = cur.find(s => s.status === 'offered');
  if (off) return {label:'Ждём ответ', tone:'blue', reason:'Предложено время: ' + lc(slotLine(off.slot)) + '. Пациент ещё не ответил', group:'wait', need:true};
  const conf = cur.find(s => s.status === 'confirmed');
  if (conf) return {label:'Записан', tone:'', reason:`Ждём визита: ${lc(slotLine(conf.slot))}`, group:'booked', need:false};
  return {label:'В работе', tone:'', reason:'Активных шагов нет', group:'booked', need:false};
}
export const awaitingOutcome = () => state.episodes.flatMap(e => e.steps.filter(s => s.status === 'attended' && !(s.slot && s.slot.partner)).map(s => [e, s]));
