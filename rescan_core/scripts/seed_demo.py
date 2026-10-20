"""Демо-данные и создание таблиц.

Запуск:  python -m scripts.seed_demo

Что делает:
  1) накатывает миграции (если таблиц ещё нет) — через alembic API;
  2) создаёт пилотную клинику, филиал, двух врачей, форматы, цели;
  3) идемпотентно: повторный запуск ничего не дублирует.

Почему клиника нужна заранее: приём события (B2) ищет активную клинику, к
которой привязывать филиалы, врачей и пациентов. Без неё первый же вебхук
вернёт понятную ошибку с подсказкой запустить этот скрипт.
"""
from __future__ import annotations

import json
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.db.models import Clinic, Doctor, Format, Goal, GoalDoctor
from app.db.session import engine, session_scope

ROOT = Path(__file__).resolve().parent.parent
DEMO_STEP_OPTIONS = json.dumps([
    {"code": "discuss", "title": "Обсудить на приёме"},
    {"code": "retest", "title": "Пересдать через несколько недель", "weeks": [2, 4, 8, 12]},
    {"code": "followup", "title": "Прийти ко мне на контроль"},
], ensure_ascii=False)
DEMO_THEME = json.dumps({"name": "Клиника", "logo_url": None, "accent": "#2F6FED"},
                        ensure_ascii=False)

