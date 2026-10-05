import http.client
import importlib.util
import json
import secrets
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import service
from errors import GatewayError
from service import WEB_DIR, ConfigError, Gateway, load_config, make_handler
from sessions import ensure_owner
from upstream import Upstream, human_error, signature

REPO = Path(__file__).resolve().parents[1]

# Текстовые проверки веб-файлов — только для исходников. Картинки и шрифт читаются как байты.
TEXT_SUFFIXES = {".html", ".css", ".js", ".svg"}


def load_path_auth():
    """The path service's auth.py under another module name: the reference implementation of the signature."""
    spec = importlib.util.spec_from_file_location("path_service_auth_reference", REPO / "medmarshrut_path_service" / "auth.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PATH_AUTH = load_path_auth()


class FakeService:
    """Records requests and answers with canned responses. mode: ok, drop (close without answer), slow."""

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.requests = []
        self.mode = "ok"
        self.delay = 0.0
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                return

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                request = {"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body}
                fake.requests.append(request)
                if fake.mode == "drop":
                    return
                if fake.mode == "slow":
                    time.sleep(fake.delay)
                answer = fake.routes.get((self.command, self.path))
                if answer is None:
                    prefix = next((k for k in fake.routes if k[0] == self.command and k[1].endswith("*")
                                   and self.path.startswith(k[1][:-1])), None)
                    answer = fake.routes.get(prefix)
                status, payload = answer(request) if callable(answer) else answer if answer else (404, {"error": "Not found"})
                binary = isinstance(payload, bytes)
                data = payload if binary else json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/dicom" if binary else "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_DELETE = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class GatewayTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.secrets = {name: f"secret-{name.lower()}-{secrets.token_hex(12)}"
                        for name in ("REVIEWER_TOKEN", "PATH_ADMIN_TOKEN", "PATH_MIS_TOKEN", "CLINIC_SHARED_SECRET")}
        self.staff_tokens = {f"staff-{c}-{secrets.token_hex(12)}": c
                             for c in ("clinic-central", "clinic-partner-1", "clinic-partner-2")}
        self.patients = {"demo-patient-1": {"patient_ref": "demo-patient-1", "home_clinic_id": "clinic-central",
                                            "home_clinic_name": "Центральная", "status": "active"},
                         "foreign-patient": {"patient_ref": "foreign-patient", "home_clinic_id": "clinic-partner-1",
                                             "home_clinic_name": "Лесная", "status": "active"},
                         "archived-patient": {"patient_ref": "archived-patient", "home_clinic_id": "clinic-central",
                                              "home_clinic_name": "Центральная", "status": "archived"}}
        self.image = FakeService({("GET", "/health"): (200, {"status": "ok"})})
        self.path = FakeService({("GET", "/health"): (200, {"status": "ok"})})
        self.clinic = FakeService({("GET", "/health"): (200, {"status": "ok", "network_version": "test-net-1"}),
                                   ("GET", "/v1/patients/by-ref/*"): self.by_ref})
        for fake in (self.image, self.path, self.clinic):
            self.addCleanup(fake.stop)
        env = {**self.secrets, "CLINIC_STAFF_TOKENS": json.dumps(self.staff_tokens),
               "GATEWAY_STATE_DIR": self.tmp.name, "GATEWAY_PEOPLE": str(REPO / "demo_stand" / "people.demo.json"),
               "GATEWAY_IMAGING_MODE": "demo-scripted", "IMAGE_URL": self.image.url, "PATH_URL": self.path.url,
               "CLINIC_URL": self.clinic.url, "GATEWAY_PORT": "0"}
        # Windows retries a refused loopback connect for about two seconds, so keep the timeout above that.
        self.gateway = Gateway(load_config(env), timeout=5)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.gateway))
        self.gateway.port = self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.cookies = {}
        self.responses = []

    def by_ref(self, request):
        timestamp = request["headers"].get("X-Path-Timestamp", "")
        provided = request["headers"].get("X-Path-Signature", "")
        if not PATH_AUTH.verify(self.secrets["CLINIC_SHARED_SECRET"], timestamp, provided, b""):
            return 403, {"error": "Invalid interservice signature"}
        patient = self.patients.get(request["path"].rsplit("/", 1)[1])
        return (200, patient) if patient else (404, {"error": "Not found"})

    def call(self, method, path, *, role=None, body=None, headers=None, host=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        sent = {"Host": host or f"127.0.0.1:{self.port}"}
        if role:
            sent["X-MM-Role"] = role
        data = raw
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            sent["Content-Type"] = "application/json"
        if self.cookies:  # a browser sends every cookie of the origin, whatever the window
            sent["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        sent.update(headers or {})
        connection.request(method, path, body=data, headers=sent)
        response = connection.getresponse()
        payload = response.read()
        connection.close()
        for header in response.headers.get_all("Set-Cookie") or []:
            name, value = header.split(";", 1)[0].split("=", 1)
            if "Max-Age=0" in header:
                self.cookies.pop(name, None)
            else:
                self.cookies[name] = value
        self.responses.append((response.status, str(response.headers), payload))
        parsed = json.loads(payload) if response.headers.get("Content-Type", "").startswith("application/json") else None
        return response.status, response.headers, parsed if parsed is not None else payload

    def login(self, role, **extra):
        return self.call("POST", "/api/session", role=role, body={"role": role, **extra})


class SignatureTests(GatewayTestCase):
    def test_signature_matches_path_service(self):
        for body in (b"", b'{"a":1}', json.dumps({"text": "Кириллица"}, ensure_ascii=False).encode("utf-8")):
            self.assertEqual(signature("secret-1234567890", "1700000000", body),
                             PATH_AUTH.signature("secret-1234567890", "1700000000", body))

    def test_get_is_signed_over_empty_body(self):
        status, _, body = self.login("patient")
        self.assertEqual(status, 201, body)
        request = self.clinic.requests[-1]
        self.assertEqual(request["path"], "/v1/patients/by-ref/demo-patient-1")
        self.assertTrue(PATH_AUTH.verify(self.secrets["CLINIC_SHARED_SECRET"], request["headers"]["X-Path-Timestamp"],
                                         request["headers"]["X-Path-Signature"], b""))

    def test_cyrillic_body_is_signed_over_sent_utf8_bytes(self):
        self.clinic.routes[("POST", "/v1/route-candidates")] = lambda r: (
            (200, {"ok": True}) if PATH_AUTH.verify(self.secrets["CLINIC_SHARED_SECRET"], r["headers"]["X-Path-Timestamp"],
                                                    r["headers"]["X-Path-Signature"], r["body"]) else (403, {}))
        status, body = self.gateway.upstream.request("clinic", "POST", "/v1/route-candidates",
                                                     body={"reason": "Контрольная КТ"}, auth="clinic_signed")
        self.assertEqual((status, body), (200, {"ok": True}))
        raw = self.clinic.requests[-1]["body"]
        self.assertIn("Контрольная КТ".encode("utf-8"), raw)
        self.assertNotIn(b"\\u", raw)


class SessionTests(GatewayTestCase):
    def test_cookie_flags_and_public_fields(self):
        status, headers, body = self.login("staff")
        self.assertEqual(status, 201)
        self.assertEqual(body, {"role": "staff", "name": "Наталья", "clinic_id": "clinic-central"})
        cookie = headers.get_all("Set-Cookie")[0]
        self.assertTrue(cookie.startswith("mm_session_staff="))
        for flag in ("HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(flag, cookie)

    def test_role_bodies(self):
        self.assertEqual(self.login("doctor")[2], {"role": "doctor", "name": "Врач клиники, демо-роль", "clinic_id": "clinic-central"})
        self.assertEqual(self.login("patient")[2], {"role": "patient", "name": "Демо-пациент", "patient_ref": "demo-patient-1"})
        self.assertEqual(self.login("partner", clinic_id="clinic-partner-2")[2]["clinic_id"], "clinic-partner-2")
        self.assertEqual(self.login("partner", clinic_id="clinic-central")[0], 400)
        self.assertEqual(self.login("partner", clinic_id="clinic-unknown")[0], 400)

    def test_no_session_is_401(self):
        self.assertEqual(self.call("GET", "/api/session", role="staff")[0], 401)
        self.login("staff")
        self.assertEqual(self.call("GET", "/api/session", role="doctor")[0], 401)
        self.assertEqual(self.call("GET", "/api/session")[0], 401)

    def test_two_roles_live_side_by_side(self):
        self.login("staff")
        self.login("patient")
        self.assertEqual(self.call("GET", "/api/session", role="staff")[2]["role"], "staff")
        self.assertEqual(self.call("GET", "/api/session", role="patient")[2]["patient_ref"], "demo-patient-1")
        status, _, _ = self.call("DELETE", "/api/session", role="patient", headers={"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(self.call("GET", "/api/session", role="patient")[0], 401)
        self.assertEqual(self.call("GET", "/api/session", role="staff")[0], 200)

    def test_cookie_of_one_role_does_not_open_another(self):
        self.login("patient")
        self.cookies["mm_session_staff"] = self.cookies["mm_session_patient"]
        self.assertEqual(self.call("GET", "/api/session", role="staff")[0], 401)

    def test_unknown_foreign_or_inactive_patient_is_not_created(self):
        for ref, code in (("missing-patient", "unknown_patient"), ("foreign-patient", "foreign_patient"),
                          ("archived-patient", "inactive_patient")):
            status, headers, body = self.login("patient", patient_ref=ref)
            self.assertEqual((status, body["error"]["code"]), (400, code))
            self.assertIsNone(headers.get("Set-Cookie"))
        self.assertEqual(self.login("patient", patient_ref="bad/ref")[0], 400)

    def test_body_role_must_match_window_role_and_no_extra_fields(self):
        self.assertEqual(self.call("POST", "/api/session", role="staff", body={"role": "doctor"})[0], 400)
        self.assertEqual(self.login("staff", actor="someone-else")[0], 400)

    def test_ensure_owner(self):
        self.login("patient")
        session = self.gateway.sessions.get("patient", self.cookies["mm_session_patient"])
        ensure_owner(session, "demo-patient-1")
        with self.assertRaises(GatewayError) as caught:
            ensure_owner(session, "demo-patient-2")
        self.assertEqual(caught.exception.status, 404)
        self.login("staff")
        ensure_owner(self.gateway.sessions.get("staff", self.cookies["mm_session_staff"]), "demo-patient-2")


class AccessTests(GatewayTestCase):
    def test_order_404_401_403(self):
        self.gateway.routes[("GET", "/api/unlisted")] = lambda ctx: (200, {"ok": True})
        self.gateway.routes[("GET", "/api/staff-only/{id}")] = lambda ctx: (200, ctx.params)
        self.gateway.access[("GET", "/api/staff-only/{id}")] = {"staff"}
        self.assertEqual(self.call("GET", "/api/nothing-here")[0], 404)
        self.assertEqual(self.call("GET", "/api/unlisted")[0], 401)
        self.login("patient")
        self.assertEqual(self.call("GET", "/api/unlisted", role="patient")[0], 403)
        self.assertEqual(self.call("GET", "/api/staff-only/42", role="patient")[0], 403)
        self.login("staff")
        self.assertEqual(self.call("GET", "/api/staff-only/42", role="staff")[2], {"id": "42"})

    def test_host_origin_role_type_and_size(self):
        self.assertEqual(self.call("GET", "/api/health", host="evil.example:80")[0], 403)
        self.assertEqual(self.call("GET", "/", host=f"localhost:{self.port}")[0], 200)
        status, _, body = self.call("POST", "/api/session", role="staff", body={"role": "staff"},
                                    headers={"Origin": "http://evil.example"})
        self.assertEqual((status, body["error"]["code"]), (403, "forbidden_origin"))
        self.assertEqual(self.call("POST", "/api/session", role="staff", body={"role": "staff"},
                                   headers={"Origin": f"http://localhost:{self.port}"})[0], 201)
        self.assertEqual(self.call("POST", "/api/session", body={"role": "staff"})[0], 401)
        self.assertEqual(self.call("GET", "/api/health", host="demo.example.org")[0], 403)
        self.gateway.public_hosts = ("demo.example.org",)
        self.assertEqual(self.call("GET", "/api/health", host="demo.example.org")[0], 200)
        self.assertEqual(self.call("POST", "/api/session", role="staff", body={"role": "staff"}, host="demo.example.org",
                                   headers={"Origin": "https://demo.example.org"})[0], 201)
        status, _, body = self.call("POST", "/api/session", role="staff", body={"role": "staff"},
                                    host="demo.example.org", headers={"Origin": "http://demo.example.org"})
        self.assertEqual((status, body["error"]["code"]), (403, "forbidden_origin"))
        self.assertEqual(self.call("GET", "/api/health", host="evil.example:80")[0], 403)
        self.assertEqual(self.call("POST", "/api/session", role="staff", raw=b"role=staff",
                                   headers={"Content-Type": "application/x-www-form-urlencoded"})[0], 415)
        self.assertEqual(self.call("POST", "/api/session", role="staff", raw=b"",
                                   headers={"Content-Type": "application/json", "Content-Length": str(64 * 1024)})[0], 413)
        self.assertEqual(self.call("POST", "/api/session", role="staff", raw=b"{not json",
                                   headers={"Content-Type": "application/json"})[0], 400)

    def test_security_headers(self):
        _, headers, _ = self.call("GET", "/api/health")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(headers["Cache-Control"], "no-store")


class StaticTests(GatewayTestCase):
    def test_index_and_assets(self):
        status, headers, body = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertIn("МедМаршрут".encode("utf-8"), body)
        status, headers, _ = self.call("GET", "/assets/js/main.js")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/javascript"))
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_font_and_webp_served_with_type(self):
        # Шрифта в git нет, картинки лежат по разным путям: проверяем на временной папке.
        with tempfile.TemporaryDirectory() as directory:
            web = Path(directory).resolve()
            (web / "fonts").mkdir()
            (web / "img").mkdir()
            (web / "fonts" / "Stolzl-Regular.otf").write_bytes(b"OTTO\x00\x01font")
            (web / "img" / "pic.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBPvp8")
            with mock.patch.object(service, "WEB_DIR", web):
                status, headers, body = self.call("GET", "/assets/fonts/Stolzl-Regular.otf")
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Type"], "font/otf")
                self.assertEqual(body, b"OTTO\x00\x01font")
                status, headers, body = self.call("GET", "/assets/img/pic.webp")
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Type"], "image/webp")
                self.assertEqual(body, b"RIFF\x00\x00\x00\x00WEBPvp8")
        self.assertEqual(self.call("GET", "/assets/index.txt")[0], 404)

    def test_csp_allows_self_font_and_script(self):
        self.assertIn("font-src 'self'", service.CSP)
        self.assertIn("script-src 'self'", service.CSP)
        _, headers, _ = self.call("GET", "/")
        self.assertIn("font-src 'self'", headers["Content-Security-Policy"])
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])

    def test_health_reports_brand_font(self):
        with tempfile.TemporaryDirectory() as directory:
            font = Path(directory) / "Stolzl-Regular.otf"
            with mock.patch.object(service, "BRAND_FONT", font):
                self.assertEqual(self.call("GET", "/api/health")[2]["brand_font"], False)
                font.write_bytes(b"OTTO")
                self.assertEqual(self.call("GET", "/api/health")[2]["brand_font"], True)

    def test_no_escape_from_web(self):
        for path in ("/assets/../service.py", "/assets/..%2fservice.py", "/assets/%2e%2e/%2e%2e/start.py",
                     "/assets/js/../../test_gateway.py", "/assets/..\\service.py", "/assets/C:/Windows/win.ini",
                     "/assets/index.txt", "/service.py", "/assets/"):
            self.assertEqual(self.call("GET", path)[0], 404, path)

    def test_nested_modules_and_styles(self):
        status, headers, _ = self.call("GET", "/assets/js/pages/patient.js")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/javascript"))
        status, headers, _ = self.call("GET", "/assets/styles.css")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/css"))

    def test_web_has_no_storage_external_urls_or_inline_handlers(self):
        for path in WEB_DIR.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            content = path.read_text(encoding="utf-8")
            self.assertNotRegex(content, r"localStorage|sessionStorage", path.name)
            self.assertNotRegex(content, r"https?://|(?<![:\w])//[a-z0-9-]+\.[a-z]{2,}", path.name)
            self.assertNotRegex(content, r"\son[a-z]+\s*=\s*['\"]", path.name)

    def test_html_has_no_inline_scripts(self):
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)")
        self.assertNotRegex(html, r"\son[a-z]+\s*=")


class SecretTests(GatewayTestCase):
    def test_no_secret_in_responses_or_web_files(self):
        self.call("GET", "/api/health")
        self.call("GET", "/")
        self.call("GET", "/assets/js/main.js")
        for role in ("patient", "staff", "doctor", "partner"):
            self.login(role)
            self.call("GET", "/api/session", role=role)
        self.login("patient", patient_ref="missing-patient")
        self.call("GET", "/api/nothing-here")
        self.clinic.mode = "drop"
        self.login("patient")
        values = list(self.secrets.values()) + list(self.staff_tokens)
        self.assertGreater(len(self.responses), 10)
        for status, headers, payload in self.responses:
            for value in values:
                self.assertNotIn(value, headers)
                self.assertNotIn(value.encode(), payload)
        for path in WEB_DIR.rglob("*"):
            if path.is_file():
                content = path.read_bytes()
                for value in values:
                    self.assertNotIn(value.encode(), content)


class UpstreamFailureTests(GatewayTestCase):
    def test_health_reports_down_service(self):
        status, _, body = self.call("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["auth"], "demo-roles")
        self.assertEqual(body["imaging_mode"], "demo-scripted")
        self.assertEqual(body["services"]["clinic"], {"status": "up", "port": self.clinic.port, "network_version": "test-net-1"})
        self.image.stop()
        self.path.mode = "drop"
        status, _, body = self.call("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["services"]["image"]["status"], "down")
        self.assertEqual(body["services"]["path"]["status"], "down")
        self.assertEqual(body["services"]["clinic"]["status"], "up")

    def test_dropped_connection_is_502(self):
        self.clinic.mode = "drop"
        status, _, body = self.login("patient")
        self.assertEqual(status, 502)
        self.assertEqual(body["error"]["code"], "upstream_unavailable")
        self.assertIn("сервис клиники", body["error"]["message"].lower())

    def test_stopped_service_is_502_and_timeout_is_504(self):
        self.clinic.stop()
        status, _, body = self.login("patient")
        self.assertEqual((status, body["error"]["code"]), (502, "upstream_unavailable"))
        slow = FakeService({("GET", "/health"): (200, {"status": "ok"})})
        self.addCleanup(slow.stop)
        slow.mode, slow.delay = "slow", 1.5
        upstream = Upstream({"image": slow.url, "path": slow.url, "clinic": slow.url}, reviewer_token="r" * 16,
                            path_admin_token="a" * 16, path_mis_token="", clinic_secret="s" * 16, clinic_tokens={},
                            timeout=0.3)
        with self.assertRaises(GatewayError) as caught:
            upstream.request("path", "GET", "/health")
        self.assertEqual((caught.exception.status, caught.exception.code), (504, "upstream_timeout"))

    def test_upstream_error_text_and_detail_by_role(self):
        error = human_error("clinic", 409, {"error": "Active referral already exists for this pair"})
        self.assertEqual((error.status, error.code), (409, "upstream_rejected"))
        self.assertIn("Направление этому партнёру уже есть", error.message)
        self.assertNotIn("detail", error.payload(show_detail=False)["error"])
        self.assertEqual(error.payload(show_detail=True)["error"]["detail"], "Active referral already exists for this pair")
        self.assertEqual(human_error("path", 403, {"error": "Administrator authorization required"}).status, 502)
        self.gateway.routes[("GET", "/api/conflict")] = lambda ctx: (_ for _ in ()).throw(error)
        self.gateway.access[("GET", "/api/conflict")] = {"patient", "staff"}
        self.login("patient")
        self.login("staff")
        self.assertNotIn("detail", self.call("GET", "/api/conflict", role="patient")[2]["error"])
        self.assertIn("detail", self.call("GET", "/api/conflict", role="staff")[2]["error"])

    def test_internal_error_has_no_traceback(self):
        def broken(ctx):
            raise RuntimeError("boom with internals")
        self.gateway.routes[("GET", "/api/broken")] = broken
        self.gateway.access[("GET", "/api/broken")] = {"staff"}
        self.login("staff")
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()):
            status, _, body = self.call("GET", "/api/broken", role="staff")
        self.assertEqual((status, body["error"]["code"]), (500, "internal"))
        self.assertNotIn("boom", json.dumps(body))
        self.assertNotIn("Traceback", json.dumps(body))


class ConfigTests(unittest.TestCase):
    def base(self):
        return {"REVIEWER_TOKEN": "r" * 16, "PATH_ADMIN_TOKEN": "a" * 16, "CLINIC_SHARED_SECRET": "s" * 16,
                "CLINIC_STAFF_TOKENS": json.dumps({"t" * 16: "clinic-central"}), "GATEWAY_STATE_DIR": "state"}

    def test_valid_and_defaults(self):
        config = load_config(self.base())
        self.assertEqual((config.port, config.home_clinic, config.imaging_mode), (8763, "clinic-central", "no-model"))
        self.assertEqual(config.urls["path"], "http://127.0.0.1:8765")

    def test_missing_or_short_secret_is_named(self):
        for name in ("REVIEWER_TOKEN", "PATH_ADMIN_TOKEN", "CLINIC_SHARED_SECRET"):
            for value in (None, "short"):
                env = self.base()
                env.pop(name) if value is None else env.update({name: value})
                with self.assertRaisesRegex(ConfigError, name):
                    load_config(env)
        with self.assertRaisesRegex(ConfigError, "PATH_MIS_TOKEN"):
            load_config({**self.base(), "PATH_MIS_TOKEN": "short"})

    def test_staff_tokens_urls_and_mode(self):
        with self.assertRaisesRegex(ConfigError, "CLINIC_STAFF_TOKENS"):
            load_config({**self.base(), "CLINIC_STAFF_TOKENS": "not json"})
        with self.assertRaisesRegex(ConfigError, "GATEWAY_HOME_CLINIC"):
            load_config({**self.base(), "GATEWAY_HOME_CLINIC": "clinic-other"})
        with self.assertRaisesRegex(ConfigError, "PATH_URL"):
            load_config({**self.base(), "PATH_URL": "http://example.com:8765"})
        with self.assertRaisesRegex(ConfigError, "GATEWAY_IMAGING_MODE"):
            load_config({**self.base(), "GATEWAY_IMAGING_MODE": "magic"})
        with self.assertRaisesRegex(ConfigError, "GATEWAY_STATE_DIR"):
            load_config({k: v for k, v in self.base().items() if k != "GATEWAY_STATE_DIR"})

    def test_public_hosts(self):
        self.assertEqual(load_config(self.base()).public_hosts, ())
        config = load_config({**self.base(), "GATEWAY_PUBLIC_HOSTS": " WWW.Demo.example.org, x.up.railway.app "})
        self.assertEqual(config.public_hosts, ("www.demo.example.org", "x.up.railway.app"))
        for bad in ("https://demo.example.org", "demo.example.org:443", "localhost", "demo.example.org/path"):
            with self.assertRaisesRegex(ConfigError, "GATEWAY_PUBLIC_HOSTS"):
                load_config({**self.base(), "GATEWAY_PUBLIC_HOSTS": bad})


if __name__ == "__main__":
    unittest.main()
