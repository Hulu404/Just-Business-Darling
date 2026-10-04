"""Image service with a scripted backend. Demo stand only: findings are scripted, pixels are never analysed."""
import json
import os
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "medmarshrut_image_service"))
from model import ModelBackend  # noqa: E402
from service import StudyService, make_handler  # noqa: E402

MODEL_VERSION = "demo-scripted-1"


class DemoScriptedBackend(ModelBackend):
    def __init__(self, index_path: Path):
        self.index_path = index_path
        self.index: dict[str, list[dict]] = {}

    def load_model(self, model_path=None):
        self.index = json.loads(self.index_path.read_text(encoding="utf-8"))

    def check_compatibility(self, study, task):
        return study["modality"] == task.modality, "Modality does not match task"

    def infer_local(self, study, task, archive):
        base = {"kind": "model_inference", "backend": "DemoScriptedBackend", "model_version": MODEL_VERSION,
                "weights_sha256": "none", "preprocessing_version": "none", "modality": study["modality"],
                "anatomy": study["anatomy"], "protocol_name": study["protocol_name"],
                "diagnostic_task": "scripted demo, no image analysis",
                "input_quality": {"instance_count": study["instance_count"]},
                "limitations": ["Демо-сценарий: признак задан заранее, снимок не анализировался"]}
        script = self.index.get(study["study_uid"])
        if script is None:
            return {**base, "findings": [],
                    "refusal_reason": "Demo stand analyses only studies from the demo kit"}
        findings = []
        for item in script:
            for series_uid, series in study["series"].items():
                if study["modality"] == "MG":
                    sop_uid = next((k for k, v in series["projections"].items() if v == item["projection"]), None)
                    place = {"projection": item["projection"]}
                else:
                    order = series["ordered_sop_uids"]
                    sop_uid = order[item["slice_index"] - 1] if item["slice_index"] <= len(order) else None
                    place = {"slice_index": item["slice_index"]}
                if sop_uid:
                    findings.append({"code": item["code"], "description": item["description"], "confidence": 0.0,
                                     "localization": {"series_uid": series_uid, "sop_uid": sop_uid, **place}})
                    break
        return {**base, "findings": findings, "refusal_reason": None}


if __name__ == "__main__":
    service = StudyService(DemoScriptedBackend(Path(os.environ["DEMO_STUDY_INDEX"])),
                           router_url=os.environ.get("ROUTER_URL"), router_secret=os.environ.get("PATH_SHARED_SECRET"))
    server = ThreadingHTTPServer(("127.0.0.1", 8766), make_handler(service, os.environ["REVIEWER_TOKEN"]))
    print("DEMO image service (scripted findings, no image analysis): http://127.0.0.1:8766", flush=True)
    server.serve_forever()
