"""CLI for a single binary image finding task; no automatic clinical release."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

from dataset_manifest import partition, read_manifest, split_patients, validate_split
from evaluation import evaluation_report
from model import TASKS
from preprocessing import PREPROCESSING_VERSION, dicom_tensor


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def task_config(path: Path) -> dict:
    c = json.loads(path.read_text(encoding="utf-8"))
    required = {"model_version", "task", "modality", "anatomy", "protocol_name", "diagnostic_task",
                "label_code", "label_description", "input_size", "threshold", "epochs", "batch_size", "learning_rate", "seed", "preprocessing_version", "limitations"}
    if not isinstance(c, dict) or set(c) != required:
        raise ValueError("Task configuration fields differ from schema")
    if c["task"] not in TASKS or c["modality"] not in TASKS[c["task"]].modalities:
        raise ValueError("Unsupported task/modality")
    for key in ("model_version", "anatomy", "protocol_name", "diagnostic_task", "label_code", "label_description"):
        if not isinstance(c[key], str) or not c[key].strip():
            raise ValueError(f"Invalid {key}")
    if c["preprocessing_version"] != PREPROCESSING_VERSION:
        raise ValueError("Training and inference preprocessing differ")
    if not isinstance(c["input_size"], list) or len(c["input_size"]) != 2 or any(type(v) is not int or not 16 <= v <= 4096 for v in c["input_size"]):
        raise ValueError("Invalid input size")
    if not isinstance(c["threshold"], (int, float)) or not 0 < c["threshold"] < 1:
        raise ValueError("Invalid threshold")
    if any(type(c[k]) is not int or c[k] < 1 for k in ("epochs", "batch_size")) or type(c["seed"]) is not int:
        raise ValueError("Invalid training integers")
    if not isinstance(c["learning_rate"], (int, float)) or not 0 < c["learning_rate"] <= 1:
        raise ValueError("Invalid learning rate")
    if not isinstance(c["limitations"], list) or not all(isinstance(x, str) for x in c["limitations"]):
        raise ValueError("Invalid limitations")
    if c["modality"] == "MG" and "BI-RADS" in c["label_description"].upper():
        raise ValueError("BI-RADS needs its own validated contract")
    return c


def image_tensor(row: dict, size: list[int]):
    from pydicom import dcmread
    ds = dcmread(row["_image"])
    loc = row["finding_location"]
    if (str(ds.Modality) != row["modality"] or str(ds.StudyInstanceUID) != row["study_id"]
            or str(ds.SeriesInstanceUID) != loc["series_uid"] or str(ds.SOPInstanceUID) != loc["sop_uid"]
            or str(getattr(ds, "BodyPartExamined", "")).strip().upper() != row["anatomy"]
            or str(getattr(ds, "ProtocolName", "")).strip() != row["protocol_name"]):
        raise ValueError("DICOM metadata differs from manifest")
    return dicom_tensor(ds, size)[0]


def _scores(session, rows: list[dict], size: list[int]):
    import numpy as np
    input_name = session.get_inputs()[0].name
    return [float(np.asarray(session.run(None, {input_name: image_tensor(r, size)[None]})[0]).reshape(-1)[0]) for r in rows]


def train(manifest: Path, config_path: Path, split_path: Path, artifact: Path, *, allow_real_data: bool) -> None:
    if not allow_real_data:
        raise ValueError("Explicit --allow-real-data is required after dataset-use authorization")
    import numpy as np
    import torch
    import torch.nn as nn
    import onnxruntime as ort
    c = task_config(config_path)
    rows, digest = read_manifest(manifest, c)
    split = json.loads(split_path.read_text(encoding="utf-8"))
    validate_split(rows, split, digest)
    if artifact.exists():
        raise ValueError("Versioned artifact directory already exists")
    if artifact.name != c["model_version"]:
        raise ValueError("Artifact directory name must equal model_version")
    train_rows, val_rows = partition(rows, split, "train"), partition(rows, split, "validation")
    random.seed(c["seed"])
    np.random.seed(c["seed"])
    torch.manual_seed(c["seed"])
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(c["seed"])
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    device = "cuda" if torch.cuda.is_available() else "cpu"
    class DicomDataset(torch.utils.data.Dataset):
        def __init__(self, items):
            self.items = items
        def __len__(self):
            return len(self.items)
        def __getitem__(self, index):
            row = self.items[index]
            return torch.from_numpy(image_tensor(row, c["input_size"])), torch.tensor([row["label"]], dtype=torch.float32)
    train_loader = torch.utils.data.DataLoader(DicomDataset(train_rows), batch_size=c["batch_size"],
        shuffle=True, num_workers=0, generator=torch.Generator().manual_seed(c["seed"]))
    val_loader = torch.utils.data.DataLoader(DicomDataset(val_rows), batch_size=c["batch_size"], num_workers=0)
    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.layers = nn.Sequential(nn.Conv2d(1, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
                nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
                nn.Conv2d(32, 64, 3, padding=1), nn.ReLU(), nn.AdaptiveAvgPool2d(1),
                nn.Flatten(), nn.Linear(64, 1), nn.Sigmoid())
        def forward(self, x):
            return self.layers(x)
    network = Net().to(device)
    optimizer = torch.optim.Adam(network.parameters(), lr=c["learning_rate"])
    loss_fn = nn.BCELoss()
    best = float("inf")
    best_state = None
    history = []
    for epoch in range(c["epochs"]):
        network.train()
        for images, targets in train_loader:
            images, targets = images.to(device), targets.to(device)
            optimizer.zero_grad()
            loss = loss_fn(network(images), targets)
            loss.backward()
            optimizer.step()
        network.eval()
        with torch.no_grad():
            total_loss = 0.0
            for images, targets in val_loader:
                images, targets = images.to(device), targets.to(device)
                total_loss += float(loss_fn(network(images), targets)) * len(images)
            val_loss = total_loss / len(val_rows)
        history.append({"epoch": epoch + 1, "validation_loss": val_loss})
        if val_loss < best:
            best = val_loss
            best_state = {k: v.detach().cpu().clone() for k, v in network.state_dict().items()}
    network.load_state_dict(best_state)
    network.cpu().eval()
    artifact.mkdir(parents=True)
    torch.save(best_state, artifact / "checkpoint.pt")
    dummy = torch.zeros(1, 1, *c["input_size"])
    torch.onnx.export(network, dummy, str(artifact / "model.onnx"), input_names=["image"], output_names=["probability"], opset_version=17)
    weights = (artifact / "model.onnx").read_bytes()
    model_config = {"model_version": c["model_version"], "preprocessing_version": c["preprocessing_version"],
        "task": c["task"], "modality": c["modality"], "anatomy": c["anatomy"],
        "protocol_name": c["protocol_name"], "diagnostic_task": c["diagnostic_task"],
        "weights_file": "model.onnx", "weights_sha256": hashlib.sha256(weights).hexdigest(),
        "input_size": c["input_size"], "labels": [{"code": c["label_code"], "description": c["label_description"], "threshold": c["threshold"]}],
        "limitations": c["limitations"]}
    write_json(artifact / "model.json", model_config)
    write_json(artifact / "train_config.json", c)
    write_json(artifact / "split.json", split)
    session = ort.InferenceSession(str(artifact / "model.onnx"), providers=["CPUExecutionProvider"])
    reports = {}
    for name in ("validation", "test", "external"):
        subset = partition(rows, split, name)
        reports[name] = evaluation_report(subset, _scores(session, subset, c["input_size"]), c["threshold"])
    write_json(artifact / "metrics.json", {"manifest_sha256": digest, "training_history": history, "partitions": reports})
    write_json(artifact / "model_card.json", {"model_version": c["model_version"], "diagnostic_task": c["diagnostic_task"],
        "intended_use": "Research evaluation; physician review required after manual approval", "unit": "image",
        "data": {"manifest_sha256": digest, "patients_by_partition": {k: len(v) for k, v in split["patients"].items()}},
        "label_definition": c["label_description"], "label_sources": sorted({r["label_source"]["kind"] for r in rows}),
        "annotation_versions": sorted({r["annotation_version"] for r in rows}), "preprocessing_version": PREPROCESSING_VERSION,
        "limitations": c["limitations"], "clinical_validation": "Not established by this pipeline", "training_device": device,
        "environment": {"python": sys.version.split()[0], "torch": torch.__version__, "numpy": np.__version__,
                        "onnxruntime": ort.__version__, "cuda": torch.version.cuda,
                        "cudnn": torch.backends.cudnn.version()}})


def evaluate(manifest: Path, artifact: Path, split_name: str) -> dict:
    import onnxruntime as ort
    c = task_config(artifact / "train_config.json")
    rows, digest = read_manifest(manifest, c)
    split = json.loads((artifact / "split.json").read_text(encoding="utf-8"))
    validate_split(rows, split, digest)
    model = json.loads((artifact / "model.json").read_text(encoding="utf-8"))
    weights = artifact / model["weights_file"]
    if hashlib.sha256(weights.read_bytes()).hexdigest() != model["weights_sha256"]:
        raise ValueError("Weights checksum mismatch")
    if model["preprocessing_version"] != PREPROCESSING_VERSION:
        raise ValueError("Preprocessing version mismatch")
    subset = partition(rows, split, split_name)
    session = ort.InferenceSession(str(weights), providers=["CPUExecutionProvider"])
    return evaluation_report(subset, _scores(session, subset, c["input_size"]), c["threshold"])


def approve(artifact: Path, reviewer: str, decision_record: str) -> None:
    if not reviewer.strip() or not decision_record.strip():
        raise ValueError("Reviewer and decision record are required")
    if (artifact / "approval.json").exists():
        raise ValueError("Artifact already approved; create a new version for changes")
    required_files = ("model.onnx", "model.json", "metrics.json", "model_card.json", "train_config.json", "split.json")
    for filename in required_files:
        if not (artifact / filename).is_file():
            raise ValueError(f"Missing artifact file: {filename}")
    config_path = artifact / "model.json"
    c = json.loads(config_path.read_text(encoding="utf-8"))
    if hashlib.sha256((artifact / "model.onnx").read_bytes()).hexdigest() != c["weights_sha256"]:
        raise ValueError("Weights checksum mismatch")
    write_json(artifact / "approval.json", {"model_version": c["model_version"],
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "files_sha256": {name: hashlib.sha256((artifact / name).read_bytes()).hexdigest() for name in required_files},
        "approved_by": reviewer, "approved_at": datetime.now(timezone.utc).isoformat(),
        "decision_record": decision_record})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--manifest", type=Path, required=True)
    common.add_argument("--config", type=Path, required=True)
    check = sub.add_parser("validate", parents=[common])
    split = sub.add_parser("split", parents=[common])
    split.add_argument("--external-institution", required=True)
    split.add_argument("--output", type=Path, required=True)
    split.add_argument("--seed", type=int, default=42)
    tr = sub.add_parser("train", parents=[common])
    tr.add_argument("--split", type=Path, required=True)
    tr.add_argument("--artifact", type=Path, required=True)
    tr.add_argument("--allow-real-data", action="store_true")
    ev = sub.add_parser("evaluate")
    ev.add_argument("--manifest", type=Path, required=True)
    ev.add_argument("--artifact", type=Path, required=True)
    ev.add_argument("--partition", choices=["validation", "test", "external"], required=True)
    ap = sub.add_parser("approve")
    ap.add_argument("--artifact", type=Path, required=True)
    ap.add_argument("--approved-by", required=True)
    ap.add_argument("--decision-record", required=True)
    args = p.parse_args()
    if args.command in {"validate", "split"}:
        c = task_config(args.config)
        rows, digest = read_manifest(args.manifest, c)
        print(json.dumps({"images": len(rows), "patients": len({r["patient_id"] for r in rows}), "sha256": digest}))
        if args.command == "split":
            parts = split_patients(rows, args.seed, args.external_institution)
            write_json(args.output, {"manifest_sha256": digest, "external_institution": args.external_institution, "seed": args.seed, "patients": parts})
    elif args.command == "train":
        train(args.manifest, args.config, args.split, args.artifact, allow_real_data=args.allow_real_data)
    elif args.command == "evaluate":
        print(json.dumps(evaluate(args.manifest, args.artifact, args.partition), ensure_ascii=False, indent=2))
    else:
        approve(args.artifact, args.approved_by, args.decision_record)


if __name__ == "__main__":
    main()
