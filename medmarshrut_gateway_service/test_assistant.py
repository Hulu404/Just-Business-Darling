"""Task 11: the AI assistant. A stub replaces the SDK client: no network, nothing leaves the test."""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest import mock

import anthropic
import httpx

from assistant import Assistant
from service import load_config
from test_gateway import GatewayTestCase
from test_imaging import DEMO_TEXTS, SERIES, SOPS, RegistryFake, confirmed, job, public

SUGGESTION = "Рентгенография органов грудной клетки.\nУчасток уплотнения лёгочной ткани.\n\nЗаключение: инфильтрат."
EXPLANATION = "Врач посмотрел снимок и увидел небольшой участок уплотнения в лёгком. Терапевт посмотрит вас в течение суток."
# What must never reach the API: model score and version, UIDs, image-service draft lines, the patient's identity.
NEVER_SENT = ("0.91", "confidence", "model_version", "demo-scripted", "Модель предполагает", SERIES, *SOPS, "1.2.3\"",
              "demo-patient-1", "Демо-пациент", "other-patient")


class StubMessages:
    def __init__(self):
        self.calls: list[dict] = []
        self.text, self.stop, self.error = SUGGESTION, "end_turn", None

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=self.text)],
                               stop_reason=self.stop, model=kwargs["model"],
                               usage=SimpleNamespace(input_tokens=120, output_tokens=60))


class AssistantStore(RegistryFake):
    def __init__(self):
        super().__init__()
        self.texts: dict[tuple[str, str], str] = {}

    def assistant_text(self, job_id, input_hash):
        return self.texts.get((job_id, input_hash))

    def save_assistant_text(self, job_id, input_hash, model, body):
        return self.texts.setdefault((job_id, input_hash), body)


def episode(conclusion: str = "Заключение врача по КТ") -> dict:
    return {"id": "ep-1", "status": "active", "manual_reason": None, "created_at": "2026-10-04T11:00:00Z",
            "updated_at": "2026-10-04T11:00:00Z",
            "source_report": {"source_report_id": "job-own", "patient_ref": "demo-patient-1", "confidence": 0.91,
                              "source_model": "demo-scripted-1", "conclusion": conclusion, "finding_code": "DEMO_CT_INFILTRATE"},
            "plan_steps": [{"id": "s1", "kind": "appointment", "status": "open", "position": 1,
                            "description": "Приём терапевта в течение 24 часов"}]}


