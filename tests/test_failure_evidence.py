"""Request events and failure snapshots: bounded, immutable, and lifecycle-safe."""

import dataclasses
import json

import pytest

from pantograph_async import (
    FailureSnapshot,
    PantographCaptureError,
    PantographClient,
    PantographRemoteInternalError,
    PantographResourceError,
    PantographTacticRejected,
    RequestEvent,
    SessionPhase,
    parse_repl_failures,
)
from pantograph_async.evidence import REQUEST_BYTES, snapshot_for
from tests.support import assert_reaped, records, run


def requests_sent(report):
    return [row["command"] for row in records(report) if row["kind"] == "request"]


def test_every_request_is_reported_before_it_is_written_and_after_it_finishes(setup):
    env, report = setup
    events: list[RequestEvent] = []

    def observe(event):
        # The command is not on the wire yet when "prepared" arrives.
        if event.stage == "prepared":
            assert requests_sent(report).count(event.operation) < sum(
                1 for e in events if e.operation == event.operation and e.stage == "prepared") + 1
        events.append(event)

    async def body():
        async with await PantographClient.create(env, observer=observe) as client:
            async with client.state_scope() as scope:
                root = await scope.start_goal("True")
                done = await scope.apply_tactic(root, "trivial")
                await scope.inspect(done, [root.root])
                await scope.certify(done)

    run(body)
    operations = [e.operation for e in events if e.stage == "prepared"]
    assert operations[:3] == ["protocol.describe", "options.set", "options.print"]
    for name in ("goal.start", "goal.tactic", "goal.inspect", "goal.certify", "goal.delete"):
        assert name in operations
    sequences = [e.sequence for e in events if e.stage == "prepared"]
    assert sequences == sorted(sequences) and len(set(sequences)) == len(sequences)
    for event in events:
        if event.stage == "prepared":
            done = [e for e in events if e.sequence == event.sequence and e.stage == "completed"]
            assert len(done) == 1 and events.index(done[0]) > events.index(event)
    tactic = next(e for e in events if e.operation == "goal.tactic" and e.stage == "prepared")
    assert json.loads(tactic.request.split(" ", 1)[1])["tactic"] == "trivial"
    assert (tactic.state_id, tactic.goal_index) == (0, 0)
    allocated = [e.allocated_state_id for e in events if e.stage == "completed"
                 and e.operation in ("goal.start", "goal.tactic")]
    assert allocated == [0, 1]
    json.dumps([e.to_dict() for e in events])
    assert_reaped(report)


def test_a_repl_failure_keeps_the_request_error_and_matched_repl_record(setup):
    env, report = setup

    async def body():
        client = await PantographClient.create(env)
        async with client.state_scope() as scope:
            root = await scope.start_goal("True")
            with pytest.raises(PantographRemoteInternalError):
                await scope.apply_tactic(root, "repl_failure")
        assert client.phase is SessionPhase.CLOSED and not client.is_usable
        snapshot = client.last_failure
        assert isinstance(snapshot, FailureSnapshot) and snapshot.final
        assert snapshot.operation == "goal.tactic" and snapshot.exchange_stage == "decoded"
        assert json.loads(snapshot.request.split(" ", 1)[1])["tactic"] == "repl_failure"
        assert (snapshot.state_id, snapshot.goal_index) == (0, 0)
        assert snapshot.error_type == "PantographRemoteInternalError"
        assert snapshot.payload["recovery"] == "session-unusable"
        assert snapshot.association == "matched"
        record = snapshot.repl_failure
        assert record.detail == "unknown constant 'Foo'" and record.phase == "observe"
        # The two counters are independent and both are kept.
        assert record.repl_command_sequence == 7 and snapshot.sequence != 7
        with pytest.raises(dataclasses.FrozenInstanceError):
            snapshot.message = "changed"  # type: ignore[misc]
        json.dumps(snapshot.to_dict())
        await client.aclose()

    run(body)
    assert_reaped(report)


