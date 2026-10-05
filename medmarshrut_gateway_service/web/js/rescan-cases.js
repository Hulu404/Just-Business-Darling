/* Кейсы образца rescan (prototype/rescan-app-standalone.html, CASES и ORG): модель органа, точки находок,
   выноски с параметрами и подсвеченное заключение. Учебные, демо: пациенты вымышленные, кнопок одобрения нет —
   настоящее подтверждение идёт по исследованиям из сервиса снимков. Стили — rescan.css (.c-stage, .c-org …). */

const KI = {
  lung:'M12 3v7M12 10c-1.4 1-2.6-1.6-4.7-1.6C5 8.4 4 11.3 4 14.3 4 17.1 5 18 7 18c2.9 0 5-1.9 5-4.8M12 10c1.4 1 2.6-1.6 4.7-1.6 2.3 0 3.3 2.9 3.3 5.9 0 2.8-1 3.7-3 3.7-2.9 0-5-1.9-5-4.8',
  heart:'M12 20s-8-5-8-11a4.5 4.5 0 0 1 8-2.5A4.5 4.5 0 0 1 20 9c0 6-8 11-8 11z',
  act:'M9 22h6c5 0 7-2 7-7V9c0-5-2-7-7-7H9C4 2 2 4 2 9v6c0 5 2 7 7 7zM7 14.5l2.4-3.1c.3-.4 1-.5 1.4-.2l1.8 1.4c.4.3 1 .2 1.4-.2L16.5 9',
  brain:'M9 3a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 1 5 3 3 0 0 0 4 3h1V3H9zM15 3a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-1 5 3 3 0 0 1-4 3h-1V3h1z',
  kid:'M9 4c-3 0-5 3-5 7s2 9 5 9c2 0 2-2 1-4-.7-1.4-.7-2.6 0-4 1-2 1-8-1-8zM15 4c3 0 5 3 5 7s-2 9-5 9c-2 0-2-2-1-4 .7-1.4.7-2.6 0-4-1-2-1-8 1-8z'
};
const ki = (n, s = 18, w = 1.5) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${KI[n]}"/></svg>`;

/* Пропорции картинок органов (ширина / высота) — из ORG образца; сами картинки — web/img/rescan/<орган>.webp */
const ORG = {lungs:0.951, heart:0.623, adrenal:0.611, brain:1.179, knee:0.451};
const MODC = {'КТ':'#1866A0', 'МРТ':'#7B61FF', 'Рентген':'#0FA3A3'};

