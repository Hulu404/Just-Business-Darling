"""Разбор CSV-выгрузок (приём визитов).

Требование B2: «ошибка в строке видна, а не теряется». Парсер не падает на
плохой строке, а собирает валидные строки и отдельный список ошибок с номерами.

Заголовок CSV: patient_token,visit_date,paid_amount,doctor_id
"""
from __future__ import annotations

import csv
import io
from datetime import datetime

from pydantic import ValidationError

from app.schemas.events import CsvRowError, VisitRow

EXPECTED_COLUMNS = {"patient_token", "visit_date", "paid_amount", "doctor_id"}


def parse_visits_csv(content: bytes) -> tuple[list[VisitRow], list[CsvRowError]]:
    """Вернуть (валидные строки, ошибки). Никогда не бросает на плохой строке."""
    text = content.decode("utf-8-sig")  # снимаем BOM из Excel-выгрузок
    reader = csv.DictReader(io.StringIO(text))

    rows: list[VisitRow] = []
    errors: list[CsvRowError] = []

    if reader.fieldnames is None:
        errors.append(CsvRowError(line_number=0, message="пустой файл или нет заголовка"))
        return rows, errors

    missing = EXPECTED_COLUMNS - set(reader.fieldnames)
    if missing:
        errors.append(
            CsvRowError(
                line_number=1,
                message=f"нет обязательных колонок: {', '.join(sorted(missing))}",
                raw=",".join(reader.fieldnames),
            )
        )
        return rows, errors

    for i, raw_row in enumerate(reader, start=2):  # строка 1 — заголовок
        try:
            visit_date = datetime.fromisoformat(raw_row["visit_date"].strip())
            row = VisitRow(
                patient_token=raw_row["patient_token"].strip(),
                visit_date=visit_date,
                paid_amount=(raw_row.get("paid_amount") or "").strip() or None,
                doctor_id=(raw_row.get("doctor_id") or "").strip() or None,
            )
            rows.append(row)
        except (ValidationError, ValueError, KeyError, AttributeError) as exc:
            errors.append(
                CsvRowError(
                    line_number=i,
                    message=str(exc),
                    raw=",".join(f"{k}={v}" for k, v in raw_row.items() if k),
                )
            )

    return rows, errors
