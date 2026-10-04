import { notify, title } from './domain.js';
import { icon } from './icons.js';
import { doctor, study } from './pages/doctor.js';
import { imaging, messages, pharmacy, result } from './pages/patient.js';
import { services } from './pages/services.js';
import { requests, rules, who } from './pages/staff.js';

/* ---------- Услуги, слоты, партнёры ---------- */
export const SERVICES = {
  gp:{title:'Консультация терапевта'},
  attending:{title:'Приём лечащего врача'},
  therapist:{title:'Приём терапевта'},
  therapist2:{title:'Повторный приём терапевта'},
  pulmo:{title:'Консультация пульмонолога'},
  labs:{title:'Анализы крови (общий и С-реактивный белок)'},
  xray2:{title:'Контрольная рентгенография органов грудной клетки'},
  ct:{title:'КТ органов грудной клетки'},
  ct2:{title:'Контрольная КТ органов грудной клетки'},
  usbreast:{title:'УЗИ молочных желёз'},
  mammolog:{title:'Приём маммолога'},
  biopsy:{title:'Биопсия под контролем УЗИ'},
  ortho:{title:'Приём травматолога-ортопеда'},
  ortho2:{title:'Повторный приём травматолога-ортопеда'},
  rehab:{title:'Курс лечебной физкультуры'}
};

export const PARTNERS = {
  'p-sev':{name:'Клиника «Северная»', services:'Терапевт, пульмонолог, УЗИ', exchange:'Через API', wait:'1 день', sent:38, back:'74%'},
  'p-les':{name:'Диагностический центр на Лесной', services:'КТ, МРТ, ПЭТ-КТ', exchange:'Через API', wait:'2 дня', sent:41, back:'81%'},
  'p-mam':{name:'Маммологический центр «Опора»', services:'Биопсия, маммолог-онколог', exchange:'Выгрузка раз в сутки', wait:'4 дня', sent:17, back:'65%'},
  'p-dvi':{name:'Клиника реабилитации «Движение»', services:'ЛФК, физиотерапия', exchange:'Выгрузка раз в сутки', wait:'3 дня', sent:22, back:'88%'}
};

