/* Приложение пациента rescan (задание 13): телефон из prototype/rescan-app-standalone.html на данных шлюза.
   Экраны #/patient/rsHome … rsProfile рисуются в #view внутри .ph; полоса с логотипом и списком ролей — на месте
   прежней шапки (#topbar), как у врача. Стили — phone.css. Действия — через ACTIONS и data-action. */
import { api } from './api.js';
import { health, sessions, state, ui } from './state.js';
import { go, safe, toast } from './ui.js';
import { statusName } from './path-ui.js';
import { uploadHooks, uploadModal } from './imaging-ui.js';

export const PH_PAGES = ['rsHome', 'rsReport', 'rsResults', 'rsCare', 'rsCalendar', 'rsBook', 'rsStep', 'rsVisits', 'rsProfile'];
export const isPhonePage = () => state.role === 'patient' && PH_PAGES.includes(state.page);

/* ---------- Значки и шары образца ---------- */
const IC = {
  home:'M4 11l8-7 8 7v9h-5v-6H9v6H4z',
  pill:'M10.5 20.5a4.95 4.95 0 0 1-7-7l6-6a4.95 4.95 0 0 1 7 7zM7.5 10.5l6 6',
  cal:'M5 5h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM8 3v4M16 3v4M4 10h16',
  bag:'M5 8h14l-1 12H6zM9 8V6a3 3 0 0 1 6 0v2',
  user:'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c1-4 4.5-6 8-6s7 2 8 6',
  doc:'M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6',
  back:'M15 6l-6 6 6 6', chev:'M9 6l6 6-6 6', plus:'M12 5v14M5 12h14', check:'M5 12l5 5L20 7',
  scan:'M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M8 12h8',
  steth:'M6 3v6a4 4 0 0 0 8 0V3M10 13v2a5 5 0 0 0 10 0v-2',
  heart:'M12 20s-8-5-8-11a4.5 4.5 0 0 1 8-2.5A4.5 4.5 0 0 1 20 9c0 6-8 11-8 11z',
  map:'M12 21s-7-6-7-11a7 7 0 0 1 14 0c0 5-7 11-7 11zM12 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z'
};
const ic = (n, s = 22, w = 1.7) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${IC[n]}"/></svg>`;
let uid = 0;
function orb(w, icon, light){
  const id = 'po' + (uid++);
  return `<svg width="${w}" height="${w}" viewBox="0 0 100 100" aria-hidden="true"><defs><radialGradient id="${id}" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="${light ? '#E6EFEC' : '#8FB3AA'}"/><stop offset=".35" stop-color="${light ? '#A2C3BB' : '#3C5D55'}"/><stop offset=".8" stop-color="${light ? '#517B71' : '#141F1C'}"/><stop offset="1" stop-color="${light ? '#283E38' : '#050807'}"/></radialGradient></defs>`
    + `<ellipse cx="50" cy="94" rx="30" ry="4" fill="#000" opacity=".5"/><circle cx="50" cy="50" r="42" fill="url(#${id})"/><ellipse cx="38" cy="26" rx="16" ry="9" fill="#fff" opacity=".28" transform="rotate(-20 38 26)"/>`
    + `<g transform="translate(32 32) scale(1.5)" stroke="${light ? '#0E1614' : 'rgba(255,255,255,.88)'}" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="${IC[icon]}"/></g></svg>`;
}
const KIND_ICON = {appointment:'steth', test:'scan', follow_up:'cal', care_coordination:'user', manual_review:'doc'};
const KIND_NAME = {appointment:'Приём', test:'Исследование', follow_up:'Наблюдение', care_coordination:'Помощь координатора', manual_review:'План врача'};

