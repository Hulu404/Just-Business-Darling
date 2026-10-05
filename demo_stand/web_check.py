"""Browser checks of the web app on a running stand (Playwright). Run via `python start.py --web-check`."""
from __future__ import annotations

import sys
from pathlib import Path

from stand_api import env, utf8_console

try:
    from playwright.sync_api import Error as PlaywrightError, sync_playwright
except ImportError:  # pragma: no cover - depends on the machine
    sync_playwright = None
from PIL import Image, ImageChops, ImageDraw

APP = "http://127.0.0.1:8763"
PROTOTYPE = Path(__file__).resolve().parents[1] / "prototype" / "medmarshrut_product_prototype_v2.html"

# 23 screens of the prototype, each in a role that has it in the menu (or reaches it from there).
SCREENS = [
    ("patient", "home"), ("patient", "intake"), ("patient", "review"), ("patient", "result"), ("patient", "plan"),
    ("patient", "imaging"), ("patient", "appointments"), ("patient", "messages"), ("patient", "pharmacy"),
    ("patient", "documents"),
    ("staff", "inbox"), ("staff", "case"), ("staff", "scheduling"), ("staff", "requests"), ("staff", "comms"),
    ("staff", "partners"), ("staff", "pharmacyAdmin"), ("staff", "rules"), ("staff", "analytics"),
    ("doctor", "reading"), ("doctor", "study"), ("doctor", "doctor"), ("doctor", "requests"), ("doctor", "inbox"),
    ("patient", "services"), ("staff", "services"), ("doctor", "services"),
    ("partner", "incoming"), ("partner", "services"),
    # rescan doctor cabinet (task 12): opened by address until the switch-over cycle
    ("doctor", "rsToday"), ("doctor", "rsStudies"), ("doctor", "rsPatients"), ("doctor", "rsVisits"), ("doctor", "rsSettings"),
]
WIDTHS = (390, 820, 1280, 1680)
MAX_DIFF = 0.01

# Pixel comparison with the prototype. A screen leaves this list when it moves to service data (tasks 04-07).
COMPARE = [s for s in SCREENS if s[1] not in {"services", "home", "plan", "appointments", "inbox", "case", "scheduling",
                                             "imaging", "reading", "study", "review", "rules", "analytics", "doctor",
                                             "partners", "documents", "incoming",
                                             "rsToday", "rsStudies", "rsPatients", "rsVisits", "rsSettings"}]
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
    if not page.url.endswith("#/patient/home"):
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
    # jumps from «Карта сервисов» open the right role and screen
    for target, expected, title in (("staff:partners:refs", "#/staff/partners", "Партнёры"),
                                    ("doctor:reading", "#/doctor/reading", "Что на снимке")):
        open_screen(page, "patient", "services")
        page.click(f'[data-jump="{target}"] >> nth=0')
        wait_ready(page)
        if page.evaluate("() => location.hash") != expected or page.inner_text("#topbar strong") != title:
            failures.append(f"переход {target} открыл {page.evaluate('() => location.hash')}")
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


def check_scenario(browser) -> list[str]:
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = watch(page)
    page.goto(APP + "/#/patient/plan")
    wait_ready(page)
    page.click('[data-action=pathChoose] >> nth=0')
    page.wait_for_function("() => location.hash === '#/patient/appointments'")
    page.wait_for_selector("[data-action=pathBook]")
    page.click("[data-action=pathBook] >> nth=0")
    page.wait_for_selector(".note:has-text('Вы записаны')")
    failures = []
    page.select_option("#role", "staff")
    page.wait_for_function("() => location.hash === '#/staff/inbox'")
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
    patient.goto(APP + "/#/patient/plan")
    staff.goto(APP + "/#/staff/inbox")
    wait_ready(patient)
    wait_ready(staff)
    patient.reload()
    staff.reload()
    wait_ready(patient)
    wait_ready(staff)
    failures = []
    for page, role, badge in ((patient, "patient", "Пациент"), (staff, "staff", "Клиника")):
        if page.eval_on_selector("#role", "e => e.value") != role or badge not in page.inner_text("#topbar"):
            failures.append(f"окно {role} показывает чужую роль")
        session = page.evaluate("role => fetch('/api/session', {headers:{'X-MM-Role':role}}).then(r => r.json())", role)
        if session.get("role") != role:
            failures.append(f"окно {role}: сессия {session}")
    open_screen(patient, "patient", "imaging")
    staff.click("[data-nav=requests]")
    wait_ready(staff)
    if staff.eval_on_selector("#role", "e => e.value") != "staff" or patient.eval_on_selector("#role", "e => e.value") != "patient":
        failures.append("действия в одном окне поменяли роль в другом")
    context.close()
    return failures


