/* Задание 05: «Что на снимке?» на сервисе снимков через шлюз. Схем и демо-содержания здесь нет:
   только настоящие срезы, статусы и заключения. До подтверждения врачом пациент видит один статус. */
import { api, imageUrl, uploadArchive } from './api.js';
import { icon } from './icons.js';
import { sessions, state, ui } from './state.js';
import { $, badge, btn, closeModal, errorNote, go, loadingCards, modalHead, navBtn, openModal, plural, safe, toast } from './ui.js';
import { render } from './shell.js';

const MAX_ARCHIVE = 50 * 1024 * 1024;
const MAX_TEXT = 3500;
const HERE = {patient:['imaging'], doctor:['reading', 'study', 'inbox'], staff:['inbox']};
export const isImagingPage = () => (HERE[state.role] || []).includes(state.page);
/* Список перечитывается раз в 15 секунд; экран «Снимок и заключение» — только при входе: там врач правит текст */
export const isImagingListPage = () => isImagingPage() && state.page !== 'study';

const data = {role:null, page:null, status:'loading', message:'', items:[], detail:null, detailId:null,
              manual:[], notRouted:[], kit:null, index:0, drafts:{}, code:null, busy:false};
const blobs = new Map();
const known = new Set();  // идентификаторы из списка врача: старый выбор из демо-состояния в шлюз не уходит
const enc = encodeURIComponent;
const fmt = value => { if (!value) return ''; const d = new Date(value); return Number.isNaN(+d) ? String(value) : new Intl.DateTimeFormat('ru-RU', {day:'numeric', month:'long', hour:'2-digit', minute:'2-digit'}).format(d); };
const ready = () => data.role === state.role && data.page === state.page && data.status === 'ok';
const gate = () => data.role === state.role && data.page === state.page && data.status === 'error' ? errorNote(data.message, 'imagingRetry') : loadingCards();
const head = (title, text, actions = '') => `<div class="pagehead"><div><div class="eyebrow">Сервис «Что на снимке?»</div><h1>${title}</h1>${text ? `<p>${text}</p>` : ''}</div>${actions ? `<div class="actions">${actions}</div>` : ''}</div>`;
const VIEW_NOTE = 'Просмотр для проверки, не диагностический просмотрщик';
const DEMO_NOTE = 'Демо-сценарий: признак задан заранее, снимок не анализировался';

export async function refreshImaging(){
  if (!isImagingPage() || sessions[state.role]?.status !== 'ok') return;
  const role = state.role, page = state.page;
  if (page === 'study' && !known.has(state.sel.study)){
    try { remember((await api('GET', '/api/doctor/studies', {role})).studies || []); } catch (err){ /* покажет ошибка ниже */ }
    const list = [...known.values()];
    if (!known.has(state.sel.study)) state.sel.study = list[0] || null;
  }
  const id = state.sel.study;
  const fresh = data.role !== role || data.page !== page || (page === 'study' && data.detailId !== id);
  if (fresh){ Object.assign(data, {role, page, status:'loading', message:''}); if (page === 'study') Object.assign(data, {detail:null, detailId:id, index:0, drafts:{}, code:null}); render(); }
  try {
    if (page === 'imaging') data.items = (await api('GET', '/api/patient/studies', {role})).studies || [];
    else if (page === 'reading'){ data.items = remember((await api('GET', '/api/doctor/studies', {role})).studies || []); state.readingCount = data.items.filter(s => s.status === 'awaiting_physician').length; }
    else if (page === 'study'){
      if (!id){ data.detail = null; data.status = 'empty'; render(); return; }
      data.detail = (await api('GET', `/api/doctor/studies/${enc(id)}`, {role})).study;
      const first = data.detail.images?.findIndex(x => x.sop_uid === data.detail.findings?.[0]?.sop_uid);
      if (fresh && first > 0) data.index = first;
    } else if (page === 'inbox'){ const r = await api('GET', '/api/staff/studies/manual', {role}); data.manual = r.manual || []; data.notRouted = r.not_routed || []; }
    data.status = 'ok';
  } catch (err){ data.status = 'error'; data.message = 'Не удалось загрузить исследования. ' + err.message; }
  if (state.role === role && state.page === page && !ui.modal) render();
}

