#!/usr/bin/env python
"""Раскладывает образец rescan на файлы без base64.

Образец `prototype/rescan-app-standalone.html` держит в себе шрифт и картинки
строками base64 (78 % веса). Для работы над кабинетом врача (задание 12) из него
нужны:

- шрифт Stolzl -> `medmarshrut_gateway_service/web/fonts/Stolzl-Regular.otf`;
- картинки форм лекарств (`IMG`) и органов (`ORG`) ->
  `medmarshrut_gateway_service/web/img/rescan/<ключ>.webp`;
- текст образца без base64 -> `prototype/rescan-app-text.html` (его читают и ищут).

Портреты (`AVS`) намеренно не извлекаются: это вымышленные люди, на стенде у
пациентов и врача — инициалы.

Запуск из корня репозитория: `python prototype/rescan_extract.py`.
Скрипт идемпотентен: повторный запуск не меняет уже разложенные файлы.
Без образца печатает, куда его положить, и выходит с кодом 1.
"""
import base64
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "prototype" / "rescan-app-standalone.html"
WEB = ROOT / "medmarshrut_gateway_service" / "web"
FONT_PATH = WEB / "fonts" / "Stolzl-Regular.otf"
IMG_DIR = WEB / "img" / "rescan"
TEXT_OUT = ROOT / "prototype" / "rescan-app-text.html"

B64 = r"[A-Za-z0-9+/=]+"


def write_if_changed(path, data):
    """Пишет файл, только если содержимое изменилось: иначе ни байта, ни mtime."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def extract_font(html):
    m = re.search(r"url\(data:font/otf;base64,(" + B64 + r")\)", html)
    if not m:
        raise SystemExit("В образце не нашёлся шрифт (data:font/otf).")
    return write_if_changed(FONT_PATH, base64.b64decode(m.group(1)))


def extract_webp_object(html, name, pattern):
    """Разбирает объект вида {"ключ": "data:image/webp;base64,..."} и кладёт webp по ключам."""
    m = re.search(name + r"=(\{.*?\});", html)
    if not m:
        raise SystemExit(f"В образце не нашёлся объект {name}.")
    body = m.group(1)
    changed = 0
    keys = []
    for key, payload in re.findall(pattern, body):
        keys.append(key)
        if write_if_changed(IMG_DIR / f"{key}.webp", base64.b64decode(payload)):
            changed += 1
    return keys, changed


def make_text(html):
    """Текст образца без base64: длинные полезные нагрузки убраны, адреса data: сохранены коротко."""
    text = re.sub(r"(base64,)" + B64, r"\1", html)
    return text.replace("\r\n", "\n")


def main():
    if not SRC.exists():
        print(f"Нет образца. Положите rescan-app-standalone.html в {SRC.parent}")
        return 1
    html = SRC.read_text(encoding="utf-8")

    font_changed = extract_font(html)
    img_keys, img_changed = extract_webp_object(
        html, "IMG", r'"(\w+)":\s*"data:image/webp;base64,(' + B64 + r')"')
    org_keys, org_changed = extract_webp_object(
        html, "ORG", r'"(\w+)":\s*\{"src":\s*"data:image/webp;base64,(' + B64 + r')"')
    text_changed = write_if_changed(TEXT_OUT, make_text(html))

    print(f"Шрифт: {FONT_PATH.relative_to(ROOT)} — {'записан' if font_changed else 'без изменений'}")
    print(f"Формы лекарств (IMG): {len(img_keys)} шт., обновлено {img_changed}")
    print(f"Органы (ORG): {len(org_keys)} шт., обновлено {org_changed}: {', '.join(org_keys)}")
    print(f"Текст без base64: {TEXT_OUT.relative_to(ROOT)} — {'записан' if text_changed else 'без изменений'}")
    print("Портреты (AVS) не извлекались.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
