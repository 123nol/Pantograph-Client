"""Pure revision-3 contract tests; no Lean process or PyPantograph import."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import subprocess
import sys

import pytest

from pantograph_async.protocol import (
    COMMAND_ERROR_CATEGORIES,
    PROTOCOL_DESCRIPTION,
    REQUIRED_OPTIONS,
    CommandAcknowledgement,
    CommandError,
    GoalStartResult,
    PantographError,
    PantographConfigurationError,
    PantographGoalRejected,
    PantographProtocolError,
    PantographRequestTimeout,
    PantographStateError,
    PantographStats,
    PantographTransportError,
    ProtocolDescription,
    SessionOptions,
    StartedGoal,
    StateHandle,
    TacticFailure,
    TacticParseFailure,
    TacticState,
    TacticSuccess,
    decode_execution_goal,
    decode_json_response,
    decode_messages,
    decode_response,
    encode_request,
)
from pantograph_async import compatibility


FIXTURES = Path(__file__).parent / "fixtures"
BASELINE = json.loads((FIXTURES / "baseline" / "baseline.json").read_text())
CAPTURES = {entry["label"]: entry for entry in BASELINE["interactions"]}
FUTURE = json.loads((FIXTURES / "future_contract.json").read_text())
UPSTREAM = json.loads((FIXTURES / "upstream_pr1" / "capture.json").read_text())
UPSTREAM_CAPTURES = {entry["label"]: entry for entry in UPSTREAM["interactions"]}


def success(name="identity_intro"):
    return deepcopy(FUTURE["successes"][name])


def test_protocol_import_is_independent_of_upstream_and_models():
    # A fresh interpreter makes this independent of pytest's import order.
    code = """
import importlib.abc
import sys
class ForbiddenImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"pantograph", "torch", "maths_ai", "pydantic"}:
            raise AssertionError("Forbidden dependency: " + fullname)
