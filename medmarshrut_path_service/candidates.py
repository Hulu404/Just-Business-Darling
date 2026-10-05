"""Optional local candidate proposer; output is never a clinical plan."""
from __future__ import annotations

from typing import Protocol

from domain import SourceReport


class CandidateProposer(Protocol):
    def propose(self, source_report: SourceReport) -> list[dict]:
        """Return suggestions for review, never approved PlanStep objects."""
        ...


def review_candidates(proposer: CandidateProposer, source_report: SourceReport) -> list[dict]:
    candidates = proposer.propose(source_report)
    if not isinstance(candidates, list) or len(candidates) > 20:
        raise ValueError("Invalid candidate list")
    for candidate in candidates:
        if (not isinstance(candidate, dict) or set(candidate) != {"text", "rationale"}
                or any(not isinstance(candidate[k], str) or not candidate[k].strip() or len(candidate[k]) > 1000
                       for k in ("text", "rationale"))):
            raise ValueError("Invalid candidate")
    return candidates
