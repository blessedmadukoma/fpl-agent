"""Read the JSONL files that hold eval cases, runs, manifests and reviews."""

import json
from pathlib import Path


def load_cases(evals_json: Path) -> list[dict]:
    """Read JSONL records, ignoring blank lines."""
    with evals_json.open("r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    cases = []
    for line in lines:
        if not line.strip():
            continue
        case = json.loads(line)
        cases.append(case)
    return cases