export const SLOTS = {
  gp:[
    {id:'a', who:'Терапевт · Анна Соколова', place:'Центральный филиал', date:'Сегодня', time:'17:30', price:'3 200 ₽', format:'Очно'},
    {id:'b', who:'Терапевт · Михаил Орлов', place:'Северный филиал', date:'Завтра', time:'11:00', price:'2 900 ₽', format:'Очно'},
    {id:'c', who:'Терапевт · Анна Соколова', place:'Онлайн', date:'Завтра', time:'13:15', price:'2 400 ₽', format:'Онлайн'}
  ],
  therapist:[
    {id:'t1', who:'Терапевт · Анна Соколова', place:'Центральный филиал', date:'Сегодня', time:'17:30', price:'3 200 ₽', format:'Очно'},
    {id:'t2', who:'Терапевт · Михаил Орлов', place:'Северный филиал', date:'Сегодня', time:'18:20', price:'2 900 ₽', format:'Очно'},
    {id:'t3', who:'Терапевт · Ольга Белова', place:'Клиника «Северная»', date:'Сегодня', time:'18:30', price:'3 000 ₽', format:'Очно', partner:'p-sev'}
  ],
  therapist2:[
    {id:'r1', who:'Терапевт · Анна Соколова', place:'Центральный филиал', date:'Через 14 дней', time:'10:40', price:'2 600 ₽', format:'Очно'},
    {id:'r2', who:'Терапевт · Анна Соколова', place:'Онлайн', date:'Через 14 дней', time:'19:00', price:'2 000 ₽', format:'Онлайн'}
  ],
  attending:[
    {id:'at1', who:'Терапевт · Анна Соколова', place:'Центральный филиал', date:'Завтра', time:'16:20', price:'2 600 ₽', format:'Очно'},
    {id:'at2', who:'Терапевт · Анна Соколова', place:'Онлайн', date:'Послезавтра', time:'09:00', price:'2 000 ₽', format:'Онлайн'}
  ],
  pulmo:[
    {id:'u1', who:'Пульмонолог · Виктор Лебедев', place:'Центральный филиал', date:'Завтра', time:'15:20', price:'3 600 ₽', format:'Очно'},
    {id:'u2', who:'Пульмонолог · Ирина Гусева', place:'Клиника «Северная»', date:'Послезавтра', time:'10:00', price:'3 400 ₽', format:'Очно', partner:'p-sev'}
  ],
  labs:[
    {id:'l1', who:'Процедурный кабинет', place:'Центральный филиал', date:'Завтра', time:'08:30', price:'1 150 ₽', format:'Очно'},
    {id:'l2', who:'Процедурный кабинет', place:'Северный филиал', date:'Завтра', time:'09:10', price:'1 150 ₽', format:'Очно'}
  ],
  xray2:[
    {id:'x1', who:'Кабинет рентгена', place:'Центральный филиал', date:'Через 14 дней', time:'10:00', price:'1 900 ₽', format:'Очно'},
    {id:'x2', who:'Кабинет рентгена', place:'Центральный филиал', date:'Через 15 дней', time:'18:20', price:'1 900 ₽', format:'Очно'}
  ],
  ct:[
    {id:'c1', who:'Кабинет КТ', place:'Диагностический центр на Лесной', date:'Послезавтра', time:'12:20', price:'5 400 ₽', format:'Очно', partner:'p-les'},
    {id:'c2', who:'Кабинет КТ', place:'Диагностический центр на Лесной', date:'Через 3 дня', time:'09:40', price:'5 400 ₽', format:'Очно', partner:'p-les'}
  ],
  ct2:[
    {id:'k1', who:'Кабинет КТ', place:'Диагностический центр на Лесной', date:'Завтра', time:'14:00', price:'5 400 ₽', format:'Очно', partner:'p-les'},
    {id:'k2', who:'Кабинет КТ', place:'Диагностический центр на Лесной', date:'Через 2 дня', time:'08:40', price:'5 400 ₽', format:'Очно', partner:'p-les'}
  ],
  usbreast:[
    {id:'b1', who:'Кабинет УЗИ', place:'Центральный филиал', date:'Завтра', time:'12:00', price:'2 700 ₽', format:'Очно'},
    {id:'b2', who:'Кабинет УЗИ', place:'Северный филиал', date:'Послезавтра', time:'09:30', price:'2 700 ₽', format:'Очно'}
  ],
  mammolog:[
    {id:'m1', who:'Маммолог · Татьяна Крылова', place:'Центральный филиал', date:'Завтра', time:'12:40', price:'3 900 ₽', format:'Очно'},
    {id:'m2', who:'Маммолог · Алла Зимина', place:'Маммологический центр «Опора»', date:'Через 3 дня', time:'16:00', price:'4 200 ₽', format:'Очно', partner:'p-mam'}
  ],
  biopsy:[
    {id:'bi1', who:'Процедурный кабинет', place:'Маммологический центр «Опора»', date:'Через 4 дня', time:'11:00', price:'7 800 ₽', format:'Очно', partner:'p-mam'}
  ],
  ortho:[
    {id:'o1', who:'Травматолог-ортопед · Павел Громов', place:'Центральный филиал', date:'Сегодня', time:'15:00', price:'3 400 ₽', format:'Очно'},
    {id:'o2', who:'Травматолог-ортопед · Павел Громов', place:'Центральный филиал', date:'Завтра', time:'10:20', price:'3 400 ₽', format:'Очно'}
  ],
  ortho2:[
    {id:'o3', who:'Травматолог-ортопед · Павел Громов', place:'Центральный филиал', date:'Через 14 дней', time:'15:00', price:'2 800 ₽', format:'Очно'}
  ],
  rehab:[
    {id:'h1', who:'Зал ЛФК', place:'Клиника реабилитации «Движение»', date:'Через 2 дня', time:'18:00', price:'1 600 ₽ за занятие', format:'Очно', partner:'p-dvi'}
  ]
};
export const slotsFor = service => SLOTS[service] || SLOTS.gp;
export const partnerOnly = service => slotsFor(service).every(x => x.partner);

/* ---------- Правила маршрута после исследований (аналог rules.json в сервисе пути) ---------- */
export const RULES = [
  {id:'NORM', modality:null, study:'Любое исследование', finding:'Изменений не выявлено', test:/(изменени[йя]|патологии)\s+(в\s+[а-яё]+\s+)?не\s+(выявлено|обнаружено)|без\s+патологических/i, steps:[], due:'', note:'Маршрут не нужен. Напоминание о плановом обследовании через 12 месяцев.', version:2},
  {id:'XR-INF', modality:'xray', study:'Рентгенография органов грудной клетки', finding:'Инфильтративные изменения в лёгком', test:/инфильтр/i, steps:['therapist'], due:'24 часа', version:3},
  {id:'CT-NOD', modality:'ct', study:'КТ органов грудной клетки', finding:'Очаг в лёгком', test:/очаг/i, steps:['pulmo'], due:'7 дней', version:2},
  {id:'MG-ADD', modality:'mg', study:'Маммография', finding:'Участок, который требует дообследования', test:/уплотнени|образовани|дообследовани/i, steps:['usbreast','mammolog'], due:'7 дней', version:1},
  {id:'MR-MEN', modality:'mri', study:'МРТ коленного сустава', finding:'Повреждение мениска', test:/мениск/i, steps:['ortho'], due:'14 дней', version:1}
];
export const MOD_LABEL = {xray:'Рентгенография', ct:'КТ', mg:'Маммография', mri:'МРТ'};

