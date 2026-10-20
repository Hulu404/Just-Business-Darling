"""Проверки страниц пилота rescan (`web/pilot/`) без браузера: задание 18, раздел «Тестировщик», п. 2.

Читают каждый текстовый файл пилота. Пока папки нет, каждый тест падает с сообщением «нет web/pilot»:
пустой проход ничего бы не доказал.
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
        """Всё, что попадает на экраны пациента: экраны P1–P3, их стили, мок-данные и разметка."""
        files = self.pilot_files()
        chosen = [p for p in files if p.name.startswith("patient-") or p.name in {"patient.css", "mocks.js", "index.html"}]
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


if __name__ == "__main__":
    unittest.main()
