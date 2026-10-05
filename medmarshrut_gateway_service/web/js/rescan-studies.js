/* Кабинет rescan, раздел «Исследования» (задание 12, цикл 5): вкладки пациентов, настоящие срезы, находки,
   заключение врача и маршрут. Шаг пациенту назначает правило клиники: до подтверждения — только предпросмотр. */
import { api } from './api.js';
import { k, empty, head, load, redraw, rs, stateOf } from './rescan-ui.js';
import { planButton, planCard } from './rescan-plan.js';
import { casesBlock } from './rescan-cases.js';
import { current } from './path-ui.js';
import { state, ui } from './state.js';
import { $, go, plural, safe, toast } from './ui.js';

const MAX_TEXT = 3500;
const VIEW_NOTE = 'Просмотр для проверки, не диагностический просмотрщик';
const DEMO_NOTE = 'Демо-сценарий: признак задан заранее, снимок не анализировался';
const MODS = {CT:['КТ', '#1866A0'], MR:['МРТ', '#7B61FF'], MG:['ММГ', '#E06C9F'], CR:['Рентген', '#0FA3A3'], DX:['Рентген', '#0FA3A3']};
const STATUS = {awaiting_physician:['Ждёт вас', 'amber'], confirmed:['Подтверждено', 'green'], manual_review:['Ручное описание', 'grey'],
                test_only:['Техническая проверка', 'grey'], unavailable:['Недоступно', 'red'], processing:['Обрабатывается', 'blue']};
const enc = encodeURIComponent;
const fmt = value => { if (!value) return ''; const d = new Date(value); return Number.isNaN(+d) ? String(value) : new Intl.DateTimeFormat('ru-RU', {day:'numeric', month:'long', hour:'2-digit', minute:'2-digit'}).format(d); };
const pill = status => { const [text, tone] = STATUS[status] || [status, 'grey']; return `<span class="c-s ${tone}">${safe(text)}</span>`; };
const short = name => { const [first, last] = String(name || '').split(/\s+/); return last ? `${first} ${last[0]}.` : first || 'Пациент'; };
const initials = name => String(name || '').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('') || '?';
const avatar = (name, size) => `<span class="c-av" style="width:${size}px;height:${size}px;display:grid;place-items:center;font-weight:600;color:var(--c-blue)">${safe(initials(name))}</span>`;
const text = value => safe(value).replace(/\n+/g, '<br>');

/* Открытое исследование: {id, status, data, message}; черновики по коду признака живут до смены исследования */
const det = {id:null, status:'idle', data:null, message:'', index:0, drafts:{}, code:null, busy:false, suggest:null, suggesting:false};

/* Ожидающие проверки — первыми, как в образце */
const ordered = list => [...list].sort((a, b) => (b.status === 'awaiting_physician') - (a.status === 'awaiting_physician'));
export function studyNeeds(timer){ return timer && det.status === 'ok' ? [] : ['studies', 'assistant', 'episodes', 'catalog', 'rules']; }

async function loadDetail(id){
  Object.assign(det, {id, status:'loading', data:null, message:'', index:0, drafts:{}, code:null, suggest:null});
  redraw();
  try {
    const st = (await api('GET', `/api/doctor/studies/${enc(id)}`, {role:'doctor'})).study;
    if (det.id !== id) return;
    const first = (st.images || []).findIndex(x => x.sop_uid === st.findings?.[0]?.sop_uid);
    Object.assign(det, {status:'ok', data:st, index:first > 0 ? first : 0});
  } catch (err){
    if (det.id !== id) return;
    Object.assign(det, {status:'error', message:'Не удалось открыть исследование. ' + err.message});
  }
  if (state.page === 'rsStudies') redraw();
}