sys.meta_path.insert(0, ForbiddenImports())
from pantograph_async.protocol import decode_response
assert decode_response("goal.start", {"stateId": 0, "root": "g"}).state_id == 0
assert not any(name.split(".")[0] in {"pantograph", "torch", "maths_ai"} for name in sys.modules)
"""
    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )


@pytest.mark.parametrize(
    "raw",
    [
        '{"stateId":0,"stateId":1}',
        '{"x":{"a":1,"a":2}}',
        '{"x":NaN}',
        '{"x":Infinity}',
        '{"x":-Infinity}',
        "[]",
        "null",
        "ready.",
        "{",
        "{} {}",
        b"\xff",
    ],
)
def test_reject_malformed_json(raw):
    with pytest.raises(PantographProtocolError):
        decode_json_response(raw)


def test_request_framing_preserves_unicode_and_escaped_source():
    tactic = 'have h : α = α := by\n  trace "quoted"\n  rfl'
    raw = encode_request("goal.tactic", {"stateId": 0, "goalId": 2, "tactic": tactic})
    assert raw.count(b"\n") == 1 and raw.endswith(b"\n")
    assert raw.startswith(b'goal.tactic {"stateId":0,"goalId":2,')
    assert "α".encode() in raw
    assert json.loads(raw.decode().split(" ", 1)[1])["tactic"] == tactic
    assert decode_json_response('{"root":"α","stateId":0}\n')["root"] == "α"


@pytest.mark.parametrize(
    "command,payload",
    [
        ("goal.tactic", {"stateId": 0, "tactic": "skip"}),
        ("goal.tactic", {"stateId": True, "goalId": 0, "tactic": "skip"}),
        ("goal.tactic", {"stateId": 0, "goalId": -1, "tactic": "skip"}),
        ("goal.tactic", {"stateId": 0, "goalId": False, "tactic": "skip"}),
        ("goal.tactic", {"stateId": 0, "goalId": 0, "tactic": None}),
        ("goal.start", {"expr": "True", "copyFrom": "Nat.add_comm"}),
        ("goal.start", {"expr": ""}),
        ("goal.start", {"expr": "True", "levels": "u"}),
        ("goal.start", {"expr": "True", "levels": []}),
        ("goal.start", {"expr": "True", "levels": ["u", "u"]}),
        ("goal.start", {"expr": "True", "levels": [""]}),
        ("goal.start", {"expr": "True", "levels": [1]}),
        ("goal.start", {"expr": "True", "levels": ["Foo.u"]}),
        ("goal.start", {"expr": "True", "levels": ["u₁"]}),
        ("goal.start", {"expr": "True", "levels": ["1u"]}),
        ("goal.start", {"expr": "True", "levels": ["max"]}),
        ("goal.start", {"expr": "True", "levels": ["_"]}),
        ("goal.delete", {"stateIds": [False]}),
        ("stat", {"unused": 1}),
        ("options.set", {"printExprAST": 1}),
    ],
)
def test_request_shape_is_strict(command, payload):
    with pytest.raises(PantographProtocolError):
        encode_request(command, payload)


def test_goal_start_levels_are_sent_only_when_declared():
    assert encode_request("goal.start", {"expr": "True"}) == (
        b'goal.start {"expr":"True"}\n'
    )
    assert encode_request(
        "goal.start", {"expr": "Sort u_1 → Type v", "levels": ["u_1", "v", "w'"]}
    ) == 'goal.start {"expr":"Sort u_1 → Type v","levels":["u_1","v","w\'"]}\n'.encode()


def test_request_options_and_deletions():
    for key, value in REQUIRED_OPTIONS.items():
        with pytest.raises(PantographConfigurationError):
            encode_request("options.set", {key: not value})
    with pytest.raises(PantographStateError):
        encode_request("goal.delete", {"stateIds": [0, 0]})
    with pytest.raises(PantographConfigurationError):
        encode_request("goal.print", {})
    assert (
        encode_request("goal.delete", {"stateIds": [0, 1]})
        == b'goal.delete {"stateIds":[0,1]}\n'
    )


@pytest.mark.parametrize("state_id", [0, 17])
def test_goal_start_does_not_fabricate_solved_goals(state_id):
    response = decode_response("goal.start", {"stateId": state_id, "root": "g"})
    assert response == GoalStartResult(state_id, "g")
    state = StartedGoal(
        StateHandle("session", "scope", response.state_id), response.root
    )
    assert not hasattr(state, "goals")
    with pytest.raises(FrozenInstanceError):
        state.root = "changed"


@pytest.mark.parametrize("value", [True, False, -1, 0.0, "0", None])
@pytest.mark.parametrize(
    "command,field",
    [("goal.start", "stateId"), ("goal.tactic", "nextStateId"), ("stat", "nGoals")],
)
def test_integer_fields_reject_booleans_and_invalid_ids(value, command, field):
    payload = (
        {"stateId": 0, "root": "g"}
        if command == "goal.start"
        else success() if command == "goal.tactic" else {"nGoals": 0}
    )
    payload[field] = value
    with pytest.raises(PantographProtocolError) as exc:
        decode_response(command, payload)
    assert exc.value.command == command
    assert exc.value.payload == payload
    assert exc.value.__cause__ is not None


def test_all_response_variants():
    assert isinstance(
        decode_response("protocol.describe", FUTURE["descriptor"]), ProtocolDescription
    )
    assert isinstance(decode_response("goal.tactic", success()), TacticSuccess)
    assert isinstance(
        decode_response("goal.tactic", FUTURE["parse_failure"]), TacticParseFailure
    )
    assert isinstance(
        decode_response("goal.tactic", FUTURE["tactic_failure"]), TacticFailure
    )
    assert isinstance(
        decode_response("goal.tactic", FUTURE["logged_error_failure"]), TacticFailure
    )
    assert decode_response("goal.delete", {}) == CommandAcknowledgement("goal.delete")
    assert decode_response("options.set", {}) == CommandAcknowledgement("options.set")
    assert decode_response("stat", {"nGoals": 0}) == PantographStats(0)
    options = decode_response("options.print", CAPTURES["options_print"]["response"])
    assert isinstance(options, SessionOptions)
    assert options.to_dict() == CAPTURES["options_print"]["response"]


@pytest.mark.parametrize("key", list(PROTOCOL_DESCRIPTION))
def test_descriptor_versions_and_identity_are_exact(key):
    descriptor = deepcopy(FUTURE["descriptor"])
    del descriptor[key]
    with pytest.raises(PantographProtocolError):
        decode_response("protocol.describe", descriptor)
    descriptor[key] = True if type(PROTOCOL_DESCRIPTION[key]) is int else "incompatible"
    with pytest.raises(PantographProtocolError):
        decode_response("protocol.describe", descriptor)


@pytest.mark.parametrize("command,categories", list(COMMAND_ERROR_CATEGORIES.items()))
def test_error_categories_are_known_per_command(command, categories):
    for category in categories:
        response = decode_response(command, {"error": category, "desc": "detail"})
        assert isinstance(response, CommandError)
        exc = response.as_exception()
        assert isinstance(exc, PantographError)
        assert exc.command == command and exc.payload == {
            "error": category,
            "desc": "detail",
        }
    with pytest.raises(PantographProtocolError):
        decode_response(command, {"error": "unknown", "desc": "detail"})


@pytest.mark.parametrize(
    "label",
    [
        "goal_parse_error",
        "goal_elab_error",
        "invalid_state",
        "invalid_goal",
        "missing_goal_id",
        "unsupported_descriptor",
    ],
)
def test_captured_error_mapping(label):
    capture = CAPTURES[label]
    response = decode_response(capture["command"], capture["response"])
    expected = (
        PantographGoalRejected
        if label.startswith("goal_")
        else (
            PantographStateError
            if label.startswith("invalid_")
            else PantographProtocolError
        )
    )
    assert isinstance(response.as_exception(), expected)


def test_timeout_is_distinct_from_domain_failure():
    assert issubclass(PantographRequestTimeout, PantographTransportError)
    assert not issubclass(PantographTransportError, PantographGoalRejected)


@pytest.mark.parametrize(
    "label",
    [
        entry["label"]
        for entry in BASELINE["interactions"]
        if entry["command"] == "goal.tactic" and "error" not in entry["response"]
    ],
)
def test_every_baseline_tactic_response_is_rejected(label):
    # Even valid old successes lack required evidence. Failures lack diagnostics.
    with pytest.raises(PantographProtocolError):
        decode_response("goal.tactic", CAPTURES[label]["response"])


@pytest.mark.parametrize(
    "change",
    [
        {"parseError": "failure"},
        {"tacticErrors": ["failure"]},
        {"error": "index", "desc": "bad"},
        {"goals": None},
        {"goals": {}},
        {"messages": None},
        {"validation": None},
        {"fragment": "tactic"},
        {"hasSorry": None},
    ],
)
def test_mixed_and_unknown_tactic_variants_are_rejected(change):
    payload = success()
    payload.update(change)
    with pytest.raises(PantographProtocolError):
        decode_response("goal.tactic", payload)


@pytest.mark.parametrize("field", ["version", "scope", "checked"])
def test_validation_fields_are_required(field):
    payload = success()
    del payload["validation"][field]
    with pytest.raises(PantographProtocolError):
        decode_response("goal.tactic", payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", True),
        ("version", 2),
        ("scope", "root-proof"),
        ("checked", False),
        ("checked", 1),
    ],
)
def test_validation_evidence_is_strict(field, value):
    payload = success()
    payload["validation"][field] = value
    with pytest.raises(PantographProtocolError):
        decode_response("goal.tactic", payload)


@pytest.mark.parametrize(
    "name,flag", [("admission", "has_sorry"), ("unsafe", "has_unsafe")]
)
def test_positive_evidence_retains_allocation_for_later_release(name, flag):
    result = decode_response("goal.tactic", success(name))
    assert isinstance(result, TacticSuccess)
    assert getattr(result.validation, flag) is True
    assert result.validation.is_rejection
    assert result.next_state_id == FUTURE["successes"][name]["nextStateId"]


def test_message_positions_and_warning_preservation():
    result = decode_response("goal.tactic", FUTURE["warning_success"])
    message = result.messages[0]
    assert (message.pos.line, message.pos.column) == (2, 0)
    assert (message.end_pos.line, message.end_pos.column) == (2, 4)
    assert message.kind == "example" and message.pos.is_available
    assert message.severity == "warning"
    payload = success()
    payload["messages"] = [
        {
            "kind": "[anonymous]",
            "severity": "error",
            "data": "logged error",
            "pos": {"line": 0, "column": 0},
        }
    ]
    with pytest.raises(PantographProtocolError):
        decode_response("goal.tactic", payload)
    info = decode_messages(
        [
            {
                "kind": "[anonymous]",
                "severity": "information",
                "data": "info",
                "pos": {"line": 0, "column": 0},
            }
        ]
    )[0]
    assert (info.pos.line, info.pos.column) == (0, 0)
    assert not info.pos.is_available


@pytest.mark.parametrize(
    "change",
    [
        {"severity": "info", "data": "bad"},
        {"severity": "error", "data": 0},
        {"severity": "warning", "data": "bad", "pos": None},
        {"severity": "warning", "data": "bad", "pos": {"line": 0, "column": 1}},
        {"severity": "warning", "data": "bad", "pos": {"line": True, "column": 0}},
        {
            "severity": "warning",
            "data": "bad",
            "pos": {"line": 0, "column": 0},
            "endPos": {"line": 1, "column": 0},
        },
        {
            "severity": "warning",
            "data": "bad",
            "pos": {"line": 2, "column": 0},
            "endPos": {"line": 1, "column": 0},
        },
    ],
)
def test_message_schema_is_strict(change):
    message = {
        "kind": "[anonymous]",
        "severity": "warning",
        "data": "text",
        "pos": {"line": 1, "column": 0},
    }
    message.update(change)
    with pytest.raises(PantographProtocolError):
        decode_messages([message])


@pytest.mark.parametrize("variant", ["parseError", "tacticErrors"])
@pytest.mark.parametrize("bad", [None, False, 0, {}, [], ""])
def test_failure_payloads_are_not_empty_or_wrong_type(variant, bad):
    payload = {variant: bad, "messages": [], "hasSorry": False, "hasUnsafe": False}
    # Nonempty strings only for parseError; nonempty string arrays for tacticErrors.
    with pytest.raises(PantographProtocolError):
        decode_response("goal.tactic", payload)


def test_goals_keep_order_case_tags_and_conversion_metadata():
    result = decode_response("goal.tactic", success("conjunction_split"))
    wire = FUTURE["successes"]["conjunction_split"]["goals"]
    assert [goal.goal_name for goal in result.goals] == [goal["name"] for goal in wire]
    assert [goal.case_tag for goal in result.goals] == ["left", "right"]
    goal_payload = deepcopy(wire[0])
    goal_payload["isConversion"] = True
    goal_payload["fragment"] = "conv"
    decoded = decode_execution_goal(goal_payload)
    assert decoded.is_conversion is True
    assert decoded.fragment == "conv"
    assert decoded.case_tag == "left"


def test_locals_preserve_instances_lets_and_raw_views():
    instance = decode_response("goal.tactic", success("instance_intro")).goals[0]
    assert [local.context_index for local in instance.locals] == [0, 1, 2]
    assert instance.locals[1].is_instance is True
    assert instance.locals[1].binder_role == ":instance-implicit"
    let_goal = decode_response("goal.tactic", success("let_intro")).goals[0]
    assert let_goal.locals[1].is_let is True
    assert let_goal.locals[1].value.pp == "n"
    assert let_goal.locals[1].value.model_sexp == "(:fv FV0)"
    assert let_goal.fragment == "tactic"
    assert let_goal.target.sexp != let_goal.target.model_sexp
    assert let_goal.locals[0].type.pp == "ℕ"
    with pytest.raises(FrozenInstanceError):
        let_goal.locals[0].user_name = "changed"


def test_context_gaps_are_not_renumbered():
    payload = success("instance_intro")["goals"][0]
    del payload["vars"][1]
    goal = decode_execution_goal(payload)
    assert [local.context_index for local in goal.locals] == [0, 2]
    assert "FV2" in goal.target.model_sexp


@pytest.mark.parametrize("role", [":explicit", ":implicit", ":strict-implicit"])
def test_supported_declaration_binder_roles(role):
    payload = success()["goals"][0]
    payload["vars"][0]["binderRole"] = role
    assert decode_execution_goal(payload).locals[0].binder_role == role


@pytest.mark.parametrize(
    "field,value",
    [
        ("contextIndex", True),
        ("contextIndex", -1),
        ("contextIndex", 0.5),
        ("binderRole", ":instImplicit"),
        ("isInstance", "false"),
        ("isLet", 0),
        ("isInaccessible", None),
        ("type", {"pp": "Prop"}),
        ("value", {"pp": "unexpected"}),
    ],
)
def test_local_schema_is_strict(field, value):
    payload = success()["goals"][0]
    payload["vars"][0][field] = value
    with pytest.raises(PantographProtocolError):
        decode_execution_goal(payload)


def test_missing_let_value_and_metadata_are_rejected():
    for field in ("value", "isLet", "contextIndex", "binderRole", "isInstance"):
        payload = success("let_intro")["goals"][0]
        del payload["vars"][1][field]
        with pytest.raises(PantographProtocolError):
            decode_execution_goal(payload)


@pytest.mark.parametrize("indices", [[0, 0], [1, 0]])
def test_duplicate_and_reordered_context_indices_are_rejected(indices):
    payload = success()["goals"][0]
    for local, index in zip(payload["vars"], indices):
        local["contextIndex"] = index
    with pytest.raises(PantographProtocolError):
        decode_execution_goal(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("modelSexpVersion", True),
        ("modelSexpVersion", 2),
        ("modelSexp", ""),
        ("sexp", None),
        ("pp", None),
    ],
)
def test_expression_views_and_versions_are_required(field, value):
    for location in ("target", "type", "value"):
        payload = success("let_intro")["goals"][0]
        expr = (
            payload["target"] if location == "target" else payload["vars"][1][location]
        )
        expr[field] = value
        with pytest.raises(PantographProtocolError):
            decode_execution_goal(payload)


def test_only_known_optional_expression_diagnostics_are_allowed():
    payload = success()["goals"][0]
    payload["target"]["dependentMVars"] = ["g2"]
    assert decode_execution_goal(payload).target.dependent_mvars == ("g2",)
    payload["target"]["inventedDiagnostic"] = []
    with pytest.raises(PantographProtocolError):
        decode_execution_goal(payload)


def test_immutable_containers():
    result = decode_response("goal.tactic", success())
    state = TacticState(
        StateHandle("session", "scope", result.next_state_id),
        result.goals,
        result.validation,
        result.messages,
        result.transition,
    )
    with pytest.raises(FrozenInstanceError):
        result.next_state_id = 5
    with pytest.raises(FrozenInstanceError):
        result.goals[0].target.pp = "changed"
    assert state.goals is result.goals
    for bad in (True, -1, "0"):
        with pytest.raises(PantographStateError):
            StateHandle("session", "scope", bad)


def test_baseline_evidence_is_not_final_contract_evidence():
    assert BASELINE["kind"] == "unmodified-custom-repl-baseline"
    assert FUTURE["kind"] == "authored-future-contract"
    assert FUTURE["contract_revision"] == 3
    assert BASELINE["readiness_line"] == "ready."
    for entry in BASELINE["interactions"]:
        assert json.loads(entry["response_line"]) == entry["response"]
    for label in ("admission_unchecked", "logged_error_unchecked"):
        assert CAPTURES[label]["response"]["goals"] == []
        assert "validation" not in CAPTURES[label]["response"]
    assert CAPTURES["focused_all_goals"]["response"]["goals"]
    assert CAPTURES["identity_after_parent_delete"]["response"]["goals"] == []
    assert CAPTURES["identity_alternative"]["response"]["goals"] == []
    assert (
        CAPTURES["initial_stat"]["response"]
        == CAPTURES["final_stat"]["response"]
        == {"nGoals": 0}
    )


def test_frozen_contract_descriptor_matches_the_codec():
    contract = compatibility.contract()
    assert contract["descriptor"] == dict(PROTOCOL_DESCRIPTION)
    assert contract["required_options"] == dict(REQUIRED_OPTIONS)
    assert {name: set(codes) for name, codes in contract["commands"].items()} == dict(
        COMMAND_ERROR_CATEGORIES
    )
    assert contract["complete_theorem_certification"] is True
    assert contract["contract_revision"] == FUTURE["contract_revision"] == 3
    assert contract["transition_validation"] == success()["validation"]
    assert set(contract["tactic_responses"]["success"]["required"]) == set(success())
    for variant, fixture in [
        ("parse_failure", "parse_failure"),
        ("tactic_failure", "tactic_failure"),
    ]:
        assert set(contract["tactic_responses"][variant]["required"]) == set(
            FUTURE[fixture]
        )
    message = FUTURE["parse_failure"]["messages"][0]
    assert set(message) == set(contract["message_schema"]["required"])
    assert set(FUTURE["warning_success"]["messages"][0]) == set(
        contract["message_schema"]["required"] + contract["message_schema"]["optional"]
    )
    assert set(success()["goals"][0]) == set(contract["goal_schema"]["required"])


def test_goal_names_and_omitted_case_names_are_not_interchangeable():
    payload = success()
    assert "userName" not in payload["goals"][0]
    goal = decode_response("goal.tactic", payload).goals[0]
    assert goal.case_tag is None
    assert goal.goal_name != ""
    payload["goals"].append(deepcopy(payload["goals"][0]))
    with pytest.raises(PantographProtocolError):
        decode_response("goal.tactic", payload)


def test_errors_keep_independent_payload_snapshots():
    payload = success()
    payload["validation"]["checked"] = False
    with pytest.raises(PantographProtocolError) as failure:
        decode_response("goal.tactic", payload)
    payload["validation"]["checked"] = True
    assert failure.value.payload["validation"]["checked"] is False
    copied = failure.value.payload
    copied["validation"]["checked"] = True
    assert failure.value.payload["validation"]["checked"] is False


@pytest.mark.parametrize("flag", ["hasSorry", "hasUnsafe"])
@pytest.mark.parametrize("bad", [None, 0, 1, "false", [], {}])
def test_top_level_proof_flags_require_booleans(flag, bad):
    payload = success()
    payload[flag] = bad
    with pytest.raises(PantographProtocolError):
        decode_response("goal.tactic", payload)


@pytest.mark.parametrize("flag", ["hasSorry", "hasUnsafe"])
def test_proof_flags_are_required_at_top_level_without_nested_duplicates(flag):
    payload = success()
    del payload[flag]
    with pytest.raises(PantographProtocolError):
        decode_response("goal.tactic", payload)
    payload["validation"][flag] = False
    with pytest.raises(PantographProtocolError):
        decode_response("goal.tactic", payload)
    payload[flag] = False
    with pytest.raises(PantographProtocolError):
        decode_response("goal.tactic", payload)


@pytest.mark.parametrize("variant", ["parse_failure", "tactic_failure"])
@pytest.mark.parametrize("flag", ["hasSorry", "hasUnsafe"])
@pytest.mark.parametrize("bad", [True, None, 0, "false"])
def test_failed_operations_require_false_boolean_proof_flags(variant, flag, bad):
    payload = deepcopy(FUTURE[variant])
    payload[flag] = bad
    with pytest.raises(PantographProtocolError):
        decode_response("goal.tactic", payload)


@pytest.mark.parametrize("variant", ["parse_failure", "tactic_failure"])
@pytest.mark.parametrize("flag", ["hasSorry", "hasUnsafe"])
def test_failed_operations_require_both_proof_flags(variant, flag):
    payload = deepcopy(FUTURE[variant])
    del payload[flag]
    with pytest.raises(PantographProtocolError):
        decode_response("goal.tactic", payload)


@pytest.mark.parametrize("field", ["kind", "severity", "pos", "data"])
def test_all_merged_message_fields_are_required(field):
    message = deepcopy(FUTURE["parse_failure"]["messages"][0])
    del message[field]
    with pytest.raises(PantographProtocolError):
        decode_messages([message])


@pytest.mark.parametrize("field", ["kind", "data", "pos", "endPos"])
def test_null_message_fields_are_not_supported(field):
    message = deepcopy(FUTURE["warning_success"]["messages"][0])
    message[field] = None
    with pytest.raises(PantographProtocolError):
        decode_messages([message])


def test_removed_message_file_name_is_not_a_compatibility_field():
    message = deepcopy(FUTURE["warning_success"]["messages"][0])
    message["fileName"] = "<Pantograph>"
    with pytest.raises(PantographProtocolError):
        decode_messages([message])


@pytest.mark.parametrize(
    "position",
    [
        {"line": 0, "column": 2},
        {"line": -1, "column": 0},
        {"line": 1, "column": -1},
        {"line": False, "column": 0},
        {"line": 1, "column": True},
        {"line": 1.0, "column": 0},
        {"line": 1, "column": "0"},
    ],
)
def test_message_position_rejects_malformed_coordinates(position):
    message = deepcopy(FUTURE["parse_failure"]["messages"][0])
    message["pos"] = position
    with pytest.raises(PantographProtocolError):
        decode_messages([message])


@pytest.mark.parametrize(
    "end",
    [{"line": 0, "column": 0}, {"line": 1, "column": 0}, {"line": 2, "column": 1}],
)
def test_message_end_requires_known_ordered_start(end):
    message = deepcopy(FUTURE["warning_success"]["messages"][0])
    message["pos"] = {"line": 2, "column": 2}
    message["endPos"] = end
    with pytest.raises(PantographProtocolError):
        decode_messages([message])


def test_equal_known_message_start_and_end_are_valid():
    message = deepcopy(FUTURE["warning_success"]["messages"][0])
    message["endPos"] = deepcopy(message["pos"])
    decoded = decode_messages([message])[0]
    assert decoded.pos == decoded.end_pos
    assert decoded.pos.is_available
    with pytest.raises(FrozenInstanceError):
        decoded.pos.line = 0


@pytest.mark.parametrize("field", ["fragment", "isConversion"])
def test_goal_mode_fields_are_required(field):
    payload = success()["goals"][0]
    del payload[field]
    with pytest.raises(PantographProtocolError):
        decode_execution_goal(payload)


@pytest.mark.parametrize("fragment", [None, False, 0, "unknown", "", "conversion"])
def test_goal_fragments_are_strict(fragment):
    payload = success()["goals"][0]
    payload["fragment"] = fragment
    with pytest.raises(PantographProtocolError):
        decode_execution_goal(payload)


@pytest.mark.parametrize(
    "fragment,is_conversion",
    [("tactic", True), ("calc", True), ("conv", False), ("conv", 1)],
)
def test_fragment_and_conversion_must_agree(fragment, is_conversion):
    payload = success()["goals"][0]
    payload.update(fragment=fragment, isConversion=is_conversion)
    with pytest.raises(PantographProtocolError):
        decode_execution_goal(payload)


@pytest.mark.parametrize("fragment", ["tactic", "conv", "calc"])
def test_fragment_is_immutable_execution_metadata(fragment):
    payload = success()["goals"][0]
    expected = decode_execution_goal(payload).target
    payload.update(fragment=fragment, isConversion=(fragment == "conv"))
    goal = decode_execution_goal(payload)
    assert goal.fragment == fragment
    assert goal.target == expected
    with pytest.raises(FrozenInstanceError):
        goal.fragment = "other"


@pytest.mark.parametrize(
    "label",
    [
        entry["label"]
        for entry in UPSTREAM["interactions"]
        if "nextStateId" in entry["response"]
    ],
)
def test_upstream_success_requires_the_missing_companion_metadata(label):
    with pytest.raises(PantographProtocolError) as exc:
        decode_response("goal.tactic", UPSTREAM_CAPTURES[label]["response"])
    assert "validation" in str(exc.value)


@pytest.mark.parametrize(
    "label,expected",
    [("parse_failure", TacticParseFailure), ("tactic_failure", TacticFailure)],
)
def test_merged_failure_messages_decode_without_fabricating_proof_evidence(
    label, expected
):
    result = decode_response("goal.tactic", UPSTREAM_CAPTURES[label]["response"])
    assert isinstance(result, expected)
    assert result.messages[0].kind == "[anonymous]"
    assert not result.messages[0].pos.is_available
    assert not hasattr(result, "validation")
    assert not hasattr(result, "next_state_id")


def test_historical_revision1_fixture_is_preserved_but_not_accepted():
    historical = json.loads(
        (FIXTURES / "historical_revision1" / "future_contract.json").read_text()
    )
    for payload in historical["successes"].values():
        with pytest.raises(PantographProtocolError):
            decode_response("goal.tactic", payload)
    for name in [
        "parse_failure",
        "tactic_failure",
        "logged_error_failure",
        "warning_success",
    ]:
        with pytest.raises(PantographProtocolError):
            decode_response("goal.tactic", historical[name])


def test_historical_revision2_fixture_is_preserved_but_not_accepted():
    historical = json.loads(
        (FIXTURES / "historical_revision2" / "future_contract.json").read_text()
    )
    for payload in historical["successes"].values():
        with pytest.raises(PantographProtocolError, match="transition"):
            decode_response("goal.tactic", payload)
    with pytest.raises(PantographProtocolError):
        decode_response("protocol.describe", historical["descriptor"])


def test_stage4_companion_capture_is_preserved_but_not_accepted():
    capture = json.loads((FIXTURES / "stage4_companion" / "capture.json").read_text())
    assert capture["subprocess_reaped"] is True
    for entry in capture["interactions"]:
        assert decode_json_response(entry["response_line"]) == entry["response"]
        if entry["command"] == "protocol.describe" or "nextStateId" in entry["response"]:
            with pytest.raises(PantographProtocolError):
                decode_response(entry["command"], entry["response"])


def test_snapshot_companion_capture_decodes_completely():
    capture = json.loads((FIXTURES / "snapshot_companion" / "capture.json").read_text())
    assert capture["subprocess_reaped"] is True
    decoded = {}
    for entry in capture["interactions"]:
        assert decode_json_response(entry["response_line"]) == entry["response"]
        decoded[entry["label"]] = decode_response(entry["command"], entry["response"])
    assert decoded["certificate"].is_certified
    assert decoded["partial_certificate"].status == "incomplete"
    assert "Classical.choice" in decoded["classical_certificate"].receipt.axioms
    assert decoded["shared_assignment"].transition.changed
    assert [item.status for item in decoded["witness_inspection"].obligations] == [
        "complete",
        "complete",
        "active",
    ]
    for label in ("unknown_obligation", "unknown_state"):
        assert isinstance(decoded[label].as_exception(), PantographStateError)


def provenance(payload=None, **changes):
    payload = deepcopy(payload or success("conjunction_split"))
    payload["transition"].update(changes)
    return payload


def test_transition_provenance_decodes_and_partitions_the_goals():
    result = decode_response("goal.tactic", provenance())
    names = tuple(goal.goal_name for goal in result.goals)
    assert result.transition.direct == names
    assert result.transition.introduced == ((), ())
    assert result.transition.selected == "_selected"


@pytest.mark.parametrize(
    "changes",
    [
        {"direct": ["_uniq.22"]},
        {"direct": ["_uniq.22", "_uniq.23"], "siblings": ["_uniq.23"]},
        {"direct": ["_uniq.22", "_uniq.23", "_uniq.24"]},
        {"direct": ["_uniq.22", "_uniq.22", "_uniq.23"]},
        {"selected": "_uniq.22", "direct": ["_uniq.23"], "extra": ["_uniq.22"], "introduced": [[]]},
        {"closed": ["_uniq.23"]},
        {"closed": ["_selected"]},
        {"closed": ["_uniq.5"], "dormant": ["_uniq.5"]},
        {"changed": ["_uniq.22"]},
        {"introduced": [[]]},
        {"introduced": [["_uniq.8"], []]},
        {"version": 2},
        {"selected": ""},
    ],
)
def test_inconsistent_provenance_is_rejected(changes):
    with pytest.raises(PantographProtocolError):
        decode_response("goal.tactic", provenance(**changes))


def test_a_goal_left_open_is_its_own_direct_goal():
    payload = provenance(selected="_uniq.22")
    result = decode_response("goal.tactic", payload)
    assert result.transition.selected in result.transition.direct


def test_success_without_provenance_is_rejected():
    payload = success()
    payload.pop("transition")
    with pytest.raises(PantographProtocolError, match="transition"):
        decode_response("goal.tactic", payload)


def obligation(**changes):
    value = {"name": "_uniq.12", "status": "complete", "holes": [], "universeHoles": False}
    value.update(changes)
    return value


def test_inspection_decodes_each_status():
    goal = success()["goals"][0]
    result = decode_response(
        "goal.inspect",
        {
            "obligations": [
                obligation(status="active", goal=goal),
                obligation(name="_uniq.3", status="assigned", holes=["_uniq.4"]),
                obligation(name="_uniq.5", status="delayed", universeHoles=True, holes=[]),
                obligation(name="_uniq.6"),
            ]
        },
    )
    active, assigned, delayed, complete = result.obligations
    assert active.goal.goal_name == "_uniq.12" and not active.is_complete
    assert assigned.holes == ("_uniq.4",) and delayed.universe_holes
    assert complete.is_complete and complete.goal is None


@pytest.mark.parametrize(
    "item",
    [
        obligation(status="active"),
        obligation(goal=success()["goals"][0]),
        obligation(status="pending", goal={**success()["goals"][0], "name": "_uniq.1"}),
        obligation(holes=["_uniq.4"]),
        obligation(universeHoles=True),
        obligation(status="assigned"),
        obligation(status="solved"),
        obligation(holes=["_uniq.4", "_uniq.4"], status="assigned"),
    ],
)
def test_inconsistent_inspection_is_rejected(item):
    with pytest.raises(PantographProtocolError):
        decode_response("goal.inspect", {"obligations": [item]})


def test_certificates_decode_and_carry_exactly_one_explanation():
    certified = decode_response("goal.certify", deepcopy(FUTURE["certified"]))
    assert certified.is_certified and certified.reason is None
    assert certified.receipt.identity == "lean-expr-digest-v1"
    incomplete = decode_response("goal.certify", deepcopy(FUTURE["incomplete"]))
    assert not incomplete.is_certified and incomplete.receipt is None
    for status in ("rejected", "inconclusive"):
        result = decode_response(
            "goal.certify", {"version": 1, "status": status, "reason": "why"}
        )
        assert result.status == status and not result.is_certified


def receipt(**changes):
    payload = deepcopy(FUTURE["certified"])
    payload["receipt"].update(changes)
    return payload


@pytest.mark.parametrize(
    "payload",
    [
        {"version": 1, "status": "certified"},
        {**deepcopy(FUTURE["certified"]), "reason": "both"},
        {"version": 1, "status": "incomplete"},
        {**deepcopy(FUTURE["incomplete"]), "receipt": FUTURE["certified"]["receipt"]},
        {"version": 1, "status": "proved", "reason": "x"},
        {"version": 2, "status": "incomplete", "reason": "x"},
        {"version": 1, "status": "rejected", "reason": ""},
        receipt(identity="lean-expr-hash-v1"),
        receipt(proof="00a1"),
        receipt(rootType="00000000000000A1"),
        receipt(levels=["Foo.u"]),
        receipt(axioms=["propext", "propext"]),
        receipt(version=2),
    ],
)
def test_malformed_certificates_are_rejected(payload):
    with pytest.raises(PantographProtocolError):
        decode_response("goal.certify", payload)


@pytest.mark.parametrize(
    "command,payload",
    [
        ("goal.inspect", {"stateId": 0, "goals": []}),
        ("goal.inspect", {"stateId": 0, "goals": ["a", "a"]}),
        ("goal.inspect", {"stateId": 0, "goals": [""]}),
        ("goal.inspect", {"stateId": 0}),
        ("goal.certify", {"stateId": 0, "maxHeartbeats": 0}),
        ("goal.certify", {"stateId": 0, "maxHeartbeats": True}),
        ("goal.certify", {"stateId": 0, "type": "False"}),
    ],
)
def test_invalid_snapshot_requests_are_rejected_before_sending(command, payload):
    with pytest.raises((PantographProtocolError, PantographConfigurationError)):
        encode_request(command, payload)


def test_snapshot_requests_encode_canonically():
    assert encode_request("goal.inspect", {"stateId": 3, "goals": ["_uniq.1"]}) == (
        b'goal.inspect {"stateId":3,"goals":["_uniq.1"]}\n'
    )
    assert encode_request("goal.certify", {"stateId": 3}) == (
        b'goal.certify {"stateId":3}\n'
    )