/* ---------- Статичный фон «мох»: canvas образца, без анимации; картинка рисуется один раз и кешируется ---------- */
function rng(seed){ let s = seed >>> 0 || 1; return () => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; }; }
function mossCanvas(w, h, opt){
  const R = rng(opt.seed || 7), T = new Float32Array(256 * 256);
  for (let i = 0; i < T.length; i++) T[i] = R();
  const n = (x, y) => { const xi = Math.floor(x), yi = Math.floor(y); let xf = x - xi, yf = y - yi; xf = xf * xf * (3 - 2 * xf); yf = yf * yf * (3 - 2 * yf);
    const a = T[((xi & 255) << 8) | (yi & 255)], b = T[(((xi + 1) & 255) << 8) | (yi & 255)], c = T[((xi & 255) << 8) | ((yi + 1) & 255)], d = T[(((xi + 1) & 255) << 8) | ((yi + 1) & 255)];
    return a + (b - a) * xf + (c - a) * yf + (a - b - c + d) * xf * yf; };
  const H = (u, v) => n(u, v) * .62 + n(u * 2.03 + 5, v * 2.03 + 3) * .26 + n(u * 4.1 + 9, v * 4.1 + 1) * .12;
  const hz = h * opt.crest, camH = opt.camH, proj = h * opt.proj, amp = opt.amp, sc = opt.sc, off = R() * 50;
  const img = new ImageData(w, h), D = img.data;
  for (let p = 3; p < D.length; p += 4) D[p] = 255;
  const lx = -.7, ly = .45;
  for (let x = 0; x < w; x++){
    let maxY = h;
    for (let z = opt.z0; z < 26; z += .009 * z + .004){
      const u = (x / w - .5) * z * 1.25 + off, v = z + off * .7, hh = H(u * sc, v * sc) * amp;
      const y = Math.floor(hz + (camH - hh) / z * proj);
      if (y < maxY){
        const e = .05, gx = (H((u + e) * sc, v * sc) - H((u - e) * sc, v * sc)) * amp / (2 * e), gy = (H(u * sc, (v + e) * sc) - H(u * sc, (v - e) * sc)) * amp / (2 * e);
        let lam = .42 + (-gx * lx + gy * ly) * 1.05; lam = Math.max(0, Math.min(1.25, lam));
        let fog = Math.max(0, 1 - (z - 1) / opt.fogd); fog *= fog;
        const L = lam * fog, y0 = Math.max(0, y);
        for (let yy = y0; yy < maxY; yy++){
          const k = (yy * w + x) * 4, r = (yy - y) / (maxY - y + 1), l = Math.pow(L * (1 - .3 * r), 1.5);
          D[k] = 4 + l * 72; D[k + 1] = 8 + l * 116; D[k + 2] = 7 + l * 96;
        }
        maxY = y0; if (maxY <= 0) break;
      }
    }
  }
  const c = document.createElement('canvas'); c.width = w * 2; c.height = h * 2;
  const x2 = c.getContext('2d'), t = document.createElement('canvas'); t.width = w; t.height = h; t.getContext('2d').putImageData(img, 0, 0);
  x2.imageSmoothingQuality = 'high'; x2.drawImage(t, 0, 0, w * 2, h * 2);
  const B = 16, P = []; for (let b = 0; b < B; b++) P.push(new Path2D());
  const N = Math.round(w * h * 1.3);
  for (let i = 0; i < N; i++){
    const px = R() * w, py = R() * h, k = ((py | 0) * w + (px | 0)) * 4, lum = (D[k + 1] - 8) / 128; if (lum < .02) continue;
    const v = Math.min(1, lum * (.75 + R() * .6)), bi = Math.min(B - 1, Math.floor(v * B));
    const ang = -Math.PI / 2 - .5 + (R() - .5) * 1.4, len = (.8 + R() * 2.2) * (.6 + lum);
    P[bi].moveTo(px * 2, py * 2); P[bi].lineTo((px + Math.cos(ang) * len) * 2, (py + Math.sin(ang) * len) * 2);
  }
  x2.lineCap = 'round';
  for (let q = 0; q < B; q++){ const f = q / (B - 1); x2.strokeStyle = `hsl(${156 - f * 8},${22 + f * 14}%,${4 + f * f * 66}%)`; x2.lineWidth = .9 + f * .5; x2.globalAlpha = .35 + f * .4; x2.stroke(P[q]); }
  return c;
}
const MOSS = {};
function moss(key, w, h, opt = {}){
  if (MOSS[key]) return MOSS[key];
  try { MOSS[key] = mossCanvas(w, h, {seed:8, crest:.22, camH:3.3, amp:3, sc:.7, fogd:9, proj:.42, z0:1.2, ...opt}).toDataURL('image/jpeg', .86); }
  catch (err){ MOSS[key] = ''; }  // без canvas остаётся тёмный фон
  return MOSS[key];
}
const mossStyle = (key, w, h, opt) => { const url = moss(key, w, h, opt); return url ? ` style="background-image:url(${url})"` : ''; };

/* ---------- Данные: {status:'loading'|'ok'|'error', data, message} ---------- */
const LOADERS = {
  studies:() => api('GET', '/api/patient/studies', {role:'patient'}).then(b => b.studies || []),
  episodes:() => api('GET', '/api/patient/episodes', {role:'patient'}),
  documents:() => api('GET', '/api/patient/documents', {role:'patient'}).then(b => b.referrals || []),
  assistant:() => api('GET', '/api/assistant/status', {role:'patient'})
};
const NEEDS = {rsHome:['studies', 'episodes'], rsReport:['studies', 'episodes', 'assistant'], rsResults:['studies'], rsCare:[],
               rsCalendar:['episodes'], rsBook:['episodes'], rsStep:['episodes'], rsVisits:['episodes'], rsProfile:['documents']};
export const ph = {};
const inflight = {};
const slots = {};  // ключ шага → {status, data, message}
let rerender = () => {};
export const setPhoneRender = fn => { rerender = fn; };

async function load(key){
  if (inflight[key]) return inflight[key];
  if (!ph[key]) ph[key] = {status:'loading', data:null, message:''};
  inflight[key] = (async () => {
    try { ph[key] = {status:'ok', data:await LOADERS[key](), message:''}; }
    catch (err){ ph[key] = {status:'error', data:ph[key].data, message:err.message}; }
    delete inflight[key];
    if (isPhonePage()) rerender();
  })();
  return inflight[key];
}
async function loadSlots(key){
  const [e, s] = key.split(':');
  slots[key] = {status:'loading', data:slots[key]?.data || null, message:''};
  rerender();
  try {
    const body = await api('GET', `/api/slots?episode=${enc(e)}&step=${enc(s)}`, {role:'patient'});
    slots[key] = {status:'ok', data:body.slots || [], message:''};
  } catch (err){ slots[key] = {status:'error', data:null, message:err.message}; }
  if (isPhonePage()) rerender();
}
/* Перечитать данные открытого экрана: при переходе и по таймеру main.js (timer = true).
   Экран выбора времени по таймеру не перерисовывается, пока пациент выбирает */
export function refreshPhone(timer = false){
  if (!isPhonePage() || sessions.patient?.status !== 'ok') return;
  if (timer && state.page === 'rsStep') return;
  (NEEDS[state.page] || []).forEach(load);
  if (!timer && state.page === 'rsStep' && ui.phKey && !slots[ui.phKey]) loadSlots(ui.phKey);
}

/* ---------- Состояния ---------- */
const enc = encodeURIComponent;
const skeleton = (n = 2) => `<div class="pskels" aria-busy="true" aria-label="Загружаем">${'<div class="c-skel"></div>'.repeat(n)}</div>`;
const errorBox = (message, action, data = '') => `<div class="perr" role="alert"><span>${safe(message)}</span><button class="gbtn" type="button" data-action="${action}" ${data}>Повторить</button></div>`;
const empty = (title, text) => `<div class="pempty"><b>${safe(title)}</b><span>${safe(text)}</span></div>`;
function stateOf(keys, view){
  for (const key of keys){
    const s = ph[key];
    if (!s || (s.status === 'loading' && s.data === null)) return skeleton();
    if (s.status === 'error' && s.data === null) return `<div class="sec">${errorBox('Не удалось загрузить данные. ' + s.message, 'phRetry', `data-key="${key}"`)}</div>`;
  }
  const stale = keys.find(key => ph[key].status === 'error');
  return (stale ? `<div class="sec">${errorBox('Не удалось обновить данные. ' + ph[stale].message, 'phRetry', `data-key="${stale}"`)}</div>` : '') + view(...keys.map(key => ph[key].data));
}