/* ---------- Левая колонка: шапка, срезы, находки, заключение ---------- */
function viewer(st){
  const list = st.images || [];
  if (!list.length) return empty('Срезов нет', 'Архив не прошёл проверку сервиса снимков.');
  const i = Math.min(det.index, list.length - 1), img = list[i];
  const hit = (st.findings || []).find(f => f.sop_uid === img.sop_uid);
  return `<div class="c-msg" style="padding:10px;display:flex;flex-direction:column;gap:8px">
    <img class="studyimg" style="width:100%;max-height:440px;object-fit:contain;border-radius:12px;background:#0E1614;display:block" alt="${safe(img.label)}" data-api-src="/api/doctor/studies/${enc(st.id)}/images/${enc(img.sop_uid)}.png">
    <div style="display:flex;flex-wrap:wrap;justify-content:space-between;gap:4px 14px;font-size:12px;color:var(--c-fg2);line-height:1.3"><span>${safe(img.label)}${hit && hit.place !== img.label ? ' · ' + safe(hit.place) : ''}</span><span>${VIEW_NOTE}</span></div>
    ${list.length > 1 ? `<div class="c-act" style="justify-content:center"><button class="c-btn gh sm" type="button" data-action="rsStep" data-step="-1" aria-label="Предыдущий срез">${k('l', 14, 2)}Назад</button><span style="font-size:13px">${i + 1} из ${list.length}</span><button class="c-btn gh sm" type="button" data-action="rsStep" data-step="1" aria-label="Следующий срез">Вперёд${k('r', 14, 2)}</button></div>` : ''}</div>`;
}
function findingsBlock(st){
  const info = st.study;
  const rows = st.findings.length ? st.findings.map(f => `<div class="c-kv"><span>${safe(f.description)}</span><span>${safe(f.place)}${f.confidence != null ? ` · оценка модели ${safe(f.confidence)}` : ''}</span></div>`).join('')
    : st.status === 'test_only' ? `<div class="c-kv"><span>${safe(st.test_message)}</span><span></span></div>`
    : `<div class="c-kv"><span>${safe(st.reason?.text || 'Находок нет')}</span><span>${st.reason ? 'сервис снимков: ' + safe(st.reason.original) : ''}</span></div>`;
  const facts = [st.limitations?.length ? ['Ограничения модели', st.limitations.map(safe).join('<br>')] : null,
                 ['Файлы', info ? `${safe(info.instance_count)} ${plural(info.instance_count, ['файл', 'файла', 'файлов'])} · ${safe(info.series_count)} ${plural(info.series_count, ['серия', 'серии', 'серий'])}` : 'Не прочитаны'],
                 info ? ['Протокол', `${safe(info.protocol_name)} · ${safe(info.anatomy)}`] : null,
                 ['Проверка DICOM', info ? 'Пройдена' : 'Не пройдена']].filter(Boolean);
  return `<div class="c-ch"><span><h2>Находки ИИ</h2><span class="sub">модель отмечает только находки, на которые её проверяли${info?.modality === 'MG' ? '; категорию BI-RADS указывает врач' : ''}</span></span></div>
    <div class="c-kvs">${rows}</div><div class="c-kvs">${facts.map(([a, b]) => `<div class="c-kv" style="background:none;padding:2px 12px;font-size:12px"><span>${a}</span><span>${b}</span></div>`).join('')}</div>`;
}
function codesOf(st){ return Object.keys(st.templates || {}); }
function currentCode(st){ const codes = codesOf(st); return det.code && codes.includes(det.code) ? det.code : codes[0]; }
function conclusionBlock(st, assistant){
  if (st.status === 'confirmed'){
    const c = st.confirmation;
    return `<div class="c-hl"><span class="c-hl-h">Заключение врача · подтверждено ${safe(fmt(c.confirmed_at))}${c.edited ? ' · заготовка исправлена' : ''}</span><span style="color:var(--c-fg)">${text(c.conclusion)}</span></div>`;
  }
  if (st.status !== 'awaiting_physician'){
    return `<div class="c-hl">${st.status === 'test_only' ? 'Техническая проверка, анализ не выполнялся. Подтвердить нельзя.' : 'Подтвердить нельзя: сервис принимает заключение только с находкой модели. Врач описывает исследование сам, координатор видит его в группе «Снимки на ручном описании».'}</div>`;
  }
  const codes = codesOf(st), code = currentCode(st);
  const value = det.drafts[code] ?? st.templates[code] ?? '';
  const choose = codes.length > 1 ? `<div class="c-fld"><label>Какой признак вы подтверждаете</label><div class="c-fl">${st.findings.filter(f => codes.includes(f.code)).map(f => `<button type="button" data-action="rsCode" data-code="${safe(f.code)}" aria-pressed="${f.code === code}">${safe(f.description)}</button>`).join('')}</div></div>` : '';
  const suggest = det.suggest && det.suggest.code === code ? `<div class="c-msg"><span class="c-hl-h">Черновик ИИ-помощника</span><div style="font-size:13px;line-height:1.6">${text(det.suggest.text)}</div><p class="c-demo" style="margin:8px 0">Прочитайте перед тем, как подставить. Заключение подтверждаете вы.</p><div class="c-act"><button class="c-btn sm" type="button" data-action="rsSuggestUse">Подставить</button><button class="c-btn gh sm" type="button" data-action="rsSuggestDrop">Не нужно</button></div></div>` : '';
  return `${choose}<div class="c-fld"><label for="rsDraft">Заключение</label><textarea id="rsDraft" data-code="${safe(code)}" maxlength="${MAX_TEXT}" style="min-height:190px;border:1.5px solid transparent;border-radius:14px;padding:12px 14px;font:inherit;font-size:13px;line-height:1.6;resize:vertical;background:var(--c-main);color:var(--c-fg)">${safe(value)}</textarea>
    <span class="c-demo"><span id="rsDraftCount">${value.length}</span> из ${MAX_TEXT} символов. Заготовка без оценок модели: прочитайте, исправьте и подтвердите.</span></div>
    ${assistant ? `<div class="c-act"><button class="c-btn gh sm" type="button" data-action="rsRewrite">${det.suggesting ? 'Готовим вариант…' : 'Улучшить формулировку'}</button></div>` : ''}${suggest}`;
}

