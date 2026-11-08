# Standalone client: failure snapshots and shared request evidence

## Status, repository, and dependencies

Proposed architecture; obtain explicit verification before implementation.
Target repository: `123nol/Pantograph-Client`.
Reference client reviewed: `e8aa9ecc17686cfa2703c7082c02d45310ce421f`.
Verify the maintained target branch/base before editing.

This is the standalone-client portion of
[puct_pantograph_failure_diagnostics_and_remediation.md](puct_pantograph_failure_diagnostics_and_remediation.md).
Companion plans:
[REPL](pantograph_repl_unexpected_failure_diagnostics.md) and
[application](mcts_pantograph_failure_bundles_and_replay.md).

The historical log contains 74 remote internal errors, but the application
has only their class names. The client already preserves typed exception
payloads and a bounded stderr tail. Extend that shared boundary with a public,
typed failure-evidence interface so callers do not inspect private transport
state or individually patch request readers.

Development with fake subprocesses can begin before the REPL change lands.
Native verification and release handoff require the REPL's version-1 stderr
fixtures and full source/executable identity. Existing stdout decoding and
recovery classifications stay strict.

## Alternatives considered

| Approach | Advantages | Limits / decision |
|---|---|---|
| Application patches `_exchange` or `_read_stdout` | Quick experiment | Depends on private lifecycle state and splits callers; rejected for implementation. |
| Add only `str(exc)` to logs | Small change | Omits request, structured payload, cancellation state, and final stderr; insufficient. |
| Retain every response/state object | Broad history | Keeps allocations and Python objects alive without a bound; rejected. |
| Reclassify internal errors as tactic rejection | Appears to keep search running | Violates the unusable-session contract; rejected. |
| Shared immutable diagnostics plus bounded request/outcome events | Reusable public API and explicit ownership | Requires lifecycle and observer-error tests; selected. |

## Public evidence contract

Add typed, immutable plain-data records in a dedicated module, exported from
the package's public interface. Do not include `TacticState`, live handles,
model tensors, process objects, futures, or mutable environment objects.

### Request and outcome events

Emit evidence from the serialized exchange boundary for every operation,
including goal start, tactic, inspection, certification, deletion, and startup
options/capabilities. This is a generic client facility, not an RL callback.

Each event identifies its schema version, client session ID, process ID,
`client_request_sequence`, operation, timing, request/outcome kind, selected
wire state/goal fields when present, and bounded request/response data.
The sequence is assigned by this client session, not by the REPL.

The pre-dispatch event is emitted before the write. Preserve clear timing
states: waiting for exchange ownership, prepared but not written, written and
awaiting response, decoded, allocation-registered, and failed. A timeout before
dispatch must not be falsely described as a command interrupted in Lean.

Use a documented public observer/sink interface with typed events. Its error,
ordering, cancellation, and durability semantics must be explicit:

- Preserve ordered delivery within the serialized exchange.
- Permit the application sink to acknowledge a required pre-dispatch record
  before the corresponding write; include that work in request deadlines.
- Bound event memory and do not start detached tasks that outlive cleanup.
- Report capture truncation or sink failure explicitly. Never silently claim
  a complete history after dropping events.
- A sink failure is a diagnostic-capture failure, not a fabricated remote
  internal or ordinary tactic error. Preserve a concurrent primary protocol
  failure and its cleanup result separately.
- Allocation registration and cleanup must remain correct if an outcome sink
  fails after a response creates a Lean allocation.

The application owns durable journals and run-wide disk caps. The client
owns exchange sequencing and finite request/failure snapshots. Do not add
unbounded transport history inside the client.

### Failure snapshot

Provide public access to an immutable snapshot for a failed or interrupted
request. Include:

- Schema version, session/process identity, operation, and request sequence.
- Bounded exact request, including tactic and selected state/goal where present.
- Exception class/message, structured error payload, and exception notes.
- Timeout source and exchange timing state where known.
- Current stderr tail, truncation flags, and diagnostic-capture errors.
- A recognized REPL diagnostic, when unambiguously associated, plus the raw
  stderr tail regardless of whether parsing succeeds.

Serialize typed error payload dataclasses structurally. Do not reduce them to
opaque strings. Preserve strict bounds for nested data and serialized bytes.
Mark a request with omitted/truncated execution fields as incomplete.

The snapshot must remain readable after retirement and `aclose()`. Allow a
finalized immutable snapshot after process reaping and stderr drain. Do not
mutate an already returned snapshot in place. Preserve the original error if
cleanup also fails; expose both, with their ownership and timing.

### REPL stderr contract

Recognize only JSON records tagged `kind: pantograph-command-failure` and
`version: 1`. The REPL plan defines operation, `repl_command_sequence`, selected
state/goal, actual phase, exception category/ID, bounded detail, truncation,
and rendering status. Other stderr remains raw diagnostic text.

