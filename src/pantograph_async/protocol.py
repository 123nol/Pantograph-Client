"""Pure codec for the explicit-focused custom Pantograph contract, version 2.

There is no subprocess or upstream-client dependency here. Missing transition
evidence is rejected, including responses from the unmodified custom REPL.
Conversions into application goal models belong to the consumer.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

# The client owns every wire version. Consumers compare their own expression
# representation against these values instead of the codec importing theirs.
MODEL_SEXP_VERSION = 1

PROTOCOL_DESCRIPTION = MappingProxyType(
    {
        "protocol": "maths-ai-pantograph",
        "protocolVersion": 2,
        "modelSexpVersion": MODEL_SEXP_VERSION,
        "transitionValidationVersion": 1,
        "transitionProvenanceVersion": 1,
        "inspectionVersion": 1,
        "certificationVersion": 1,
        "messageVersion": 1,
        "goalSelection": "explicit-focused-v1",
        "tacticErrorsFormat": "string-array-v1",
    }
)
REQUIRED_OPTIONS = MappingProxyType(
    {
        "printJsonPretty": False,
        "printExprPretty": True,
        "printExprAST": True,
        "printExprModelAST": True,
        "noRepeat": False,
        "automaticMode": True,
    }
)
OPTION_NAMES = frozenset(REQUIRED_OPTIONS) | {
    "printDependentMVars",
    "printAuxDecls",
    "printImplementationDetailHyps",
}
BINDER_ROLES = frozenset(
    {
        ":explicit",
        ":implicit",
        ":strict-implicit",
        ":instance-implicit",
        ":let",
    }
)
GOAL_FRAGMENTS = frozenset({"tactic", "conv", "calc"})
# goal.start passes each level through String.toName, which splits at dots, so
# only atomic ASCII names are accepted. Callers map other names to safe aliases.
LEVEL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_']*")
RESERVED_LEVEL_NAMES = frozenset({"_", "max", "imax"})
SUPPORTED_COMMANDS = frozenset(
    {
        "protocol.describe",
        "options.set",
        "options.print",
        "goal.start",
        "goal.tactic",
        "goal.delete",
        "goal.inspect",
        "goal.certify",
        "stat",
    }
)
OBLIGATION_STATUSES = frozenset({"active", "pending", "assigned", "delayed", "complete"})
CERTIFICATE_STATUSES = frozenset({"certified", "incomplete", "rejected", "inconclusive"})
PROOF_IDENTITY = "lean-expr-digest-v1"
DIGEST = re.compile(r"[0-9a-f]{16}")
# These categories come from Repl.lean and Library.lean at the pinned base.
# "validation" is reserved for the required companion extension.
COMMAND_ERROR_CATEGORIES = MappingProxyType(
    {
        "protocol.describe": frozenset({"command"}),
        "options.set": frozenset({"command"}),
        "options.print": frozenset({"command"}),
        "goal.start": frozenset({"command", "arguments", "parsing", "elab"}),
        "goal.tactic": frozenset(
            {"command", "arguments", "index", "invalid", "validation"}
        ),
        "goal.delete": frozenset({"command"}),
        "goal.inspect": frozenset({"command", "arguments", "index"}),
        "goal.certify": frozenset({"command", "arguments", "index"}),
        "stat": frozenset({"command"}),
    }
)


class PantographError(RuntimeError):
    """Base failure with command and independently copied wire-payload context."""

    def __init__(
        self, message: str, *, command: str | None = None, payload: Any = None
    ):
        super().__init__(message)
        self.command = command
        self._payload = deepcopy(payload)

    @property
    def payload(self) -> Any:
        return deepcopy(self._payload)


class PantographConfigurationError(PantographError):
    pass


class PantographStartupError(PantographError):
    pass


class PantographGoalRejected(PantographError):
    pass


class PantographTacticRejected(PantographError):
    pass


class PantographProtocolError(PantographError):
    pass


class PantographTransportError(PantographError):
    pass


class PantographRequestTimeout(PantographTransportError):
    pass


class PantographStateError(PantographError):
    pass


@dataclass(frozen=True)
class StateHandle:
    """A session-bound allocation. ``allocation`` numbers the scope's
    registrations, so a released handle stays distinct from a later state that
    reuses its server ID."""

    session_id: str
    scope_id: str
    state_id: int
    allocation: int = 0

    def __post_init__(self):
        if (
            not isinstance(self.session_id, str)
            or not self.session_id
            or not isinstance(self.scope_id, str)
            or not self.scope_id
            or type(self.state_id) is not int
            or self.state_id < 0
            or type(self.allocation) is not int
            or self.allocation < 0
        ):
            raise PantographStateError(
                "A handle requires session/scope identities and nonnegative integer IDs."
            )


@dataclass(frozen=True)
class WireExpression:
    pp: str
    sexp: str
    model_sexp: str
    model_sexp_version: int
    dependent_mvars: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ExecutionLocal:
    internal_name: str
    user_name: str
    context_index: int
    binder_role: str
    is_instance: bool
    is_let: bool
    is_inaccessible: bool
    type: WireExpression
    value: WireExpression | None = None


@dataclass(frozen=True)
class ExecutionGoal:
    goal_name: str
    case_tag: str | None
    is_conversion: bool
    fragment: str
    target: WireExpression
    locals: tuple[ExecutionLocal, ...]


@dataclass(frozen=True)
class MessagePosition:
    line: int
    column: int

    @property
    def is_available(self) -> bool:
        """The merged wire's (0, 0) sentinel is not a source location."""
        return self.line != 0


