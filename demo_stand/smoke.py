"""End-to-end smoke check of the demo stand on its own synthetic patient, services and gateway."""
from __future__ import annotations

import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path

from stand_api import (DEMO_DIR, GATEWAY, Gateway, StandError, call, clinic_signed, clinic_staff, confirm, env, expect,
                       find_episode, load_json, path_get, path_post, review, step_action, upload_kit, upload_study, utf8_console)
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

    def leaks(body: object) -> list[str]:
        text = str(body)
        return [w for w in ("'result'", "'draft'", "confidence", "model_version", "'reason'", "оценка") if w in text]

    def step12():
        patient = ctx["patient"] = Gateway("patient", patient_ref=ref)
        archive = (kit_dir / load_json(kit_dir / "kit.json")["smoke-ct"]["archive"]).read_bytes()
        status, body = patient.call("POST", "/api/patient/studies?task=ct_general&consent=1", raw=archive,
                                    content_type="application/zip")
        study = expect(status, body, 201, "Загрузка через шлюз")["study"]
        check(study["status"] == "awaiting" and not leaks(body), f"ответ пациенту: {body}")
        ctx["gw_job"] = study["id"]
        status, body = patient.call("GET", "/api/patient/studies")
        mine = [s for s in expect(status, body, 200, "Исследования пациента")["studies"] if s["id"] == ctx["gw_job"]]
        check(mine and "conclusion" not in mine[0] and not leaks(body), f"до подтверждения пациент видит лишнее: {mine}")
        status, _ = patient.call("GET", f"/api/patient/studies/{ctx['gw_job']}/images/x.png")
        check(status == 404, f"пациент получил срез до подтверждения: {status}")
        return "201, статус «ждёт врача», шлюз сам собрал манифест, срез пациенту закрыт"

    def step13():
        doctor = ctx["doctor"] = Gateway("doctor")
        status, body = doctor.call("GET", "/api/doctor/studies")
        check(any(s["id"] == ctx["gw_job"] for s in expect(status, body, 200, "Список врача")["studies"]), "врач не видит исследование")
        status, body = doctor.call("GET", f"/api/doctor/studies/{ctx['gw_job']}")
        study = expect(status, body, 200, "Исследование у врача")["study"]
        check(len(study["images"]) == 3 and study["demo"] and "confidence" not in study["findings"][0], f"исследование: {study}")
        status, png = doctor.call("GET", f"/api/doctor/studies/{ctx['gw_job']}/images/{study['findings'][0]['sop_uid']}.png")
        check(status == 200 and isinstance(png, bytes) and png.startswith(b"\x89PNG"), f"PNG: {status}")
        template = study["templates"]["DEMO_CT_INFILTRATE"]
        check(template == conclusions["DEMO_CT_INFILTRATE"], "заготовка не из conclusions.demo.json")
        status, body = doctor.call("POST", f"/api/doctor/studies/{ctx['gw_job']}/confirm", {"conclusion": template})
        result = expect(status, body, 200, "Подтверждение через шлюз")
        check(result["next"].get("step") == "Приём терапевта в течение 24 часов", f"что дальше: {result['next']}")
        return f"в списке, 3 среза, PNG {len(png)} байт, подтверждено, шаг «{result['next']['step']}»"

    def step14():
        status, body = ctx["patient"].call("GET", "/api/patient/studies")
        study = next(s for s in expect(status, body, 200, "Исследования пациента")["studies"] if s["id"] == ctx["gw_job"])
        check(study["status"] == "confirmed" and study["conclusion"] == conclusions["DEMO_CT_INFILTRATE"], f"заключение: {study}")
        check(study["explanation"]["seen"] != "Заключение готово." and study["episode"]["steps"][0]["status"] == "open",
              f"объяснение или шаг: {study}")
        check(not leaks(body), f"пациенту ушло лишнее: {leaks(body)}")
        status, png = ctx["patient"].call("GET", f"/api/patient/studies/{ctx['gw_job']}/images/{study['image']['sop_uid']}.png")
        check(status == 200 and png.startswith(b"\x89PNG"), f"срез пациенту: {status}")
        return f"заключение врача, объяснение, шаг «{study['episode']['steps'][0]['description']}», срез с подписью «{study['image']['label']}»"

    def step15():
        archive, _ = build_study("ct", variant=98)
        status, body = ctx["patient"].call("POST", "/api/patient/studies?task=ct_general&consent=1", raw=archive,
                                           content_type="application/zip")
        study = expect(status, body, 201, "Чужой архив через шлюз")["study"]
        check(study["status"] == "manual", f"статус {study}")
        staff = Gateway("staff")
        status, body = staff.call("GET", "/api/staff/studies/manual")
        check(any(s["id"] == study["id"] for s in expect(status, body, 200, "Ручное описание")["manual"]) and not leaks(body),
              f"координатор не видит исследование или видит лишнее: {body}")
        status, body = ctx["doctor"].call("GET", f"/api/doctor/studies/{study['id']}")
        detail = expect(status, body, 200, "Ручное описание у врача")["study"]
        check(detail["findings"] == [] and detail["reason"]["text"], f"у врача: {detail}")
        return f"ручное описание, у координатора в группе, врачу причина: «{detail['reason']['text']}»"

    def step16():
        staff = Gateway("staff")
        status, body = staff.call("POST", "/api/demo/studies/smoke-mg/submit", {"patient_ref": ref})
        study = expect(status, body, 201, "Маммография через шлюз")["study"]
        status, body = ctx["doctor"].call("GET", f"/api/doctor/studies/{study['id']}")
        labels = [i["label"] for i in expect(status, body, 200, "Маммография у врача")["study"]["images"]]
        check(labels == ["Проекция L-CC", "Проекция L-MLO", "Проекция R-CC", "Проекция R-MLO"], f"проекции: {labels}")
        status, body = ctx["doctor"].call("POST", f"/api/doctor/studies/{study['id']}/confirm",
                                          {"conclusion": conclusions["DEMO_MG_DENSITY"]})
        nxt = expect(status, body, 200, "Подтверждение маммографии")["next"]
        check(nxt.get("status") == "manual_review", f"что дальше: {nxt}")
        body = expect(*staff.call("GET", f"/api/staff/episodes/{nxt['episode_id']}/route-candidates"), 200, "Кандидаты маммографии")
        clinics = sorted(c["clinic_id"] for c in body["candidates"])
        check(clinics == [HOME, "clinic-partner-2"], f"кандидаты маммографии: {clinics}")
        return f"четыре проекции, после подтверждения — ручной разбор: «{nxt['reason']}»; кандидаты — своя клиника и «Опора»"

    def step17():
        staff = ctx["staff"] = Gateway("staff")
        partner = ctx["partner"] = Gateway("partner", clinic_id=PARTNER)
        # the referral of step 9 is still accepted: the partner closes it, so a new one can be proposed
        old = next(r for r in expect(*partner.call("GET", "/api/partner/referrals"), 200, "Направления партнёра")["referrals"]
                   if r["patient_ref"] == ref and r["status"] == "accepted")
        expect(*partner.call("POST", f"/api/partner/referrals/{old['id']}/complete", {}), 200, "Завершение старого направления")
        episode = find_episode(ctx["gw_job"])
        ctx["gw_episode"], ctx["gw_step"] = episode["id"], episode["plan_steps"][0]["id"]
        body = expect(*staff.call("GET", f"/api/staff/episodes/{episode['id']}/route-candidates"), 200, "Кандидаты через шлюз")
        roles = {(c["clinic_id"], c["role"]) for c in body["candidates"]}
        check({(HOME, "home"), (PARTNER, "partner")} <= roles, f"кандидаты: {body}")
        body = expect(*staff.call("POST", f"/api/staff/episodes/{episode['id']}/steps/{ctx['gw_step']}/referral",
                                  {"to_clinic_id": PARTNER, "reason": "Смоук: КТ у партнёра"}), 201, "Направление через шлюз")
        check(body["referral"]["status"] == "proposed" and body["link"]["step_id"] == ctx["gw_step"], f"направление: {body}")
        ctx["gw_referral"] = body["referral"]
        return "кандидаты «у нас» и партнёр, направление создано и связано с шагом"

    def step18():
        partner, referral = ctx["partner"], ctx["gw_referral"]
        card_route = f"/api/partner/patients/{referral['patient_id']}/card"
        before = expect(*partner.call("GET", card_route), 200, "Карта у партнёра до принятия")
        check(not {"full_name", "birth_date", "contact"} & set(before["patient"]) and "Внутренняя заметка" not in str(before),
              f"партнёр видит лишнее до принятия: {before['patient']}")
        expect(*partner.call("POST", f"/api/partner/referrals/{referral['id']}/accept", {"note": "Ждём пациента"}), 200, "Принятие")
        after = expect(*partner.call("GET", card_route), 200, "Карта у партнёра после принятия")
        check(after["patient"].get("full_name") == "Пациент смоук-проверки", f"после принятия: {after['patient']}")
        return "до принятия без ФИО и внутренних записей, после принятия ФИО есть"

    def step19():
        staff, partner = ctx["staff"], ctx["partner"]
        when = stamp(now + timedelta(days=3))
        body = expect(*staff.call("POST", f"/api/staff/episodes/{ctx['gw_episode']}/steps/{ctx['gw_step']}/confirm",
                                  {"partner_time": when, "partner_clinic_id": PARTNER}), 200, "Запись у партнёра")
        step = next(s for s in body["episode"]["steps"] if s["id"] == ctx["gw_step"])
        check(step["status"] == "confirmed", f"шаг после записи: {step}")
        before = len(path_get(f"/v1/episodes/{ctx['gw_episode']}")["audit_events"])
        expect(*partner.call("POST", f"/api/partner/referrals/{ctx['gw_referral']['id']}/complete", {}), 200, "Услуга оказана")
        check(len(path_get(f"/v1/episodes/{ctx['gw_episode']}")["audit_events"]) == before, "завершение у партнёра изменило эпизод")
        refs = expect(*staff.call("GET", "/api/staff/referrals"), 200, "Направления координатора")["referrals"]
        mine = next(r for r in refs if r["id"] == ctx["gw_referral"]["id"])
        check(mine["status"] == "completed" and mine["link"] == {"episode_id": ctx["gw_episode"], "step_id": ctx["gw_step"]},
              f"направление у координатора: {mine}")
        body = expect(*staff.call("POST", f"/api/staff/episodes/{ctx['gw_episode']}/steps/{ctx['gw_step']}/attend", {}), 200, "Визит")
        check(next(s for s in body["episode"]["steps"] if s["id"] == ctx["gw_step"])["status"] == "attended", "визит не отмечен")
        return "время партнёра записано, «услуга оказана» не тронула эпизод, координатор отметил визит сам"

    def step20():
        body = expect(*Gateway("staff").call("POST", "/api/staff/rules/dry-run", {"study_type": "xray", "anatomy": "CHEST",
                      "protocol_name": "CHEST_PA", "finding_code": "DEMO_XR_INFILTRATE"}), 200, "Песочница правил")
        check(body["manual_reason"] is None and [s["description"] for s in body["steps"]] == ["Приём терапевта в течение 24 часов"],
              f"песочница: {body}")
        return "рентген грудной клетки → «Приём терапевта в течение 24 часов» по утверждённому правилу"

    def step21():
        patient = Gateway("patient", patient_ref=ref)
        archive = (kit_dir / load_json(kit_dir / "kit.json")["smoke-xr"]["archive"]).read_bytes()
        study = expect(*patient.call("POST", "/api/patient/studies?task=xr_general&consent=1", raw=archive,
                                     content_type="application/zip"), 201, "Рентген через шлюз")["study"]
        check(study["status"] == "awaiting", f"статус рентгена: {study}")
        doctor = Gateway("doctor")
        detail = expect(*doctor.call("GET", f"/api/doctor/studies/{study['id']}"), 200, "Рентген у врача")["study"]
        check([i["label"] for i in detail["images"]] == ["Проекция PA"] and detail["findings"][0]["place"] == "Проекция PA",
              f"рентген у врача: {detail['images']}, {detail['findings']}")
        status, png = doctor.call("GET", f"/api/doctor/studies/{study['id']}/images/{detail['images'][0]['sop_uid']}.png")
        check(status == 200 and png.startswith(b"\x89PNG"), f"PNG рентгена: {status}")
        nxt = expect(*doctor.call("POST", f"/api/doctor/studies/{study['id']}/confirm",
                                  {"conclusion": detail["templates"]["DEMO_XR_INFILTRATE"]}), 200, "Подтверждение рентгена")["next"]
        check(nxt.get("step") == "Приём терапевта в течение 24 часов", f"что дальше: {nxt}")
        episode = find_episode(study["id"])
        check(episode["source_report"]["study_type"] == "xray", f"study_type: {episode['source_report']['study_type']}")
        mine = next(s for s in expect(*patient.call("GET", "/api/patient/studies"), 200, "Исследования")["studies"] if s["id"] == study["id"])
        check(mine["title"] == "Рентгенография органов грудной клетки" and mine["explanation"]["seen"].startswith("В нижней части правого лёгкого"),
              f"у пациента: {mine['title']}, {mine['explanation']}")
        return "проекция PA, PNG, подтверждение → study_type xray → «Приём терапевта в течение 24 часов», объяснение у пациента"

    def step22():
        # the stand gives no API key to checks: the assistant is off, and nothing else changes
        patient, doctor = Gateway("patient", patient_ref=ref), Gateway("doctor")
        status = expect(*patient.call("GET", "/api/assistant/status"), 200, "Состояние помощника")
        check(status == {"enabled": False}, f"помощник на смоуке: {status}")
        archive = (kit_dir / load_json(kit_dir / "kit.json")["smoke-xr"]["archive"]).read_bytes()
        study = expect(*patient.call("POST", "/api/patient/studies?task=xr_general&consent=1", raw=archive,
                                     content_type="application/zip"), 201, "Рентген для помощника")["study"]
        detail = expect(*doctor.call("GET", f"/api/doctor/studies/{study['id']}"), 200, "Рентген у врача")["study"]
        template = detail["templates"]["DEMO_XR_INFILTRATE"]
        code, body = doctor.call("POST", f"/api/doctor/studies/{study['id']}/assistant/rewrite",
                                 {"finding_code": "DEMO_XR_INFILTRATE", "text": template})
        check(code == 503 and body["error"]["code"] == "assistant_unavailable", f"помощник без ключа: {code} {body}")
        nxt = expect(*doctor.call("POST", f"/api/doctor/studies/{study['id']}/confirm", {"conclusion": template}),
                     200, "Подтверждение без помощника")["next"]
        check(nxt.get("step") == "Приём терапевта в течение 24 часов", f"что дальше: {nxt}")
        code, body = patient.call("POST", f"/api/patient/studies/{study['id']}/assistant/explain", {})
        check(code == 503 and body["error"]["code"] == "assistant_unavailable", f"пояснение без ключа: {code} {body}")
        return "выключен, «Улучшить формулировку» — 503, подтверждение прошло, шаг тот же, пояснение — 503"

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
             ("Шлюз", step11),
             ("Пациент загружает учебную КТ через шлюз", step12),
             ("Врач: список, срез PNG, подтверждение", step13),
             ("Пациент видит заключение, объяснение и шаг", step14),
             ("Архив не из учебного набора через шлюз", step15),
             ("Маммография через шлюз", step16),
             ("Кандидаты и направление через шлюз", step17),
             ("Партнёр принимает направление", step18),
             ("Запись у партнёра, услуга оказана, визит", step19),
             ("Песочница правил: рентген", step20),
             ("Рентгенограмма через шлюз до шага плана", step21),
             ("ИИ-помощник без ключа", step22)]
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