const CASES = [
  {id:'anna', tab:'Лёгкие', ti:'lung', organ:'lungs', who:'Анна К.', study:'КТ ОГК', mod:'КТ',
   text:'В <span class="f">S6 правого лёгкого</span> определяется <span class="f">солидный узел</span> с <span class="f">ровными контурами</span> размером <span class="f">7×6 мм</span>. <span class="f">Лимфоузлы не увеличены</span>. Рекомендована <span class="r">консультация пульмонолога</span>, <span class="r">контрольная КТ через 6–12 месяцев</span>.',
   pts:{n:[.22, .66], h:[.5, .3]},
   route:[['Консультация пульмонолога', 'в течение 2 недель'], ['Контрольная КТ ОГК', 'через 6–12 месяцев']], rule:'Флейшнер, 2017',
   float:{t:'Солидный узел', v:'7×6 мм', s:'Наблюдать'},
   w:[{p:'n', x:62, y:6, w:26, kind:'size', h:'Размер узла', hv:'7×6 мм'}, {p:'n', x:64, y:46, w:26, rows:[['Сегмент', 'S6 справа'], ['Контуры', 'ровные'], ['Структура', 'солидный']]}, {p:'h', x:64, y:73, w:26, rows:[['Лимфоузлы', 'норма'], ['Плевра', 'свободна']]}]},
  {id:'dmitry', tab:'Сердце', ti:'heart', organ:'heart', who:'Дмитрий Р.', study:'Рентген ОГК', mod:'Рентген',
   text:'Лёгочные поля <span class="f">без очаговых изменений</span>. <span class="f">Тень сердца расширена</span> влево, <span class="f">КТИ 0,56</span>. Рекомендована <span class="r">консультация кардиолога</span>, <span class="r">ЭхоКГ</span>.',
   pts:{n:[.66, .5], h:[.5, .86]},
   route:[['Консультация кардиолога', 'в течение 2 недель'], ['ЭхоКГ', 'по решению кардиолога']], rule:'КР МЗ РФ: КТИ больше 0,5',
   float:{t:'Тень сердца', v:'КТИ 0,56', s:'Выше нормы'},
   w:[{p:'n', x:62, y:6, w:26, kind:'size', h:'КТИ', hv:'0,56'}, {p:'n', x:64, y:46, w:26, rows:[['Контур', 'расширен влево'], ['Норма КТИ', 'до 0,50']]}, {p:'h', x:64, y:73, w:26, rows:[['Верхушка', 'смещена влево'], ['Лёгочные поля', 'норма']]}]},
  {id:'oleg', tab:'Колено', ti:'act', organ:'knee', who:'Олег Ш.', study:'МРТ коленного сустава', mod:'МРТ',
   text:'В <span class="f">заднем роге медиального мениска</span> <span class="f">горизонтальный разрыв</span>, <span class="f">выпот в суставе умеренный</span>. Связки <span class="f">без повреждений</span>. Рекомендована <span class="r">консультация травматолога-ортопеда</span>.',
   pts:{n:[.34, .5], h:[.62, .6]},
   route:[['Травматолог-ортопед', 'в течение 2 недель'], ['Решение об артроскопии', 'по решению врача']], rule:'Stoller, степень III',
   float:{t:'Мениск', v:'разрыв III ст.', s:'К специалисту'},
   w:[{p:'n', x:62, y:6, w:26, kind:'size', h:'Степень по Stoller', hv:'III'}, {p:'n', x:64, y:46, w:26, rows:[['Мениск', 'медиальный'], ['Отдел', 'задний рог'], ['Тип', 'горизонтальный']]}, {p:'h', x:64, y:73, w:26, rows:[['Связки', 'целы'], ['Выпот', 'умеренный']]}]},
  {id:'vera', tab:'Мозг', ti:'brain', organ:'brain', who:'Вера С.', study:'КТ головы', mod:'КТ',
   text:'В <span class="f">левой средней черепной ямке</span> <span class="f">арахноидальная киста 14 мм</span>, <span class="f">без масс-эффекта</span>. Рекомендована <span class="r">консультация невролога</span>.',
   pts:{n:[.36, .62], h:[.6, .3]},
   route:[['Консультация невролога', 'в течение месяца'], ['МРТ головного мозга', 'по решению невролога']], rule:'Протокол клиники: кисты больше 10 мм',
   float:{t:'Киста', v:'14 мм', s:'Наблюдать'},
   w:[{p:'n', x:62, y:6, w:26, kind:'size', h:'Размер кисты', hv:'14 мм'}, {p:'n', x:64, y:46, w:26, rows:[['Локализация', 'средняя ямка'], ['Масс-эффект', 'нет']]}, {p:'h', x:64, y:73, w:26, rows:[['Желудочки', 'норма'], ['Срединные структуры', 'не смещены']]}]},
  {id:'pavel', tab:'Надпочечник', ti:'kid', organ:'adrenal', who:'Павел Н.', study:'КТ ОБП', mod:'КТ',
   text:'Случайная находка: в <span class="f">левом надпочечнике</span> <span class="f">образование 18 мм</span> <span class="f">однородной структуры</span>. Рекомендована <span class="r">консультация эндокринолога</span>.',
   pts:{n:[.55, .16], h:[.42, .62]},
   route:[['Консультация эндокринолога', 'в течение месяца'], ['Гормональные анализы', 'по решению врача']], rule:'ACR: находки надпочечника 1–4 см',
   float:{t:'Образование', v:'18 мм', s:'Дообследовать'},
   w:[{p:'n', x:62, y:6, w:26, kind:'size', h:'Размер образования', hv:'18 мм'}, {p:'n', x:64, y:46, w:26, rows:[['Сторона', 'левая'], ['Структура', 'однородная']]}, {p:'h', x:64, y:73, w:26, rows:[['Почка', 'без изменений']]}]}
];

/* Кривая «положение находки относительно порогов» из виджета размера, как wave() образца */
function wave(){
  const d = [2, 2, 3, 6, 22, 40, 22, 6, 3, 2, 2], W = 160, H = 62, pad = 6, max = 44;
  const p = d.map((v, i) => [i * W / (d.length - 1), pad + (1 - v / max) * (H - 2 * pad)]);
  let path = `M${p[0][0]},${p[0][1]}`;
  for (let i = 0; i < p.length - 1; i++){
    const a = p[i - 1] || p[i], b = p[i], c = p[i + 1], e = p[i + 2] || c;
    path += ` C${(b[0] + (c[0] - a[0]) / 6).toFixed(1)},${(b[1] + (c[1] - a[1]) / 6).toFixed(1)} ${(c[0] - (e[0] - b[0]) / 6).toFixed(1)},${(c[1] - (e[1] - b[1]) / 6).toFixed(1)} ${c[0].toFixed(1)},${c[1].toFixed(1)}`;
  }
  return `<svg class="c-chart" viewBox="0 0 ${W} ${H}" width="100%" height="${H}" preserveAspectRatio="none" role="img" aria-label="Положение находки относительно порогов"><path d="${path}" fill="none" stroke="#1866A0" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linecap="round"/></svg>`;
}

