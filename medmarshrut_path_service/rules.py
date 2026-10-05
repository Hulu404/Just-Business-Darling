"""Exact, versioned clinic rules. No confidence-based routing."""
from __future__ import annotations

import json
from pathlib import Path

STUDY_TYPES = {"ct", "mr", "mammography", "xray"}
STEP_KINDS = {"appointment", "test", "follow_up", "manual_review", "care_coordination"}


class Ruleset:
    def __init__(self, path: Path):
        config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(config, dict) or set(config) != {"version", "supported_protocols", "rules"}:
            raise ValueError("Invalid ruleset structure")
        if not isinstance(config["version"], str) or not config["version"].strip():
            raise ValueError("Ruleset version is required")
        if not isinstance(config["supported_protocols"], list) or not isinstance(config["rules"], list):
            raise ValueError("Invalid ruleset lists")
        scopes = set()
        for scope in config["supported_protocols"]:
            if not isinstance(scope, dict) or set(scope) != {"study_type", "anatomy", "protocol_name"}:
                raise ValueError("Invalid supported protocol")
            if scope["study_type"] not in STUDY_TYPES or any(not isinstance(scope[k], str) or not scope[k].strip() for k in ("anatomy", "protocol_name")):
                raise ValueError("Invalid supported protocol values")
            key = (scope["study_type"], scope["anatomy"], scope["protocol_name"])
            if key in scopes:
                raise ValueError("Duplicate supported protocol")
            scopes.add(key)
        rules = {}
        for rule in config["rules"]:
            if not isinstance(rule, dict) or set(rule) != {"study_type", "anatomy", "protocol_name", "finding_code", "approved", "steps"}:
                raise ValueError("Invalid rule")
            scope = (rule["study_type"], rule["anatomy"], rule["protocol_name"])
            if scope not in scopes or not isinstance(rule["finding_code"], str) or not rule["finding_code"].strip():
                raise ValueError("Rule has unsupported scope or finding code")
            if type(rule["approved"]) is not bool or not isinstance(rule["steps"], list):
                raise ValueError("Invalid approval or steps")
            if rule["approved"] and not rule["steps"]:
                raise ValueError("Approved rule needs steps")
            for step in rule["steps"]:
                if (not isinstance(step, dict) or set(step) != {"kind", "description"}
                        or step["kind"] not in STEP_KINDS or not isinstance(step["description"], str)
                        or not step["description"].strip() or len(step["description"]) > 500):
                    raise ValueError("Invalid rule step")
            key = (*scope, rule["finding_code"])
            if key in rules:
                raise ValueError("Duplicate rule")
            rules[key] = rule
        self.version = config["version"]
        self.scopes = scopes
        self.rules = rules
        self.codes = {key[3] for key in rules}

    def plan(self, report: dict) -> tuple[list[dict], str | None]:
        if not report.get("patient_ref"):
            return [], "missing_patient_ref"
        scope = (report["study_type"], report["anatomy"], report["protocol_name"])
        if scope not in self.scopes:
            return [], "unsupported_protocol"
        key = (*scope, report["finding_code"])
        rule = self.rules.get(key)
        if rule is None:
            return [], "unknown_finding_code" if report["finding_code"] not in self.codes else "no_approved_rule"
        if not rule["approved"]:
            return [], "rule_not_approved"
        return list(rule["steps"]), None
