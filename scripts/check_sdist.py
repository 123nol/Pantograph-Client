"""Check the release archives against the tracked tree.

The sdist must carry every tracked file except repository-only metadata, so
the archive alone can rebuild the wheel and run the complete offline suite.
The wheel must carry only the package and its metadata.

    python scripts/check_sdist.py dist/pantograph_async_client-*.tar.gz \
        dist/pantograph_async_client-*.whl
"""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import zipfile

REPOSITORY_ONLY = (".github/", ".gitignore", ".gitattributes")
REQUIRED = (
    "pyproject.toml",
    "MANIFEST.in",
    "tests/__init__.py",
    "tests/conftest.py",
    "tests/support.py",
    "tests/fixtures/fake_repl.py",
    "src/pantograph_async/resources/repository_client_contract.patch",
)


def tracked(root: Path) -> set[str]:
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=root, text=True)
    return {
        name
        for name in output.split("\0")
        if name and not name.startswith(REPOSITORY_ONLY)
    }


def sdist_members(path: Path) -> set[str]:
    with tarfile.open(path) as archive:
        names = [member.name for member in archive.getmembers() if member.isfile()]
    # Strip the "<name>-<version>/" prefix.
    return {str(PurePosixPath(*PurePosixPath(name).parts[1:])) for name in names}


def check_sdist(path: Path, root: Path) -> list[str]:
    members = sdist_members(path)
    errors = [f"sdist is missing {name}" for name in sorted(tracked(root) - members)]
    errors += [
        f"sdist is missing {name}" for name in REQUIRED if name not in members
    ]
    fixtures = {name for name in members if name.startswith("tests/fixtures/")}
    if not any(name.endswith(".json") for name in fixtures):
        errors.append("sdist has no JSON test fixtures")
    errors += [
        f"sdist contains build residue {name}"
        for name in sorted(members)
        if "__pycache__" in name or name.endswith((".pyc", ".pyo"))
    ]
    return sorted(set(errors))


def check_wheel(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        tops = {PurePosixPath(name).parts[0] for name in archive.namelist()}
    return [
        f"wheel ships {top}"
        for top in sorted(tops)
        if top != "pantograph_async" and not top.endswith(".dist-info")
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sdist", type=Path)
    parser.add_argument("wheel", type=Path, nargs="?")
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    args = parser.parse_args(argv)
    errors = check_sdist(args.sdist, args.root)
    if args.wheel is not None:
        errors += check_wheel(args.wheel)
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