/* ---------- Форматы ---------- */
const asDate = v => { if (!v) return null; const d = new Date(v); return Number.isNaN(+d) ? null : d; };
const fmt = v => { const d = asDate(v); return d ? new Intl.DateTimeFormat('ru-RU', {day:'numeric', month:'long', hour:'2-digit', minute:'2-digit'}).format(d) : ''; };
const fmtDay = v => { const d = asDate(v); return d ? new Intl.DateTimeFormat('ru-RU', {day:'numeric', month:'long'}).format(d) : ''; };
const hhmm = v => { const d = asDate(v); return d ? new Intl.DateTimeFormat('ru-RU', {hour:'2-digit', minute:'2-digit'}).format(d) : ''; };
const FORMATS = {in_person:'Очно', online:'Онлайн', 'Очно':'Очно'};
const greet = () => { const h = new Date().getHours(); return h >= 5 && h < 12 ? 'Доброе утро' : h >= 12 && h < 17 ? 'Добрый день' : h >= 17 && h < 23 ? 'Добрый вечер' : 'Доброй ночи'; };
const patientName = () => sessions.patient?.data?.name || 'Пациент';

/* ---------- Путь: текущий шаг, этап, герой экрана ---------- */
const DONE = ['completed', 'superseded', 'closed'];
const current = e => (e.steps || []).find(s => !DONE.includes(s.status));
const keyOf = (e, s) => `${e.id}:${s.id}`;
const needsAction = e => { const s = current(e); return e.status === 'active' && s && ['open', 'offered'].includes(s.status); };
/* 1 — заключение подтверждено, плана нет или ручной разбор; 2 — нужно записаться; 3 — запись есть; 4 — ждём итог врача */
function stageOf(e){
  const s = current(e);
  if (e.status === 'manual_review' || !s || s.kind === 'manual_review') return s || e.status === 'manual_review' ? 1 : 0;
  return {open:2, offered:2, confirmed:3, attended:4}[s.status] || 1;
}
function hero(episodes){
  const list = [...episodes].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
  return list.find(needsAction) || list.find(e => e.status !== 'closed' && current(e)) || list[0] || null;
}
const dueText = s => s.appointment_at ? 'Запись: ' + fmt(s.appointment_at) : s.due_at ? 'Срок: до ' + fmtDay(s.due_at) : 'Срок — в описании шага';
function appointmentOf(data, e, s){
  return (data.appointments || []).filter(a => a.episode_id === e.id && a.step_id === s.id && ['offered', 'confirmed'].includes(a.status)).pop() || null;
}
function heroLine(e){
  const s = current(e);
  if (e.status === 'paused') return {lb:'Отложено', nm:'Координатор свяжется с вами', wh:e.title, icon:'user'};
  if (e.status === 'manual_review' || s?.kind === 'manual_review') return {lb:'Сейчас', nm:'Врач уточняет план', wh:'Мы покажем шаг, как только врач его назначит', icon:'doc'};
  if (!s) return {lb:'Готово', nm:'План выполнен', wh:'Все шаги по этому исследованию сделаны', icon:'check', light:true};
  if (s.status === 'offered') return {lb:'Клиника предложила время', nm:s.description, wh:fmt(s.appointment_at), icon:KIND_ICON[s.kind] || 'steth', action:'phOpenStep', key:keyOf(e, s)};
  if (s.status === 'open') return {lb:'Следующий шаг', nm:s.description, wh:dueText(s), icon:KIND_ICON[s.kind] || 'steth', action:'phOpenStep', key:keyOf(e, s)};
  if (s.status === 'confirmed') return {lb:'Вы записаны', nm:s.description, wh:fmt(s.appointment_at), icon:'check', light:true, nav:'rsVisits'};
  return {lb:'Были на приёме', nm:s.description, wh:'Ждём итог врача', icon:'check', light:true, nav:'rsVisits'};
}
const clickAttrs = x => x.action ? `data-action="${x.action}" data-key="${safe(x.key)}"` : `data-nav="${x.nav || 'rsHome'}"`;
function dots(n){ let h = ''; for (let i = 1; i <= 4; i++){ h += `<i class="${i < n ? 'on' : i === n ? 'cur' : ''}"></i>`; if (i < 4) h += `<b class="${i < n ? 'on' : ''}"></b>`; } return `<span class="dots">${h}</span>`; }
const STAGE_LEFT = ['', 'ждём план врача', 'записаться и прийти', 'прийти на приём', 'ждём итог врача'];