/* Что врач может назначить после приёма: [услуга, срок, отмечено по умолчанию] */
export const NEXT = {
  'XR-INF':[['labs','завтра',true],['xray2','через 14 дней',true],['therapist2','через 14 дней',true],['ct','в течение 7 дней',false]],
  'CT-NOD':[['ct2','через 3 месяца',true],['pulmo','после контрольной КТ',false]],
  'MG-ADD':[['usbreast','в течение 7 дней',true],['mammolog','в течение 7 дней',true],['biopsy','по решению маммолога',false]],
  'MR-MEN':[['ortho2','через 14 дней',true],['rehab','10 занятий',true]],
  'own':[['labs','завтра',true],['therapist2','через 14 дней',false]]
};

/* ---------- Демо-содержание исследований ---------- */
export const DEMO = {
  xray:{
    modality:'xray', title:'Рентгенография органов грудной клетки', ready:'Результат рентгенографии готов', scheme:'xray', files:'1 снимок, прямая проекция',
    findings:[{label:'Инфильтративные изменения', place:'правое лёгкое, нижняя доля', conf:'0,91'}],
    draft:'Рентгенография органов грудной клетки в прямой проекции. В нижней доле правого лёгкого определяется участок инфильтрации лёгочной ткани с нечёткими контурами. Корни лёгких структурны, не расширены. Плевральные синусы свободны. Тень сердца не расширена.\n\nЗаключение: рентгенологические признаки инфильтративных изменений в нижней доле правого лёгкого. Рекомендована консультация терапевта.',
    seen:'В нижней части правого лёгкого есть участок, который на снимке выглядит плотнее, чем ткань вокруг.',
    means:'Так бывает при воспалении. По одному снимку диагноз не ставят: терапевт послушает лёгкие и, если нужно, назначит анализы.'
  },
  ct:{
    modality:'ct', title:'КТ органов грудной клетки', ready:'Результат КТ готов', scheme:'ct', files:'Серия 3, 310 срезов по 1 мм',
    findings:[{label:'Очаг 7 мм', place:'правое лёгкое, сегмент S6, срез 142', conf:'0,88'}],
    draft:'КТ органов грудной клетки без контрастного усиления. В S6 правого лёгкого солидный очаг 7 мм с чёткими ровными контурами. Внутригрудные лимфатические узлы не увеличены. Жидкости в плевральных полостях нет.\n\nЗаключение: одиночный очаг в S6 правого лёгкого, 7 мм. Рекомендована консультация пульмонолога.',
    seen:'В правом лёгком есть небольшой округлый участок — очаг размером 7 мм.',
    means:'Небольшие очаги в лёгких встречаются часто. Что это за очаг и нужно ли за ним наблюдать, решит пульмонолог.'
  },
  mg:{
    modality:'mg', title:'Маммография', ready:'Результат маммографии готов', scheme:'mg', files:'4 проекции: R-CC, R-MLO, L-CC, L-MLO',
    findings:[{label:'Участок уплотнения до 12 мм', place:'левая молочная железа, верхне-наружный квадрант, проекция L-MLO', conf:'0,84'}],
    draft:'Маммография обеих молочных желёз в двух проекциях. В верхне-наружном квадранте левой молочной железы участок локального уплотнения ткани до 12 мм. Кожа, соски и ареолы не изменены.\n\nЗаключение: участок уплотнения в верхне-наружном квадранте левой молочной железы. Рекомендовано дообследование: УЗИ молочных желёз, консультация маммолога.',
    seen:'В левой молочной железе есть участок, где ткань выглядит плотнее.',
    means:'Маммография не всегда показывает такой участок достаточно подробно. Обычно его дополнительно смотрят на УЗИ, а вывод делает маммолог.'
  },
  mri:{
    modality:'mri', title:'МРТ коленного сустава', ready:'Результат МРТ готов', scheme:'mri', files:'5 серий, 142 изображения',
    findings:[{label:'Линейный участок повышенного сигнала', place:'медиальный мениск, задний рог', conf:'0,86'}],
    draft:'МРТ правого коленного сустава. В заднем роге медиального мениска линейный участок повышенного сигнала, который достигает суставной поверхности. Крестообразные связки прослеживаются на всём протяжении. Выпота в полости сустава нет.\n\nЗаключение: МР-признаки повреждения заднего рога медиального мениска. Рекомендована консультация травматолога-ортопеда.',
    seen:'В правом колене изменён внутренний мениск — хрящевая прокладка между костями.',
    means:'По снимку видно место повреждения. Чем его лечить, решит травматолог-ортопед после осмотра колена.'
  },
  norm:{
    modality:'xray', title:'Рентгенография органов грудной клетки', ready:'Результат рентгенографии готов', scheme:'xray', files:'1 снимок, прямая проекция',
    findings:[],
    draft:'Рентгенография органов грудной клетки в прямой проекции. Очаговых и инфильтративных изменений в лёгких не выявлено. Корни лёгких структурны. Плевральные синусы свободны. Тень сердца не расширена.\n\nЗаключение: рентгенологических признаков патологии органов грудной клетки нет.',
    seen:'Изменений, которые требуют действий, на снимке не нашли.',
    means:'Сейчас ничего делать не нужно. Мы напомним о следующем плановом обследовании через 12 месяцев.'
  }
};

