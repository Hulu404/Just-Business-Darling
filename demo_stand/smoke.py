"""End-to-end smoke check of the demo stand on its own synthetic patient, services and gateway."""
from __future__ import annotations

import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path

from stand_api import (DEMO_DIR, GATEWAY, StandError, call, clinic_signed, clinic_staff, confirm, env, expect, find_episode,
                       load_json, path_post, review, step_action, upload_kit, upload_study, utf8_console)
from synthetic_dicom import build_study

HOME, PARTNER = "clinic-central", "clinic-partner-1"
COORDINATOR, DOCTOR, PARTNER_STAFF = "coordinator-natalia", "doctor-demo", "partner1-coordinator"


def stamp(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def check(ok: bool, what: str) -> None:
    if not ok:
        raise StandError(what)


def main() -> int:
    utf8_console()
    kit_dir = Path(env("DEMO_STATE_DIR")) / "kit"
    conclusions = load_json(DEMO_DIR / "conclusions.demo.json")
    ref = "smoke-" + secrets.token_hex(4)
    now = datetime.now().astimezone()
    ctx: dict = {}

    def step1():
        status, body = clinic_staff("POST", "/v1/patients", HOME, {
            "home_clinic_id": HOME, "patient_ref": ref, "full_name": "Пациент смоук-проверки",
            "birth_date": "1980-01-01", "sex": "X", "contact": f"{ref}@example.invalid"})
        ctx["patient_id"] = expect(status, body, 201, "Регистрация")["patient"]["id"]
        for text, shareable in (("Запись для партнёра", True), ("Внутренняя заметка клиники", False)):
            status, body = clinic_staff("POST", f"/v1/patients/{ctx['patient_id']}/anamnesis", HOME, {
                "kind": "note", "code": None, "text": text, "shareable": shareable, "recorded_at": None,
                "author_id": COORDINATOR, "author_role": "coordinator", "clinic_id": HOME})
            expect(status, body, 201, "Анамнез")
        return f"{ref} зарегистрирован в {HOME}"

    def step2():
        status, body = upload_kit(kit_dir, "smoke-ct")
        check(status == 201 and body["status"] == "awaiting_physician", f"ожидали 201 awaiting_physician, получили {status} {body}")
        check(set(body) == {"id", "created_at", "status", "reason", "routing_status"}, f"в публичном статусе лишние поля: {sorted(body)}")
        ctx["ct_job"] = body["id"]
        return "201, awaiting_physician, наружу только статус"

    def step3():
        archive, manifest = build_study("ct", variant=99)
        status, body = upload_study(archive, manifest)
        check(body["status"] == "manual_review", f"ожидали manual_review, получили {status} {body}")
        job = review(body["id"])
        check(job["result"]["findings"] == [] and job["draft"] == [], "у чужого исследования появились признаки")
        return f"{status}, manual_review, признаков нет"

    def step4():
        job = review(ctx["ct_job"])
        code = job["result"]["findings"][0]["code"]
        check(code == "DEMO_CT_INFILTRATE", f"неожиданный код находки {code}")
        check(job["result"]["model_version"].startswith("demo-") and job["result"]["findings"][0]["confidence"] == 0.0,
              "сценарный backend должен помечать версию префиксом demo- и ставить оценку 0.0")
        result = confirm(ctx["ct_job"], DOCTOR, conclusions[code], code, ref)
        check(result["routing_status"] == "sent", f"routing_status {result['routing_status']}")
        return "routing_status = sent"

    def step5():
        episode = find_episode(ctx["ct_job"])
        check(episode is not None, "эпизод не найден по source_report_id")
        check(episode["status"] == "active", f"статус эпизода {episode['status']}")
        first = episode["plan_steps"][0]
        check(first["decision_source"].startswith("rule:") and first["description"] == "Приём терапевта в течение 24 часов",
              f"шаг не из правила: {first}")
        ctx["episode"] = episode
        return f"эпизод {episode['id'][:8]}…, active, шаг «{first['description']}» по правилу"

    def step6():
        report = ctx["episode"]["source_report"]
        status, body = clinic_signed("/v1/route-candidates", {"patient_ref": ref, "scope": {
            "study_type": report["study_type"], "anatomy": report["anatomy"],
            "protocol_name": report["protocol_name"], "finding_code": report["finding_code"]}})
        expect(status, body, 200, "route-candidates")
        roles = {(c["clinic_id"], c["role"], c["referral_required"]) for c in body["candidates"]}
        check((HOME, "home", False) in roles and (PARTNER, "partner", True) in roles, f"кандидаты: {body}")
        return f"дом {HOME}, партнёр {PARTNER} с направлением"

    def step7():
        episode_id, step_id = ctx["episode"]["id"], ctx["episode"]["plan_steps"][0]["id"]
        step_action(episode_id, step_id, "offer", COORDINATOR, "Смоук: предложено", appointment_at=stamp(now - timedelta(hours=3)))
        step_action(episode_id, step_id, "confirm", COORDINATOR, "Смоук: подтверждено")
        step_action(episode_id, step_id, "attend", COORDINATOR, "Смоук: пришёл")
        body = path_post(f"/v1/episodes/{episode_id}/outcomes", {"step_id": step_id, "outcome": {
            "source": "staff_form", "event_id": f"{ref}-visit-1", "physician_id": DOCTOR,
            "confirmed_at": stamp(now - timedelta(hours=2)), "summary": "Смоук: нужен контроль",
            "next_steps": [{"kind": "test", "description": "Контрольная КТ органов грудной клетки", "owner": COORDINATOR,
                            "due_at": stamp(now + timedelta(days=30)), "continue_on": "confirmed_outcome"}]}})
        steps = body["episode"]["plan_steps"]
        check(steps[0]["status"] == "completed" and steps[-1]["cycle"] == 2 and steps[-1]["status"] == "open",
              f"второй цикл не появился: {[(s['status'], s['cycle']) for s in steps]}")
        ctx["episode"] = body["episode"]
        return "offer → confirm → attend → итог врача, открыт шаг второго цикла"

    def step8():
        episode_id, second = ctx["episode"]["id"], ctx["episode"]["plan_steps"][-1]["id"]
        step_action(episode_id, second, "offer", COORDINATOR, "Смоук: предложено", appointment_at=stamp(now + timedelta(days=7)))
        paused = step_action(episode_id, second, "refuse", COORDINATOR, "Смоук: пациент отказался от даты")
        check(paused["status"] == "paused", f"после отказа эпизод {paused['status']}")
        revised = path_post(f"/v1/episodes/{episode_id}/revise-plan", {"physician_id": DOCTOR, "reason": "Смоук: другая клиника",
            "steps": [{"kind": "test", "description": "Контрольная КТ органов грудной клетки у партнёра", "owner": COORDINATOR,
                       "due_at": stamp(now + timedelta(days=30)), "continue_on": "confirmed_outcome"}]})
        new_step = revised["plan_steps"][-1]["id"]
        offered = step_action(episode_id, new_step, "offer", COORDINATOR, "Смоук: новое предложение",
                              appointment_at=stamp(now + timedelta(days=10)))
        statuses = {s["id"]: s["status"] for s in offered["plan_steps"]}
        check(statuses[second] == "superseded" and statuses[new_step] == "offered", f"статусы шагов: {statuses}")
        return "offer → refuse → revise-plan → offer нового шага прошёл"

    def step9():
        status, body = clinic_signed("/v1/referrals", {"patient_ref": ref, "from_clinic_id": HOME, "to_clinic_id": PARTNER,
                                                       "reason": "Смоук: контрольная КТ", "created_by": COORDINATOR})
        referral = expect(status, body, 201, "Направление")
        card_path = f"/v1/patients/{ctx['patient_id']}/card"
        status, before = clinic_staff("GET", card_path, PARTNER)
        expect(status, before, 200, "Карта партнёра до принятия")
        check("full_name" not in before["patient"], "партнёр видит ФИО до принятия направления")
        check([e["text"] for e in before["anamnesis"]] == ["Запись для партнёра"], f"партнёр видит лишний анамнез: {before['anamnesis']}")
        status, body = clinic_staff("POST", f"/v1/referrals/{referral['id']}/accept", PARTNER, {"actor": PARTNER_STAFF})
        expect(status, body, 200, "Принятие направления")
        status, after = clinic_staff("GET", card_path, PARTNER)
        expect(status, after, 200, "Карта партнёра после принятия")
        check(after["patient"].get("full_name") == "Пациент смоук-проверки", "после принятия ФИО не появилось")
        return "до accept ФИО скрыто и виден только shareable-анамнез, после accept ФИО есть"

    def step10():
        status, body = upload_kit(kit_dir, "smoke-mg")
        check(status == 201 and body["status"] == "awaiting_physician", f"маммография: {status} {body}")
        job = review(body["id"])
        code = job["result"]["findings"][0]["code"]
        result = confirm(body["id"], DOCTOR, conclusions[code], code, ref)
        check(result["routing_status"] == "sent", f"routing_status {result['routing_status']}")
        episode = find_episode(body["id"])
        check(episode is not None and episode["status"] == "manual_review" and episode["manual_reason"] == "rule_not_approved",
              f"эпизод маммографии: {episode and (episode['status'], episode['manual_reason'])}")
        return "эпизод в manual_review, причина rule_not_approved"

    def step11():
        status, health = call("GET", GATEWAY + "/api/health")
        expect(status, health, 200, "Состояние через шлюз")
        down = [name for name, info in health["services"].items() if info["status"] != "up"]
        check(not down and health["auth"] == "demo-roles" and health["imaging_mode"] == "demo-scripted",
              f"состояние через шлюз: {health}")
        status, session = call("POST", GATEWAY + "/api/session", {"role": "patient", "patient_ref": ref},
                               headers={"X-MM-Role": "patient"})
        expect(status, session, 201, "Сессия пациента через шлюз")
        check(session == {"role": "patient", "name": "Пациент", "patient_ref": ref}, f"сессия: {session}")
        status, foreign = call("POST", GATEWAY + "/api/session", {"role": "patient", "patient_ref": "no-such-patient"},
                               headers={"X-MM-Role": "patient"})
        check(status == 400, f"шлюз пустил незарегистрированного пациента: {status} {foreign}")
        return "три сервиса работают, сессия пациента создаётся, чужой псевдоним отклонён"

    steps = [("Регистрация пациента в сервисе клиники", step1),
             ("Загрузка учебной КТ", step2),
             ("Загрузка КТ не из учебного набора", step3),
             ("Подтверждение врачом с patient_ref", step4),
             ("Эпизод в сервисе пути", step5),
             ("Кандидаты маршрута", step6),
             ("Первый цикл до итога врача", step7),
             ("Отказ и пересмотр плана", step8),
             ("Направление партнёру", step9),
             ("Учебная маммография без утверждённого правила", step10),
             ("Шлюз", step11)]
    print(f"Смоук-проверка на пациенте {ref}", flush=True)
    for number, (title, run) in enumerate(steps, 1):
        try:
            detail = run()
        except StandError as exc:
            print(f"[!!] {number:>2}. {title}: {exc}", flush=True)
            print(f"Смоук-проверка не прошла на шаге {number} из {len(steps)}.", flush=True)
            return 1
        print(f"[ок] {number:>2}. {title}: {detail}", flush=True)
    print(f"Смоук-проверка пройдена: {len(steps)} шагов из {len(steps)}.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
