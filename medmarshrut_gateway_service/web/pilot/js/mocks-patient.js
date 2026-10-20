// FE2: synthetic patient sessions. Copy: docs/rescan-pilot/design/p1-p3.md.
const PATIENT_TEXTS = {
  "p1.active.title": "Анализы готовы",
  "p1.active.body": "Здесь — следующий шаг и запись к врачу. Сами результаты смотрите в личном кабинете клиники или спросите у администратора.",
  "p1.active.action": "Посмотреть следующий шаг",
  "p1.active.privacy": "Ссылка личная, не пересылайте её. Результатов анализов на этой странице нет.",
  "p1.consent.title": "Прежде чем продолжить",
  "p1.consent.body": "Клиника пользуется сервисом rescan, чтобы вам было проще записаться к врачу. Сервис получает только ваш номер телефона и отметку, что анализы готовы. Результатов анализов у сервиса нет.",
  "p1.consent.revoke": "Согласие можно отозвать в любой момент: позвоните в клинику.",
  "p1.consent.policy_link": "Как клиника обрабатывает данные",
  "p1.consent.action": "Соглашаюсь и продолжаю",
  "p1.consent.pending": "Сохраняем…",
  "p1.consent.error": "Не получилось сохранить согласие. Проверьте интернет и нажмите кнопку ещё раз.",
  "p1.expired.title": "Срок действия ссылки закончился",
  "p1.expired.body": "Позвоните в клинику: администратор запишет вас к врачу или пришлёт новую ссылку.",
  "p1.stopped.title": "Запись через эту страницу сейчас не работает",
  "p1.stopped.body": "Клиника временно не принимает здесь заявки. Чтобы записаться к врачу, позвоните в клинику — администратор поможет.",
  "p1.unsubscribed.title": "Вы отписались от сообщений клиники",
  "p1.unsubscribed.body": "Мы больше ничего не присылаем, и эта страница закрыта. Чтобы записаться к врачу, позвоните в клинику.",
  "p1.call.action": "Позвонить в клинику: {clinic_phone}",
  "p1.call.no_phone": "Номер телефона есть на сайте клиники.",
  "p2.doctor.label": "Ваш врач",
  "p2.discuss.title": "Ваш врач предлагает обсудить анализы на приёме",
  "p2.discuss.body": "Формат приёма и удобное время выберете на следующих шагах.",
  "p2.retest.title": "Ваш врач предлагает пересдать анализы через {weeks_text}",
  "p2.retest.body": "Заявку можно оставить уже сейчас — администратор подберёт удобную дату.",
  "p2.retest.weeks.one": "{n} неделю",
  "p2.retest.weeks.few": "{n} недели",
  "p2.retest.weeks.many": "{n} недель",
  "p2.followup.title": "Ваш врач предлагает прийти на повторный приём",
  "p2.followup.body": "Приём у того же врача. Удобное время выберете на следующих шагах.",
  "p2.step.action": "Выбрать цель визита",
  "p2.branches.title": "Как вы хотите продолжить?",
  "p2.branches.body": "Выберите один вариант — дальше подскажем, к кому и когда записаться.",
  "p2.branch.discuss.title": "Обсудить анализы с врачом",
  "p2.branch.discuss.hint": "Приём в клинике или онлайн",
  "p2.branch.retest.title": "Записаться на пересдачу анализов",
  "p2.branch.retest.hint": "Если врач уже говорил, когда пересдавать",
  "p2.branch.followup.title": "Записаться на плановый приём",
  "p2.branch.followup.hint": "К своему врачу или к терапевту",
  "p2.branches.action": "Дальше",
  "p2.branches.choose": "Выберите вариант, чтобы продолжить.",
  "p3.back": "Назад",
  "p3.title": "Какая цель визита?",
  "p3.body": "Выберите одну. По ней клиника подберёт врача и формат приёма.",
  "p3.action": "Дальше",
  "p3.choose": "Выберите цель, чтобы продолжить.",
  "p3.pending": "Сохраняем…",
  "p3.error": "Не получилось сохранить выбор. Проверьте интернет и нажмите «Дальше» ещё раз.",
  "next.title": "Дальше — выбор врача",
  "next.body": "Здесь появятся врачи, формат приёма и удобное время. Демо: экран в разработке.",
  "next.saved": "Ваш выбор сохранён.",
  "next.back": "Изменить цель"
};
const PATIENT_CLINIC_A = {
  name: 'Демо-клиника А',
  phone: '+7 000 000-00-00',
  theme: { name: 'Демо-клиника А', logo_url: '', accent: '#1D5FD1' },
};
const PATIENT_CLINIC_B = {
  name: 'Демо-клиника Б',
  theme: { name: 'Демо-клиника Б', logo_url: '', accent: '#00A3AD' },
};
const PATIENT_BASE = {
  state: 'active', clinic: PATIENT_CLINIC_A, consent_required: false, doctor_step: null,
  branches: [
  {
    "code": "discuss",
    "title": "Обсудить анализы с врачом",
    "hint": "Приём в клинике или онлайн"
  },
  {
    "code": "retest",
    "title": "Записаться на пересдачу анализов",
    "hint": "Если врач уже говорил, когда пересдавать"
  },
  {
    "code": "followup",
    "title": "Записаться на плановый приём",
    "hint": "К своему врачу или к терапевту"
  }
],
  goals: [
  {
    "id": "goal-discuss",
    "title": "Обсудить анализы с врачом"
  },
  {
    "id": "goal-retest",
    "title": "Пересдать анализы"
  },
  {
    "id": "goal-followup",
    "title": "Повторный приём у своего врача"
  },
  {
    "id": "goal-other",
    "title": "Другой вопрос к врачу"
  }
],
  texts: PATIENT_TEXTS,
};
export const PATIENT = {
  'demo-active': { ...PATIENT_BASE },
  'demo-step-discuss': { ...PATIENT_BASE, doctor_step: { code: 'discuss', retest_weeks: null, doctor_name: 'Демо-врач' } },
  'demo-step-retest': { ...PATIENT_BASE, doctor_step: { code: 'retest', retest_weeks: 4, doctor_name: 'Демо-врач' } },
  'demo-step-followup': { ...PATIENT_BASE, doctor_step: { code: 'followup', retest_weeks: null, doctor_name: 'Демо-врач' } },
  'demo-expired': { ...PATIENT_BASE, state: 'expired' },
  'demo-stopped': { ...PATIENT_BASE, state: 'stopped' },
  'demo-unsubscribed': { ...PATIENT_BASE, state: 'unsubscribed' },
  'demo-consent': { ...PATIENT_BASE, consent_required: true },
  'demo-clinic-a': { ...PATIENT_BASE, clinic: PATIENT_CLINIC_A },
  'demo-clinic-b': { ...PATIENT_BASE, clinic: PATIENT_CLINIC_B },
};

