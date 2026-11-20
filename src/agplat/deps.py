"""What a tool is allowed to know about the run it is serving."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RunDeps:
    """Carried through every tool call and child run.

    Frozen on purpose: a tool cannot change the identity of the run it belongs
    to. Delegation creates a new RunDeps with a higher depth instead of mutating
    this one, which is what keeps a run tree traceable.
    """

    run_id: str
    agent: str
    depth: int = 0
