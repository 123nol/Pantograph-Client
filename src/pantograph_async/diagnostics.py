"""CPU-only live verification of the custom execution and model contract.

Every check here is protocol-level. Consumers add their own representation
checks on top; nothing reads files outside the installed package.
"""

from __future__ import annotations

import hashlib
from importlib import metadata, resources
import json
from pathlib import Path
import sys

from . import compatibility
from .client import PantographClient
from .environment import PantographEnv
from .probes import (
    probe_alternatives,
    probe_focus,
    probe_goal_shapes,
    probe_messages,
    probe_model_client,
    probe_ordinary_failures,
    probe_repeated_proofs,
    probe_unsafe,
    require,
    supports_metaprograms,
)
from .protocol import MODEL_SEXP_VERSION, PROTOCOL_DESCRIPTION, PantographProtocolError

DISTRIBUTION = "pantograph-async-client"
# Checks that elaborate run_tac metaprograms and so need Lean's own API.
METAPROGRAM_CHECKS = ("diagnostics-multiline", "positive-unsafe-rejection")


def installed_sources() -> dict[str, str]:
    """Hash the modules that were actually imported, wherever they are installed."""
    package = resources.files(__package__)
    return {
        entry.name: hashlib.sha256(entry.read_bytes()).hexdigest()
        for entry in sorted(package.iterdir(), key=lambda item: item.name)
        if entry.name.endswith(".py")
    }


def distribution_version() -> str | None:
    try:
        return metadata.version(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return None


def distribution_source() -> dict | None:
    """PEP 610 direct-source metadata, when the installer recorded it."""
    try:
        text = metadata.distribution(DISTRIBUTION).read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        return None
    return json.loads(text) if text else None


async def verify_live_client(
    env: PantographEnv, *, proofs: int = 100, require_all: bool = True
) -> dict:
    """Exercise the actual client without a checkpoint, dataset, or GPU.

    Imports are used exactly as configured. Metaprogram checks run only when
    those imports can elaborate ``run_tac``; with ``require_all`` a skipped
    check fails the gate instead of being reported as passed.
    """
    if type(proofs) is not int or proofs < 100:
        raise ValueError("The designated leak check requires at least 100 proofs.")
    compatibility.verify_contract()
    client = await PantographClient.create(env)
    pid = client.pid
    outcomes = []
    skipped = {}
    try:
        baseline = (await client.stat()).n_goals
        await probe_model_client(client)
        outcomes.append("instance-let-valid-and-admission-probes")
        async with client.state_scope() as scope:
            outcomes.extend(await probe_goal_shapes(scope))
            await probe_alternatives(scope)
            outcomes.append("parent-deletion-and-independent-alternatives")
            await probe_focus(scope)
            outcomes.append("focus-and-sibling-resumption")
            await probe_ordinary_failures(scope)
            outcomes.append("failure-recovery")
            if await supports_metaprograms(scope):
                await probe_messages(scope)
                outcomes.append("diagnostics-multiline")
                await probe_unsafe(scope)
                outcomes.append("positive-unsafe-rejection")
            else:
                reason = "imports cannot elaborate run_tac; include Lean or Mathlib"
                skipped = {name: reason for name in METAPROGRAM_CHECKS}
        await probe_repeated_proofs(client, proofs)
        outcomes.append("repeated-scoped-proofs")
        final = (await client.stat()).n_goals
        require(final == baseline, "Live checks leaked states.")
        report = {
            "python": sys.executable,
            "python_version": sys.version,
            "client_version": distribution_version(),
            "client_source": distribution_source(),
            "client_location": str(resources.files(__package__)),
            "python_sources_sha256": installed_sources(),
            "repl": str(env.pantograph_repl),
            "repl_sha256": hashlib.sha256(
                Path(env.pantograph_repl).read_bytes()
            ).hexdigest(),
            "source_root": str(env.source_root),
            "toolchain": client.launch_spec.toolchain,
            "imports": list(client.launch_spec.imports),
            "options": client.effective_options.to_dict(),
            "descriptor": dict(PROTOCOL_DESCRIPTION),
            "compatibility": {
                "model_sexp_version": MODEL_SEXP_VERSION,
                **compatibility.companion_base(),
            },
            "checks": outcomes,
            "skipped_checks": skipped,
            "scoped_proofs": proofs,
            "initial_states": baseline,
            "final_states": final,
            "pid": pid,
            "complete_theorem_certification": False,
        }
    finally:
        await client.aclose()
    # CLOSED is reached only after the transport confirms process reaping and
    # joins its readers; consumers do not inspect the private subprocess.
    report.update(
        phase=client.phase.value,
        stderr_tail=client.stderr_tail,
        subprocess_reaped=client.phase.value == "CLOSED",
    )
    if require_all and skipped:
        raise PantographProtocolError(
            f"Required live checks did not run: {sorted(skipped)}; {skipped[next(iter(skipped))]}."
        )
    return report
