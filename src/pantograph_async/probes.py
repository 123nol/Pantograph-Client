"""Wire-level probes over the public scoped API.

Every probe checks execution fields directly and leaves the allocated-state
count where it found it. Representation checks belong to the consumer.
"""

from __future__ import annotations

from .client import PantographClient, PantographStateScope
from .protocol import PantographProtocolError, PantographTacticRejected


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PantographProtocolError(message)


async def probe_model_client(client: PantographClient) -> None:
    """Require actual normalized instance/let metadata and both proof outcomes."""
    baseline = (await client.stat()).n_goals
    async with client.state_scope() as scope:
        root = await scope.start_goal(
            "∀ (α : Type) [inst : Inhabited α] (x : α), x = x"
        )
        state = await scope.apply_tactic(root, "intro α inst x")
        goal = state.goals[0]
        require(
            len(goal.locals) == 3 and goal.locals[1].is_instance,
            "Instance probe did not preserve its ordered local context.",
        )
        require(
            "FV0" in goal.locals[2].type.model_sexp and "FV2" in goal.target.model_sexp,
            "Instance probe did not return normalized model expressions.",
        )
        require(
            not (await scope.apply_tactic(state, "rfl")).goals,
            "Valid probe did not close.",
        )
        root = await scope.start_goal("∀ (n : Nat), let x := n; x = x")
        state = await scope.apply_tactic(root, "intro n x")
        local = state.goals[0].locals[-1]
        require(
            local.is_let
            and local.value is not None
            and local.value.model_sexp == "(:fv FV0)",
            "Let probe lost its normalized value.",
        )
        require(
            not (await scope.apply_tactic(state, "rfl")).goals,
            "Local-let probe did not close.",
        )
        root = await scope.start_goal("True")
        try:
            await scope.apply_tactic(root, "exact (by sorry)")
        except PantographTacticRejected:
            pass
        else:
            raise PantographProtocolError("Admission probe was accepted.")
        require(
            not (await scope.apply_tactic(root, "trivial")).goals,
            "Source state was not reusable after admission rejection.",
        )
    require((await client.stat()).n_goals == baseline, "Model probe leaked states.")


# Expected goal counts after one tactic; goldens for derived representations
# belong to the consumer that owns them.
SHAPE_CASES = (
    ("identity_intro", "∀ (p : Prop), p → p", "intro p h", 1),
    ("conjunction_split", "True ∧ True", "constructor", 2),
    (
        "instance_intro",
        "∀ (α : Type) [inst : Inhabited α] (x : α), x = x",
        "intro α inst x",
        1,
    ),
    ("let_intro", "∀ (n : Nat), let x := n; x = x", "intro n x", 1),
)

UNSAFE_TACTIC = """run_tac
  let info : Lean.DefinitionVal := {
    name := `OwnedClientUnsafeEvidence, levelParams := [], type := Lean.mkConst ``True,
    value := Lean.mkConst ``True.intro, hints := .opaque, safety := .unsafe
  }
  Lean.addDecl (.defnDecl info)
  (← Lean.Elab.Tactic.getMainGoal).assign (Lean.mkConst `OwnedClientUnsafeEvidence)
  Lean.Elab.Tactic.setGoals []"""


async def probe_goal_shapes(scope: PantographStateScope) -> list[str]:
    outcomes = []
    for label, expression, tactic, count in SHAPE_CASES:
        root = await scope.start_goal(expression)
        state = await scope.apply_tactic(root, tactic)
        require(len(state.goals) == count, f"Goal count changed: {label}")
        require(
            all(goal.fragment == "tactic" for goal in state.goals),
            f"Goal fragment changed: {label}",
        )
        outcomes.append(label)
    return outcomes


async def probe_alternatives(scope: PantographStateScope) -> None:
    """A released parent must not invalidate its child or the child's siblings."""
    root = await scope.start_goal("∀ (p : Prop), p → p")
    child = await scope.apply_tactic(root, "intro p h")
    await scope.release(root)
    first = await scope.apply_tactic(child, "exact h")
    await scope.release(first)
    require(
        not (await scope.apply_tactic(child, "assumption")).goals,
        "Independent sibling alternative was invalidated.",
    )


async def probe_focus(scope: PantographStateScope) -> None:
    root = await scope.start_goal("True ∧ True")
    split = await scope.apply_tactic(root, "constructor")
    remaining = await scope.apply_tactic(split, "all_goals trivial", goal_index=1)
    require(len(remaining.goals) == 1, "Focused tactic lost unresolved sibling.")
    require(
        not (await scope.apply_tactic(remaining, "trivial")).goals,
        "Automatic sibling resumption failed.",
    )


async def probe_ordinary_failures(scope: PantographStateScope) -> None:
    """Parse and tactic failures are domain rejections; the source stays usable."""
    root = await scope.start_goal("True")
    for tactic in ("exact False", "exact ("):
        try:
            await scope.apply_tactic(root, tactic)
        except PantographTacticRejected:
            pass
        else:
            raise PantographProtocolError(f"Expected rejection: {tactic}")
    require(
        not (await scope.apply_tactic(root, "trivial")).goals,
        "Source state was not reusable after ordinary failures.",
    )


async def supports_metaprograms(scope: PantographStateScope) -> bool:
    """Whether the selected imports can elaborate ``run_tac`` metaprograms.

    Logged-error, message and unsafe probes are metaprograms. Without this
    check their expected rejections could come from an unknown constant.
    """
    root = await scope.start_goal("True")
    try:
        state = await scope.apply_tactic(root, "run_tac pure ()\ntrivial")
    except PantographTacticRejected:
        return False
    return not state.goals


async def probe_messages(scope: PantographStateScope) -> None:
    root = await scope.start_goal("True")
    try:
        await scope.apply_tactic(
            root, 'run_tac Lean.logError "expected diagnostic"\ntrivial'
        )
    except PantographTacticRejected:
        pass
    else:
        raise PantographProtocolError("A logged error was accepted.")
    good = await scope.apply_tactic(
        root,
        'run_tac Lean.logWarning "warning evidence"\nrun_tac Lean.logInfo "information evidence"\ntrivial',
    )
    require(
        not good.goals
        and {m.severity for m in good.messages} == {"warning", "information"},
        "Diagnostics or multiline execution changed.",
    )


async def probe_unsafe(scope: PantographStateScope) -> None:
    """The rejection must come from the transition scanner, not elaboration."""
    root = await scope.start_goal("True")
    try:
        await scope.apply_tactic(root, UNSAFE_TACTIC)
    except PantographTacticRejected as exc:
        require(
            getattr(exc.payload, "validation", None) is not None
            and exc.payload.validation.has_unsafe,
            "Unsafe example failed before reaching the proof scanner.",
        )
    else:
        raise PantographProtocolError("Unsafe proof was accepted.")


async def probe_repeated_proofs(client: PantographClient, proofs: int) -> None:
    baseline = (await client.stat()).n_goals
    for _ in range(proofs):
        async with client.state_scope() as scope:
            root = await scope.start_goal("∀ (p : Prop), p → p")
            require(
                not (await scope.apply_tactic(root, "intro p h\nexact h")).goals,
                "Repeated identity proof failed.",
            )
        require(
            (await client.stat()).n_goals == baseline,
            "Repeated workload leaked a state.",
        )
