"""Fill the demo stand through public service APIs only. Synthetic people and studies."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from stand_api import (DEMO_DIR, StandError, clinic_signed, clinic_staff, confirm, env, expect, find_episode,
                       load_json, path_post, review, step_action, upload_kit, utf8_console)

HOME = "clinic-central"
COORDINATOR = "coordinator-natalia"
RADIOLOGIST = "radiologist-ershov"
THERAPIST = "therapist-sokolova"
PULMONOLOGIST = "pulmonologist-lebedev"

# patient_ref -> (kind, code, text, shareable, author_id, author_role)
ANAMNESIS = {
    "demo-patient-1": [("allergy", None, "Аллергия на пенициллин (крапивница)", True, THERAPIST, "physician"),
                       ("risk_factor", None, "Курит 10 лет, около пачки в день", True, THERAPIST, "physician"),
                       ("note", None, "Просит звонить после 18:00", False, COORDINATOR, "coordinator")],
    "demo-patient-2": [("family_history", None, "Рак молочной железы у матери в 58 лет", True, THERAPIST, "physician"),
                       ("note", None, "Предпочитает запись на утро", False, COORDINATOR, "coordinator")],
    "demo-patient-3": [("diagnosis", "J44", "Хроническая обструктивная болезнь лёгких", True, PULMONOLOGIST, "physician"),
                       ("medication", None, "Тиотропий, ингаляции ежедневно", True, PULMONOLOGIST, "physician"),
                       ("note", None, "Плохо слышит, лучше писать в мессенджер", False, COORDINATOR, "coordinator")],
    "demo-patient-4": [("surgery", None, "Артроскопия левого коленного сустава, 2019", True, THERAPIST, "physician"),
                       ("note", None, "Занимается бегом, просит раннюю запись", False, COORDINATOR, "coordinator")],
    "demo-patient-5": [("diagnosis", "I10", "Гипертоническая болезнь", True, THERAPIST, "physician"),
                       ("measurement", None, "АД 145/90 на последнем приёме", True, THERAPIST, "physician"),
                       ("note", None, "Работает посменно", False, COORDINATOR, "coordinator")],
    "demo-patient-6": [("risk_factor", None, "Бывший курильщик, бросил 5 лет назад", True, THERAPIST, "physician"),
                       ("note", None, "Связь только по телефону", False, COORDINATOR, "coordinator")],
    "demo-patient-7": [("allergy", None, "Аллергических реакций не отмечает", True, THERAPIST, "physician"),
                       ("note", None, "Обследование по направлению работодателя", False, COORDINATOR, "coordinator")],
}


def say(ok: bool, text: str) -> None:
    print(("[ок] " if ok else "[!!] ") + text, flush=True)


def stamp(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


class Seeder:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.kit_dir = state_dir / "kit"
        self.kit = load_json(self.kit_dir / "kit.json")
        self.people = load_json(DEMO_DIR / "people.demo.json")
        self.conclusions = load_json(DEMO_DIR / "conclusions.demo.json")
        self.registry: dict[str, dict] = {}
        self.patient_ids: dict[str, str] = {}
        self.now = datetime.now().astimezone()
        self.problems = 0
        self.real_image = os.environ.get("DEMO_IMAGE_MODE") == "real"

    # ---------- clinic ----------

    def register_patients(self) -> None:
        for person in self.people["patients"]:
            ref = person["patient_ref"]
            status, body = clinic_staff("POST", "/v1/patients", HOME, {
                "home_clinic_id": HOME, "patient_ref": ref, "full_name": person["full_name"],
                "birth_date": person["birth_date"], "sex": person["sex"], "contact": person["contact"]})
            patient_id = expect(status, body, 201, f"Регистрация {ref}")["patient"]["id"]
            self.patient_ids[ref] = patient_id
            for kind, code, text, shareable, author, role in ANAMNESIS[ref]:
                status, body = clinic_staff("POST", f"/v1/patients/{patient_id}/anamnesis", HOME, {
                    "kind": kind, "code": code, "text": text, "shareable": shareable,
                    "recorded_at": stamp(self.now - timedelta(days=90)), "author_id": author,
                    "author_role": role, "clinic_id": HOME})
                expect(status, body, 201, f"Анамнез {ref}")
        say(True, f"сервис клиники: {len(self.patient_ids)} пациентов в «{HOME}», у каждого анамнез")

    # ---------- image + path ----------

    def study(self, ref: str, *, confirm_it: bool) -> dict | None:
        """Upload the patient's kit study; confirm it as the radiologist. Returns the episode or None."""
        status, public = upload_kit(self.kit_dir, ref)
        job_id = public["id"]
        self.registry[job_id] = {"patient_ref": ref, "title": self.kit[ref]["title"], "kind": self.kit[ref]["kind"],
                                 "kit": ref}
        self.save_registry()
        self.last_status = public["status"]
        if public["status"] != "awaiting_physician":
            if confirm_it and self.real_image:
                say(True, f"{ref}: настоящий сервис снимков отправил исследование на ручной разбор "
                          f"({public['reason']}); дальше сценарий не идёт")
            elif confirm_it:
                self.problems += 1
                say(False, f"{ref}: исследование ушло на ручной разбор в сервисе снимков ({public['reason']}); "
                           f"сценарий дальше не идёт")
            return None
        if not confirm_it:
            return None
        job = review(job_id)
        code = job["result"]["findings"][0]["code"]
        confirmed = confirm(job_id, RADIOLOGIST, self.conclusions[code], code, ref)
        if confirmed["routing_status"] != "sent":
            raise StandError(f"{ref}: заключение не дошло до сервиса пути ({confirmed['routing_status']})")
        episode = find_episode(job_id)
        if episode is None:
            raise StandError(f"{ref}: эпизод не найден по source_report_id {job_id}")
        return episode

    def clinical_step(self, episode: dict) -> dict:
        return next(s for s in episode["plan_steps"] if s["kind"] != "manual_review" and s["status"] == "open")

    def check(self, ok: bool, text: str) -> None:
        self.problems += not ok
        say(ok, text)

    def save_registry(self) -> None:
        (self.state_dir / "studies.json").write_text(json.dumps(self.registry, ensure_ascii=False, indent=2),
                                                     encoding="utf-8")

    def run(self) -> int:
        self.register_patients()

        episode = self.study("demo-patient-1", confirm_it=True)
        if episode:
            self.check(episode["status"] == "active", "demo-patient-1: эпизод активен, шаг открыт, пациент ещё не записался")

        episode = self.study("demo-patient-2", confirm_it=True)
        if episode:
            self.check(episode["status"] == "manual_review" and episode["manual_reason"] == "rule_not_approved",
                       "demo-patient-2: ручной разбор, правило не утверждено")

        episode = self.study("demo-patient-3", confirm_it=True)
        if episode:
            step = self.clinical_step(episode)
            visit = (self.now - timedelta(days=20)).replace(hour=10, minute=0, second=0)
            step_action(episode["id"], step["id"], "offer", COORDINATOR, "Записан по телефону", appointment_at=stamp(visit))
            step_action(episode["id"], step["id"], "confirm", COORDINATOR, "Пациент подтвердил запись")
            step_action(episode["id"], step["id"], "attend", COORDINATOR, "Пациент пришёл на приём")
            path_post(f"/v1/episodes/{episode['id']}/outcomes", {"step_id": step["id"], "outcome": {
                "source": "staff_form", "event_id": "seed-demo-patient-3-visit-1", "physician_id": PULMONOLOGIST,
                "confirmed_at": stamp(visit + timedelta(hours=1)),
                "summary": "Очаг требует контроля. Назначена контрольная КТ.",
                "next_steps": [{"kind": "test", "description": "Контрольная КТ органов грудной клетки",
                                "owner": COORDINATOR, "due_at": stamp(self.now - timedelta(days=6)),
                                "continue_on": "confirmed_outcome"}]}})
            status, body = clinic_signed("/v1/referrals", {
                "patient_ref": "demo-patient-3", "from_clinic_id": HOME, "to_clinic_id": "clinic-partner-1",
                "reason": "Контрольная КТ органов грудной клетки", "created_by": COORDINATOR})
            expect(status, body, 201, "Направление demo-patient-3")
            say(True, "demo-patient-3: первый приём с итогом врача, контрольная КТ просрочена, направление на Лесную предложено")

        episode = self.study("demo-patient-4", confirm_it=True)
        if episode:
            step = self.clinical_step(episode)
            today = self.now.replace(hour=16, minute=30, second=0)
            if today <= self.now:
                today = min(self.now + timedelta(minutes=15), self.now.replace(hour=23, minute=59))
            step_action(episode["id"], step["id"], "offer", COORDINATOR, "Записана через приложение", appointment_at=stamp(today))
            step_action(episode["id"], step["id"], "confirm", COORDINATOR, "Пациентка подтвердила запись")
            say(True, "demo-patient-4: запись подтверждена на сегодня")

        episode = self.study("demo-patient-5", confirm_it=True)
        if episode:
            step = self.clinical_step(episode)
            step_action(episode["id"], step["id"], "offer", COORDINATOR, "Записан по телефону",
                        appointment_at=stamp(self.now - timedelta(hours=2)))
            step_action(episode["id"], step["id"], "confirm", COORDINATOR, "Пациент подтвердил запись")
            step_action(episode["id"], step["id"], "attend", COORDINATOR, "Пациент пришёл на приём")
            say(True, "demo-patient-5: визит состоялся, итог врача ещё не внесён")

        self.study("demo-patient-6", confirm_it=False)
        if self.real_image:
            say(True, f"demo-patient-6: настоящий сервис снимков, статус {self.last_status}, эпизода нет")
        else:
            self.check(self.last_status == "awaiting_physician", "demo-patient-6: исследование ждёт проверки врача, эпизода нет")

        self.study("demo-patient-7", confirm_it=False)
        self.check(self.last_status == "manual_review",
                   "demo-patient-7: ручной разбор в сервисе снимков, эпизода нет"
                   + ("" if self.real_image else " (находок нет)"))

        print(f"Реестр исследований: {self.state_dir / 'studies.json'}", flush=True)
        return 1 if self.problems else 0


def main() -> int:
    utf8_console()
    state_dir = Path(env("DEMO_STATE_DIR"))
    try:
        return Seeder(state_dir).run()
    except StandError as exc:
        say(False, f"наполнение остановлено: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
