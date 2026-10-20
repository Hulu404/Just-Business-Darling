// FE4: данные моков P7, P8 (только синтетика). Логика ответов и токены сбоев — mocks.js и api.js (FE3).
//   CARE       — сессии по мок-токену в том же виде, что PATIENT в mocks-patient.js,
//                плюс after_visit: null | { step: { code, due_date, doctor_name }, booked }.
//   CARE_TEXTS — тексты P7, P8 и err.invalid_input; mocks.js добавляет их к texts каждой сессии.
// Тексты — docs/rescan-pilot/design/p4-p8.md, раздел «Тексты», дословно.
import { PATIENT } from './mocks-patient.js';

export const CARE_TEXTS = Object.freeze({
  "p7.entry": "Когда пересдавать",
  "p7.back": "Назад",
  "p7.before.title": "Пересдать анализы — {date}",
  "p7.before.body": "Так предложил ваш врач. Оставить заявку можно уже сейчас: администратор подберёт время ближе к этой дате.",
  "p7.today.title": "Пересдать анализы можно с сегодняшнего дня",
  "p7.today.body": "Срок, который предложил врач, наступил. Оставьте заявку — администратор подберёт удобное время.",
  "p7.overdue.title": "Записаться на пересдачу можно сейчас",
  "p7.overdue.body": "Врач предлагал пересдать анализы с {date}. Оставьте заявку — администратор подберёт удобное время.",
  "p7.memo.title": "Перед пересдачей",
  "p7.memo.1": "Спросите администратора, как подготовиться: правила зависят от анализов.",
  "p7.memo.2": "Возьмите паспорт, а если сдаёте по полису — и полис.",
  "p7.memo.3": "Если планы изменятся, позвоните в клинику — запись перенесут.",
  "p7.action": "Записаться",
  "p7.none.title": "Срока пересдачи нет",
  "p7.none.body": "Врач не предлагал пересдачу. Посмотрите следующий шаг.",
  "p7.none.action": "К следующему шагу",

  "p8.demo": "Демо: напоминание после приёма пока работает только на учебных данных.",
  "p8.observe.title": "Новых визитов пока не нужно",
  "p8.observe.body": "Так решил ваш врач после приёма. Если появятся вопросы, запишитесь на приём.",
  "p8.retest.title": "Ваш врач предлагает пересдать анализы",
  "p8.retest.body": "Оставьте заявку заранее — администратор подберёт удобное время.",
  "p8.specialist.title": "Ваш врач предлагает приём у другого специалиста",
  "p8.specialist.body": "Оставьте заявку — клиника подберёт специалиста и удобное время.",
  "p8.none.title": "Следующего шага после приёма нет",
  "p8.none.body": "Врач не назначил новых визитов. Если появятся вопросы, запишитесь на приём или позвоните в клинику.",
  "p8.due": "Срок, который предложил врач: {date}",
  "p8.memo.title": "Чтобы не забыть",
  "p8.memo.1": "Заявку можно оставить заранее — администратор подберёт время.",
  "p8.memo.2": "Если вы уже записались по телефону, нажмите «У меня уже есть запись», и мы перестанем напоминать.",
  "p8.action": "Записаться",
  "p8.booked.action": "У меня уже есть запись",
  "p8.booked.pending": "Сохраняем…",
  "p8.booked.done": "Хорошо, напоминать не будем.",
  "p8.booked.already": "Вы отметили, что уже записаны. Напоминать не будем.",
  "p8.booked.error": "Не получилось сохранить. Проверьте интернет и нажмите кнопку ещё раз.",
  "p8.empty.title": "Напоминаний пока нет",
  "p8.empty.body": "Когда врач отметит следующий шаг после приёма, он появится здесь.",
  "p8.empty.action": "К следующему шагу",

  "err.invalid_input": "Этот вариант сейчас недоступен. Проверьте выбор и нажмите кнопку ещё раз."
});

const DOCTOR_NAME = 'Иванова Анна Петровна';
const RETEST_WEEKS = 4;
const DAYS_IN_WEEK = 7;
const OVERDUE_DAYS = 10;
// Демо-клиники живут в Europe/Moscow. Даты считаются от сегодняшнего дня, чтобы состояние не менялось само.
const CLINIC_TIMEZONE = 'Europe/Moscow';

const today = () => new Intl.DateTimeFormat('en-CA', {
  timeZone: CLINIC_TIMEZONE, year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date());

export function demoDate(offsetDays) {
  const day = new Date(`${today()}T12:00:00Z`);
  day.setUTCDate(day.getUTCDate() + offsetDays);
  return day.toISOString().slice(0, 10);
}

const withCare = (session, changes) => ({
  ...structuredClone(session), choice: null, request: null, after_visit: null, ...changes,
  texts: { ...session.texts, ...CARE_TEXTS },
});
const retest = (state, offsetDays) => withCare(PATIENT['demo-active'], {
  doctor_step: { code: 'retest', retest_weeks: RETEST_WEEKS, due_date: demoDate(offsetDays), retest_state: state, doctor_name: DOCTOR_NAME },
});
const afterVisit = booked => withCare(PATIENT['demo-active'], {
  after_visit: { step: { code: 'retest', due_date: demoDate(RETEST_WEEKS * DAYS_IN_WEEK), doctor_name: DOCTOR_NAME }, booked },
});
// demo-step-retest из FE2 расширен датой и состоянием: P2 ведёт с него на P7, остальные поля прежние.
const stepRetest = PATIENT['demo-step-retest'];

export const CARE = Object.freeze({
  'demo-step-retest': withCare(stepRetest, {
    doctor_step: { ...stepRetest.doctor_step, due_date: demoDate(RETEST_WEEKS * DAYS_IN_WEEK), retest_state: 'before' },
  }),
  'demo-retest-before': retest('before', RETEST_WEEKS * DAYS_IN_WEEK),
  'demo-retest-today': retest('today', 0),
  'demo-retest-overdue': retest('overdue', -OVERDUE_DAYS),
  'demo-after-visit': afterVisit(false),
  'demo-after-booked': afterVisit(true),
});