def check_imaging(browser) -> list[str]:
    """Patient uploads a kit CT as a file, the doctor confirms it on real slices, the patient sees the result."""
    archive = Path(env("DEMO_STATE_DIR")) / "kit" / "upload-ct-nodule.zip"
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    patient, doctor = context.new_page(), context.new_page()
    patient_errors, doctor_errors = watch(patient), watch(doctor)
    failures = []
    patient.goto(APP + "/#/patient/imaging")
    wait_ready(patient)
    patient.click("[data-action=uploadOpen]")
    if "Рентгенография" not in patient.inner_text("#upKind"):
        failures.append("в окне загрузки нет рентгенографии")
    patient.click("[data-action=uploadKit]")
    patient.wait_for_selector("[data-action=uploadKitSend]")
    patient.set_input_files("#upFile", str(archive))
    patient.select_option("#upKind", "ct_general")
    patient.check("#upConsent")
    patient.click("[data-action=upload]")
    patient.wait_for_selector("#view .panel:has-text('Ждёт врача')", timeout=70000)
    doctor.goto(APP + "/#/doctor/reading")
    doctor.wait_for_selector("[data-action=studyOpen]")
    doctor.click("[data-action=studyOpen] >> nth=0")
    doctor.wait_for_selector("img.studyimg[src^='blob:']")
    if "Демо-сценарий: признак задан заранее" not in doctor.inner_text("#view"):
        failures.append("нет плашки демо-сценария")
    if "Оценка модели" in doctor.inner_text("#view"):
        failures.append("в демо-сценарии видна оценка модели")
    if doctor.query_selector("[data-action=studyRewrite]"):
        failures.append("без ключа API у врача видна кнопка ИИ-помощника")
    doctor.click("[data-action=studyStep][data-step='1']")
    doctor.wait_for_selector("img.studyimg[src^='blob:']")
    doctor.click("[data-action=studyConfirm]")
    doctor.wait_for_selector("#view:has-text('Шаг по правилу')", timeout=20000)
    patient.reload()
    patient.wait_for_selector("#view .panel:has-text('Подтверждено врачом') img.studyimg[src^='blob:']", timeout=20000)
    text = patient.inner_text("#view")
    for word in ("оценка", "0.0", "1.2.826"):
        if word in text:
            failures.append(f"пациенту видно «{word}»")
    if not patient.query_selector("[data-action=pathChoose]"):
        failures.append("у пациента нет кнопки записи")
    if patient.query_selector("[data-action=studyExplain]") or "ИИ-помощник" in text:
        failures.append("без ключа API у пациента видна кнопка ИИ-помощника")
    if patient_errors or doctor_errors:
        failures.append("ошибки в консоли: " + "; ".join(patient_errors + doctor_errors))
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
    patient.goto(APP + "/#/patient/imaging")
    wait_ready(patient)
    patient.click("[data-action=uploadOpen]")
    patient.set_input_files("#upFile", str(archive))
    patient.select_option("#upKind", "ct_general")
    patient.check("#upConsent")
    patient.click("[data-action=upload]")
    patient.wait_for_selector("#view .panel:has-text('Ждёт врача')", timeout=70000)
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
    patient.wait_for_selector("#view .panel:has-text('Подтверждено врачом') img.studyimg[src^='blob:']", timeout=20000)
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
    patient.goto(APP + "/#/patient/plan")
    wait_ready(patient)
    if not patient.query_selector("[data-action=pathChoose]"):
        context.close()
        return ["у пациента нет шага, на который можно записаться"]
    patient.click("[data-action=pathChoose] >> nth=0")
    patient.wait_for_selector("[data-action=pathBook]")
    patient.click("[data-action=pathBook] >> nth=0")
    patient.wait_for_selector(".note:has-text('Вы записаны')")
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
    for box in doctor.query_selector_all("#rsOutcome [data-rs-step]:checked"):
        box.uncheck()
    planned = "Контрольный приём терапевта, демо"
    doctor.fill("#rsOutCustom", planned)
    doctor.click("[data-action=rsOutcomeSave]")
    doctor.wait_for_selector("#rsOutcome", state="detached", timeout=20000)
    patient.goto(APP + "/#/patient/plan")
    wait_ready(patient)
    try:
        patient.wait_for_selector(f"#view:has-text('{planned}')", timeout=10000)
    except PlaywrightError:
        failures.append("после итога приёма у пациента нет нового шага")
    if patient_errors or doctor_errors:
        failures.append("ошибки в консоли: " + "; ".join(patient_errors + doctor_errors))
    context.close()
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
                      ("Сквозной сценарий: запись → итог врача и рецепт → второй этап → бронь в аптеке", check_scenario),
                      ("Два окна с разными ролями не мешают друг другу", check_two_windows),
                      ("Снимок: пациент загружает ZIP, врач подтверждает на настоящих срезах, пациент видит заключение и запись", check_imaging),
                      ("Кабинет rescan, «Исследования»: предпросмотр по правилу, настоящие срезы, подтверждение, цепочка маршрута", check_rescan_imaging),
                      ("Кабинет rescan, «Приёмы»: запись пациента появляется у врача за 20 с без обновления, итог создаёт следующий шаг", check_rescan_visits),
                      ("Направление: координатор и партнёр в соседних окнах, ФИО после принятия, время партнёра, визит", check_referral)]
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