function remember(items){
  known.clear();
  [...items].sort((a, b) => (b.status === 'awaiting_physician') - (a.status === 'awaiting_physician')).forEach(s => known.add(s.id));
  return items;
}

/* Картинки: <img data-api-src> получает blob:-адрес после отрисовки, без повторной отрисовки экрана */
function hydrate(){
  document.querySelectorAll('img[data-api-src]').forEach(img => {
    const path = img.dataset.apiSrc;
    if (img.dataset.loaded === path) return;
    img.dataset.loaded = path;
    if (!blobs.has(path)) blobs.set(path, imageUrl(path, state.role).catch(err => { blobs.delete(path); throw err; }));
    blobs.get(path).then(url => { if (img.dataset.apiSrc === path) img.src = url; })
      .catch(err => { img.alt = 'Срез не загрузился. ' + err.message; });
  });
}
new MutationObserver(hydrate).observe(document.querySelector('#view'), {childList:true, subtree:true});

/* ---------- Пациент ---------- */
const STAGES = ['Файлы приняты', 'ИИ готовит черновик', 'Врач проверяет', 'Результат и план'];
function patientNext(st){
  const e = st.episode;
  const s = e && e.steps.find(x => !['completed', 'superseded', 'closed'].includes(x.status));
  if (!e) return {head:'План готовится', text:'Следующий шаг появится в разделе «Мой план».', buttons:navBtn('Мой план', 'plan', 'secondary')};
  if (e.status === 'manual_review') return {head:'Врач уточняет план', text:'Мы напишем, как только план будет готов.', buttons:navBtn('Мой план', 'plan', 'secondary')};
  if (!s) return {head:'План выполнен', text:'Все шаги по этому исследованию сделаны.', buttons:''};
  const book = e.status === 'active' && ['open', 'offered'].includes(s.status);
  return {head:s.description || 'Шаг плана', text:s.appointment_at ? 'Запись: ' + fmt(s.appointment_at) : s.due_at ? 'Срок: ' + fmt(s.due_at) : '',
          buttons:book ? btn('Выбрать время', 'pathChoose', '', {key:`${e.id}:${s.id}`}) : navBtn('Мой план', 'plan', 'secondary')};
}
function patientCard(st){
  const top = (text, tone) => `${badge(text, tone)}<h2 style="margin-top:11px">${safe(st.title)}</h2><p>Загружено ${safe(fmt(st.created_at))}</p>`;
  if (st.status === 'processing' || st.status === 'awaiting'){
    const stage = st.status === 'processing' ? 1 : 2;
    return `<div class="panel">${top(st.status === 'processing' ? 'Обрабатывается' : 'Ждёт врача', 'blue')}<div class="steps" style="margin:18px 0 14px">${STAGES.map((n, i) => `${i ? '<span class="sep"></span>' : ''}<span class="step ${i <= stage ? 'on' : ''}"><b>${i + 1}</b>${n}</span>`).join('')}</div><p style="margin:0">${st.status === 'processing' ? 'Проверяем файлы и готовим черновик заключения.' : 'Черновик готов, его проверяет врач-рентгенолог. Результат и план появятся здесь.'}</p></div>`;
  }
  if (st.status === 'manual') return `<div class="panel">${top('Врач описывает сам', 'orange')}<p style="margin:0">Этот снимок врач описывает сам. Координатор свяжется с вами.</p></div>`;
  if (st.status === 'unavailable') return `<div class="panel">${top('Недоступно', 'red')}<p style="margin:0">${safe(st.message)}. Загрузите исследование заново или напишите координатору.</p></div>`;
  const nx = patientNext(st);
  const picture = st.image?.sop_uid ? `<div class="viewer"><img class="studyimg" alt="${safe(st.image.label)}" data-api-src="/api/patient/studies/${enc(st.id)}/images/${enc(st.image.sop_uid)}.png"><div class="cap"><span>${safe(st.image.label)}</span><span>${VIEW_NOTE}</span></div></div>` : '';
  return `<div class="panel">${top('Подтверждено врачом')}
    <div class="explain">${picture}
      <div class="stack">
        <div><div class="eyebrow">Что увидели</div><p class="plain">${safe(st.explanation?.seen)}</p></div>
        <div><div class="eyebrow">Что это значит</div><p class="plain">${safe(st.explanation?.means)}</p></div>
        <div class="resultmain" style="padding:20px"><div class="eyebrow">Что дальше</div><strong style="font-size:20px">${safe(nx.head)}</strong>${nx.text ? `<p style="margin:7px 0 0">${safe(nx.text)}</p>` : ''}${nx.buttons ? `<div class="actions" style="margin-top:14px">${nx.buttons}</div>` : ''}</div>
      </div>
    </div>
    <details class="more"><summary>Заключение врача полностью</summary><div class="quote">${safe(st.conclusion).replace(/\n+/g, '<br>')}<br><br><span class="muted">Подтверждено ${safe(fmt(st.confirmed_at))}</span></div></details>
  </div>`;
}
export function imagingPage(){
  const intro = head('Мои исследования', 'Заключение появляется здесь после того, как его подтвердил врач. Рядом — объяснение простыми словами и следующий шаг.', btn(icon('plus') + 'Загрузить снимок', 'uploadOpen'));
  if (!ready()) return intro + gate();
  return intro + `<div class="stack">${data.items.map(patientCard).join('') || '<div class="panel empty"><h3>Исследований пока нет</h3><p>Загрузите снимок из другой клиники или возьмите учебное исследование.</p></div>'}</div>
    <div class="note" style="margin-top:18px">ИИ не ставит диагноз. Он помогает врачу описать снимок, а нам — подобрать следующий шаг. Заключение всегда подтверждает врач.</div>`;
}
export function uploadModal(){
  openModal(`${modalHead('Сервис «Что на снимке?»', 'Загрузить снимок')}
    <p>Подойдёт исследование из другой клиники. ИИ подготовит черновик, врач его проверит, и вы получите объяснение и план.</p>
    <div class="field"><label for="upKind">Что за исследование</label><select id="upKind"><option value="xr_general">Рентгенография</option><option value="ct_general">КТ</option><option value="mg_screening_2d">Маммография</option><option value="mr_general">МРТ</option></select></div>
    <div class="field" style="margin-top:14px"><label for="upFile">Файл</label><input id="upFile" type="file" accept=".zip,application/zip"><small>ZIP-архив с файлами DICOM, до 50 МиБ. Демо-стенд: загружайте только учебные архивы, не настоящие снимки.</small></div>
    <label class="checkline" style="margin-top:14px"><input type="checkbox" id="upConsent"><span>Разрешаю передать исследование врачу клиники «Линия здоровья» для описания</span></label>
    <div class="actions">${btn('Отправить врачу', 'upload')}${btn('Взять учебное исследование', 'uploadKit', 'secondary')}${btn('Отмена', 'close', 'secondary')}</div>
    <div id="upKit"></div>`);
}

