"""Actual custom REPL gate; no fake child and no consumer project.

Run with explicit paths and ``--run-pantograph-live`` so missing resources fail
instead of skipping. Imports default to ``Init,Lean``; the metaprogram checks
need ``Lean`` (or anything importing it, such as Mathlib):

    PANTOGRAPH_TEST_SOURCE_ROOT=... PANTOGRAPH_TEST_REPL=... \
        python -m pytest tests/test_client_live.py --run-pantograph-live
"""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from dataclasses import replace

from pantograph_async import (
    PantographClient,
    PantographEnv,
    PantographGoalRejected,
    PantographProtocolError,
    PantographTacticRejected,
)
from pantograph_async.diagnostics import METAPROGRAM_CHECKS, verify_live_client


@pytest.fixture
def live_env(request):
    source = os.environ.get("PANTOGRAPH_TEST_SOURCE_ROOT")
    repl = os.environ.get("PANTOGRAPH_TEST_REPL")
    if not source or not repl:
        if request.config.getoption(
            "--run-pantograph-live"
        ) or request.config.getoption("--run-pantograph-mathlib"):
            pytest.fail(
                "Required live run needs PANTOGRAPH_TEST_SOURCE_ROOT and PANTOGRAPH_TEST_REPL."
            )
        pytest.skip("Explicit live paths not configured.")
    imports = os.environ.get("PANTOGRAPH_TEST_IMPORTS", "Init,Lean").split(",")
    return PantographEnv(
        source_root=Path(source), pantograph_repl=Path(repl), imports=tuple(imports)
    )


@pytest.mark.pantograph_live
def test_protocol_gate_and_repeated_scoped_proofs(live_env):
    report = asyncio.run(verify_live_client(live_env))
    assert report["scoped_proofs"] == 100
    assert report["initial_states"] == report["final_states"] == 0
    assert report["phase"] == "CLOSED" and report["subprocess_reaped"]
    assert {
        "instance-let-valid-and-admission-probes",
        "parent-deletion-and-independent-alternatives",
        "focus-and-sibling-resumption",
        "failure-recovery",
        "diagnostics-multiline",
        "positive-unsafe-rejection",
        "repeated-scoped-proofs",
    } <= set(report["checks"])
    assert report["skipped_checks"] == {}


@pytest.mark.pantograph_live
def test_metaprogram_checks_are_reported_not_faked_without_lean(live_env):
    core = replace(live_env, imports=("Init",))
    report = asyncio.run(verify_live_client(core, require_all=False))
    assert set(report["skipped_checks"]) == set(METAPROGRAM_CHECKS)
    assert not set(METAPROGRAM_CHECKS) & set(report["checks"])
    assert report["subprocess_reaped"]
    with pytest.raises(PantographProtocolError, match="did not run"):
        asyncio.run(verify_live_client(core))


@pytest.mark.pantograph_live
def test_early_release_and_rejection_keep_the_session_usable(live_env):
    async def run():
        async with await PantographClient.create(live_env) as client:
            baseline = (await client.stat()).n_goals
            async with client.state_scope() as scope:
                root = await scope.start_goal("True ∧ True")
                split = await scope.apply_tactic(root, "constructor")
                await scope.release(root)
                await scope.release(root)
                assert (await client.stat()).n_goals == baseline + 1
                with pytest.raises(PantographTacticRejected):
                    await scope.apply_tactic(split, "exact False")
                assert client.is_usable
                left = await scope.apply_tactic(split, "trivial", goal_index=0)
                assert len(left.goals) == 1
            assert (await client.stat()).n_goals == baseline
        assert client.phase.value == "CLOSED"

    asyncio.run(run())


