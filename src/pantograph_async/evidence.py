"""Bounded, immutable evidence about requests and failed requests.

The client numbers every request it serializes and can report each one to an
observer before it is written and again when it finishes. When a request fails,
it keeps a :class:`FailureSnapshot`: the exact bounded request, the typed error
and its structured payload, the stderr tail, and any version-1
``pantograph-command-failure`` records the REPL wrote. These are plain data;
they hold no states, handles, processes or futures.

``client_request_sequence`` (this module's ``sequence``) is counted by the client.
The REPL's ``repl_command_sequence`` is counted by the REPL. They are recorded
side by side and never assumed equal.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
from typing import Any, Callable, Literal

from .protocol import PantographError

__all__ = [
    "EVIDENCE_VERSION",
    "REPL_FAILURE_KIND",
    "FailureSnapshot",
    "PantographCaptureError",
    "ReplFailureRecord",
    "RequestEvent",
    "RequestObserver",
    "parse_repl_failures",
]

EVIDENCE_VERSION = 1
REPL_FAILURE_KIND = "pantograph-command-failure"
REQUEST_BYTES = 16384
PAYLOAD_BYTES = 16384

Stage = Literal["prepared", "completed", "failed"]
ExchangeStage = Literal["waiting", "prepared", "written", "decoded"]
Association = Literal["matched", "ambiguous", "absent"]


class PantographCaptureError(PantographError):
    """The request observer failed before the command was written. Nothing was sent."""


def _bounded_text(text: str, limit: int) -> tuple[str, bool]:
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text, False
    return data[:limit].decode("utf-8", errors="ignore"), True


def _plain(value: Any) -> Any:
    """A JSON-compatible copy; dataclasses become dictionaries, unknown objects text."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return _plain(asdict(value))
    return repr(value)


def _bounded_payload(value: Any) -> Any:
    plain = _plain(value)
    text = json.dumps(plain, ensure_ascii=False)
    if len(text.encode("utf-8")) <= PAYLOAD_BYTES:
        return plain
    prefix, _ = _bounded_text(text, PAYLOAD_BYTES)
    return {"truncated": True, "json_prefix": prefix}


@dataclass(frozen=True)
class RequestEvent:
    """One request at one stage. ``prepared`` is reported before the write."""

    session_id: str
    pid: int | None
    sequence: int
    operation: str
    stage: Stage
    request: str
    request_truncated: bool
    state_id: int | None = None
    goal_index: int | None = None
    outcome: str | None = None
    error_type: str | None = None
    elapsed_s: float | None = None
    #: The state the response allocated (``goal.start``, ``goal.tactic``), for
    #: mapping recorded states to fresh ones in a replay. Never a live handle.
    allocated_state_id: int | None = None
    version: int = EVIDENCE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


RequestObserver = Callable[[RequestEvent], None]


@dataclass(frozen=True)
class ReplFailureRecord:
    """A version-1 ``pantograph-command-failure`` line from REPL stderr."""

    repl_command_sequence: int
    operation: str
    state_id: int | None
    goal_index: int | None
    phase: str
    exception_category: str
    internal_exception_id: str | None
    detail: str | None
    detail_truncated: bool
    render_status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _record(value: Any) -> ReplFailureRecord | None:
    if not isinstance(value, dict) or value.get("kind") != REPL_FAILURE_KIND or value.get("version") != 1:
        return None
    try:
        record = ReplFailureRecord(
            repl_command_sequence=value["repl_command_sequence"],
            operation=value["operation"],
            state_id=value["state_id"],
            goal_index=value["goal_index"],
            phase=value["phase"],
            exception_category=value["exception_category"],
            internal_exception_id=value["internal_exception_id"],
            detail=value["detail"],
            detail_truncated=value["detail_truncated"],
            render_status=value["render_status"],
        )
    except (KeyError, TypeError):
        return None
    numbers = (record.repl_command_sequence, record.state_id, record.goal_index)
    if any(n is not None and (type(n) is not int or n < 0) for n in numbers):
        return None
    texts = (record.operation, record.phase, record.exception_category, record.render_status)
    if not all(isinstance(t, str) for t in texts) or type(record.detail_truncated) is not bool:
        return None
    if record.detail is not None and not isinstance(record.detail, str):
        return None
    if record.internal_exception_id is not None and not isinstance(record.internal_exception_id, str):
        return None
    return record


