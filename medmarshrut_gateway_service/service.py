"""Gateway: serves the web app, keeps demo-role sessions and calls the three services on the browser's behalf."""
from __future__ import annotations

import json
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote, unquote, urlsplit

from assistant import DOCTOR_UNAVAILABLE, PATIENT_UNAVAILABLE, Assistant
from catalog import STUDY_NAMES
from errors import GatewayError
from imaging import (MAX_ARCHIVE, MAX_CONCLUSION, MODALITY_TYPES, TASKS, build_manifest, confirm_body,
                     conclusion_templates, dicom_to_png, images, is_demo, place, reason_text as study_reason)
from pharmacy import PHARMACY_LABELS, PharmacyModule
from sessions import ROLES, People, Session, SessionStore, cookie_name
from store import GatewayStore, StoreConflict, StoreError
from upstream import Upstream, human_error, patient_ref, service_url, text
from views import patient_episode, reason_text, staff_episode

MAX_BODY = 32 * 1024
UPLOAD_TIMEOUT = 60  # the image service waits up to 30 s for inference
UNAVAILABLE = "Недоступно: сервис снимков перезапущен"
NOT_ROUTED = "Заключение подтверждено, но не дошло до сервиса маршрута"
DEFAULT_EXPLANATION = {"seen": "Заключение готово.", "means": "Врач объяснит результат на приёме"}
PATIENT_STATUS = {"processing": "processing", "awaiting_physician": "awaiting", "manual_review": "manual",
                  "test_only": "manual", "confirmed": "confirmed"}
WEB_DIR = Path(__file__).resolve().parent / "web"
BRAND_FONT = WEB_DIR / "fonts" / "Stolzl-Regular.otf"
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                ".ico": "image/x-icon", ".webp": "image/webp", ".otf": "font/otf"}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
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
    clinic_tokens: dict[str, str]
    home_clinic: str
    state_dir: Path
    people_path: Path
    imaging_mode: str
    urls: dict[str, str]
    port: int
    med_secret: str = ""
    med_admin_token: str = ""
    med_patient_token: str = ""
    med_staff_tokens: dict[str, str] = field(default_factory=dict)
    db_dsn: str = ""
    db_schema: str = ""
    conclusions_path: Path | None = None
    assistant_key: str = field(default="", repr=False)  # ANTHROPIC_API_KEY: only in this process
    assistant_model: str = ""


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
        urls = {service: service_url(env.get(f"{service.upper()}_URL"), service)
                for service in ("image", "path", "clinic", "medications")}
        port = int(env.get("GATEWAY_PORT") or 8763)
    except ValueError as exc:
        raise ConfigError(str(exc) if "_URL" in str(exc) else "GATEWAY_PORT must be a port number") from None
    if not 0 <= port <= 65535:
        raise ConfigError("GATEWAY_PORT must be a port number")
    try:
        med_staff_raw = json.loads(env.get("MED_STAFF_TOKENS", "{}") or "{}")
    except ValueError:
        med_staff_raw = {}
    med_staff_tokens = dict(med_staff_raw) if isinstance(med_staff_raw, dict) else {}
    return Config(values["REVIEWER_TOKEN"], values["PATH_ADMIN_TOKEN"], secret("PATH_MIS_TOKEN", required=False),
                  values["CLINIC_SHARED_SECRET"], clinic_tokens, home, Path(env["GATEWAY_STATE_DIR"]),
                  Path(env.get("GATEWAY_PEOPLE") or REPO / "demo_stand" / "people.demo.json"), mode, urls, port,
                  env.get("MED_SHARED_SECRET", ""), env.get("MED_ADMIN_TOKEN", ""),
                  env.get("MED_PATIENT_TOKEN", ""), med_staff_tokens,
                  env.get("GATEWAY_DATABASE_URL", ""), env.get("GATEWAY_DB_SCHEMA", ""),
                  Path(env.get("GATEWAY_CONCLUSIONS") or REPO / "demo_stand" / "conclusions.demo.json"),
                  env.get("ANTHROPIC_API_KEY", ""), env.get("GATEWAY_ASSISTANT_MODEL", ""))

@dataclass(frozen=True)
class RawResponse:
    """A non-JSON answer, such as a PNG preview."""
    data: bytes
    content_type: str


@dataclass
class Context:
    role: str | None
    session: Session | None
    body: dict
    params: dict[str, str]
    cookies: list[str] = field(default_factory=list)
    session_cookie: str | None = None
    query: dict[str, str] = field(default_factory=dict)
    raw: bytes = b""


Handler = Callable[[Context], tuple[int, dict | RawResponse]]


