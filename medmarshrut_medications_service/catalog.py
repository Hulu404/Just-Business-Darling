"""Versioned medication catalog and partner pharmacies."""
from __future__ import annotations

import json
from pathlib import Path

from domain import FORM_KINDS, Medication, Pharmacy


class CatalogError(ValueError):
    pass


class Catalog:
    def __init__(self, path: Path):
        try:
            config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise CatalogError(f"Invalid catalog file: {exc}") from None
        if not isinstance(config, dict) or set(config) != {"version", "pharmacies", "medications"}:
            raise CatalogError("Catalog requires version, pharmacies, medications")
        if not isinstance(config["version"], str) or not config["version"].strip():
            raise CatalogError("Catalog version is required")
        self.version = config["version"]
        self.pharmacies: dict[str, Pharmacy] = {}
        for item in config["pharmacies"]:
            required = {"id", "name", "network", "city", "active", "order_url_template"}
            if not isinstance(item, dict) or set(item) != required:
                raise CatalogError("Invalid pharmacy entry")
            for k in ("id", "name", "network", "city", "order_url_template"):
                if not isinstance(item[k], str) or not item[k].strip():
                    raise CatalogError(f"Invalid pharmacy {k}")
            if "{order_id}" not in item["order_url_template"]:
                raise CatalogError("order_url_template must contain {order_id}")
            if not item["order_url_template"].startswith("https://"):
                raise CatalogError("order_url_template must be https://")
            if type(item["active"]) is not bool:
                raise CatalogError("Pharmacy active must be bool")
            if item["id"] in self.pharmacies:
                raise CatalogError("Duplicate pharmacy id")
            self.pharmacies[item["id"]] = Pharmacy(**item)
        self.medications: dict[str, Medication] = {}
        for item in config["medications"]:
            required = {"id", "inn", "trade_name", "form", "strength", "atc_code", "prescription_required", "active"}
            if not isinstance(item, dict) or set(item) != required:
                raise CatalogError("Invalid medication entry")
            if item["form"] not in FORM_KINDS:
                raise CatalogError("Invalid medication form")
            for k in ("id", "inn", "trade_name", "strength"):
                if not isinstance(item[k], str) or not item[k].strip():
                    raise CatalogError(f"Invalid medication {k}")
            if item["atc_code"] is not None and not isinstance(item["atc_code"], str):
                raise CatalogError("Invalid atc_code")
            if type(item["prescription_required"]) is not bool or type(item["active"]) is not bool:
                raise CatalogError("Medication flags must be bool")
            if item["id"] in self.medications:
                raise CatalogError("Duplicate medication id")
            self.medications[item["id"]] = Medication(**item)

    def find_exact(self, inn: str, form: str, strength: str) -> list[Medication]:
        key = (inn.lower().strip(), form.lower().strip(), strength.lower().strip())
        return [m for m in self.medications.values() if m.active and m.analog_key == key]