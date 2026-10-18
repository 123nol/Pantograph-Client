"""Explicit environment and launch validation; nothing is spawned on failure."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from pantograph_async import PantographClient, PantographConfigurationError, PantographEnv
from pantograph_async.launch import build_launch_spec

from tests.support import FAKE, assert_reaped, records, run


def test_explicit_paths_are_required():
    with pytest.raises(TypeError):
        PantographEnv()
    with pytest.raises(PantographConfigurationError):
        PantographEnv(source_root=None, pantograph_repl=None).verify()


def test_environment_uses_owned_launch_validation(setup):
    env, _report = setup
    env.verify()
    assert "stdbuf -oL" in env.describe()
    for changed in (
        replace(env, source_root=Path("/nonexistent")),
        replace(env, pantograph_repl=Path("/nonexistent/repl")),
        replace(env, options={"noRepeat": True}),
    ):
        with pytest.raises(PantographConfigurationError):
            changed.verify()


@pytest.mark.parametrize(
    "change",
    [
        {"source_root": None},
        {"pantograph_repl": None},
        {"imports": ()},
        {"imports": "Init"},
        {"imports": ("--flag",)},
        {"imports": ("Init\nstat",)},
        {"options": {"noRepeat": True}},
        {"options": {"unknown": True}},
        {"timeout": True},
        {"timeout": float("nan")},
        {"server_start_timeout_s": 0},
        {"worker_shutdown_timeout_s": -1},
        {"response_line_limit": True},
        {"stderr_tail_limit": 0},
    ],
)
def test_invalid_launch_settings_fail_without_spawning(setup, change):
    env, report = setup
    with pytest.raises(PantographConfigurationError):
        build_launch_spec(replace(env, **change))
    assert records(report) == []


@pytest.mark.parametrize(
    "missing",
    [
        "source_toolchain",
        "repl_toolchain",
        "source_lakefile",
        "repl_lakefile",
        "executable",
        "lake",
        "stdbuf",
    ],
)
def test_missing_launch_dependencies_are_not_silently_accepted(
    setup, monkeypatch, missing
):
    env, report = setup
    if missing == "source_toolchain":
        (env.source_root / "lean-toolchain").unlink()
    elif missing == "repl_toolchain":
        (env.pantograph_repl.parents[3] / "lean-toolchain").unlink()
    elif missing == "source_lakefile":
        (env.source_root / "lakefile.lean").unlink()
    elif missing == "repl_lakefile":
        (env.pantograph_repl.parents[3] / "lakefile.lean").unlink()
    elif missing == "executable":
        env.pantograph_repl.chmod(0o644)
    else:
        original = shutil.which
        monkeypatch.setattr(
            "pantograph_async.launch.shutil.which",
            lambda name: None if name == missing else original(name),
        )
    with pytest.raises(PantographConfigurationError):
        build_launch_spec(env)
    assert records(report) == []


def test_toolchain_mismatch_is_rejected(setup):
    env, _report = setup
    (env.pantograph_repl.parents[3] / "lean-toolchain").write_text(
        "leanprover/lean4:v4.29.1\n"
    )
    with pytest.raises(PantographConfigurationError, match="toolchain mismatch"):
        build_launch_spec(env)


def test_external_executable_requires_matching_explicit_manifest(setup, tmp_path):
    env, _report = setup
    external = tmp_path / "external-repl"
    shutil.copyfile(env.pantograph_repl, external)
    external.chmod(0o755)
    with pytest.raises(PantographConfigurationError, match="build_manifest"):
        build_launch_spec(replace(env, pantograph_repl=external))
    manifest = tmp_path / "manifest.json"
    value = {
        "toolchain": "leanprover/lean4:v4.10.0-rc1",
        "repl_sha256": hashlib.sha256(external.read_bytes()).hexdigest(),
    }
    manifest.write_text(json.dumps(value))
    assert (
        build_launch_spec(
            replace(env, pantograph_repl=external, build_manifest=manifest)
        ).repl
        == external
    )
    value["repl_sha256"] = "wrong"
    manifest.write_text(json.dumps(value))
    with pytest.raises(PantographConfigurationError, match="hash mismatch"):
        build_launch_spec(
            replace(env, pantograph_repl=external, build_manifest=manifest)
        )


def test_non_gnu_stdbuf_is_rejected_before_repl_spawn(setup):
    env, report = setup
    launcher = report.parent / "tools" / "stdbuf"
    shutil.copyfile(FAKE, launcher)
    launcher.chmod(0o755)

    async def body():
        with pytest.raises(PantographConfigurationError, match="not GNU"):
            await PantographClient.create(env)

    run(body)
    assert_reaped(report)
    assert not any(row.get("executable") == "repl" for row in records(report))