# B6: тексты страницы пациента P1–P8 — из docs/rescan-pilot/design/p1-p3.md и p4-p8.md.
DEMO_TEXTS = {
    "p1.active.title": "Анализы готовы",
    "p1.active.body": (
        "Здесь — следующий шаг и запись к врачу. Сами результаты смотрите в личном кабинете "
        "клиники или спросите у администратора."
    ),
    "p1.active.action": "Посмотреть следующий шаг",
    "p1.active.privacy": (
        "Ссылка личная, не пересылайте её. Результатов анализов на этой странице нет."
    ),
    "p1.consent.title": "Прежде чем продолжить",
    "p1.consent.body": (
        "Клиника пользуется сервисом rescan, чтобы вам было проще записаться к врачу. Сервис "
        "получает только ваш номер телефона и отметку, что анализы готовы. Результатов "
        "анализов у сервиса нет."
    ),
    "p1.consent.revoke": "Согласие можно отозвать в любой момент: позвоните в клинику.",
    "p1.consent.policy_link": "Как клиника обрабатывает данные",
    "p1.consent.action": "Соглашаюсь и продолжаю",
    "p1.consent.pending": "Сохраняем…",
    "p1.consent.error": (
        "Не получилось сохранить согласие. Проверьте интернет и нажмите кнопку ещё раз."
    ),
    "p1.expired.title": "Срок действия ссылки закончился",
    "p1.expired.body": (
        "Позвоните в клинику: администратор запишет вас к врачу или пришлёт новую ссылку."
    ),
    "p1.stopped.title": "Запись через эту страницу сейчас не работает",
    "p1.stopped.body": (
        "Клиника временно не принимает здесь заявки. Чтобы записаться к врачу, позвоните в "
        "клинику — администратор поможет."
    ),
    "p1.unsubscribed.title": "Вы отписались от сообщений клиники",
    "p1.unsubscribed.body": (
        "Мы больше ничего не присылаем, и эта страница закрыта. Чтобы записаться к врачу, "
        "позвоните в клинику."
    ),
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
    "p4.back": "Назад",
    "p4.title": "Выберите врача",
    "p4.body": (
        "Здесь врачи, которые ведут приём по вашей цели. Формат и удобное время выберете "
        "дальше."
    ),
    "p4.tag.ordering": "Ваш врач",
    "p4.tag.visited": "Вы уже были на приёме",
    "p4.price_from": "от {price}",
    "p4.card.action": "Выбрать",
    "p4.empty.title": "Записаться здесь пока не получится",
    "p4.empty.body": (
        "По этой цели запись через страницу не работает. Позвоните в клинику — администратор "
        "подберёт врача и время."
    ),
    "p4.empty.change_goal": "Выбрать другую цель",
    "p5.back": "Назад",
    "p5.title": "Заявка на приём",
    "p5.doctor.label": "Врач",
    "p5.format.legend": "Формат",
    "p5.format.prepay": "Оплата на сайте клиники после заявки",
    "p5.window.legend": "Удобное время",
    "p5.window.hint": "Администратор предложит время приёма в этом промежутке.",
    "p5.confirm_note": (
        "Это заявка, а не запись. Администратор клиники позвонит вам, подберёт точное время "
        "и подтвердит запись."
    ),
    "p5.action": "Оставить заявку",
    "p5.choose": "Выберите формат и удобное время, чтобы продолжить.",
    "p5.pending": "Отправляем…",
    "p5.error": (
        "Не получилось отправить заявку. Проверьте интернет и нажмите кнопку ещё раз — выбор "
        "сохранён."
    ),
    "p5.paid.title": "Заявка отправлена",
    "p5.paid.body": "Этот формат клиника просит оплатить заранее. Оплата — на сайте клиники.",
    "p5.paid.action": "Оплатить на сайте клиники",
    "p5.paid.new_tab": "Сайт клиники откроется в новой вкладке.",
    "p5.paid.later": "Посмотреть заявку",
    "p5.paid.note": (
        "Если оплатить не получилось, администратор подскажет, как это сделать, когда "
        "позвонит."
    ),
    "p5.no_doctor.title": "Этого врача нет в списке",
    "p5.no_doctor.body": "Возможно, расписание изменилось. Выберите врача ещё раз.",
    "p5.no_doctor.action": "К списку врачей",
    "p6.accepted.title": "Заявка принята",
    "p6.accepted.body": (
        "Администратор клиники позвонит вам, подберёт точное время и подтвердит запись."
    ),
    "p6.in_progress.title": "Администратор подбирает время",
    "p6.in_progress.body": (
        "Он позвонит вам, чтобы договориться о приёме. Если пропустили звонок, позвоните в "
        "клинику сами."
    ),
    "p6.booked.title": "Вы записаны",
    "p6.booked.body": (
        "Дату и время приёма вам сообщил администратор. Чтобы перенести запись, позвоните в "
        "клинику."
    ),
    "p6.cancelled.title": "Заявка закрыта",
    "p6.cancelled.body": (
        "Клиника закрыла эту заявку. Если вы хотите записаться, позвоните в клинику — "
        "администратор поможет."
    ),
    "p6.progress.accepted": "Заявка принята",
    "p6.progress.in_progress": "Администратор подбирает время",
    "p6.progress.booked": "Вы записаны",
    "p6.progress.current": "сейчас",
    "p6.summary.doctor": "Врач",
    "p6.summary.format": "Формат",
    "p6.summary.window": "Удобное время",
    "p6.summary.created": "Заявка от",
    "p6.revisit": "Статус заявки можно посмотреть по этой же ссылке.",
    "p7.entry": "Когда пересдавать",
    "p7.back": "Назад",
    "p7.before.title": "Пересдать анализы — {date}",
    "p7.before.body": (
        "Так предложил ваш врач. Оставить заявку можно уже сейчас: администратор подберёт "
        "время ближе к этой дате."
    ),
    "p7.today.title": "Пересдать анализы можно с сегодняшнего дня",
    "p7.today.body": (
        "Срок, который предложил врач, наступил. Оставьте заявку — администратор подберёт "
        "удобное время."
    ),
    "p7.overdue.title": "Записаться на пересдачу можно сейчас",
    "p7.overdue.body": (
        "Врач предлагал пересдать анализы с {date}. Оставьте заявку — администратор подберёт "
        "удобное время."
    ),
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
    "p8.observe.body": (
        "Так решил ваш врач после приёма. Если появятся вопросы, запишитесь на приём."
    ),
    "p8.retest.title": "Ваш врач предлагает пересдать анализы",
    "p8.retest.body": "Оставьте заявку заранее — администратор подберёт удобное время.",
    "p8.specialist.title": "Ваш врач предлагает приём у другого специалиста",
    "p8.specialist.body": "Оставьте заявку — клиника подберёт специалиста и удобное время.",
    "p8.none.title": "Следующего шага после приёма нет",
    "p8.none.body": (
        "Врач не назначил новых визитов. Если появятся вопросы, запишитесь на приём или "
        "позвоните в клинику."
    ),
    "p8.due": "Срок, который предложил врач: {date}",
    "p8.memo.title": "Чтобы не забыть",
    "p8.memo.1": "Заявку можно оставить заранее — администратор подберёт время.",
    "p8.memo.2": (
        "Если вы уже записались по телефону, нажмите «У меня уже есть запись», и мы "
        "перестанем напоминать."
    ),
    "p8.action": "Записаться",
    "p8.booked.action": "У меня уже есть запись",
    "p8.booked.pending": "Сохраняем…",
    "p8.booked.done": "Хорошо, напоминать не будем.",
    "p8.booked.already": "Вы отметили, что уже записаны. Напоминать не будем.",
    "p8.booked.error": "Не получилось сохранить. Проверьте интернет и нажмите кнопку ещё раз.",
    "p8.empty.title": "Напоминаний пока нет",
    "p8.empty.body": "Когда врач отметит следующий шаг после приёма, он появится здесь.",
    "p8.empty.action": "К следующему шагу",
    "err.invalid_input": (
        "Этот вариант сейчас недоступен. Проверьте выбор и нажмите кнопку ещё раз."
    ),
}
DEMO_BRANCHES = [
    {"code": code, "title": DEMO_TEXTS[f"p2.branch.{code}.title"],
     "hint": DEMO_TEXTS[f"p2.branch.{code}.hint"]}
    for code in ("discuss", "retest", "followup")
]
DEMO_WINDOWS = [
    {"code": "morning", "title": "Утром, 8:00–12:00"},
    {"code": "day", "title": "Днём, 12:00–16:00"},
    {"code": "evening", "title": "Вечером, 16:00–20:00"},
    {"code": "any", "title": "В любое время"},
]
DEMO_PATIENT_SETTINGS = json.dumps({
    "phone": "+7 000 000-00-00",
    "privacy_url": "https://example-clinic.ru/privacy",
    "timezone": "Europe/Moscow",
    "branches": DEMO_BRANCHES,
    "windows": DEMO_WINDOWS,
    "texts": DEMO_TEXTS,
}, ensure_ascii=False)
DEMO_GOALS = ["Обсудить анализы с врачом", "Пересдать анализы",
              "Повторный приём у своего врача", "Другой вопрос к врачу"]