/* Схемы вместо снимков: условные рисунки, не медицинские изображения */
export const SCHEME = {
  xray:(m, tag) => `<svg viewBox="0 0 360 300" role="img" aria-label="Схема рентгенограммы грудной клетки"><rect width="360" height="300" rx="12" fill="#0b1a1f"/><path d="M58 300C58 180 84 86 150 62c10-4 20-14 30-14s20 10 30 14c66 24 92 118 92 238z" fill="#1a3038"/><path d="M166 86c-44 6-70 62-70 142 0 30 44 34 62 16 8-8 8-158 8-158z" fill="#0d2026"/><path d="M194 86c44 6 70 62 70 142 0 30-30 34-46 22-22-16-24-164-24-164z" fill="#0d2026"/><path d="M176 150c22-6 52 14 54 52 2 30-30 46-54 42z" fill="#27444d"/><rect x="174" y="52" width="12" height="236" rx="6" fill="#2c4d57"/><g fill="none" stroke="#3a6470" stroke-width="2" stroke-linecap="round" opacity=".75"><path d="M100 128q34-18 70-8M98 156q36-18 72-8M98 184q36-16 72-8M100 212q34-14 70-8"/><path d="M260 128q-34-18-70-8M262 156q-36-18-72-8M262 184q-36-16-72-8M260 212q-34-14-70-8"/><path d="M90 92q44-14 84 0M270 92q-44-14-84 0"/></g>${m ? `<ellipse cx="124" cy="214" rx="24" ry="19" fill="#b7cdd1" opacity=".32"/><rect x="92" y="186" width="64" height="56" rx="9" fill="none" stroke="#19d3b6" stroke-width="2.5"/>${tag ? `<text x="92" y="178" fill="#19d3b6" font-size="12" font-weight="700">ИИ · ${tag}</text>` : ''}` : ''}<text x="20" y="34" fill="#7fa3ab" font-size="15" font-weight="700">R</text></svg>`,
  ct:(m, tag) => `<svg viewBox="0 0 360 300" role="img" aria-label="Схема среза КТ грудной клетки"><rect width="360" height="300" rx="12" fill="#0b1a1f"/><ellipse cx="180" cy="152" rx="150" ry="112" fill="#213a42"/><g id="ctLungs"><path d="M168 70c-60-8-104 34-104 90 0 46 40 70 84 62 18-4 22-40 20-152z" fill="#060f12"/><path d="M192 70c60-8 104 34 104 90 0 46-40 70-84 62-18-4-22-40-20-152z" fill="#060f12"/><g fill="#4f747e"><circle cx="118" cy="128" r="3"/><circle cx="134" cy="160" r="2.5"/><circle cx="236" cy="134" r="3"/><circle cx="226" cy="170" r="2.5"/><circle cx="104" cy="170" r="2"/><circle cx="256" cy="176" r="2"/></g></g><path d="M168 78c16-10 40-6 46 22 6 30-6 62-34 64-16 0-16-60-12-86z" fill="#35555f"/><circle cx="180" cy="228" r="19" fill="#a9c1c6"/><circle cx="180" cy="230" r="6" fill="#213a42"/>${m ? `<g id="ctMark"><circle cx="112" cy="196" r="6" fill="#dbe9eb"/><circle cx="112" cy="196" r="17" fill="none" stroke="#19d3b6" stroke-width="2.5"/>${tag ? `<text x="134" y="200" fill="#19d3b6" font-size="12" font-weight="700">ИИ · ${tag}</text>` : ''}</g>` : ''}<text x="20" y="34" fill="#7fa3ab" font-size="15" font-weight="700">R</text></svg>`,
  mg:(m, tag) => `<svg viewBox="0 0 360 300" role="img" aria-label="Схема маммограммы в косой проекции"><rect width="360" height="300" rx="12" fill="#0b1a1f"/><path d="M24 30c96 6 142 52 142 120s-46 114-142 120z" fill="#1d363e"/><path d="M336 30c-96 6-142 52-142 120s46 114 142 120z" fill="#1d363e"/><g fill="#3c5e68" opacity=".7"><ellipse cx="74" cy="140" rx="34" ry="52"/><ellipse cx="286" cy="150" rx="34" ry="52"/></g><g fill="#587c86" opacity=".6"><ellipse cx="62" cy="120" rx="16" ry="24"/><ellipse cx="296" cy="170" rx="18" ry="22"/></g>${m ? `<circle cx="276" cy="104" r="9" fill="#cfe0e3" opacity=".85"/><circle cx="276" cy="104" r="21" fill="none" stroke="#19d3b6" stroke-width="2.5"/>${tag ? `<text x="212" y="74" fill="#19d3b6" font-size="12" font-weight="700">ИИ · ${tag}</text>` : ''}` : ''}<text x="24" y="290" fill="#7fa3ab" font-size="13" font-weight="700">R-MLO</text><text x="290" y="290" fill="#7fa3ab" font-size="13" font-weight="700">L-MLO</text></svg>`,
  mri:(m, tag) => `<svg viewBox="0 0 360 300" role="img" aria-label="Схема МРТ коленного сустава"><rect width="360" height="300" rx="12" fill="#0b1a1f"/><path d="M120 0h112v104c0 44-28 62-58 62s-54-22-54-62z" fill="#42626c"/><path d="M112 196c20-10 112-10 132 0v104H112z" fill="#42626c"/><ellipse cx="86" cy="118" rx="15" ry="32" fill="#39565f"/><path d="M118 174l34 9-34 9z" fill="#111f24"/><path d="M242 174l-34 9 34 9z" fill="#111f24"/>${m ? `<path d="M240 180l-22 5" stroke="#dbe9eb" stroke-width="2" stroke-linecap="round"/><circle cx="228" cy="183" r="19" fill="none" stroke="#19d3b6" stroke-width="2.5"/>${tag ? `<text x="254" y="188" fill="#19d3b6" font-size="12" font-weight="700">ИИ · ${tag}</text>` : ''}` : ''}<text x="20" y="34" fill="#7fa3ab" font-size="13" font-weight="700">Сагиттальный срез</text></svg>`
};