/* ---------- Правая колонка: маршрут и что увидит пациент ---------- */
function routeCard(st){
  if (st.status === 'awaiting_physician'){
    const p = st.preview ? st.preview[currentCode(st)] : null;
    const step = p?.steps?.[0];
    const what = !st.preview ? `<div class="c-next"><span>Предпросмотр недоступен</span><small>Сервис маршрута не ответил. Шаг назначит правило клиники после подтверждения.</small></div>`
      : step ? `<div class="c-next"><span>Шаг по правилу клиники${p.rule_version ? ', версия ' + safe(p.rule_version) : ''}</span><b>${safe(step.description)}</b>${p.steps.length > 1 ? `<small>Дальше: ${p.steps.slice(1).map(s => safe(s.description)).join(' → ')}</small>` : ''}</div>`
      : `<div class="c-next"><span>Ручной разбор${p?.rule_version ? ' · правила, версия ' + safe(p.rule_version) : ''}</span><b>${safe(p?.manual_reason_text || p?.manual_reason || 'Правила для этой находки нет')}</b><small>После подтверждения план назначает врач.</small></div>`;
    return `<div class="c-card c-dec"><div class="c-ch"><span><h2>Маршрут</h2><span class="sub">предпросмотр, шаг назначит правило клиники</span></span>${pill(st.status)}</div>${what}
      <button class="c-btn big" type="button" data-action="rsConfirm"${det.busy ? ' disabled' : ''}>${k('check', 18, 2.2)}${det.busy ? 'Подтверждаем…' : 'Подтвердить заключение'}</button>
      <span class="c-demo">До подтверждения пациент и координатор видят только статус «Врач проверяет».</span></div>`;
  }
  if (st.status === 'confirmed'){
    /* Свежий эпизод из списка важнее next открытого исследования: врач мог уже назначить или изменить план */
    const fresh = st.next?.episode_id && (rs.episodes?.data || []).find(x => x.id === st.next.episode_id);
    const step = fresh && current(fresh);
    const n = fresh ? {...st.next, status:fresh.status, step:fresh.status === 'active' ? step?.description : null, step_status:step?.status || null, reason:fresh.reason,
                               reached:fresh.steps.some(x => ['attended', 'completed'].includes(x.status))} : st.next || {};
    const came = n.reached || n.step_status === 'attended' || n.status === 'completed', booked = came || ['confirmed', 'attended'].includes(n.step_status);
    const chain = [['Заключение', true], ['Подтверждено', true], ['Записан', booked || came], ['Пришёл', came]]
      .map(([label, on]) => `<span class="${on ? 'on' : ''}"><i>${on ? k('check', 12, 2.6) : ''}</i>${label}</span>`).join('');
    const body = n.warning ? `<div class="c-err"><p>${safe(n.warning)}</p></div>`
      : n.status === 'manual_review' ? `<div class="c-kv"><span>Ручной разбор</span><span>${safe(n.reason)}</span></div>`
      : `<div class="c-kv"><span>Шаг</span><span>${safe(n.step || (n.status === 'completed' ? 'План выполнен' : n.status === 'paused' ? 'Маршрут на паузе' : '—'))}</span></div>`;
    /* План врача после подтверждения: «Назначить план» при ручном разборе, «Изменить план» у активного маршрута */
    const e = fresh;
    const plan = planButton(e);
    return `<div class="c-card c-dec"><div class="c-ch"><span><h2>Маршрут</h2><span class="sub">подтверждено ${safe(fmt(st.confirmation?.confirmed_at))}</span></span>${pill(st.status)}</div><div class="c-path">${chain}</div>${body}${plan ? `<div class="c-act">${plan}</div>` : ''}</div>${planCard(e)}`;
  }
  return `<div class="c-card"><div class="c-ch"><span><h2>Маршрут</h2></span>${pill(st.status)}</div><span style="font-size:13px;color:var(--c-fg2)">Маршрута нет: исследование не подтверждается через сервис.</span></div>`;
}
function patientCard(st){
  let body;
  if (st.status === 'awaiting_physician'){
    const p = st.preview ? st.preview[currentCode(st)] : null;
    const ex = p?.explanation;
    body = `<div class="c-bub"><span class="c-bub-h">${k('scan', 14, 1.7)}после подтверждения</span>${ex ? `<b>Что увидели.</b> ${safe(ex.seen)}<br><b>Что это значит.</b> ${safe(ex.means)}` : 'Клиника ещё не утвердила объяснение для этого признака: пациент увидит общий текст и ваше заключение.'}</div>
      <div class="c-after"><span>Следующий шаг</span><b>${safe(p?.steps?.[0]?.description || 'План назначит врач')}</b><small>Объяснение утверждено клиникой. Оценка модели пациенту не показывается.</small></div>`;
  } else if (st.status === 'confirmed'){
    body = `<div class="c-after" style="margin:0;padding:0;border:0"><span>Пациент видит</span><b>Ваше заключение, утверждённое объяснение и шаг${st.next?.step ? ' «' + safe(st.next.step) + '»' : ''}</b><small>Оценка модели пациенту не показывается.</small></div>`;
  } else body = `<div class="c-after" style="margin:0;padding:0;border:0"><span>Пациент видит</span><b>«Врач описывает сам»</b><small>Координатор свяжется с пациентом.</small></div>`;
  /* Ссылка открывает окно пациента (роль «пациент», раздел «Что на снимке») */
  return `<div class="c-card"><div class="c-ch"><span><h2>Что увидит пациент</h2><span class="sub">в разделе «Что на снимке»</span></span></div><div class="c-msg">${body}</div><div class="c-act"><button class="c-lnk" type="button" data-jump="patient:rsResults">Посмотреть глазами пациента</button></div></div>`;
}

