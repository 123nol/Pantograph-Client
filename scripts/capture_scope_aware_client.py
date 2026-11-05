#!/usr/bin/env python3
"""Run the pinned scope harness with the client's required serialization options.

The companion harness also records default-option exchanges. Keep those raw
captures separately; this capture demonstrates the installed client's schema.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from pantograph_async import compatibility
from pantograph_async.protocol import (
    REQUIRED_OPTIONS,
    SUPPORTED_COMMANDS,
    decode_response,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companion", type=Path, required=True)
    parser.add_argument("--mathlib", type=Path, required=True)
    parser.add_argument("--mathlib-reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    companion = args.companion.resolve()
    compatibility.verify_companion_sources(companion)
    if args.output.exists():
        raise FileExistsError(args.output)
    spec = importlib.util.spec_from_file_location(
        "scope_harness", companion / "scripts/test_scope_aware_validation.py"
    )
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)

    class ClientSession(harness.Session):
        def __init__(self, entries, env, imports):
            super().__init__(entries, env, imports)
            self.call("options.set", dict(REQUIRED_OPTIONS))
            effective = self.call("options.print", {})
            decode_response("options.print", effective)

    # Configure the same native sessions before the harness executes any goals.
    harness.Session = ClientSession
    verification = harness.verify_mathlib_sources(args.mathlib, args.mathlib_reference)
    env = harness.environment(args.mathlib.resolve())
    core = harness.core_gate(env)
    mathlib, diagnostic, ordinary = harness.mathlib_gate(args.mathlib, env)
    for entry in [*core, *mathlib]:
        if entry["command"] in SUPPORTED_COMMANDS:
            decode_response(entry["command"], entry["response"])
    result = {
        "companion_commit": compatibility.companion_base()["source_commit"],
        "repl_sha256": hashlib.sha256(
            (companion / ".lake/build/bin/repl").read_bytes()
        ).hexdigest(),
        "required_options": dict(REQUIRED_OPTIONS),
        "mathlib_source_verification": verification,
        "core": core,
        "mathlib": mathlib,
        "diagnostic": diagnostic,
        "ordinary_lean": ordinary,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"PASS: {len(core)} core and {len(mathlib)} Mathlib client-option exchanges")


if __name__ == "__main__":
    main()
