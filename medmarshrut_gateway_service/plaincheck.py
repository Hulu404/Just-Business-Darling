"""Сверка упрощённого текста для пациента с заключением врача: что из фактов заключения сохранилось.

Без ИИ и без сети: правила на регулярных выражениях. Проверяются числа и размеры, сторона, сегменты и категории,
специалисты и контрольное исследование. Смысл целиком сверка не проверяет — это делает врач, сверка лишь
показывает, что потерялось или появилось нового.
"""
from __future__ import annotations

import re

NUMBER = re.compile(r"(?<![A-Za-zА-Яа-яЁё\d.,])\d+(?:[.,]\d+)?")
SIZE = re.compile(r"(?<![A-Za-zА-Яа-яЁё\d.,])\d+(?:[.,]\d+)?(?:\s*[×xх*–-]\s*\d+(?:[.,]\d+)?)*"
                  r"(?:\s*(?:мм|см|мл|%|месяц\w*|недел\w*|дн(?:я|ей)|час\w*|сут\w*|год\w*|лет)\b)?", re.IGNORECASE)
ENDINGS = r"(?:ый|ая|ое|ого|ой|ом|ому|ую|ые|ых|ым|ыми|ее|его|ей|ем|ему|юю|ие|их|им|ими)"
SIDES = {
    "справа": re.compile(r"\b(?:справа|прав" + ENDINGS + r")\b", re.IGNORECASE),
    "слева": re.compile(r"\b(?:слева|лев" + ENDINGS + r")\b", re.IGNORECASE),
    "с двух сторон": re.compile(r"\b(?:с\s+двух\s+сторон|двусторонн\w*|с\s+обеих\s+сторон)\b", re.IGNORECASE),
}
SEGMENT = re.compile(r"\b(S\s?\d{1,2})\b")
BIRADS = re.compile(r"BI-?RADS\s*(\d[a-c]?)", re.IGNORECASE)
SPECIALISTS = ("пульмонолог", "кардиолог", "терапевт", "онколог", "маммолог", "невролог", "эндокринолог",
               "травматолог", "ортопед", "хирург", "уролог", "гастроэнтеролог", "гинеколог", "фтизиатр", "нейрохирург")
FOLLOW_UP = re.compile(r"\b(?:контрольн\w*|контрол[ья]\w*|повторн\w*|динамик\w*)\b", re.IGNORECASE)


def numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in NUMBER.findall(text)}


def facts(text: str) -> list[tuple[str, str]]:
    """Факты заключения: [(вид, подпись)], без повторов, в порядке появления."""
    found: list[tuple[str, str]] = []

    def add(kind: str, label: str) -> None:
        if (kind, label) not in found:
            found.append((kind, label))
    for match in SIZE.finditer(text):
        label = match.group(0).strip()
        if numbers(label):
            add("size", label)
    for name, pattern in SIDES.items():
        if pattern.search(text):
            add("side", name)
    for segment in SEGMENT.findall(text):
        add("segment", segment.replace(" ", ""))
    for category in BIRADS.findall(text):
        add("birads", "BI-RADS " + category)
    low = text.lower()
    for name in SPECIALISTS:
        if name in low and not (name == "хирург" and "нейрохирург" in low and low.count("хирург") == low.count("нейрохирург")):
            add("specialist", name)
    if FOLLOW_UP.search(text):
        add("follow_up", "контрольное исследование")
    return found


def present(kind: str, label: str, plain: str) -> bool:
    if kind == "size":
        return numbers(label) <= numbers(plain)
    if kind == "side":
        return bool(SIDES[label].search(plain))
    if kind == "segment":
        return bool(re.search(r"\bS\s?" + re.escape(label[1:]) + r"\b", plain))
    if kind == "birads":
        return label.split()[-1].lower() in [c.lower() for c in BIRADS.findall(plain)]
    if kind == "specialist":
        return label in plain.lower()
    if kind == "follow_up":
        return bool(FOLLOW_UP.search(plain))
    return False


def preservation(conclusion: str, plain: str) -> dict:
    """{"ok", "kept", "missing", "added"}: подписи фактов. ok — ничего не потеряно и ничего не добавлено."""
    source = facts(conclusion)
    kept = [label for kind, label in source if present(kind, label, plain)]
    missing = [label for kind, label in source if not present(kind, label, plain)]
    # Новые числа, сторона и специалисты, которых нет в заключении врача
    added = [label for kind, label in facts(plain)
             if kind in ("size", "side", "specialist", "birads", "segment") and not present(kind, label, conclusion)]
    return {"ok": not missing and not added, "kept": kept, "missing": missing, "added": added}