/* ---------- Врач: список ---------- */
const STATUS = {awaiting_physician:['Ждёт проверки', 'orange'], confirmed:['Подтверждено врачом', ''], manual_review:['Ручное описание', 'gray'],
                test_only:['Техническая проверка', 'gray'], unavailable:['Недоступно', 'red'], processing:['Обрабатывается', 'blue']};
const studyBadge = st => badge(...(STATUS[st.status] || [st.status, 'gray']));
const findingLine = f => `${safe(f.description)}, ${safe(f.place).toLowerCase()}${f.confidence != null ? `. Оценка модели ${safe(f.confidence)}` : ''}`;
const nextText = n => !n ? '' : n.warning ? `<span class="badge red">${safe(n.warning)}</span>` : n.step ? safe(n.step) : n.reason ? 'Ручной разбор: ' + safe(n.reason).toLowerCase() : safe(n.status);
export function readingPage(){
  const intro = head('Черновики ИИ на проверку', 'ИИ готовит черновик заключения, врач его подтверждает. До этого ни пациент, ни координатор результата не видят.');
  if (!ready()) return intro + gate();
  const by = status => data.items.filter(s => s.status === status);
  const wait = by('awaiting_physician'), done = by('confirmed'), manual = by('manual_review').concat(by('test_only')), gone = by('unavailable');
  const open = st => btn('Открыть', 'studyOpen', 'secondary small', {id:st.id});
  return intro + `<div class="grid three" style="margin-bottom:18px"><div class="card"><div class="metric">${wait.length}</div><span class="muted">${plural(wait.length, ['ждёт', 'ждут', 'ждут'])} проверки</span></div><div class="card"><div class="metric">${done.length}</div><span class="muted">подтверждено</span></div><div class="card"><div class="metric">${done.filter(s => s.confirmation?.edited).length}</div><span class="muted">черновиков исправлено врачом</span></div></div>
    <div class="sectionhead" style="margin-top:8px"><h2>Ждут проверки</h2></div>
    ${wait.length ? `<div class="grid two">${wait.map(st => `<div class="card">${studyBadge(st)}<h3 style="margin-top:13px">${safe(st.patient)}</h3><p>${safe(st.title)} · ${safe(fmt(st.created_at))}<br>ИИ: ${st.findings.map(findingLine).join('; ')}${st.demo ? '<br><span class="muted">Демо-сценарий</span>' : ''}</p><div class="actions">${btn('Открыть снимок', 'studyOpen', 'small', {id:st.id})}</div></div>`).join('')}</div>` : '<div class="panel empty"><h3>Всё проверено</h3><p>Новые исследования появятся здесь, когда придут из РИС или от пациента.</p></div>'}
    <div class="sectionhead"><h2>Подтверждённые</h2></div>
    <div class="tablewrap"><table><thead><tr><th>Пациент</th><th>Исследование</th><th>Находка</th><th>Что дальше</th><th></th></tr></thead><tbody>
      ${done.map(st => `<tr><td><strong>${safe(st.patient)}</strong></td><td>${safe(st.title)}<small>${safe(fmt(st.confirmation?.confirmed_at))}</small></td><td>${safe(st.findings.find(f => f.code === st.confirmation?.finding_code)?.description || st.confirmation?.finding_code)}${st.confirmation?.edited ? '<small>черновик исправлен</small>' : ''}</td><td>${nextText(st.next)}</td><td>${open(st)}</td></tr>`).join('') || '<tr><td colspan="5">Подтверждённых исследований пока нет.</td></tr>'}
    </tbody></table></div>
    <div class="sectionhead"><h2>Ручное описание</h2></div>
    <div class="tablewrap"><table><thead><tr><th>Пациент</th><th>Исследование</th><th>Причина</th><th></th></tr></thead><tbody>
      ${manual.map(st => `<tr><td><strong>${safe(st.patient)}</strong></td><td>${safe(st.title)}<small>${safe(fmt(st.created_at))}</small></td><td>${st.status === 'test_only' ? 'Техническая проверка, анализ не выполнялся' : safe(st.reason?.text)}${st.reason ? `<small>${safe(st.reason.original)}</small>` : ''}</td><td>${open(st)}</td></tr>`).join('') || '<tr><td colspan="4">Исследований на ручном описании нет.</td></tr>'}
    </tbody></table></div>
    ${gone.length ? `<div class="sectionhead"><h2>Недоступны</h2></div><div class="note">${gone.map(st => `${safe(st.patient)}, ${safe(st.title)}: ${safe(st.message)}`).join('<br>')}</div>` : ''}`;
}

