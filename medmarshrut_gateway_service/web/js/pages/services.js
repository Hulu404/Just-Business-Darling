import { icon } from '../icons.js';
import { health } from '../state.js';
import { badge, errorNote, loadingLine } from '../ui.js';

/* ---------- Карта сервисов ---------- */
export const jump = (label, target, kind = 'secondary small') => `<button class="btn ${kind}" data-jump="${target}">${label}</button>`;
export function services(){
  const cards = [
    ['scan', '', 'Что на снимке?', 'Принимает снимок или готовое заключение ИИ и показывает врачу черновик с находками. После подтверждения объясняет результат пациенту простыми словами.', [['Глазами пациента', 'patient:imaging'], ['Глазами врача', 'doctor:reading']]],
    ['route', '', 'Путь пациента', 'Маршрутизатор читает подтверждённое заключение и по правилам клиники предлагает следующий шаг. Эпизод ведёт пациента через запись, визит и новые назначения в клинике и у партнёров.', [['План пациента', 'patient:plan'], ['Очередь координатора', 'staff:inbox'], ['Партнёры', 'staff:partners:refs'], ['Глазами партнёра', 'partner:incoming']]],
    ['doctor', 'blue', 'Врач — клиника', 'Координатор просит врача подтвердить маршрут. Врач передаёт, кого и куда записать после приёма. Каждый запрос привязан к обращению.', [['Глазами координатора', 'staff:requests'], ['Глазами врача', 'doctor:requests']]],
    ['message', 'blue', 'Клиника — пациент', 'Сообщение уходит, когда готов результат, пора записаться или изменился план. Пациент отвечает кнопкой: записаться, попросить звонок, отложить.', [['Переписка пациента', 'patient:messages'], ['Журнал клиники', 'staff:comms']]],
    ['cart', 'violet', 'Маркетплейс без рецепта', 'Безрецептурные товары из аптек-партнёров. Заказ можно забрать в клинике в день приёма.', [['Каталог', 'patient:pharmacy:otc'], ['Заказы', 'staff:pharmacyAdmin']]],
    ['pharmacy', 'violet', 'Аптеки-партнёры', 'Электронный рецепт после приёма попадает в план. Пациент видит наличие и бронирует препарат в аптеке рядом.', [['Рецепты пациента', 'patient:pharmacy:rx'], ['Сеть аптек', 'staff:partners:pharm']]]
  ];
  const node = (t, sub, n) => `<div class="node"><div class="nodehead">${n ? `<b class="num">${n}</b>` : ''}<span>${t}</span></div><small>${sub}</small></div>`;
  return `<div class="pagehead"><div><div class="eyebrow">Обзор продукта</div><h1>Карта сервисов</h1><p>ИИ-заключение по снимку превращается в следующий шаг пациента. Шесть сервисов закрывают путь от снимка до аптеки.</p></div></div>
    <div class="panel"><div class="flow">
      <div class="flowcol"><div class="flowhead">Откуда приходят данные</div>${node('РИС и PACS клиники', 'Снимки DICOM и описания')}${node('ИИ-сервисы «Третье мнение»', 'Заключения ИИ по КТ, рентгену, маммографии')}${node('МИС клиники', 'Расписание, карта пациента, итоги визитов')}${node('Пациент', 'Снимок или заключение из другой клиники')}</div>
      <div class="arrow">→</div>
      <div class="flowcol core"><div class="flowhead">МедМаршрут</div>${node('Что на снимке?', 'Черновик ИИ, затем подтверждение врача', 1)}<div class="down">↓</div>${node('Путь пациента', 'Заключение, следующий шаг, эпизод сопровождения', 2)}<div class="down">↓</div><div class="pair">${node('Врач — клиника', 'Решения и запросы', 3)}${node('Клиника — пациент', 'Сообщения и ответы', 4)}</div><div class="pair">${node('Маркетплейс', 'Товары без рецепта', 5)}${node('Аптеки-партнёры', 'Бронь по рецепту', 6)}</div></div>
      <div class="arrow">→</div>
      <div class="flowcol"><div class="flowhead">Кто этим пользуется</div>${node('Пациент', 'Личный кабинет и приложение: объяснение, запись, план, аптека')}${node('Координатор', 'Очередь, рекомендация, запись')}${node('Врач', 'Черновик ИИ, итог приёма, рецепт')}${node('Клиники-партнёры', 'Направление туда, результат обратно')}${node('Аптеки-партнёры', 'Наличие, бронь, выдача')}</div>
    </div>${clinicState()}</div>
    <div class="sectionhead"><h2>Шесть сервисов</h2><span class="muted">Кнопки открывают нужный экран в нужной роли</span></div>
    <div class="grid three">${cards.map(([ic, tone, name, text, links], i) => `<div class="card"><div class="tile ${tone}">${icon(ic)}</div><h3>${i + 1}. ${name}</h3><p>${text}</p>${cardState(i)}<div class="actions" style="margin-top:16px">${links.map(([l, t]) => jump(l, t)).join('')}</div></div>`).join('')}</div>
    <div class="sectionhead"><h2>Как показать за три минуты</h2></div>
    <div class="panel"><ol class="routeSteps">
      <li><b>1</b><span><strong>Пациент узнаёт результат.</strong> На главной — «Результат рентгенографии готов», в разделе «Что на снимке» — объяснение и следующий шаг. ${jump('Открыть', 'patient:imaging', 'ghost small')}</span></li>
      <li><b>2</b><span><strong>Пациент записывается.</strong> Время в своей клинике или у партнёра, без звонка. ${jump('Открыть', 'patient:appointments', 'ghost small')}</span></li>
      <li><b>3</b><span><strong>Координатор видит, кто не дошёл.</strong> В карточке — заключение, рекомендация и причина задержки. ${jump('Открыть', 'staff:inbox', 'ghost small')}</span></li>
      <li><b>4</b><span><strong>Врач проверяет черновик ИИ.</strong> После подтверждения маршрут строится сам. ${jump('Открыть', 'doctor:reading', 'ghost small')}</span></li>
      <li><b>5</b><span><strong>Врач вносит итог приёма.</strong> Назначает следующие шаги и выписывает рецепт. ${jump('Открыть', 'doctor:doctor', 'ghost small')}</span></li>
      <li><b>6</b><span><strong>План продолжается.</strong> У пациента новый этап, бронь по рецепту и заказ без рецепта. ${jump('Открыть', 'patient:pharmacy:rx', 'ghost small')}</span></li>
    </ol></div>
    <div class="sectionhead"><h2>На чём держится безопасность</h2></div>
    <div class="grid two">
      <div class="card"><h3>Диагноз ставит врач</h3><p>ИИ готовит черновик, врач его подтверждает. До подтверждения результат не видят ни пациент, ни координатор.</p></div>
      <div class="card"><h3>План меняет человек или утверждённое правило</h3><p>Маршрутизатор применяет только правила, которые утвердила клиника. Нет правила — случай уходит врачу.</p></div>
      <div class="card"><h3>Срочность не зависит от оценки модели</h3><p>Срок следующего шага задают правило или врач. Число «0,91» остаётся в журнале для аудита.</p></div>
      <div class="card"><h3>Заключение не уходит в мессенджеры</h3><p>В SMS и мессенджерах только ссылка. Текст заключения пациент читает в личном кабинете.</p></div>
    </div>`;
}

/* ---------- Дополнения продукта: состояние сервисов из GET /api/health ---------- */
/* Карточки 1 и 2 работают на настоящих сервисах, остальные четыре — демо-модули */
const LIVE_CARDS = {0:'image', 1:'path'};
function serviceBadge(key){
  if (health.status === 'loading') return loadingLine();
  if (health.status !== 'ok' || !health.data.services[key]) return badge('нет данных', 'gray');
  return health.data.services[key].status === 'up' ? badge('работает') : badge('недоступен', 'red');
}
function cardState(i){
  const key = LIVE_CARDS[i];
  return `<p class="svcstate">${key ? 'Сервис: ' + serviceBadge(key) : badge('демо-модуль', 'gray')}</p>`;
}
function clinicState(){
  if (health.status === 'error') return errorNote(health.message, 'healthRetry');
  return `<p class="svcstate svcline">Сервис клиники — карта пациента, сеть клиник, направления: ${serviceBadge('clinic')}</p>`;
}