/* ---------- Экраны ---------- */
function hd(title, sub, right = '', back = ''){
  return `<header class="hd">${back ? `<button class="cbtn" type="button" ${back} aria-label="Назад">${ic('back', 20, 2.2)}</button>` : ''}<div class="tt"><h1>${title}</h1>${sub ? `<span class="st">${sub}</span>` : ''}</div>${right}</header>`;
}
function rsHome(){
  return stateOf(['studies', 'episodes'], (studies, data) => {
    const episodes = data.episodes || [], e = hero(episodes);
    const waiting = studies.filter(st => ['processing', 'awaiting'].includes(st.status));
    const head = `<div class="hello"><div style="flex:1;min-width:0"><div class="g">${greet()}</div><h1>${safe(patientName())}</h1></div><button class="cbtn" type="button" data-nav="rsResults" aria-label="Мои исследования">${ic('doc', 20, 2)}</button></div>`;
    if (!e){
      const body = waiting.length ? `<button class="next glass" type="button" data-nav="rsResults"><span><span class="lb">${waiting[0].status === 'processing' ? 'Обрабатывается' : 'Ждёт врача'}</span><br><span class="nm">${safe(waiting[0].title)}</span><br><span class="wh">Результат и план появятся после проверки врачом</span></span>${orb(70, 'scan')}</button>`
        : `<button class="next glass" type="button" data-nav="rsResults"><span><span class="lb">Исследований пока нет</span><br><span class="nm">Загрузите снимок</span><br><span class="wh">Врач проверит его и подскажет следующий шаг</span></span>${orb(70, 'plus', true)}</button>`;
      return head + `<div class="moss phero"${mossStyle('home', 400, 400, {crest:.16})}>${body}</div>${planList(episodes, studies)}`;
    }
    const n = stageOf(e), x = heroLine(e);
    return head + `<div class="moss phero"${mossStyle('home', 400, 400, {crest:.16})}>
      <div class="trow"><button class="tbox glass" type="button" data-action="phReport" data-id="${safe(studyOfEpisode(studies, e)?.id || '')}" aria-label="Пройдено этапов: ${n} из 4"><span class="n">${n}</span><span class="of">/ 4</span><span style="font-size:11px;line-height:1.25;color:var(--fg-2);align-self:flex-end;margin-bottom:22px;white-space:nowrap">этапа<br>пройдено</span></button>
      <button class="tbox glass" type="button" data-action="phReport" data-id="${safe(studyOfEpisode(studies, e)?.id || '')}" style="flex-direction:column;align-items:stretch;justify-content:center;gap:9px"><span style="font-size:10px;letter-spacing:.08em;color:var(--fg-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${safe(String(e.title || '').toUpperCase())}</span>${dots(n)}<span style="font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" class="mut">${STAGE_LEFT[n] || ''}</span></button></div>
      <button class="next glass" type="button" ${clickAttrs(x)} id="phNext"><span style="min-width:0"><span class="lb">${safe(x.lb)}</span><br><span class="nm">${safe(x.nm)}</span><br><span class="wh">${safe(x.wh)}</span></span>${orb(70, x.icon, x.light)}</button></div>${planList(episodes, studies)}`;
  });
}
const studyOfEpisode = (studies, e) => studies.find(st => st.episode?.id === e.id) || null;
function planList(episodes, studies){
  const rows = [];
  studies.filter(st => ['processing', 'awaiting', 'manual'].includes(st.status)).forEach(st =>
    rows.push(`<button class="srow" type="button" data-nav="rsResults"><span><div class="nm">${safe(st.title)}</div><div class="ds">${st.status === 'manual' ? 'врач описывает сам' : 'ждёт проверки врача'}</div></span><span class="pchip">${st.status === 'manual' ? 'Врач описывает' : 'Ждёт врача'}</span></button>`));
  episodes.forEach(e => {
    const st = studyOfEpisode(studies, e);
    rows.push(`<button class="srow done" type="button" data-action="phReport" data-id="${safe(st?.id || '')}"><span><div class="nm">${safe(e.title)}</div><div class="ds">${safe(fmtDay(e.created_at))} · заключение подтверждено врачом</div></span><span class="pchip">Готово</span></button>`);
    (e.steps || []).forEach(s => {
      const done = DONE.includes(s.status) || s.status === 'cancelled';
      const chip = s.status === 'completed' ? '<span class="pchip">Выполнено</span>' : s.status === 'superseded' ? '<span class="pchip">Заменён</span>'
        : ['open', 'offered'].includes(s.status) && e.status === 'active' ? '<span class="pchip good">Записаться</span>' : `<span class="pchip mod">${safe(statusName(s.status))}</span>`;
      const go = ['open', 'offered'].includes(s.status) && e.status === 'active' ? `data-action="phOpenStep" data-key="${safe(keyOf(e, s))}"` : 'data-nav="rsVisits"';
      rows.push(`<button class="srow${done ? ' done' : ''}" type="button" ${go}><span><div class="nm">${safe(s.description)}</div><div class="ds">${safe(s.kind === 'manual_review' ? 'врач назначит шаг' : dueText(s))}</div></span>${chip}</button>`);
    });
  });
  return `<div class="pstack"><span class="lab">Ваш план</span>${rows.join('') || empty('Плана пока нет', 'Он появится, когда врач подтвердит заключение по вашему исследованию.')}</div>`;
}

/* «Заключение»: текст врача без подсветки, объяснение, срез, пояснение помощника, шаги */
function rsReport(){
  return stateOf(['studies', 'episodes', 'assistant'], (studies, data, assistant) => {
    const confirmed = studies.filter(st => st.status === 'confirmed');
    const st = confirmed.find(x => x.id === ui.phStudy) || confirmed[0];
    const back = 'data-nav="rsResults"';
    if (!st) return hd('Заключение', '', '', back) + `<div class="sec">${empty('Подтверждённых заключений пока нет', 'Заключение появится здесь после проверки врачом.')}</div>`;
    const e = (data.episodes || []).find(x => x.id === st.episode?.id) || st.episode;
    const picture = st.image?.sop_uid ? `<div class="shot"><img class="studyimg" alt="${safe(st.image.label)}" data-api-src="/api/patient/studies/${enc(st.id)}/images/${enc(st.image.sop_uid)}.png"><span>${safe(st.image.label)} · просмотр для проверки, не диагностический просмотрщик</span></div>` : '';
    const steps = e ? (e.steps || []).map((s, i) => { const cur = current(e)?.id === s.id; const done = DONE.includes(s.status);
      return `<div class="rs"><span class="st ${done ? 'on' : cur ? 'cur' : ''}">${done ? ic('check', 16, 2.6) : i + 1}</span><span style="flex:1;min-width:0"><div class="nm">${safe(s.description)}</div><div class="ds">${safe(statusName(s.status))} · ${safe(s.kind === 'manual_review' ? 'врач назначит шаг' : dueText(s))}</div></span>${cur && needsAction(e) ? `<button class="pchip good" type="button" data-action="phOpenStep" data-key="${safe(keyOf(e, s))}" style="border:0;height:30px">Записаться</button>` : ''}</div>`; }).join('') : '';
    return hd('Заключение', `${safe(st.title)} · подтверждено ${safe(fmtDay(st.confirmed_at))}`, '', back) + `<div class="sec">
      ${st.plain ? `<div class="pnote"><div class="eye">Простыми словами · текст утвердил врач</div><p class="plain">${safe(st.plain.text).replace(/\n+/g, '<br>')}</p></div><span class="lab">Заключение врача</span>` : ''}
      <div class="rep">${safe(st.conclusion).replace(/\n+/g, '<br>')}</div>
      ${picture}
      <div class="pnote"><div class="eye">Что увидели</div><p class="plain">${safe(st.explanation?.seen)}</p></div>
      <div class="pnote"><div class="eye">Что это значит</div><p class="plain">${safe(st.explanation?.means)}</p></div>
      ${assistant?.enabled === true ? explainBlock(st) : ''}
      ${steps ? `<span class="lab">Что делать дальше</span><div class="route">${steps}</div>` : ''}
      <div class="route" style="padding:14px 20px"><div class="mut" style="font-size:12px;line-height:1.5">План составлен по правилам клиники и подтверждён врачом. Сервис не ставит диагноз.</div></div>
      <button class="gbtn" type="button" data-nav="rsResults">Все исследования</button></div>`;
  });
}
const explained = {};
function explainBlock(st){
  const x = explained[st.id];
  if (x?.status === 'ok') return `<div class="pnote"><div class="eye">Пояснение ИИ-помощника. Это не заключение врача</div><p class="plain">${safe(x.text).replace(/\n+/g, '<br>')}</p><p class="plain"><b>Вопросы по результату задайте врачу.</b></p></div>`;
  if (x?.status === 'error') return errorBox(x.message, 'phExplain', `data-id="${safe(st.id)}"`);
  return `<button class="gbtn" type="button" data-action="phExplain" data-id="${safe(st.id)}"${x?.status === 'loading' ? ' disabled' : ''}>${x?.status === 'loading' ? 'Готовим объяснение…' : 'Объяснить подробнее'}</button>`;
}

