import { seed } from './demo-data.js';

/* ---------- Состояние и базовые функции ---------- */
export const freshState = () => { const s = seed(); s.sandbox.result = null; return s; };
/* Создаётся в main.js до первой отрисовки: модули не вызывают функций при загрузке. */
export let state = null;
export function setState(value){ state = value; }
/* Переменные прототипа, которые меняют несколько модулей */
export const ui = {mobileOpen:false, modal:null, seq:200, toastTimer:null};

/* ---------- Связь с шлюзом ---------- */
/* main.js подставляет сюда синхронизацию адреса и сессии: go() вызывает её после каждого перехода */
export const hooks = {navigate(){}};
/* Сессии окна по ролям: {status:'loading'|'ok'|'error', data, message} */
export const sessions = {};
/* Состояние сервисов из GET /api/health */
export const health = {status:'loading', data:null, message:''};

/* Имена из сессии там, где прототип писал их текстом */
export const staffFirstName = () => (sessions.staff && sessions.staff.data && sessions.staff.data.name) || 'Наталья';
export const staffName = () => staffFirstName() + ', координатор';
export const patientName = () => (sessions.patient && sessions.patient.data && sessions.patient.data.name) || 'Демо-пациент';