class Gateway:
    def __init__(self, config: Config, *, timeout: float | None = None, store: GatewayStore | None = None):
        self.config = config
        self.port = config.port
        self.people = People(config.people_path)
        self.sessions = SessionStore()
        self.store = store
        try:  # demo-stand conclusion templates by finding code; with a real model the gateway composes its own
            self.demo_texts = json.loads(config.conclusions_path.read_text(encoding="utf-8")) if config.conclusions_path else {}
        except (OSError, ValueError):
            self.demo_texts = {}
        kwargs = {"timeout": timeout} if timeout else {}
        self.upstream = Upstream(config.urls, reviewer_token=config.reviewer_token,
                                 path_admin_token=config.path_admin_token, path_mis_token=config.path_mis_token,
                                 clinic_secret=config.clinic_secret, clinic_tokens=config.clinic_tokens,
                                 med_secret=config.med_secret, med_admin_token=config.med_admin_token,
                                 med_patient_token=config.med_patient_token, med_staff_tokens=config.med_staff_tokens,
                                 **kwargs)
        self.assistant = Assistant.from_key(config.assistant_key, config.assistant_model)
        self.pharmacy = PharmacyModule(self.upstream, config)
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
            ("POST", "/api/patient/studies"): self.patient_upload,
            ("POST", "/api/staff/studies"): self.staff_upload,
            ("GET", "/api/demo/studies"): self.demo_studies,
            ("POST", "/api/demo/studies/{name}/submit"): self.demo_submit,
            ("GET", "/api/patient/studies"): self.patient_studies,
            ("GET", "/api/patient/studies/{id}/images/{image}"): self.patient_image,
            ("GET", "/api/doctor/studies"): self.doctor_studies,
            ("GET", "/api/doctor/studies/{id}"): self.doctor_study,
            ("GET", "/api/doctor/studies/{id}/images/{image}"): self.doctor_image,
            ("POST", "/api/doctor/studies/{id}/confirm"): self.doctor_confirm,
            ("GET", "/api/staff/studies/manual"): self.staff_manual_studies,
            ("GET", "/api/staff/patients"): self.staff_patients,
            ("GET", "/api/staff/patients/{ref}/card"): self.staff_patient_card,
            ("POST", "/api/staff/patients/{ref}/anamnesis"): self.staff_anamnesis,
            ("GET", "/api/staff/episodes/{id}/route-candidates"): self.staff_route_candidates,
            ("POST", "/api/staff/episodes/{id}/steps/{step}/referral"): self.staff_referral,
            ("GET", "/api/staff/referrals"): self.staff_referrals,
            ("POST", "/api/staff/referrals/{id}/cancel"): self.staff_referral_cancel,
            ("GET", "/api/staff/network"): self.staff_network,
            ("GET", "/api/partner/queue"): self.partner_queue,
            ("GET", "/api/partner/referrals"): self.partner_referrals,
            ("GET", "/api/partner/patients/{id}/card"): self.partner_card,
            ("POST", "/api/partner/referrals/{id}/{action}"): self.partner_action,
            ("GET", "/api/patient/documents"): self.patient_documents,
            ("GET", "/api/assistant/status"): self.assistant_status,
            ("POST", "/api/doctor/studies/{id}/assistant/rewrite"): self.doctor_rewrite,
            ("POST", "/api/patient/studies/{id}/assistant/explain"): self.patient_explain,
             # ---- Медикаменты ----
            ("GET", "/api/patient/offers"): self.pharmacy.patient_offers,
            ("GET", "/api/patient/prescriptions/{id}/offers"): self.pharmacy.patient_prescription_offers,
            ("GET", "/api/patient/orders"): self.pharmacy.patient_orders,
            ("GET", "/api/patient/orders/{id}"): self.pharmacy.patient_order,
            ("POST", "/api/patient/orders"): self.pharmacy.patient_order_place,
            ("POST", "/api/patient/orders/{id}/cancel"): self.pharmacy.patient_order_cancel,
            ("POST", "/api/doctor/prescriptions"): self.pharmacy.doctor_prescription_create,
            ("GET", "/api/pharmacy/queue"): self.pharmacy.pharmacy_queue,
            ("GET", "/api/pharmacy/metrics"): self.pharmacy.pharmacy_metrics,
            ("GET", "/api/pharmacy/catalog"): self.pharmacy.pharmacy_catalog,
            ("POST", "/api/pharmacy/orders/{id}/{action}"): self.pharmacy.pharmacy_order_action,
            # ---- Rescan: врач ----
            ("GET", "/api/doctor/dashboard"): self.doctor_dashboard,
            ("GET", "/api/doctor/studies/{id}/plan-preview"): self.doctor_plan_preview,
            ("POST", "/api/doctor/studies/{id}/skip-step"): self.doctor_skip_step,
            ("GET", "/api/doctor/appointments"): self.doctor_appointments,
            ("GET", "/api/doctor/integrations"): self.doctor_integrations,
            # ---- Rescan: пациент ----
            ("GET", "/api/patient/settings"): self.patient_settings_get,
            ("POST", "/api/patient/settings"): self.patient_settings_post,
            ("GET", "/api/patient/self-medications"): self.patient_self_meds_get,
            ("POST", "/api/patient/self-medications"): self.patient_self_meds_post,
            ("POST", "/api/patient/self-medications/{id}/remove"): self.patient_self_meds_remove,
            ("GET", "/api/patient/calendar"): self.patient_calendar,
            ("GET", "/api/patient/payment-methods"): self.patient_payment_methods,
        }
        # Routes whose body is a ZIP archive, not JSON: type and Content-Length are checked before reading.
        self.raw_routes: set[tuple[str, str]] = {("POST", "/api/patient/studies"), ("POST", "/api/staff/studies")}
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
            ("POST", "/api/patient/studies"): {"patient"},
            ("POST", "/api/staff/studies"): {"staff"},
            ("GET", "/api/demo/studies"): {"patient", "staff"},
            ("POST", "/api/demo/studies/{name}/submit"): {"patient", "staff"},
            ("GET", "/api/patient/studies"): {"patient"},
            ("GET", "/api/patient/studies/{id}/images/{image}"): {"patient"},
            ("GET", "/api/doctor/studies"): {"doctor"},
            ("GET", "/api/doctor/studies/{id}"): {"doctor"},
            ("GET", "/api/doctor/studies/{id}/images/{image}"): {"doctor"},
            ("POST", "/api/doctor/studies/{id}/confirm"): {"doctor"},
            ("GET", "/api/staff/studies/manual"): {"staff", "doctor"},
            ("GET", "/api/staff/patients"): {"staff", "doctor"},
            ("GET", "/api/staff/patients/{ref}/card"): {"staff", "doctor"},
            ("POST", "/api/staff/patients/{ref}/anamnesis"): {"staff", "doctor"},
            ("GET", "/api/staff/episodes/{id}/route-candidates"): {"staff", "doctor"},
            ("POST", "/api/staff/episodes/{id}/steps/{step}/referral"): {"staff"},
            ("GET", "/api/staff/referrals"): {"staff"},
            ("POST", "/api/staff/referrals/{id}/cancel"): {"staff"},
            ("GET", "/api/staff/network"): {"staff"},
            ("GET", "/api/partner/queue"): {"partner"},
            ("GET", "/api/partner/referrals"): {"partner"},
            ("GET", "/api/partner/patients/{id}/card"): {"partner"},
            ("POST", "/api/partner/referrals/{id}/{action}"): {"partner"},
            ("GET", "/api/patient/documents"): {"patient"},
            ("GET", "/api/assistant/status"): set(ROLES),
            ("POST", "/api/doctor/studies/{id}/assistant/rewrite"): {"doctor"},
            ("POST", "/api/patient/studies/{id}/assistant/explain"): {"patient"},
             ("GET", "/api/patient/offers"): {"patient"},
            ("GET", "/api/patient/prescriptions/{id}/offers"): {"patient"},
            ("GET", "/api/patient/orders"): {"patient"},
            ("GET", "/api/patient/orders/{id}"): {"patient"},
            ("POST", "/api/patient/orders"): {"patient"},
            ("POST", "/api/patient/orders/{id}/cancel"): {"patient"},
            ("POST", "/api/doctor/prescriptions"): {"doctor"},
            ("GET", "/api/pharmacy/queue"): {"pharmacy"},
            ("GET", "/api/pharmacy/metrics"): {"pharmacy"},
            ("GET", "/api/pharmacy/catalog"): {"pharmacy"},
            ("POST", "/api/pharmacy/orders/{id}/{action}"): {"pharmacy"},
            ("GET", "/api/doctor/dashboard"): {"doctor"},
            ("GET", "/api/doctor/studies/{id}/plan-preview"): {"doctor"},
            ("POST", "/api/doctor/studies/{id}/skip-step"): {"doctor"},
            ("GET", "/api/doctor/appointments"): {"doctor", "staff"},
            ("GET", "/api/doctor/integrations"): {"doctor", "staff"},
            ("GET", "/api/patient/settings"): {"patient"},
            ("POST", "/api/patient/settings"): {"patient"},
            ("GET", "/api/patient/self-medications"): {"patient"},
            ("POST", "/api/patient/self-medications"): {"patient"},
            ("POST", "/api/patient/self-medications/{id}/remove"): {"patient"},
            ("GET", "/api/patient/calendar"): {"patient"},
            ("GET", "/api/patient/payment-methods"): {"patient"},
        }

    def allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def match(self, method: str, path: str) -> tuple[tuple[str, str], dict[str, str]] | None:
        """The most specific route wins: a literal segment beats a {parameter} (…/steps/{step}/referral)."""
        segments = path.strip("/").split("/")
        for key in sorted(self.routes, key=lambda k: k[1].count("{")):
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
                     "services": self.upstream.health_all(), "partner_clinics": self._partner_clinics(),
                     "assistant": self.assistant.enabled, "brand_font": BRAND_FONT.is_file(),
                     "pharmacies": [{"pharmacy_id": pid, "name": PHARMACY_LABELS[pid]}
                                    for pid in sorted(self.upstream.medications_with_staff())]}

    def _partner_clinics(self) -> list[dict]:
        """Partner clinics a window can open: a staff token, a demo person, a name from the clinic network."""
        if not getattr(self, "_clinic_titles", None):
            try:
                body = self.upstream.json("clinic", "GET", "/v1/clinics", auth=("clinic_staff", self.config.home_clinic))
                self._clinic_titles = {c["id"]: c["name"] for c in body.get("clinics", [])}
            except GatewayError:
                return []
        return [{"clinic_id": clinic, "name": self._clinic_titles[clinic]} for clinic in sorted(self.upstream.clinics_with_staff())
                if clinic != self.config.home_clinic and clinic in self._clinic_titles and self.people.partner(clinic)]

    def session_create(self, ctx: Context) -> tuple[int, dict]:
        body = ctx.body
        role = body.get("role")
        if role not in ROLES:
            raise GatewayError(400, "invalid_input", "Выберите роль: пациент, сотрудник, врач или партнёр.")
        if role != ctx.role:
            raise GatewayError(400, "invalid_input", "Роль в запросе не совпадает с ролью окна. Обновите страницу.")
        allowed = ({"role", "patient_ref"} if role == "patient"
                   else {"role", "clinic_id"} if role == "partner"
                   else {"role", "pharmacy_id"} if role == "pharmacy"
                   else {"role"})
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
        elif role == "pharmacy":
            pharmacy = text(body.get("pharmacy_id", "pharm-central"), "pharmacy_id", 128)
            if pharmacy not in PHARMACY_LABELS:
                raise GatewayError(400, "unknown_clinic", "Такой аптеки на стенде нет.")
            session = self.sessions.create(role, person_id=f"pharmacy-{pharmacy}",
                                           name=PHARMACY_LABELS[pharmacy], clinic_id=pharmacy)
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
        base = self.data_store().catalogue(self.config.home_clinic)
        base["specialists"] = self.data_store().specialists(self.config.home_clinic)
        return 200, base
    
    def slots(self, ctx: Context) -> tuple[int, dict]:
        episode_id, step_id = ctx.query.get("episode"), ctx.query.get("step")
        if not episode_id or not step_id:
            raise GatewayError(400, "invalid_input", "Выберите шаг плана и попробуйте снова.")
        raw = self._owned_episode(ctx, episode_id) if ctx.role == "patient" else self._one_episode(episode_id)
        step = next((s for s in raw.get("plan_steps", []) if s.get("id") == step_id), None)
        if step is None or step.get("kind") == "manual_review":
            raise GatewayError(404, "not_found", "Шаг плана не найден. Обновите страницу.")
        return 200, {"slots": self.data_store().slots(self.config.home_clinic, step["description"]), "demo": True}

    def patient_episode(self, ctx: Context) -> tuple[int, dict]:
        raw = self._owned_episode(ctx, ctx.params["id"])
        return 200, {"episode": patient_episode(raw, self._explanation(raw))}

    def _patient_names(self) -> dict[str, str]:
        body = self.upstream.json("clinic", "GET", "/v1/patients?limit=500",
                                  auth=("clinic_staff", self.config.home_clinic))
        return {p["patient_ref"]: p["full_name"] for p in body.get("patients", [])}

    def patient_episodes(self, ctx: Context) -> tuple[int, dict]:
        mine = [raw for raw in self._episodes()
                if (raw.get("source_report") or {}).get("patient_ref") == ctx.session.patient_ref]
        items = []
        for raw in mine:
            view = patient_episode(raw, self._explanation(raw))
            view["stage"] = self._episode_stage(raw)
            view["stage_labels"] = ["Заключение", "Рекомендация", "Запись", "Приём"]
            items.append(view)
        return 200, {"episodes": items}

    @staticmethod
    def _episode_stage(raw: dict) -> int:
        """0 — заключение, 1 — рекомендация, 2 — запись, 3 — приём."""
        status = raw.get("status")
        if status == "completed":
            return 3
        steps = raw.get("plan_steps") or []
        # Ищем активные (не superseded и не completed)
        active = [s for s in steps if s.get("status") not in {"completed", "superseded", "closed"}]
        for step in active:
            st = step.get("status")
            if st == "attended":
                return 3
            if st == "confirmed":
                return 2
            if st == "offered":
                return 2  # предложение уже отправлено, ожидаем ответа — считаем «на шаге записи»
            if st == "open":
                return 1
        if raw.get("status") == "active":
            return 1
        return 1
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
        if action == "confirm" and "partner_time" in ctx.body:
            return self._partner_booking(ctx, raw, step)
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
        store = self.data_store()
        visits = []
        for raw in self._episodes():
            for step in raw.get("plan_steps", []):
                if step.get("status") in {"confirmed", "attended"}:
                    visits.append({"episode": staff_episode(raw, names.get(
                        (raw.get("source_report") or {}).get("patient_ref"), "Пациент не указан")),
                                   "step_id": step["id"],
                                   "appointment": store.appointment_detail(raw["id"], step["id"])})
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

    # ---------- studies: image service + study_registry ----------

    def _image_get(self, route: str, **kwargs) -> dict | None:
        """A JSON read from the image service; None when the job is gone from its memory (404)."""
        status, body = self.upstream.request("image", "GET", route, **kwargs)
        if status == 404:
            return None
        if status != 200 or not isinstance(body, dict):
            raise human_error("image", status, body)
        return body

    def _review(self, job_id: str) -> dict | None:
        return self._image_get("/v1/review/" + quote(job_id, safe=""), auth="reviewer")

    def _public(self, job_id: str) -> dict | None:
        return self._image_get("/v1/studies/" + quote(job_id, safe=""))

    def _many(self, fn, ids: list[str]) -> list:
        if not ids:
            return []
        with ThreadPoolExecutor(max_workers=min(8, len(ids))) as pool:
            return list(pool.map(fn, ids))

    def _registry_row(self, job_id: str, *, owner: Session | None = None) -> dict:
        row = self.data_store().study(self.config.home_clinic, job_id)
        if row is None or (owner is not None and row["patient_ref"] != owner.patient_ref):
            raise GatewayError(404, "not_found", "Такого исследования нет. Обновите список.")
        return row

    @staticmethod
    def _title(row: dict, job: dict | None = None) -> str:
        study = (job or {}).get("study") or {}
        named = STUDY_NAMES.get((MODALITY_TYPES.get(study.get("modality")), study.get("anatomy")))
        return named or row.get("title") or TASKS.get(row.get("task"), "Исследование")

    def _episodes_by_report(self) -> dict[str, dict]:
        return {(raw.get("source_report") or {}).get("source_report_id"): raw for raw in self._episodes()}

    def _staff_patient(self, value: object) -> str:
        ref = patient_ref(value)
        card = self.upstream.patient_by_ref(ref)
        if card is None:
            raise GatewayError(400, "unknown_patient", f"Пациента «{ref}» нет в сервисе клиники. Проверьте псевдоним.")
        if card.get("home_clinic_id") != self.config.home_clinic:
            raise GatewayError(400, "foreign_patient", "Этот пациент наблюдается в другой клинике.")
        return ref

    def _submit(self, ctx: Context, archive: bytes, task: str, ref: str | None, *, title: str | None = None,
                kit: str | None = None, consent: bool = False) -> tuple[dict, dict]:
        """Build the manifest, send the archive, register the job. Returns (public status, registry row)."""
        manifest = build_manifest(archive, task)
        status, body = self.upstream.request("image", "POST", "/v1/studies", raw=archive, content_type="application/zip",
                                             headers={"X-Study-Manifest": json.dumps(manifest)}, timeout=UPLOAD_TIMEOUT)
        if status in {413, 415}:
            raise GatewayError(400, "invalid_archive", "Сервис снимков не принял архив: нужен ZIP до 50 МиБ.",
                               body.get("error") if isinstance(body, dict) else None)
        # 201, 202, 422, 503 and 504 all mean "job created": the body is its public status.
        if status not in {201, 202, 422, 503, 504} or not isinstance(body, dict) or not isinstance(body.get("id"), str):
            raise human_error("image", status, body)
        row = self.data_store().register_study(body["id"], self.config.home_clinic, ref, task, title or TASKS[task], kit,
                                               ctx.role, ctx.session.actor,
                                               datetime.now(timezone.utc) if consent else None)
        return body, row

    @staticmethod
    def _consent(value: object) -> None:
        if value not in {True, "1"}:
            raise GatewayError(400, "consent_required", "Отметьте согласие на передачу исследования врачу клиники.")

    def patient_upload(self, ctx: Context) -> tuple[int, dict]:
        self._consent(ctx.query.get("consent"))
        public, row = self._submit(ctx, ctx.raw, ctx.query.get("task", ""), ctx.session.patient_ref, consent=True)
        return 201, {"study": {"id": row["job_id"], "title": row["title"], "created_at": row["created_at"],
                               "status": PATIENT_STATUS.get(public.get("status"), "awaiting")}}

    def staff_upload(self, ctx: Context) -> tuple[int, dict]:
        ref = self._staff_patient(ctx.query.get("patient_ref"))
        public, row = self._submit(ctx, ctx.raw, ctx.query.get("task", ""), ref)
        return 201, {"study": {"id": row["job_id"], "title": row["title"], "status": public.get("status")}}

    def _kit(self) -> dict:
        try:
            kit = json.loads((self.config.state_dir / "kit" / "kit.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return kit if isinstance(kit, dict) else {}

    def demo_studies(self, ctx: Context) -> tuple[int, dict]:
        """Learning archives a person may submit from the window: only the `upload-*` part of the stand kit."""
        entries = [(name, item) for name, item in self._kit().items() if name.startswith("upload-")]
        totals: dict[str, int] = {}
        for _, item in entries:
            totals[item["title"]] = totals.get(item["title"], 0) + 1
        seen: dict[str, int] = {}
        result = []
        for name, item in entries:
            seen[item["title"]] = seen.get(item["title"], 0) + 1
            label = item["title"] + (f", вариант {seen[item['title']]}" if totals[item["title"]] > 1 else "")
            result.append({"name": name, "title": item["title"], "label": label, "task": item["task"]})
        return 200, {"studies": result, "demo": True}

    def demo_submit(self, ctx: Context) -> tuple[int, dict]:
        name = ctx.params["name"]
        item = self._kit().get(name)
        if not isinstance(item, dict) or (ctx.role == "patient" and not name.startswith("upload-")):
            raise GatewayError(404, "not_found", "Такого учебного исследования нет. Обновите список.")
        try:
            archive = (self.config.state_dir / "kit" / Path(item["archive"]).name).read_bytes()
        except (OSError, KeyError, TypeError):
            raise GatewayError(404, "not_found", "Учебный архив не найден. Перезапустите стенд: python start.py") from None
        if ctx.role == "patient":
            self._consent(ctx.body.get("consent"))
            public, row = self._submit(ctx, archive, item["task"], ctx.session.patient_ref,
                                       title=item["title"], kit=name, consent=True)
            return 201, {"study": {"id": row["job_id"], "title": row["title"], "created_at": row["created_at"],
                                   "status": PATIENT_STATUS.get(public.get("status"), "awaiting")}, "demo": True}
        ref = self._staff_patient(ctx.body.get("patient_ref"))
        public, row = self._submit(ctx, archive, item["task"], ref, title=item["title"], kit=name)
        return 201, {"study": {"id": row["job_id"], "title": row["title"], "status": public.get("status")}, "demo": True}

    def _patient_item(self, row: dict, public: dict | None, episodes: Callable[[], dict]) -> dict:
        """Before confirmation: status only. After: the physician's text, the approved explanation, the plan step."""
        item = {"id": row["job_id"], "title": self._title(row), "created_at": row["created_at"]}
        if public is None:
            return {**item, "status": "unavailable", "message": UNAVAILABLE}
        item["status"] = PATIENT_STATUS.get(public.get("status"), "awaiting")
        if item["status"] != "confirmed":
            return item
        job = self._review(row["job_id"])
        if job is None:
            return {**item, "status": "unavailable", "message": UNAVAILABLE}
        confirmation = job.get("confirmation") or {}
        code = (confirmation.get("routing_payload") or {}).get("finding_code")
        explanation = self.data_store().explanation(self.config.home_clinic, code) if code else None
        finding = next((f for f in (job.get("result") or {}).get("findings") or [] if f.get("code") == code), None)
        item.update(title=self._title(row, job), conclusion=confirmation.get("conclusion"),
                    confirmed_at=confirmation.get("confirmed_at"), explanation=explanation or DEFAULT_EXPLANATION)
        if finding:
            item["image"] = {"sop_uid": (finding.get("localization") or {}).get("sop_uid"),
                             "label": place(finding, job.get("study"))}
        raw = episodes().get(row["job_id"])
        item["episode"] = patient_episode(raw, explanation) if raw else None
        return item

    def patient_studies(self, ctx: Context) -> tuple[int, dict]:
        rows = self.data_store().studies(self.config.home_clinic, ctx.session.patient_ref)
        publics = self._many(self._public, [row["job_id"] for row in rows])
        cache: dict = {}

        def episodes() -> dict:
            if "all" not in cache:
                cache["all"] = {key: raw for key, raw in self._episodes_by_report().items()
                                if (raw.get("source_report") or {}).get("patient_ref") == ctx.session.patient_ref}
            return cache["all"]
        return 200, {"studies": [self._patient_item(row, public, episodes) for row, public in zip(rows, publics)]}

    def _png(self, job_id: str, image: str) -> tuple[int, RawResponse]:
        if not image.endswith(".png") or len(image) <= 4:
            raise GatewayError(404, "not_found", "Такого среза нет.")
        status, body = self.upstream.request("image", "GET", "/v1/review/" + quote(job_id, safe="") + "/images/"
                                             + quote(image[:-4], safe=""), auth="reviewer")
        if status == 404:
            raise GatewayError(404, "not_found", "Срез не найден: исследование недоступно или сервис снимков перезапущен.")
        if status != 200 or not isinstance(body, bytes):
            raise human_error("image", status, body)
        try:
            return 200, RawResponse(dicom_to_png(body), "image/png")
        except Exception:
            raise GatewayError(502, "image_unreadable", "Не удалось показать срез. Откройте другой срез или исследование.") from None

    def patient_image(self, ctx: Context) -> tuple[int, RawResponse]:
        row = self._registry_row(ctx.params["id"], owner=ctx.session)
        public = self._public(row["job_id"])
        if public is None or public.get("status") != "confirmed":
            raise GatewayError(404, "not_found", "Снимок появится здесь после проверки врачом.")
        return self._png(row["job_id"], ctx.params["image"])

    def _next(self, job: dict, episodes: dict[str, dict]) -> dict:
        """What happened in the path service after confirmation: the episode and its first step, or why not."""
        if job.get("routing_status") == "failed":
            return {"warning": NOT_ROUTED}
        raw = episodes.get(job.get("id"))
        if raw is None:
            if job.get("routing_status") != "sent":
                return {"warning": "Сервис снимков не настроен на отправку заключений в сервис маршрута."}
            return {"warning": "Обращение в сервисе маршрута пока не найдено. Обновите страницу."}
        step = self._first_unfinished(raw)
        return {"episode_id": raw["id"], "status": raw.get("status"),
                "step": step.get("description") if step and raw.get("status") == "active" else None,
                "step_status": step.get("status") if step else None,
                "reason": reason_text(raw.get("manual_reason")) if raw.get("status") == "manual_review" else ""}

    def _doctor_item(self, row: dict, job: dict | None, names: dict[str, str], episodes: dict[str, dict]) -> dict:
        ref = row.get("patient_ref")
        item = {"id": row["job_id"], "patient": names.get(ref, "Пациент не указан") if ref else "Пациент не указан",
                "patient_ref": ref, "created_at": row["created_at"], "uploaded_by_role": row["uploaded_by_role"],
                "kit": row.get("kit")}
        if job is None:
            return {**item, "title": self._title(row), "status": "unavailable", "message": UNAVAILABLE}
        demo = is_demo(job)
        findings = []
        for finding in (job.get("result") or {}).get("findings") or []:
            entry = {"code": finding.get("code"), "description": finding.get("description"),
                     "place": place(finding, job.get("study")),
                     "sop_uid": (finding.get("localization") or {}).get("sop_uid")}
            if not demo:
                entry["confidence"] = finding.get("confidence")
            findings.append(entry)
        item.update(title=self._title(row, job), status=job.get("status"), demo=demo, reason=study_reason(job.get("reason")),
                    routing_status=job.get("routing_status"), findings=findings)
        confirmation = job.get("confirmation")
        if confirmation:
            item["confirmation"] = {"physician_id": confirmation.get("physician_id"),
                                    "confirmed_at": confirmation.get("confirmed_at"), "edited": bool(job.get("edits")),
                                    "conclusion": confirmation.get("conclusion"),
                                    "finding_code": (confirmation.get("routing_payload") or {}).get("finding_code")}
            item["next"] = self._next(job, episodes)
        return item

    def doctor_studies(self, ctx: Context) -> tuple[int, dict]:
        rows = self.data_store().studies(self.config.home_clinic)
        jobs = self._many(self._review, [row["job_id"] for row in rows])
        names = self._patient_names() if rows else {}
        episodes = self._episodes_by_report() if any(job and job.get("status") == "confirmed" for job in jobs) else {}
        return 200, {"studies": [self._doctor_item(row, job, names, episodes) for row, job in zip(rows, jobs)]}

    def doctor_study(self, ctx: Context) -> tuple[int, dict]:
        row = self._registry_row(ctx.params["id"])
        job = self._review(row["job_id"])
        episodes = self._episodes_by_report() if job and job.get("status") == "confirmed" else {}
        item = self._doctor_item(row, job, self._patient_names(), episodes)
        if job is not None:
            study = job.get("study") or {}
            result = job.get("result") or {}
            item.update(study={key: study.get(key) for key in ("task", "modality", "anatomy", "protocol_name", "instance_count")}
                        | {"series_count": len(study.get("series") or {})} if study else None,
                        images=images(study), limitations=result.get("limitations") or [],
                        test_message="Техническая проверка, анализ не выполнялся" if job.get("status") == "test_only" else None,
                        templates=conclusion_templates(job, item["title"], self.demo_texts)
                        if job.get("status") == "awaiting_physician" else {})
            if job.get("status") == "awaiting_physician":
                item["preview"] = self._study_preview(job)
        return 200, {"study": item}

    def _study_preview(self, job: dict) -> dict | None:
        """Предпросмотр шага по каждой находке: dry-run правил клиники (шаги или причина ручного разбора
        и версия правил) плюс утверждённое объяснение из finding_texts или None. confidence в запрос
        не входит. Сервис пути недоступен — None, остальной ответ прежний."""
        study = job.get("study") or {}
        scope = {"study_type": MODALITY_TYPES.get(study.get("modality")),
                 "anatomy": study.get("anatomy"), "protocol_name": study.get("protocol_name")}
        codes = list(dict.fromkeys(f.get("code") for f in (job.get("result") or {}).get("findings") or [] if f.get("code")))
        if not codes or not all(isinstance(value, str) and value for value in scope.values()):
            return None
        store = self.data_store()
        preview: dict[str, dict] = {}
        try:
            for code in codes:
                result = self.upstream.json("path", "POST", "/v1/rules/dry-run",
                                            body={**scope, "finding_code": code}, auth="path_admin")
                preview[code] = {"steps": result.get("steps") or [], "manual_reason": result.get("manual_reason"),
                                 "manual_reason_text": reason_text(result.get("manual_reason")),
                                 "rule_version": result.get("rule_version"),
                                 "explanation": store.explanation(self.config.home_clinic, code)}
        except GatewayError:
            return None
        return preview

    def doctor_image(self, ctx: Context) -> tuple[int, RawResponse]:
        row = self._registry_row(ctx.params["id"])
        return self._png(row["job_id"], ctx.params["image"])

    def doctor_confirm(self, ctx: Context) -> tuple[int, dict]:
        row = self._registry_row(ctx.params["id"])
        job = self._review(row["job_id"])
        if job is None:
            raise GatewayError(409, "study_unavailable", UNAVAILABLE + ". Попросите загрузить исследование заново.")
        if job.get("status") != "awaiting_physician":
            raise GatewayError(409, "study_unavailable", "Исследование уже подтверждено или не ждёт проверки врача. Обновите страницу.")
        conclusion = text(ctx.body.get("conclusion"), "conclusion", MAX_CONCLUSION)
        codes = list(dict.fromkeys(f.get("code") for f in (job.get("result") or {}).get("findings") or []))
        code = codes[0] if len(codes) == 1 else ctx.body.get("finding_code")
        if code not in codes:
            raise GatewayError(400, "invalid_input", "Выберите признак, который вы подтверждаете.")
        template = conclusion_templates(job, self._title(row, job), self.demo_texts).get(code)
        data = confirm_body(ctx.session.actor, conclusion, code, template, row.get("patient_ref"))
        status, body = self.upstream.request("image", "POST", "/v1/review/" + quote(row["job_id"], safe=""),
                                             raw=data, content_type="application/json", auth="reviewer")
        if status != 200 or not isinstance(body, dict):
            raise human_error("image", status, body)

        # === Rescan: если врач выбрал свой шаг — переопределяем план ===
        override = ctx.body.get("override_step")
        if override and body.get("routing_status") == "sent":
            episodes_map = self._episodes_by_report()
            raw_ep = episodes_map.get(row["job_id"])
            if raw_ep:
                steps = [self._normalize_override_step(override)]
                try:
                    self.upstream.json("path", "POST",
                                       f"/v1/episodes/{quote(raw_ep['id'], safe='')}/revise-plan",
                                       body={"physician_id": ctx.session.actor,
                                             "reason": "Врач уточнил план при подтверждении",
                                             "steps": steps},
                                       auth="path_admin")
                except GatewayError as exc:
                    # Не падаем: подтверждение уже прошло, план остался стандартным
                    self.log_override_failure(row["job_id"], str(exc))
        # === конец override ===

        episodes = self._episodes_by_report() if body.get("routing_status") == "sent" else {}
        item = self._doctor_item(row, body, self._patient_names(), episodes)
        return 200, {"study": item, "next": item.get("next")}

    # ---------- ИИ-помощник (задание 11): текст для врача и пациента, ничего не решает ----------

    def assistant_status(self, ctx: Context) -> tuple[int, dict]:
        return 200, {"enabled": self.assistant.enabled}

    def doctor_rewrite(self, ctx: Context) -> tuple[int, dict]:
        """A wording suggestion. Nothing is stored and nothing goes to the image service: the physician confirms as usual.
        To the API: study title, finding description and place, the physician's text. No score, UID, name or patient_ref."""
        if not self.assistant.enabled:
            raise GatewayError(503, "assistant_unavailable", DOCTOR_UNAVAILABLE)
        row = self._registry_row(ctx.params["id"])
        job = self._review(row["job_id"])
        if job is None or job.get("status") != "awaiting_physician":
            raise GatewayError(409, "study_unavailable", "Исследование уже подтверждено или не ждёт проверки врача. Обновите страницу.")
        draft = text(ctx.body.get("text"), "text", MAX_CONCLUSION)
        finding = next((f for f in (job.get("result") or {}).get("findings") or []
                        if f.get("code") == ctx.body.get("finding_code")), None)
        if finding is None:
            raise GatewayError(400, "invalid_input", "Выберите признак, который вы подтверждаете.")
        payload = {"study": self._title(row, job), "finding": finding.get("description"),
                   "place": place(finding, job.get("study")), "draft": draft}
        return 200, {"suggestion": self.assistant.rewrite_conclusion(row["job_id"], payload, MAX_CONCLUSION)}

    def patient_explain(self, ctx: Context) -> tuple[int, dict]:
        """Only the patient's own study and only after confirmation; before it the API is not called at all.
        To the API: study title, the physician's conclusion, the approved explanation, the plan step. Cached by input."""
        if not self.assistant.enabled:
            raise GatewayError(503, "assistant_unavailable", PATIENT_UNAVAILABLE)
        row = self._registry_row(ctx.params["id"], owner=ctx.session)
        public = self._public(row["job_id"])
        if public is None or public.get("status") != "confirmed":
            raise GatewayError(409, "not_confirmed", "Объяснение появится после того, как врач подтвердит заключение.")
        job = self._review(row["job_id"])
        if job is None:
            raise GatewayError(409, "study_unavailable", UNAVAILABLE + ". Загрузите исследование заново.")
        confirmation = job.get("confirmation") or {}
        code = (confirmation.get("routing_payload") or {}).get("finding_code")
        store = self.data_store()
        raw = self._episodes_by_report().get(row["job_id"])
        step = self._first_unfinished(raw) if raw and raw.get("status") == "active" else None
        payload = {"study": self._title(row, job), "conclusion": confirmation.get("conclusion"),
                   "approved": (store.explanation(self.config.home_clinic, code) if code else None) or DEFAULT_EXPLANATION,
                   "next_step": step.get("description") if step else None}
        key = self.assistant.digest(payload)
        saved = store.assistant_text(row["job_id"], key)
        if saved is None:
            saved = store.save_assistant_text(row["job_id"], key, self.assistant.model,
                                              self.assistant.explain_for_patient(row["job_id"], payload))
        return 200, {"explanation": saved}

    @staticmethod
    def _normalize_override_step(override: dict) -> dict:
        from datetime import datetime, timedelta, timezone
        kind = override.get("kind") or "appointment"
        description = text(override.get("description"), "description", 500)
        due_at = override.get("due_at")
        if not due_at and override.get("due_days"):
            try:
                days = int(override["due_days"])
                due_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")
            except (TypeError, ValueError):
                due_at = None
        return {
            "kind": kind,
            "description": description,
            "owner": "coordinator",
            "due_at": due_at,
            "continue_on": "confirmed_outcome",
        }

    def log_override_failure(self, job_id: str, message: str) -> None:
        import sys
        print(f"[gateway] override_step failed for {job_id}: {message}", file=sys.stderr)

    def staff_manual_studies(self, ctx: Context) -> tuple[int, dict]:
        """For the coordinator: who waits for a manual reading, and which confirmations never reached the path service.
        No reason and no model output."""
        rows = self.data_store().studies(self.config.home_clinic)
        publics = self._many(self._public, [row["job_id"] for row in rows])
        names = self._patient_names() if rows else {}
        manual, not_routed = [], []
        for row, public in zip(rows, publics):
            if public is None:
                continue
            entry = {"id": row["job_id"], "patient": names.get(row.get("patient_ref"), "Пациент не указан"),
                     "patient_ref": row.get("patient_ref"), "title": self._title(row), "created_at": row["created_at"]}
            if public.get("status") == "manual_review":
                manual.append(entry)
            elif public.get("status") == "confirmed" and public.get("routing_status") == "failed":
                not_routed.append({**entry, "warning": NOT_ROUTED})
        return 200, {"manual": manual, "not_routed": not_routed}

    # ---------- clinic: cards, network, referrals ----------

    def _own_clinic(self, ctx: Context) -> tuple[str, str]:
        """The token is chosen by the session's clinic; a staff session acts only for the home clinic."""
        clinic = ctx.session.clinic_id
        if ctx.role == "partner":
            if not clinic or clinic == self.config.home_clinic:
                raise GatewayError(403, "forbidden", "Сессия партнёра не привязана к клинике-партнёру. Выберите роль заново.")
        elif clinic != self.config.home_clinic:
            raise GatewayError(403, "forbidden", "Сессия не привязана к своей клинике. Выберите роль заново.")
        return "clinic_staff", clinic

    def _clinic(self, ctx: Context, method: str, route: str, body: dict | None = None) -> dict:
        return self.upstream.json("clinic", method, route, body=body, auth=self._own_clinic(ctx))

    def _clinic_names(self, ctx: Context) -> dict[str, str]:
        return {c["id"]: c["name"] for c in self._clinic(ctx, "GET", "/v1/clinics").get("clinics", [])}

    def _patient_id(self, ctx: Context, ref: str) -> str:
        ref = patient_ref(ref)
        found = next((p for p in self._clinic(ctx, "GET", "/v1/patients?limit=500").get("patients", [])
                      if p.get("patient_ref") == ref), None)
        if found is None:
            raise GatewayError(404, "not_found", "Пациент не найден в карте клиники. Проверьте псевдоним.")
        return found["id"]

    def staff_patients(self, ctx: Context) -> tuple[int, dict]:
        raw_limit = ctx.query.get("limit", "100")
        if not raw_limit.isdecimal() or not 1 <= int(raw_limit) <= 500:
            raise GatewayError(400, "invalid_input", "Число пациентов в списке: целое от 1 до 500.")
        route = f"/v1/patients?limit={int(raw_limit)}"
        if ctx.query.get("status"):
            if ctx.query["status"] not in {"active", "archived", "transferred", "deceased"}:
                raise GatewayError(400, "invalid_input", "Статус карты: active, archived, transferred или deceased.")
            route += "&status=" + ctx.query["status"]
        body = self._clinic(ctx, "GET", route)
        # Пробрасываем communication_channel как есть; фронт ожидает это поле
        for p in body.get("patients", []):
            p.setdefault("communication_channel", None)
        return 200, body
    
    def staff_patient_card(self, ctx: Context) -> tuple[int, dict]:
        patient_id = self._patient_id(ctx, ctx.params["ref"])
        return 200, self._clinic(ctx, "GET", f"/v1/patients/{quote(patient_id, safe='')}/card")

    ANAMNESIS_KINDS = {"diagnosis", "allergy", "medication", "surgery", "family_history", "risk_factor", "note",
                       "measurement", "lab"}

    def staff_anamnesis(self, ctx: Context) -> tuple[int, dict]:
        kind = ctx.body.get("kind")
        if kind not in self.ANAMNESIS_KINDS:
            raise GatewayError(400, "invalid_input", "Выберите вид записи анамнеза.")
        shareable = ctx.body.get("shareable", False)
        if type(shareable) is not bool:
            raise GatewayError(400, "invalid_input", "Отметьте, показывать ли запись партнёрам.")
        patient_id = self._patient_id(ctx, ctx.params["ref"])
        # author_id, author_role and clinic_id come from the session, never from the request body.
        body = {"kind": kind, "code": text(ctx.body.get("code"), "code", 64, required=False),
                "text": text(ctx.body.get("text"), "text", 4000), "shareable": shareable, "recorded_at": None,
                "author_id": ctx.session.actor, "author_role": "physician" if ctx.role == "doctor" else "coordinator",
                "clinic_id": ctx.session.clinic_id}
        return 201, self._clinic(ctx, "POST", f"/v1/patients/{quote(patient_id, safe='')}/anamnesis", body)

    CANDIDATE_REASONS = {None: "", "unknown_patient_ref": "Пациент не найден в карте клиники",
                         "no_clinic_with_capability": "Ни своя клиника, ни партнёры не выполняют такой шаг"}

    def staff_route_candidates(self, ctx: Context) -> tuple[int, dict]:
        self._own_clinic(ctx)
        report = self._one_episode(ctx.params["id"]).get("source_report") or {}
        ref = report.get("patient_ref")
        if not ref:
            return 200, {"candidates": [], "reason": "unknown_patient_ref", "reason_text": self.CANDIDATE_REASONS["unknown_patient_ref"]}
        scope = {key: report.get(key) for key in ("study_type", "anatomy", "protocol_name", "finding_code")}
        if not all(isinstance(v, str) and v for v in scope.values()):
            raise GatewayError(409, "invalid_scope", "В заключении не хватает сведений об исследовании: кандидатов не подобрать.")
        result = self.upstream.json("clinic", "POST", "/v1/route-candidates", body={"patient_ref": ref, "scope": scope},
                                    auth="clinic_signed")
        reason = result.get("reason")
        result["reason_text"] = self.CANDIDATE_REASONS.get(reason, "Карта пациента закрыта" if str(reason).startswith("patient_") else reason)
        return 200, result

    def _referrals(self, ctx: Context) -> list[dict]:
        return self._clinic(ctx, "GET", "/v1/referrals").get("referrals", [])

    def staff_referral(self, ctx: Context) -> tuple[int, dict]:
        clinic = self._own_clinic(ctx)[1]
        raw = self._one_episode(ctx.params["id"])
        step = self._step(raw, ctx.params["step"])
        if step.get("kind") == "manual_review" or step.get("status") in {"completed", "superseded", "closed"}:
            raise GatewayError(409, "step_unavailable", "Для этого шага направление уже не нужно. Обновите карточку.")
        ref = (raw.get("source_report") or {}).get("patient_ref")
        if not ref:
            raise GatewayError(409, "missing_patient", "В обращении нет пациента. Передайте случай врачу на ручной разбор.")
        target = text(ctx.body.get("to_clinic_id"), "to_clinic_id", 128)
        reason = text(ctx.body.get("reason"), "reason", 1000)
        # A repeat after a failed link write must not create a second referral: reuse the active one.
        existing = next((r for r in self._referrals(ctx) if r.get("patient_ref") == ref and r.get("from_clinic_id") == clinic
                         and r.get("to_clinic_id") == target and r.get("status") in {"proposed", "accepted"}), None)
        if existing is not None:
            linked = self.data_store().referral_links([existing["id"]]).get(existing["id"])
            if linked and (linked["episode_id"], linked["step_id"]) != (raw["id"], step["id"]):
                raise GatewayError(409, "upstream_rejected", "Направление этому партнёру уже есть. Откройте его во вкладке «Направления».")
            referral, status = existing, 200
        else:
            referral = self.upstream.json("clinic", "POST", "/v1/referrals", auth="clinic_signed", ok={201}, body={
                "patient_ref": ref, "from_clinic_id": clinic, "to_clinic_id": target, "reason": reason,
                "created_by": ctx.session.actor})
            status = 201
        try:
            link = self.data_store().link_referral(referral["id"], raw["id"], step["id"], ctx.session.actor)
        except StoreConflict:
            raise
        except StoreError:
            raise GatewayError(503, "link_not_saved", "Направление создано, но связь с шагом не записалась. "
                               "Нажмите «Направить» ещё раз: второе направление не появится.") from None
        return status, {"referral": referral, "link": {"episode_id": link["episode_id"], "step_id": link["step_id"]}}

    def staff_referrals(self, ctx: Context) -> tuple[int, dict]:
        items = self._referrals(ctx)
        names = self._clinic_names(ctx)
        links = self.data_store().referral_links([r["id"] for r in items]) if items else {}
        clinic = ctx.session.clinic_id
        return 200, {"referrals": [{**r, "direction": "outgoing" if r.get("from_clinic_id") == clinic else "incoming",
                                    "from_clinic_name": names.get(r.get("from_clinic_id"), r.get("from_clinic_id")),
                                    "to_clinic_name": names.get(r.get("to_clinic_id"), r.get("to_clinic_id")),
                                    "link": links.get(r["id"])} for r in items]}

    def staff_referral_cancel(self, ctx: Context) -> tuple[int, dict]:
        note = text(ctx.body.get("note"), "note", 500, required=False)
        body = {"actor": ctx.session.actor, **({"note": note} if note else {})}
        return 200, {"referral": self._clinic(ctx, "POST", f"/v1/referrals/{quote(ctx.params['id'], safe='')}/cancel", body)}

    def staff_network(self, ctx: Context) -> tuple[int, dict]:
        clinics = self._clinic(ctx, "GET", "/v1/clinics")
        partners = self._clinic(ctx, "GET", "/v1/partnerships").get("partners", [])
        metrics = self._clinic(ctx, "GET", "/v1/staff/metrics")
        counts: dict[str, dict] = {}
        for r in self._referrals(ctx):
            if r.get("from_clinic_id") == ctx.session.clinic_id:
                item = counts.setdefault(r.get("to_clinic_id"), {"sent": 0, "accepted": 0})
                item["sent"] += 1
                item["accepted"] += r.get("status") in {"accepted", "completed"}
        return 200, {"clinics": clinics.get("clinics", []), "network_version": clinics.get("network_version"),
                     "partners": partners, "metrics": metrics, "referral_counts": counts, "home_clinic_id": ctx.session.clinic_id}

    # Partner screens get exactly what the clinic service returned for the partner's own token.

    def partner_queue(self, ctx: Context) -> tuple[int, dict]:
        return 200, self._clinic(ctx, "GET", "/v1/staff/queue")

    def partner_referrals(self, ctx: Context) -> tuple[int, dict]:
        names = self._clinic_names(ctx)
        return 200, {"referrals": [{**r, "from_clinic_name": names.get(r.get("from_clinic_id"), r.get("from_clinic_id")),
                                    "to_clinic_name": names.get(r.get("to_clinic_id"), r.get("to_clinic_id"))}
                                   for r in self._referrals(ctx)], "clinic_id": ctx.session.clinic_id}

    def partner_card(self, ctx: Context) -> tuple[int, dict]:
        return 200, self._clinic(ctx, "GET", f"/v1/patients/{quote(ctx.params['id'], safe='')}/card")

    def partner_action(self, ctx: Context) -> tuple[int, dict]:
        action = ctx.params["action"]
        if action not in {"accept", "reject", "complete"}:
            raise GatewayError(404, "not_found", "Такого действия нет.")
        note = text(ctx.body.get("note"), "note", 500, required=False)
        body = {"actor": ctx.session.actor, **({"note": note} if note else {})}
        # Completing a referral changes nothing in the path service: the coordinator marks the visit, the doctor the outcome.
        return 200, {"referral": self._clinic(ctx, "POST", f"/v1/referrals/{quote(ctx.params['id'], safe='')}/{action}", body)}

    def patient_documents(self, ctx: Context) -> tuple[int, dict]:
        home = ("clinic_staff", self.config.home_clinic)
        items = self.upstream.json("clinic", "GET", "/v1/referrals", auth=home).get("referrals", [])
        names = {c["id"]: c["name"] for c in self.upstream.json("clinic", "GET", "/v1/clinics", auth=home).get("clinics", [])}
        mine = [r for r in items if r.get("patient_ref") == ctx.session.patient_ref]
        return 200, {"referrals": [{"id": r["id"], "to_clinic_name": names.get(r.get("to_clinic_id"), "Клиника-партнёр"),
                                    "reason": r.get("reason"), "status": r.get("status"), "created_at": r.get("created_at")}
                                   for r in mine]}
        # ---------- Rescan: врач ----------

    def doctor_dashboard(self, ctx: Context) -> tuple[int, dict]:
        episodes = self._episodes()
        names = self._patient_names()
        rows = self.data_store().studies(self.config.home_clinic)
        publics = self._many(self._public, [row["job_id"] for row in rows])
        new_studies = []
        for row, pub in zip(rows, publics):
            if pub and pub.get("status") == "awaiting_physician":
                job = self._review(row["job_id"])
                if not job:
                    continue
                finding = (job.get("result") or {}).get("findings", [{}])
                first = finding[0] if finding else {}
                new_studies.append({
                    "id": row["job_id"],
                    "patient": names.get(row.get("patient_ref"), "Пациент"),
                    "patient_ref": row.get("patient_ref"),
                    "title": self._title(row, job),
                    "modality": (job.get("study") or {}).get("modality"),
                    "finding": first.get("description") or "",
                    "created_at": row.get("created_at"),
                })
        in_progress = []
        for raw in episodes:
            if raw.get("status") != "active":
                continue
            step = self._first_unfinished(raw)
            if not step:
                continue
            ref = (raw.get("source_report") or {}).get("patient_ref")
            in_progress.append({
                "episode_id": raw["id"],
                "patient_ref": ref,
                "patient": names.get(ref, "Пациент"),
                "step": step.get("description"),
                "step_id": step.get("id"),
                "status": step.get("status"),
                "due_at": step.get("due_at"),
            })
        return 200, {
            "new_studies": new_studies,
            "in_progress": in_progress,
            "sync_status": [
                {"label": "МИС клиники", "state": "synced", "detail": "синхронизировано"},
                {"label": "Протоколы из РИС", "state": "synced", "detail": "подтягиваются сами"},
                {"label": "Маршрут и статусы", "state": "synced", "detail": "пишутся в карту"},
                {"label": "Визиты", "state": "synced", "detail": "отмечаются по данным МИС"},
            ],
        }

    def doctor_plan_preview(self, ctx: Context) -> tuple[int, dict]:
        row = self._registry_row(ctx.params["id"])
        job = self._review(row["job_id"])
        if job is None:
            raise GatewayError(409, "study_unavailable", UNAVAILABLE)
        study = job.get("study") or {}
        findings = (job.get("result") or {}).get("findings") or []
        code = findings[0].get("code") if findings else None
        recommendation = None
        if study and code:
            try:
                dry = self.upstream.json("path", "POST", "/v1/rules/dry-run", body={
                    "study_type": (MODALITY_TYPES.get(study.get("modality")) or "ct"),
                    "anatomy": study.get("anatomy"),
                    "protocol_name": study.get("protocol_name"),
                    "finding_code": code,
                }, auth="path_admin")
                steps = dry.get("steps") or []
                recommendation = {
                    "step": steps[0] if steps else None,
                    "steps": steps,
                    "manual_reason": dry.get("manual_reason"),
                    "rule_version": dry.get("rule_version"),
                }
            except GatewayError:
                recommendation = {"step": None, "steps": [], "manual_reason": "no_rule", "rule_version": None}
        specialists = self.data_store().specialists(self.config.home_clinic)
        return 200, {
            "recommendation": recommendation,
            "finding_code": code,
            "study": {k: study.get(k) for k in ("modality", "anatomy", "protocol_name")} if study else None,
            "specialists": specialists,
            "due_options": [
                {"days": 7, "label": "7 дней"},
                {"days": 14, "label": "2 недели"},
                {"days": 30, "label": "1 месяц"},
                {"days": 90, "label": "3 месяца"},
            ],
        }

    def doctor_skip_step(self, ctx: Context) -> tuple[int, dict]:
        row = self._registry_row(ctx.params["id"])
        job = self._review(row["job_id"])
        if job is None or job.get("status") != "awaiting_physician":
            raise GatewayError(409, "study_unavailable",
                               "Исследование уже подтверждено или не ждёт проверки врача.")
        conclusion = text(ctx.body.get("conclusion"), "conclusion", MAX_CONCLUSION)
        codes = list(dict.fromkeys(f.get("code") for f in (job.get("result") or {}).get("findings") or []))
        code = codes[0] if len(codes) == 1 else ctx.body.get("finding_code")
        if code not in codes:
            raise GatewayError(400, "invalid_input", "Выберите признак.")
        template = conclusion_templates(job, self._title(row, job), self.demo_texts).get(code)
        data = confirm_body(ctx.session.actor, conclusion, code, template, row.get("patient_ref"))
        status, body = self.upstream.request("image", "POST", "/v1/review/" + quote(row["job_id"], safe=""),
                                             raw=data, content_type="application/json", auth="reviewer")
        if status != 200 or not isinstance(body, dict):
            raise human_error("image", status, body)
        # Если эпизод уже создан — останавливаем его
        if body.get("routing_status") == "sent":
            episodes = self._episodes_by_report()
            raw = episodes.get(row["job_id"])
            if raw:
                try:
                    self.upstream.json("path", "POST", f"/v1/episodes/{quote(raw['id'], safe='')}/stop",
                                       body={"actor": ctx.session.actor,
                                             "reason": ctx.body.get("reason") or "Врач не назначил шаг"},
                                       auth="path_admin")
                except GatewayError:
                    pass
        item = self._doctor_item(row, body, self._patient_names(), {})
        return 200, {"study": item, "next": {"warning": "Пациент получит заключение без записи"}}

    def doctor_appointments(self, ctx: Context) -> tuple[int, dict]:
        from datetime import date, timedelta
        today = date.today()
        from_iso = ctx.query.get("from") or (today - timedelta(days=7)).isoformat()
        to_iso = ctx.query.get("to") or (today + timedelta(days=60)).isoformat()
        appts = self.data_store().appointments_between(self.config.home_clinic, from_iso, to_iso)
        names = self._patient_names()
        # Шаги достанем один раз
        episodes = {raw["id"]: raw for raw in self._episodes()}
        result = []
        for a in appts:
            ep = episodes.get(a["episode_id"]) or {}
            step = next((s for s in ep.get("plan_steps", []) if s.get("id") == a["step_id"]), {})
            result.append({
                **a,
                "patient_name": names.get(a["patient_ref"], "Пациент не указан"),
                "physician_name": step.get("owner") or "Координатор",
                "reason": step.get("description") or "",
                "clinic_name": "Клиника «Линия здоровья»",
            })
        return 200, {"appointments": result}

    def doctor_integrations(self, ctx: Context) -> tuple[int, dict]:
        health = self.upstream.health_all()
        partners = []
        try:
            partners = self.upstream.json("clinic", "GET", "/v1/partnerships",
                                          auth=("clinic_staff", self.config.home_clinic)).get("partners", [])
        except GatewayError:
            pass
        return 200, {
            "mis": {"connected": True, "last_sync": None, "name": "МедИС"},
            "ris": {"connected": True, "name": "PACS-1"},
            "ai": {"connected": health.get("image", {}).get("status") == "up",
                   "name": "Третье Мнение", "models": 4},
            "channels": {"connected": 5, "total": 5,
                         "list": ["Telegram", "MAX", "VK", "SMS", "email"]},
            "partners": {"clinics": len(partners),
                         "pharmacies": len(self.upstream.medications_with_staff())},
        }

    # ---------- Rescan: пациент ----------

    def patient_settings_get(self, ctx: Context) -> tuple[int, dict]:
        data = self.data_store().patient_settings(ctx.session.patient_ref)
        defaults = {
            "notifications": {"reminders": True, "new_results": True, "weekly_report": False},
            "channels": {"telegram": True, "max": False, "sms": True, "email": True},
        }
        merged = {**defaults, **data}
        # Добавим клинику и её название
        try:
            card = self.upstream.patient_by_ref(ctx.session.patient_ref)
        except GatewayError:
            card = None
        merged["clinic"] = {"id": (card or {}).get("home_clinic_id"),
                            "name": (card or {}).get("home_clinic_name")}
        return 200, merged

    def patient_settings_post(self, ctx: Context) -> tuple[int, dict]:
        body = ctx.body or {}
        current = self.data_store().patient_settings(ctx.session.patient_ref)
        merged = {**current, **body}
        saved = self.data_store().save_patient_settings(ctx.session.patient_ref, merged)
        return 200, {"status": "saved", "settings": saved}

    def patient_self_meds_get(self, ctx: Context) -> tuple[int, dict]:
        return 200, {"medications": self.data_store().self_medications(ctx.session.patient_ref)}

    def patient_self_meds_post(self, ctx: Context) -> tuple[int, dict]:
        body = ctx.body or {}
        name = text(body.get("name"), "name", 128)
        dose = text(body.get("dose"), "dose", 128)
        time_slot = text(body.get("time_slot"), "time_slot", 16)
        form = text(body.get("form"), "form", 32)
        if time_slot not in {"morning", "day", "evening"}:
            raise GatewayError(400, "invalid_input", "Время: morning, day или evening.")
        saved = self.data_store().add_self_medication(ctx.session.patient_ref, name, dose, time_slot, form)
        return 201, {"medication": saved}

    def patient_self_meds_remove(self, ctx: Context) -> tuple[int, dict]:
        self.data_store().remove_self_medication(ctx.session.patient_ref, ctx.params["id"])
        return 200, {"status": "removed"}

    def patient_calendar(self, ctx: Context) -> tuple[int, dict]:
        # Собираем все записи и все self-medications за месяц (упрощённо — на 30 дней вперёд и 7 назад)
        from datetime import date, timedelta
        today = date.today()
        days = {}
        for offset in range(-7, 31):
            d = (today + timedelta(days=offset)).isoformat()
            days[d] = {"date": d, "visits": 0}
        # Визиты
        for a in self.data_store().appointments_between(self.config.home_clinic, today.isoformat(),
                                                        (today + timedelta(days=31)).isoformat()):
            d = a["starts_at"][:10]
            if d in days:
                days[d]["visits"] = days[d].get("visits", 0) + 1
        # Приёмы на сегодня (по self-medications)
        today_list = []
        for m in self.data_store().self_medications(ctx.session.patient_ref):
            hour = {"morning": "08:00", "day": "13:00", "evening": "20:00"}[m["time_slot"]]
            today_list.append({"id": m["id"], "kind": "self_medication", "name": m["name"],
                               "time": hour, "dose": m["dose"]})
        return 200, {"days": list(days.values()), "today": today_list, "month": today.isoformat()[:7]}

    def patient_payment_methods(self, ctx: Context) -> tuple[int, dict]:
        return 200, {"methods": [
            {"id": "dms", "label": "Полис ДМС", "detail": "•••• 4242", "enabled": True},
            {"id": "cash", "label": "Оплата в клинике", "detail": "по прайсу", "enabled": True},
        ]}

    def _partner_booking(self, ctx: Context, raw: dict, step: dict) -> tuple[int, dict]:
        """The coordinator enters the time the partner reported: offer + confirm, marked «у партнёра»."""
        when = ctx.body.get("partner_time")
        try:
            if datetime.fromisoformat(str(when)).tzinfo is None:
                raise ValueError
        except ValueError:
            raise GatewayError(400, "invalid_input", "Укажите дату и время, которые сообщил партнёр.") from None
        clinic = text(ctx.body.get("partner_clinic_id"), "partner_clinic_id", 128)
        ref = (raw.get("source_report") or {}).get("patient_ref")
        if not any(r.get("patient_ref") == ref and r.get("to_clinic_id") == clinic and r.get("status") == "accepted"
                   for r in self._referrals(ctx)):
            raise GatewayError(409, "referral_not_accepted", "Записать к партнёру можно после того, как он принял направление.")
        if step.get("status") not in {"open", "offered"} or raw.get("status") != "active":
            raise GatewayError(409, "step_unavailable", "Этот шаг сейчас нельзя записать. Обновите карточку.")
        evidence = f"Запись у партнёра: {self._clinic_names(ctx).get(clinic, clinic)}"
        if step["status"] == "open":
            self.upstream.json("path", "POST", self._path_route(raw["id"], step["id"], "offer"), auth="path_admin",
                               body={"actor": ctx.session.actor, "evidence": evidence, "appointment_at": when})
        updated = self.upstream.json("path", "POST", self._path_route(raw["id"], step["id"], "confirm"), auth="path_admin",
                                     body={"actor": ctx.session.actor, "evidence": evidence, "appointment_at": when})
        return 200, {"episode": staff_episode(updated, self._patient_names().get(ref, "Пациент не указан"))}


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
                raw_length = 0
                if method in MUTATING:
                    origin = self.headers.get("Origin")
                    if origin is not None and origin not in {"http://" + h for h in gateway.allowed_hosts()}:
                        raise GatewayError(403, "forbidden_origin", "Запрос пришёл с чужой страницы и отклонён.")
                    if not role:
                        raise GatewayError(401, "no_session", "Окно не знает своей роли. Обновите страницу и выберите роль.")
                    content_type = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
                    if key in gateway.raw_routes:
                        # The image service answers an oversized body without reading it and the client sees a
                        # dropped connection, so type and size are checked here, before the body is read.
                        if content_type != "application/zip":
                            raise GatewayError(415, "unsupported_type", "Загрузите ZIP-архив с файлами DICOM.")
                        try:
                            raw_length = int(self.headers.get("Content-Length") or 0)
                        except ValueError:
                            raise GatewayError(400, "invalid_input", "Неверный заголовок Content-Length.") from None
                        if raw_length <= 0:
                            raise GatewayError(411, "length_required", "Архив пустой или без размера. Выберите файл заново.")
                        if raw_length > MAX_ARCHIVE:
                            raise GatewayError(413, "archive_too_large", "Архив больше 50 МиБ. Загрузите исследование без лишних файлов.")
                        body = {}
                    else:
                        if content_type != "application/json":
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
                raw = self.rfile.read(raw_length) if raw_length else b""
                ctx = Context(role, session, body, params, session_cookie=cookie, query=query, raw=raw)
                status, payload = gateway.routes[key](ctx)
                if isinstance(payload, RawResponse):
                    self._send(status, payload.data, payload.content_type, {"Cache-Control": "no-store"})
                else:
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