/* «Результаты»: исследования пациента со статусами и загрузка снимка */
const STUDY_STATUS = {processing:['Обрабатывается', 'mod'], awaiting:['Ждёт врача', 'mod'], manual:['Врач описывает сам', 'mod'], confirmed:['Подтверждено врачом', 'good'], unavailable:['Недоступно', 'low']};
function rsResults(){
  return hd('Результаты', 'Ваши исследования', `<button class="cbtn" type="button" data-action="phUpload" aria-label="Загрузить снимок">${ic('plus', 22, 2)}</button>`) + stateOf(['studies'], studies => {
    const rows = studies.map(st => { const [label, tone] = STUDY_STATUS[st.status] || [st.status, 'mod'];
      const text = st.status === 'confirmed' ? 'Заключение врача, объяснение и следующий шаг' : st.status === 'manual' ? 'Этот снимок врач описывает сам. Координатор свяжется с вами.'
        : st.status === 'unavailable' ? safe(st.message) + '. Загрузите исследование заново или напишите координатору.' : 'Результат и план появятся после проверки врачом.';
      const open = st.status === 'confirmed' ? `data-action="phReport" data-id="${safe(st.id)}"` : '';
      return `<${open ? 'button' : 'div'} class="mrow" ${open ? 'type="button" ' + open : ''} data-study="${safe(st.id)}"><span class="t"><span><div class="nm">${safe(st.title)}</div><div class="ds">загружено ${safe(fmt(st.created_at))}</div></span><span class="pchip ${tone}">${safe(label)}</span></span><span class="ds" style="margin-top:6px">${st.status === 'unavailable' ? text : safe(text)}</span></${open ? 'button' : 'div'}>`; }).join('');
    return `<div class="sec">${rows || empty('Исследований пока нет', 'Загрузите снимок из другой клиники или возьмите учебное исследование.')}
      <button class="wbtn" type="button" data-action="phUpload">Загрузить снимок</button>
      <p class="mut3" style="font-size:11px;margin:0 4px">ИИ не ставит диагноз. Он помогает врачу описать снимок. Заключение всегда подтверждает врач.</p></div>`;
  });
}

/* «Запись»: только шаги своего плана, которые ждут записи */
function rsBook(){
  return hd('Запись', 'Шаги вашего плана') + stateOf(['episodes'], data => {
    const tiles = (data.episodes || []).filter(needsAction).map(e => { const s = current(e), offered = s.status === 'offered';
      return `<button class="ptile${offered ? ' w' : ''}" type="button" data-action="phOpenStep" data-key="${safe(keyOf(e, s))}"><span class="ct">${safe(e.title)}</span><span class="nm">${safe(s.description)}</span><span class="pr">${offered ? 'клиника предложила время' : safe(dueText(s))}</span><span class="art">${orb(108, KIND_ICON[s.kind] || 'steth', offered)}</span><span class="plus" aria-hidden="true">${ic('plus', 18, 2.2)}</span></button>`; }).join('');
    return tiles ? `<div class="pgrid">${tiles}</div>` : `<div class="sec">${empty('Сейчас записываться не на что', 'Когда врач назначит шаг, он появится здесь.')}<button class="gbtn" type="button" data-nav="rsVisits">Мои записи</button></div>`;
  });
}

