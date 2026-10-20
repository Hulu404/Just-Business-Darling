import json

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db.models import AuditEvent, Clinic
from tests.test_crm_delivery import application as request_fixture

application = request_fixture


def assert_error(response, status, code):
    assert response.status_code == status
    detail = response.json()["detail"]
    assert set(detail) == {"code", "message"} and detail["code"] == code
    assert detail["message"]


def post(client, sign_headers, body, **kwargs):
    raw = json.dumps(body).encode()
    return client.post("/v1/crm/status", content=raw, headers=sign_headers(
        raw, secret=get_settings().crm_status_secret, **kwargs))


@pytest.mark.parametrize("old", ["new", "sent", "in_progress", "booked", "cancelled"])
@pytest.mark.parametrize("new", ["in_progress", "booked", "cancelled"])
@pytest.mark.parametrize("manual", [False, True])
def test_all_transitions(client, sign_headers, db_session, application, old, new, manual):
    request = application[2]
    request.status = old
    db_session.commit()
    allowed = old == new or new in {
        "new": {"cancelled"}, "sent": {"in_progress", "cancelled"},
        "in_progress": {"booked", "cancelled"}, "booked": set(), "cancelled": set(),
    }[old]
    if manual:
        response = client.post(f"/v1/admin/requests/{request.id}/status", json={"status": new},
                               headers={"X-Staff-Token": "dev-admin-token"})
    else:
        response = post(client, sign_headers, {"request_id": request.id, "status": new})
    if allowed:
        assert response.status_code == 200
    else:
        assert_error(response, 409, "invalid_transition")
    db_session.refresh(request)
    assert request.status == (new if allowed else old)
    events = db_session.scalars(select(AuditEvent)).all()
    if allowed and old != new:
        assert len(events) == 1
        assert events[0].action == "crm.status_changed"
        assert events[0].actor_id == ("dev-admin" if manual else "crm")
    else:
        assert events == []


def test_lookup_crm_id_idempotent(client, sign_headers, db_session, application):
    request = application[2]
    request.status, request.crm_request_id = "sent", "demo-crm-id"
    db_session.commit()
    for _ in range(2):
        response = post(client, sign_headers, {"crm_request_id": "demo-crm-id",
                                             "status": "in_progress"})
        assert response.json() == {"request_id": request.id, "status": "in_progress"}
    assert len(db_session.scalars(select(AuditEvent)).all()) == 1


@pytest.mark.parametrize("body", [
    {}, [], {"status": "booked"},
    {"request_id": "demo", "crm_request_id": "demo", "status": "booked"},
    {"request_id": "", "status": "booked"}, {"request_id": "demo", "status": "sent"},
    {"request_id": "demo", "status": "booked", "phone": "70000000000"},
    {"request_id": None, "crm_request_id": "demo", "status": "booked"},
])
def test_bad_body_private(client, sign_headers, application, body):
    response = post(client, sign_headers, body)
    assert_error(response, 422, "invalid_input")
    assert "70000000000" not in response.text
    assert "demo" not in response.text


@pytest.mark.parametrize("identity", ["request_id", "crm_request_id"])
def test_missing(client, sign_headers, application, identity):
    assert_error(post(client, sign_headers, {identity: "missing", "status": "booked"}),
                 404, "request_not_found")


@pytest.mark.parametrize("headers", [{}, {"X-Rescan-Signature": "bad"},
                                  {"X-Rescan-Signature": "bad", "X-Rescan-Timestamp": "bad"}])
def test_bad_signature(client, application, headers):
    assert_error(client.post("/v1/crm/status", json={"request_id": application[2].id,
                 "status": "cancelled"}, headers=headers), 401, "bad_signature")


def test_stale_and_tampered(client, sign_headers, application):
    body = {"request_id": application[2].id, "status": "cancelled"}
    assert_error(post(client, sign_headers, body, ts=1), 401, "bad_signature")
    raw = json.dumps(body).encode()
    headers = sign_headers(raw, secret=get_settings().crm_status_secret)
    assert_error(client.post("/v1/crm/status", content=raw + b" ", headers=headers),
                 401, "bad_signature")


@pytest.mark.parametrize("token,code", [("dev-doctor-token", 403), ("missing", 401)])
def test_manual_role(client, application, token, code):
    response = client.post(f"/v1/admin/requests/{application[2].id}/status",
                           json={"status": "cancelled"}, headers={"X-Staff-Token": token})
    assert response.status_code == code


def test_manual_foreign_clinic(client, db_session, application, monkeypatch):
    other = Clinic(name="Демо другая клиника")
    db_session.add(other)
    db_session.commit()
    monkeypatch.setattr(get_settings(), "mis_clinic_id", other.id)
    response = client.post(f"/v1/admin/requests/{application[2].id}/status",
                           json={"status": "cancelled"},
                           headers={"X-Staff-Token": "dev-admin-token"})
    assert_error(response, 404, "request_not_found")


def test_manual_missing_and_invalid(client, application):
    headers = {"X-Staff-Token": "dev-admin-token"}
    assert_error(client.post("/v1/admin/requests/missing/status", json={"status": "cancelled"},
                             headers=headers), 404, "request_not_found")
    response = client.post(f"/v1/admin/requests/{application[2].id}/status",
                           json={"status": "cancelled", "phone": "70000000000"}, headers=headers)
    assert_error(response, 422, "invalid_input")
    assert "70000000000" not in response.text