/* ---------- Аптека ---------- */
export const PHARMACIES = [
  {id:'ph0', name:'Аптека на первом этаже клиники', addr:'Центральный филиал', dist:'в клинике'},
  {id:'ph1', name:'Аптека на Садовой', addr:'ул. Садовая, 14', dist:'350 м от клиники'},
  {id:'ph2', name:'Аптека у метро «Северная»', addr:'Северный проспект, 2', dist:'1,2 км от дома'}
];
export const RX_STOCK = {ph0:['В наличии','1 240 ₽'], ph1:['В наличии','1 180 ₽'], ph2:['Под заказ, завтра после 12:00','1 150 ₽']};
export const CATS = [['all','Все'],['cold','Простуда'],['vit','Витамины'],['devices','Приборы'],['care','Уход и перевязка']];
export const PRODUCTS = [
  {id:'g1', cat:'devices', icon:'device', name:'Термометр электронный', form:'1 шт.', price:390},
  {id:'g2', cat:'devices', icon:'device', name:'Пульсоксиметр на палец', form:'1 шт.', price:1490},
  {id:'g3', cat:'devices', icon:'device', name:'Тонометр автоматический', form:'1 шт.', price:2890},
  {id:'g4', cat:'cold', icon:'drop', name:'Солевой спрей для носа', form:'30 мл', price:320},
  {id:'g5', cat:'cold', icon:'pill', name:'Парацетамол', form:'таблетки 500 мг, 20 шт.', price:65, drug:true},
  {id:'g6', cat:'cold', icon:'pill', name:'Ибупрофен', form:'таблетки 200 мг, 20 шт.', price:110, drug:true},
  {id:'g7', cat:'vit', icon:'drop', name:'Витамин D3', form:'капли, 10 мл', price:410},
  {id:'g8', cat:'vit', icon:'pill', name:'Витамин C', form:'драже, 50 шт.', price:120},
  {id:'g9', cat:'care', icon:'bandage', name:'Эластичный бинт', form:'3 м', price:240},
  {id:'g10', cat:'care', icon:'bandage', name:'Наколенник эластичный', form:'1 шт.', price:890},
  {id:'g11', cat:'care', icon:'bandage', name:'Пластырь, набор', form:'20 шт.', price:150},
  {id:'g12', cat:'care', icon:'device', name:'Маски медицинские', form:'50 шт.', price:290}
];

/* ---------- Сообщения пациентам: сценарии ---------- */
export const TRIGGERS = [
  ['ready','Врач подтвердил заключение','сразу','Объяснение простыми словами и предложение записи'],
  ['remind4','Запись не выбрана','через 4 часа','Напоминание с ближайшим временем'],
  ['call24','Пациент не ответил','через 24 часа','Задача координатору: позвонить'],
  ['before','Скоро визит','за сутки','Напоминание и подготовка к приёму'],
  ['after','Врач внёс итог приёма','сразу','Обновлённый план и рецепт'],
  ['overdue','Просрочен контрольный шаг','на следующий день','Напоминание и задача координатору']
];

