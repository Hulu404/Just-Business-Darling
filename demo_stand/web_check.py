"""Browser checks of the web app on a running stand (Playwright). Run via `python start.py --web-check`."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from stand_api import GATEWAY, env, utf8_console

try:
    from playwright.sync_api import Error as PlaywrightError, sync_playwright
except ImportError:  # pragma: no cover - depends on the machine
    sync_playwright = None
from PIL import Image, ImageChops, ImageDraw

APP = GATEWAY
PROTOTYPE = Path(__file__).resolve().parents[1] / "prototype" / "medmarshrut_product_prototype_v2.html"

# 23 screens of the prototype, each in a role that has it in the menu (or reaches it from there).
SCREENS = [
    # rescan patient app (task 13): the only patient screens after the switch-over
    ("patient", "rsHome"), ("patient", "rsReport"), ("patient", "rsResults"), ("patient", "rsCare"),
    ("patient", "rsCalendar"), ("patient", "rsBook"), ("patient", "rsStep"), ("patient", "rsVisits"),
    ("patient", "rsProfile"),
    ("staff", "inbox"), ("staff", "case"), ("staff", "scheduling"), ("staff", "requests"), ("staff", "comms"),
    ("staff", "partners"), ("staff", "pharmacyAdmin"), ("staff", "rules"), ("staff", "analytics"),
    ("staff", "services"),
    ("partner", "incoming"), ("partner", "services"),
    # rescan doctor cabinet (task 12): the only doctor screens after the switch-over (cycle 9)
    ("doctor", "rsToday"), ("doctor", "rsStudies"), ("doctor", "rsPatients"), ("doctor", "rsVisits"), ("doctor", "rsSettings"),
]
WIDTHS = (390, 820, 1280, 1680)
MAX_DIFF = 0.01

# Pixel comparison with the prototype. A screen leaves this list when it moves to service data (tasks 04-07).
COMPARE = [s for s in SCREENS if s[1] not in {"services", "home", "plan", "appointments", "inbox", "case", "scheduling",
                                             "imaging", "reading", "study", "review", "rules", "analytics", "doctor",
                                             "partners", "documents", "incoming",
                                             "rsToday", "rsStudies", "rsPatients", "rsVisits", "rsSettings"}
           and s[0] != "patient"]
# Intentional differences. Masked areas are painted over in both screenshots before comparing.
MASKS = [".brand small"]  # sidebar subtitle: «Демо-стенд» instead of «Прототип · версия 2»
INTENTIONAL = [
    "подпись под названием в боковой панели: «Демо-стенд» (маска .brand small)",
    "«Карта сервисов»: строки состояния сервисов и пометки «демо-модуль» (экран не сравнивается)",
    "имена из сессии: в журнале и новых записях вместо текста прототипа (на стартовых экранах совпадают)",
    "экраны снимков работают на сервисе снимков: настоящие срезы вместо схем, загрузка ZIP с DICOM (не сравниваются)",
    "создание маршрута выключено до задания 07",
    "«Партнёры», «Документы» и кабинет клиники-партнёра работают на сервисе клиники: без выдуманных чисел (не сравниваются)",
    "кабинет врача rescan (rs*) сделан по другому образцу, prototype/rescan-app-standalone.html (не сравнивается)",
    "приложение пациента rescan (rs*) — мобильный сайт по тому же образцу (не сравнивается)",
]
CSP_PROBE = ("window.__mmCsp = [];"
             "document.addEventListener('securitypolicyviolation', e => window.__mmCsp.push(e.violatedDirective + ' ' + e.blockedURI));")


def say(ok: bool, text: str) -> None:
    print(("[ок] " if ok else "[!!] ") + text, flush=True)


def wait_ready(page) -> None:
    page.wait_for_function("() => document.querySelector('#view').children.length && !document.querySelector('.card.skeleton, .c-skel')",
                           timeout=8000)


def open_screen(page, role: str, name: str) -> None:
    page.evaluate(f"location.hash = '#/{role}/{name}'")
    page.wait_for_function(f"() => location.hash.split('?')[0] === '#/{role}/{name}' && document.querySelector('#role').value.split(':')[0] === '{role}'",
                           timeout=8000)
    wait_ready(page)


def watch(page) -> list[str]:
    errors: list[str] = []
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type in {"error", "warning"} else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.add_init_script(CSP_PROBE)
    return errors


def check_screens(browser) -> list[str]:
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = watch(page)
    failures = []
    page.goto(APP + "/")
    wait_ready(page)
    if not page.url.endswith("#/patient/rsHome"):
        failures.append(f"стартовый адрес {page.url}")
    for role, name in SCREENS:
        before = len(errors)
        open_screen(page, role, name)
        csp = page.evaluate("() => window.__mmCsp.splice(0)")
        if len(errors) > before or csp:
            failures.append(f"{role}/{name}: {'; '.join(errors[before:] + csp)}")
    # address survives a reload; back and forward work
    page.goto(APP + "/#/staff/case")
    wait_ready(page)
    page.reload()
    wait_ready(page)
    if page.inner_text("#topbar strong") != "Карточка обращения" or page.eval_on_selector("#role", "e => e.value") != "staff":
        failures.append("после обновления страницы открылся другой экран")
    page.click("[data-nav=scheduling]")
    wait_ready(page)
    page.go_back()
    page.wait_for_function("() => location.hash === '#/staff/case'")
    wait_ready(page)
    if page.inner_text("#topbar strong") != "Карточка обращения":
        failures.append("«Назад» не вернул на предыдущий экран")
    page.go_forward()
    page.wait_for_function("() => location.hash === '#/staff/scheduling'")
    # jumps from «Карта сервисов» open the right role and screen (у пациента карты больше нет, задание 13)
    open_screen(page, "staff", "services")
    page.click('[data-jump="staff:partners:refs"] >> nth=0')
    wait_ready(page)
    if page.evaluate("() => location.hash") != "#/staff/partners" or page.inner_text("#topbar strong") != "Партнёры":
        failures.append("переход staff:partners открыл " + page.evaluate("() => location.hash"))
    # «Глазами врача» ведёт в кабинет rescan: прежних экранов врача больше нет
    open_screen(page, "staff", "services")
    page.click('[data-jump="doctor:rsStudies"] >> nth=0')
    wait_ready(page)
    if page.evaluate("() => location.hash") != "#/doctor/rsStudies" or "Исследования" not in page.inner_text("#view"):
        failures.append("переход «Глазами врача» открыл " + page.evaluate("() => location.hash"))
    # прежние адреса врача открывают стартовый экран кабинета, а не старый каркас
    for old in ("reading", "inbox"):
        page.evaluate(f"location.hash = '#/doctor/{old}'")
        page.reload()
        wait_ready(page)
        if page.evaluate("() => location.hash") != "#/doctor/rsToday" or not page.query_selector("#clinic"):
            failures.append(f"прежний адрес #/doctor/{old} не открыл кабинет: " + page.evaluate("() => location.hash"))
    # прежние адреса пациента открывают «Главную» приложения
    for old in ("plan", "imaging"):
        page.evaluate(f"location.hash = '#/patient/{old}'")
        page.reload()
        wait_ready(page)
        if page.evaluate("() => location.hash") != "#/patient/rsHome" or not page.query_selector(".ph .ptabs"):
            failures.append(f"прежний адрес #/patient/{old} не открыл приложение: " + page.evaluate("() => location.hash"))
    page.close()
    return failures


def check_widths(browser) -> list[str]:
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(APP + "/")
    wait_ready(page)
    failures = []
    for width in WIDTHS:
        page.set_viewport_size({"width": width, "height": 900})
        for role, name in SCREENS:
            open_screen(page, role, name)
            overflow = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
            if overflow > 0:
                failures.append(f"{width}px {role}/{name}: шире экрана на {overflow}px")
    page.close()
    return failures


def check_rescan_today(browser) -> list[str]:
    """rescan cabinet, «Сегодня» on a clean stand: Игорь С. is in «Новые исследования», Мария К. and Сергей Т. in
    «Требуют внимания», Елена П. in «Приёмы»; the bell feed lists a new study. Runs before the scenarios that
    change patient state (bookings, outcomes, the plan for Мария К.)."""
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = watch(page)
    failures = []
    page.goto(APP + "/#/doctor/rsToday")
    wait_ready(page)
    page.wait_for_selector("#clinic .c-att, #clinic .c-g2 .c-empty")
    if "Игорь" not in page.inner_text("#clinic .c-g2 > .c-card"):
        failures.append("Игоря С. нет в «Новых исследованиях»")
    attention = page.inner_text("#clinic .c-g2 .c-col")
    for who in ("Мария", "Сергей"):
        if who not in attention:
            failures.append(f"{who} нет в «Требуют внимания»")
    page.click("[data-action=rsFeed]")
    page.wait_for_selector("#clinic .c-feed")
    if "Новое исследование" not in page.inner_text("#clinic .c-feed"):
        failures.append("в ленте колокольчика нет нового исследования")
    open_screen(page, "doctor", "rsVisits")
    if "Елена" not in page.inner_text("#clinic .c-tbl"):
        failures.append("Елены П. нет в «Приёмах»")
    if errors:
        failures.append("ошибки в консоли: " + "; ".join(errors))
    page.close()
    return failures


def book_on_phone(page) -> bool:
    """«Запись» in the patient app: open the first step that waits for booking, take the first free time, book."""
    if not page.query_selector(".ph [data-action=phOpenStep]"):
        return False
    page.click(".ph .pgrid [data-action=phOpenStep] >> nth=0")
    page.wait_for_selector(".ph [data-action=phSlot]", timeout=10000)
    page.click(".ph [data-action=phSlot] >> nth=0")
    page.click(".ph [data-action=phBook]:not([disabled])")
    page.wait_for_selector("#phDone:has-text('Вы записаны')", timeout=20000)
    return True


def check_scenario(browser) -> list[str]:
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = watch(page)
    page.goto(APP + "/#/patient/rsBook")
    wait_ready(page)
    failures = []
    if not book_on_phone(page):
        page.close()
        return ["у пациента нет шага, на который можно записаться"]
    page.goto(APP + "/#/staff/inbox")  # в списке ролей только пациент и врач
    page.wait_for_selector("#view:has-text('Демо-пациент')")
    if "Демо-пациент" not in page.inner_text("#view"):
        failures.append("координатор не видит обращение пациента")
    if errors:
        failures.append("ошибки в консоли: " + "; ".join(errors))
    page.close()
    return failures


def check_two_windows(browser) -> list[str]:
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    patient, staff = context.new_page(), context.new_page()
    patient.goto(APP + "/#/patient/rsHome")
    staff.goto(APP + "/#/staff/inbox")
    wait_ready(patient)
    wait_ready(staff)
    patient.reload()
    staff.reload()
    wait_ready(patient)
    wait_ready(staff)
    failures = []
    for page, role, badge in ((patient, "patient", "Пациент"), (staff, "staff", "Клиника")):
        # у пациента вместо шапки прототипа полоса rescan: роль окна видна в списке ролей
        if page.eval_on_selector("#role", "e => e.value") != role or (role == "staff" and badge not in page.inner_text("#topbar")):
            failures.append(f"окно {role} показывает чужую роль")
        session = page.evaluate("role => fetch('/api/session', {headers:{'X-MM-Role':role}}).then(r => r.json())", role)
        if session.get("role") != role:
            failures.append(f"окно {role}: сессия {session}")
    open_screen(patient, "patient", "rsResults")
    staff.click("[data-nav=requests]")
    wait_ready(staff)
    if staff.eval_on_selector("#role", "e => e.value") != "staff" or patient.eval_on_selector("#role", "e => e.value") != "patient":
        failures.append("действия в одном окне поменяли роль в другом")
    context.close()
    return failures


def check_rescan_imaging(browser) -> list[str]:
    """rescan cabinet, «Исследования»: the patient uploads a kit CT, the doctor sees the rule preview, pages real slices
    and confirms; the route chain appears and the patient sees the result. Seeded studies are left untouched."""
    archive = Path(env("DEMO_STATE_DIR")) / "kit" / "upload-ct-nodule.zip"
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    patient, doctor = context.new_page(), context.new_page()
    patient_errors, doctor_errors = watch(patient), watch(doctor)
    failures = []
    patient.goto(APP + "/#/patient/rsResults")
    wait_ready(patient)
    patient.click(".ph .wbtn[data-action=phUpload]")
    if "Рентгенография" not in patient.inner_text("#upKind"):
        failures.append("в окне загрузки нет рентгенографии")
    patient.click("[data-action=uploadKit]")
    patient.wait_for_selector("[data-action=uploadKitSend]")
    patient.set_input_files("#upFile", str(archive))
    patient.select_option("#upKind", "ct_general")
    patient.check("#upConsent")
    patient.click("[data-action=upload]")
    patient.wait_for_selector("#view .mrow:has-text('Ждёт врача')", timeout=70000)
    doctor.goto(APP + "/#/doctor/rsStudies")
    wait_ready(doctor)
    job = doctor.evaluate("""async () => {
        const r = await fetch('/api/doctor/studies', {headers: {'X-MM-Role': 'doctor'}});
        const list = (await r.json()).studies.filter(s => s.status === 'awaiting_physician' && s.uploaded_by_role === 'patient');
        list.sort((a, b) => b.created_at.localeCompare(a.created_at));
        return list.length ? list[0].id : null; }""")
    if not job:
        context.close()
        return ["у врача нет загруженного пациентом исследования"]
    doctor.wait_for_selector(f"[data-action=rsStudyOpen][data-id='{job}']")
    doctor.click(f".c-tabs [data-action=rsStudyOpen][data-id='{job}']")
    doctor.wait_for_selector("#clinic img.studyimg[src^='blob:']", timeout=20000)
    text = doctor.inner_text("#view")
    if "Демо-сценарий: признак задан заранее" not in text:
        failures.append("нет плашки демо-сценария")
    if "оценка модели" in text.lower().replace("оценка модели пациенту", ""):
        failures.append("в демо-сценарии видна оценка модели")
    if "Шаг по правилу клиники" not in text:
        failures.append("нет предпросмотра шага по правилу")
    if "Просмотр для проверки, не диагностический просмотрщик" not in text:
        failures.append("нет подписи просмотрщика")
    if doctor.query_selector("[data-action=rsRewrite]"):
        failures.append("без ключа API у врача видна кнопка ИИ-помощника")
    if not doctor.query_selector("#rsDraft") or not doctor.input_value("#rsDraft").strip():
        failures.append("нет заготовки заключения")
    planned = doctor.inner_text("#clinic .c-dec .c-next b") if doctor.query_selector("#clinic .c-dec .c-next b") else ""
    first = doctor.get_attribute("#clinic img.studyimg", "alt")
    doctor.click("[data-action=rsStep][data-step='1']")
    doctor.wait_for_function(f"() => document.querySelector('#clinic img.studyimg').alt !== {first!r}")
    doctor.wait_for_selector("#clinic img.studyimg[src^='blob:']")
    doctor.click("[data-action=rsConfirm]")
    doctor.wait_for_selector("#clinic .c-path:has-text('Подтверждено')", timeout=20000)
    if not planned or planned not in doctor.inner_text("#clinic .c-dec"):
        failures.append(f"после подтверждения шаг не совпал с предпросмотром «{planned}»")
    patient.reload()
    patient.wait_for_selector("#view .mrow:has-text('Подтверждено врачом')", timeout=20000)
    patient.click("#view .mrow:has-text('Подтверждено врачом') >> nth=0")
    patient.wait_for_selector("#view .shot img.studyimg[src^='blob:']", timeout=20000)
    for word in ("оценка", "1.2.826"):
        if word in patient.inner_text("#view"):
            failures.append(f"пациенту видно «{word}»")
    if patient_errors or doctor_errors:
        failures.append("ошибки в консоли: " + "; ".join(patient_errors + doctor_errors))
    context.close()
    return failures


def check_rescan_visits(browser) -> list[str]:
    """rescan cabinet, «Приёмы»: the doctor keeps the screen open, the patient books in another window and the visit
    appears without a reload within 20 s; the doctor saves the outcome with a next step and the patient sees it."""
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    patient, doctor = context.new_page(), context.new_page()
    patient_errors, doctor_errors = watch(patient), watch(doctor)
    failures = []
    doctor.goto(APP + "/#/doctor/rsVisits")
    wait_ready(doctor)
    rows = "() => [...document.querySelectorAll('#clinic .c-tbl tbody tr[data-step]')].map(r => r.dataset.step)"
    before = doctor.evaluate(rows)
    patient.goto(APP + "/#/patient/rsBook")
    wait_ready(patient)
    if not book_on_phone(patient):
        context.close()
        return ["у пациента нет шага, на который можно записаться"]
    try:
        doctor.wait_for_function(f"() => ({rows})().some(s => !{before!r}.includes(s))", timeout=20000)
    except PlaywrightError:
        context.close()
        return ["запись пациента не появилась у врача за 20 секунд без обновления страницы"]
    step = next(s for s in doctor.evaluate(rows) if s not in before)
    row = f"#clinic .c-tbl tr[data-step='{step}']"
    if "Демо-пациент" not in doctor.inner_text(row):
        failures.append("в новой строке не пациент, который записался")
    doctor.click(f"{row} [data-action=rsOutcomeOpen]")
    doctor.wait_for_selector("#rsOutcome")
    doctor.fill("#rsOutSummary", "Осмотр проведён, назначен контроль.")
    for box in doctor.query_selector_all("#rsOutcome [data-step-of=rsOut]:checked"):
        box.uncheck()
    planned = "Контрольный приём терапевта, демо"
    doctor.fill("#rsOutCustom", planned)
    doctor.click("[data-action=rsOutcomeSave]")
    doctor.wait_for_selector("#rsOutcome", state="detached", timeout=20000)
    patient.goto(APP + "/#/patient/rsHome")
    wait_ready(patient)
    try:
        patient.wait_for_selector(f"#view:has-text('{planned}')", timeout=10000)
    except PlaywrightError:
        failures.append("после итога приёма у пациента нет нового шага")
    if patient_errors or doctor_errors:
        failures.append("ошибки в консоли: " + "; ".join(patient_errors + doctor_errors))
    context.close()
    return failures


def check_rescan_patients(browser) -> list[str]:
    """rescan cabinet, «Пациенты»: Мария К. (manual review) gets the doctor's plan from her card; an anamnesis entry
    added by the doctor is still in the card after a page reload."""
    import uuid
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = watch(page)
    failures = []
    maria = "#clinic tr[data-ref='demo-patient-2']"
    page.goto(APP + "/#/doctor/rsPatients")
    wait_ready(page)
    page.click(maria)
    page.wait_for_selector(f"{maria}.live")
    if "Врач уточняет план" not in page.inner_text(maria):
        failures.append("Мария К. не на ручном разборе: " + page.inner_text(maria).replace(chr(10), " "))
    page.click("[data-action=rsPlanOpen][data-mode=manual]")
    page.wait_for_selector("#rsPlan")
    if not page.query_selector("#rsPlan [data-step-of=rsPlan]:checked"):
        page.fill("#rsPlanCustom", "Дообследование по решению врача, демо")
    page.click("[data-action=rsPlanSave]")
    page.wait_for_selector("#rsPlan", state="detached", timeout=20000)
    try:
        page.wait_for_function(f"() => (document.querySelector(\"{maria}\")?.innerText || '').includes('В работе')", timeout=20000)
    except PlaywrightError:
        failures.append("после плана врача Мария К. не перешла в «В работе»")
    note = "Демо-запись анамнеза " + uuid.uuid4().hex[:8]
    page.fill("#rsAnText", note)
    page.click("[data-action=rsAnamnesisAdd]")
    page.wait_for_selector(f"#rsPatientCard:has-text('{note}')", timeout=20000)
    page.reload()
    wait_ready(page)
    page.click(maria)
    try:
        page.wait_for_selector(f"#rsPatientCard:has-text('{note}')", timeout=20000)
    except PlaywrightError:
        failures.append("запись в анамнез не видна после обновления страницы")
    if errors:
        failures.append("ошибки в консоли: " + "; ".join(errors))
    page.close()
    return failures


def check_referral(browser) -> list[str]:
    """Coordinator and partner windows side by side: the seeded referral of Олег Р. without a name until accepted,
    the partner's time, «услуга оказана», and the coordinator marks the visit."""
    from datetime import datetime, timedelta
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    staff, partner = context.new_page(), context.new_page()
    staff_errors, partner_errors = watch(staff), watch(partner)
    failures = []

    def open_case():  # the address does not keep the selected case: open it from the inbox again
        staff.goto(APP + "/#/staff/inbox")
        staff.reload()
        staff.wait_for_selector("tr:has-text('Олег') [data-case]")
        staff.click("tr:has-text('Олег') [data-case]")
        staff.wait_for_selector("#view:has-text('Где выполнить шаг')")
    open_case()
    text = staff.inner_text("#view")
    for word in ("Диагностический центр на Лесной", "у нас", "Ждёт ответа партнёра", "Учтено из карты"):
        if word not in text:
            failures.append(f"в карточке Олега Р. нет «{word}»")
    partner.goto(APP + "/#/partner/incoming?clinic=clinic-partner-1")
    partner.wait_for_selector("[data-action=partnerOpen]")
    partner.click("[data-action=partnerOpen] >> nth=0")
    partner.wait_for_selector("#view:has-text('ФИО и контакт откроются после принятия направления')")
    if "Романов" in partner.inner_text("#view") or "Олег" in partner.inner_text("#view"):
        failures.append("партнёр видит ФИО до принятия")
    if "Плохо слышит" in partner.inner_text("#view"):
        failures.append("партнёр видит запись «только для своей клиники»")
    partner.click("[data-action=partnerAct][data-act=accept]")
    partner.wait_for_selector("#view:has-text('Романов')")
    open_case()
    staff.wait_for_selector("[data-action=partnerTimeOpen]")
    staff.click("[data-action=partnerTimeOpen]")
    staff.fill("#ptTime", (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%dT10:00"))
    staff.click("[data-action=partnerTimeSave]")
    staff.wait_for_selector("[data-action=pathStaffAct][data-act=attend]")
    partner.click("[data-action=partnerAct][data-act=complete]")
    partner.wait_for_selector("#view .badge:has-text('Услуга оказана')")
    open_case()
    staff.wait_for_selector("#view:has-text('Партнёр сообщил: услуга оказана')")
    staff.click("[data-action=pathStaffAct][data-act=attend]")
    staff.wait_for_selector("#view:has-text('Ждём итог врача')")
    if staff.eval_on_selector("#role", "e => e.value") != "staff" or not partner.eval_on_selector("#role", "e => e.value").startswith("partner"):
        failures.append("окна координатора и партнёра смешали роли")
    if staff_errors or partner_errors:
        failures.append("ошибки в консоли: " + "; ".join(staff_errors + partner_errors))
    context.close()
    return failures


# ---------- Пилот rescan (задание 18): отдельная точка входа /assets/pilot/index.html, данные — моки FE1/FE2 ----------
PILOT = APP + "/assets/pilot/index.html"
PILOT_WIDTHS = (360, 390, 1280)
PILOT_PATIENT = [  # (адрес, что проверить сверх общего)
    ("#/p/demo-active", "entry"), ("#/p/demo-consent", "consent"),
    ("#/p/demo-expired", "closed"), ("#/p/demo-stopped", "closed"), ("#/p/demo-unsubscribed", "closed"),
    ("#/p/demo-step-discuss/step", "doctor_step"), ("#/p/demo-step-retest/step", "retest"),
    ("#/p/demo-step-followup/step", "doctor_step"), ("#/p/demo-active/step", "branches"),
    # без шага врача P3 возвращает на выбор ветки, поэтому цели проверяем у пациента с шагом врача
    ("#/p/demo-step-discuss/goal", "goals"), ("#/p/demo-active/next", "stub"),
    ("#/p/demo-clinic-a", "entry"), ("#/p/demo-clinic-b", "entry"),
]
PILOT_STAFF = ["#/staff/login", "#/doctor", "#/clinic"]
PILOT_BAD_LOGIN = "Логин или пароль не подошли. Проверьте и попробуйте ещё раз"
# Контраст --clinic-accent с белым: ниже 4,5:1 тема обязана подставить наш акцент (клиника B)
PILOT_CONTRAST = """() => {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--clinic-accent').trim();
  const probe = document.createElement('i'); probe.style.color = raw; document.body.append(probe);
  const rgb = (getComputedStyle(probe).color.match(/\\d+(\\.\\d+)?/g) || []).slice(0, 3).map(Number); probe.remove();
  if (!raw || rgb.length < 3) return null;
  const lin = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  const L = 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2]);
  return {accent: raw, ratio: 1.05 / (L + 0.05),
          name: getComputedStyle(document.documentElement).getPropertyValue('--clinic-name').trim()};
}"""
PILOT_CHOICES = ("() => document.querySelectorAll('#view button:not([disabled]), #view a[href], "
                 "#view input[type=radio], #view [role=radio]').length")
PILOT_FREE_INPUT = "#view textarea, #view [contenteditable], #view input:not([type=radio]):not([type=checkbox]):not([type=hidden])"


def pilot_open(page, address: str) -> str | None:
    """Открыть адрес пилота с нуля (полная загрузка, не смена hash); вернуть текст ошибки или None."""
    page.goto("about:blank")
    response = page.goto(PILOT + address)
    if response is None or response.status != 200:
        return f"страница пилота {PILOT} не открылась: {response.status if response else 'нет ответа'} (ждём FE1/FE2)"
    wait_ready(page)
    return None


def pilot_common(page, address: str, errors: list[str], before: int) -> list[str]:
    """Общее для каждого экрана пилота: консоль, CSP, плашка «демо», прокрутка на 360/390/1280."""
    failures = []
    csp = page.evaluate("() => window.__mmCsp.splice(0)")
    if len(errors) > before or csp:
        failures.append(f"{address}: {'; '.join(errors[before:] + csp)}")
    if "демо" not in page.inner_text("body").lower():
        failures.append(f"{address}: нет плашки «демо»")
    for width in PILOT_WIDTHS:
        page.set_viewport_size({"width": width, "height": 800})
        overflow = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        if overflow > 0:
            failures.append(f"{width}px {address}: шире экрана на {overflow}px")
    page.set_viewport_size({"width": 390, "height": 800})
    return failures


def pilot_patient_screen(page, address: str, kind: str) -> list[str]:
    failures = []
    text = page.inner_text("#view")
    if page.query_selector(PILOT_FREE_INPUT):
        failures.append(f"{address}: поле свободного ввода на экране пациента")
    if kind == "closed" and page.query_selector("#view button:has-text('Повторить')"):
        failures.append(f"{address}: кнопка «Повторить» у закрытой ссылки")
    if kind == "closed" and not any(ch.isdigit() for ch in text):
        failures.append(f"{address}: нет телефона клиники — что делать дальше")
    if kind in {"doctor_step", "retest"} and "Ваш врач предлагает" not in text:
        failures.append(f"{address}: нет «Ваш врач предлагает…»")
    if kind == "retest" and not any(ch.isdigit() for ch in text):
        failures.append(f"{address}: в пересдаче нет числа недель")
    if kind == "branches" and page.evaluate(PILOT_CHOICES) < 3:
        failures.append(f"{address}: меньше трёх веток")
    if kind == "goals" and page.evaluate(PILOT_CHOICES) < 4:
        failures.append(f"{address}: меньше четырёх целей")
    if kind == "consent" and page.evaluate(PILOT_CHOICES) < 1:
        failures.append(f"{address}: нет действия «согласен»")
    return failures


def pilot_theme(page, address: str, themes: dict) -> list[str]:
    theme = page.evaluate(PILOT_CONTRAST)
    if not theme:
        return [f"{address}: тема клиники не применена (--clinic-accent пуст)"]
    themes[address] = theme
    if theme["ratio"] < 4.5:
        return [f"{address}: акцент {theme['accent']} с белым {theme['ratio']:.2f}:1 — не подставлен наш"]
    return []


def check_pilot_patient(browser) -> list[str]:
    """P1 в четырёх состояниях и с согласием, P2 с тремя шагами врача и с ветками, P3 и заглушка «Дальше»;
    тема клиники: акцент на каждом экране проходит контраст 4,5:1, обе мок-клиники встречаются."""
    page = browser.new_page(viewport={"width": 390, "height": 800})
    errors = watch(page)
    failures, themes = [], {}
    for address, kind in PILOT_PATIENT:
        before = len(errors)
        try:
            problem = pilot_open(page, address)
            if problem:
                failures.append(problem)
                break
            failures += pilot_patient_screen(page, address, kind)
            failures += pilot_theme(page, address, themes)
            failures += pilot_common(page, address, errors, before)
        except PlaywrightError as exc:
            failures.append(f"{address}: {str(exc).splitlines()[0]}")
    if themes and len({t["name"] for t in themes.values()}) < 2:
        failures.append("все мок-токены пациента открывают одну клинику: клиники B с подставленным акцентом нет")
    page.close()
    return failures


def pilot_login(page, login: str, password: str) -> None:
    """Вход с клавиатуры: Enter в поле пароля, как требует FE1."""
    page.fill("#view input:not([type=password]):not([type=hidden]) >> nth=0", login)
    page.fill("#view input[type=password]", password)
    page.press("#view input[type=password]", "Enter")


def pilot_staff_login(page, errors: list[str]) -> list[str]:
    failures = []
    for login, target in (("demo-doctor", "#/doctor"), ("demo-manager", "#/clinic")):
        before = len(errors)
        pilot_open(page, "#/staff/login")
        pilot_login(page, login, "demo")
        try:
            page.wait_for_function(f"() => location.hash === '{target}'", timeout=8000)
            wait_ready(page)
        except PlaywrightError:
            failures.append(f"вход {login} открыл {page.evaluate('() => location.hash')}, ждали {target}")
            continue
        failures += pilot_common(page, f"{target} после входа {login}", errors, before)
    before = len(errors)
    pilot_open(page, "#/staff/login")
    pilot_login(page, "demo-nobody", "wrong")
    try:
        page.wait_for_selector(f"#view :text('{PILOT_BAD_LOGIN}')", timeout=8000)
    except PlaywrightError:
        failures.append("неверный логин: нет «" + PILOT_BAD_LOGIN + "»")
    if page.evaluate("() => location.hash") != "#/staff/login":
        failures.append("неверный логин увёл со страницы входа")
    failures += pilot_common(page, "#/staff/login, неверный логин", errors, before)
    return failures


def check_pilot_staff(browser) -> list[str]:
    """Заглушки входа, #/doctor и #/clinic; вход врача и руководителя на свои заглушки, неверный логин."""
    page = browser.new_page(viewport={"width": 390, "height": 800})
    errors = watch(page)
    failures = []
    try:
        for address in PILOT_STAFF:
            before = len(errors)
            problem = pilot_open(page, address)
            if problem:
                page.close()
                return [problem]
            failures += pilot_common(page, address, errors, before)
        failures += pilot_staff_login(page, errors)
        if page.evaluate("() => localStorage.length + sessionStorage.length"):
            failures.append("пилот пишет в хранилище браузера")
    except PlaywrightError as exc:
        failures.append(str(exc).splitlines()[0])
    page.close()
    return failures


# ---------- Пилот rescan (задание 19): P4–P8 и ошибки пациента на моках FE3/FE4 ----------
# Подготовка идёт кликами (проверяем экран, а не дорогу к нему); путь P1 → P6 — отдельно, только клавиатурой.
# Допущения о разметке: выбор врача на P4 — ссылка на #/p/<token>/request?doctor=<id> или кнопка внутри элемента
# с data-doctor / data-doctor-id; на P5 сначала группа радиокнопок форматов (value = id формата), потом окон.
PILOT_QA = r"""window.__qa = {
  doctors() {
    const view = document.querySelector('#view');
    if (!view) return [];
    const found = [...view.querySelectorAll("a[href*='/request'], [data-doctor], [data-doctor-id]")]
      .map(e => e.matches('a[href], button') ? e : e.querySelector('a[href], button')).filter(Boolean);
    return [...new Set(found)];
  },
  isDoctor() { return window.__qa.doctors().includes(document.activeElement); },
  focusVisible() {
    const shown = el => { if (!el) return false; const s = getComputedStyle(el);
      return (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== 'none'; };
    const e = document.activeElement;
    return shown(e) || shown(e && e.closest('label'));
  },
  red() {
    return [...document.querySelectorAll('#view *')].some(e => {
      if (!e.getClientRects().length) return false;
      const s = getComputedStyle(e);
      return [s.color, s.backgroundColor].some(c => {
        const m = (c.match(/[\d.]+/g) || []).map(Number);
        return m.length >= 3 && m[3] !== 0 && m[0] >= 180 && m[1] < 110 && m[2] < 110;
      });
    });
  },
  async mock(token, path) {
    try {
      const mocks = await import(new URL('js/mocks.js', location.href).href);
      const answer = mocks.respond('GET', path, undefined, {token});
      return answer && answer.data ? answer.data : null;
    } catch { return null; }
  }
};"""
PILOT_FLOW = ("", "/step", "/goal", "/doctors")
PILOT_REQUEST_TOKENS = ("demo-request-accepted", "demo-request-in-progress", "demo-request-booked", "demo-request-cancelled")
PILOT_RETEST_TOKENS = ("demo-retest-before", "demo-retest-today", "demo-retest-overdue")
PILOT_DATE = re.compile(r"\d{1,2}[\s ]+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)")
PILOT_PRICE = re.compile(r"от[\s  ]*\d[\d\s  ]*₽")
PILOT_EXCLAMATION = re.compile(r"[А-Яа-яЁё»)]\s*!")
PILOT_FORBIDDEN = re.compile(r"(?i)(?<![\w-])(расшифров|риск|срочн|отклонени|диагноз)")
PILOT_TEL = "#view a[href^='tel:']"
PILOT_HAVE_BOOKING = "У меня уже есть запись"  # кнопка P8, решение дизайнера
PILOT_NEW_REQUEST = "Оставить новую заявку"  # P6 в booked и cancelled → P3
KEY_SUBMIT = "() => { const e = document.activeElement; return !!e && !!e.closest('#view') && e.matches('button[type=submit]:not([disabled])'); }"
KEY_MAIN = "() => { const e = document.activeElement; return !!e && !!e.closest('#view') && e.matches('button.btn:not(.text):not([disabled])'); }"
KEY_RADIO = "n => { const e = document.activeElement; return !!e && !!e.closest('#view') && e.matches('input[type=radio]') && (!n || e.name !== n); }"
KEY_DOCTOR = "() => window.__qa.isDoctor()"
PICK_FIRST = """() => { const names = new Set();
  for (const r of document.querySelectorAll('#view input[type=radio]')) {
    if (names.has(r.name)) continue; names.add(r.name);
    if (!document.querySelector(`#view input[type=radio][name="${r.name}"]:checked`)) r.click(); } }"""


class PilotStop(Exception):
    """Дальше по сценарию идти нельзя: причина — в тексте."""


def pilot_page(browser):
    page = browser.new_page(viewport={"width": 390, "height": 800})
    errors = watch(page)
    page.add_init_script(PILOT_QA)
    return page, errors


def pilot_path(page) -> str:
    return page.evaluate("() => location.hash.split('?')[0]")


def pilot_wait(page, suffix: str) -> bool:
    try:
        page.wait_for_function("s => location.hash.split('?')[0].endsWith(s)", arg=suffix, timeout=8000)
        wait_ready(page)
        return True
    except PlaywrightError:
        return False


def pilot_button(page, text: str):
    return page.query_selector(f"#view :is(button, a):has-text('{text}')")


def pilot_advance(page) -> None:
    """Главное действие экрана с первым вариантом выбора (подготовка, не проверка)."""
    path = pilot_path(page)
    if path.endswith("/doctors"):
        if not page.evaluate("() => { const d = window.__qa.doctors(); if (d[0]) d[0].click(); return d.length; }"):
            raise PilotStop(f"{path}: нет ни одного врача для выбора")
    else:
        page.evaluate(PICK_FIRST)
        button = (page.query_selector("#view form button[type=submit]:not([disabled])")
                  or page.query_selector("#view button.btn:not(.text):not([disabled])"))
        if button is None:
            raise PilotStop(f"{path}: нет кнопки действия")
        button.click()
    page.wait_for_function("p => location.hash.split('?')[0] !== p", arg=path, timeout=8000)
    wait_ready(page)


def pilot_walk(page, token: str, target: str) -> None:
    """Открыть #/p/<token>/<target>; если экран вернул назад (согласие, ветка, цель) — пройти шаги до него."""
    problem = pilot_open(page, f"#/p/{token}/{target}")
    if problem:
        raise PilotStop(problem)
    for _ in range(6):
        path = pilot_path(page)
        if path.endswith("/" + target):
            return
        if path.removeprefix(f"#/p/{token}") not in PILOT_FLOW:
            raise PilotStop(f"до #/p/{token}/{target} не дошли: остановились на {path}")
        pilot_advance(page)
    raise PilotStop(f"до #/p/{token}/{target} не дошли за 6 шагов")


def pilot_calm(page, label: str, *, still: bool = True) -> list[str]:
    """Спокойный экран пациента: без красного, восклицаний, запрещённых слов, тикающих таймеров и полей ввода."""
    failures = []
    text = page.inner_text("#view")
    if page.evaluate("() => window.__qa.red()"):
        failures.append(f"{label}: красный на экране пациента")
    if PILOT_EXCLAMATION.search(text):
        failures.append(f"{label}: восклицание в тексте")
    if PILOT_FORBIDDEN.search(text):
        failures.append(f"{label}: запрещённое слово «{PILOT_FORBIDDEN.search(text).group(0)}»")
    if page.query_selector(PILOT_FREE_INPUT):
        failures.append(f"{label}: поле свободного ввода")
    if still:
        page.wait_for_timeout(1200)
        if page.inner_text("#view") != text:
            failures.append(f"{label}: текст меняется сам (таймер?)")
    return failures


def pilot_steps(page, errors: list[str], steps) -> list[str]:
    """Шаги (подпись, функция page → список проблем); после каждого — общее: консоль, CSP, «демо», ширины."""
    failures = []
    for label, step in steps:
        before = len(errors)
        try:
            failures += [f"{label}: {p}" for p in step(page)]
            failures += pilot_common(page, label, errors, before)
        except PilotStop as stop:
            failures.append(f"{label}: {stop}")
        except PlaywrightError as exc:
            failures.append(f"{label}: {str(exc).splitlines()[0]}")
    if page.evaluate("() => localStorage.length + sessionStorage.length"):
        failures.append("пилот пишет в хранилище браузера")
    return failures


# --- P4–P6 (FE3) ---

def p4_doctors(page) -> list[str]:
    pilot_walk(page, "demo-step-discuss", "doctors")
    failures = pilot_calm(page, "P4", still=False)
    count = page.evaluate("() => window.__qa.doctors().length")
    if count < 3:
        failures.append(f"врачей {count}, ждали минимум три (ordering, visited, без метки)")
    text = page.inner_text("#view")
    mock = page.evaluate("t => window.__qa.mock(t, '/patient/doctors')", "demo-step-discuss")
    names = [d["name"] for d in (mock or {}).get("doctors", [])]
    places = [text.find(name) for name in names]
    if names and (-1 in places or places != sorted(places)):
        failures.append("порядок карточек не как в ответе GET /patient/doctors")
    if not PILOT_PRICE.search(text):
        failures.append("нет цены «от N ₽»")
    if page.evaluate("() => [...document.querySelectorAll('#view img')].some(i => new URL(i.src, location.href).origin !== location.origin)"):
        failures.append("фото врача не с того же источника")
    return failures


def p4_empty(page) -> list[str]:
    pilot_walk(page, "demo-no-doctors", "doctors")
    failures = pilot_calm(page, "P4 пусто", still=False)
    if page.evaluate("() => window.__qa.doctors().length"):
        failures.append("пустой список, а карточки врачей есть")
    if not page.query_selector(PILOT_TEL):
        failures.append("пустой список без кнопки звонка в клинику")
    return failures


def p5_request(page) -> list[str]:
    pilot_walk(page, "demo-step-discuss", "doctors")
    pilot_advance(page)
    if not pilot_path(page).endswith("/request"):
        raise PilotStop(f"выбор врача открыл {pilot_path(page)}, ждали /request")
    failures = pilot_calm(page, "P5", still=False)
    groups = page.evaluate("() => new Set([...document.querySelectorAll('#view input[type=radio]')].map(r => r.name)).size")
    if groups < 2:
        failures.append(f"групп выбора {groups}, ждали формат и окно времени")
    text = page.inner_text("#view")
    if "₽" not in text:
        failures.append("у форматов нет цены")
    if "администратор" not in text.lower():
        failures.append("нет подписи, что запись подтвердит администратор клиники")
    if not page.query_selector("#view button[type=submit]"):
        failures.append("нет кнопки «Оставить заявку»")
    return failures


def p5_payment(page) -> list[str]:
    pilot_walk(page, "demo-paid-format", "doctors")
    pilot_advance(page)
    formats = page.evaluate("t => window.__qa.mock(t, '/patient/formats')", "demo-paid-format") or {}
    paid = [f["id"] for f in formats.get("formats", []) if f.get("has_payment")]
    page.evaluate(PICK_FIRST)
    radio = paid and page.query_selector(f"#view input[type=radio][value='{paid[0]}']")
    if radio:
        radio.check()
    page.click("#view button[type=submit]")
    try:
        link = page.wait_for_selector("#view a[target='_blank']", timeout=8000)
    except PlaywrightError:
        return [f"после заявки с оплатой нет ссылки «Оплатить на сайте клиники» (открыт {pilot_path(page)})"]
    href, rel = link.get_attribute("href") or "", (link.get_attribute("rel") or "").split()
    failures = [] if href.startswith("https://") else [f"ссылка оплаты не https: {href[:40]}"]
    if not {"noopener", "noreferrer"} <= set(rel):
        failures.append(f"у ссылки оплаты rel={' '.join(rel)!r}, ждали noopener noreferrer")
    return failures


def p6_statuses(page) -> list[str]:
    failures, texts = [], set()
    for token in PILOT_REQUEST_TOKENS:
        problem = pilot_open(page, f"#/p/{token}/status")
        if problem or not pilot_path(page).endswith("/status"):
            failures.append(f"{token}: P6 не открылся ({problem or pilot_path(page)})")
            continue
        failures += pilot_calm(page, token)
        if not page.query_selector(PILOT_TEL):
            failures.append(f"{token}: нет кнопки звонка в клинику")
        texts.add(page.inner_text("#view"))
        final = token in {"demo-request-booked", "demo-request-cancelled"}
        again = pilot_button(page, PILOT_NEW_REQUEST)
        if final and again is None:
            failures.append(f"{token}: нет кнопки «{PILOT_NEW_REQUEST}»")
        elif final:
            again.click()
            if not pilot_wait(page, "/goal"):
                failures.append(f"{token}: «{PILOT_NEW_REQUEST}» открыл {pilot_path(page)}, ждали P3")
        elif again is not None:
            failures.append(f"{token}: заявка ещё в работе, а кнопка «{PILOT_NEW_REQUEST}» есть")
    if len(texts) < len(PILOT_REQUEST_TOKENS):
        failures.append("четыре статуса заявки показывают одинаковый текст")
    return failures


def p6_redirects(page) -> list[str]:
    """P1 и P4 ведут на P6 только при заявке accepted и in_progress."""
    failures = []
    for token in ("demo-request-accepted", "demo-request-in-progress"):
        pilot_open(page, f"#/p/{token}/doctors")
        if not pilot_wait(page, "/status"):
            failures.append(f"{token}: P4 открыл {pilot_path(page)}, ждали P6")
        pilot_open(page, f"#/p/{token}")
        page.click("#view form button[type=submit]")
        if not pilot_wait(page, "/status"):
            failures.append(f"{token}: P1 после входа открыл {pilot_path(page)}, ждали P6")
    for token in ("demo-request-booked", "demo-request-cancelled"):
        pilot_open(page, f"#/p/{token}")
        page.click("#view form button[type=submit]")
        page.wait_for_timeout(600)
        wait_ready(page)
        if pilot_path(page).endswith("/status"):
            failures.append(f"{token}: P1 увёл на P6, а заявка завершена")
    return failures


def check_pilot_booking(browser) -> list[str]:
    """P4 (врачи, пусто), P5 (формат и окно, оплата), P6 в четырёх статусах, переходы на P6 при заявке."""
    page, errors = pilot_page(browser)
    failures = pilot_steps(page, errors, [
        ("P4 врачи, demo-step-discuss", p4_doctors), ("P4 пусто, demo-no-doctors", p4_empty),
        ("P5 заявка, demo-step-discuss", p5_request), ("P5 оплата, demo-paid-format", p5_payment),
        ("P6 статусы demo-request-*", p6_statuses), ("P1 и P4 при заявке ведут на P6", p6_redirects)])
    page.close()
    return failures


# --- P7, P8 и ошибки (FE4) ---

def pilot_book_button(page, label: str) -> list[str]:
    button = pilot_button(page, "Записаться")
    if button is None:
        return [f"{label}: нет кнопки «Записаться»"]
    button.click()
    return [] if pilot_wait(page, "/goal") else [f"{label}: «Записаться» открыл {pilot_path(page)}, ждали P3"]


def p7_retest(page) -> list[str]:
    failures, texts = [], set()
    for token in PILOT_RETEST_TOKENS:
        problem = pilot_open(page, f"#/p/{token}/retest")
        if token == "demo-retest-before" and "Ссылка не найдена" in page.inner_text("#view"):
            token = "demo-step-retest"  # контракт: «demo-retest-before (можно расширить demo-step-retest)»
            problem = pilot_open(page, f"#/p/{token}/retest")
        if problem or not pilot_path(page).endswith("/retest"):
            failures.append(f"{token}: P7 не открылся ({problem or pilot_path(page)})")
            continue
        text = page.inner_text("#view")
        texts.add(text)
        # p4-p8.md: дата — в заголовке «до» и в тексте «просрочено»; у «сегодня» её нет по тексту дизайнера
        if token != "demo-retest-today" and not PILOT_DATE.search(text):
            failures.append(f"{token}: нет даты пересдачи вида «17 ноября»")
        failures += pilot_calm(page, token)
        failures += pilot_book_button(page, token)
    if len(texts) < len(PILOT_RETEST_TOKENS):
        failures.append("состояния before, today и overdue показывают одинаковый текст")
    return failures


def p2_to_retest(page) -> list[str]:
    pilot_open(page, "#/p/demo-step-retest/step")
    button = pilot_button(page, "Когда пересдавать")
    if button is None:
        return ["у P2 с пересдачей нет кнопки «Когда пересдавать»"]
    button.click()
    return [] if pilot_wait(page, "/retest") else [f"«Когда пересдавать» открыл {pilot_path(page)}, ждали P7"]


def p8_after(page) -> list[str]:
    pilot_open(page, "#/p/demo-after-visit/after")
    failures = pilot_calm(page, "P8")
    if "демо" not in page.inner_text("#view").lower():
        failures.append("на экране P8 нет пометки «демо»")
    booked = pilot_button(page, PILOT_HAVE_BOOKING)
    if booked is None:
        failures.append(f"нет кнопки «{PILOT_HAVE_BOOKING}»")
    else:
        booked.click()
        try:
            page.wait_for_selector("#view :text('Хорошо, напоминать не будем')", timeout=8000)
        except PlaywrightError:
            failures.append(f"после «{PILOT_HAVE_BOOKING}» нет «Хорошо, напоминать не будем»")
    pilot_open(page, "#/p/demo-after-visit/after")
    return failures + pilot_book_button(page, "P8")


def p8_booked(page) -> list[str]:
    pilot_open(page, "#/p/demo-after-booked/after")
    failures = pilot_calm(page, "P8 записан")
    if pilot_button(page, PILOT_HAVE_BOOKING):
        failures.append(f"пациент уже записан, а кнопка «{PILOT_HAVE_BOOKING}» осталась")
    return failures


def error_screen(token: str, expected: str, retry: bool):
    def step(page) -> list[str]:
        pilot_open(page, f"#/p/{token}")
        text = page.inner_text("#view")
        failures = [] if expected in text else [f"нет «{expected}»"]
        failures += pilot_calm(page, token, still=False)
        has_retry = pilot_button(page, "Повторить") is not None
        if has_retry != retry:
            failures.append("нет кнопки «Повторить»" if retry else "лишняя кнопка «Повторить»")
        if retry and has_retry:
            pilot_button(page, "Повторить").click()
            page.wait_for_timeout(600)
            wait_ready(page)
            if expected not in page.inner_text("#view"):
                failures.append(f"после «Повторить» пропало «{expected}»")
        return failures
    return step


def error_redirect(address: str, suffix: str):
    def step(page) -> list[str]:
        pilot_open(page, address)
        return [] if pilot_wait(page, suffix) else [f"открылся {pilot_path(page)}, ждали …{suffix}"]
    return step


def check_pilot_care(browser) -> list[str]:
    """P7 в трёх состояниях и переход с P2, P8 (обе ветки), каждая ошибка пациента из таблицы контракта."""
    page, errors = pilot_page(browser)
    failures = pilot_steps(page, errors, [
        ("P7 пересдача", p7_retest), ("P2 → P7", p2_to_retest),
        ("P8 после визита", p8_after), ("P8 уже записан", p8_booked),
        ("404 link_not_found", error_screen("demo-unknown-link", "Ссылка не найдена", False)),
        ("503 not_configured", error_screen("demo-not-configured", "ещё не настроена", False)),
        ("сеть", error_screen("demo-error-network", "Нет связи", True)),
        ("500", error_screen("demo-error-500", "", True)),
        ("409 consent_required → P1", error_redirect("#/p/demo-consent/doctors", "/p/demo-consent")),
        ("409 choice_required → P3", error_redirect("#/p/demo-step-discuss/doctors", "/goal")),
        ("409 not_active → P1", error_redirect("#/p/demo-expired/doctors", "/p/demo-expired"))])
    page.close()
    return failures


# --- путь P1 → P6 с клавиатуры ---

def press_to(page, predicate: str, arg=None, limit: int = 40) -> bool:
    for _ in range(limit):
        page.keyboard.press("Tab")
        if page.evaluate(predicate, arg):
            return True
    return False


def key_act(page, predicate: str, what: str, key: str = "Enter", arg=None) -> list[str]:
    if not press_to(page, predicate, arg):
        raise PilotStop(f"{what}: не дойти клавишей Tab")
    seen = page.evaluate("() => window.__qa.focusVisible()")
    # Метка старого экрана: адрес меняется раньше, чем роутер перерисует #view
    page.evaluate("() => document.querySelector('#view').firstElementChild?.setAttribute('data-qa-old', '')")
    page.keyboard.press(key)
    return [] if seen else [f"{what}: фокус не виден"]


def key_wait(page, suffix: str, what: str) -> None:
    if not pilot_wait(page, suffix):
        raise PilotStop(f"{what} открыл {pilot_path(page)}, ждали …{suffix}")
    try:
        page.wait_for_function("() => !document.querySelector('#view [data-qa-old]')", timeout=8000)
        wait_ready(page)
    except PlaywrightError:
        raise PilotStop(f"{what}: экран {pilot_path(page)} не перерисовался") from None


def key_request(page, token: str) -> list[str]:
    """P5: формат без оплаты стрелками, окно, «Оставить заявку»."""
    if not press_to(page, KEY_RADIO):
        raise PilotStop("P5 формат: не дойти клавишей Tab")
    formats = page.evaluate("t => window.__qa.mock(t, '/patient/formats')", token) or {}
    paid = {f["id"] for f in formats.get("formats", []) if f.get("has_payment")}
    group = page.evaluate("() => document.activeElement.name")
    for _ in range(10):
        if page.evaluate("() => document.activeElement.value") not in paid:
            break
        page.keyboard.press("ArrowDown")
    failures = [] if page.evaluate("() => window.__qa.focusVisible()") else ["P5 формат: фокус не виден"]
    page.keyboard.press("Space")
    failures += key_act(page, KEY_RADIO, "P5 окно", "Space", arg=group)
    return failures + key_act(page, KEY_SUBMIT, "P5 «Оставить заявку»")


def key_path(page, token: str) -> list[str]:
    problem = pilot_open(page, f"#/p/{token}")
    if problem:
        raise PilotStop(problem)
    failures = key_act(page, KEY_SUBMIT, "P1")
    key_wait(page, "/step", "P1")
    if page.query_selector("#view input[type=radio]"):
        failures += key_act(page, KEY_RADIO, "P2 ветка", "Space") + key_act(page, KEY_SUBMIT, "P2")
    else:
        failures += key_act(page, KEY_MAIN, "P2")
    key_wait(page, "/goal", "P2")
    failures += key_act(page, KEY_RADIO, "P3 цель", "Space") + key_act(page, KEY_SUBMIT, "P3")
    key_wait(page, "/doctors", "P3")
    failures += key_act(page, KEY_DOCTOR, "P4 врач")
    key_wait(page, "/request", "P4")
    request_hash = page.evaluate("() => location.hash")
    failures += key_request(page, token)
    key_wait(page, "/status", "P5")
    if not page.query_selector(PILOT_TEL):
        failures.append("P6: нет кнопки звонка в клинику")
    return failures + key_repeat(page, request_hash)


def key_repeat(page, request_hash: str) -> list[str]:
    """Повторная заявка того же эпизода (409 request_exists) приводит на P6."""
    page.evaluate("h => { location.hash = h; }", request_hash)
    page.wait_for_timeout(400)
    wait_ready(page)
    if pilot_path(page).endswith("/request"):
        page.evaluate(PICK_FIRST)
        page.click("#view button[type=submit]")
    return [] if pilot_wait(page, "/status") else [f"повторная заявка: открыт {pilot_path(page)}, ждали P6 (request_exists)"]


def check_pilot_keyboard(browser) -> list[str]:
    """Путь P1 → P6 только с клавиатуры (Tab, пробел, стрелки, Enter), видимый фокус; повторная заявка → P6."""
    page, errors = pilot_page(browser)
    failures = pilot_steps(page, errors, [(f"клавиатура, {token}", lambda p, t=token: key_path(p, t))
                                          for token in ("demo-step-discuss", "demo-active")])
    page.close()
    return failures


def masked(image: Image.Image, boxes: list[tuple[int, int, int, int]]) -> Image.Image:
    image = image.convert("RGB")
    draw = ImageDraw.Draw(image)
    for box in boxes:
        draw.rectangle(box, fill=(0, 0, 0))
    return image


def boxes_of(page) -> list[tuple[int, int, int, int]]:
    result = []
    for selector in MASKS:
        for box in page.eval_on_selector_all(selector, "els => els.map(e => { const r = e.getBoundingClientRect(); "
                                                       "return [r.left, r.top + scrollY, r.right, r.bottom + scrollY]; })"):
            result.append(tuple(int(round(v)) for v in box))
    return result


def check_compare(browser, out: Path) -> tuple[list[str], float]:
    out.mkdir(parents=True, exist_ok=True)
    proto = browser.new_page(viewport={"width": 1280, "height": 900})
    product = browser.new_page(viewport={"width": 1280, "height": 900})
    proto.goto(PROTOTYPE.as_uri())
    product.goto(APP + "/")
    wait_ready(product)
    failures, worst = [], 0.0
    for role, name in COMPARE:
        proto.evaluate("([role, name]) => { state.role = role; go(name); }", [role, name])
        open_screen(product, role, name)
        product.evaluate("() => window.scrollTo(0, 0)")
        a_path, b_path = out / f"{role}-{name}-prototype.png", out / f"{role}-{name}-product.png"
        proto.screenshot(path=str(a_path), full_page=True)
        product.screenshot(path=str(b_path), full_page=True)
        boxes = boxes_of(proto) + boxes_of(product)
        a, b = masked(Image.open(a_path), boxes), masked(Image.open(b_path), boxes)
        if a.size != b.size:
            failures.append(f"{role}/{name}: снимок продукта {b.size}, прототипа {a.size}")
            continue
        diff = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v else 0)
        share = diff.histogram()[255] / (a.size[0] * a.size[1])
        worst = max(worst, share)
        if share > MAX_DIFF:
            diff.save(out / f"{role}-{name}-diff.png")
            failures.append(f"{role}/{name}: расхождение {share:.2%}")
    proto.close()
    product.close()
    return failures, worst


def main() -> int:
    utf8_console()
    if sync_playwright is None:
        print("[!!] Playwright не установлен: python -m pip install playwright && python -m playwright install chromium", flush=True)
        return 2
    out = Path(env("DEMO_STATE_DIR")) / "web-check"
    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            checks = [("Все экраны во всех ролях без ошибок консоли и CSP; адрес переживает обновление, «назад» и переходы с карты сервисов", check_screens),
                      ("Нет горизонтальной прокрутки при 390, 820, 1280 и 1680 px", check_widths),
                      ("Кабинет rescan, «Сегодня» на чистом стенде: Игорь С. в «Новых», Мария К. и Сергей Т. в «Требуют внимания», Елена П. в «Приёмах»", check_rescan_today),
                      ("Сквозной сценарий: запись → итог врача и рецепт → второй этап → бронь в аптеке", check_scenario),
                      ("Два окна с разными ролями не мешают друг другу", check_two_windows),
                      ("Кабинет rescan, «Исследования»: предпросмотр по правилу, настоящие срезы, подтверждение, цепочка маршрута", check_rescan_imaging),
                      ("Кабинет rescan, «Приёмы»: запись пациента появляется у врача за 20 с без обновления, итог создаёт следующий шаг", check_rescan_visits),
                      ("Кабинет rescan, «Пациенты»: Мария К. получает план врача, запись в анамнез видна после обновления", check_rescan_patients),
                      ("Направление: координатор и партнёр в соседних окнах, ФИО после принятия, время партнёра, визит", check_referral),
                      ("Пилот rescan, пациент: P1 в четырёх состояниях и с согласием, P2 и P3, тема клиники B, 360/390/1280 px", check_pilot_patient),
                      ("Пилот rescan, сотрудники: вход врача и руководителя, неверный логин, 360/390/1280 px", check_pilot_staff),
                      ("Пилот rescan, P4–P6: врачи, пусто, заявка, оплата, четыре статуса, переходы на P6, 360/390/1280 px", check_pilot_booking),
                      ("Пилот rescan, P7–P8 и ошибки пациента: три состояния пересдачи, после визита, 404/503/сеть/500/409, 360/390/1280 px", check_pilot_care),
                      ("Пилот rescan, путь P1 → P6 с клавиатуры, видимый фокус, повторная заявка → P6", check_pilot_keyboard)]
            for title, check in checks:
                failures = check(browser)
                results.append(not failures)
                say(not failures, title + ("" if not failures else ": " + " | ".join(failures[:8])))
            failures, worst = check_compare(browser, out)
            results.append(not failures)
            say(not failures, f"Сравнение с прототипом при 1280 px: {len(COMPARE)} экранов, максимальное расхождение {worst:.3%}"
                + ("" if not failures else ": " + " | ".join(failures)))
            browser.close()
    except PlaywrightError as exc:
        say(False, f"проверка в браузере прервана: {exc}")
        return 1
    print("Намеренные отличия от прототипа: " + "; ".join(INTENTIONAL), flush=True)
    print(f"Снимки: {out}", flush=True)
    passed = sum(results)
    print(f"Проверка в браузере: {passed} из {len(results)}.", flush=True)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
