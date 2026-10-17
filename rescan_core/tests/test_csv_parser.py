"""Тесты разбора CSV (B2): валидные строки + видимые ошибки."""
from __future__ import annotations

from decimal import Decimal

import pytest

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
    assert rows[0].paid_amount == Decimal("3500")
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


@pytest.mark.parametrize("amount", ["NOT_MONEY", "NaN", "Infinity", "-1", "1.001", "1e30"])
def test_invalid_amount_is_a_row_error(amount):
    body = ("patient_token,visit_date,paid_amount,doctor_id\n"
            f"pt-1,2026-10-20T10:00:00,{amount},doc-1\n").encode()
    rows, errors = parse_visits_csv(body)
    assert rows == []
    assert len(errors) == 1
    assert errors[0].line_number == 2


def test_invalid_encoding_is_reported():
    rows, errors = parse_visits_csv(b"\xff")
    assert rows == []
    assert len(errors) == 1
