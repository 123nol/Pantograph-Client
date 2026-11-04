"""Strict resource envelopes and transactional ownership across real child pipes."""

import asyncio
import json
from pathlib import Path
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest

from pantograph_async import (
    PantographClient,
    PantographResourceError,
    PantographSessionResourceError,
    PantographRemoteInternalError,
    PantographTransportError,
    PantographError,
    PantographGoalRejected,
    PantographTacticRejected,
    PantographProtocolError,
    PantographStateError,
    PantographRequestTimeout,
)
from pantograph_async.protocol import SUPPORTED_COMMANDS, decode_response
from tests.support import run, assert_reaped, records, wait_event


FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "resource_errors.json").read_text()
)
RESOURCE = FIXTURES["resource"]
INTERNAL = FIXTURES["internal"]


@pytest.mark.parametrize("command", sorted(SUPPORTED_COMMANDS))
@pytest.mark.parametrize("phase", ["execute", "validate", "observe", "serialize"])
@pytest.mark.parametrize("recovery", ["command-rolled-back", "session-unusable"])
def test_resource_codec(command, phase, recovery):
    wire = deepcopy(RESOURCE)
    wire["resource"]["phase"] = phase
    wire["recovery"] = recovery
    result = decode_response(command, wire)
    error = result.as_exception()
    expected = (
        PantographResourceError
        if recovery == "command-rolled-back"
        else PantographSessionResourceError
    )
    assert type(error) is expected
    assert error.command == command
    assert (error.kind, error.phase, error.limit, error.recovery) == (
        "heartbeats",
        phase,
        200000,
        recovery,
    )
    assert isinstance(error, PantographTransportError) == (
        recovery == "session-unusable"
    )
    assert not isinstance(error, (PantographGoalRejected, PantographTacticRejected))
    assert PantographResourceError.__bases__[-1] is PantographError
    for field, value in [
        ("kind", "other"),
        ("phase", "other"),
        ("limit", 1),
        ("recovery", "other"),
        ("resource", None),
    ]:
        with pytest.raises(AttributeError):
            setattr(error, field, value)
    with pytest.raises(FrozenInstanceError):
        error.resource.limit = 1
    wire["resource"]["limit"] = 1
    copy = error.payload
    copy["resource"]["limit"] = 2
    assert error.payload["resource"]["limit"] == 200000


@pytest.mark.parametrize("command", sorted(SUPPORTED_COMMANDS))
def test_internal_codec(command):
    error = decode_response(command, INTERNAL).as_exception()
    assert type(error) is PantographRemoteInternalError
    assert isinstance(error, PantographTransportError)
    assert error.command == command and error.recovery == "session-unusable"


BAD = FIXTURES["malformed"]


@pytest.mark.parametrize("wire", BAD)
def test_invalid_envelopes(wire):
    with pytest.raises(PantographProtocolError):
        decode_response("goal.start", wire)


@pytest.mark.parametrize(
    "command",
    sorted(SUPPORTED_COMMANDS - {"protocol.describe", "options.set", "options.print"}),
)
def test_rollback_preserves_allocations_for_every_operation(
    setup, monkeypatch, command
):
    env, report = setup
    # Configure after startup for runtime commands; the child reads its launch environment.
    monkeypatch.setenv("PANTOGRAPH_FAKE_RESOURCE_COMMAND", command)

    async def body():
        async with await PantographClient.create(env) as client:
            async with client.state_scope() as scope:
                if command == "goal.start":
                    with pytest.raises(PantographResourceError):
                        await scope.start_goal("True")
                    assert not scope._issued and not client._allocated_ids
                root = await scope.start_goal("True")
                before = (
                    scope._allocations,
                    dict(scope._issued),
                    set(scope._live_ids),
                    set(client._allocated_ids),
                )
                operations = {
                    "goal.tactic": lambda: scope.apply_tactic(root, "trivial"),
                    "goal.inspect": lambda: scope.inspect(root, [root.root]),
                    "goal.certify": lambda: scope.certify(root),
                    "goal.delete": lambda: scope.release(root),
                    "stat": client.stat,
                }
                if command != "goal.start":
                    with pytest.raises(PantographResourceError) as caught:
                        await operations[command]()
                    assert caught.value.command == command
                    assert before == (
                        scope._allocations,
                        dict(scope._issued),
                        set(scope._live_ids),
                        set(client._allocated_ids),
                    )
                assert client.is_usable
                done = await scope.apply_tactic(root, "trivial")
                assert (await scope.certify(done)).is_certified
            assert not client._allocated_ids
            assert (await client.stat()).n_goals == 0

    run(body)
    assert_reaped(report)