/* Экран шага: описание, срок, свободное время своей клиники, запись */
function rsStep(){
  return stateOf(['episodes'], data => {
    const [eid, sid] = String(ui.phKey || '').split(':');
    const e = (data.episodes || []).find(x => x.id === eid), s = e?.steps.find(x => x.id === sid);
    const back = 'data-nav="rsBook"';
    if (ui.phDone && ui.phDone.key === ui.phKey) return doneView(ui.phDone);
    if (!e || !s) return hd('Запись', '', '', back) + `<div class="sec">${empty('Шаг не найден', 'Возможно, план изменился. Откройте «Запись» заново.')}</div>`;
    const top = `<div class="moss dtop"${mossStyle('svc', 400, 360, {seed:33, crest:.42, proj:.35})}><button class="cbtn back" type="button" ${back} aria-label="Назад">${ic('back', 20, 2.2)}</button><div style="margin-bottom:10px">${orb(170, KIND_ICON[s.kind] || 'steth', true)}</div></div>
      <p class="para" style="margin:0 0 4px;color:var(--acc)">${safe(e.title)}</p><h1 class="dtitle" id="phStepTitle">${safe(s.description)}</h1>
      <div class="keys pcard" style="margin-top:14px"><div class="krow"><b>Вид</b><span>${safe(KIND_NAME[s.kind] || 'Шаг плана')}</span></div><div class="krow"><b>Срок</b><span>${safe(s.due_at ? 'до ' + fmtDay(s.due_at) : 'указан в описании шага')}</span></div><div class="krow"><b>Статус</b><span>${safe(statusName(s.status))}</span></div></div>`;
    if (!needsAction(e)){
      const a = appointmentOf(data, e, s);
      return top + `<div class="sec" style="margin-top:14px"><div class="box"><span class="h">${safe(statusName(s.status))}</span>${s.appointment_at ? `<span class="adr">${safe(fmt(s.appointment_at))}</span>` : ''}${a ? `<span class="mut" style="font-size:13px">${safe([a.place, a.specialist, FORMATS[a.format] || a.format].filter(Boolean).join(' · '))}</span>` : ''}</div><button class="gbtn" type="button" data-nav="rsVisits">Мои записи</button></div>`;
    }
    const offered = s.status === 'offered' ? `<div class="box"><span class="h">Клиника предложила время</span><span class="adr">${safe(fmt(s.appointment_at))}</span>
      <div class="pact"><button class="wbtn" type="button" data-action="phConfirm" data-key="${safe(ui.phKey)}">Подтвердить</button><button class="gbtn" type="button" data-action="phAsk" data-key="${safe(ui.phKey)}" data-intent="other_time">Другое время</button></div></div>` : '';
    return top + `<div class="sec" style="margin-top:14px">${offered}${slotPicker(ui.phKey)}
      <button class="gbtn" type="button" data-action="phAsk" data-key="${safe(ui.phKey)}" data-intent="later">Не сейчас</button>
      <p class="mut3" style="font-size:11px;margin:0 4px">«Не сейчас» передаёт координатору, что вы запишетесь позже. Он свяжется с вами.</p></div>`;
  });
}
function slotPicker(key){
  const x = slots[key];
  if (!x || (x.status === 'loading' && !x.data)) return '<div class="c-skel" aria-busy="true"></div>';
  if (x.status === 'error') return errorBox('Не удалось загрузить свободное время. ' + x.message, 'phSlotsRetry', `data-key="${safe(key)}"`);
  const list = x.data || [];
  if (!list.length) return `<div class="box"><span class="h">Свободного времени пока нет</span><span class="mut" style="font-size:13px">Координатор подберёт время и свяжется с вами.</span><button class="wbtn" type="button" data-action="phAsk" data-key="${safe(key)}" data-intent="callback">Попросить координатора</button></div>`;
  const days = [...new Set(list.map(sl => fmtDay(sl.starts_at)))];
  const day = days.includes(ui.phDay) ? ui.phDay : days[0];
  const today = list.filter(sl => fmtDay(sl.starts_at) === day);
  const chosen = list.find(sl => String(sl.id) === String(ui.phSlot)) || null;
  const dayBtn = d => { const sl = list.find(z => fmtDay(z.starts_at) === d), dt = asDate(sl.starts_at);
    return `<button class="day" type="button" data-action="phDay" data-day="${safe(d)}" aria-pressed="${d === day}"><span>${safe(new Intl.DateTimeFormat('ru-RU', {weekday:'short'}).format(dt))}</span><b>${dt.getDate()}</b></button>`; };
  return `<div class="box"><span class="h">День <span class="demo">· время учебное, демо</span></span><div class="days" role="group" aria-label="День">${days.map(dayBtn).join('')}</div>
    <span class="h">Время</span><div class="times" role="group" aria-label="Время">${today.map(sl => `<button class="tm" type="button" data-action="phSlot" data-slot="${safe(sl.id)}" aria-pressed="${chosen && String(chosen.id) === String(sl.id)}">${safe(hhmm(sl.starts_at))}</button>`).join('')}</div></div>
    ${chosen ? `<div class="box"><span class="h">Где и кто</span><span class="adr">${safe(chosen.place)}</span><span class="mut3" style="font-size:12px">${safe([chosen.specialist, FORMATS[chosen.format] || chosen.format, chosen.price ? chosen.price + ' ₽' : ''].filter(Boolean).join(' · '))}</span></div>` : ''}
    <button class="wbtn" type="button" data-action="phBook" data-key="${safe(key)}"${chosen && !ui.phBusy ? '' : ' disabled'}>${ui.phBusy ? 'Записываем…' : chosen ? 'Записаться на ' + safe(fmt(chosen.starts_at)) : 'Выберите время'}</button>`;
}
function doneView(d){
  return `<div class="moss" style="height:220px;margin-top:-50px"${mossStyle('done', 400, 220, {seed:41, crest:.2, proj:.5})}></div>
    <div class="success" style="margin-top:-60px" id="phDone"><span class="okc">${ic('check', 40, 2.6)}</span><h1 class="dtitle" style="padding:0">Вы записаны</h1><p class="mut" style="margin:0;font-size:14px">Клиника видит вашу запись.</p></div>
    <div class="sec" style="margin-top:18px"><div class="keys pcard" style="margin:0"><div class="krow"><b>${safe(d.step)}</b><span></span></div><div class="krow"><b>Когда</b><span>${safe(fmt(d.starts_at))}</span></div>${d.place ? `<div class="krow"><b>Где</b><span>${safe(d.place)}</span></div>` : ''}${d.format ? `<div class="krow"><b>Формат</b><span>${safe(FORMATS[d.format] || d.format)}</span></div>` : ''}</div>
    <button class="wbtn" type="button" data-action="phDoneClose">Готово</button></div>`;
}

