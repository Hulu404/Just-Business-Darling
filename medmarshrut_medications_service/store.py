"""SQLite repository for prescriptions, offers and orders."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from catalog import Catalog
from domain import (FORM_KINDS, ORDER_STATUSES, Order, OrderItem, Prescription,
                    PrescriptionItem)


class MedError(ValueError):
    pass


class ConflictError(MedError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso(value, name):
    if not isinstance(value, str):
        raise MedError(f"Invalid {name}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise MedError(f"Invalid {name}") from None
    if parsed.tzinfo is None:
        raise MedError(f"{name} needs a time zone")
    return parsed


def validate_prescription(payload: dict) -> None:
    required = {"source_service", "source_prescription_id", "source_prescription_version",
                "patient_ref", "physician_id", "confirmed_at", "expires_at", "conclusion",
                "study_uid", "items"}
    if not isinstance(payload, dict) or set(payload) != required:
        raise MedError("Invalid prescription fields")
    if payload["source_service"] not in {"medmarshrut_path_service", "medmarshrut_mis"}:
        raise MedError("Only physician-signed prescriptions from path service or MIS are accepted")
    for key in ("source_prescription_id", "patient_ref", "physician_id", "conclusion", "study_uid"):
        value = payload[key]
        if not isinstance(value, str) or not value.strip() or len(value) > (4000 if key == "conclusion" else 256):
            raise MedError(f"Invalid {key}")
    if type(payload["source_prescription_version"]) is not int or payload["source_prescription_version"] < 1:
        raise MedError("Invalid source prescription version")
    confirmed = _iso(payload["confirmed_at"], "confirmed_at")
    expires = _iso(payload["expires_at"], "expires_at")
    if expires <= confirmed:
        raise MedError("expires_at must be after confirmed_at")
    items = payload["items"]
    if not isinstance(items, list) or not 1 <= len(items) <= 20:
        raise MedError("Prescription needs 1-20 items")
    for item in items:
        required_item = {"inn", "trade_name", "form", "strength", "dosage", "duration_days", "quantity", "substitution_allowed"}
        if not isinstance(item, dict) or set(item) != required_item:
            raise MedError("Invalid prescription item")
        if not isinstance(item["inn"], str) or not item["inn"].strip():
            raise MedError("Invalid INN")
        if item["trade_name"] is not None and (not isinstance(item["trade_name"], str) or not item["trade_name"].strip()):
            raise MedError("Invalid trade_name")
        if item["form"] not in FORM_KINDS:
            raise MedError("Invalid form")
        if not isinstance(item["strength"], str) or not item["strength"].strip():
            raise MedError("Invalid strength")
        if not isinstance(item["dosage"], str) or not item["dosage"].strip() or len(item["dosage"]) > 500:
            raise MedError("Invalid dosage")
        if type(item["duration_days"]) is not int or not 1 <= item["duration_days"] <= 365:
            raise MedError("Invalid duration_days")
        if type(item["quantity"]) is not int or not 1 <= item["quantity"] <= 1000:
            raise MedError("Invalid quantity")
        if type(item["substitution_allowed"]) is not bool:
            raise MedError("Invalid substitution_allowed")


class MedStore:
    def __init__(self, db_path: Path, catalog: Catalog, inventory_path: Path):
        self.catalog = catalog
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS prescriptions (
                id TEXT PRIMARY KEY, source_service TEXT NOT NULL, source_prescription_id TEXT NOT NULL,
                source_prescription_version INTEGER NOT NULL, patient_ref TEXT NOT NULL,
                physician_id TEXT NOT NULL, confirmed_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                conclusion TEXT NOT NULL, study_uid TEXT NOT NULL, status TEXT NOT NULL,
                items_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(source_service, source_prescription_id, source_prescription_version));
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY, prescription_id TEXT NOT NULL REFERENCES prescriptions(id),
                patient_ref TEXT NOT NULL, pharmacy_id TEXT NOT NULL, status TEXT NOT NULL,
                total REAL NOT NULL, currency TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL REFERENCES orders(id),
                medication_id TEXT NOT NULL, trade_name TEXT NOT NULL, quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL, currency TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, prescription_id TEXT, order_id TEXT,
                event_type TEXT NOT NULL, actor TEXT NOT NULL, occurred_at TEXT NOT NULL, details_json TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_prescriptions_patient ON prescriptions(patient_ref);
            CREATE INDEX IF NOT EXISTS idx_orders_patient ON orders(patient_ref);
            CREATE INDEX IF NOT EXISTS idx_orders_pharmacy ON orders(pharmacy_id);
        """)
        inv = json.loads(Path(inventory_path).read_text(encoding="utf-8-sig"))
        if not isinstance(inv, dict) or set(inv) != {"version", "inventory"}:
            raise MedError("Invalid inventory file")
        self.inventory_version = inv["version"]
        self.inventory: list[dict] = []
        seen = set()
        for row in inv["inventory"]:
            required = {"pharmacy_id", "medication_id", "stock", "price", "currency", "updated_at"}
            if not isinstance(row, dict) or set(row) != required:
                raise MedError("Invalid inventory entry")
            if row["pharmacy_id"] not in catalog.pharmacies or row["medication_id"] not in catalog.medications:
                raise MedError("Inventory references unknown pharmacy or medication")
            if type(row["stock"]) is not int or row["stock"] < 0:
                raise MedError("Invalid stock")
            if not isinstance(row["price"], (int, float)) or not math.isfinite(row["price"]) or row["price"] < 0:
                raise MedError("Invalid price")
            if not isinstance(row["currency"], str) or len(row["currency"]) != 3:
                raise MedError("Invalid currency")
            _iso(row["updated_at"], "updated_at")
            key = (row["pharmacy_id"], row["medication_id"])
            if key in seen:
                raise MedError("Duplicate inventory row")
            seen.add(key)
            self.inventory.append(dict(row))

    def close(self) -> None:
        with self._lock:
            self.db.close()

    def _event(self, prescription_id, order_id, event_type, actor, details):
        self.db.execute("INSERT INTO audit_events(prescription_id,order_id,event_type,actor,occurred_at,details_json) VALUES(?,?,?,?,?,?)",
                        (prescription_id, order_id, event_type, actor, now(), json.dumps(details, ensure_ascii=False, sort_keys=True)))

    # ---------- prescriptions ----------

    def ingest_prescription(self, payload: dict) -> tuple[Prescription, bool]:
        validate_prescription(payload)
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(body.encode()).hexdigest()
        with self._lock, self.db:
            existing = self.db.execute(
                "SELECT id,payload_sha256 FROM prescriptions WHERE source_service=? AND source_prescription_id=? AND source_prescription_version=?",
                (payload["source_service"], payload["source_prescription_id"], payload["source_prescription_version"])).fetchone()
            if existing:
                if existing["payload_sha256"] != digest:
                    raise ConflictError("Same prescription version has different content")
                return self.get_prescription(existing["id"]), True
            stamp = now()
            pid = uuid.uuid4().hex
            items_json = json.dumps(payload["items"], ensure_ascii=False, sort_keys=True)
            self.db.execute("INSERT INTO prescriptions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (pid, payload["source_service"], payload["source_prescription_id"],
                             payload["source_prescription_version"], payload["patient_ref"],
                             payload["physician_id"], payload["confirmed_at"], payload["expires_at"],
                             payload["conclusion"], payload["study_uid"], "active", items_json, digest, stamp))
            self._event(pid, None, "prescription_ingested", payload["source_service"], {"items": len(payload["items"])})
            return self.get_prescription(pid), False

    def get_prescription(self, pid: str) -> Prescription | None:
        with self._lock:
            row = self.db.execute("SELECT * FROM prescriptions WHERE id=?", (pid,)).fetchone()
            if not row:
                return None
            items = tuple(PrescriptionItem(position=i + 1, **item)
                          for i, item in enumerate(json.loads(row["items_json"])))
            return Prescription(id=row["id"], source_prescription_id=row["source_prescription_id"],
                                source_version=row["source_prescription_version"], patient_ref=row["patient_ref"],
                                physician_id=row["physician_id"], confirmed_at=row["confirmed_at"],
                                expires_at=row["expires_at"], conclusion=row["conclusion"],
                                study_uid=row["study_uid"], status=row["status"],
                                created_at=row["created_at"], items=items)

    def list_prescriptions(self, patient_ref: str) -> list[Prescription]:
        with self._lock:
            ids = [r["id"] for r in self.db.execute(
                "SELECT id FROM prescriptions WHERE patient_ref=? ORDER BY created_at DESC", (patient_ref,))]
        return [self.get_prescription(i) for i in ids]

    def _expire_status(self, p: Prescription) -> str:
        if p.status != "active":
            return p.status
        if datetime.fromisoformat(p.expires_at) < datetime.now(timezone.utc):
            return "expired"
        return "active"

    # ---------- offers ----------

    def match_offers(self, prescription_id: str) -> dict:
        p = self.get_prescription(prescription_id)
        if not p:
            raise MedError("Prescription not found")
        status = self._expire_status(p)
        if status != "active":
            return {"prescription_id": prescription_id, "status": status, "offers": [], "reason": f"prescription_{status}"}
        offers = []
        for item in p.items:
            matches = self.catalog.find_exact(item.inn, item.form, item.strength)
            if item.trade_name:
                exact = [m for m in matches if m.trade_name.lower() == item.trade_name.lower()]
                if not exact:
                    offers.append({"position": item.position, "inn": item.inn,
                                   "trade_name": item.trade_name, "form": item.form, "strength": item.strength,
                                   "quantity": item.quantity, "substitution_allowed": item.substitution_allowed,
                                   "options": [], "reason": "not_in_catalog"})
                    continue
                if item.substitution_allowed:
                    candidates = matches
                else:
                    candidates = exact
            else:
                candidates = matches
            options = []
            for med in candidates:
                for inv in self.inventory:
                    if inv["medication_id"] == med.id and inv["stock"] > 0:
                        pharm = self.catalog.pharmacies.get(inv["pharmacy_id"])
                        if not pharm or not pharm.active:
                            continue
                        options.append({"pharmacy_id": pharm.id, "pharmacy_name": pharm.name,
                                        "city": pharm.city, "medication_id": med.id,
                                        "trade_name": med.trade_name, "inn": med.inn,
                                        "form": med.form, "strength": med.strength,
                                        "price": inv["price"], "currency": inv["currency"],
                                        "stock": inv["stock"],
                                        "is_substitution": bool(item.trade_name and med.trade_name.lower() != item.trade_name.lower()),
                                        "prescription_required": med.prescription_required})
            options.sort(key=lambda o: (o["is_substitution"], o["price"]))
            offers.append({"position": item.position, "inn": item.inn,
                           "trade_name": item.trade_name, "form": item.form, "strength": item.strength,
                           "dosage": item.dosage, "duration_days": item.duration_days,
                           "quantity": item.quantity, "substitution_allowed": item.substitution_allowed,
                           "options": options,
                           "reason": None if options else "no_stock_in_partner_pharmacies"})
        return {"prescription_id": prescription_id, "status": "active", "offers": offers, "reason": None}

    # ---------- orders ----------

    def place_order(self, prescription_id: str, patient_ref: str, pharmacy_id: str, items: list[dict]) -> Order:
        if not isinstance(items, list) or not 1 <= len(items) <= 20:
            raise MedError("Order needs 1-20 items")
        for item in items:
            if not isinstance(item, dict) or set(item) != {"medication_id", "quantity"}:
                raise MedError("Invalid order item")
            if not isinstance(item["medication_id"], str) or not item["medication_id"]:
                raise MedError("Invalid medication_id")
            if type(item["quantity"]) is not int or not 1 <= item["quantity"] <= 1000:
                raise MedError("Invalid quantity")
        with self._lock, self.db:
            p = self.get_prescription(prescription_id)
            if not p:
                raise MedError("Prescription not found")
            if p.patient_ref != patient_ref:
                raise ConflictError("Prescription belongs to another patient")
            status = self._expire_status(p)
            if status != "active":
                raise ConflictError(f"Prescription is {status}")
            if pharmacy_id not in self.catalog.pharmacies or not self.catalog.pharmacies[pharmacy_id].active:
                raise MedError("Unknown or inactive pharmacy")
            order_items = []
            total = 0.0
            currency = None
            for item in items:
                med = self.catalog.medications.get(item["medication_id"])
                if not med or not med.active:
                    raise MedError(f"Medication {item['medication_id']} not available")
                matched_item = next((pi for pi in p.items if pi.inn.lower() == med.inn.lower()
                                     and pi.form.lower() == med.form.lower()
                                     and pi.strength.lower() == med.strength.lower()), None)
                if not matched_item:
                    raise ConflictError("Ordered medication does not match prescription")
                if matched_item.trade_name and not matched_item.substitution_allowed:
                    if med.trade_name.lower() != matched_item.trade_name.lower():
                        raise ConflictError("Substitution not allowed for this prescription item")
                inv = next((i for i in self.inventory if i["pharmacy_id"] == pharmacy_id and i["medication_id"] == med.id), None)
                if not inv or inv["stock"] < item["quantity"]:
                    raise ConflictError(f"Insufficient stock for {med.trade_name}")
                if currency is None:
                    currency = inv["currency"]
                elif inv["currency"] != currency:
                    raise MedError("Mixed currencies in one order are unsupported")
                order_items.append(OrderItem(medication_id=med.id, trade_name=med.trade_name,
                                             quantity=item["quantity"], unit_price=float(inv["price"]),
                                             currency=inv["currency"]))
                total += item["quantity"] * float(inv["price"])
            for oi in order_items:
                pi = next(pi for pi in p.items if pi.inn.lower() == self.catalog.medications[oi.medication_id].inn.lower()
                          and pi.form.lower() == self.catalog.medications[oi.medication_id].form.lower()
                          and pi.strength.lower() == self.catalog.medications[oi.medication_id].strength.lower())
                rows = self.db.execute(
                    "SELECT oi2.quantity FROM order_items oi2 JOIN orders o2 ON o2.id=oi2.order_id "
                    "WHERE o2.prescription_id=? AND o2.status NOT IN ('cancelled','failed') AND oi2.medication_id=?",
                    (prescription_id, oi.medication_id)).fetchall()
                already_count = sum(r["quantity"] for r in rows)
                if already_count + oi.quantity > pi.quantity:
                    raise ConflictError("Total ordered quantity exceeds prescribed quantity")
            order_id = uuid.uuid4().hex
            stamp = now()
            self.db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?)",
                            (order_id, prescription_id, patient_ref, pharmacy_id, "placed", total, currency, stamp, stamp))
            for oi in order_items:
                self.db.execute("INSERT INTO order_items(order_id,medication_id,trade_name,quantity,unit_price,currency) VALUES(?,?,?,?,?,?)",
                                (order_id, oi.medication_id, oi.trade_name, oi.quantity, oi.unit_price, oi.currency))
            self._event(prescription_id, order_id, "order_placed", patient_ref,
                        {"pharmacy_id": pharmacy_id, "items": len(order_items), "total": total})
            return self.get_order(order_id)

    def get_order(self, order_id: str) -> Order | None:
        with self._lock:
            row = self.db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            if not row:
                return None
            item_rows = self.db.execute("SELECT * FROM order_items WHERE order_id=? ORDER BY id", (order_id,)).fetchall()
            items = tuple(OrderItem(medication_id=r["medication_id"], trade_name=r["trade_name"],
                                    quantity=r["quantity"], unit_price=r["unit_price"], currency=r["currency"])
                          for r in item_rows)
            pharmacy = self.catalog.pharmacies.get(row["pharmacy_id"])
            redirect_url = None
            if pharmacy and row["status"] in {"placed", "confirmed", "ready"}:
                redirect_url = pharmacy.order_url_template.replace("{order_id}", row["id"])
            return Order(id=row["id"], prescription_id=row["prescription_id"], patient_ref=row["patient_ref"],
                         pharmacy_id=row["pharmacy_id"], status=row["status"], total=row["total"],
                         currency=row["currency"], items=items, created_at=row["created_at"],
                         updated_at=row["updated_at"], redirect_url=redirect_url)

    def transition_order(self, order_id: str, action: str, actor: str, note: str | None) -> Order:
        allowed = {"confirm": ({"placed"}, "confirmed"),
                   "ready": ({"confirmed"}, "ready"),
                   "picked_up": ({"ready"}, "picked_up"),
                   "cancel": ({"placed", "confirmed"}, "cancelled"),
                   "fail": ({"placed", "confirmed", "ready"}, "failed")}
        if action not in allowed:
            raise MedError("Invalid order action")
        with self._lock, self.db:
            order = self.get_order(order_id)
            if not order:
                raise MedError("Order not found")
            before, after = allowed[action]
            if order.status not in before:
                raise ConflictError(f"Order must be in {sorted(before)}")
            self.db.execute("UPDATE orders SET status=?,updated_at=? WHERE id=?", (after, now(), order_id))
            self._event(order.prescription_id, order_id, f"order_{after}", actor, {"note": note})
            return self.get_order(order_id)

    def list_orders(self, *, patient_ref: str | None = None, pharmacy_id: str | None = None,
                    status: str | None = None) -> list[Order]:
        with self._lock:
            query = "SELECT id FROM orders WHERE 1=1"
            args: list = []
            if patient_ref:
                query += " AND patient_ref=?"; args.append(patient_ref)
            if pharmacy_id:
                query += " AND pharmacy_id=?"; args.append(pharmacy_id)
            if status:
                if status not in ORDER_STATUSES:
                    raise MedError("Invalid status")
                query += " AND status=?"; args.append(status)
            query += " ORDER BY created_at DESC"
            return [self.get_order(r["id"]) for r in self.db.execute(query, args)]

    def staff_queue(self) -> list[dict]:
        with self._lock:
            cases = []
            for row in self.db.execute("SELECT * FROM orders WHERE status IN ('placed','confirmed','ready') ORDER BY created_at"):
                cases.append({"kind": "order", "order_id": row["id"], "status": row["status"],
                              "pharmacy_id": row["pharmacy_id"], "patient_ref": row["patient_ref"],
                              "total": row["total"], "currency": row["currency"], "created_at": row["created_at"]})
            return cases

    def metrics(self) -> dict:
        with self._lock:
            prescriptions = [self.get_prescription(r["id"]) for r in self.db.execute("SELECT id FROM prescriptions")]
            orders = [self.get_order(r["id"]) for r in self.db.execute("SELECT id FROM orders")]
            by_status = {}
            for o in orders:
                by_status[o.status] = by_status.get(o.status, 0) + 1
            completed = by_status.get("picked_up", 0)
            cancelled = by_status.get("cancelled", 0)
            return {"prescriptions_total": len(prescriptions),
                    "orders_total": len(orders),
                    "orders_by_status": by_status,
                    "orders_completed": completed,
                    "orders_cancelled": cancelled,
                    "completion_rate": completed / len(orders) if orders else None,
                    "catalog_version": self.catalog.version,
                    "inventory_version": self.inventory_version}