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
        if request.config.getoption("--run-pantograph-live"):
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
                assert split.transition.direct == tuple(g.goal_name for g in split.goals)
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
                solved = await scope.apply_tactic(parts, "exact (rfl : 0 = 0)", goal_index=1)
                assert solved.transition.closed == (w,)
                assert solved.transition.changed == (b,)
                obligations = await scope.inspect(solved, [w, a, b])
                assert [item.status for item in obligations] == ["complete", "complete", "active"]
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
                conflict = await scope.apply_tactic(parts, "exact (rfl : 0 = 0)", goal_index=1)
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
def test_a_tactic_that_leaves_the_goal_open_keeps_the_session(live_env):
    async def run():
        async with await PantographClient.create(live_env) as client:
            async with client.state_scope() as scope:
                root = await scope.start_goal("True")
                same = await scope.apply_tactic(root, "skip")
                assert same.transition.direct == (root.root,) == (same.goals[0].goal_name,)
                assert client.is_usable

    asyncio.run(run())
