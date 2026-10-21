"""Helpers shared by the real-child tests; fixtures live in conftest.py."""

import asyncio
import json
import os
from pathlib import Path

import pytest


FAKE = Path(__file__).parent / "fixtures" / "fake_repl.py"


def records(report):
    return (
        [json.loads(line) for line in report.read_text().splitlines()]
        if report.exists()
        else []
    )


def assert_reaped(report):
    for pid in {entry["pid"] for entry in records(report)}:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


async def wait_event(report, kind, **fields):
    deadline = asyncio.get_running_loop().time() + 3
    while asyncio.get_running_loop().time() < deadline:
        if any(
            row["kind"] == kind
            and all(row.get(key) == value for key, value in fields.items())
            for row in records(report)
        ):
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"Child event missing: {kind} {fields}; {records(report)}")


def run(body):
    async def checked():
        errors = []
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda _loop, context: errors.append(context))
        await body()
        await asyncio.sleep(0)
        assert not errors
        assert not [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
            and task.get_name().startswith("pantograph-")
        ]

    asyncio.run(checked(), debug=True)