@dataclass(frozen=True)
class ExecutionMessage:
    severity: str
    data: str
    kind: str
    pos: MessagePosition
    end_pos: MessagePosition | None = None


@dataclass(frozen=True)
class TransitionValidation:
    version: int
    scope: str
    checked: bool
    has_sorry: bool
    has_unsafe: bool

    @property
    def is_rejection(self) -> bool:
        return self.has_sorry or self.has_unsafe


@dataclass(frozen=True)
class TransitionProvenance:
    """How a transition's goals relate to its input state, by execution name.

    ``direct``, ``siblings`` and ``extra`` partition the result's goals.
    ``direct`` contains ``selected`` itself when the tactic left it open.
    ``introduced[i]`` lists the locals ``direct[i]`` has that ``selected`` lacks.
    Names are valid only inside this session's state lineage.
    """

    selected: str
    direct: tuple[str, ...]
    introduced: tuple[tuple[str, ...], ...]
    siblings: tuple[str, ...]
    changed: tuple[str, ...]
    closed: tuple[str, ...]
    dormant: tuple[str, ...]
    extra: tuple[str, ...]


@dataclass(frozen=True)
class ObligationInspection:
    name: str
    status: str
    goal: ExecutionGoal | None
    holes: tuple[str, ...]
    universe_holes: bool

    @property
    def is_complete(self) -> bool:
        return self.status == "complete"


@dataclass(frozen=True)
class CertificateReceipt:
    root: str
    levels: tuple[str, ...]
    root_type: str
    proof: str
    environment: str
    lean: str
    axioms: tuple[str, ...]
    auxiliary: tuple[str, ...]
    identity: str = PROOF_IDENTITY
    version: int = 1


@dataclass(frozen=True)
class CertificationResult:
    """The kernel's verdict on a state's complete root proof.

    Only ``certified`` is success. ``inconclusive`` means a resource limit,
    not a rejected proof.
    """

    status: str
    reason: str | None
    receipt: CertificateReceipt | None

    @property
    def is_certified(self) -> bool:
        return self.status == "certified"


@dataclass(frozen=True)
class StartedGoal:
    handle: StateHandle
    root: str


@dataclass(frozen=True)
class TacticState:
    handle: StateHandle
    goals: tuple[ExecutionGoal, ...]
    validation: TransitionValidation
    messages: tuple[ExecutionMessage, ...]
    transition: TransitionProvenance