/* «Мои записи»: статусы шагов, место и специалист из appointments */
const VISIT_TONE = {offered:'mod', confirmed:'mod', attended:'mod', completed:'good', cancelled:'low'};
const VISIT_NAME = {offered:'Предложена запись', confirmed:'Записаны', attended:'Были на приёме, ждём итог врача', completed:'Выполнено', cancelled:'Запись отменена'};
function visitList(data){
  const rows = [];
  (data.episodes || []).forEach(e => (e.steps || []).filter(s => s.appointment_at || ['attended', 'cancelled'].includes(s.status)).forEach(s => rows.push([e, s])));
  rows.sort((a, b) => String(b[1].appointment_at || '').localeCompare(String(a[1].appointment_at || '')));
  return rows;
}
function rsVisits(){
  return hd('Мои записи', 'Визит отмечает координатор, итог вносит врач', '', 'data-nav="rsHome"') + stateOf(['episodes'], data => {
    const rows = visitList(data).map(([e, s]) => { const a = appointmentOf(data, e, s);
      return `<div class="box" data-step="${safe(s.id)}"><div style="display:flex;align-items:center;gap:12px">${orb(56, KIND_ICON[s.kind] || 'steth', s.status === 'confirmed')}<span style="flex:1;min-width:0"><div style="font-size:17px;font-weight:700">${safe(s.description)}</div><div class="mut" style="font-size:12px">${safe(s.appointment_at ? fmt(s.appointment_at) : 'время не указано')}</div></span><span class="pchip ${VISIT_TONE[s.status] || 'mod'}">${safe(VISIT_NAME[s.status] || statusName(s.status))}</span></div>
        <span class="mut3" style="font-size:12px">${safe(a ? [a.place, a.specialist, FORMATS[a.format] || a.format].filter(Boolean).join(' · ') : 'Место уточнит координатор')}</span>
        ${s.status === 'confirmed' ? `<button class="gbtn" type="button" data-action="phAsk" data-key="${safe(keyOf(e, s))}" data-intent="other_time" style="min-height:44px;font-size:13px">Попросить координатора</button>` : ''}</div>`; }).join('');
    return `<div class="sec">${rows || `${empty('Пока нет записей', 'Записаться можно на шаги своего плана.')}<button class="wbtn" type="button" data-nav="rsBook">Перейти к записи</button>`}</div>`;
  });
}

/* «Календарь»: текущий месяц, дни с визитами и сроками, список ближайших */
function rsCalendar(){
  const now = new Date(), y = now.getFullYear(), m = now.getMonth();
  const title = new Intl.DateTimeFormat('ru-RU', {month:'long', year:'numeric'}).format(now);
  return hd(title.charAt(0).toUpperCase() + title.slice(1), 'Визиты и сроки шагов') + stateOf(['episodes'], data => {
    const marks = {};
    const events = [];
    (data.episodes || []).forEach(e => (e.steps || []).filter(s => !['superseded', 'closed', 'cancelled'].includes(s.status)).forEach(s => {
      const visit = asDate(s.appointment_at), due = asDate(s.due_at);
      if (visit){ events.push({at:visit, text:s.description, kind:'Визит'}); if (visit.getFullYear() === y && visit.getMonth() === m) marks[visit.getDate()] = 'y'; }
      else if (due && s.status !== 'completed'){ events.push({at:due, text:s.description, kind:'Срок'}); if (due.getFullYear() === y && due.getMonth() === m) marks[due.getDate()] = marks[due.getDate()] || 'p'; }
    }));
    const lead = (new Date(y, m, 1).getDay() + 6) % 7, total = new Date(y, m + 1, 0).getDate();
    let cells = '<span></span>'.repeat(lead);
    for (let d = 1; d <= total; d++) cells += `<span class="dd ${d === now.getDate() ? 't' : marks[d] || ''}"${d === now.getDate() ? ' aria-current="date"' : ''}>${d}</span>`;
    const soon = events.filter(x => x.at >= new Date(y, m, now.getDate())).sort((a, b) => a.at - b.at).slice(0, 6);
    return `<div class="sec" style="padding-bottom:10px"><div style="display:flex;gap:14px;font-size:11px;color:var(--fg-2);align-items:center;flex-wrap:wrap"><span><i style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--acc);margin-right:5px"></i>Визит</span><span><i style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--deep);margin-right:5px"></i>Срок шага</span></div></div>
      <div class="wk">${['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map(x => `<span>${x}</span>`).join('')}${cells}</div>
      <div class="sec" style="margin-top:16px"><span class="lab">Ближайшее</span>${soon.map(x => `<div class="todo"><span style="min-width:0"><div class="nm">${safe(x.text)}</div><div class="when acc">${safe(x.kind)} · ${safe(x.kind === 'Визит' ? fmt(x.at) : fmtDay(x.at))}</div></span></div>`).join('') || empty('Ближайших визитов и сроков нет', 'Они появятся, когда вы запишетесь на шаг плана.')}</div>`;
  });
}

function rsCare(){
  return hd('Лечение', 'Назначения врача') + `<div class="sec">${empty('Назначений пока нет', 'Назначения врача появятся здесь.')}</div>`;
}

function rsProfile(){
  const name = patientName(), letters = name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('') || '?';
  return `<header class="hd"><div class="tt"><h1>Профиль</h1></div></header>
    <div class="who"><span class="ava">${safe(letters)}</span><span style="flex:1;min-width:0"><div style="font-size:19px;font-weight:700">${safe(name)}</div><div class="mut3" style="font-size:12px">Клиника «Линия здоровья»</div></span></div>
    <div class="sec"><span class="lab">Направления</span>${stateOf(['documents'], refs => refs.length ? `<div class="grp">${refs.map(r => `<div class="sr"><span style="min-width:0">${safe(r.to_clinic_name)}<div class="mut3" style="font-size:12px;font-weight:500">${safe(r.reason)} · ${safe(fmtDay(r.created_at))}</div></span><span class="v">${safe(REF_STATUS[r.status] || r.status)}</span></div>`).join('')}</div>` : empty('Направлений нет', 'Направление в клинику-партнёр появится здесь, если координатор его оформит.'))}
    <span class="lab">Настройки</span><div class="grp"><div class="sr"><span>Клиника</span><span class="v">«Линия здоровья»</span></div><div class="sr"><span>Личные данные и уведомления</span><span class="v">на стенде не настраиваются</span></div></div></div>`;
}
const REF_STATUS = {proposed:'Отправлено', accepted:'Принято клиникой', rejected:'Отклонено', completed:'Услуга оказана', cancelled:'Отменено'};