@pytest.mark.pantograph_live
def test_named_universe_levels_elaborate_only_when_declared(live_env):
    expression = "∀ (α : Sort u) (β : Type v) (a : α) (b : β), a = a ∧ b = b"

    async def run():
        async with await PantographClient.create(live_env) as client:
            baseline = (await client.stat()).n_goals
            async with client.state_scope() as scope:
                with pytest.raises(PantographGoalRejected, match="universe"):
                    await scope.start_goal(expression)
                with pytest.raises(PantographGoalRejected, match="universe"):
                    await scope.start_goal(expression, levels=["u"])
                assert client.is_usable
                assert (await client.stat()).n_goals == baseline
                root = await scope.start_goal(expression, levels=["u", "v"])
                intro = await scope.apply_tactic(root, "intro α β a b")
                assert [local.user_name for local in intro.goals[0].locals] == [
                    "α",
                    "β",
                    "a",
                    "b",
                ]
                split = await scope.apply_tactic(intro, "constructor")
                left = await scope.apply_tactic(split, "rfl", goal_index=0)
                done = await scope.apply_tactic(left, "rfl")
                assert done.goals == ()
            assert (await client.stat()).n_goals == baseline
        assert client.phase.value == "CLOSED"

    asyncio.run(run())


@pytest.mark.pantograph_live
def test_installed_cli_reports_without_a_checkout(live_env, tmp_path):
    report = tmp_path / "report.json"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pantograph_async.cli",
            "smoke",
            "--source-root",
            str(live_env.source_root),
            "--pantograph-repl",
            str(live_env.pantograph_repl),
            *(arg for name in live_env.imports for arg in ("--import", name)),
            "--report",
            str(report),
        ],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        timeout=600,
    )
    payload = json.loads(report.read_text())
    assert payload["subprocess_reaped"] and payload["checks"]
    assert payload["compatibility"]["model_sexp_version"] == 1
    assert len(payload["repl_sha256"]) == 64


@pytest.mark.pantograph_live
def test_provenance_separates_children_from_siblings(live_env):
    async def run():
        async with await PantographClient.create(live_env) as client:
            async with client.state_scope() as scope:
                root = await scope.start_goal("True ∧ True")
                split = await scope.apply_tactic(root, "constructor")
                assert split.transition.selected == root.root
                assert split.transition.direct == tuple(
                    g.goal_name for g in split.goals
                )
                left, right = (goal.goal_name for goal in split.goals)
                second = await scope.apply_tactic(split, "trivial", goal_index=1)
                assert second.transition.selected == right
                assert second.transition.direct == ()
                assert second.transition.siblings == (left,)
                first = await scope.apply_tactic(split, "trivial", goal_index=0)
                assert first.transition.siblings == (right,)

                witness = await scope.start_goal("∃ n : Nat, n = 0 ∧ n = 1")
                parts = await scope.apply_tactic(witness, "refine ⟨?w, ?a, ?b⟩")
                w, a, b = (goal.goal_name for goal in parts.goals)
                solved = await scope.apply_tactic(
                    parts, "exact (rfl : 0 = 0)", goal_index=1
                )
                assert solved.transition.closed == (w,)
                assert solved.transition.changed == (b,)
                obligations = await scope.inspect(solved, [w, a, b])
                assert [item.status for item in obligations] == [
                    "complete",
                    "complete",
                    "active",
                ]
                assert obligations[2].goal.target.pp == "0 = 1"
                untouched = await scope.inspect(parts, [w, a, b])
                assert [item.status for item in untouched] == ["active"] * 3

                intro = await scope.apply_tactic(
                    await scope.start_goal("∀ (p : Prop), p → p"), "intro p h"
                )
                (goal,) = intro.goals
                assert intro.transition.introduced == (
                    tuple(local.internal_name for local in goal.locals),
                )

    asyncio.run(run())


@pytest.mark.pantograph_live
def test_certification_requires_a_kernel_checked_complete_root(live_env):
    async def run():
        async with await PantographClient.create(live_env) as client:
            async with client.state_scope() as scope:
                root = await scope.start_goal("True ∧ True")
                split = await scope.apply_tactic(root, "constructor")
                partial = await scope.apply_tactic(split, "trivial", goal_index=1)
                result = await scope.certify(partial)
                assert result.status == "incomplete" and result.receipt is None
                done = await scope.apply_tactic(partial, "trivial")
                certificate = await scope.certify(done)
                assert certificate.is_certified and certificate.reason is None
                assert certificate.receipt.root == root.root
                assert await scope.certify(done) == certificate
                assert (await scope.certify(root)).status == "incomplete"

                witness = await scope.start_goal("∃ n : Nat, n = 0 ∧ n = 1")
                parts = await scope.apply_tactic(witness, "refine ⟨?w, ?a, ?b⟩")
                conflict = await scope.apply_tactic(
                    parts, "exact (rfl : 0 = 0)", goal_index=1
                )
                assert not (await scope.certify(conflict)).is_certified

                classical = await scope.apply_tactic(
                    await scope.start_goal("∀ (p : Prop), p ∨ ¬p"),
                    "intro p\nexact Classical.em p",
                )
                receipt = (await scope.certify(classical)).receipt
                assert "Classical.choice" in receipt.axioms
            assert (await client.stat()).n_goals == 0

    asyncio.run(run())