@dataclass(frozen=True)
class GoalStartResult:
    state_id: int
    root: str


@dataclass(frozen=True)
class TacticSuccess:
    next_state_id: int
    goals: tuple[ExecutionGoal, ...]
    validation: TransitionValidation
    messages: tuple[ExecutionMessage, ...]
    transition: TransitionProvenance


@dataclass(frozen=True)
class TacticParseFailure:
    parse_error: str
    messages: tuple[ExecutionMessage, ...]


@dataclass(frozen=True)
class TacticFailure:
    tactic_errors: tuple[str, ...]
    messages: tuple[ExecutionMessage, ...]


@dataclass(frozen=True)
class CommandError:
    command: str
    category: str
    description: str

    def as_exception(self) -> PantographError:
        error_class: type[PantographError] = PantographProtocolError
        if self.command == "goal.start" and self.category in {"parsing", "elab"}:
            error_class = PantographGoalRejected
        elif (
            self.command in {"goal.tactic", "goal.inspect", "goal.certify"}
            and self.category == "index"
        ):
            error_class = PantographStateError
        return error_class(
            self.description,
            command=self.command,
            payload={"error": self.category, "desc": self.description},
        )


@dataclass(frozen=True)
class PantographStats:
    n_goals: int


@dataclass(frozen=True)
class CommandAcknowledgement:
    command: str


@dataclass(frozen=True)
class ProtocolDescription:
    protocol: str
    protocol_version: int
    model_sexp_version: int
    transition_validation_version: int
    transition_provenance_version: int
    inspection_version: int
    certification_version: int
    message_version: int
    goal_selection: str
    tactic_errors_format: str


@dataclass(frozen=True)
class SessionOptions:
    values: tuple[tuple[str, bool], ...]

    def to_dict(self) -> dict[str, bool]:
        return dict(self.values)


@dataclass(frozen=True)
class InspectionResult:
    obligations: tuple[ObligationInspection, ...]


Response = (
    GoalStartResult
    | TacticSuccess
    | InspectionResult
    | CertificationResult
    | TacticParseFailure
    | TacticFailure
    | CommandError
    | PantographStats
    | CommandAcknowledgement
    | ProtocolDescription
    | SessionOptions
)


