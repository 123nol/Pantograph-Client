# Changelog

## 0.1.0 (unreleased)

First standalone release, extracted from Mathematics-ai-atp `AC-branch` at
`e8e4b18e081d6dd84491433b00e8cfa596cdfbee`.

- Async transport, launch validation, state scopes and the strict codec for
  contract revision 2, unchanged apart from module paths.
- `MODEL_SEXP_VERSION` is owned by the client; execution types no longer
  convert into application models.
- Wire probes (`pantograph_async.probes`) and a live gate that reports which
  checks ran and fails when required checks cannot run.
- `pantograph-client smoke` CLI that needs no checkout or Git metadata.
- Contract, compatibility manifest and companion patch shipped as package data,
  with digest, codec and patched-source checks.
- The spawn-cancellation test gets its own startup budget, fixing a race with
  the helper processes.
- The sdist carries the complete offline suite, fixtures, documentation,
  evidence and example, checked by `scripts/check_sdist.py` in CI; the wheel
  stays runtime-only.
