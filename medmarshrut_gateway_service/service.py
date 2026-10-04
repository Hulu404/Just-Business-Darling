"""Gateway: serves the web app, keeps demo-role sessions and calls the three services on the browser's behalf."""
from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import dataclass, field
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote, unquote, urlsplit

from errors import GatewayError
from sessions import ROLES, People, Session, SessionStore, cookie_name
from store import GatewayStore, StoreConflict, StoreError
from upstream import Upstream, patient_ref, service_url, text
from views import patient_episode, staff_episode

MAX_BODY = 32 * 1024
WEB_DIR = Path(__file__).resolve().parent / "web"
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                ".ico": "image/x-icon"}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
IMAGING_MODES = {"demo-scripted", "model", "no-model"}
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
DETAIL_ROLES = {"staff", "doctor", "partner"}
DEFAULT_PATIENT = "demo-patient-1"
DEFAULT_PARTNER = "clinic-partner-1"
REPO = Path(__file__).resolve().parents[1]


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    reviewer_token: str
    path_admin_token: str
    path_mis_token: str
    clinic_secret: str
    clinic_tokens: dict[str, str]  # clinic_id -> staff token
    home_clinic: str
    state_dir: Path
    people_path: Path
    imaging_mode: str
    urls: dict[str, str]
    port: int
    db_dsn: str = ""
    db_schema: str = ""


def load_config(env: dict[str, str]) -> Config:
    def secret(name: str, required: bool = True) -> str:
        value = env.get(name, "")
        if not value and not required:
            return ""
        if len(value) < 16:
            raise ConfigError(f"{name} is required and must have at least 16 characters")
        return value

    values = {name: secret(name) for name in ("REVIEWER_TOKEN", "PATH_ADMIN_TOKEN", "CLINIC_SHARED_SECRET")}
    try:
        staff = json.loads(env.get("CLINIC_STAFF_TOKENS", ""))
    except ValueError:
        raise ConfigError("CLINIC_STAFF_TOKENS is required and must be a JSON object token -> clinic_id") from None
    if (not isinstance(staff, dict) or not staff
            or not all(isinstance(k, str) and len(k) >= 16 and isinstance(v, str) and v for k, v in staff.items())):
        raise ConfigError("CLINIC_STAFF_TOKENS must map tokens of at least 16 characters to clinic ids")
    clinic_tokens = {clinic: token for token, clinic in staff.items()}
    home = env.get("GATEWAY_HOME_CLINIC") or "clinic-central"
    if home not in clinic_tokens:
        raise ConfigError(f"CLINIC_STAFF_TOKENS has no staff token for GATEWAY_HOME_CLINIC ({home})")
    if not env.get("GATEWAY_STATE_DIR"):
        raise ConfigError("GATEWAY_STATE_DIR is required: the stand state folder")
    mode = env.get("GATEWAY_IMAGING_MODE") or "no-model"
    if mode not in IMAGING_MODES:
        raise ConfigError(f"GATEWAY_IMAGING_MODE must be one of {sorted(IMAGING_MODES)}")
    try:
        urls = {service: service_url(env.get(f"{service.upper()}_URL"), service) for service in ("image", "path", "clinic")}
        port = int(env.get("GATEWAY_PORT") or 8763)
    except ValueError as exc:
        raise ConfigError(str(exc) if "_URL" in str(exc) else "GATEWAY_PORT must be a port number") from None
    if not 0 <= port <= 65535:
        raise ConfigError("GATEWAY_PORT must be a port number")
    return Config(values["REVIEWER_TOKEN"], values["PATH_ADMIN_TOKEN"], secret("PATH_MIS_TOKEN", required=False),
                  values["CLINIC_SHARED_SECRET"], clinic_tokens, home, Path(env["GATEWAY_STATE_DIR"]),
                  Path(env.get("GATEWAY_PEOPLE") or REPO / "demo_stand" / "people.demo.json"), mode, urls, port,
                  env.get("GATEWAY_DATABASE_URL", ""), env.get("GATEWAY_DB_SCHEMA", ""))


@dataclass
class Context:
    role: str | None
    session: Session | None
    body: dict
    params: dict[str, str]
    cookies: list[str] = field(default_factory=list)
    session_cookie: str | None = None
    query: dict[str, str] = field(default_factory=dict)


Handler = Callable[[Context], tuple[int, dict]]


