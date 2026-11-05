"""Strict representation-aware validation metadata and terminal integrity failures."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest

from pantograph_async import (
    PantographClient,
    PantographProtocolError,
    SessionPhase,
    TRANSITION_VALIDATION_VERSION,
    TRANSITION_VALIDATION_SCOPE,
)
from pantograph_async.protocol import decode_response
from tests.support import run, records, assert_reaped

FIXTURES = Path(__file__).parent / "fixtures"
CURRENT = FIXTURES / "compiler_aware_validation"
SHARED = json.loads((CURRENT / "fixtures.json").read_text())
SUCCESS = json.loads((FIXTURES / "future_contract.json").read_text())["successes"][
    "valid_truth"
]


def test_shared_validation_contract_accepts_checked_scope():
    wire = deepcopy(SUCCESS)
    wire["validation"] = SHARED["validation"]
    result = decode_response("goal.tactic", wire)
    assert result.validation.version == TRANSITION_VALIDATION_VERSION == 3
    assert result.validation.scope == TRANSITION_VALIDATION_SCOPE
    assert result.validation.checked and not result.validation.is_rejection


@pytest.mark.parametrize(
    "command", ["goal.start", "goal.tactic", "goal.inspect", "goal.certify"]
)
def test_shared_integrity_error_remains_protocol_failure(command):
    error = decode_response(command, SHARED["integrityError"]).as_exception()
    assert type(error) is PantographProtocolError
    assert error.command == command
    assert error.payload == SHARED["integrityError"]
    assert "owner=" in str(error) and "path=" in str(error)


def test_startup_rejects_old_validation_before_options_or_allocations(
    setup, monkeypatch
):
    env, report = setup
    monkeypatch.setenv("PANTOGRAPH_FAKE_SCENARIO", "old_validation_descriptor")

    async def body():
        with pytest.raises(
            PantographProtocolError, match="transitionValidationVersion"
        ):
            await PantographClient.create(env)

    run(body)
    assert [row["command"] for row in records(report) if row["kind"] == "request"] == [
        "protocol.describe"
    ]
    assert_reaped(report)


@pytest.mark.parametrize(
    "folder",
    [
        "snapshot_companion",
        "transactional_snapshot_companion",
        "scope_aware_snapshot_companion",
    ],
)
def test_historical_success_cannot_claim_current_validation(folder):
    historical = json.loads((FIXTURES / folder / "capture.json").read_text())
    rejected = 0
    for entry in historical["interactions"]:
        if entry["command"] == "protocol.describe" or "validation" in entry["response"]:
            with pytest.raises(PantographProtocolError):
                decode_response(entry["command"], entry["response"])
            rejected += 1
    assert rejected > 1


def test_validation_failure_prevents_a_queued_request_from_writing(setup):
    env, report = setup

    async def body():
        async with await PantographClient.create(env) as client:
            async with client.state_scope() as scope:
                root = await scope.start_goal("True")
                failed = asyncio.create_task(
                    scope.apply_tactic(root, "validation_error")
                )
                waiting = asyncio.create_task(client.stat())
                first, second = await asyncio.gather(
                    failed, waiting, return_exceptions=True
                )
                assert type(first) is PantographProtocolError
                assert second is first
                assert client.phase is SessionPhase.CLOSED
                assert not client._allocated_ids and not scope._issued

    run(body)
    assert not any(row.get("command") == "stat" for row in records(report))
    assert_reaped(report)


CAPTURE = json.loads((CURRENT / "capture.json").read_text())


CLIENT_CAPTURE = json.loads((CURRENT / "client_capture.json").read_text())


@pytest.mark.parametrize("entry", [*CLIENT_CAPTURE["core"], *CLIENT_CAPTURE["mathlib"]])
def test_captured_compiler_aware_exchanges_decode_strictly(entry):
    from pantograph_async.protocol import SUPPORTED_COMMANDS, decode_json_response

    assert decode_json_response(entry["response_line"]) == entry["response"]
    if entry["command"] in SUPPORTED_COMMANDS:
        result = decode_response(entry["command"], entry["response"])
        if entry["response"].get("error") == "validation":
            assert type(result.as_exception()) is PantographProtocolError
        if "validation" in entry["response"]:
            assert result.validation.version == TRANSITION_VALIDATION_VERSION
            assert result.validation.checked


def test_captured_diagnostic_retains_inert_residue_and_certifies_root():
    diagnostic = CAPTURE["diagnostic"]
    assert diagnostic["validator"] == "accepted"
    assert diagnostic["rootCertificate"]["status"] == "certified"
    assert diagnostic["auxiliaryAudit"]
    assert any(
        not record["rootReachable"] and record["missingInOwner"]
        for record in diagnostic["assignments"]
    )


def test_compiler_aware_shared_artifacts_match_pinned_companion():
    import hashlib
    from pantograph_async import compatibility

    root = CURRENT
    provenance = json.loads((root / "provenance.json").read_text())
    assert (
        provenance["companion_commit"]
        == compatibility.manifest()["companion"]["source_commit"]
    )
    assert (
        provenance["repl_sha256"]
        == compatibility.manifest()["companion"]["reference_repl_sha256"]
    )
    assert provenance["core_exchanges"] == len(CAPTURE["core"]) == 44
    assert provenance["mathlib_exchanges"] == len(CAPTURE["mathlib"]) == 40
    assert CLIENT_CAPTURE["companion_commit"] == provenance["companion_commit"]
    assert CLIENT_CAPTURE["repl_sha256"] == provenance["repl_sha256"]
    assert CLIENT_CAPTURE["required_options"] == dict(compatibility.REQUIRED_OPTIONS)
    verification = provenance["mathlib_source_verification"]
    assert (
        verification["reference_commit"]
        == compatibility.manifest()["tested_inputs"]["mathlib_commit"]
    )
    assert (
        not verification["missing_or_different"]
        and not verification["local_extra_lean_files"]
    )
    for name, digest in provenance["files_sha256"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize(
    "wire",
    [
        entry["response"]
        for entry in [*CAPTURE["core"], *CAPTURE["mathlib"]]
        if "validation" in entry["response"]
    ],
)
def test_default_option_capture_still_carries_strict_validation(wire):
    from pantograph_async.protocol import decode_transition_validation

    checked = decode_transition_validation(
        wire["validation"], has_sorry=wire["hasSorry"], has_unsafe=wire["hasUnsafe"]
    )
    assert checked.version == TRANSITION_VALIDATION_VERSION
    assert checked.scope == TRANSITION_VALIDATION_SCOPE
    assert checked.checked


def _compiler_producing(entries):
    return [
        entry
        for entry in entries
        if entry["command"] == "goal.tactic"
        and entry["request"].get("tactic")
        in {"unfold Nat.pow", "rw [Nat.pow]", "simp only [Nat.pow]", "cases n <;> simp [Nat.pow]"}
    ]


def test_compiler_producing_tactics_are_checked_transitions():
    # These tactics compile an on-demand match splitter. Version 2 ended the session.
    from pantograph_async.protocol import decode_transition_validation

    raw = _compiler_producing([*CAPTURE["core"], *CAPTURE["mathlib"]])
    configured = _compiler_producing([*CLIENT_CAPTURE["core"], *CLIENT_CAPTURE["mathlib"]])
    assert len(raw) >= 5 and len(configured) == len(raw)
    for entry in raw:
        wire = entry["response"]
        checked = decode_transition_validation(
            wire["validation"], has_sorry=wire["hasSorry"], has_unsafe=wire["hasUnsafe"]
        )
        assert checked.version == TRANSITION_VALIDATION_VERSION and checked.checked
        assert not wire["hasSorry"] and not wire["hasUnsafe"]
    for entry in configured:
        # The client's required options give the complete typed result.
        result = decode_response("goal.tactic", entry["response"])
        assert result.validation.version == TRANSITION_VALIDATION_VERSION
        assert result.validation.scope == TRANSITION_VALIDATION_SCOPE
        assert not result.validation.is_rejection


def test_compiler_producing_proofs_certify_without_compiler_dependencies():
    receipts = [
        entry["response"]["receipt"]
        for entry in [*CAPTURE["core"], *CAPTURE["mathlib"]]
        if entry["command"] == "goal.certify"
        and any("splitter" in name for name in entry["response"]["receipt"]["auxiliary"])
    ]
    assert len(receipts) >= 3
    for receipt in receipts:
        decode_response("goal.certify", {"version": 1, "status": "certified", "receipt": receipt})
        assert not any("_cstage" in name for name in receipt["auxiliary"])


def test_old_compiler_failure_is_a_terminal_protocol_error():
    # The exact integrity failure version 2 reported for `unfold Nat.pow`.
    wire = {
        "error": "validation",
        "desc": "execution owner=declaration _private.0.Nat.pow.match_1.splitter._rarg._cstage2 "
        "path=environment audit/declaration-type/binder-type: Missing proof dependency _obj",
    }
    error = decode_response("goal.tactic", wire).as_exception()
    assert type(error) is PantographProtocolError
    assert error.payload == wire