class AssistantRouteTests(GatewayTestCase):
    def setUp(self):
        super().setUp()
        self.store = AssistantStore()
        self.gateway.store = self.store
        self.gateway.demo_texts = DEMO_TEXTS
        self.store.register_study("job-own", "clinic-central", "demo-patient-1", "ct_general", "КТ", None,
                                  "patient", "demo-patient-1", None)
        self.store.register_study("job-foreign", "clinic-central", "other-patient", "ct_general", "КТ", None,
                                  "staff", "coordinator-natalia", None)
        self.jobs = {"job-own": job("job-own"), "job-foreign": job("job-foreign")}
        for job_id in self.jobs:
            self.image.routes[("GET", f"/v1/review/{job_id}")] = lambda r, j=job_id: (200, self.jobs[j])
            self.image.routes[("GET", f"/v1/studies/{job_id}")] = lambda r, j=job_id: (200, public(self.jobs[j]))
        self.path.routes[("GET", "/v1/episodes")] = (200, {"episode_ids": []})
        self.clinic.routes[("GET", "/v1/patients?limit=500")] = (200, {"patients": [
            {"patient_ref": "demo-patient-1", "full_name": "Демо-пациент"}]})
        self.stub = StubMessages()
        self.gateway.assistant = Assistant(SimpleNamespace(beta=SimpleNamespace(messages=self.stub)))
        self.logged: list[str] = []
        patcher = mock.patch("assistant.log", self.logged.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def sent(self, index: int = -1) -> str:
        call = self.stub.calls[index]
        return json.dumps([call["system"], call["messages"]], ensure_ascii=False)

    def confirm_own(self, conclusion: str = "Заключение врача по КТ") -> None:
        self.jobs["job-own"] = confirmed(job("job-own"), conclusion)
        self.path.routes.update({("GET", "/v1/episodes"): (200, {"episode_ids": ["ep-1"]}),
                                 ("GET", "/v1/episodes/ep-1"): (200, episode(conclusion))})

    def rewrite(self, role="doctor", job_id="job-own", body=None):
        return self.call("POST", f"/api/doctor/studies/{job_id}/assistant/rewrite", role=role,
                         body=body or {"finding_code": "DEMO_CT_INFILTRATE", "text": "КТ. Уплотнение справа. Заключение: "})

    def explain(self, job_id="job-own"):
        return self.call("POST", f"/api/patient/studies/{job_id}/assistant/explain", role="patient", body={})

    # ---------- without a key ----------

    def test_without_key_everything_else_works(self):
        self.gateway.assistant = Assistant(None)
        for role in ("patient", "doctor"):
            self.login(role)
            status, _, body = self.call("GET", "/api/assistant/status", role=role)
            self.assertEqual((status, body), (200, {"enabled": False}))
        status, _, body = self.rewrite()
        self.assertEqual((status, body["error"]["code"]), (503, "assistant_unavailable"))
        self.assertIn("без него", body["error"]["message"])
        status, _, body = self.explain()
        self.assertEqual((status, body["error"]["code"]), (503, "assistant_unavailable"))
        status, _, body = self.call("GET", "/api/doctor/studies/job-own", role="doctor")
        self.assertEqual(status, 200, body)
        self.assertIn("DEMO_CT_INFILTRATE", body["study"]["templates"])
        status, _, body = self.call("GET", "/api/health", role="patient")
        self.assertIs(body["assistant"], False)

    def test_key_stays_in_the_gateway(self):
        key = "sk-ant-test-" + "x" * 24
        env = {**self.secrets, "CLINIC_STAFF_TOKENS": json.dumps(self.staff_tokens), "GATEWAY_STATE_DIR": self.tmp.name,
               "ANTHROPIC_API_KEY": key}
        config = load_config(env)
        self.assertNotIn(key, repr(config))
        self.assertTrue(Assistant.from_key(config.assistant_key, config.assistant_model).enabled)
        self.login("doctor")
        for path in ("/api/health", "/api/assistant/status", "/api/session"):
            _, _, body = self.call("GET", path, role="doctor")
            self.assertNotIn("sk-ant", json.dumps(body))
            self.assertNotIn("claude-", json.dumps(body))

    # ---------- physician ----------

    def test_rewrite_sends_only_depersonalised_text_and_stores_nothing(self):
        self.login("doctor")
        status, _, body = self.rewrite()
        self.assertEqual((status, body), (200, {"suggestion": SUGGESTION}))
        sent = self.sent()
        for word in NEVER_SENT:
            self.assertNotIn(word, sent)
        self.assertIn("Уплотнение справа", sent)
        self.assertIn("участок уплотнения лёгочной ткани", sent)
        call = self.stub.calls[0]
        self.assertEqual((call["model"], call["output_config"], call["betas"], call["extra_body"]),
                         ("claude-sonnet-5-5", {"effort": "low"}, ["server-side-fallback-2026-07-01"], {"fallbacks": "default"}))
        self.assertEqual([r for r in self.image.requests if r["method"] == "POST"], [])
        self.assertEqual(self.store.texts, {})
        self.assertEqual(len(self.logged), 1)
        self.assertIn("route=rewrite study=job-own", self.logged[0])
        self.assertIn("input_tokens=120", self.logged[0])
        for word in ("Уплотнение", "Заключение", "уплотнения"):
            self.assertNotIn(word, self.logged[0])

    def test_rewrite_only_for_doctor_and_only_while_waiting(self):
        for role in ("patient", "staff"):
            self.login(role)
            status, _, _ = self.rewrite(role=role)
            self.assertEqual(status, 403)
        self.login("doctor")
        status, _, body = self.rewrite(body={"finding_code": "DEMO_OTHER", "text": "Текст"})
        self.assertEqual(status, 400, body)
        status, _, _ = self.rewrite(body={"finding_code": "DEMO_CT_INFILTRATE", "text": "   "})
        self.assertEqual(status, 400)
        self.confirm_own()
        status, _, body = self.rewrite()
        self.assertEqual(status, 409, body)
        status, _, _ = self.rewrite(job_id="job-missing")
        self.assertEqual(status, 404)
        self.assertEqual(self.stub.calls, [])

    # ---------- patient ----------

    def test_explain_before_confirmation_never_calls_the_api(self):
        self.login("patient")
        status, _, body = self.explain()
        self.assertEqual((status, body["error"]["code"]), (409, "not_confirmed"))
        self.jobs["job-foreign"] = confirmed(job("job-foreign"))
        status, _, _ = self.explain("job-foreign")
        self.assertEqual(status, 404)
        self.assertEqual(self.stub.calls, [])

    def test_explain_after_confirmation_is_grounded_and_cached(self):
        self.confirm_own()
        self.stub.text = EXPLANATION
        self.login("patient")
        status, _, body = self.explain()
        self.assertEqual((status, body), (200, {"explanation": EXPLANATION}))
        sent = self.sent()
        for word in NEVER_SENT:
            self.assertNotIn(word, sent)
        for word in ("Заключение врача по КТ", "Врач подтвердил участок уплотнения", "Приём терапевта в течение 24 часов"):
            self.assertIn(word, sent)
        status, _, body = self.explain()
        self.assertEqual((status, body["explanation"], len(self.stub.calls)), (200, EXPLANATION, 1))
        self.confirm_own("Другое заключение врача")
        status, _, _ = self.explain()
        self.assertEqual((status, len(self.stub.calls)), (200, 2))
        self.assertIn("Другое заключение врача", self.sent())

    # ---------- failures ----------

    def test_failures_are_503_and_no_text_is_shown_or_stored(self):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        cases = {"refusal": {"stop": "refusal"}, "max_tokens": {"stop": "max_tokens"},
                 "too long": {"text": "а" * 1501}, "empty": {"text": "  "},
                 "connection": {"error": anthropic.APIConnectionError(request=request)}}
        self.confirm_own()
        self.login("patient")
        for name, change in cases.items():
            with self.subTest(name):
                self.stub.text, self.stub.stop, self.stub.error = "Текст, который нельзя показать", "end_turn", None
                for field, value in change.items():
                    setattr(self.stub, field, value)
                status, _, body = self.explain()
                self.assertEqual((status, body["error"]["code"]), (503, "assistant_unavailable"))
                self.assertNotIn("нельзя показать", json.dumps(body, ensure_ascii=False))
                self.assertEqual(self.store.texts, {})


if __name__ == "__main__":
    unittest.main()
