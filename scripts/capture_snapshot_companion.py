#!/usr/bin/env python3
"""Record raw protocol-version-2 exchanges from a built snapshot companion REPL.

The output directory must not exist. Run from any directory with GNU stdbuf on
PATH; the companion checkout supplies LEAN_PATH through ``lake env``.

    python scripts/capture_snapshot_companion.py \\
        --companion /path/to/Pantograph --output tests/fixtures/snapshot_companion
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

# (label, command, payload); "$name" refers to an earlier response's nextStateId
# or stateId, "@name.i" to the name of its i-th returned goal.
SCRIPT = [
    ("descriptor", "protocol.describe", {}),
    ("options", "options.set", {
        "printJsonPretty": False, "printExprPretty": True, "printExprAST": True,
        "printExprModelAST": True, "noRepeat": False, "automaticMode": True,
    }),
    ("conjunction", "goal.start", {"expr": "True ∧ True"}),
    ("split", "goal.tactic", {"stateId": "$conjunction", "goalId": 0, "tactic": "constructor"}),
    ("right_first", "goal.tactic", {"stateId": "$split", "goalId": 1, "tactic": "trivial"}),
    ("left_first", "goal.tactic", {"stateId": "$split", "goalId": 0, "tactic": "trivial"}),
    ("partial_certificate", "goal.certify", {"stateId": "$right_first"}),
    ("done", "goal.tactic", {"stateId": "$right_first", "goalId": 0, "tactic": "trivial"}),
    ("certificate", "goal.certify", {"stateId": "$done"}),
    ("solved_inspection", "goal.inspect", {"stateId": "$done", "goals": ["@split.0", "@split.1"]}),
    ("witness", "goal.start", {"expr": "∃ n : Nat, n = 0 ∧ n = 1"}),
    ("witness_parts", "goal.tactic", {"stateId": "$witness", "goalId": 0, "tactic": "refine ⟨?w, ?a, ?b⟩"}),
    ("shared_assignment", "goal.tactic", {"stateId": "$witness_parts", "goalId": 1, "tactic": "exact (rfl : 0 = 0)"}),
    ("witness_inspection", "goal.inspect", {
        "stateId": "$shared_assignment",
        "goals": ["@witness_parts.0", "@witness_parts.1", "@witness_parts.2"],
    }),
    ("conflict_certificate", "goal.certify", {"stateId": "$shared_assignment"}),
    ("nested", "goal.start", {"expr": "∀ (p q : Prop), p → q → (p ∧ q) ∧ True"}),
    ("nested_intro", "goal.tactic", {"stateId": "$nested", "goalId": 0, "tactic": "intro p q hp hq\nconstructor"}),
    ("nested_split", "goal.tactic", {"stateId": "$nested_intro", "goalId": 0, "tactic": "constructor"}),
    ("classical", "goal.start", {"expr": "∀ (p : Prop), p ∨ ¬p"}),
    ("classical_done", "goal.tactic", {"stateId": "$classical", "goalId": 0, "tactic": "intro p\nexact Classical.em p"}),
    ("classical_certificate", "goal.certify", {"stateId": "$classical_done", "maxHeartbeats": 100000}),
    ("unknown_obligation", "goal.inspect", {"stateId": "$witness_parts", "goals": ["_uniq.999999"]}),
    ("unknown_state", "goal.certify", {"stateId": 999999}),
    ("final_cleanup", "goal.delete", {"stateIds": "$all"}),
    ("final_stat", "stat", {}),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--companion", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    companion = args.companion.resolve()
    args.output.mkdir(parents=True)
    paths = subprocess.check_output(
        ["lake", "env", "printenv", "LEAN_PATH"], cwd=companion, text=True
    ).strip()
    env = dict(os.environ, LEAN_PATH=os.pathsep.join(
        str((companion / path).resolve()) for path in paths.split(os.pathsep) if path
    ))
    repl = companion / ".lake/build/bin/repl"
    process = subprocess.Popen(
        ["stdbuf", "-oL", str(repl), "Init"], cwd=companion, env=env, text=True,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, encoding="utf-8",
    )
    ready = process.stdout.readline().rstrip("\n")
    assert ready == "ready.", ready
    responses: dict[str, dict] = {}
    allocated: set[int] = set()

    def resolve(value):
        if isinstance(value, str) and value == "$all":
            return sorted(allocated)
        if isinstance(value, str) and value.startswith("$"):
            response = responses[value[1:]]
            return response.get("nextStateId", response.get("stateId"))
        if isinstance(value, str) and value.startswith("@"):
            label, index = value[1:].rsplit(".", 1)
            return responses[label]["goals"][int(index)]["name"]
        if isinstance(value, list):
            return [resolve(item) for item in value]
        return value

    interactions = []
    for label, command, payload in SCRIPT:
        request = {key: resolve(value) for key, value in payload.items()}
        line = command + " " + json.dumps(request, ensure_ascii=False, separators=(",", ":"))
        process.stdin.write(line + "\n")
        process.stdin.flush()
        response_line = process.stdout.readline().rstrip("\n")
        response = json.loads(response_line)
        responses[label] = response
        for key in ("stateId", "nextStateId"):
            if key in response:
                allocated.add(response[key])
        if command == "goal.delete":
            allocated.difference_update(request["stateIds"])
        interactions.append({
            "label": label, "command": command, "request": request,
            "request_line": line, "response_line": response_line, "response": response,
        })
    process.stdin.close()
    reaped = process.wait(timeout=30) is not None
    capture = {
        "kind": "snapshot-companion-live-capture",
        "readiness_line": ready,
        "imports": ["Init"],
        "interactions": interactions,
        "subprocess_reaped": reaped,
    }
    (args.output / "capture.json").write_text(
        json.dumps(capture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=companion, text=True).strip()
    provenance = {
        "kind": "snapshot-companion-capture-provenance",
        "companion_commit": head,
        "repl_sha256": hashlib.sha256(repl.read_bytes()).hexdigest(),
        "toolchain": (companion / "lean-toolchain").read_text().strip(),
        "capture_sha256": hashlib.sha256((args.output / "capture.json").read_bytes()).hexdigest(),
    }
    (args.output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")


if __name__ == "__main__":
    main()