/* ---------- Врач: снимок и заключение ---------- */
function viewer(st){
  const list = st.images || [];
  if (!list.length) return `<div class="viewer"><p style="margin:12px">Срезов нет: архив не прошёл проверку сервиса снимков.</p></div>`;
  const i = Math.min(data.index, list.length - 1), img = list[i];
  const hit = (st.findings || []).find(f => f.sop_uid === img.sop_uid);
  return `<div class="viewer"><img class="studyimg" alt="${safe(img.label)}" data-api-src="/api/doctor/studies/${enc(st.id)}/images/${enc(img.sop_uid)}.png">
    <div class="cap"><span>${safe(img.label)}${hit ? ' · ' + safe(hit.place) : ''}</span><span>${VIEW_NOTE}</span></div>
    <div class="viewnav">${btn('← Назад', 'studyStep', 'secondary small', {step:-1})}<span>${i + 1} из ${list.length}</span>${btn('Вперёд →', 'studyStep', 'secondary small', {step:1})}</div></div>`;
}
function draftPanel(st){
  const codes = Object.keys(st.templates || {});
  const code = data.code && codes.includes(data.code) ? data.code : codes[0];
  const text = data.drafts[code] ?? st.templates[code] ?? '';
  const choose = codes.length > 1 ? `<div class="field"><label>Какой признак вы подтверждаете</label>${st.findings.filter(f => codes.includes(f.code)).map(f => `<label class="checkline" style="margin-bottom:8px"><input type="radio" name="studyCode" value="${safe(f.code)}" data-action="studyCode" data-code="${safe(f.code)}" ${f.code === code ? 'checked' : ''}><span><strong>${safe(f.description)}</strong><br><span class="muted">${safe(f.place)}</span></span></label>`).join('')}</div>` : '';
  return `<div class="panel"><h3>Черновик заключения</h3>${choose}
    <div class="field"><textarea id="studyDraft" data-code="${safe(code)}" maxlength="${MAX_TEXT}" style="min-height:190px" aria-label="Текст заключения">${safe(text)}</textarea><small><span id="draftCount">${text.length}</span> из ${MAX_TEXT} символов. Заготовка без оценок модели: прочитайте, исправьте и подтвердите.</small></div>
    <div class="actions">${btn(data.busy ? 'Подтверждаем…' : 'Подтвердить заключение', 'studyConfirm', '', {id:st.id, code})}</div></div>`;
}
function afterPanel(st){
  const c = st.confirmation, n = st.next || {};
  const caseBtn = n.episode_id ? `<button class="btn secondary small" data-case="${safe(n.episode_id)}">Открыть обращение</button>` : '';
  const what = n.warning ? `<div class="note red">${safe(n.warning)}</div>` : n.step ? `<p style="margin:0">Шаг по правилу: <strong>${safe(n.step)}</strong></p>` : n.reason ? `<div class="note warn">Ручной разбор: ${safe(n.reason)}</div>` : '';
  return `<div class="panel"><h3>Заключение</h3><div class="quote">${safe(c.conclusion).replace(/\n+/g, '<br>')}</div><p style="margin:12px 0 0">${safe(c.physician_id)}, подтверждено ${safe(fmt(c.confirmed_at))}${c.edited ? ' · черновик исправлен' : ''}</p></div>
    <div class="panel"><h3>Что дальше</h3>${what}${caseBtn ? `<div class="actions">${caseBtn}</div>` : ''}</div>`;
}
export function studyPage(){
  const back = navBtn('← К списку', 'reading', 'secondary');
  const st = data.detail;
  if (data.role === state.role && data.page === state.page && data.status === 'empty') return head('Снимок и заключение', '', back) + '<div class="panel empty"><h3>Исследований пока нет</h3><p>Новые исследования появятся в списке, когда придут из РИС или от пациента.</p></div>';
  if (!ready() || !st) return head('Снимок и заключение', '', back) + gate();
  const source = st.uploaded_by_role === 'patient' ? 'загрузил пациент' : 'выгрузка из РИС, демо';
  const intro = head(safe(st.patient), `${safe(st.title)} · ${safe(fmt(st.created_at))} · ${source}`, studyBadge(st) + back);
  if (st.status === 'unavailable') return intro + `<div class="note">${safe(st.message)}. Попросите загрузить исследование заново.</div>`;
  const info = st.study;
  const findings = st.findings.length ? st.findings.map(f => `<div class="finding"><span class="dot now"></span><span><strong>${safe(f.description)}</strong><small>${safe(f.place)}</small>${f.confidence != null ? `<small>Оценка модели: ${safe(f.confidence)}</small>` : ''}</span></div>`).join('')
    : st.status === 'test_only' ? `<p>${safe(st.test_message)}</p>` : `<p>${safe(st.reason?.text || 'Находок нет.')}</p>${st.reason ? `<p class="muted" style="font-size:13px">Сервис снимков: ${safe(st.reason.original)}</p>` : ''}`;
  const right = st.status === 'awaiting_physician' ? draftPanel(st) : st.status === 'confirmed' ? afterPanel(st)
    : `<div class="panel"><h3>Заключение</h3><p style="margin:0">${st.status === 'test_only' ? 'Техническая проверка, анализ не выполнялся. Подтвердить нельзя.' : 'Подтвердить нельзя: сервис принимает заключение только с находкой модели. Врач описывает исследование сам, координатор видит его в группе «Снимки на ручном описании».'}</p></div>`;
  return intro + `${st.demo ? `<div class="note warn" style="margin-bottom:18px">${DEMO_NOTE}</div>` : ''}
    <div class="twocol study"><div class="stack">${viewer(st)}
        <div class="note">Модель отмечает только те находки, на которые её проверяли. ${info?.modality === 'MG' ? 'Категорию BI-RADS сервис не присваивает: её указывает врач.' : 'Если протокол или область не подходят модели, исследование сразу уходит на ручное описание.'}</div></div>
      <div class="stack"><div class="panel"><h3>Находки ИИ</h3>${findings}
          <dl class="kv" style="margin-top:14px">${st.limitations?.length ? `<dt>Ограничения модели</dt><dd>${st.limitations.map(safe).join('<br>')}</dd>` : ''}<dt>Файлы</dt><dd>${info ? `${safe(info.instance_count)} ${plural(info.instance_count, ['файл', 'файла', 'файлов'])} · ${safe(info.series_count)} ${plural(info.series_count, ['серия', 'серии', 'серий'])}` : 'Не прочитаны'}</dd>${info ? `<dt>Протокол</dt><dd>${safe(info.protocol_name)} · ${safe(info.anatomy)}</dd>` : ''}<dt>Проверка DICOM</dt><dd>${info ? 'Пройдена' : 'Не пройдена'}</dd></dl></div>
        ${right}</div></div>`;
}

