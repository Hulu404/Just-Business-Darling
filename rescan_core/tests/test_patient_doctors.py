"""B6: порядок врачей для выбранной цели.

Источники порядка — только назначивший врач, визиты пациента к врачам цели и
порядок клиники в `goal_doctors`. Всё остальное на порядок не влияет.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.db.models import (
    Clinic,
    Consent,
    Doctor,
    Episode,
    Format,
    Goal,
    GoalDoctor,
    Patient,
    Step,
    Visit,
)
from tests.test_patient_api import SETTINGS, add_link, headers


@pytest.fixture
def clinic(db_session) -> Clinic:
    clinic = db_session.execute(select(Clinic)).scalar_one()
    clinic.patient_settings = json.dumps(SETTINGS, ensure_ascii=False)
    db_session.commit()
    return clinic


@pytest.fixture
def goal(db_session, clinic) -> Goal:
    return db_session.execute(select(Goal)).scalar_one()


@pytest.fixture
def staff(db_session, clinic, goal) -> dict[str, Doctor]:
    """Терапевт первым в цели, затем кардиолог, эндокринолог, невролог."""
    doctors = {
        "therapist": db_session.execute(select(Doctor)).scalar_one(),
        "cardio": Doctor(clinic_id=clinic.id, external_id="doc-cardio", full_name="Кардиолог Д.",
                         specialty="Кардиолог"),
        "endo": Doctor(clinic_id=clinic.id, external_id="doc-endo", full_name="Эндокринолог Д.",
                       specialty="Эндокринолог"),
        "neuro": Doctor(clinic_id=clinic.id, external_id="doc-neuro", full_name="Невролог Д.",
                        specialty="Невролог"),
        "ordering": Doctor(clinic_id=clinic.id, external_id="doc-ordering",
                           full_name="Назначивший Д.", specialty="Терапевт"),
    }
    db_session.add_all(doctors.values())
    db_session.flush()
    for order, key in enumerate(("therapist", "cardio", "endo", "neuro"), start=1):
        db_session.add(GoalDoctor(goal_id=goal.id, doctor_id=doctors[key].id, sort_order=order))
    db_session.commit()
    return doctors


@pytest.fixture
def patient_link(db_session, clinic, goal, staff):
    """Эпизод с согласием и выбранной целью; назначивший — staff['ordering']."""

    def _make(*, ordering: str | None = "ordering", token: str = "pt-doctors") -> str:
        patient = Patient(clinic_id=clinic.id, patient_token=token, group="main")
        db_session.add(patient)
        db_session.flush()
        episode = Episode(patient_id=patient.id, group="main", status="awaiting_doctor",
                          ordering_doctor_id=staff[ordering].id if ordering else None,
                          ready_at=datetime(2026, 10, 18, tzinfo=UTC), chosen_goal_id=goal.id,
                          chosen_branch="discuss")
        db_session.add_all([episode, Consent(patient_id=patient.id, kind="pd_processing",
                                             granted=True, source="link")])
        db_session.commit()
        return add_link(db_session, episode)

    return _make


def visit(session, clinic: Clinic, token: str, doctor: Doctor, day: int) -> None:
    session.add(Visit(clinic_id=clinic.id, patient_token=token,
                      visit_date=datetime(2026, 9, day, 10, tzinfo=UTC),
                      doctor_external_id=doctor.external_id))
    session.commit()


def doctors_of(client, token: str) -> list[tuple[str, str | None]]:
    response = client.get("/v1/patient/doctors", headers=headers(token))
    assert response.status_code == 200
    return [(item["id"], item["tag"]) for item in response.json()["doctors"]]


def test_order_ordering_then_visited_then_goal_order(client, db_session, clinic, staff,
                                                     patient_link):
    token = patient_link()
    visit(db_session, clinic, "pt-doctors", staff["endo"], 1)
    visit(db_session, clinic, "pt-doctors", staff["neuro"], 20)
    visit(db_session, clinic, "pt-doctors", staff["endo"], 25)  # последний визит — к endo

    assert doctors_of(client, token) == [
        (staff["ordering"].id, "ordering"),
        (staff["endo"].id, "visited"),
        (staff["neuro"].id, "visited"),
        (staff["therapist"].id, None),
        (staff["cardio"].id, None),
    ]


def test_response_fields(client, db_session, staff, patient_link):
    staff["ordering"].photo_url = "/assets/pilot/demo/doctor.png"
    db_session.commit()
    response = client.get("/v1/patient/doctors", headers=headers(patient_link()))
    first = response.json()["doctors"][0]
    assert first == {"id": staff["ordering"].id, "name": "Назначивший Д.",
                     "specialty": "Терапевт", "photo_url": "/assets/pilot/demo/doctor.png",
                     "tag": "ordering"}
    assert "pt-doctors" not in response.text


def test_no_duplicates_ordering_doctor_in_goal_and_visited(client, db_session, clinic, staff,
                                                           patient_link):
    token = patient_link(ordering="cardio")
    visit(db_session, clinic, "pt-doctors", staff["cardio"], 10)
    assert doctors_of(client, token) == [
        (staff["cardio"].id, "ordering"),
        (staff["therapist"].id, None),
        (staff["endo"].id, None),
        (staff["neuro"].id, None),
    ]


def test_without_ordering_doctor(client, staff, patient_link):
    token = patient_link(ordering=None)
    assert [tag for _, tag in doctors_of(client, token)] == [None] * 4
    assert doctors_of(client, token)[0][0] == staff["therapist"].id


def test_inactive_doctors_are_hidden(client, db_session, clinic, staff, patient_link):
    token = patient_link()
    visit(db_session, clinic, "pt-doctors", staff["endo"], 5)
    for key in ("ordering", "endo", "cardio"):
        staff[key].is_active = False
    db_session.commit()
    assert doctors_of(client, token) == [(staff["therapist"].id, None),
                                         (staff["neuro"].id, None)]


def test_visits_of_other_patients_and_clinics_do_not_count(client, db_session, clinic, staff,
                                                           patient_link):
    token = patient_link()
    other_clinic = Clinic(name="Чужая", service_enabled=True)
    db_session.add(other_clinic)
    db_session.flush()
    visit(db_session, clinic, "pt-someone-else", staff["neuro"], 5)
    visit(db_session, other_clinic, "pt-doctors", staff["endo"], 5)
    assert [tag for _, tag in doctors_of(client, token)] == ["ordering", None, None, None, None]


def test_visited_doctor_outside_goal_is_not_added(client, db_session, clinic, staff, goal,
                                                  patient_link):
    outsider = Doctor(clinic_id=clinic.id, external_id="doc-out", full_name="Вне цели")
    db_session.add(outsider)
    db_session.commit()
    token = patient_link()
    visit(db_session, clinic, "pt-doctors", outsider, 5)
    assert outsider.id not in {doctor_id for doctor_id, _ in doctors_of(client, token)}


def test_foreign_clinic_doctor_in_goal_is_hidden(client, db_session, goal, staff, patient_link):
    other_clinic = Clinic(name="Чужая", service_enabled=True)
    db_session.add(other_clinic)
    db_session.flush()
    foreign = Doctor(clinic_id=other_clinic.id, external_id="doc-f", full_name="Чужой")
    db_session.add(foreign)
    db_session.flush()
    db_session.add(GoalDoctor(goal_id=goal.id, doctor_id=foreign.id, sort_order=0))
    db_session.commit()
    assert foreign.id not in {doctor_id for doctor_id, _ in doctors_of(client, patient_link())}


def test_empty_list(client, db_session, clinic, staff, patient_link):
    other_goal = Goal(clinic_id=clinic.id, title="Без врачей", sort_order=9)
    db_session.add(other_goal)
    db_session.commit()
    token = patient_link(ordering=None)
    assert client.post("/v1/patient/choice", headers=headers(token), json={
        "branch_code": "discuss", "goal_id": other_goal.id}).status_code == 200
    response = client.get("/v1/patient/doctors", headers=headers(token))
    assert response.status_code == 200
    assert response.json() == {"doctors": []}


def test_order_depends_only_on_three_sources(client, db_session, clinic, goal, staff,
                                             patient_link):
    token = patient_link()
    visit(db_session, clinic, "pt-doctors", staff["neuro"], 3)
    before = doctors_of(client, token)

    # Меняем всё, кроме назначившего, визитов к врачам цели и порядка цели.
    names = {"therapist": "Яковлев", "cardio": "Абрамова", "endo": "Борисов", "neuro": "Юрьев"}
    for key, name in names.items():
        staff[key].full_name = name
        staff[key].specialty = "Другая специальность"
        staff[key].photo_url = "/assets/pilot/demo/x.png"
    episode = db_session.execute(select(Episode)).scalar_one()
    episode.chosen_branch = "retest"
    episode.status = "doctor_marked"
    episode.ready_at = datetime(2020, 1, 1, tzinfo=UTC)
    db_session.add_all([
        Step(episode_id=episode.id, kind="retest", set_by_doctor_id=staff["cardio"].id,
             set_at=datetime.now(UTC)),
        Format(clinic_id=clinic.id, title="Ещё формат", price_kopecks=1),
        Goal(clinic_id=clinic.id, title="Другая цель", sort_order=-5),
        Doctor(clinic_id=clinic.id, external_id="doc-new", full_name="Аааа Новый"),
        Consent(patient_id=episode.patient_id, kind="marketing", granted=False),
    ])
    episode.patient.group = "main"
    clinic.theme = '{"name": "Другая", "accent": "#000000"}'
    clinic.patient_settings = json.dumps({**SETTINGS, "timezone": "Asia/Vladivostok"})
    db_session.commit()

    assert doctors_of(client, token) == before
