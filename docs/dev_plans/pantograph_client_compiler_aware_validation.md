# Standalone client support for compiler-aware Pantograph validation

## Status, dependency, and objective

This is a proposed implementation plan for `123nol/Pantograph-Client`. No client runtime edits are implemented here. It depends on [the custom REPL plan](pantograph_repl_compiler_aware_validation.md) and supplies the package consumed by [the application integration plan](mcts_compiler_aware_validation_integration.md).

The client does not interpret Lean compiler expressions or decide that `_obj` is safe. Those decisions belong to the REPL's shared validator. The client's responsibility is to require the revised validation contract, preserve typed state ownership, package verifiable companion evidence, and retain terminal handling for genuine integrity failures.

Inspected baseline: `/home/nolawi/Pantograph-Client`, commit `053ff67dfc540391100c86e4deada06839904655`, package version 0.4.0. It currently accepts overall protocol 3 and transition validation 2. `CommandError.as_exception()` maps the `validation` category to `PantographProtocolError`; the transport retires the session on that failure.

## Decisions and alternatives

| Approach | Benefit | Cost or defect | Decision |
| --- | --- | --- | --- |
| Catch the `_obj` message and return a tactic rejection | Small client patch | Masks a REPL integrity failure and trusts an unverified snapshot | Reject |
| Accept validation versions 2 and 3 | Easier staged deployment | Leaves current callers using different audit boundaries | Reject for this coordinated migration |
| Leave the wire contract at version 2 and refresh only companion metadata | Fewer changes | Does not distinguish the revised representation/hazard boundary | Do not choose for this plan |
| Strictly migrate to validation version 3 and the new companion | Establishes one audit contract before allocations | Requires coordinated deployment and fixture migration | Choose |
| Add Python-side compiler-expression validation | Another local check | Duplicates Lean internals without snapshot/compiler ownership | Reject |

No transport redesign, new state lifetime scheme, or new recoverable error type is required by this incident. Preserve allocation registration and cancellation cleanup already implemented.

## Target contract

Require the REPL descriptor to advertise:

```json
{"transitionValidationVersion": 3}
```

Successful validation evidence must contain:

```json
{
  "version": 3,
  "scope": "execution-closure-and-representation-aware-audit",
  "checked": true
}
```

Overall protocol remains 3. Existing transition, resource, inspection, and certification schemas remain unchanged under this plan. Update every active descriptor and response consumer together. Do not accept an old version through an alternate decoder or a disable-validation option.

Compiler-aware auditing does not turn an integrity error into a recoverable domain rejection. A REPL `validation` error must still become a terminal `PantographProtocolError`. Successful evidence must not override contradictory `hasSorry` or `hasUnsafe` fields under the declared boundary.

## Stage 0: Freeze the REPL companion evidence

1. Obtain the exact REPL commit, patch, toolchain identity, source hashes, executable identity, and raw fixtures after its native regression passes.
2. Confirm the descriptor, successful validation evidence, hazard semantics, and terminal error behavior match the REPL plan.
3. Obtain captures for the exact minimized compiler failure, a multi-step incomplete proof, successful original-root certification, and genuine kernel dependency failure.
4. Record the input sequence and context necessary for reproduction. Do not assume `simp` is the failing command or that `True ∧ True` alone reproduces it.
5. Enumerate current resources and tests asserting validation version 2, including fake-server responses and live tests.

**Exit gate:** immutable companion evidence exists. Raw protocol fixtures may support development before the REPL commit is published; release evidence must point to its final immutable revision.

## Stage 1: Migrate codec, handshake, and packaged resources

Primary modules are `src/pantograph_async/protocol.py`, `compatibility.py`, and `resources/`. Audit `client.py` for any directly embedded validation assumptions.

- Set the transition validation constant to 3 and its scope to `execution-closure-and-representation-aware-audit`.
- Migrate the expected descriptor, typed validation decoder, schema resources, fake server, examples, and all active fixtures.
- Reject validation-version-2 companions at startup before options, allocations, or user tactic commands are sent.
- Reject missing, false, unknown, mixed-version, or contradictory evidence on a successful response.
- Keep the existing terminal error mapping. Preserve the structured REPL payload and command identity for diagnostics.
- Do not register a result state before the full successful response has been validated. Preserve response-arrival registration where needed to ensure cancellation cannot leak a validated allocation.
- Update `compatibility.json`, `contract.json`, companion patch and patch digest, and source hashes from actual committed evidence. Record both the descriptor revision and the validation subprotocol; do not conflate them.
- Preserve historical captures without editing their contents or hashes. Add a current capture group and its source lineage instead.
- Update documentation explaining that compiler-only runtime entries are not certified proof constants and that kernel certification remains authoritative for complete proofs.

**Exit gate:** one decoder and startup handshake enforce the new boundary; resource and ownership behavior remains intact.

## Stage 2: Add contract and lifecycle regressions

| Test | Expected outcome |
| --- | --- |
| Native compiler-producing reproduction with repaired companion | Ordinary typed successful transition, valid retained ownership |
| Subsequent tactic and inspection of retained output | State remains usable without reconstruction |
| Completed reproduction | Typed certification result for the original root |
| Descriptor or response at validation version 2 | Rejected without permissive decoding |
| New version with old scope, false `checked`, missing fields, or unsupported scope | Protocol failure |
| Genuine missing kernel dependency, including `_obj` in a kernel expression | Terminal protocol failure; session retired |
| Terminal validation error while another request waits | Queued request does not write to the retired session |
| Cancellation before dispatch, after response arrival, or during scope cleanup | Correct allocation registration, cleanup, and process reaping |
| Resource exhaustion during compiler-aware audit | Existing typed resource error; retryability follows the existing session contract |
| Copied, stale, cross-scope, and cross-session references | Existing ownership rejection preserved |

Keep core codec tests independent of Mathlib. The exact native reproduction belongs to a separately configured live test gate. Record whether that gate ran; passing fake-server tests is not native evidence.

## Stage 3: Build and release the standalone package

- Build both wheel and source distribution. Inspect the archives for current contract/compatibility resources and companion patch data.
- Install the wheel into an isolated environment and verify the installed resources agree with the codec.
- Run the source distribution's included tests using its unpacked contents and packaged support fixtures, rather than replacing them with files from the Git checkout.
- Re-run the existing transport, ownership, cleanup, resource, and live compatibility suites.
- Choose the next package version through the repository's release process. Record its full immutable commit for the application dependency.
- Publish a handoff listing the required REPL commit, descriptor and validation versions, tested toolchain/Mathlib, fixture lineage, and native verification commands.

**Exit gate:** the released package strictly accepts the repaired REPL and rejects the old audit contract; its installed resources can reproduce companion verification.

## Work explicitly outside this client patch

Do not recognize compiler declarations by Python string matching, continue a session after terminal validation failure, or alter certification semantics. Do not change the application model, retrieval artifacts, PLN translator, or tactic proposal distribution here. Those are separate components.

## Completion criteria

The updated package carries the correct immutable companion evidence, accepts version-3 checked transitions, preserves state ownership across cancellation, and retires sessions on actual integrity failures. Application migration can then use the exact published client commit.