@pytest.mark.pantograph_live
def test_released_states_are_reclaimed_inside_a_scope(live_env):
    import gc
    import weakref

    async def run():
        async with await PantographClient.create(live_env) as client:
            async with client.state_scope() as scope:
                root = await scope.start_goal("∀ (p : Prop), p → p")
                refs = []
                for _ in range(200):
                    state = await scope.apply_tactic(root, "intro p h")
                    refs.append(weakref.ref(state))
                    await scope.release(state)
                    del state
                gc.collect()
                assert all(ref() is None for ref in refs)
                assert len(scope._issued) == 1
                assert (await client.stat()).n_goals == 1

    asyncio.run(run())


@pytest.mark.pantograph_live
def test_a_protocol_version_1_binary_is_rejected_at_startup(live_env):
    old = os.environ.get("PANTOGRAPH_TEST_OLD_REPL")
    if not old:
        pytest.skip("PANTOGRAPH_TEST_OLD_REPL not configured.")

    async def run():
        with pytest.raises(PantographProtocolError, match="certificationVersion"):
            await PantographClient.create(replace(live_env, pantograph_repl=Path(old)))

    asyncio.run(run())


@pytest.mark.pantograph_live
def test_a_validation_version_2_binary_is_rejected_at_startup(live_env):
    old = os.environ.get("PANTOGRAPH_TEST_VALIDATION2_REPL")
    if not old:
        pytest.skip("PANTOGRAPH_TEST_VALIDATION2_REPL not configured.")

    async def run():
        with pytest.raises(PantographProtocolError, match="transitionValidationVersion"):
            await PantographClient.create(replace(live_env, pantograph_repl=Path(old)))

    asyncio.run(run())


@pytest.mark.pantograph_live
def test_compiler_producing_tactics_keep_a_usable_state_and_certify(live_env):
    """`unfold Nat.pow` compiles the match splitter; version 2 ended the session."""
    from pantograph_async import TRANSITION_VALIDATION_VERSION

    async def run():
        async with await PantographClient.create(live_env) as client:
            async with client.state_scope() as scope:
                root = await scope.start_goal("∀ m n : Nat, Nat.pow m n = Nat.pow m n")
                middle = await scope.apply_tactic(root, "intro m n")
                unfolded = await scope.apply_tactic(middle, "unfold Nat.pow")
                assert unfolded.validation.version == TRANSITION_VALIDATION_VERSION
                assert not unfolded.validation.is_rejection and unfolded.goals
                inspected = await scope.inspect(unfolded, [root.root])
                assert not inspected[0].is_complete
                split = await scope.apply_tactic(unfolded, "split")
                assert len(split.goals) == 2
                first = await scope.apply_tactic(split, "rfl")
                done = await scope.apply_tactic(first, "rfl")
                assert not done.goals and scope._validate_state(done)
                certificate = await scope.certify(done)
                assert certificate.status == "certified"
                assert any("splitter" in name for name in certificate.receipt.auxiliary)
                assert not any("_cstage" in name for name in certificate.receipt.auxiliary)
                # A rewrite through generated equations on another root, same session.
                other = await scope.start_goal(
                    "∀ m n : Nat, Nat.pow m (n+1) = Nat.pow m n * m"
                )
                opened = await scope.apply_tactic(other, "intro m n")
                rewritten = await scope.apply_tactic(opened, "rw [Nat.pow]")
                assert not rewritten.validation.is_rejection and rewritten.goals
                assert client.is_usable
            assert (await client.stat()).n_goals == 0

    asyncio.run(run())


