"""Тесты разбора CSV (B2): валидные строки + видимые ошибки."""
from __future__ import annotations

from app.services.csv_parser import parse_visits_csv

GOOD = (
    b"patient_token,visit_date,paid_amount,doctor_id\n"
    b"pt-1,2026-10-20T10:00:00,3500,doc-1\n"
    b"pt-2,2026-10-21T11:30:00,,doc-2\n"
)


def test_valid_rows_parsed():
    rows, errors = parse_visits_csv(GOOD)
    assert len(rows) == 2
    assert errors == []
    assert rows[0].paid_amount == "3500"
    assert rows[1].paid_amount is None


def test_bad_row_is_reported_not_dropped():
    bad = (
        b"patient_token,visit_date,paid_amount,doctor_id\n"
        b"pt-1,2026-10-20T10:00:00,3500,doc-1\n"
        b"pt-2,NOT-A-DATE,1000,doc-2\n"
    )
    rows, errors = parse_visits_csv(bad)
    assert len(rows) == 1
    assert len(errors) == 1
    assert errors[0].line_number == 3


def test_missing_column_reported():
    broken = b"patient_token,visit_date\npt-1,2026-10-20T10:00:00\n"
    rows, errors = parse_visits_csv(broken)
    assert rows == []
    assert errors and "колонок" in errors[0].message