# Порядок врачей в каждой цели: терапевты первыми.
DEMO_GOAL_DOCTORS = ["dev-doctor", "doc-1", "doc-2"]


def run_migrations() -> None:
    """Накатить миграции. Так таблицы создаются ровно по схеме, а не «как получится»."""
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")


def seed() -> None:
    with session_scope() as session:
        clinic = session.query(Clinic).first()
        if clinic is None:
            clinic = Clinic(name="Пилотная клиника", service_enabled=True, theme=DEMO_THEME)
            session.add(clinic)
            session.flush()

        # B4: шаги врача, включённые демо-клиникой, и врач токена dev-doctor-token.
        if not clinic.step_options:
            clinic.step_options = DEMO_STEP_OPTIONS
        # B6: страница пациента.
        if not clinic.patient_settings:
            clinic.patient_settings = DEMO_PATIENT_SETTINGS
        if not session.query(Doctor).filter_by(clinic_id=clinic.id,
                                               external_id="dev-doctor").first():
            session.add(Doctor(clinic_id=clinic.id, external_id="dev-doctor",
                               full_name="Демо-врач очереди", specialty="Терапевт"))

        if not session.query(Doctor).filter_by(clinic_id=clinic.id,
                                               external_id="doc-1").first():
            session.add_all([
                Doctor(clinic_id=clinic.id, external_id="doc-1",
                       full_name="Иванова Анна Петровна", specialty="Терапевт"),
                Doctor(clinic_id=clinic.id, external_id="doc-2",
                       full_name="Петров Сергей Иванович", specialty="Кардиолог"),
            ])

        if not session.query(Format).filter_by(clinic_id=clinic.id).first():
            session.add_all([
                Format(clinic_id=clinic.id, title="Приём в клинике", price_kopecks=250000),
                Format(clinic_id=clinic.id, title="Онлайн-консультация", price_kopecks=180000),
                Format(clinic_id=clinic.id, title="Быстрый ответ врача", price_kopecks=90000,
                       payment_url="https://example-clinic.ru/pay/quick-answer"),
            ])

        if not session.query(Goal).filter_by(clinic_id=clinic.id).first():
            session.add_all([
                Goal(clinic_id=clinic.id, title=title, sort_order=order)
                for order, title in enumerate(DEMO_GOALS, start=1)
            ])
        session.flush()
        seed_goal_doctors(session, clinic)


def seed_goal_doctors(session, clinic: Clinic) -> None:
    """Каждой цели — все демо-врачи в порядке DEMO_GOAL_DOCTORS; недостающие пары дописать."""
    doctors = {doctor.external_id: doctor for doctor in
               session.query(Doctor).filter_by(clinic_id=clinic.id).all()}
    for goal in session.query(Goal).filter_by(clinic_id=clinic.id).all():
        for order, external_id in enumerate(DEMO_GOAL_DOCTORS, start=1):
            doctor = doctors.get(external_id)
            if doctor and session.get(GoalDoctor, (goal.id, doctor.id)) is None:
                session.add(GoalDoctor(goal_id=goal.id, doctor_id=doctor.id, sort_order=order))


def main() -> None:
    print("Накатываю миграции...")
    run_migrations()
    print("Пишу демо-данные...")
    seed()
    print("Готово. Таблиц в базе:", len(engine.dialect.get_table_names(engine.connect())))


if __name__ == "__main__":
    main()
