"""HTTP-проверки подписи файла и сохранения визитов."""
from sqlalchemy import select

from app.db.models import Clinic, Visit

CSV = (b"patient_token,visit_date,paid_amount,doctor_id\n"
       b"pt-1,2026-10-20T10:00:00+03:00,3500.25,doc-1\n"
       b"pt-2,2026-10-21T11:30:00+03:00,,doc-2\n")


def upload(client, sign_headers, content=CSV, signed=None):
    headers = sign_headers(content if signed is None else signed)
    headers.pop("Content-Type")
    return client.post("/v1/mis/visits-csv", headers=headers,
                       files={"file": ("visits.csv", content, "text/csv")})


def test_signed_file_is_persisted_and_repeat_is_noop(client, sign_headers, db_session):
    response = upload(client, sign_headers)
    assert response.status_code == 200
    assert response.json() == {"accepted": 2, "errors": []}
    rows = db_session.execute(select(Visit).order_by(Visit.patient_token)).scalars().all()
    assert len(rows) == 2
    assert rows[0].paid_kopecks == 350025
    assert rows[1].paid_kopecks == 0
    assert upload(client, sign_headers).json()["accepted"] == 0
    assert len(db_session.execute(select(Visit)).scalars().all()) == 2


def test_tampered_file_is_not_imported(client, sign_headers, db_session):
    response = upload(client, sign_headers, CSV.replace(b"3500", b"9999"), signed=CSV)
    assert response.status_code == 401
    assert db_session.execute(select(Visit)).first() is None


def test_invalid_rows_are_reported_and_valid_rows_saved(client, sign_headers, db_session):
    response = upload(client, sign_headers, CSV + b"pt-3,2026-10-20,garbage,doc-1\n")
    assert response.status_code == 200
    assert response.json()["accepted"] == 2
    assert response.json()["errors"][0]["line_number"] == 4
    assert len(db_session.execute(select(Visit)).scalars().all()) == 2


def test_csv_disabled_clinic_has_no_writes(client, sign_headers, db_session):
    db_session.execute(select(Clinic)).scalar_one().service_enabled = False
    db_session.commit()
    assert upload(client, sign_headers).status_code == 403
    assert db_session.execute(select(Visit)).first() is None


def test_equivalent_money_and_timezone_do_not_duplicate(client, sign_headers, db_session):
    assert upload(client, sign_headers).json()["accepted"] == 2
    equivalent = CSV.replace(b"3500.25", b"3500.250").replace(
        b"2026-10-20T10:00:00+03:00", b"2026-10-20T07:00:00+00:00",
    )
    assert upload(client, sign_headers, equivalent).json()["accepted"] == 0
    assert len(db_session.execute(select(Visit)).scalars().all()) == 2