/* ---------- Координатор: группа в «Обращениях» ---------- */
export function manualStudiesBlock(){
  if (data.role !== state.role || data.page !== 'inbox') return '';
  if (data.status === 'error') return errorNote(data.message, 'imagingRetry');
  if (data.status !== 'ok') return '';
  const warn = data.notRouted.length ? `<div class="note red" style="margin-top:14px">${data.notRouted.map(s => `${safe(s.patient)}, ${safe(s.title)}: ${safe(s.warning)}`).join('<br>')}</div>` : '';
  return `<div class="sectionhead"><h2>Снимки на ручном описании</h2></div>
    ${data.manual.length ? `<div class="tablewrap"><table><thead><tr><th>Пациент</th><th>Исследование</th><th>Загружено</th></tr></thead><tbody>${data.manual.map(s => `<tr><td><strong>${safe(s.patient)}</strong></td><td>${safe(s.title)}</td><td>${safe(fmt(s.created_at))}</td></tr>`).join('')}</tbody></table></div><p class="muted" style="font-size:13px">Эти снимки врач описывает сам. Свяжитесь с пациентом и договоритесь, как он получит заключение.</p>` : '<div class="note">Снимков на ручном описании нет.</div>'}${warn}`;
}
export const demoSource = model => String(model || '').startsWith('demo-') ? `<div class="note warn" style="margin-top:10px">${DEMO_NOTE}</div>` : '';

