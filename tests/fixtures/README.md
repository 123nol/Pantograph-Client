# Test fixtures

Wire evidence, kept unchanged from Mathematics-ai-atp `e8e4b18`. Only the
final validated contract is accepted by the codec; the others are kept to prove
older or unextended servers are rejected.

| Path | What it is | Accepted by the codec |
| --- | --- | --- |
| `baseline/` | Raw capture from the original, unmodified custom REPL | No |
| `upstream_pr1/` | Live capture from the merged fork (PR #1) without the companion patch | Failure variants only |
| `historical_revision1/` | Authored fixtures for the superseded contract revision 1 | No |
| `stage4_companion/` | Live capture from the validated companion build (revision 2) | Yes |
| `future_contract.json` | Authored revision-2 responses used by the fake REPL and codec tests | Yes |
| `fake_repl.py` | Diagnostic child process for real-process transport tests; never used at runtime | n/a |

Canonical graph goldens belong to the consuming application, not here.