class Gateway:
    def __init__(self, config: Config, *, timeout: float | None = None, store: GatewayStore | None = None):
        self.config = config
        self.port = config.port
        self.people = People(config.people_path)
        self.sessions = SessionStore()
        self.store = store
        kwargs = {"timeout": timeout} if timeout else {}
        self.upstream = Upstream(config.urls, reviewer_token=config.reviewer_token,
                                 path_admin_token=config.path_admin_token, path_mis_token=config.path_mis_token,
                                 clinic_secret=config.clinic_secret, clinic_tokens=config.clinic_tokens, **kwargs)
        # Route -> handler. A route works only with a row in `access` (or in `public`): default is deny.
        self.routes: dict[tuple[str, str], Handler] = {
            ("GET", "/api/health"): self.health,
            ("POST", "/api/session"): self.session_create,
            ("GET", "/api/session"): self.session_get,
            ("DELETE", "/api/session"): self.session_delete,
            ("GET", "/api/catalog"): self.catalog,
            ("GET", "/api/slots"): self.slots,
            ("GET", "/api/patient/episodes"): self.patient_episodes,
            ("GET", "/api/patient/episodes/{id}"): self.patient_episode,
            ("GET", "/api/staff/episodes"): self.staff_episodes,
            ("GET", "/api/staff/episodes/{id}"): self.staff_episode,
            ("POST", "/api/patient/episodes/{id}/steps/{step}/book"): self.patient_book,
            ("POST", "/api/patient/episodes/{id}/steps/{step}/confirm"): self.patient_confirm,
            ("POST", "/api/patient/episodes/{id}/steps/{step}/ask"): self.patient_ask,
            ("POST", "/api/staff/episodes/{id}/steps/{step}/complete"): self.staff_complete,
            ("POST", "/api/staff/episodes/{id}/steps/{step}/{action}"): self.staff_transition,
            ("POST", "/api/staff/episodes/{id}/{action}"): self.staff_episode_action,
            ("GET", "/api/doctor/visits"): self.doctor_visits,
            ("POST", "/api/doctor/episodes/{id}/manual-plan"): self.doctor_manual_plan,
            ("POST", "/api/doctor/episodes/{id}/revise-plan"): self.doctor_revise_plan,
            ("POST", "/api/doctor/episodes/{id}/steps/{step}/outcome"): self.doctor_outcome,
            ("GET", "/api/staff/rules"): self.staff_rules,
            ("POST", "/api/staff/rules/dry-run"): self.staff_rules_dry_run,
            ("GET", "/api/staff/metrics"): self.staff_metrics,
        }
        self.public: set[tuple[str, str]] = {("GET", "/api/health"), ("POST", "/api/session")}
        self.access: dict[tuple[str, str], set[str]] = {
            ("GET", "/api/session"): set(ROLES),
            ("DELETE", "/api/session"): set(ROLES),
            ("GET", "/api/catalog"): set(ROLES),
            ("GET", "/api/slots"): {"patient", "staff"},
            ("GET", "/api/patient/episodes"): {"patient"},
            ("GET", "/api/patient/episodes/{id}"): {"patient"},
            ("GET", "/api/staff/episodes"): {"staff", "doctor"},
            ("GET", "/api/staff/episodes/{id}"): {"staff", "doctor"},
            ("POST", "/api/patient/episodes/{id}/steps/{step}/book"): {"patient"},
            ("POST", "/api/patient/episodes/{id}/steps/{step}/confirm"): {"patient"},
            ("POST", "/api/patient/episodes/{id}/steps/{step}/ask"): {"patient"},
            ("POST", "/api/staff/episodes/{id}/steps/{step}/{action}"): {"staff"},
            ("POST", "/api/staff/episodes/{id}/steps/{step}/complete"): {"staff"},
            ("POST", "/api/staff/episodes/{id}/{action}"): {"staff"},
            ("GET", "/api/doctor/visits"): {"doctor"},
            ("POST", "/api/doctor/episodes/{id}/manual-plan"): {"doctor"},
            ("POST", "/api/doctor/episodes/{id}/revise-plan"): {"doctor"},
            ("POST", "/api/doctor/episodes/{id}/steps/{step}/outcome"): {"doctor"},
            ("GET", "/api/staff/rules"): {"staff", "doctor"},
            ("POST", "/api/staff/rules/dry-run"): {"staff", "doctor"},
            ("GET", "/api/staff/metrics"): {"staff"},
        }

    def allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def match(self, method: str, path: str) -> tuple[tuple[str, str], dict[str, str]] | None:
        segments = path.strip("/").split("/")
        for key in self.routes:
            if key[0] != method:
                continue
            pattern = key[1].strip("/").split("/")
            if len(pattern) != len(segments):
                continue
            params = {}
            for want, got in zip(pattern, segments):
                if want.startswith("{") and want.endswith("}") and got:
                    params[want[1:-1]] = got
                elif want != got:
                    break
            else:
                return key, params
        return None

    # ---------- handlers ----------

    def health(self, ctx: Context) -> tuple[int, dict]:
        return 200, {"gateway": "ok", "auth": "demo-roles", "imaging_mode": self.config.imaging_mode,
                     "services": self.upstream.health_all()}

    def session_create(self, ctx: Context) -> tuple[int, dict]:
        body = ctx.body
        role = body.get("role")
        if role not in ROLES:
            raise GatewayError(400, "invalid_input", "Выберите роль: пациент, сотрудник, врач или партнёр.")
        if role != ctx.role:
            raise GatewayError(400, "invalid_input", "Роль в запросе не совпадает с ролью окна. Обновите страницу.")
        allowed = {"role", "patient_ref"} if role == "patient" else {"role", "clinic_id"} if role == "partner" else {"role"}
        if set(body) - allowed:
            raise GatewayError(400, "invalid_input", f"Лишние поля для роли: {', '.join(sorted(set(body) - allowed))}.")
        home = self.config.home_clinic
        if role == "patient":
            ref = patient_ref(body.get("patient_ref", DEFAULT_PATIENT))
            card = self.upstream.patient_by_ref(ref)
            if card is None:
                raise GatewayError(400, "unknown_patient", f"Пациента «{ref}» нет в сервисе клиники. Проверьте псевдоним.")
            if card.get("home_clinic_id") != home:
                raise GatewayError(400, "foreign_patient", "Этот пациент наблюдается в другой клинике и войти здесь не может.")
            if card.get("status") != "active":
                raise GatewayError(400, "inactive_patient", "Карта этого пациента не активна. Обратитесь в регистратуру.")
            person = self.people.patients.get(ref, {})
            session = self.sessions.create(role, person_id=ref, name=person.get("name") or "Пациент", patient_ref=ref)
        elif role == "partner":
            clinic = text(body.get("clinic_id", DEFAULT_PARTNER), "clinic_id", 128)
            person = self.people.partner(clinic)
            if clinic == home or clinic not in self.upstream.clinics_with_staff() or person is None:
                raise GatewayError(400, "unknown_clinic", "Такой клиники-партнёра на стенде нет. Выберите другую.")
            session = self.sessions.create(role, person_id=person["id"], name=person["name"], clinic_id=clinic)
        else:
            person = self.people.person(self.people.roles[role])
            session = self.sessions.create(role, person_id=person["id"], name=person["name"], clinic_id=home)
        self.sessions.delete(ctx.session_cookie)
        ctx.cookies.append(f"{cookie_name(role)}={session.id}; HttpOnly; SameSite=Strict; Path=/")
        return 201, session.public()

    def session_get(self, ctx: Context) -> tuple[int, dict]:
        return 200, ctx.session.public()

    def session_delete(self, ctx: Context) -> tuple[int, dict]:
        self.sessions.delete(ctx.session.id)
        ctx.cookies.append(f"{cookie_name(ctx.role)}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
        return 200, {"status": "closed"}

    def data_store(self) -> GatewayStore:
        if self.store is None:
            raise GatewayError(503, "database_unavailable", "База шлюза недоступна. Проверьте настройки и повторите действие.")
        return self.store

    def _episodes(self) -> list[dict]:
        ids = self.upstream.json("path", "GET", "/v1/episodes", auth="path_admin").get("episode_ids", [])
        return [self.upstream.json("path", "GET", "/v1/episodes/" + quote(eid, safe=""), auth="path_admin")
                for eid in ids]

    def _one_episode(self, episode_id: str) -> dict:
        return self.upstream.json("path", "GET", "/v1/episodes/" + quote(episode_id, safe=""), auth="path_admin")

    def _owned_episode(self, ctx: Context, episode_id: str) -> dict:
        raw = self._one_episode(episode_id)
        if (raw.get("source_report") or {}).get("patient_ref") != ctx.session.patient_ref:
            raise GatewayError(404, "not_found", "Такого обращения у вас нет. Откройте «Мой план».")
        return raw

    def _explanation(self, raw: dict) -> dict | None:
        code = (raw.get("source_report") or {}).get("finding_code")
        return self.data_store().explanation(self.config.home_clinic, code) if code else None

    def catalog(self, ctx: Context) -> tuple[int, dict]:
        return 200, self.data_store().catalogue(self.config.home_clinic)

    def slots(self, ctx: Context) -> tuple[int, dict]:
        episode_id, step_id = ctx.query.get("episode"), ctx.query.get("step")
        if not episode_id or not step_id:
            raise GatewayError(400, "invalid_input", "Выберите шаг плана и попробуйте снова.")
        raw = self._owned_episode(ctx, episode_id) if ctx.role == "patient" else self._one_episode(episode_id)
        step = next((s for s in raw.get("plan_steps", []) if s.get("id") == step_id), None)
        if step is None or step.get("kind") == "manual_review":
            raise GatewayError(404, "not_found", "Шаг плана не найден. Обновите страницу.")
        return 200, {"slots": self.data_store().slots(self.config.home_clinic, step["description"]), "demo": True}

    def patient_episodes(self, ctx: Context) -> tuple[int, dict]:
        mine = [raw for raw in self._episodes()
                if (raw.get("source_report") or {}).get("patient_ref") == ctx.session.patient_ref]
        return 200, {"episodes": [patient_episode(raw, self._explanation(raw)) for raw in mine]}

    def patient_episode(self, ctx: Context) -> tuple[int, dict]:
        raw = self._owned_episode(ctx, ctx.params["id"])
        return 200, {"episode": patient_episode(raw, self._explanation(raw))}

    def _patient_names(self) -> dict[str, str]:
        body = self.upstream.json("clinic", "GET", "/v1/patients?limit=500",
                                  auth=("clinic_staff", self.config.home_clinic))
        return {p["patient_ref"]: p["full_name"] for p in body.get("patients", [])}

    def staff_episodes(self, ctx: Context) -> tuple[int, dict]:
        names = self._patient_names()
        pending = self.data_store().pending_patient_messages(self.config.home_clinic)
        pending_ids = {item["episode_id"] for item in pending}
        return 200, {"episodes": [staff_episode(raw, names.get((raw.get("source_report") or {}).get("patient_ref"), "Пациент не указан"),
                                                callback=raw["id"] in pending_ids)
                                  for raw in self._episodes()], "patient_requests": pending}

    def staff_episode(self, ctx: Context) -> tuple[int, dict]:
        raw = self._one_episode(ctx.params["id"])
        names = self._patient_names()
        name = names.get((raw.get("source_report") or {}).get("patient_ref"), "Пациент не указан")
        pending = self.data_store().pending_patient_messages(self.config.home_clinic)
        return 200, {"episode": staff_episode(raw, name, callback=any(item["episode_id"] == raw["id"] for item in pending)),
                     "patient_requests": [item for item in pending if item["episode_id"] == raw["id"]]}

    @staticmethod
    def _step(raw: dict, step_id: str) -> dict:
        step = next((s for s in raw.get("plan_steps", []) if s.get("id") == step_id), None)
        if step is None:
            raise GatewayError(404, "not_found", "Шаг плана не найден. Обновите страницу.")
        return step

    @staticmethod
    def _first_unfinished(raw: dict) -> dict | None:
        return next((s for s in raw.get("plan_steps", []) if s.get("status") not in {"completed", "superseded"}), None)

    @staticmethod
    def _path_route(episode_id: str, step_id: str, action: str) -> str:
        return "/v1/episodes/" + quote(episode_id, safe="") + "/steps/" + quote(step_id, safe="") + "/" + action

    def patient_book(self, ctx: Context) -> tuple[int, dict]:
        raw = self._owned_episode(ctx, ctx.params["id"])
        step = self._step(raw, ctx.params["step"])
        if raw.get("status") != "active" or step.get("status") not in {"open", "offered"} or self._first_unfinished(raw) != step:
            raise GatewayError(409, "step_unavailable", "Этот шаг пока нельзя записать. Обновите план.")
        slot_id = str(ctx.body.get("slot_id", ""))
        reservation, old_id = self.data_store().reserve_slot(self.config.home_clinic, ctx.session.patient_ref,
            raw["id"], step["id"], step["description"], slot_id, "patient", ctx.session.actor)
        if step["status"] == "open":
            try:
                self.upstream.json("path", "POST", self._path_route(raw["id"], step["id"], "offer"),
                    body={"actor": ctx.session.actor, "evidence": "Пациент выбрал время в личном кабинете",
                          "appointment_at": reservation["starts_at"]}, auth="path_admin")
            except GatewayError:
                if not reservation["reused"]:
                    self.data_store().undo_reservation(reservation["id"], old_id)
                raise
        try:
            updated = self.upstream.json("path", "POST", self._path_route(raw["id"], step["id"], "confirm"),
                body={"actor": ctx.session.actor, "evidence": "Пациент подтвердил запись в личном кабинете",
                      "appointment_at": reservation["starts_at"]}, auth="path_admin")
        except GatewayError:
            if step["status"] == "offered":
                if not reservation["reused"]:
                    self.data_store().undo_reservation(reservation["id"], old_id)
            raise
        self.data_store().appointment_status(reservation["id"], "confirmed")
        return 200, {"episode": patient_episode(updated, self._explanation(updated)), "appointment": reservation, "demo": True}

    def patient_confirm(self, ctx: Context) -> tuple[int, dict]:
        raw = self._owned_episode(ctx, ctx.params["id"])
        step = self._step(raw, ctx.params["step"])
        if raw.get("status") != "active" or step.get("status") != "offered":
            raise GatewayError(409, "step_unavailable", "Предложение уже изменилось. Обновите план.")
        appointment = self.data_store().appointment_for_step(raw["id"], step["id"])
        if appointment is None:
            raise GatewayError(409, "appointment_missing", "Время предложения не найдено. Попросите координатора предложить его снова.")
        updated = self.upstream.json("path", "POST", self._path_route(raw["id"], step["id"], "confirm"),
            body={"actor": ctx.session.actor, "evidence": "Пациент подтвердил предложенное время"}, auth="path_admin")
        self.data_store().appointment_status(appointment["id"], "confirmed")
        return 200, {"episode": patient_episode(updated, self._explanation(updated)), "demo": True}

    def patient_ask(self, ctx: Context) -> tuple[int, dict]:
        raw = self._owned_episode(ctx, ctx.params["id"])
        step = self._step(raw, ctx.params["step"])
        intent = ctx.body.get("intent")
        if intent not in {"later", "callback", "other_time"}:
            raise GatewayError(400, "invalid_input", "Выберите причину обращения к координатору.")
        body = text(ctx.body.get("message") or {"later": "Пока не готов записаться", "callback": "Перезвоните мне, пожалуйста",
                                                "other_time": "Нужно другое время"}[intent], "message", 1000)
        self.data_store().add_patient_message(self.config.home_clinic, ctx.session.patient_ref, ctx.session.actor,
                                               raw["id"], step["id"], intent, body)
        return 201, {"status": "sent"}

    def staff_transition(self, ctx: Context) -> tuple[int, dict]:
        action = ctx.params["action"]
        if action not in {"offer", "confirm", "attend", "cancel", "refuse", "lost_contact"}:
            raise GatewayError(404, "not_found", "Такого действия нет.")
        raw = self._one_episode(ctx.params["id"])
        step = self._step(raw, ctx.params["step"])
        body = {"actor": ctx.session.actor, "evidence": "Запись по звонку" if action in {"offer", "confirm"}
                else "Координатор отметил изменение записи"}
        reservation = None
        old_id = None
        if action in {"offer", "confirm"} and ctx.body.get("slot_id"):
            ref = (raw.get("source_report") or {}).get("patient_ref")
            if not ref:
                raise GatewayError(409, "missing_patient", "В обращении нет пациента. Передайте случай врачу на ручной разбор.")
            reservation, old_id = self.data_store().reserve_slot(self.config.home_clinic, ref, raw["id"], step["id"],
                step["description"], str(ctx.body["slot_id"]), "staff", ctx.session.actor)
            body["appointment_at"] = reservation["starts_at"]
        elif action == "offer":
            raise GatewayError(400, "invalid_input", "Выберите время для предложения пациенту.")
        elif action == "confirm" and step.get("status") == "open":
            raise GatewayError(400, "invalid_input", "Выберите время для записи по звонку.")
        if action == "confirm" and step.get("status") == "open":
            try:
                self.upstream.json("path", "POST", self._path_route(raw["id"], step["id"], "offer"),
                    body={"actor": ctx.session.actor, "evidence": "Запись по звонку",
                          "appointment_at": reservation["starts_at"]}, auth="path_admin")
            except GatewayError:
                if not reservation["reused"]:
                    self.data_store().undo_reservation(reservation["id"], old_id)
                raise
        try:
            updated = self.upstream.json("path", "POST", self._path_route(raw["id"], step["id"], action),
                                         body=body, auth="path_admin")
        except GatewayError:
            if reservation is not None and not (action == "confirm" and step.get("status") == "open"):
                if not reservation["reused"]:
                    self.data_store().undo_reservation(reservation["id"], old_id)
            raise
        if reservation is not None and action == "confirm":
            self.data_store().appointment_status(reservation["id"], "confirmed")
        elif action == "confirm":
            current = self.data_store().appointment_for_step(raw["id"], step["id"])
            if current:
                self.data_store().appointment_status(current["id"], "confirmed")
        if action in {"cancel", "refuse", "lost_contact"}:
            self.data_store().cancel_appointment(raw["id"], step["id"])
        return 200, {"episode": staff_episode(updated, self._patient_names().get(
            (updated.get("source_report") or {}).get("patient_ref"), "Пациент не указан"))}

    def staff_complete(self, ctx: Context) -> tuple[int, dict]:
        raw = self._one_episode(ctx.params["id"])
        step = self._step(raw, ctx.params["step"])
        if step.get("kind") != "care_coordination":
            raise GatewayError(409, "step_unavailable", "Завершить этот шаг может только врач после итога приёма.")
        route = self._path_route(raw["id"], step["id"], "")[:-1]
        updated = self.upstream.json("path", "POST", route,
            body={"actor": ctx.session.actor, "evidence": "Координатор завершил организационный шаг"}, auth="path_admin")
        return 200, {"episode": staff_episode(updated, self._patient_names().get(
            (updated.get("source_report") or {}).get("patient_ref"), "Пациент не указан"))}

    def staff_episode_action(self, ctx: Context) -> tuple[int, dict]:
        action = ctx.params["action"]
        if action not in {"stop", "close"}:
            raise GatewayError(404, "not_found", "Такого действия нет.")
        raw = self._one_episode(ctx.params["id"])
        field = "reason" if action == "stop" else "outcome"
        value = text(ctx.body.get(field), field, 500)
        updated = self.upstream.json("path", "POST", "/v1/episodes/" + quote(raw["id"], safe="") + "/" + action,
                                    body={"actor": ctx.session.actor, field: value}, auth="path_admin")
        return 200, {"episode": staff_episode(updated, self._patient_names().get(
            (updated.get("source_report") or {}).get("patient_ref"), "Пациент не указан"))}

    @staticmethod
    def _doctor_steps(value: object, *, full: bool) -> list[dict]:
        if not isinstance(value, list) or not 0 < len(value) <= 50:
            raise GatewayError(400, "invalid_input", "Добавьте хотя бы один шаг плана (не больше 50).")
        result = []
        for item in value:
            if not isinstance(item, dict) or item.get("kind") not in {"appointment", "test", "follow_up", "care_coordination"}:
                raise GatewayError(400, "invalid_input", "Выберите вид шага и проверьте план.")
            description = text(item.get("description"), "description", 500)
            step = {"kind": item["kind"], "description": description}
            if full:
                due = item.get("due_at")
                if due is not None:
                    try:
                        from datetime import datetime
                        if datetime.fromisoformat(due).tzinfo is None:
                            raise ValueError
                    except (TypeError, ValueError):
                        raise GatewayError(400, "invalid_input", "Укажите срок с часовым поясом или оставьте его пустым.") from None
                step.update(owner="coordinator", due_at=due, continue_on="confirmed_outcome")
            result.append(step)
        return result

    def doctor_visits(self, ctx: Context) -> tuple[int, dict]:
        names = self._patient_names()
        visits = []
        for raw in self._episodes():
            for step in raw.get("plan_steps", []):
                if step.get("status") in {"confirmed", "attended"}:
                    visits.append({"episode": staff_episode(raw, names.get(
                        (raw.get("source_report") or {}).get("patient_ref"), "Пациент не указан")),
                                   "step_id": step["id"]})
        return 200, {"visits": visits}

    def doctor_manual_plan(self, ctx: Context) -> tuple[int, dict]:
        raw = self._one_episode(ctx.params["id"])
        if raw.get("status") != "manual_review":
            raise GatewayError(409, "episode_unavailable", "Обращение уже не ждёт плана врача. Обновите страницу.")
        steps = self._doctor_steps(ctx.body.get("steps"), full=False)
        updated = self.upstream.json("path", "POST", f"/v1/episodes/{quote(raw['id'], safe='')}/manual-plan",
                                    body={"actor": ctx.session.actor, "steps": steps}, auth="path_admin")
        return 200, {"episode": staff_episode(updated, self._patient_names().get(
            (updated.get("source_report") or {}).get("patient_ref"), "Пациент не указан"))}

    def doctor_revise_plan(self, ctx: Context) -> tuple[int, dict]:
        raw = self._one_episode(ctx.params["id"])
        steps = self._doctor_steps(ctx.body.get("steps"), full=True)
        reason = text(ctx.body.get("reason"), "reason", 500)
        updated = self.upstream.json("path", "POST", f"/v1/episodes/{quote(raw['id'], safe='')}/revise-plan",
            body={"physician_id": ctx.session.actor, "reason": reason, "steps": steps}, auth="path_admin")
        return 200, {"episode": staff_episode(updated, self._patient_names().get(
            (updated.get("source_report") or {}).get("patient_ref"), "Пациент не указан"))}

    def doctor_outcome(self, ctx: Context) -> tuple[int, dict]:
        raw = self._one_episode(ctx.params["id"])
        step = self._step(raw, ctx.params["step"])
        event_id = text(ctx.body.get("event_id"), "event_id", 128)
        summary = text(ctx.body.get("summary"), "summary", 1000)
        next_steps = self._doctor_steps(ctx.body.get("next_steps", []), full=True) if ctx.body.get("next_steps") else []
        content = {"summary": summary, "next_steps": next_steps}
        stamp = self.data_store().outcome_timestamp(event_id, raw["id"], step["id"], ctx.session.actor, content)
        if step.get("status") == "confirmed":
            raw = self.upstream.json("path", "POST", self._path_route(raw["id"], step["id"], "attend"),
                body={"actor": ctx.session.actor, "evidence": "Врач подтвердил, что приём состоялся"}, auth="path_admin")
        elif step.get("status") not in {"attended", "completed"}:
            raise GatewayError(409, "step_unavailable", "Этот визит ещё не подтверждён. Обновите страницу.")
        payload = {"step_id": step["id"], "outcome": {"source": "staff_form", "event_id": event_id,
            "physician_id": ctx.session.actor, "confirmed_at": stamp, **content}}
        result = self.upstream.json("path", "POST", f"/v1/episodes/{quote(raw['id'], safe='')}/outcomes",
                                    body=payload, auth="path_admin")
        updated = result["episode"]
        return 200, {"episode": staff_episode(updated, self._patient_names().get(
            (updated.get("source_report") or {}).get("patient_ref"), "Пациент не указан")),
            "duplicate": result.get("duplicate", False)}

    def staff_rules(self, ctx: Context) -> tuple[int, dict]:
        return 200, self.upstream.json("path", "GET", "/v1/rules", auth="path_admin")

    def staff_rules_dry_run(self, ctx: Context) -> tuple[int, dict]:
        allowed = {"study_type", "anatomy", "protocol_name", "finding_code"}
        if set(ctx.body) != allowed:
            raise GatewayError(400, "invalid_input", "Выберите исследование и находку из списка.")
        body = {key: text(ctx.body[key], key, 128) for key in allowed}
        return 200, self.upstream.json("path", "POST", "/v1/rules/dry-run", body=body, auth="path_admin")

    def staff_metrics(self, ctx: Context) -> tuple[int, dict]:
        metrics = self.upstream.json("path", "GET", "/v1/staff/metrics", auth="path_admin")
        episodes = self._episodes()
        metrics["funnel"] = {"reports": len(episodes), "active": sum(e.get("status") == "active" for e in episodes),
            "booked": sum(any(s.get("status") in {"confirmed", "attended", "completed"}
                              for s in e.get("plan_steps", [])) for e in episodes),
            "completed": sum(e.get("status") in {"completed", "closed"} for e in episodes)}
        metrics["demo"] = True
        return 200, metrics


def make_handler(gateway: Gateway):
    class RequestHandler(BaseHTTPRequestHandler):
        server_version = "MedMarshrutGateway"
        sys_version = ""

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _send(self, status: int, data: bytes, content_type: str, headers: dict | None = None,
                  cookies: list[str] | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            for cookie in cookies or []:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _json(self, status: int, body: dict, cookies: list[str] | None = None) -> None:
            self._send(status, json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8",
                       {"Cache-Control": "no-store"}, cookies)

        def _cookie(self, role: str) -> str | None:
            try:
                jar = SimpleCookie(self.headers.get("Cookie", ""))
            except CookieError:
                return None
            morsel = jar.get(cookie_name(role))
            return morsel.value if morsel else None

        def _body(self) -> dict:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise GatewayError(400, "invalid_input", "Неверный заголовок Content-Length.") from None
            if length > MAX_BODY or length < 0:
                raise GatewayError(413, "body_too_large", "Запрос слишком большой: не больше 32 КиБ.")
            if length == 0:
                return {}
            try:
                body = json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, ValueError):
                raise GatewayError(400, "invalid_input", "Тело запроса — не JSON. Обновите страницу и попробуйте снова.") from None
            if not isinstance(body, dict):
                raise GatewayError(400, "invalid_input", "Тело запроса должно быть JSON-объектом.")
            return body

        def _static(self, path: str) -> None:
            if path == "/":
                relative = "index.html"
            elif path.startswith("/assets/"):
                relative = unquote(path[len("/assets/"):])
            else:
                raise GatewayError(404, "not_found", "Такой страницы нет.")
            parts = relative.replace("\\", "/").split("/")
            target = (WEB_DIR / relative).resolve()
            if (any(p in {"", ".", ".."} for p in parts) or ":" in relative or WEB_DIR not in target.parents
                    or target.suffix.lower() not in STATIC_TYPES or not target.is_file()):
                raise GatewayError(404, "not_found", "Такой страницы нет.")
            headers = {"Cache-Control": "no-cache"}
            if target.suffix.lower() == ".html":
                headers["Content-Security-Policy"] = CSP
            self._send(200, target.read_bytes(), STATIC_TYPES[target.suffix.lower()], headers)

        def _handle(self) -> None:
            session = None
            try:
                if self.headers.get("Host", "") not in gateway.allowed_hosts():
                    raise GatewayError(403, "forbidden_host", "Откройте приложение по адресу 127.0.0.1 или localhost.")
                parsed = urlsplit(self.path)
                path = parsed.path
                method = self.command
                if not path.startswith("/api/"):
                    if method not in {"GET", "HEAD"}:
                        raise GatewayError(404, "not_found", "Такой страницы нет.")
                    self._static(path)
                    return
                found = gateway.match(method, path)
                if found is None:
                    raise GatewayError(404, "not_found", "Такого адреса в API нет.")
                key, params = found
                role = self.headers.get("X-MM-Role")
                if method in MUTATING:
                    origin = self.headers.get("Origin")
                    if origin is not None and origin not in {"http://" + h for h in gateway.allowed_hosts()}:
                        raise GatewayError(403, "forbidden_origin", "Запрос пришёл с чужой страницы и отклонён.")
                    if not role:
                        raise GatewayError(401, "no_session", "Окно не знает своей роли. Обновите страницу и выберите роль.")
                    if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                        raise GatewayError(415, "unsupported_type", "Шлюз принимает только JSON.")
                    body = self._body()
                else:
                    body = {}
                role = role if role in ROLES else None
                cookie = self._cookie(role) if role else None
                session = gateway.sessions.get(role, cookie) if role else None
                if key not in gateway.public:
                    if session is None:
                        raise GatewayError(401, "no_session", "Сессия не найдена или истекла. Выберите роль заново.")
                    if session.role not in gateway.access.get(key, set()):
                        raise GatewayError(403, "forbidden", "Этой роли действие недоступно.")
                query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
                ctx = Context(role, session, body, params, session_cookie=cookie, query=query)
                status, payload = gateway.routes[key](ctx)
                self._json(status, payload, ctx.cookies)
            except GatewayError as exc:
                self._json(exc.status, exc.payload(show_detail=bool(session and session.role in DETAIL_ROLES)))
            except StoreConflict as exc:
                self._json(409, {"error": {"code": "slot_unavailable", "message": str(exc)}})
            except StoreError:
                self._json(503, {"error": {"code": "database_unavailable", "message":
                                           "База шлюза недоступна. Проверьте подключение и повторите действие."}})
            except Exception:
                print("Gateway internal error:", file=sys.stderr)
                traceback.print_exc()
                self._json(500, {"error": {"code": "internal", "message": "Внутренняя ошибка шлюза. Попробуйте ещё раз; "
                                           "если повторится — перезапустите стенд."}})

        do_GET = do_POST = do_DELETE = do_PUT = do_PATCH = do_HEAD = _handle

    return RequestHandler


def main() -> None:
    try:
        config = load_config(dict(os.environ))
    except ConfigError as exc:
        raise SystemExit(f"Gateway configuration error: {exc}")
    config.state_dir.mkdir(parents=True, exist_ok=True)
    try:
        store = GatewayStore(config.db_dsn, config.db_schema)
        store.verify_schema()
    except StoreError as exc:
        raise SystemExit(f"Gateway database error: {exc}") from None
    gateway = Gateway(config, store=store)
    server = ThreadingHTTPServer(("127.0.0.1", config.port), make_handler(gateway))
    gateway.port = server.server_address[1]
    print(f"MedMarshrut gateway: http://127.0.0.1:{gateway.port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        store.close()


if __name__ == "__main__":
    main()
