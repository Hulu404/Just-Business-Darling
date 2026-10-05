"""Модуль медикаментов: рецепты, аптеки, заказы. Ходит в 8767 через Upstream."""
from __future__ import annotations

import hashlib
import hmac
from urllib.parse import quote

from errors import GatewayError


PHARMACY_LABELS = {
    "pharm-central": "Аптека «Центральная»",
    "pharm-north": "Аптека «Северная»",
    "pharm-south": "Аптека «Южная»",
}


class PharmacyModule:
    def __init__(self, upstream, config):
        self.upstream = upstream
        self.config = config

    # ---------- Пациент ----------

    def patient_offers(self, ctx):
        body = self.upstream.json("medications", "GET", "/v1/offers",
                                  auth="med_patient",
                                  token_override=self._patient_token(ctx.session.patient_ref))
        return 200, body

    def patient_prescription_offers(self, ctx):
        pid = ctx.params["id"]
        body = self.upstream.json("medications", "GET",
                                  f"/v1/prescriptions/{quote(pid, safe='')}/offers",
                                  auth="med_patient",
                                  token_override=self._patient_token(ctx.session.patient_ref))
        return 200, body

    def patient_orders(self, ctx):
        body = self.upstream.json("medications", "GET", "/v1/orders",
                                  auth="med_patient",
                                  token_override=self._patient_token(ctx.session.patient_ref))
        return 200, body

    def patient_order(self, ctx):
        oid = ctx.params["id"]
        body = self.upstream.json("medications", "GET", f"/v1/orders/{quote(oid, safe='')}",
                                  auth="med_patient",
                                  token_override=self._patient_token(ctx.session.patient_ref))
        return 200, body

    def patient_order_place(self, ctx):
        body = ctx.body
        required = {"prescription_id", "pharmacy_id", "items"}
        if not isinstance(body, dict) or set(body) != required:
            raise GatewayError(400, "invalid_input", "Нужны prescription_id, pharmacy_id и items.")
        result = self.upstream.json("medications", "POST", "/v1/orders",
                                    body=body, auth="med_patient",
                                    token_override=self._patient_token(ctx.session.patient_ref),
                                    ok={201})
        return 201, result

    def patient_order_cancel(self, ctx):
        oid = ctx.params["id"]
        result = self.upstream.json("medications", "POST",
                                    f"/v1/orders/{quote(oid, safe='')}/cancel",
                                    body=ctx.body or {}, auth="med_patient",
                                    token_override=self._patient_token(ctx.session.patient_ref))
        return 200, result

    # ---------- Врач ----------

    def doctor_prescription_create(self, ctx):
        body = ctx.body or {}
        if "patient_ref" not in body or "items" not in body:
            raise GatewayError(400, "invalid_input", "Нужны patient_ref и items.")
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        payload = {
            "source_service": "medmarshrut_path_service",
            "source_prescription_id": body.get("source_prescription_id") or f"rx-{int(now.timestamp())}",
            "source_prescription_version": 1,
            "patient_ref": body["patient_ref"],
            "physician_id": ctx.session.actor,
            "confirmed_at": now.isoformat(timespec="seconds"),
            "expires_at": body.get("expires_at") or (now + timedelta(days=60)).isoformat(timespec="seconds"),
            "conclusion": body.get("conclusion") or "Электронный рецепт",
            "study_uid": body.get("study_uid") or "1.2.3",
            "items": body["items"],
        }
        result = self.upstream.json("medications", "POST", "/v1/prescriptions",
                                    body=payload, auth="med_signed", ok={200, 201})
        return 201, result

    # ---------- Аптека ----------

    def pharmacy_queue(self, ctx):
        pharmacy_id = self._session_pharmacy(ctx)
        return 200, self.upstream.json("medications", "GET", "/v1/staff/queue",
                                       auth=("med_staff", pharmacy_id))

    def pharmacy_metrics(self, ctx):
        pharmacy_id = self._session_pharmacy(ctx)
        return 200, self.upstream.json("medications", "GET", "/v1/staff/metrics",
                                       auth=("med_staff", pharmacy_id))

    def pharmacy_catalog(self, ctx):
        pharmacy_id = self._session_pharmacy(ctx)
        return 200, self.upstream.json("medications", "GET", "/v1/staff/catalog",
                                       auth=("med_staff", pharmacy_id))

    def pharmacy_order_action(self, ctx):
        action = ctx.params["action"]
        if action not in {"confirm", "ready", "picked_up", "cancel", "fail"}:
            raise GatewayError(404, "not_found", "Такого действия нет.")
        pharmacy_id = self._session_pharmacy(ctx)
        oid = ctx.params["id"]
        note = (ctx.body or {}).get("note")
        body = {"note": note} if note else {}
        return 200, self.upstream.json("medications", "POST",
                                       f"/v1/orders/{quote(oid, safe='')}/{action}",
                                       body=body, auth=("med_staff", pharmacy_id))

    # ---------- Внутреннее ----------

    def _patient_token(self, patient_ref: str) -> str:
        if not patient_ref:
            raise GatewayError(403, "forbidden", "Нет псевдонима пациента.")
        return hmac.new(self.config.med_patient_token.encode(),
                        patient_ref.encode(), hashlib.sha256).hexdigest()

    def _session_pharmacy(self, ctx) -> str:
        pharmacy = getattr(ctx.session, "clinic_id", None)
        if not pharmacy or pharmacy not in PHARMACY_LABELS:
            raise GatewayError(403, "forbidden",
                               "Сессия не привязана к аптеке. Выберите роль «Аптека».")
        return pharmacy