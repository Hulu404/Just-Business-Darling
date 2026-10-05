/* Кабинет rescan, раздел «Сегодня» (задание 12, цикл 8): три плитки, «Новые исследования» и «Требуют внимания»
   на данных стенда. Источники: /api/doctor/studies (новые), /api/staff/episodes и /api/doctor/visits (поводы),
   /api/staff/studies/manual (заключение не дошло до сервиса маршрута). Числа и списки считаются по данным. */
import { attention, reached } from './rescan-patients.js';
import { staffReason } from './path-ui.js';
import { k, empty, head, stateOf } from './rescan-ui.js';
import { go, safe } from './ui.js';
import { ui } from './state.js';

export function todayNeeds(){ return ['studies', 'episodes', 'visits', 'manual']; }

const initials = name => String(name || '').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('') || '?';
const stepOf = v => (v.episode.steps || []).find(s => s.id === v.step_id) || {};
const isToday = value => { const d = new Date(value), n = new Date(); return !Number.isNaN(+d) && d.getFullYear() === n.getFullYear() && d.getMonth() === n.getMonth() && d.getDate() === n.getDate(); };

/* ---------- Плитки: только числа по данным, без «примерно N мин» и «остальное rescan ведёт сам» ---------- */
const tile = (nav, label, value, sub) => `<button class="c-tile" type="button" data-nav="${nav}"><span class="c-tl">${safe(label)}</span><span class="c-tv">${value}</span><span class="c-ts">${safe(sub)}</span></button>`;
function tiles(fresh, att, inPath, approved){
  return `<div class="c-tiles">
    ${tile('rsStudies', 'Новые исследования', fresh, fresh ? 'ждут вашего разбора' : 'всё разобрано')}
    ${tile('rsPatients', 'Требуют внимания', att, att ? 'где нужно ваше решение' : 'никто не потерялся')}
    ${tile('rsPatients', 'Пациенты в пути', inPath, approved + ' одобрено сегодня')}</div>`;
}

/* ---------- «Новые исследования»: пациент, вид исследования, описание признака и место из findings ---------- */
function studyRow(s){
  const f = (s.findings || [])[0];
  const meta = f ? [f.description, f.place].filter(Boolean).join(' · ') : '';
  return `<button class="c-in" type="button" data-action="rsStudyOpen" data-id="${safe(s.id)}">
    <span class="th">${k('scan', 30)}</span>
    <span class="tx"><span class="t1">${safe(s.patient)}</span><span class="t2">${safe(s.title)}</span>${meta ? `<span class="t3">${safe(meta)}</span>` : ''}</span>
    <span class="tmx"><i>${k('r', 16, 2)}</i></span></button>`;
}
function freshCard(list){
  const body = list.length ? list.map(studyRow).join('')
    : empty('Новых исследований нет', 'Когда пациент или клиника загрузит исследование, оно появится здесь.');
  return `<div class="c-card"><div class="c-ch"><span><h2>Новые исследования</h2><span class="sub">ждут проверки врачом</span></span>${list.length ? '<button class="c-btn" type="button" data-nav="rsStudies">Начать разбор</button>' : ''}</div>${body}</div>`;
}

/* ---------- «Требуют внимания»: только настоящие поводы, у каждого — кнопка к нужному экрану ---------- */
function attentionItems(episodes, visits, notRouted){
  const items = [];
  episodes.filter(e => e.status === 'manual_review' || e.status === 'paused')
    .forEach(e => items.push({name:e.patient, why:staffReason(e), kind:'patient', ref:e.patient_ref}));
  visits.filter(v => stepOf(v).status === 'attended')
    .forEach(v => items.push({name:v.episode.patient, why:'Пришёл на приём, ждёт вашего итога', kind:'visit'}));
  notRouted.forEach(s => items.push({name:s.patient, why:s.warning, kind:'study', id:s.id}));
  return items;
}
function attentionRow(it){
  const btn = it.kind === 'patient' ? `<button class="c-btn gh sm" type="button" data-action="rsGoPatient" data-ref="${safe(it.ref)}">Карточка</button>`
    : it.kind === 'visit' ? `<button class="c-btn gh sm" type="button" data-nav="rsVisits">К приёму</button>`
    : `<button class="c-btn gh sm" type="button" data-action="rsStudyOpen" data-id="${safe(it.id)}">Открыть</button>`;
  return `<div class="c-att"><span class="c-av" style="display:grid;place-items:center;font-weight:600;color:var(--c-blue)">${safe(initials(it.name))}</span>
    <span class="tx"><b>${safe(it.name)}</b><small>${safe(it.why)}</small></span>${btn}</div>`;
}
function attentionCard(items){
  const body = items.length ? items.map(attentionRow).join('')
    : empty('Никто не потерялся', 'Все пациенты записались или в пределах срока.');
  return `<div class="c-col"><div class="c-card"><div class="c-ch"><span><h2>Требуют внимания</h2><span class="sub">только то, где нужны вы</span></span></div>${body}</div></div>`;
}

export function rsToday(){
  return head('Сегодня', 'Новые исследования и пациенты, которым нужно ваше решение') +
    stateOf('studies', studies => stateOf('episodes', episodes => stateOf('visits', visits => stateOf('manual', manual => {
      const fresh = studies.filter(s => s.status === 'awaiting_physician');
      const approved = studies.filter(s => s.confirmation && isToday(s.confirmation.confirmed_at)).length;
      const inPath = new Set(episodes.filter(e => e.status === 'active' && !attention(e) && !reached(e)).map(e => e.patient_ref));
      const att = attentionItems(episodes, visits, manual.not_routed || []);
      return tiles(fresh.length, att.length, inPath.size, approved) +
        `<div class="c-g2">${freshCard(fresh)}${attentionCard(att)}</div>`;
    }))));
}

export function installTodayActions(ACTIONS){
  ACTIONS.rsGoPatient = d => { ui.rsPatient = d.ref; ui.rsPlan = null; go('rsPatients'); };
}