function stage(c){
  const AR = 1.45, ow = Math.min(50, 84 * ORG[c.organ] / AR), oh = ow * AR / ORG[c.organ], ox = 4, oy = (100 - oh) / 2 + 2;
  const at = pt => [ox + ow * pt[0], oy + oh * pt[1]];
  const endY = w => w.y + (w.kind === 'size' ? 14 : 8);
  const lines = `<svg class="ln" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">${c.w.map(w => { const a = at(c.pts[w.p]), ex = w.x - 1.2, ey = endY(w);
    return `<path d="M${a[0]},${a[1]} C${a[0] + 16},${a[1]} ${ex - 14},${ey} ${ex},${ey}" fill="none" stroke="#90D5EC" stroke-width="2" vector-effect="non-scaling-stroke"/>`; }).join('')}</svg>`;
  const ends = c.w.map(w => `<span class="c-pt" style="left:${w.x - 1.2}%;top:${endY(w)}%"></span>`).join('');
  const pts = Object.values(c.pts).map(pt => { const a = at(pt); return `<span class="c-pt" style="left:${a[0]}%;top:${a[1]}%;width:10px;height:10px"></span>`; }).join('');
  const widgets = c.w.map(w => w.kind === 'size'
    ? `<div class="c-w" style="left:${w.x}%;top:${w.y}%;width:${w.w}%"><div class="r"><span>${w.h}</span><b>${w.hv}</b></div><div class="inn">${wave()}</div></div>`
    : `<div class="c-w" style="left:${w.x}%;top:${w.y}%;min-width:${w.w}%">${w.rows.map(r => `<div class="r"><span>${r[0]}</span><b>${r[1]}</b></div>`).join('')}</div>`).join('');
  const float = `<div class="c-float" style="left:6%;top:${oy + oh - 14}%;width:30%"><span class="t">${ki(c.ti, 16, 1.8)}${c.float.t}</span><span class="r" style="display:flex;justify-content:space-between"><span>${c.float.v}</span><span style="color:var(--c-fg2)">${c.float.s}</span></span></div>`;
  return `<div class="c-tw"><div class="c-stage"><div class="c-org" style="left:${ox}%;top:${oy}%;width:${ow}%;height:${oh}%"><img src="/assets/img/rescan/${c.organ}.webp" alt="3D-модель: ${c.tab.toLowerCase()}"></div>${lines}${pts}${ends}${widgets}${float}</div></div>`;
}

/* Кейсы — вкладки «Исследований» рядом с настоящими: id вкладки «case:<id>», отдельной загрузки нет */
const PREFIX = 'case:';
export const isCase = id => String(id || '').startsWith(PREFIX);
export const caseIds = () => CASES.map(x => PREFIX + x.id);
export function caseTabs(selected){
  return CASES.map(x => `<button class="c-tab" type="button" data-action="rsStudyOpen" data-id="${PREFIX + x.id}" aria-pressed="${PREFIX + x.id === selected}" title="${x.study} · учебный кейс, демо">${ki(x.ti)}${x.who}<small style="color:var(--c-fg2);font-weight:400">демо</small></button>`).join('');
}

/* Открытый кейс: модель с выносками, заключение и предложенный маршрут. Одобрять нечего — пациенты вымышленные */
export function caseDetail(id){
  const c = CASES.find(x => PREFIX + x.id === id) || CASES[0];
  return `<div class="c-grid" id="rsCases"><div class="c-card"><div class="c-hdr"><span><b>${c.who} · демо</b><small>${c.study} · учебный кейс</small></span><span style="margin-left:auto"><span class="c-mod" style="--m:${MODC[c.mod]}">${c.mod}</span></span></div>
      ${stage(c)}<div class="c-hl"><span class="c-hl-h">Заключение «Третье Мнение» · подсвечено, что извлёк rescan</span>${c.text}</div></div>
    <div class="c-col"><div class="c-card c-dec"><div class="c-ch"><span><h2>Маршрут</h2><span class="sub">предложен ИИ · ${c.rule}</span></span><span class="c-s grey">Демо</span></div>
      ${c.route.map((r, i) => `<div class="c-next"><span>${i ? 'Дальше по плану' : 'Первый шаг'}</span><b>${r[0]}</b><small>${r[1]}</small></div>`).join('')}
      <div class="c-demo">Учебный кейс из образца: так rescan показывает находки на модели органа. Пациент вымышленный, одобрять нечего. Настоящий маршрут строится только по утверждённому правилу клиники после подтверждения врачом.</div></div></div></div>`;
}
