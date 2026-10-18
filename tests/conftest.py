"""Shared fixtures; opt-in real Lean checks are required, not skipped, when designated."""

import os
import shutil

import pytest

from pantograph_async import PantographEnv

from tests.support import FAKE


def pytest_addoption(parser):
    parser.addoption("--run-pantograph-live", action="store_true", default=False)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "pantograph_live: actual custom Lean executable integration"
    )


@pytest.fixture
def setup(tmp_path, monkeypatch):
    source = tmp_path / "mathlib"
    project = tmp_path / "Pantograph"
    for root in (source, project):
        root.mkdir()
        (root / "lakefile.lean").write_text("import Lake\n")
        (root / "lean-toolchain").write_text("leanprover/lean4:v4.10.0-rc1\n")
    repl = project / ".lake" / "build" / "bin" / "repl"
    repl.parent.mkdir(parents=True)
    shutil.copyfile(FAKE, repl)
    repl.chmod(0o755)
    tools = tmp_path / "tools"
    tools.mkdir()
    lake = tools / "lake"
    shutil.copyfile(FAKE, lake)
    lake.chmod(0o755)
    report = tmp_path / "events.jsonl"
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("PANTOGRAPH_FAKE_REPORT", str(report))
    monkeypatch.setenv(
        "PANTOGRAPH_FAKE_CONTRACT", str(FAKE.with_name("future_contract.json"))
    )
    monkeypatch.setenv("PANTOGRAPH_FAKE_SCENARIO", "normal")
    monkeypatch.setenv("PANTOGRAPH_FAKE_RESOLVER", "normal")
    env = PantographEnv(
        source_root=source,
        pantograph_repl=repl,
        imports=("Init",),
        timeout=1,
        server_start_timeout_s=2,
        worker_shutdown_timeout_s=0.4,
    )
    return env, report