def _object(value: Any, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise PantographProtocolError(f"{owner} must be a JSON object.")
    return value


def _fields(
    value: dict[str, Any], required: set[str] | frozenset[str], optional=()
) -> None:
    missing = set(required) - value.keys()
    extra = value.keys() - set(required) - set(optional)
    if missing or extra:
        raise PantographProtocolError(
            f"Invalid fields: missing={sorted(missing)}, unexpected={sorted(extra)}."
        )


def _string(value: Any, owner: str, *, nonempty: bool = False) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise PantographProtocolError(
            f"{owner} must be a{' nonempty' if nonempty else ''} string."
        )
    # Reject unpaired surrogates even when JSON used escaped character values.
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PantographProtocolError(f"{owner} is not valid UTF-8 text.") from exc
    return value


def _nat(value: Any, owner: str) -> int:
    if type(value) is not int or value < 0:
        raise PantographProtocolError(
            f"{owner} must be a nonnegative integer, not a Boolean."
        )
    return value


def _bool(value: Any, owner: str) -> bool:
    if type(value) is not bool:
        raise PantographProtocolError(f"{owner} must be a Boolean.")
    return value


def _array(value: Any, owner: str) -> list[Any]:
    if not isinstance(value, list):
        raise PantographProtocolError(f"{owner} must be a JSON array.")
    return value


def _level_name(value: Any) -> str:
    name = _string(value, "universe level", nonempty=True)
    if not LEVEL_NAME.fullmatch(name) or name in RESERVED_LEVEL_NAMES:
        raise PantographProtocolError(
            f"Universe level {name!r} is not an atomic ASCII Lean name."
        )
    return name


def decode_json_response(line: str | bytes) -> dict[str, Any]:
    """Parse one response object without accepting duplicate keys or NaN."""

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise PantographProtocolError(f"Duplicate JSON key {key!r}.")
            result[key] = value
        return result

    def constant(value):
        raise PantographProtocolError(f"Nonstandard JSON constant {value!r}.")

    try:
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="strict")
        if not isinstance(line, str):
            raise PantographProtocolError(
                "A JSON response requires text or UTF-8 bytes."
            )
        return _object(
            json.loads(line, object_pairs_hook=pairs, parse_constant=constant),
            "response",
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as exc:
        raise PantographProtocolError(f"Invalid UTF-8/JSON response: {exc}.") from exc


def encode_request(command: str, payload: Mapping[str, Any]) -> bytes:
    """Validate the supported request and produce exactly one compact line."""
    if command not in SUPPORTED_COMMANDS:
        raise PantographConfigurationError(
            f"Unsupported command {command!r}.", command=command
        )
    body = _object(dict(payload), "request")
    if command in {"protocol.describe", "options.print", "stat"}:
        _fields(body, set())
    elif command == "options.set":
        _fields(body, set(), OPTION_NAMES)
        for key, value in body.items():
            _bool(value, key)
            if key in REQUIRED_OPTIONS and value is not REQUIRED_OPTIONS[key]:
                raise PantographConfigurationError(
                    f"Option {key} conflicts with the execution contract."
                )
    elif command == "goal.start":
        _fields(body, {"expr"}, {"levels"})
        _string(body["expr"], "expr", nonempty=True)
        if "levels" in body:
            # No levels is sent by omitting the field, so the request stays canonical.
            levels = [_level_name(item) for item in _array(body["levels"], "levels")]
            if not levels or len(set(levels)) != len(levels):
                raise PantographProtocolError(
                    "levels must be a nonempty list of unique names."
                )
    elif command == "goal.tactic":
        _fields(body, {"stateId", "goalId", "tactic"})
        _nat(body["stateId"], "stateId")
        _nat(body["goalId"], "goalId")
        _string(body["tactic"], "tactic", nonempty=True)
    elif command == "goal.inspect":
        _fields(body, {"stateId", "goals"})
        _nat(body["stateId"], "stateId")
        goals = [
            _string(item, "obligation name", nonempty=True)
            for item in _array(body["goals"], "goals")
        ]
        if not goals or len(set(goals)) != len(goals):
            raise PantographProtocolError(
                "goals must be a nonempty list of distinct names."
            )
    elif command == "goal.certify":
        _fields(body, {"stateId"}, {"maxHeartbeats"})
        _nat(body["stateId"], "stateId")
        if "maxHeartbeats" in body and _nat(body["maxHeartbeats"], "maxHeartbeats") == 0:
            raise PantographProtocolError("maxHeartbeats must be positive.")
    else:
        _fields(body, {"stateIds"})
        ids = [
            _nat(item, "stateIds entry")
            for item in _array(body["stateIds"], "stateIds")
        ]
        if len(set(ids)) != len(ids):
            raise PantographStateError("Deletion IDs must be unique.")
    return (
        command
        + " "
        + json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def decode_expression(payload: Any) -> WireExpression:
    obj = _object(payload, "expression")
    _fields(obj, {"pp", "sexp", "modelSexp", "modelSexpVersion"}, {"dependentMVars"})
    version = _nat(obj["modelSexpVersion"], "modelSexpVersion")
    if version != MODEL_SEXP_VERSION:
        raise PantographProtocolError(f"Unsupported modelSexpVersion {version}.")
    deps = None
    if "dependentMVars" in obj:
        deps = tuple(
            _string(item, "dependent metavariable", nonempty=True)
            for item in _array(obj["dependentMVars"], "dependentMVars")
        )
    return WireExpression(
        _string(obj["pp"], "pp", nonempty=True),
        _string(obj["sexp"], "sexp", nonempty=True),
        _string(obj["modelSexp"], "modelSexp", nonempty=True),
        version,
        deps,
    )


def decode_execution_goal(payload: Any) -> ExecutionGoal:
    obj = _object(payload, "goal")
    _fields(obj, {"name", "isConversion", "fragment", "target", "vars"}, {"userName"})
    fragment = _string(obj["fragment"], "fragment")
    if fragment not in GOAL_FRAGMENTS:
        raise PantographProtocolError(f"Unsupported goal fragment {fragment!r}.")
    is_conversion = _bool(obj["isConversion"], "isConversion")
    if is_conversion != (fragment == "conv"):
        raise PantographProtocolError("Goal fragment and isConversion disagree.")
    target = decode_expression(obj["target"])
    locals_ = []
    for item in _array(obj["vars"], "vars"):
        local = _object(item, "local")
        _fields(
            local,
            {
                "name",
                "userName",
                "contextIndex",
                "binderRole",
                "isInstance",
                "isLet",
                "isInaccessible",
                "type",
            },
            {"value"},
        )
        role = _string(local["binderRole"], "binderRole")
        if role not in BINDER_ROLES:
            raise PantographProtocolError(f"Unsupported binderRole {role!r}.")
        instance = _bool(local["isInstance"], "isInstance")
        is_let = _bool(local["isLet"], "isLet")
        if is_let != (role == ":let") or instance != (role == ":instance-implicit"):
            raise PantographProtocolError(
                "Local binder role and instance/let flags disagree."
            )
        if ("value" in local) != is_let:
            raise PantographProtocolError(
                "Only let locals must carry a complete value expression."
            )
        locals_.append(
            ExecutionLocal(
                _string(local["name"], "local name", nonempty=True),
                _string(local["userName"], "local userName"),
                _nat(local["contextIndex"], "contextIndex"),
                role,
                instance,
                is_let,
                _bool(local["isInaccessible"], "isInaccessible"),
                decode_expression(local["type"]),
                decode_expression(local["value"]) if is_let else None,
            )
        )
    indices = [local.context_index for local in locals_]
    if indices != sorted(set(indices)):
        raise PantographProtocolError(
            "Locals must have unique increasing context indices; gaps are permitted."
        )
    return ExecutionGoal(
        _string(obj["name"], "goal name", nonempty=True),
        _string(obj["userName"], "goal userName") if "userName" in obj else None,
        is_conversion,
        fragment,
        target,
        tuple(locals_),
    )


def decode_messages(payload: Any) -> tuple[ExecutionMessage, ...]:
    def position(value: Any) -> MessagePosition:
        obj = _object(value, "message position")
        _fields(obj, {"line", "column"})
        line = _nat(obj["line"], "line")
        column = _nat(obj["column"], "column")
        if line == 0 and column != 0:
            raise PantographProtocolError(
                "An unavailable message position must be exactly (0, 0)."
            )
        return MessagePosition(line, column)

    result = []
    for item in _array(payload, "messages"):
        obj = _object(item, "message")
        _fields(obj, {"kind", "severity", "pos", "data"}, {"endPos"})
        severity = _string(obj["severity"], "severity")
        if severity not in {"information", "warning", "error"}:
            raise PantographProtocolError(f"Unknown message severity {severity!r}.")
        pos = position(obj["pos"])
        end = position(obj["endPos"]) if "endPos" in obj else None
        if end is not None and (
            not pos.is_available
            or not end.is_available
            or (end.line, end.column) < (pos.line, pos.column)
        ):
            raise PantographProtocolError(
                "Message endPos requires an ordered start position."
            )
        result.append(
            ExecutionMessage(
                severity,
                _string(obj["data"], "message data"),
                _string(obj["kind"], "kind"),
                pos,
                end,
            )
        )
    return tuple(result)


def decode_transition_validation(
    payload: Any, *, has_sorry: bool, has_unsafe: bool
) -> TransitionValidation:
    """Combine check metadata with the merged response's top-level proof flags."""
    obj = _object(payload, "validation")
    _fields(obj, {"version", "scope", "checked"})
    version = _nat(obj["version"], "validation version")
    scope = _string(obj["scope"], "validation scope")
    checked = _bool(obj["checked"], "validation checked")
    if version != 1 or scope != "transition-expressions" or not checked:
        raise PantographProtocolError(
            "Required transition validation was not performed with the supported version/scope."
        )
    return TransitionValidation(
        version,
        scope,
        checked,
        _bool(has_sorry, "hasSorry"),
        _bool(has_unsafe, "hasUnsafe"),
    )


def _names(value: Any, owner: str) -> tuple[str, ...]:
    names = tuple(
        _string(item, owner, nonempty=True) for item in _array(value, owner)
    )
    if len(set(names)) != len(names):
        raise PantographProtocolError(f"{owner} names must be distinct.")
    return names


def decode_transition(
    payload: Any, goals: tuple[ExecutionGoal, ...]
) -> TransitionProvenance:
    """Decode provenance and check it against the response's own goals."""
    obj = _object(payload, "transition")
    _fields(
        obj,
        {
            "version",
            "selected",
            "direct",
            "introduced",
            "siblings",
            "changed",
            "closed",
            "dormant",
            "extra",
        },
    )
    if _nat(obj["version"], "transition version") != 1:
        raise PantographProtocolError("Unsupported transition provenance version.")
    selected = _string(obj["selected"], "selected goal", nonempty=True)
    direct = _names(obj["direct"], "direct")
    siblings = _names(obj["siblings"], "siblings")
    extra = _names(obj["extra"], "extra")
    changed = _names(obj["changed"], "changed")
    closed = _names(obj["closed"], "closed")
    dormant = _names(obj["dormant"], "dormant")
    introduced = tuple(
        _names(item, "introduced") for item in _array(obj["introduced"], "introduced")
    )
    listed = [goal.goal_name for goal in goals]
    parts = [*direct, *siblings, *extra]
    if len(set(parts)) != len(parts) or set(parts) != set(listed):
        raise PantographProtocolError(
            "direct, siblings and extra must partition the returned goals."
        )
    unlisted = [*closed, *dormant, selected]
    if len(set(unlisted)) != len(unlisted) or set(unlisted[:-1]) & set(listed):
        raise PantographProtocolError(
            "The selected, closed and dormant goals must be distinct; closed and dormant goals are unlisted."
        )
    # An operation that leaves the selected goal open (skip) lists it as direct.
    if selected in listed and selected not in direct:
        raise PantographProtocolError("A listed selected goal must be a direct goal.")
    if not set(changed) <= set(siblings):
        raise PantographProtocolError("Changed goals must be siblings.")
    if len(introduced) != len(direct):
        raise PantographProtocolError("introduced needs one entry per direct goal.")
    by_name = {goal.goal_name: goal for goal in goals}
    for name, locals_ in zip(direct, introduced):
        visible = {local.internal_name for local in by_name[name].locals}
        if not set(locals_) <= visible:
            raise PantographProtocolError(
                f"Introduced locals of {name} are not in its context."
            )
    return TransitionProvenance(
        selected, direct, introduced, siblings, changed, closed, dormant, extra
    )


def decode_obligation(payload: Any) -> ObligationInspection:
    obj = _object(payload, "obligation")
    _fields(obj, {"name", "status", "holes", "universeHoles"}, {"goal"})
    name = _string(obj["name"], "obligation name", nonempty=True)
    status = _string(obj["status"], "obligation status")
    if status not in OBLIGATION_STATUSES:
        raise PantographProtocolError(f"Unknown obligation status {status!r}.")
    holes = _names(obj["holes"], "holes")
    universe_holes = _bool(obj["universeHoles"], "universeHoles")
    if ("goal" in obj) != (status in {"active", "pending"}):
        raise PantographProtocolError(
            "Exactly the active and pending obligations carry a goal."
        )
    goal = decode_execution_goal(obj["goal"]) if "goal" in obj else None
    if goal is not None and goal.goal_name != name:
        raise PantographProtocolError("An inspected goal must carry its own name.")
    if status == "complete" and (holes or universe_holes):
        raise PantographProtocolError("A complete obligation has no holes.")
    if status in {"assigned", "delayed"} and not (holes or universe_holes):
        raise PantographProtocolError(
            "An incomplete assignment must report its remaining holes."
        )
    return ObligationInspection(name, status, goal, holes, universe_holes)


def decode_certificate(payload: Any) -> CertificationResult:
    obj = _object(payload, "certification")
    _fields(obj, {"version", "status"}, {"reason", "receipt"})
    if _nat(obj["version"], "certification version") != 1:
        raise PantographProtocolError("Unsupported certification version.")
    status = _string(obj["status"], "certification status")
    if status not in CERTIFICATE_STATUSES:
        raise PantographProtocolError(f"Unknown certification status {status!r}.")
    if status == "certified":
        if "reason" in obj or "receipt" not in obj:
            raise PantographProtocolError(
                "A certified result carries a receipt and no reason."
            )
        raw = _object(obj["receipt"], "receipt")
        _fields(
            raw,
            {
                "version",
                "identity",
                "root",
                "levels",
                "rootType",
                "proof",
                "environment",
                "lean",
                "axioms",
                "auxiliary",
            },
        )
        if _nat(raw["version"], "receipt version") != 1:
            raise PantographProtocolError("Unsupported receipt version.")
        if _string(raw["identity"], "receipt identity") != PROOF_IDENTITY:
            raise PantographProtocolError("Unsupported proof identity scheme.")
        digests = [
            _string(raw[key], key) for key in ("rootType", "proof", "environment")
        ]
        if not all(DIGEST.fullmatch(digest) for digest in digests):
            raise PantographProtocolError("Receipt digests must be 16 hex digits.")
        receipt = CertificateReceipt(
            _string(raw["root"], "receipt root", nonempty=True),
            tuple(_level_name(item) for item in _array(raw["levels"], "levels")),
            *digests,
            _string(raw["lean"], "receipt lean", nonempty=True),
            _names(raw["axioms"], "axioms"),
            _names(raw["auxiliary"], "auxiliary"),
        )
        return CertificationResult(status, None, receipt)
    if "receipt" in obj or "reason" not in obj:
        raise PantographProtocolError(
            "An uncertified result carries a reason and no receipt."
        )
    return CertificationResult(
        status, _string(obj["reason"], "certification reason", nonempty=True), None
    )


def decode_response(command: str, payload: Any) -> Response:
    """Decode one final-contract response, retaining typed domain failures.

    Positive admission/unsafe flags remain a TacticSuccess rejection candidate.
    The future state owner must register and delete that allocation before raising.
    """
    if command not in SUPPORTED_COMMANDS:
        raise PantographConfigurationError(
            f"Unsupported command {command!r}.", command=command
        )
    try:
        obj = _object(payload, "response")
        if "error" in obj:
            _fields(obj, {"error", "desc"})
            category = _string(obj["error"], "error category")
            if category not in COMMAND_ERROR_CATEGORIES[command]:
                raise PantographProtocolError(
                    f"Unknown {command} error category {category!r}."
                )
            return CommandError(
                command, category, _string(obj["desc"], "error description")
            )
        if command == "goal.start":
            _fields(obj, {"stateId", "root"})
            return GoalStartResult(
                _nat(obj["stateId"], "stateId"),
                _string(obj["root"], "root", nonempty=True),
            )
        if command == "goal.tactic":
            variants = [
                key
                for key in ("nextStateId", "parseError", "tacticErrors")
                if key in obj
            ]
            if len(variants) != 1:
                raise PantographProtocolError(
                    "A tactic response must contain exactly one success/failure indicator."
                )
            variant = variants[0]
            if variant == "nextStateId":
                _fields(
                    obj,
                    {
                        "nextStateId",
                        "goals",
                        "validation",
                        "transition",
                        "messages",
                        "hasSorry",
                        "hasUnsafe",
                    },
                )
                goals = tuple(
                    decode_execution_goal(item)
                    for item in _array(obj["goals"], "goals")
                )
                if len({goal.goal_name for goal in goals}) != len(goals):
                    raise PantographProtocolError(
                        "Execution goal names must be unique within a state."
                    )
                messages = decode_messages(obj["messages"])
                if any(message.severity == "error" for message in messages):
                    raise PantographProtocolError(
                        "A logged error cannot accompany a successful transition."
                    )
                return TacticSuccess(
                    _nat(obj["nextStateId"], "nextStateId"),
                    goals,
                    decode_transition_validation(
                        obj["validation"],
                        has_sorry=obj["hasSorry"],
                        has_unsafe=obj["hasUnsafe"],
                    ),
                    messages,
                    decode_transition(obj["transition"], goals),
                )
            _fields(obj, {variant, "messages", "hasSorry", "hasUnsafe"})
            has_sorry = _bool(obj["hasSorry"], "hasSorry")
            has_unsafe = _bool(obj["hasUnsafe"], "hasUnsafe")
            if has_sorry or has_unsafe:
                raise PantographProtocolError(
                    "Failed tactic operations must carry false proof flags."
                )
            messages = decode_messages(obj["messages"])
            if variant == "parseError":
                return TacticParseFailure(
                    _string(obj[variant], variant, nonempty=True), messages
                )
            errors = tuple(
                _string(item, "tactic error", nonempty=True)
                for item in _array(obj[variant], variant)
            )
            if not errors:
                raise PantographProtocolError(
                    "tacticErrors must contain at least one error."
                )
            return TacticFailure(errors, messages)
        if command == "goal.inspect":
            _fields(obj, {"obligations"})
            return InspectionResult(
                tuple(
                    decode_obligation(item)
                    for item in _array(obj["obligations"], "obligations")
                )
            )
        if command == "goal.certify":
            return decode_certificate(obj)
        if command == "stat":
            _fields(obj, {"nGoals"})
            return PantographStats(_nat(obj["nGoals"], "nGoals"))
        if command in {"goal.delete", "options.set"}:
            _fields(obj, set())
            return CommandAcknowledgement(command)
        if command == "protocol.describe":
            _fields(obj, frozenset(PROTOCOL_DESCRIPTION))
            for key, expected in PROTOCOL_DESCRIPTION.items():
                value = (
                    _nat(obj[key], key)
                    if type(expected) is int
                    else _string(obj[key], key)
                )
                if value != expected:
                    raise PantographProtocolError(
                        f"Unsupported protocol descriptor {key}={value!r}; expected {expected!r}."
                    )
            return ProtocolDescription(
                obj["protocol"],
                obj["protocolVersion"],
                obj["modelSexpVersion"],
                obj["transitionValidationVersion"],
                obj["transitionProvenanceVersion"],
                obj["inspectionVersion"],
                obj["certificationVersion"],
                obj["messageVersion"],
                obj["goalSelection"],
                obj["tacticErrorsFormat"],
            )
        _fields(obj, OPTION_NAMES)
        for key in OPTION_NAMES:
            _bool(obj[key], key)
            if key in REQUIRED_OPTIONS and obj[key] is not REQUIRED_OPTIONS[key]:
                raise PantographProtocolError(
                    f"Effective option {key} conflicts with the execution contract."
                )
        return SessionOptions(tuple(sorted(obj.items())))
    except PantographProtocolError as exc:
        # Decoder helpers know the field; the envelope supplies command context.
        raise PantographProtocolError(
            str(exc), command=command, payload=payload
        ) from exc