@pytest.mark.pantograph_live
def test_a_tactic_that_leaves_the_goal_open_keeps_the_session(live_env):
    async def run():
        async with await PantographClient.create(live_env) as client:
            async with client.state_scope() as scope:
                root = await scope.start_goal("True")
                same = await scope.apply_tactic(root, "skip")
                assert (
                    same.transition.direct == (root.root,) == (same.goals[0].goal_name,)
                )
                assert client.is_usable

    asyncio.run(run())


@pytest.mark.pantograph_live
def test_native_heartbeat_rollback_keeps_original_state(live_env):
    """Required revision-3 gate; never substitute fake exchanges for this check."""
    from pantograph_async import PantographResourceError

    async def run():
        fixture_env = replace(
            live_env, imports=(*live_env.imports, "Test.ContractFixtures")
        )
        async with await PantographClient.create(fixture_env) as client:
            assert (await client.stat()).n_goals == 0
            async with client.state_scope() as scope:
                original = await scope.start_goal("True")
                # Native weak-head reduction exhausts the command budget.
                tactic = "contract_heartbeat"
                for _ in range(3):
                    with pytest.raises(PantographResourceError) as caught:
                        await scope.apply_tactic(original, tactic)
                    assert caught.value.kind == "heartbeats"
                    assert caught.value.command == "goal.tactic"
                    assert client.is_usable and (await client.stat()).n_goals == 1
                done = await scope.apply_tactic(original, "trivial")
                assert (await scope.certify(done)).is_certified
            assert (await client.stat()).n_goals == 0
        assert client.phase.value == "CLOSED"

    asyncio.run(run())


@pytest.mark.pantograph_live
def test_native_fatal_error_retires_owned_states(live_env):
    from pantograph_async import PantographRemoteInternalError, PantographStateError

    async def run():
        fixture_env = replace(
            live_env, imports=(*live_env.imports, "Test.ContractFixtures")
        )
        async with await PantographClient.create(fixture_env) as client:
            async with client.state_scope() as scope:
                original = await scope.start_goal("True")
                with pytest.raises(PantographRemoteInternalError) as failure:
                    await scope.apply_tactic(original, "contract_internal_failure")
                assert not client.is_usable and not client._allocated_ids
                assert not scope._issued
                with pytest.raises(PantographRemoteInternalError) as later:
                    await client.stat()
                assert later.value is failure.value
                with pytest.raises(PantographStateError):
                    await scope.apply_tactic(original, "trivial")
        assert client.phase.value == "CLOSED"

    asyncio.run(run())


@pytest.mark.pantograph_live
def test_native_auxiliary_residue_is_owned_inspectable_and_certified(live_env):
    from pantograph_async import (
        TRANSITION_VALIDATION_VERSION,
        TRANSITION_VALIDATION_SCOPE,
    )

    async def run():
        fixture_env = replace(
            live_env, imports=(*live_env.imports, "Test.ContractFixtures")
        )
        async with await PantographClient.create(fixture_env) as client:
            async with client.state_scope() as scope:
                root = await scope.start_goal("True")
                done = await scope.apply_tactic(root, "contract_inert_residue")
                assert done.validation.version == TRANSITION_VALIDATION_VERSION
                assert done.validation.scope == TRANSITION_VALIDATION_SCOPE
                assert done.validation.checked and not done.validation.is_rejection
                assert not done.goals
                assert scope._validate_state(done)
                inspected = await scope.inspect(done, [root.root])
                assert inspected[0].is_complete
                receipt = await scope.certify(done)
                assert receipt.is_certified and receipt.receipt.root == root.root
                # An alternative still executes against the retained original input.
                alternative = await scope.apply_tactic(root, "trivial")
                assert (await scope.certify(alternative)).is_certified
            assert (await client.stat()).n_goals == 0
            assert not client._allocated_ids

    asyncio.run(run())


@pytest.mark.pantograph_live
def test_native_dangling_execution_reference_is_terminal(live_env):
    from pantograph_async import PantographStateError

    async def run():
        fixture_env = replace(
            live_env, imports=(*live_env.imports, "Test.ContractFixtures")
        )
        async with await PantographClient.create(fixture_env) as client:
            async with client.state_scope() as scope:
                root = await scope.start_goal("True")
                with pytest.raises(PantographProtocolError) as failure:
                    await scope.apply_tactic(root, "contract_invalid_mutation")
                assert failure.value.payload["error"] == "validation"
                assert "owner=" in str(failure.value) and "path=" in str(failure.value)
                assert not scope._issued and not client._allocated_ids
                assert not client.is_usable
                with pytest.raises(PantographProtocolError) as later:
                    await client.stat()
                assert later.value is failure.value
                with pytest.raises(PantographStateError):
                    await scope.apply_tactic(root, "trivial")
            assert client.phase.value == "CLOSED"

    asyncio.run(run())