@pytest.mark.parametrize(
    "command", ["protocol.describe", "options.set", "options.print"]
)
@pytest.mark.parametrize(
    "mode,expected",
    [
        ("rollback", PantographResourceError),
        ("fatal", PantographSessionResourceError),
        ("internal", PantographRemoteInternalError),
    ],
)
def test_startup_errors_never_publish_ready(
    setup, monkeypatch, command, mode, expected
):
    env, report = setup
    monkeypatch.setenv("PANTOGRAPH_FAKE_RESOURCE_COMMAND", command)
    monkeypatch.setenv("PANTOGRAPH_FAKE_RESOURCE_MODE", mode)

    async def body():
        with pytest.raises(expected) as caught:
            await PantographClient.create(env)
        assert caught.value.command == command

    run(body)
    assert_reaped(report)


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("rollback", PantographResourceError),
        ("fatal", PantographSessionResourceError),
        ("internal", PantographRemoteInternalError),
    ],
)
def test_queued_requests_keep_response_identity(setup, monkeypatch, mode, expected):
    env, report = setup
    monkeypatch.setenv("PANTOGRAPH_FAKE_RESOURCE_COMMAND", "stat")
    monkeypatch.setenv("PANTOGRAPH_FAKE_RESOURCE_MODE", mode)
    monkeypatch.setenv("PANTOGRAPH_FAKE_RESOURCE_DELAY", "0.05")
    monkeypatch.setenv("PANTOGRAPH_FAKE_SCENARIO", "split")

    async def body():
        async with await PantographClient.create(env) as client:
            scope = await client.state_scope().__aenter__()
            root = await scope.start_goal("True")
            first = asyncio.create_task(client.stat())
            await wait_event(report, "request", command="stat")
            second = asyncio.create_task(client.stat())
            results = await asyncio.gather(first, second, return_exceptions=True)
            assert type(results[0]) is expected
            if mode == "rollback":
                assert results[1].n_goals == 1 and scope._validate_state(root)
            else:
                assert results[1] is results[0]
                assert (
                    not client.is_usable
                    and not scope._issued
                    and not client._allocated_ids
                )
                with pytest.raises(PantographStateError):
                    await scope.apply_tactic(root, "trivial")
            await scope.aclose()

    run(body)
    assert len([r for r in records(report) if r.get("command") == "stat"]) == (
        2 if mode == "rollback" else 1
    )
    assert_reaped(report)


@pytest.mark.parametrize("original", [False, True])
def test_scope_deletion_rollback_retires_and_preserves_original(
    setup, monkeypatch, original
):
    env, report = setup
    monkeypatch.setenv("PANTOGRAPH_FAKE_RESOURCE_COMMAND", "goal.delete")
    monkeypatch.setenv("PANTOGRAPH_FAKE_RESOURCE_REPEAT", "1")

    async def body():
        async with await PantographClient.create(env) as client:
            failure = ValueError("original operation")
            with pytest.raises(
                ValueError if original else PantographResourceError
            ) as caught:
                async with client.state_scope() as scope:
                    await scope.start_goal("True")
                    if original:
                        raise failure
            if original:
                assert caught.value is failure
                assert (
                    "Scope cleanup also failed: PantographResourceError"
                    in failure.__notes__[0]
                )
            assert (
                not client.is_usable and not client._allocated_ids and not scope._issued
            )
            with pytest.raises(PantographTransportError) as retired:
                await client.stat()
            assert isinstance(retired.value.__cause__, PantographResourceError)

    run(body)
    assert_reaped(report)


