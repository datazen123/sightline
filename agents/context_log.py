"""Context inspector: records exactly what each agent saw, for the UI panel.

This is one of the two features the build spec calls out as non-cuttable —
it's the visible proof of "context management is the game."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class ContextEntry:
    agent: str
    system_prompt: str
    retrieved_context: list[str]
    excluded: str
    tokens_in: int
    tokens_out: int
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )


class ContextLog:
    def __init__(self) -> None:
        self.entries: list[ContextEntry] = []

    def record(
        self,
        agent: str,
        system_prompt: str,
        retrieved_context: list[str],
        excluded: str,
        tokens_in: int,
        tokens_out: int,
    ) -> ContextEntry:
        entry = ContextEntry(
            agent=agent,
            system_prompt=system_prompt,
            retrieved_context=retrieved_context,
            excluded=excluded,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        self.entries.append(entry)
        return entry

    def clear(self) -> None:
        self.entries.clear()
