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
]
WIDTHS = (390, 820, 1280, 1680)
MAX_DIFF = 0.01

# Pixel comparison with the prototype. A screen leaves this list when it moves to service data (tasks 04-07).
COMPARE = [s for s in SCREENS if s[1] not in {"services", "home", "plan", "appointments", "inbox", "case", "scheduling",
                                             "imaging", "reading", "study", "review"}]
# Intentional differences. Masked areas are painted over in both screenshots before comparing.
MASKS = [".brand small"]  # sidebar subtitle: «Демо-стенд» instead of «Прототип · версия 2»
INTENTIONAL = [
    "подпись под названием в боковой панели: «Демо-стенд» (маска .brand small)",
    "«Карта сервисов»: строки состояния сервисов и пометки «демо-модуль» (экран не сравнивается)",
    "имена из сессии: в журнале и новых записях вместо текста прототипа (на стартовых экранах совпадают)",
    "экраны снимков и создания маршрута: действия выключены до заданий 05 и 07, поэтому их не сравниваем",
]
CSP_PROBE = ("window.__mmCsp = [];"
             "document.addEventListener('securitypolicyviolation', e => window.__mmCsp.push(e.violatedDirective + ' ' + e.blockedURI));")


def say(ok: bool, text: str) -> None:
    print(("[ок] " if ok else "[!!] ") + text, flush=True)


def wait_ready(page) -> None:
    page.wait_for_function("() => document.querySelector('#view').children.length && !document.querySelector('.card.skeleton')",
                           timeout=8000)


def open_screen(page, role: str, name: str) -> None:
    page.evaluate(f"location.hash = '#/{role}/{name}'")
    page.wait_for_function(f"() => location.hash === '#/{role}/{name}' && document.querySelector('#role').value === '{role}'",
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
                      ("Два окна с разными ролями не мешают друг другу", check_two_windows)]
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