def test_a_record_after_the_response_is_never_misattributed(setup):
    # The real REPL writes its record before the response. If a record only
    # arrives later, shutdown may end the process first: absence is reported.
    env, report = setup

    async def body():
        client = await PantographClient.create(env)
        async with client.state_scope() as scope:
            root = await scope.start_goal("True")
            with pytest.raises(PantographRemoteInternalError):
                await scope.apply_tactic(root, "repl_failure_late_stderr")
        await client.aclose()
        snapshot = client.last_failure
        assert snapshot.final and snapshot.association in ("matched", "absent")
        assert (snapshot.repl_failure is None) == (snapshot.association == "absent")
        assert client.last_failure is snapshot

    run(body)
    assert_reaped(report)


def test_an_observer_failure_before_the_write_sends_nothing(setup):
    env, report = setup
    calls = []

    def observe(event):
        calls.append(event)
        if event.operation == "goal.tactic" and event.stage == "prepared":
            raise RuntimeError("journal disk full")

    async def body():
        async with await PantographClient.create(env, observer=observe) as client:
            async with client.state_scope() as scope:
                root = await scope.start_goal("True")
                with pytest.raises(PantographCaptureError, match="journal disk full"):
                    await scope.apply_tactic(root, "trivial")
                # Nothing was written, so the session and the input state are intact.
                assert client.is_usable and (await client.stat()).n_goals == 1

    run(body)
    assert "goal.tactic" not in requests_sent(report)
    assert_reaped(report)


def test_an_observer_failure_after_the_response_keeps_the_allocation(setup):
    env, report = setup

    def observe(event):
        if event.operation == "goal.start" and event.stage == "completed":
            raise RuntimeError("late sink failure")

    async def body():
        async with await PantographClient.create(env, observer=observe) as client:
            async with client.state_scope() as scope:
                root = await scope.start_goal("True")
                assert scope._validate_state(root)
                assert (await client.stat()).n_goals == 1
            assert (await client.stat()).n_goals == 0
            assert any("late sink failure" in error for error in client.capture_errors)

    run(body)
    assert_reaped(report)


def test_ordinary_rejection_and_resource_rollback_keep_the_session(setup):
    env, report = setup

    async def body():
        async with await PantographClient.create(env) as client:
            async with client.state_scope() as scope:
                root = await scope.start_goal("True")
                with pytest.raises(PantographTacticRejected):
                    await scope.apply_tactic(root, "tactic_failure")
                with pytest.raises(PantographResourceError):
                    await scope.apply_tactic(root, "resource_rollback")
                assert client.is_usable
                assert client.last_failure.error_type == "PantographResourceError"
                assert client.last_failure.association == "absent"
                await scope.apply_tactic(root, "trivial")

    run(body)
    assert_reaped(report)


def test_snapshot_bounds_and_ambiguous_records():
    record = {
        "kind": "pantograph-command-failure", "version": 1, "repl_command_sequence": 2,
        "operation": "goal.inspect", "state_id": 4, "goal_index": None, "phase": "observe",
        "exception_category": "error", "internal_exception_id": None, "detail": "x",
        "detail_truncated": False, "render_status": "rendered",
    }
    stderr = "\n".join(["noise", "{not json", json.dumps({**record, "version": 2}),
                        json.dumps({**record, "state_id": "4"}), json.dumps(record)])
    assert [r.repl_command_sequence for r in parse_repl_failures(stderr)] == [2]
    error = PantographRemoteInternalError("boom", command="goal.tactic", payload={"deep": ["∀" * 50000]})
    request = ('goal.tactic {"stateId":4,"goalId":0,"tactic":"' + "x" * (2 * REQUEST_BYTES) + '"}\n').encode()
    snapshot = snapshot_for(
        session_id="s", pid=1, sequence=9, operation="goal.tactic", request=request,
        body={"stateId": 4, "goalId": 0}, stage="decoded", error=error, stderr_tail=stderr)
    assert snapshot.request_truncated and len(snapshot.request.encode()) <= REQUEST_BYTES
    assert len(json.dumps(snapshot.payload, ensure_ascii=False).encode()) <= 32768
    # The only record names another operation: it is not assigned to this request.
    assert snapshot.association == "ambiguous" and snapshot.repl_failure is None
