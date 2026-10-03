"""Versioned clinic network: clinics, capabilities, partnerships."""
from __future__ import annotations

import json
from pathlib import Path

from domain import STUDY_TYPES


class NetworkError(ValueError):
    pass


class ClinicNetwork:
    def __init__(self, path: Path):
        try:
            config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise NetworkError(f"Invalid network file: {exc}") from None
        if not isinstance(config, dict) or set(config) != {"version", "clinics", "capabilities", "partnerships"}:
            raise NetworkError("Network file requires version, clinics, capabilities, partnerships")
        if not isinstance(config["version"], str) or not config["version"].strip():
            raise NetworkError("Network version is required")
        self.version = config["version"]
        self.clinics: dict[str, dict] = {}
        for item in config["clinics"]:
            if not isinstance(item, dict) or set(item) != {"id", "name", "network", "active"}:
                raise NetworkError("Invalid clinic entry")
            if (not isinstance(item["id"], str) or not item["id"].strip()
                    or not isinstance(item["name"], str) or not item["name"].strip()
                    or not isinstance(item["network"], str) or not item["network"].strip()
                    or type(item["active"]) is not bool):
                raise NetworkError("Invalid clinic values")
            if item["id"] in self.clinics:
                raise NetworkError("Duplicate clinic id")
            self.clinics[item["id"]] = dict(item)
        self.capabilities: list[dict] = []
        seen_caps = set()
        for item in config["capabilities"]:
            if not isinstance(item, dict) or set(item) != {"clinic_id", "study_type", "anatomy",
                                                            "protocol_name", "finding_code", "approved"}:
                raise NetworkError("Invalid capability entry")
            if item["clinic_id"] not in self.clinics or item["study_type"] not in STUDY_TYPES:
                raise NetworkError("Capability references unknown clinic or study type")
            for key in ("anatomy", "protocol_name", "finding_code"):
                if not isinstance(item[key], str) or not item[key].strip() or len(item[key]) > 128:
                    raise NetworkError(f"Invalid capability {key}")
            if type(item["approved"]) is not bool:
                raise NetworkError("Capability approval must be boolean")
            key = (item["clinic_id"], item["study_type"], item["anatomy"], item["protocol_name"], item["finding_code"])
            if key in seen_caps:
                raise NetworkError("Duplicate capability")
            seen_caps.add(key)
            self.capabilities.append(dict(item))
        self.partnerships: list[dict] = []
        seen_partners = set()
        for item in config["partnerships"]:
            if not isinstance(item, dict) or set(item) != {"clinic_a", "clinic_b", "direction", "active", "since"}:
                raise NetworkError("Invalid partnership entry")
            if (item["clinic_a"] not in self.clinics or item["clinic_b"] not in self.clinics
                    or item["clinic_a"] == item["clinic_b"]
                    or item["direction"] not in {"outgoing", "incoming", "mutual"}
                    or type(item["active"]) is not bool
                    or not isinstance(item["since"], str) or not item["since"].strip()):
                raise NetworkError("Invalid partnership values")
            pair = tuple(sorted((item["clinic_a"], item["clinic_b"])))
            if pair in seen_partners:
                raise NetworkError("Duplicate partnership")
            seen_partners.add(pair)
            self.partnerships.append(dict(item))

    def clinic(self, clinic_id: str) -> dict | None:
        return self.clinics.get(clinic_id)

    def capabilities_for(self, clinic_id: str) -> list[dict]:
        return [c for c in self.capabilities if c["clinic_id"] == clinic_id]

    def partners_of(self, clinic_id: str) -> list[str]:
        out = []
        for p in self.partnerships:
            if not p["active"]:
                continue
            if p["clinic_a"] == clinic_id and p["direction"] in {"outgoing", "mutual"}:
                out.append(p["clinic_b"])
            elif p["clinic_b"] == clinic_id and p["direction"] in {"incoming", "mutual"}:
                out.append(p["clinic_a"])
        return sorted(set(out))