"""Binary image-level evaluation. Undefined denominators stay null."""
from __future__ import annotations

import math
from collections import defaultdict


def _ratio(a, b):
    return a / b if b else None


def binary_metrics(labels: list[int], scores: list[float], threshold: float) -> dict:
    if len(labels) != len(scores) or not labels:
        raise ValueError("Scores and labels must have equal nonzero length")
    if any(y not in (0, 1) for y in labels) or any(not math.isfinite(p) or p < 0 or p > 1 for p in scores):
        raise ValueError("Invalid binary labels or probabilities")
    tp = sum(y == 1 and p >= threshold for y, p in zip(labels, scores))
    tn = sum(y == 0 and p < threshold for y, p in zip(labels, scores))
    fp = sum(y == 0 and p >= threshold for y, p in zip(labels, scores))
    fn = sum(y == 1 and p < threshold for y, p in zip(labels, scores))
    bins = []
    ece = 0.0
    for i in range(10):
        idx = [j for j, p in enumerate(scores) if (i / 10 <= p < (i + 1) / 10 or i == 9 and p == 1)]
        if idx:
            confidence = sum(scores[j] for j in idx) / len(idx)
            observed = sum(labels[j] for j in idx) / len(idx)
            ece += len(idx) / len(scores) * abs(confidence - observed)
            bins.append({"range": [i / 10, (i + 1) / 10], "n": len(idx), "mean_confidence": confidence, "observed_rate": observed})
    return {"n": len(labels), "tp": tp, "tn": tn, "fp": fp, "fn": fn,
            "sensitivity": _ratio(tp, tp + fn), "recall": _ratio(tp, tp + fn),
            "specificity": _ratio(tn, tn + fp), "precision": _ratio(tp, tp + fp),
            "brier_score": sum((p-y)**2 for y, p in zip(labels, scores)) / len(labels),
            "ece_10_bins": ece, "calibration_bins": bins}


def evaluation_report(rows: list[dict], scores: list[float], threshold: float) -> dict:
    labels = [r["label"] for r in rows]
    def result(indices):
        return binary_metrics([labels[i] for i in indices], [scores[i] for i in indices], threshold)
    groups = {}
    for field in ("institution_id", "study_type", "annotation_version"):
        buckets = defaultdict(list)
        for i, row in enumerate(rows):
            buckets[row[field]].append(i)
        groups[field] = {key: result(idx) for key, idx in sorted(buckets.items())}
    errors = defaultdict(lambda: {"false_positive": 0, "false_negative": 0})
    for row, p in zip(rows, scores):
        errors[row["study_type"]]
        if row["label"] == 0 and p >= threshold:
            errors[row["study_type"]]["false_positive"] += 1
        if row["label"] == 1 and p < threshold:
            errors[row["study_type"]]["false_negative"] += 1
    return {"unit": "image", "threshold": threshold, "overall": result(range(len(rows))),
            "subgroups": groups, "errors_by_study_type": dict(errors)}
