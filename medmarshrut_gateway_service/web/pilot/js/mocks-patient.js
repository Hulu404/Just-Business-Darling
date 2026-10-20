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
