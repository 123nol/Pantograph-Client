# Wire protocol

The client speaks exactly one contract, revision 3 of the custom REPL
(`src/pantograph_async/resources/contract.json`). The codec in
`pantograph_async.protocol` rejects anything else; there is no fallback schema.

## Session

The REPL is launched as `stdbuf -oL <repl> <imports...>` in `source_root`, with
`LEAN_PATH` from `lake env printenv LEAN_PATH`. It must print `ready.` and then
answer one JSON line per request line `<command> <json>`.

Startup, under one deadline:

1. `protocol.describe` must return exactly this descriptor:

   | Field | Value |
   | --- | --- |
   | `protocol` | `maths-ai-pantograph` |
   | `protocolVersion` | 2 |
   | `modelSexpVersion` | 1 |
   | `transitionValidationVersion` | 1 |
   | `transitionProvenanceVersion` | 1 |
   | `inspectionVersion` | 1 |
   | `certificationVersion` | 1 |
   | `messageVersion` | 1 |
   | `goalSelection` | `explicit-focused-v1` |
   | `tacticErrorsFormat` | `string-array-v1` |

   The protocol name keeps its historical application name. Renaming the Python
   package does not change it.
2. `options.set` applies the required options (`printJsonPretty=false`,
   `printExprPretty`, `printExprAST`, `printExprModelAST`, `automaticMode` true,
   `noRepeat=false`). Conflicting values are rejected before any request.
3. `options.print` must report every requested option as applied.

## Commands

| Command | Request | Success |
| --- | --- | --- |
| `goal.start` | `{"expr"}`, optional `{"levels"}` | `{"stateId", "root"}` |
| `goal.tactic` | `{"stateId", "goalId", "tactic"}` | see below |
| `goal.delete` | `{"stateIds"}` (unique) | `{}` |
| `goal.inspect` | `{"stateId", "goals"}` (nonempty, distinct) | `{"obligations"}` |
| `goal.certify` | `{"stateId"}`, optional positive `{"maxHeartbeats"}` | see below |
| `stat` | `{}` | `{"nGoals"}` |

`levels` is the REPL's existing universe-parameter list for `goal.start`: the
server declares each name with `String.toName` before elaborating `expr`. It is
sent only when nonempty, so a goal without named universes keeps the original
request bytes. Each entry must be a unique atomic ASCII identifier
(`[A-Za-z_][A-Za-z0-9_']*`, not `_`, `max` or `imax`); a dotted name would become
a hierarchical name on the server. Invalid lists are rejected before anything is
sent. Exposing this field changes no descriptor version.

`goalId` is always sent explicitly. Omission is not unfocused execution.
Errors are `{"error", "desc"}` with a per-command category set. `goal.start`
parse/elaboration errors map to `PantographGoalRejected`; an unknown state
or obligation index on `goal.tactic`, `goal.inspect` or `goal.certify` maps to
`PantographStateError`; everything else is a protocol error.

## Tactic responses

Exactly one of three variants, each with `messages`, `hasSorry` and `hasUnsafe`:

- success: `nextStateId`, `goals`, `transition` (below), and `validation` =
  `{"version": 1, "scope": "transition-expressions", "checked": true}`.
  A logged error message cannot accompany a success.
- `parseError`: a nonempty string.
- `tacticErrors`: a nonempty string array.

Failed variants must carry false flags. A success with `hasSorry` or
`hasUnsafe` is an admission/unsafe rejection: the client deletes the new state
and raises `PantographTacticRejected` with the decoded success as payload.

Goals carry `name`, optional `userName` (case tag), `fragment`
(`tactic`/`conv`/`calc`, consistent with `isConversion`), a target expression,
and `vars`. Locals have unique increasing `contextIndex` values (gaps allowed),
a binder role consistent with `isInstance`/`isLet`, and a `value` exactly when
they are `let`. Every expression has `pp`, `sexp`, `modelSexp` and
`modelSexpVersion`, plus optional `dependentMVars`.

Messages have `kind`, `severity` (`information`/`warning`/`error`), `data`,
`pos` and optional `endPos`. Position `(0, 0)` means unavailable.

## Transition provenance

`transition` is `{version: 1, selected, direct, introduced, siblings, changed,
closed, dormant, extra}`. `direct` lists the goals the tactic produced for
`selected`, in tactic order and before automatic sibling resumption;
`introduced[i]` lists the locals `direct[i]` has that `selected` lacks.
`siblings` are input goals still listed, `changed` the siblings whose
instantiated target or locals changed, `closed` the input goals the transition
assigned, `dormant` those unassigned but no longer listed, and `extra` any other
listed obligation. A tactic that leaves `selected` open, such as `skip`, lists
it as its own direct goal. The codec requires `direct`, `siblings` and `extra`
to partition `goals`, `selected`, `closed` and `dormant` to be distinct,
`closed` and `dormant` to be unlisted, a listed `selected` to be direct,
`changed` to be siblings and every introduced local to be in its
goal's context. The scope also requires `selected` to name the goal it asked
for. A violation retires the session.

Names are Lean metavariable and local IDs. They are valid only inside one
session's state lineage and change when the same tactics are replayed.

## Inspection

Each obligation is `{name, status, holes, universeHoles}` plus `goal` for the
`active` and `pending` statuses. `complete` has no holes; `assigned` and
`delayed` report at least one. Obligations come back in request order, which
the scope checks. Inspection allocates nothing.

## Certification

`{version: 1, status, reason?, receipt?}` with status `certified`, `incomplete`,
`rejected` or `inconclusive` (a kernel resource limit). Exactly `certified`
carries a receipt and no reason: `{version, identity: "lean-expr-digest-v1",
root, levels, rootType, proof, environment, lean, axioms, auxiliary}`, where the
three digests are 16 lowercase hex digits. The scope requires the receipt's
root to be the root the state descends from. The check is the server's kernel
check of the started statement, not an interpretation of `goals == []`. A
request timeout retires the session like any other.

## Execution types

Decoded values are frozen dataclasses (`ExecutionGoal`, `ExecutionLocal`,
`WireExpression`, `TacticState`, `TransitionProvenance`,
`ObligationInspection`, `CertificationResult`, ...). They expose wire fields only. Converting
them into an application model is the consumer's job, in its own adapter.
