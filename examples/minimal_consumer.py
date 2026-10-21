"""Minimal consumer: start a scope, apply valid and rejected tactics, close.

    python minimal_consumer.py /path/to/source_root /path/to/repl [Import ...]

Needs only pantograph-async-client and a compatible REPL build.
"""

import asyncio
from pathlib import Path
import sys

from pantograph_async import (
    PantographClient,
    PantographEnv,
    PantographTacticRejected,
    TacticState,
)


async def main(source_root: Path, repl: Path, imports: tuple[str, ...]) -> None:
    env = PantographEnv(source_root=source_root, pantograph_repl=repl, imports=imports)
    async with await PantographClient.create(env) as client:
        async with client.state_scope() as scope:
            root = await scope.start_goal("∀ (p : Prop), p → p")
            state = await scope.apply_tactic(root, "intro p h", goal_index=0)
            assert isinstance(state, TacticState)
            goal = state.goals[0]
            print("target:", goal.target.pp, "| model:", goal.target.model_sexp)
            print("locals:", [(local.user_name, local.type.pp) for local in goal.locals])
            try:
                await scope.apply_tactic(state, "exact False", goal_index=0)
            except PantographTacticRejected as exc:
                print("rejected:", str(exc).splitlines()[0])
            done = await scope.apply_tactic(state, "exact h", goal_index=0)
            print("closed:", not done.goals)
        print("states after scope:", (await client.stat()).n_goals)
    print("phase:", client.phase.value)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2]), tuple(sys.argv[3:]) or ("Init",)))
