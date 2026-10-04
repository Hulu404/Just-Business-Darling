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
from urllib.parse import unquote, urlsplit

from errors import GatewayError
from sessions import ROLES, People, Session, SessionStore, cookie_name
from store import GatewayStore
from upstream import Upstream, patient_ref, service_url, text

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
                  Path(env.get("GATEWAY_PEOPLE") or REPO / "demo_stand" / "people.demo.json"), mode, urls, port)


@dataclass
class Context:
    role: str | None
    session: Session | None
    body: dict
    params: dict[str, str]
    cookies: list[str] = field(default_factory=list)
    session_cookie: str | None = None


Handler = Callable[[Context], tuple[int, dict]]


class Gateway:
    def __init__(self, config: Config, *, timeout: float | None = None):
        self.config = config
        self.port = config.port
        self.people = People(config.people_path)
        self.sessions = SessionStore()
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
        }
        self.public: set[tuple[str, str]] = {("GET", "/api/health"), ("POST", "/api/session")}
        self.access: dict[tuple[str, str], set[str]] = {
            ("GET", "/api/session"): set(ROLES),
            ("DELETE", "/api/session"): set(ROLES),
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
                path = urlsplit(self.path).path
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
                ctx = Context(role, session, body, params, session_cookie=cookie)
                status, payload = gateway.routes[key](ctx)
                self._json(status, payload, ctx.cookies)
            except GatewayError as exc:
                self._json(exc.status, exc.payload(show_detail=bool(session and session.role in DETAIL_ROLES)))
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
    store = GatewayStore(config.state_dir / "gateway.sqlite3")
    gateway = Gateway(config)
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