/* ---------- Каркас телефона: экран, полоса «следующий шаг», вкладки ---------- */
const TABS = [['rsHome', 'home', 'Главная'], ['rsCare', 'pill', 'Лечение'], ['rsCalendar', 'cal', 'Календарь'], ['rsBook', 'bag', 'Запись'], ['rsProfile', 'user', 'Профиль']];
const TAB_OF = {rsHome:'rsHome', rsReport:'rsHome', rsResults:'rsHome', rsCare:'rsCare', rsCalendar:'rsCalendar', rsBook:'rsBook', rsStep:'rsBook', rsVisits:'rsBook', rsProfile:'rsProfile'};
function miniBar(){
  const data = ph.episodes?.data;
  if (!data || state.page === 'rsStep') return '';
  const e = hero(data.episodes || []);
  if (!e) return '';
  const x = heroLine(e), n = stageOf(e);
  return `<button class="mini" type="button" ${clickAttrs(x)}><span class="th">${orb(44, x.icon)}</span><span class="tx"><div class="t1">${safe(x.nm)}</div><div class="t2">${safe(x.lb)}${x.wh ? ' · ' + safe(x.wh) : ''}</div></span><span class="go">${ic(x.action ? 'plus' : 'chev', 24, 2)}</span><span class="pg"><i style="width:${n / 4 * 100}%"></i></span></button>`;
}
const SCREENS = {rsHome, rsReport, rsResults, rsCare, rsCalendar, rsBook, rsStep, rsVisits, rsProfile};
let lastPage = '';
function phone(body){
  const cur = TAB_OF[state.page] || 'rsHome', quiet = lastPage === state.page;
  lastPage = state.page;
  return `<div class="ph stage${quiet ? ' quiet' : ''}">
    <div class="phone"><div class="scr" id="phScr"><div class="view">${body}<p class="sos">Если нужна срочная помощь, звоните 103 или 112</p>
        <p class="mut3" style="margin:0 20px;font-size:11px;text-align:center">Демо-стенд: пациенты, исследования и время приёма учебные.</p></div></div>
      <div class="pnav">${miniBar()}<nav class="ptabs" aria-label="Разделы">${TABS.map(([id, icon, label]) => `<button class="tb" type="button" data-nav="${id}"${cur === id ? ' aria-current="page"' : ''}>${ic(icon, 26, cur === id ? 2.2 : 1.8)}${label}</button>`).join('')}</nav></div></div></div>`;
}
let fontRequested = false;
function ensureBrandFont(){
  if (fontRequested || !health.data?.brand_font || typeof FontFace === 'undefined') return;
  fontRequested = true;
  const face = new FontFace('Stolzl', 'url(/assets/fonts/Stolzl-Regular.otf)');
  face.load().then(f => document.fonts.add(f)).catch(() => {});
}
export const PHONE_PAGES = Object.fromEntries(PH_PAGES.map(id => [id, () => {
  if (state.role !== 'patient') return '<div class="note">Этот раздел открывается в окне пациента. Выберите «Пациент» в списке ролей.</div>';
  ensureBrandFont();
  return phone(SCREENS[id]());
}]));

/* ---------- Действия ---------- */
async function mutate(key, tail, body, done){
  const [e, s] = key.split(':');
  ui.phBusy = true; rerender();
  try {
    const r = await api('POST', `/api/patient/episodes/${enc(e)}/steps/${enc(s)}/${tail}`, {role:'patient', body});
    ui.phBusy = false;
    await load('episodes');
    done(r);
  } catch (err){
    ui.phBusy = false; toast(err.message);
    if (err.status === 409 && tail === 'book'){ ui.phSlot = null; loadSlots(key); }  // время заняли: новый список
    rerender();
  }
}
export function installPhoneActions(ACTIONS){
  ACTIONS.phRetry = d => { ph[d.key] = {status:'loading', data:null, message:''}; rerender(); load(d.key); };
  ACTIONS.phSlotsRetry = d => loadSlots(d.key);
  ACTIONS.phOpenStep = d => { ui.phKey = d.key; ui.phDay = null; ui.phSlot = null; ui.phDone = null; delete slots[d.key]; go('rsStep'); loadSlots(d.key); };
  ACTIONS.phReport = d => { ui.phStudy = d.id || null; go('rsReport'); };
  ACTIONS.phDay = d => { ui.phDay = d.day; ui.phSlot = null; rerender(); };
  ACTIONS.phSlot = d => { ui.phSlot = d.slot; rerender(); };
  ACTIONS.phBook = d => { if (!ui.phSlot || ui.phBusy) return;
    const step = document.getElementById('phStepTitle')?.textContent || 'Шаг плана';
    mutate(d.key, 'book', {slot_id:String(ui.phSlot)}, r => { const a = r.appointment || {};
      ui.phDone = {key:d.key, step, starts_at:a.starts_at || slots[d.key]?.data?.find(x => String(x.id) === String(ui.phSlot))?.starts_at, place:a.place, format:a.format};
      rerender(); }); };
  ACTIONS.phConfirm = d => mutate(d.key, 'confirm', {}, () => { toast('Запись подтверждена'); go('rsVisits'); });
  ACTIONS.phAsk = d => mutate(d.key, 'ask', {intent:d.intent}, () => { toast('Координатор увидит ваше обращение и свяжется с вами'); rerender(); });
  ACTIONS.phDoneClose = () => { ui.phDone = null; go('rsHome'); };
  ACTIONS.phUpload = () => uploadModal();
  ACTIONS.phExplain = async d => {
    if (explained[d.id]?.status === 'loading') return;
    explained[d.id] = {status:'loading'}; rerender();
    try { const r = await api('POST', `/api/patient/studies/${enc(d.id)}/assistant/explain`, {role:'patient', body:{}}); explained[d.id] = {status:'ok', text:r.explanation}; }
    catch (err){ explained[d.id] = {status:'error', message:'Не получилось подготовить объяснение. ' + err.message}; }
    rerender();
  };
  /* После загрузки снимка из телефона — остаться в «Результатах» и перечитать список */
  uploadHooks.after = () => { if (state.role === 'patient' && PH_PAGES.includes(state.page)){ go('rsResults'); load('studies'); return true; } return false; };
}