// FE3: P4–P6 — врачи, форматы, окна времени, заявка. Тексты — docs/rescan-pilot/design/p4-p8.md.
// mocks.js добавляет BOOKING_TEXTS к texts каждой сессии и берёт врачей, форматы и окна из BOOKING_CATALOG,
// если у сессии нет своих. Поля doctors, formats, windows сессии наружу не уходят: их отдают свои пути.
export const BOOKING_TEXTS = {
  "p4.back": "Назад",
  "p4.title": "Выберите врача",
  "p4.body": "Здесь врачи, которые ведут приём по вашей цели. Формат и удобное время выберете дальше.",
  "p4.tag.ordering": "Ваш врач",
  "p4.tag.visited": "Вы уже были на приёме",
  "p4.price_from": "от {price}",
  "p4.card.action": "Выбрать",
  "p4.empty.title": "Записаться здесь пока не получится",
  "p4.empty.body": "По этой цели запись через страницу не работает. Позвоните в клинику — администратор подберёт врача и время.",
  "p4.empty.change_goal": "Выбрать другую цель",
  "p5.back": "Назад",
  "p5.title": "Заявка на приём",
  "p5.doctor.label": "Врач",
  "p5.format.legend": "Формат",
  "p5.format.prepay": "Оплата на сайте клиники после заявки",
  "p5.window.legend": "Удобное время",
  "p5.window.hint": "Администратор предложит время приёма в этом промежутке.",
  "p5.confirm_note": "Это заявка, а не запись. Администратор клиники позвонит вам, подберёт точное время и подтвердит запись.",
  "p5.action": "Оставить заявку",
  "p5.choose": "Выберите формат и удобное время, чтобы продолжить.",
  "p5.pending": "Отправляем…",
  "p5.error": "Не получилось отправить заявку. Проверьте интернет и нажмите кнопку ещё раз — выбор сохранён.",
  "p5.paid.title": "Заявка отправлена",
  "p5.paid.body": "Этот формат клиника просит оплатить заранее. Оплата — на сайте клиники.",
  "p5.paid.action": "Оплатить на сайте клиники",
  "p5.paid.new_tab": "Сайт клиники откроется в новой вкладке.",
  "p5.paid.later": "Посмотреть заявку",
  "p5.paid.note": "Если оплатить не получилось, администратор подскажет, как это сделать, когда позвонит.",
  "p5.no_doctor.title": "Этого врача нет в списке",
  "p5.no_doctor.body": "Возможно, расписание изменилось. Выберите врача ещё раз.",
  "p5.no_doctor.action": "К списку врачей",
  "p6.accepted.title": "Заявка принята",
  "p6.accepted.body": "Администратор клиники позвонит вам, подберёт точное время и подтвердит запись.",
  "p6.in_progress.title": "Администратор подбирает время",
  "p6.in_progress.body": "Он позвонит вам, чтобы договориться о приёме. Если пропустили звонок, позвоните в клинику сами.",
  "p6.booked.title": "Вы записаны",
  "p6.booked.body": "Дату и время приёма вам сообщил администратор. Чтобы перенести запись, позвоните в клинику.",
  "p6.cancelled.title": "Заявка закрыта",
  "p6.cancelled.body": "Клиника закрыла эту заявку. Если вы хотите записаться, позвоните в клинику — администратор поможет.",
  "p6.progress.accepted": "Заявка принята",
  "p6.progress.in_progress": "Администратор подбирает время",
  "p6.progress.booked": "Вы записаны",
  "p6.progress.current": "сейчас",
  "p6.summary.doctor": "Врач",
  "p6.summary.format": "Формат",
  "p6.summary.window": "Удобное время",
  "p6.summary.created": "Заявка от",
  "p6.revisit": "Статус заявки можно посмотреть по этой же ссылке.",
  // Решение координатора по вопросу 1 дизайнера: после booked и cancelled — новая заявка. Ключа в p4-p8.md пока нет
  "p6.new_request": "Оставить новую заявку",
};
export const BOOKING_CATALOG = {
  doctors: [
    { id: 'doc-ordering', name: 'Иванова Анна Петровна', specialty: 'Терапевт', photo_url: null, tag: 'ordering' },
    { id: 'doc-visited', name: 'Петров Сергей Иванович', specialty: 'Кардиолог', photo_url: null, tag: 'visited' },
    { id: 'doc-other', name: 'Демо-врач очереди', specialty: 'Терапевт', photo_url: null, tag: null },
  ],
  formats: [
    { id: 'fmt-clinic', title: 'Приём в клинике', price_kopecks: 250000, currency: 'RUB', payment_url: null },
    { id: 'fmt-online', title: 'Онлайн-консультация', price_kopecks: 180000, currency: 'RUB', payment_url: null },
    { id: 'fmt-quick', title: 'Быстрый ответ врача', price_kopecks: 90000, currency: 'RUB', payment_url: null },
  ],
  windows: [
    { code: 'morning', title: 'Утром, 8:00–12:00' },
    { code: 'day', title: 'Днём, 12:00–16:00' },
    { code: 'evening', title: 'Вечером, 16:00–20:00' },
    { code: 'any', title: 'В любое время' },
  ],
};
// «Демо-клиника Б» — другой набор окон: экран берёт окна из ответа, а не из кода
const CLINIC_B_WINDOWS = [
  { code: 'weekday_am', title: 'В будни до обеда, 9:00–13:00' },
  { code: 'weekday_pm', title: 'В будни после обеда, 14:00–20:00' },
  { code: 'weekend', title: 'В выходные, 10:00–16:00' },
];
const BOOKING_STEP = { code: 'discuss', retest_weeks: null, doctor_name: 'Иванова Анна Петровна' };
const BOOKING_CHOICE = { branch_code: null, goal_id: 'goal-discuss' };
const BOOKING_REQUEST = {
  id: 'req-demo', doctor_name: 'Иванова Анна Петровна', format_title: 'Приём в клинике',
  window_title: 'Утром, 8:00–12:00', created_at: '2026-10-20T09:30:00+03:00',
};
const requestIn = status => ({
  ...PATIENT_BASE, doctor_step: BOOKING_STEP, choice: BOOKING_CHOICE, request: { ...BOOKING_REQUEST, status },
});
export const BOOKING = {
  'demo-clinic-b': { ...PATIENT['demo-clinic-b'], windows: CLINIC_B_WINDOWS },
  'demo-no-doctors': { ...PATIENT_BASE, doctor_step: BOOKING_STEP, doctors: [] },
  'demo-paid-format': {
    ...PATIENT_BASE, doctor_step: BOOKING_STEP,
    formats: BOOKING_CATALOG.formats.map(format => (format.id === 'fmt-quick'
      ? { ...format, payment_url: 'https://example-clinic.ru/pay/quick-answer' } : format)),
  },
  'demo-request-accepted': requestIn('accepted'),
  'demo-request-in-progress': requestIn('in_progress'),
  'demo-request-booked': requestIn('booked'),
  'demo-request-cancelled': requestIn('cancelled'),
};