@pytest.mark.parametrize("mode", ["text", "malformed", "duplicate"])
def test_bad_response_is_terminal_with_bounded_context(setup, mode):
    env, report = setup

    async def body():
        async with await PantographClient.create(env) as client:
            async with client.state_scope() as scope:
                root = await scope.start_goal("True")
                with pytest.raises(
                    (PantographProtocolError, PantographResourceError)
                ) as caught:
                    await scope.apply_tactic(root, "resource_" + mode)
                # Duplicate delivery can retire the session immediately after decoding.
                await asyncio.sleep(0.02)
                assert not client.is_usable
                if mode == "text":
                    message = str(caught.value)
                    assert "Uncaught IO exception" in message
                    assert "goal.tactic" in message and "session=" in message
                    assert len(message) < 4097

    run(body)
    assert_reaped(report)


@pytest.mark.parametrize("cancel", [False, True])
def test_interrupted_resource_response_remains_terminal(setup, monkeypatch, cancel):
    env, report = setup
    monkeypatch.setenv("PANTOGRAPH_FAKE_RESOURCE_COMMAND", "stat")
    monkeypatch.setenv("PANTOGRAPH_FAKE_RESOURCE_DELAY", "0.2")
    if not cancel:
        env = replace(env, timeout=0.05)

    async def body():
        async with await PantographClient.create(env) as client:
            pending = asyncio.create_task(client.stat())
            await wait_event(report, "request", command="stat")
            if cancel:
                pending.cancel()
            with pytest.raises(
                asyncio.CancelledError if cancel else PantographRequestTimeout
            ):
                await pending
            assert not client.is_usable

    run(body)
    assert_reaped(report)


@pytest.mark.parametrize(
    "command",
    [
        "goal.start",
        "goal.tactic",
        "goal.inspect",
        "goal.certify",
        "goal.delete",
        "stat",
    ],
)
@pytest.mark.parametrize(
    "mode,expected",
    [
        ("fatal", PantographSessionResourceError),
        ("internal", PantographRemoteInternalError),
    ],
)
def test_fatal_errors_on_all_operations_retire_owned_states(
    setup, monkeypatch, command, mode, expected
):
    env, report = setup
    monkeypatch.setenv("PANTOGRAPH_FAKE_RESOURCE_COMMAND", command)
    monkeypatch.setenv("PANTOGRAPH_FAKE_RESOURCE_MODE", mode)

    async def body():
        async with await PantographClient.create(env) as client:
            async with client.state_scope() as scope:
                root = (
                    None if command == "goal.start" else await scope.start_goal("True")
                )
                operations = {
                    "goal.start": lambda: scope.start_goal("True"),
                    "goal.tactic": lambda: scope.apply_tactic(root, "trivial"),
                    "goal.inspect": lambda: scope.inspect(root, [root.root]),
                    "goal.certify": lambda: scope.certify(root),
                    "goal.delete": lambda: scope.release(root),
                    "stat": client.stat,
                }
                with pytest.raises(expected) as caught:
                    await operations[command]()
                assert caught.value.command == command
                assert "session=" in caught.value.__notes__[0]
                assert (
                    not client.is_usable
                    and not client._allocated_ids
                    and not scope._issued
                )
                with pytest.raises(expected) as later:
                    await client.stat()
                assert later.value is caught.value

    run(body)
    assert_reaped(report)


def test_repeated_rollback_does_not_retain_or_consume_states(setup):
    import gc
    import weakref

    env, report = setup

    async def body():
        async with await PantographClient.create(env) as client:
            async with client.state_scope() as scope:
                root = await scope.start_goal("True")
                for _ in range(30):
                    with pytest.raises(PantographResourceError):
                        await scope.apply_tactic(root, "resource_rollback")
                assert scope._allocations == 1 and len(scope._issued) == 1
                assert (await client.stat()).n_goals == 1
                alternative = await scope.apply_tactic(root, "trivial")
                ref = weakref.ref(alternative)
                await scope.release(alternative)
                del alternative
                gc.collect()
                assert ref() is None and len(scope._issued) == 1
            assert (await client.stat()).n_goals == 0

    run(body)
    assert_reaped(report)


def test_wire_error_context_is_bounded():
    wire = deepcopy(RESOURCE)
    wire["desc"] = "x" * 100000
    error = decode_response("goal.start", wire).as_exception()
    assert len(str(error)) == 2048
    assert len(repr(error.payload)) < 4096
    with pytest.raises(PantographProtocolError) as malformed:
        decode_response("goal.start", {"unknown": "x" * 100000})
    assert len(repr(malformed.value.payload)) < 4200