/* ---------- Экран ---------- */
export function rsStudies(){
  return stateOf('studies', raw => {
    const list = ordered(raw), waiting = list.filter(s => s.status === 'awaiting_physician');
    const sub = waiting.length ? `Осталось разобрать: ${waiting.length}` : 'Все исследования разобраны';
    if (!list.length) return head('Исследования', sub) + empty('Исследований нет', 'Когда пациент или клиника загрузит исследование, оно появится здесь.') + casesBlock();
    if (!ui.rsStudy || !list.some(s => s.id === ui.rsStudy)) ui.rsStudy = list[0].id;
    if (det.id !== ui.rsStudy) queueMicrotask(() => { if (det.id !== ui.rsStudy) loadDetail(ui.rsStudy); });
    const tabs = list.map(s => `<button class="c-tab" type="button" data-action="rsStudyOpen" data-id="${safe(s.id)}" aria-pressed="${s.id === ui.rsStudy}" title="${safe(s.title)}">${k('scan', 18)}${safe(short(s.patient))}${s.status === 'awaiting_physician' ? '<span class="d" style="background:var(--c-amber)"></span>' : ''}</button>`).join('');
    return head('Исследования', sub, `<div class="c-tabs" role="group" aria-label="Исследование">${tabs}</div>`) + detail(waiting) + casesBlock();
  });
}
function detail(waiting){
  if (det.status === 'error') return `<div class="c-err" role="alert"><p>${safe(det.message)}</p><button class="c-btn sm" type="button" data-action="rsStudyRetry">Повторить</button></div>`;
  if (det.status !== 'ok' || det.id !== ui.rsStudy) return '<div class="c-grid" aria-busy="true" aria-label="Загружаем"><div class="c-skel" style="min-height:360px"></div><div class="c-skel" style="min-height:360px"></div></div>';
  const st = det.data, assistant = rs.assistant?.data?.enabled === true;
  const mod = MODS[st.study?.modality];
  const source = st.uploaded_by_role === 'patient' ? 'загрузил пациент' : 'выгрузка из РИС, демо';
  const hdr = `<div class="c-hdr">${avatar(st.patient, 44)}<span><b>${safe(st.patient)}</b><small>${safe(st.title)} · ${safe(fmt(st.created_at))} · ${source}</small></span><span style="margin-left:auto">${mod ? `<span class="c-mod" style="--m:${mod[1]}">${mod[0]}</span>` : ''}</span></div>`;
  if (st.status === 'unavailable') return `<div class="c-card">${hdr}<div class="c-err"><p>${safe(st.message)}. Попросите загрузить исследование заново.</p></div></div>`;
  const next = waiting.find(s => s.id !== st.id);
  return `<div class="c-grid"><div class="c-card">${hdr}${st.demo ? `<div class="c-next" style="background:#FFF1CC"><b>${DEMO_NOTE}</b></div>` : ''}${viewer(st)}${findingsBlock(st)}${conclusionBlock(st, assistant)}</div>
    <div class="c-col">${routeCard(st)}${patientCard(st)}${st.status !== 'awaiting_physician' && next ? `<button class="c-btn gh" type="button" data-action="rsStudyOpen" data-id="${safe(next.id)}">Следующее: ${safe(short(next.patient))} ${k('r', 14, 2)}</button>` : ''}</div></div>`;
}

