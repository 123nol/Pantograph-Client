"""``pantograph-client`` command line; needs no checkout, Git, or consumer files."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .diagnostics import verify_live_client
from .environment import PantographEnv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pantograph-client",
        description="Portable checks for the custom Pantograph REPL contract.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    smoke = commands.add_parser(
        "smoke",
        help="Run the live protocol checks against an explicit REPL build.",
    )
    smoke.add_argument("--source-root", type=Path, required=True)
    smoke.add_argument("--pantograph-repl", type=Path, required=True)
    smoke.add_argument("--build-manifest", type=Path)
    smoke.add_argument(
        "--import",
        dest="imports",
        action="append",
        help="Lean module to import; repeatable (default: Init).",
    )
    smoke.add_argument("--proofs", type=int, default=100)
    smoke.add_argument(
        "--allow-partial",
        action="store_true",
        help="Report checks the imports cannot run instead of failing.",
    )
    smoke.add_argument(
        "--report",
        type=Path,
        help="Write evidence to a new JSON file; never overwrite.",
    )
    smoke.add_argument("--response-line-limit", type=int, default=8 * 1024 * 1024)
    smoke.add_argument("--stderr-tail-limit", type=int, default=64 * 1024)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.report is not None and args.report.exists():
        parser.error(f"Report already exists: {args.report}")
    env = PantographEnv(
        source_root=args.source_root,
        pantograph_repl=args.pantograph_repl,
        imports=tuple(args.imports or ("Init",)),
        build_manifest=args.build_manifest,
        response_line_limit=args.response_line_limit,
        stderr_tail_limit=args.stderr_tail_limit,
    )
    report = asyncio.run(
        verify_live_client(env, proofs=args.proofs, require_all=not args.allow_partial)
    )
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x") as stream:
            stream.write(text)
    print(text, end="")


if __name__ == "__main__":
    main()
