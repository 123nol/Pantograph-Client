"""Versioned contract, compatibility manifest, and companion patch resources.

Resources are read through the installed package, never through a checkout
path, so a wheel carries everything a consumer needs to pin its REPL build.
"""

from __future__ import annotations

import hashlib
from importlib import resources
import json
from pathlib import Path
from typing import Any

from .protocol import (
    COMMAND_ERROR_CATEGORIES,
    PROTOCOL_DESCRIPTION,
    REQUIRED_OPTIONS,
    PantographConfigurationError,
)

CONTRACT = "contract.json"
COMPATIBILITY = "compatibility.json"
COMPANION_PATCH = "repository_client_contract.patch"


def _resource(name: str):
    return resources.files(__package__).joinpath("resources", name)


def contract() -> dict[str, Any]:
    return json.loads(_resource(CONTRACT).read_text(encoding="utf-8"))


def manifest() -> dict[str, Any]:
    return json.loads(_resource(COMPATIBILITY).read_text(encoding="utf-8"))


def companion_patch() -> bytes:
    """Return the exact patch, after checking it against its recorded digest."""
    patch = _resource(COMPANION_PATCH).read_bytes()
    if hashlib.sha256(patch).hexdigest() != manifest()["companion"]["patch_sha256"]:
        raise PantographConfigurationError(
            "Companion patch does not match its recorded digest."
        )
    return patch


def companion_base() -> dict[str, str]:
    """Source pins needed to reproduce the validated companion executable."""
    data = manifest()
    return {
        "contract_revision": data["contract_revision"],
        "source_url": data["companion"]["source_url"],
        "base_commit": data["companion"]["base_commit"],
        "patch_sha256": data["companion"]["patch_sha256"],
        "toolchain": data["tested_inputs"]["lean_toolchain"],
        "mathlib_expected_pin": data["tested_inputs"]["mathlib_commit"],
    }


def companion_files() -> frozenset[str]:
    """Paths, relative to the Pantograph checkout, that the patch produces."""
    return frozenset(manifest()["companion"]["patched_sources_sha256"])


def verify_companion_sources(root: str | Path) -> None:
    """Require a checkout whose patched files match the validated companion."""
    root = Path(root)
    data = manifest()
    mismatched = []
    for name, digest in sorted(data["companion"]["patched_sources_sha256"].items()):
        path = root / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            mismatched.append(name)
    if mismatched:
        raise PantographConfigurationError(
            f"Companion sources differ from the validated build: {mismatched}"
        )
    toolchain = (root / "lean-toolchain").read_text().strip()
    if toolchain != data["tested_inputs"]["lean_toolchain"]:
        raise PantographConfigurationError(
            f"Companion checkout declares {toolchain!r}, not the validated toolchain."
        )


def verify_contract() -> None:
    """The shipped contract, manifest, and codec must describe the same server."""
    shipped = contract()
    codec = {
        "descriptor": dict(PROTOCOL_DESCRIPTION),
        "required_options": dict(REQUIRED_OPTIONS),
        "commands": {
            name: sorted(codes) for name, codes in COMMAND_ERROR_CATEGORIES.items()
        },
    }
    actual = {
        "descriptor": shipped["descriptor"],
        "required_options": shipped["required_options"],
        "commands": {
            name: sorted(codes) for name, codes in shipped["commands"].items()
        },
    }
    if actual != codec:
        raise PantographConfigurationError(
            "Shipped contract resources disagree with the protocol codec."
        )
    data = manifest()
    if (
        data["descriptor"] != shipped["descriptor"]
        or data["contract_revision"] != shipped["contract_revision"]
    ):
        raise PantographConfigurationError(
            "Compatibility manifest was recorded for a different contract."
        )