@pytest.fixture
def mathlib_env(live_env, request):
    root = os.environ.get("PANTOGRAPH_TEST_MATHLIB_ROOT")
    if not root:
        if request.config.getoption("--run-pantograph-mathlib"):
            pytest.fail("Required Mathlib run needs PANTOGRAPH_TEST_MATHLIB_ROOT.")
        pytest.skip("Separate pinned Mathlib build not configured.")
    return replace(live_env, source_root=Path(root), imports=("Mathlib",))


@pytest.mark.pantograph_live
@pytest.mark.parametrize(
    "statement,intro,levels",
    [
        ("∀ (p q : Prop), p ∧ q → q ∧ p", "intro p q", ()),
        ("∀ (p q : Prop), p ∨ q → q ∨ p", "intro p q", ()),
        (
            "∀ (α : Type u_1) (β : Type u_2) (γ : Type u_3) [DecidableEq α] "
            "(s t u v : Finset α) (a b : α), "
            "a ∉ s → ((∀ a ∈ t, a ∉ s) ↔ ∀ ⦃a : α⦄, a ∈ s → a ∉ t)",
            "intro α β γ inst s t u v a b",
            ("u_1", "u_2", "u_3"),
        ),
    ],
)
def test_native_mathlib_tauto_retains_owned_state_and_certifies(
    mathlib_env, statement, intro, levels
):
    from pantograph_async import TRANSITION_VALIDATION_SCOPE, TRANSITION_VALIDATION_VERSION

    async def run():
        async with await PantographClient.create(mathlib_env) as client:
            async with client.state_scope() as scope:
                root = await scope.start_goal(statement, levels=levels)
                middle = await scope.apply_tactic(root, intro)
                assert middle.goals
                selected = middle.goals[0].goal_name
                assert any(
                    item.status == "active"
                    for item in await scope.inspect(middle, [root.root, selected])
                )
                done = await scope.apply_tactic(middle, "tauto")
                assert scope._validate_state(done)
                assert done.validation.version == TRANSITION_VALIDATION_VERSION
                assert done.validation.scope == TRANSITION_VALIDATION_SCOPE
                assert done.validation.checked and not done.validation.is_rejection
                assert not done.goals
                assert all(
                    item.is_complete
                    for item in await scope.inspect(done, [root.root, selected])
                )
                certificate = await scope.certify(done)
                assert (
                    certificate.is_certified and certificate.receipt.root == root.root
                )
                alternative = await scope.apply_tactic(middle, "tauto")
                assert (await scope.certify(alternative)).is_certified
                assert scope._validate_state(middle)
            assert (await client.stat()).n_goals == 0
            assert not client._allocated_ids

    asyncio.run(run())


@pytest.mark.pantograph_live
def test_native_mathlib_tauto_keeps_sibling_obligations_visible(mathlib_env):
    async def run():
        async with await PantographClient.create(mathlib_env) as client:
            async with client.state_scope() as scope:
                root = await scope.start_goal(
                    "∀ (p q : Prop), (p ∧ q → q ∧ p) ∧ (p ∨ q → q ∨ p)"
                )
                split = await scope.apply_tactic(root, "intro p q; constructor")
                names = [goal.goal_name for goal in split.goals]
                assert len(names) == 2
                partial = await scope.apply_tactic(split, "tauto", goal_index=1)
                statuses = {item.status for item in await scope.inspect(partial, names)}
                assert statuses == {"active", "complete"}
                assert (await scope.certify(partial)).status == "incomplete"
                done = await scope.apply_tactic(partial, "tauto")
                receipt = await scope.certify(done)
                assert receipt.is_certified and receipt.receipt.root == root.root
            assert (await client.stat()).n_goals == 0

    asyncio.run(run())