/* ---------- Действия ---------- */
async function sendStudy(run, success){
  if (data.busy) return;
  data.busy = true;
  document.querySelectorAll('[data-action=upload],[data-action=uploadKitSend]').forEach(b => { b.disabled = true; });
  try { await run(); closeModal(); toast(success); }
  catch (err){ toast(err.message); }
  finally { data.busy = false; document.querySelectorAll('[data-action=upload],[data-action=uploadKitSend]').forEach(b => { b.disabled = false; }); }
  if (state.page === 'imaging') await refreshImaging(); else { state.role = 'patient'; go('imaging'); }
}
export function installImagingActions(actions){
  actions.imagingRetry = () => refreshImaging();
  actions.uploadOpen = () => { state.role = 'patient'; go('imaging'); uploadModal(); };
  actions.upload = () => {
    const file = $('#upFile')?.files?.[0];
    if (!file) return toast('Выберите ZIP-архив с исследованием.');
    if (!/\.zip$/i.test(file.name)) return toast('Нужен ZIP-архив с файлами DICOM. Упакуйте папку исследования в ZIP.');
    if (file.size > MAX_ARCHIVE) return toast('Архив больше 50 МиБ. Загрузите исследование без лишних файлов.');
    if (!$('#upConsent')?.checked) return toast('Отметьте согласие на передачу исследования врачу.');
    const task = $('#upKind').value;
    sendStudy(() => uploadArchive(`/api/patient/studies?task=${enc(task)}&consent=1`, 'patient', file), 'Исследование отправлено врачу');
  };
  actions.uploadKit = async () => {
    const box = $('#upKit');
    if (!box) return;
    box.innerHTML = loadingCards(1);
    try {
      const list = (await api('GET', '/api/demo/studies', {role:'patient'})).studies || [];
      box.innerHTML = `<div class="tlgroup" style="margin-top:16px">Учебные исследования стенда · демо</div>${list.map(s => `<div class="slot"><div><strong>${safe(s.label)}</strong><div class="meta">Синтетический архив стенда</div></div>${btn('Отправить', 'uploadKitSend', 'small', {name:s.name})}</div>`).join('') || '<p>Учебных исследований нет. Перезапустите стенд: python start.py</p>'}`;
    } catch (err){ box.innerHTML = errorNote('Не удалось загрузить список. ' + err.message, 'uploadKit'); }
  };
  actions.uploadKitSend = d => {
    if (!$('#upConsent')?.checked) return toast('Отметьте согласие на передачу исследования врачу.');
    sendStudy(() => api('POST', `/api/demo/studies/${enc(d.name)}/submit`, {role:'patient', body:{consent:true}}), 'Учебное исследование отправлено врачу');
  };
  actions.studyOpen = d => { state.sel.study = d.id; go('study'); };
  actions.studyStep = d => { const n = data.detail?.images?.length || 0; if (!n) return; data.index = (Math.min(data.index, n - 1) + Number(d.step) + n) % n; render(); };
  actions.studyCode = d => { data.code = d.code; render(); };
  actions.studyConfirm = async d => {
    const area = $('#studyDraft');
    const text = area ? area.value : '';
    if (!text.trim()) return toast('Заключение пустое. Напишите текст и подтвердите.');
    if (data.busy) return;
    data.drafts[d.code] = text;
    data.busy = true; render();
    try {
      await api('POST', `/api/doctor/studies/${enc(d.id)}/confirm`, {role:'doctor', body:{conclusion:text, finding_code:d.code}});
    } catch (err){
      data.busy = false; render(); toast(err.message);  // текст врача остаётся в поле
      return;
    }
    data.busy = false;
    data.detailId = null;
    toast('Заключение подтверждено');
    await refreshImaging();
  };
}

document.addEventListener('input', e => {
  if (e.target.id !== 'studyDraft') return;
  data.drafts[e.target.dataset.code] = e.target.value;
  const count = $('#draftCount');
  if (count) count.textContent = e.target.value.length;
});