/* ---------- Сценарии нового обращения (первые четыре — из первой версии) ---------- */
export const scenarios = {
  symptoms:{title:'Что-то беспокоит', icon:'spark', desc:'Опишите симптомы и получите понятный следующий шаг.'},
  document:{title:'Есть анализ или выписка', icon:'doc', desc:'Разберём документ и подготовим вас к обращению.'},
  imaging:{title:'Есть снимок или заключение', icon:'scan', desc:'Загрузите КТ, МРТ, маммографию или рентген. Врач подтвердит заключение, и мы объясним его простыми словами.', direct:'upload'},
  noslots:{title:'Не получается записаться', icon:'clock', desc:'Покажем возможные действия, если нужный врач недоступен.'},
  after:{title:'После приёма', icon:'after', desc:'Соберём назначения и дальнейшие шаги в один план.'},
  meds:{title:'Нужны лекарства', icon:'pharmacy', desc:'Товары без рецепта с выдачей в клинике и бронь рецептурных препаратов в аптеках-партнёрах.', direct:'pharmacy'}
};

/* ---------- Стартовое состояние демо ---------- */
export function seed(){
  return {
    role:'patient', page:'home',
    // анкета нового обращения (как в первой версии)
    scenario:null, channel:'private', age:'adult', symptoms:'', duration:'', city:'Москва', redflag:false, doctor:'', wait:'', documentName:'', documentNotes:'', routeCreated:false,
    rules:{manual:true, alternate:true, followup:true},
    ruleApproved:{'NORM':true, 'XR-INF':true, 'CT-NOD':true, 'MG-ADD':false, 'MR-MEN':true},
    triggers:{ready:true, remind4:true, call24:true, before:true, after:true, overdue:true},
    notify:{app:true, sms:true, messenger:false, quiet:true},
    sel:{episode:'e1', study:'st3', request:'r1', book:null, pharmTab:'otc', cat:'all', partnersTab:'clinics', inboxTab:'need', slotTab:'all', sample:'xray'},
    sandbox:{text:DEMO.xray.draft, result:null},
    calc:{n:1200, base:22, target:38, check:3200},
    cart:{},
    studies:[
      {id:'st1', patient:'Демо-пациент', mine:true, kind:'xray', date:'Вчера, 17:55', source:'Кабинет рентгена, Центральный филиал', status:'confirmed', confirmedBy:'Д. Ершов, врач-рентгенолог', confirmedAt:'вчера в 18:40', conclusion:DEMO.xray.draft, episodeId:'e1'},
      {id:'st3', patient:'Игорь С.', kind:'ct', date:'Сегодня, 10:05', source:'Кабинет КТ у партнёра, выгрузка из РИС', status:'awaiting'},
      {id:'st4', patient:'Нина В.', kind:'norm', date:'Сегодня, 10:40', source:'Кабинет рентгена, Северный филиал', status:'awaiting'},
      {id:'st2', patient:'Мария К.', kind:'mg', date:'Вчера, 11:20', source:'Кабинет маммографии, Центральный филиал', status:'confirmed', confirmedBy:'Д. Ершов, врач-рентгенолог', confirmedAt:'вчера в 12:00', conclusion:DEMO.mg.draft, episodeId:'e2'},
      {id:'st7', patient:'Сергей Т.', kind:'xray', date:'Вчера, 15:10', source:'Кабинет рентгена, Центральный филиал', status:'confirmed', confirmedBy:'Д. Ершов, врач-рентгенолог', confirmedAt:'вчера в 15:50', conclusion:DEMO.xray.draft, episodeId:'e5'},
      {id:'st6', patient:'Елена П.', kind:'mri', date:'2 дня назад', source:'Кабинет МРТ, Центральный филиал', status:'confirmed', confirmedBy:'Д. Ершов, врач-рентгенолог', confirmedAt:'2 дня назад', conclusion:DEMO.mri.draft, episodeId:'e4'},
      {id:'st5', patient:'Олег Р.', kind:'ct', date:'3 месяца назад', source:'Диагностический центр на Лесной', status:'confirmed', confirmedBy:'Д. Ершов, врач-рентгенолог', confirmedAt:'3 месяца назад', conclusion:DEMO.ct.draft, episodeId:'e3'}
    ],
    episodes:[
      {id:'e1', patient:'Демо-пациент', mine:true, kind:'imaging', studyId:'st1', title:DEMO.xray.title, opened:'Вчера, 18:40', status:'active', reason:'', ruleId:'XR-INF',
        profile:['47 лет','Полис ДМС','Флюорография год назад: без изменений','Последний визит: 12 сентября, терапевт'],
        steps:[{id:'e1s1', cycle:1, service:'therapist', status:'open', due:'сегодня до 18:40', by:'Правило XR-INF, версия 3', slot:null}],
        log:[
          {t:'Вчера, 18:32', who:'ИИ-сервис', text:'Черновик заключения готов'},
          {t:'Вчера, 18:40', who:'Д. Ершов', text:'Заключение подтверждено врачом'},
          {t:'Вчера, 18:40', who:'Маршрутизатор', text:'Следующий шаг по правилу XR-INF: приём терапевта, срок 24 часа'},
          {t:'Вчера, 18:45', who:'Сообщения', text:'Пациенту ушли объяснение и предложение записи'},
          {t:'Сегодня, 09:00', who:'Сообщения', text:'Напоминание: запись не выбрана'}
        ]},
      {id:'e2', patient:'Мария К.', kind:'imaging', studyId:'st2', title:DEMO.mg.title, opened:'Вчера, 12:00', status:'manual_review', reason:'Правило MG-ADD ещё не утверждено клиникой: нужен план врача', ruleId:'MG-ADD', suggest:['usbreast','mammolog'],
        profile:['52 года','Платный приём','Маммография два года назад: без изменений'],
        steps:[],
        log:[
          {t:'Вчера, 12:00', who:'Д. Ершов', text:'Заключение подтверждено врачом'},
          {t:'Вчера, 12:00', who:'Маршрутизатор', text:'Правило MG-ADD в статусе «черновик»: обращение передано на ручной разбор'},
          {t:'Сегодня, 10:50', who:'Наталья, координатор', text:'Запрос врачу: подтвердить маршрут'}
        ]},
      {id:'e3', patient:'Олег Р.', kind:'imaging', studyId:'st5', title:DEMO.ct.title, opened:'3 месяца назад', status:'active', reason:'', ruleId:'CT-NOD',
        profile:['61 год','Полис ДМС','Курит 30 лет'],
        steps:[
          {id:'e3s1', cycle:1, service:'pulmo', status:'completed', due:'7 дней', by:'Правило CT-NOD, версия 2', slot:{date:'3 месяца назад', time:'12:00', who:'Пульмонолог · Виктор Лебедев', place:'Центральный филиал'}, outcome:'Наблюдение. Контрольная КТ через 3 месяца.'},
          {id:'e3s2', cycle:2, service:'ct2', status:'open', overdue:true, due:'6 дней назад', by:'Итог приёма: пульмонолог В. Лебедев', slot:null}
        ],
        log:[
          {t:'3 месяца назад', who:'В. Лебедев', text:'Итог приёма: наблюдение, контрольная КТ через 3 месяца'},
          {t:'8 дней назад', who:'Сообщения', text:'Напоминание о контрольной КТ: доставлено, ответа нет'},
          {t:'Вчера, 08:10', who:'Сообщения', text:'Повторное напоминание: доставлено, ответа нет'},
          {t:'Сегодня, 08:10', who:'Маршрутизатор', text:'Шаг просрочен на 6 дней: задача координатору'}
        ]},
      {id:'e4', patient:'Елена П.', kind:'imaging', studyId:'st6', title:DEMO.mri.title, opened:'2 дня назад', status:'active', reason:'', ruleId:'MR-MEN',
        profile:['34 года','Платный приём','Жалобы: боль в колене после пробежек'],
        steps:[{id:'e4s1', cycle:1, service:'ortho', status:'confirmed', due:'14 дней', by:'Правило MR-MEN, версия 1', slot:SLOTS.ortho[0]}],
        log:[
          {t:'2 дня назад', who:'Маршрутизатор', text:'Следующий шаг по правилу MR-MEN: приём травматолога-ортопеда'},
          {t:'Вчера, 16:20', who:'Пациент', text:'Запись из сообщения: сегодня, 15:00'}
        ]},
      {id:'e5', patient:'Сергей Т.', kind:'imaging', studyId:'st7', title:DEMO.xray.title, opened:'Вчера, 15:50', status:'active', reason:'', ruleId:'XR-INF',
        profile:['39 лет','Полис ОМС','Жалобы: кашель и температура четыре дня'],
        steps:[{id:'e5s1', cycle:1, service:'therapist', status:'attended', due:'24 часа', by:'Правило XR-INF, версия 3', slot:{date:'Сегодня', time:'09:30', who:'Терапевт · Анна Соколова', place:'Центральный филиал'}}],
        log:[
          {t:'Вчера, 16:05', who:'Наталья, координатор', text:'Запись по звонку: сегодня, 09:30'},
          {t:'Сегодня, 09:55', who:'Регистратура', text:'Визит состоялся'}
        ]}
    ],
    requests:[
      {id:'r1', episodeId:'e2', from:'staff', kind:'route', subject:'Подтвердить маршрут', status:'open', t:'Сегодня, 10:50',
        msgs:[{from:'staff', t:'Сегодня, 10:50', text:'Мария К., маммография: участок уплотнения в левой молочной железе. Правило MG-ADD ещё в черновике, поэтому маршрутизатор только предлагает вариант: УЗИ молочных желёз и приём маммолога в течение 7 дней. Подтвердите или измените план.'}]},
      {id:'r2', episodeId:'e3', from:'doctor', kind:'other', subject:'Просрочена контрольная КТ', status:'open', t:'Сегодня, 08:30',
        msgs:[{from:'doctor', t:'Сегодня, 08:30', text:'Олег Р. не пришёл на контрольную КТ, срок прошёл 6 дней назад. Позвоните ему, пожалуйста. Центр на Лесной держит время на завтра, 14:00.'}]},
      {id:'r3', episodeId:'e4', from:'staff', kind:'other', subject:'Перенос приёма', status:'closed', t:'Вчера, 15:40',
        msgs:[
          {from:'staff', t:'Вчера, 15:40', text:'Елена П. просит принять её сегодня до 16:00, после работает. Возьмёте?'},
          {from:'doctor', t:'Вчера, 15:52', text:'Да, 15:00 свободно. Пусть возьмёт с собой диск с МРТ.'}
        ]}
    ],
    messages:[
      {id:'m1', from:'clinic', t:'Вчера, 18:45', text:'Результат рентгенографии готов. Врач-рентгенолог Д. Ершов подтвердил заключение, а мы объяснили его простыми словами.', actions:[['Что на снимке','nav','imaging']], unread:false},
      {id:'m2', from:'clinic', t:'Вчера, 18:45', text:'Следующий шаг — приём терапевта в течение 24 часов. Ближайшее время: сегодня в 17:30, Центральный филиал.', actions:[['Выбрать время','book','e1:e1s1'],['Перезвоните мне','callback','e1']], unread:true},
      {id:'m3', from:'clinic', t:'Сегодня, 09:00', text:'Вы пока не выбрали время приёма. Могу записать вас по телефону или подобрать время в клинике-партнёре. Наталья, координатор.', actions:[['Выбрать время','book','e1:e1s1'],['Перезвоните мне','callback','e1'],['Не сейчас','later','e1:e1s1']], unread:true}
    ],
    outbox:[
      {t:'Сегодня, 09:00', patient:'Демо-пациент', event:'Напоминание: запись не выбрана', channel:'Приложение и SMS', status:'Доставлено', episodeId:'e1'},
      {t:'Сегодня, 08:10', patient:'Олег Р.', event:'Просрочен контрольный шаг', channel:'SMS', status:'Доставлено, ответа нет', episodeId:'e3'},
      {t:'Вчера, 18:45', patient:'Демо-пациент', event:'Заключение готово: объяснение и запись', channel:'Приложение', status:'Прочитано', episodeId:'e1'},
      {t:'Вчера, 16:20', patient:'Елена П.', event:'Подтверждение записи', channel:'Мессенджер', status:'Прочитано', episodeId:'e4'},
      {t:'Вчера, 16:05', patient:'Сергей Т.', event:'Подтверждение записи', channel:'SMS', status:'Доставлено', episodeId:'e5'},
      {t:'Вчера, 12:05', patient:'Мария К.', event:'Заключение готово: план уточняет врач', channel:'Приложение', status:'Прочитано', episodeId:'e2'}
    ],
    referrals:[
      {id:'rf1', patient:'Олег Р.', service:'ct2', partner:'p-les', status:'Ожидает записи', episodeId:'e3', stepId:'e3s2'},
      {id:'rf2', patient:'Анна Л.', service:'biopsy', partner:'p-mam', status:'Услуга оказана', episodeId:null, stepId:null},
      {id:'rf3', patient:'Пётр Д.', service:'rehab', partner:'p-dvi', status:'Результат получен', episodeId:null, stepId:null}
    ],
    prescriptions:[
      {id:'rx1', number:'77-0181', patient:'Демо-пациент', mine:true, doctor:'А. Соколова, терапевт', date:'12 сентября', valid:'до 11 ноября', items:[['Препарат А','таблетки, 30 шт.']], status:'issued', pharmacy:null, code:null}
    ],
    orders:[
      {id:'З-1039', type:'otc', patient:'Мария К.', items:'Тонометр автоматический', total:'2 890 ₽', place:'Аптека на первом этаже клиники', status:'Готов к выдаче'},
      {id:'Б-0217', type:'rx', patient:'Олег Р.', items:'Рецепт № 77-0164, 1 препарат', total:'640 ₽', place:'Аптека на Садовой', status:'Забронировано'}
    ]
  };
}
