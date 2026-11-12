"""The shipped companion and native exchanges implement the client contract."""

import hashlib
import json
from pathlib import Path

import pytest

from pantograph_async import compatibility
from pantograph_async.protocol import (
    PROTOCOL_DESCRIPTION,
    REQUIRED_OPTIONS,
    SUPPORTED_COMMANDS,
    PantographResourceError,
    PantographRemoteInternalError,
    ResourceError,
    InternalError,
    decode_json_response,
    decode_response,
)

FIXTURES = Path(__file__).parent / "fixtures"
SHARED = FIXTURES / "recursion_depth_resources"
SNAPSHOTS = FIXTURES / "recursion_depth_snapshot_companion"
CAPTURE = json.loads((SHARED / "capture.json").read_text())
SNAPSHOT_CAPTURE = json.loads((SNAPSHOTS / "capture.json").read_text())


@pytest.mark.parametrize("command", sorted(SUPPORTED_COMMANDS))
@pytest.mark.parametrize("wire", json.loads((SHARED / "fixtures.json").read_text()))
def test_shared_companion_error_fixtures(command, wire):
    result = decode_response(command, wire)
    assert isinstance(result, (ResourceError, InternalError))
    assert result.as_exception().command == command
    assert result.recovery == wire["recovery"]


@pytest.mark.parametrize("entry", CAPTURE["exchanges"])
def test_native_transactional_exchanges(entry):
    wire = decode_json_response(entry["response_line"])
    assert wire == entry["response"]
    if entry["command"] in SUPPORTED_COMMANDS:
        result = decode_response(entry["command"], wire)
        if wire.get("error") == "resource":
            assert type(result.as_exception()) is PantographResourceError
        elif wire.get("error") == "internal":
            assert type(result.as_exception()) is PantographRemoteInternalError


@pytest.mark.parametrize("entry", SNAPSHOT_CAPTURE["interactions"])
def test_native_snapshot_exchanges(entry):
    assert decode_json_response(entry["response_line"]) == entry["response"]
    decode_response(entry["command"], entry["response"])


def test_native_descriptor_options_and_source_identity_agree():
    entries = {entry["label"]: entry for entry in SNAPSHOT_CAPTURE["interactions"]}
    assert entries["descriptor"]["response"] == dict(PROTOCOL_DESCRIPTION)
    options = entries["effective_options"]["response"]
    assert "printJsonPretty" not in options
    assert all(options[key] is value for key, value in REQUIRED_OPTIONS.items())
    provenance = json.loads((SNAPSHOTS / "provenance.json").read_text())
    assert (
        provenance["companion_commit"]
        == compatibility.manifest()["companion"]["source_commit"]
    )
    assert (
        provenance["repl_sha256"]
        == compatibility.manifest()["companion"]["reference_repl_sha256"]
    )
    assert (
        provenance["capture_sha256"]
        == hashlib.sha256((SNAPSHOTS / "capture.json").read_bytes()).hexdigest()
    )
    assert entries["final_stat"]["response"] == {"nGoals": 0}
    assert SNAPSHOT_CAPTURE["subprocess_reaped"]


def test_shared_native_artifacts_match_provenance():
    provenance = json.loads((SHARED / "provenance.json").read_text())
    assert (
        provenance["companion_commit"]
        == compatibility.manifest()["companion"]["source_commit"]
    )
    assert (
        provenance["repl_sha256"]
        == compatibility.manifest()["companion"]["reference_repl_sha256"]
    )
    assert provenance["captured_exchanges"] == len(CAPTURE["exchanges"])
    assert provenance["cumulative_requests"] == 3000
    for name, digest in provenance["files_sha256"].items():
        assert hashlib.sha256((SHARED / name).read_bytes()).hexdigest() == digest