def parse_repl_failures(stderr: str) -> tuple[ReplFailureRecord, ...]:
    """Recognized version-1 records only; any other stderr stays raw text."""
    found = []
    for line in stderr.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            record = _record(json.loads(line))
        except ValueError:
            continue
        if record is not None:
            found.append(record)
    return tuple(found)


@dataclass(frozen=True)
class FailureSnapshot:
    """Evidence for one failed or interrupted request.

    A request that was written owns the session's snapshot: a caller that was
    still waiting (and so wrote nothing) never replaces it, even when it
    receives the same terminal exception.

    ``final`` is true once the process has been reaped and stderr drained; a
    REPL record can arrive after the stdout response, so read
    ``PantographClient.last_failure`` after ``aclose()`` for the final version.
    """

    session_id: str
    pid: int | None
    sequence: int
    operation: str
    request: str
    request_truncated: bool
    exchange_stage: ExchangeStage
    error_type: str
    message: str
    payload: Any
    notes: tuple[str, ...]
    stderr_tail: str
    state_id: int | None = None
    goal_index: int | None = None
    timeout_source: str | None = None
    repl_records: tuple[ReplFailureRecord, ...] = ()
    association: Association = "absent"
    final: bool = False
    capture_errors: tuple[str, ...] = field(default=())
    version: int = EVIDENCE_VERSION

    @property
    def repl_failure(self) -> ReplFailureRecord | None:
        """The REPL record for this request when the association is unambiguous."""
        return self.repl_records[-1] if self.association == "matched" else None

    def finalized(self, stderr_tail: str) -> "FailureSnapshot":
        records = parse_repl_failures(stderr_tail)
        return replace(self, stderr_tail=stderr_tail, repl_records=records,
                       association=associate(self, records), final=True)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["repl_records"] = [record.to_dict() for record in self.repl_records]
        return data


def associate(snapshot: FailureSnapshot, records: tuple[ReplFailureRecord, ...]) -> Association:
    """A fatal REPL record belongs to the pending request when the last record
    names its operation, state and goal. One session has one failed request, so
    an earlier record or a mismatch is ambiguous rather than assigned."""
    if not records:
        return "absent"
    last = records[-1]
    same = (last.operation == snapshot.operation and last.state_id == snapshot.state_id
            and last.goal_index == snapshot.goal_index)
    return "matched" if same and len(records) == 1 else "ambiguous"


def describe_request(body: dict[str, Any]) -> tuple[int | None, int | None]:
    state = body.get("stateId", body.get("target"))
    goal = body.get("goalId")
    return (state if type(state) is int else None, goal if type(goal) is int else None)


def snapshot_for(
    *, session_id: str, pid: int | None, sequence: int, operation: str, request: bytes,
    body: dict[str, Any], stage: ExchangeStage, error: BaseException, stderr_tail: str,
    timeout_source: str | None = None, capture_errors: tuple[str, ...] = (),
) -> FailureSnapshot:
    text, truncated = _bounded_text(request.decode("utf-8", errors="replace").rstrip("\n"), REQUEST_BYTES)
    state_id, goal_index = describe_request(body)
    snapshot = FailureSnapshot(
        session_id=session_id, pid=pid, sequence=sequence, operation=operation,
        request=text, request_truncated=truncated, exchange_stage=stage,
        error_type=type(error).__name__, message=str(error)[:4096],
        payload=_bounded_payload(getattr(error, "payload", None)),
        notes=tuple(note[:4096] for note in getattr(error, "__notes__", ())[:8]),
        stderr_tail=stderr_tail, state_id=state_id, goal_index=goal_index,
        timeout_source=timeout_source, capture_errors=capture_errors,
    )
    records = parse_repl_failures(stderr_tail)
    return replace(snapshot, repl_records=records, association=associate(snapshot, records))


def event_for(
    *, session_id: str, pid: int | None, sequence: int, operation: str, request: bytes,
    body: dict[str, Any], stage: Stage, outcome: str | None = None,
    error: BaseException | None = None, elapsed_s: float | None = None,
    allocated_state_id: int | None = None,
) -> RequestEvent:
    text, truncated = _bounded_text(request.decode("utf-8", errors="replace").rstrip("\n"), REQUEST_BYTES)
    state_id, goal_index = describe_request(body)
    return RequestEvent(
        session_id=session_id, pid=pid, sequence=sequence, operation=operation, stage=stage,
        request=text, request_truncated=truncated, state_id=state_id, goal_index=goal_index,
        outcome=outcome, error_type=type(error).__name__ if error is not None else None,
        elapsed_s=elapsed_s, allocated_state_id=allocated_state_id,
    )
