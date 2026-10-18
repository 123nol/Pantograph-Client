# Releases

## Versioning

- The distribution version (`pantograph-async-client`, `0.1.0`) identifies a
  library release.
- The descriptor's protocol, model-expression, transition-validation and message
  versions identify wire semantics.
- A release tag never replaces the runtime descriptor check or the
  executable's provenance.

A change to the server contract needs new descriptor versions, a matching
companion patch and manifest, and a new minor version. Library-only fixes are
patch releases.

## Checklist

1. Update `CHANGELOG.md` and the `version` in `pyproject.toml` and
   `compatibility.json`.
2. `python -m pytest` passes on Python 3.11–3.13 (CI).
3. The packaging job passes: the wheel built from the sdist is tested outside
   the checkout with `PANTOGRAPH_CLIENT_REQUIRE_INSTALLED=1`.
4. The live gate passes against a REPL rebuilt from the manifest:
   `pytest tests/test_client_live.py --run-pantograph-live` with
   `PANTOGRAPH_TEST_COMPANION_SOURCE` set.
5. Tag the commit `vX.Y.Z`. PyPI publication is optional and separate.

## Consumers

Consumers pin the full commit, for example
`pantograph-async-client @ git+https://github.com/123nol/Pantograph-Client@<commit>`,
and move the pin only after their own adapter and representation checks pass
against the new release.