/* ---------- Действия ---------- */
export function installStudyActions(ACTIONS){
  ACTIONS.rsStudyOpen = d => { ui.rsStudy = d.id; if (state.page !== 'rsStudies') go('rsStudies'); else { loadDetail(d.id); window.scrollTo(0, 0); } };
  ACTIONS.rsStudyRetry = () => loadDetail(ui.rsStudy);
  ACTIONS.rsStep = d => { const n = det.data?.images?.length || 0; if (!n) return; det.index = (Math.min(det.index, n - 1) + Number(d.step) + n) % n; redraw(); };
  ACTIONS.rsCode = d => { det.code = d.code; redraw(); };
  ACTIONS.rsConfirm = async () => {
    const st = det.data, code = st && currentCode(st), value = $('#rsDraft')?.value || '';
    if (!st || det.busy) return;
    if (!value.trim()) return toast('Заключение пустое. Напишите текст и подтвердите.');
    det.drafts[code] = value;
    det.busy = true; redraw();
    try {
      await api('POST', `/api/doctor/studies/${enc(st.id)}/confirm`, {role:'doctor', body:{conclusion:value, finding_code:code}});
    } catch (err){
      det.busy = false; redraw(); toast(err.message);  // текст врача остаётся в поле
      return;
    }
    det.busy = false;
    toast('Заключение подтверждено');
    await Promise.all([loadDetail(st.id), load('studies')]);
  };
  ACTIONS.rsRewrite = async () => {
    const st = det.data, code = st && currentCode(st), value = $('#rsDraft')?.value || '';
    if (!st || det.suggesting) return;
    if (!value.trim()) return toast('Поле пустое. Напишите хотя бы несколько слов, и помощник предложит формулировку.');
    det.drafts[code] = value;
    det.suggesting = true; redraw();
    try {
      const r = await api('POST', `/api/doctor/studies/${enc(st.id)}/assistant/rewrite`, {role:'doctor', body:{finding_code:code, text:value}});
      det.suggest = {code, text:r.suggestion};
    } catch (err){ toast(err.message); }
    det.suggesting = false; redraw();
  };
  ACTIONS.rsSuggestUse = () => { if (!det.suggest) return; det.drafts[det.suggest.code] = det.suggest.text; det.suggest = null; redraw(); };
  ACTIONS.rsSuggestDrop = () => { det.suggest = null; redraw(); };
  document.addEventListener('input', e => {
    if (e.target.id !== 'rsDraft') return;
    det.drafts[e.target.dataset.code] = e.target.value;
    const count = $('#rsDraftCount');
    if (count) count.textContent = e.target.value.length;
  });
}