`repl_command_sequence` and `client_request_sequence` are distinct counters;
keep both and do not assume equality. Associate stderr with the actual pending
serialized request using process/session identity, operation, and available
state/focus/order evidence. If association is ambiguous, preserve raw records
and mark ambiguity instead of assigning a previous tactic as the cause.

Malformed or unrelated stderr must not loosen stdout response decoding.
Missing stderr after a failed write must not change a valid typed terminal
error into a protocol-decoding failure. Explicit absence is diagnostic data.

Do not put `pantograph.traceCommands` into `PantographEnv.options`: that
strict schema is for supported session options. The REPL's always-on bounded
fatal record requires no arbitrary Lean launch flags.

## Lifecycle and recovery invariants

- `PantographRemoteInternalError` remains session-unusable.
- Validation/protocol/stale-reference failures retain strict terminal handling.
- Ordinary tactic rejection does not retire the session.
- A typed safe resource rollback leaves prior state allocations usable.
- Cancellation and request timeout follow existing retirement/cleanup rules;
  evidence must not revive handles or detach process ownership.
- Request/outcome capture occurs across all state-producing and state-deleting
  operations, without leaking registrations when capture itself fails.
- A pending-request snapshot must never become the snapshot of a replacement
  client. This package does not replace application workers itself.

## Sequential implementation stages

### Stage 0 — Inventory boundaries and establish fixtures

Audit exchange serialization, request deadlines, allocation registration,
error creation, retirement, stderr draining, and `aclose()`. Record the current
public API and exception contracts. Agree the event/snapshot schema and sink
behavior with the application agent before migrating consumers.

Exit: stable interface and fake-process fixtures cover lifecycle timing states.

### Stage 1 — Add typed events and immutable snapshots

Implement finite pre-dispatch evidence, operation sequencing, structured
payload export, observer delivery, failure snapshots, and post-close
finalization. Use one shared path for every operation. Export the types and
access methods publicly and document their lifetime.

Exit: consumers can capture a complete bounded request/error record without
private attribute access or retaining live allocations.

### Stage 2 — Preserve evidence through every failure path

Integrate cancellation, timeout, malformed response, remote internal error,
protocol-integrity failure, resource rollback, stderr drain, and cleanup
failure. Handle sink failures without losing primary exception evidence or
allocation ownership. Reject or explicitly mark oversized records.

Exit: lifecycle tests prove correct registration/retirement and no growing
state/future/process references in diagnostics.

### Stage 3 — Native REPL integration

Use the REPL handoff's full commit, executable hash, and stderr fixtures.
Verify recognized failure evidence and final stderr after fatal exit. Test
ordinary rejection, rollback-resource outcomes, and positive certified proofs.
Do not require a stdout schema/version change for stderr-only diagnostics.

Exit: typed stdout behavior is unchanged, and unexpected native failures
produce useful finalized snapshots.

### Stage 4 — Package and application handoff

Run package tests and existing archive/wheel checks. Publish the full client
commit/package identity. Supply the application agent with:

- Public type/method signatures and event/snapshot schemas.
- Timing, bounds, sink-failure, and cancellation semantics.
- Recorded REPL commit/hash and native/fake-process evidence.
- Samples for internal, rejection, resource, timeout, and cleanup outcomes.
- Dependency migration instructions and a basic model-free usage example.

The application must pin this exact commit and regenerate its lockfile.
Do not introduce a legacy private-reader path for application callers.

## Required tests

- Event ordering and exact pre-dispatch request across all operation families.
- Waiting/pre-write/request/cleanup timeout origins remain distinguishable.
- Typed payloads, notes, Unicode, nesting, byte caps, explicit truncation,
  and JSON export round-trip without live state references.
- Initial snapshot survives retirement; finalized snapshot includes late
  stderr and remains readable after `aclose()`.
- Cancellation before write, after write, after response, and during cleanup
  preserves registration, state ownership, and process reaping.
- Observer failure before write sends no command; failure after allocation
  does not leak it; concurrent primary failure is not replaced by sink error.
- Recognized stderr records cannot be attached to another session/request;
  ambiguous or malformed records retain raw evidence and strict stdout decoding.
- Invalid, copied, stale, cross-scope, and cross-session references remain
  rejected. New evidence objects must not prevent released states from GC.
- Native internal failures retire the session; ordinary rejection and safe
  resource rollback remain usable; valid proof certification still passes.

## Acceptance and limits

The client patch is complete when public bounded evidence survives all
supported failure/cleanup paths without changing typed execution semantics.
It does not repair the unknown Lean causes, own application failure archives,
retry theorem attempts, or expose an unrestricted raw-command bypass.
