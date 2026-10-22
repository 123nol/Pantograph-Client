"""The installed distribution is complete, isolated, and usable on its own.

In the packaging job this module runs from the tests unpacked from the sdist,
outside any source tree, against the wheel built from that sdist, with
PANTOGRAPH_CLIENT_REQUIRE_INSTALLED=1.
"""

import hashlib
from importlib import metadata, resources
import os
from pathlib import Path
import subprocess
import sys

import pytest

import pantograph_async
from pantograph_async import (
    MODEL_SEXP_VERSION,
    PROTOCOL_DESCRIPTION,
    PantographClient,
    PantographConfigurationError,
    PantographTacticRejected,
    SessionPhase,
    TacticState,
    cli,
    compatibility,
    diagnostics,
)

from tests.support import assert_reaped, run

FORBIDDEN_RUNTIME = (
    "maths_ai",
    "pantograph",
    "pydantic",
    "torch",
    "torch_geometric",
    "faiss",
    "datasets",
)
REQUIRE_INSTALLED = pytest.mark.skipif(
    not os.environ.get("PANTOGRAPH_CLIENT_REQUIRE_INSTALLED"),
    reason="Installed-distribution check runs in the packaging job.",
)


def test_imports_do_not_load_upstream_or_application_packages():
    code = f"""
import importlib.abc
import sys
FORBIDDEN = {set(FORBIDDEN_RUNTIME)!r}
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in FORBIDDEN:
            raise AssertionError(fullname)
sys.meta_path.insert(0, Guard())
import pantograph_async
from pantograph_async import cli, compatibility, diagnostics, probes
assert not {{name.split('.')[0] for name in sys.modules}} & FORBIDDEN
"""
    subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True, timeout=10
    )


def test_contract_resources_agree_with_the_codec():
    compatibility.verify_contract()
    assert compatibility.contract()["descriptor"]["modelSexpVersion"] == MODEL_SEXP_VERSION
    assert compatibility.manifest()["descriptor"] == dict(PROTOCOL_DESCRIPTION)
    assert PROTOCOL_DESCRIPTION["protocol"] == "maths-ai-pantograph"


def test_companion_patch_matches_its_recorded_digest():
    patch = compatibility.companion_patch()
    base = compatibility.companion_base()
    assert hashlib.sha256(patch).hexdigest() == base["patch_sha256"]
    assert base["toolchain"] == "leanprover/lean4:v4.10.0-rc1"
    assert len(base["base_commit"]) == 40
    assert base["source_url"].endswith("Pantograph.git")


def test_resources_are_package_data_not_checkout_files():
    root = resources.files("pantograph_async") / "resources"
    names = {entry.name for entry in root.iterdir()}
    assert {
        compatibility.CONTRACT,
        compatibility.COMPATIBILITY,
        compatibility.COMPANION_PATCH,
    } <= names
    assert (resources.files("pantograph_async") / "py.typed").is_file()


def test_companion_source_verification(tmp_path):
    manifest = compatibility.manifest()["companion"]
    assert compatibility.companion_files() == set(manifest["patched_sources_sha256"])
    with pytest.raises(PantographConfigurationError, match="differ"):
        compatibility.verify_companion_sources(tmp_path)


@pytest.mark.skipif(
    not os.environ.get("PANTOGRAPH_TEST_COMPANION_SOURCE"),
    reason="Set PANTOGRAPH_TEST_COMPANION_SOURCE to a patched Pantograph checkout.",
)
def test_patched_checkout_matches_the_validated_companion():
    compatibility.verify_companion_sources(os.environ["PANTOGRAPH_TEST_COMPANION_SOURCE"])


def test_report_hashes_cover_every_installed_module():
    hashes = diagnostics.installed_sources()
    package = Path(pantograph_async.__file__).parent
    assert set(hashes) == {path.name for path in package.glob("*.py")}
    assert hashes["client.py"] == hashlib.sha256(
        (package / "client.py").read_bytes()
    ).hexdigest()


def test_cli_refuses_to_overwrite_reports(tmp_path):
    report = tmp_path / "report.json"
    report.write_text("{}")
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "smoke",
                "--source-root",
                str(tmp_path),
                "--pantograph-repl",
                str(tmp_path / "repl"),
                "--report",
                str(report),
            ]
        )
    assert exc.value.code == 2
    assert report.read_text() == "{}"


def test_minimal_consumer_applies_a_tactic_and_closes(setup):
    env, report = setup

    async def body():
        client = await PantographClient.create(env)
        async with client:
            async with client.state_scope() as scope:
                root = await scope.start_goal("∀ (p : Prop), p → p")
                state = await scope.apply_tactic(root, "skip")
                assert isinstance(state, TacticState)
                goal = state.goals[0]
                assert goal.fragment == "tactic"
                assert [local.user_name for local in goal.locals] == ["p", "h"]
                assert goal.target.model_sexp_version == MODEL_SEXP_VERSION
                try:
                    await scope.apply_tactic(state, "tactic_failure")
                except PantographTacticRejected as exc:
                    assert exc.payload.tactic_errors
                else:
                    raise AssertionError("A rejected tactic was accepted.")
            assert (await client.stat()).n_goals == 0
        assert client.phase is SessionPhase.CLOSED

    run(body)
    assert_reaped(report)


@REQUIRE_INSTALLED
def test_imports_resolve_to_the_installed_distribution():
    location = Path(pantograph_async.__file__).resolve()
    assert "site-packages" in location.parts
    assert not (location.parents[1] / "pyproject.toml").exists()
    assert diagnostics.distribution_version() == "0.1.1"


@REQUIRE_INSTALLED
def test_wheel_metadata_declares_no_runtime_dependencies():
    distribution = metadata.distribution(diagnostics.DISTRIBUTION)
    assert not distribution.requires or all(
        "extra ==" in requirement for requirement in distribution.requires
    )
    assert {"LICENSE", "NOTICE"} <= {
        Path(str(entry)).name for entry in distribution.files or ()
    }
    entry_points = {entry.name for entry in distribution.entry_points}
    assert entry_points == {"pantograph-client"}
    assert compatibility.manifest()["client_version"] == distribution.version
