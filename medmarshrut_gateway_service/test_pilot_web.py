"""Проверки страниц пилота rescan (`web/pilot/`) без браузера: задания 18 и 19, раздел «Тестировщик», п. 2.

Читают каждый текстовый файл пилота. Пока папки нет, каждый тест падает с сообщением «нет web/pilot»:
пустой проход ничего бы не доказал. Задание 19 добавляет экраны P4–P8 и ошибки пациента (FE3, FE4):
те же правила плюс проверки из «Контракта фронтенда».
"""
import re
import unittest
from pathlib import Path

PILOT = Path(__file__).resolve().parent / "web" / "pilot"
TEXT_SUFFIXES = {".html", ".css", ".js", ".svg"}

# Тексты для пациента: экраны P1–P3, их стили, мок-данные (раздел PATIENT с текстами «настроек клиники»)
# и общая разметка. Слова — основы, чтобы ловить падежи: «диагноза», «срочная», «отклонений».
FORBIDDEN = re.compile(r"(?i)(?<![\w-])(расшифров|риск|срочн|отклонени|диагноз)")
# Поле свободного ввода — всё, кроме выбора из готовых вариантов
FREE_INPUT_TYPES = {"", "text", "search", "email", "tel", "url", "number", "password"}
INPUT_TAG = re.compile(r"""<input\b([^>]*)>""", re.I)
INPUT_TYPE = re.compile(r"""\btype\s*=\s*["'`]?([a-z]*)""", re.I)
TOKEN_LIKE = [
    re.compile(r"(?i)x-staff-token"),
    re.compile(r"(?i)staff[_-]?token"),
    re.compile(r"(?i)\bdev-[a-z]+-token\b"),
    re.compile(r"(?i)\bbearer\s+[a-z0-9._-]{8,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
    re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{32,}(?![0-9a-f])"),  # длинный hex: ключ, хеш, токен
    re.compile(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{40,}={0,2}(?![A-Za-z0-9+/_-])"),  # base64 от 40 знаков
]
DEMO = re.compile(r"(?i)демо")
# Задание 19: адрес оплаты приходит из данных клиники. В мок-данных (js/mocks*.js) допустим только https-адрес
# синтетического домена из контракта и только как значение payment_url; в разметке экранов адресов по-прежнему нет,
# всё остальное ловит test_no_external_addresses.
MOCK_DATA = re.compile(r"^js/mocks[\w-]*\.js$")
MOCK_CLINIC_URL = re.compile(r"""(\bpayment_url['"]?\s*:\s*['"`])https://(?:[a-z0-9-]+\.)*example-clinic\.ru(?:/[^\s'"`<>]*)?(?=['"`])""")
NEW_FILES_19 = [
    "js/screens/patient-doctors.js", "js/screens/patient-request.js", "js/screens/patient-status.js",
    "js/screens/patient-retest.js", "js/screens/patient-after.js", "js/screens/patient-errors.js",
    "js/mocks-care.js", "css/patient-booking.css", "css/patient-care.css",
]
NEW_ROUTES_19 = ["doctors", "request", "status", "retest", "after"]
MOCK_TOKENS_19 = [
    "demo-step-discuss", "demo-active", "demo-no-doctors", "demo-request-accepted", "demo-request-in-progress",
    "demo-request-booked", "demo-request-cancelled", "demo-paid-format", "demo-retest-today", "demo-retest-overdue",
    "demo-after-visit", "demo-after-booked", "demo-not-configured", "demo-error-network", "demo-error-500",
]
EXCLAMATION = re.compile(r"[А-Яа-яЁё»)]\s*!(?!=)")
RED_NAMES = re.compile(r"(?i)(?<![\w-])(red|darkred|crimson|firebrick|tomato|orangered)(?![\w-])")
HEX_COLOR = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
RGB_COLOR = re.compile(r"rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)")


def is_red(r: int, g: int, b: int) -> bool:
    """Тревожный красный: красный канал сильный, зелёный и синий слабые."""
    return r >= 180 and g < 110 and b < 110


def without_comments(text: str) -> str:
    """Без комментариев JS/CSS и HTML: проверяем то, что увидит человек, а не пояснения разработчика."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    return re.sub(r"(?m)(?<![:'\"`\\])//[^\n]*", " ", text)


class PilotWebTestCase(unittest.TestCase):
    def pilot_files(self) -> list[Path]:
        if not PILOT.is_dir():
            self.fail(f"нет web/pilot: ждём каркас FE1 ({PILOT})")
        files = sorted(p for p in PILOT.rglob("*") if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES)
        if not files:
            self.fail("нет web/pilot: в папке нет ни одного .html, .css, .js или .svg")
        return files

    def read(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def name(self, path: Path) -> str:
        return path.relative_to(PILOT).as_posix()

    def patient_files(self) -> list[Path]:
        """Всё, что попадает на экраны пациента: экраны P1–P8, их стили, мок-данные (mocks*.js), тексты оболочки
        (texts.js: ошибки до ответа сессии) и разметка."""
        files = self.pilot_files()
        chosen = [p for p in files if p.name.startswith(("patient-", "mocks"))
                  or p.name in {"patient.css", "texts.js", "index.html"}]
        self.assertTrue(any(p.name.startswith("patient-") for p in chosen),
                        "нет экранов пациента web/pilot/js/screens/patient-*.js (FE2)")
        return chosen

    def patient_screens(self) -> list[Path]:
        return [p for p in self.patient_files() if p.name.startswith("patient-")]


class PilotFilesTests(PilotWebTestCase):
    def test_entry_page_exists_without_inline_scripts(self):
        self.pilot_files()
        index = PILOT / "index.html"
        self.assertTrue(index.is_file(), "нет web/pilot/index.html")
        html = self.read(index)
        self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)", "встроенный <script> в index.html")
        self.assertRegex(html, r"<script[^>]*type=[\"']module[\"'][^>]*src=[\"']js/app\.js[\"']|"
                               r"<script[^>]*src=[\"']js/app\.js[\"'][^>]*type=[\"']module[\"']",
                         "index.html должен подключать js/app.js модулем")

    def test_no_browser_storage(self):
        for path in self.pilot_files():
            self.assertNotRegex(self.read(path), r"localStorage|sessionStorage|indexedDB|document\.cookie",
                                self.name(path))

    def test_no_inline_handlers(self):
        for path in self.pilot_files():
            content = self.read(path)
            self.assertNotRegex(content, r"\son[a-z]+\s*=\s*['\"`]", self.name(path))
            self.assertNotRegex(content, r"(?i)javascript:", self.name(path))

    def test_no_external_addresses(self):
        for path in self.pilot_files():
            content = self.read(path)
            if MOCK_DATA.match(self.name(path)):
                content = MOCK_CLINIC_URL.sub(r"\1", content)
            self.assertNotRegex(content, r"https?://|(?<![:\w])//[a-z0-9-]+\.[a-z]{2,}", self.name(path))
            self.assertNotRegex(content, r"(?i)@import\s+url\(\s*['\"]?(?!/assets/|\.)", self.name(path))

    def test_no_staff_token_or_token_like_strings(self):
        for path in self.pilot_files():
            content = self.read(path)
            for pattern in TOKEN_LIKE:
                found = pattern.search(content)
                self.assertIsNone(found, f"{self.name(path)}: похоже на токен или секрет: {found and found.group(0)[:12]}…")

    def test_demo_badge_is_present(self):
        files = [p for p in self.pilot_files() if p.suffix.lower() in {".html", ".js"}]
        self.assertTrue(any(DEMO.search(without_comments(self.read(p))) for p in files),
                        "нет плашки «демо»: режим mock должен быть подписан в шапке")


class PilotPatientTests(PilotWebTestCase):
    def test_no_forbidden_words_for_patient(self):
        for path in self.patient_files():
            found = FORBIDDEN.findall(without_comments(self.read(path)))
            self.assertEqual(found, [], f"{self.name(path)}: запрещённые слова в текстах для пациента")

    def test_no_free_text_fields_on_patient_screens(self):
        for path in self.patient_screens():
            content = self.read(path)
            self.assertNotRegex(content, r"(?i)<textarea|createElement\(\s*['\"`]textarea", self.name(path))
            self.assertNotRegex(content, r"(?i)contenteditable", self.name(path))
            self.assertNotRegex(content, r"(?i)createElement\(\s*['\"`]input", self.name(path))
            for attrs in INPUT_TAG.findall(content):
                kind = INPUT_TYPE.search(attrs)
                self.assertNotIn((kind.group(1) if kind else "").lower(), FREE_INPUT_TYPES,
                                 f"{self.name(path)}: поле свободного ввода <input{attrs}>")


class PilotBookingCareTests(PilotWebTestCase):
    """Задание 19: P4–P6 (FE3), P7–P8 и ошибки пациента (FE4) по «Контракту фронтенда»."""

    def test_new_screens_and_styles_exist(self):
        self.pilot_files()
        missing = [name for name in NEW_FILES_19 if not (PILOT / name).is_file()]
        self.assertEqual(missing, [], "нет файлов FE3/FE4 из таблицы «Кто владеет файлами»")

    def test_router_has_new_routes_without_next_stub(self):
        self.pilot_files()
        router = without_comments(self.read(PILOT / "js" / "router.js"))
        for name in NEW_ROUTES_19:
            self.assertTrue(re.search(rf"pattern\s*:[^\n]*\b{name}\b", router),
                            f"в ROUTES нет адреса #/p/<token>/{name}")
        self.assertFalse("patient-next.js" in router, "заглушка #/p/<token>/next должна уйти из ROUTES")

    def test_new_styles_are_linked(self):
        self.pilot_files()
        linked = " ".join(without_comments(self.read(p)) for p in self.pilot_files() if p.suffix in {".html", ".css"})
        for name in ("patient-booking.css", "patient-care.css"):
            self.assertTrue(name in linked, f"{name} не подключён ни в index.html, ни через @import")

    def test_mock_tokens_from_contract(self):
        self.pilot_files()
        mocks = " ".join(self.read(p) for p in self.pilot_files() if MOCK_DATA.match(self.name(p)))
        missing = [token for token in MOCK_TOKENS_19 if f"'{token}'" not in mocks and f'"{token}"' not in mocks]
        self.assertEqual(missing, [], "нет мок-токенов из «Контракта фронтенда»")
        self.assertRegex(mocks, r"payment_url['\"]?\s*:\s*['\"`]https://", "нет формата с оплатой (demo-paid-format)")

    def test_blank_links_open_without_opener_and_referrer(self):
        for path in self.pilot_files():
            content = without_comments(self.read(path))
            for tag in re.findall(r"<a\b[^>]*_blank[^>]*>", content):
                self.assertRegex(tag, r"noopener", f"{self.name(path)}: {tag}")
                self.assertRegex(tag, r"noreferrer", f"{self.name(path)}: {tag}")
            if "_blank" in content:
                self.assertIn("noopener", content, f"{self.name(path)}: target=_blank без rel=noopener")
                self.assertIn("noreferrer", content, f"{self.name(path)}: target=_blank без rel=noreferrer")

    def test_no_exclamations_in_patient_texts(self):
        for path in self.patient_files():
            found = EXCLAMATION.findall(without_comments(self.read(path)))
            self.assertEqual(found, [], f"{self.name(path)}: восклицания в текстах для пациента")

    def test_no_alarm_red_in_patient_styles(self):
        styles = [p for p in self.patient_files() if p.suffix == ".css"]
        self.assertTrue(styles, "нет стилей пациента")
        for path in styles:
            content = without_comments(self.read(path))
            self.assertIsNone(RED_NAMES.search(content), f"{self.name(path)}: красный цвет")
            for value in HEX_COLOR.findall(content):
                full = value if len(value) == 6 else "".join(ch * 2 for ch in value)
                rgb = [int(full[i:i + 2], 16) for i in (0, 2, 4)]
                self.assertFalse(is_red(*rgb), f"{self.name(path)}: тревожный красный #{value}")
            for rgb in RGB_COLOR.findall(content):
                self.assertFalse(is_red(*map(int, rgb)), f"{self.name(path)}: тревожный красный rgb{rgb}")


if __name__ == "__main__":
    unittest.main()
