/* Задание 05: «Что на снимке?» на сервисе снимков через шлюз. Схем и демо-содержания здесь нет:
   только настоящие срезы, статусы и заключения. До подтверждения врачом пациент видит один статус. */
import { api, imageUrl, uploadArchive } from './api.js';
import { icon } from './icons.js';
import { sessions, state, ui } from './state.js';
import { $, badge, btn, closeModal, errorNote, go, loadingCards, modalHead, navBtn, openModal, safe, toast } from './ui.js';
import { render } from './shell.js';

const MAX_ARCHIVE = 50 * 1024 * 1024;
const HERE = {patient:['imaging'], staff:['inbox']};
export const isImagingPage = () => (HERE[state.role] || []).includes(state.page);
/* Список перечитывается раз в 15 секунд. Исследования врача — в кабинете rescan (rescan-studies.js) */
export const isImagingListPage = isImagingPage;

const data = {role:null, page:null, status:'loading', message:'', items:[], manual:[], notRouted:[], busy:false,
              assistant:null, explain:{}};  // задание 11: ИИ-помощник
const blobs = new Map();
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
  if (data.role !== role || data.page !== page){ Object.assign(data, {role, page, status:'loading', message:''}); render(); }
  /* Без ключа в шлюзе кнопок помощника нет; ошибка запроса — тоже «выключен», экран работает как раньше */
  if (data.assistant === null && page === 'imaging')
    data.assistant = await api('GET', '/api/assistant/status', {role}).then(r => r.enabled === true, () => false);
  try {
    if (page === 'imaging') data.items = (await api('GET', '/api/patient/studies', {role})).studies || [];
    else if (page === 'inbox'){ const r = await api('GET', '/api/staff/studies/manual', {role}); data.manual = r.manual || []; data.notRouted = r.not_routed || []; }
    data.status = 'ok';
  } catch (err){ data.status = 'error'; data.message = 'Не удалось загрузить исследования. ' + err.message; }
  if (state.role === role && state.page === page && !ui.modal) render();
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
        ${explainBlock(st)}
        <div class="resultmain" style="padding:20px"><div class="eyebrow">Что дальше</div><strong style="font-size:20px">${safe(nx.head)}</strong>${nx.text ? `<p style="margin:7px 0 0">${safe(nx.text)}</p>` : ''}${nx.buttons ? `<div class="actions" style="margin-top:14px">${nx.buttons}</div>` : ''}</div>
      </div>
    </div>
    <details class="more"><summary>Заключение врача полностью</summary><div class="quote">${safe(st.conclusion).replace(/\n+/g, '<br>')}<br><br><span class="muted">Подтверждено ${safe(fmt(st.confirmed_at))}</span></div></details>
  </div>`;
}
/* Пояснение помощника — под утверждённым текстом клиники, не вместо него */
function explainBlock(st){
  if (!data.assistant) return '';
  const e = data.explain[st.id];
  if (e?.status === 'ok') return `<div class="note"><div class="eyebrow">Пояснение ИИ-помощника. Это не заключение врача</div><p class="plain" style="margin:6px 0 0">${safe(e.text).replace(/\n+/g, '<br>')}</p><p style="margin:8px 0 0"><strong>Вопросы по результату задайте врачу.</strong></p></div>`;
  if (e?.status === 'error') return errorNote(e.message, 'studyExplain', {id:st.id});
  return `<div class="actions" style="margin-top:0">${btn(e?.status === 'loading' ? 'Готовим объяснение…' : 'Объяснить подробнее', 'studyExplain', 'secondary small', {id:st.id})}</div>`;
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
  actions.studyExplain = async d => {
    if (data.explain[d.id]?.status === 'loading') return;
    data.explain[d.id] = {status:'loading'}; render();
    try {
      const r = await api('POST', `/api/patient/studies/${enc(d.id)}/assistant/explain`, {role:'patient', body:{}});
      data.explain[d.id] = {status:'ok', text:r.explanation};
    } catch (err){ data.explain[d.id] = {status:'error', message:'Не получилось подготовить объяснение. ' + err.message}; }
    render();
  };
}
