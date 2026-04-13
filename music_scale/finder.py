"""Scale matching engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .notes import CHROMATIC_NOTES, normalize_many, transpose
from .scales import COMMON_SCALE_PATTERNS, ScalePattern


@dataclass(frozen=True)
class ScaleMatch:
    """A matching scale candidate for the current set of notes."""

    root: str
    pattern_name: str
    scale_notes: tuple[str, ...]

    @property
    def label(self) -> str:
        return f"{self.root} {self.pattern_name}"


@dataclass(frozen=True)
class _ScaleCandidate:
    root: str
    pattern_name: str
    scale_notes: tuple[str, ...]
    scale_set: frozenset[str]


class ScaleFinder:
    """Find all scale candidates containing the input notes."""

    def __init__(self, patterns: Sequence[ScalePattern] = COMMON_SCALE_PATTERNS) -> None:
        self._patterns = tuple(patterns)
        self._library = self._build_library()

    def _build_library(self) -> tuple[_ScaleCandidate, ...]:
        candidates: list[_ScaleCandidate] = []

        for root in CHROMATIC_NOTES:
            for pattern in self._patterns:
                scale_notes = tuple(transpose(root, step) for step in pattern.intervals)
                candidates.append(
                    _ScaleCandidate(
                        root=root,
                        pattern_name=pattern.name,
                        scale_notes=scale_notes,
                        scale_set=frozenset(scale_notes),
                    )
                )

        return tuple(candidates)

    def find_matches(
        self,
        input_notes: Iterable[str],
        min_notes: int = 3,
    ) -> list[ScaleMatch]:
        """Return every scale containing all input notes."""
        normalized = normalize_many(input_notes)
        if len(normalized) < min_notes:
            return []

        required = frozenset(normalized)
        matches: list[ScaleMatch] = []

        for candidate in self._library:
            if required.issubset(candidate.scale_set):
                matches.append(
                    ScaleMatch(
                        root=candidate.root,
                        pattern_name=candidate.pattern_name,
                        scale_notes=candidate.scale_notes,
                    )
                )

        root_order = {note: i for i, note in enumerate(CHROMATIC_NOTES)}
        matches.sort(
            key=lambda item: (
                len(item.scale_notes),
                item.pattern_name,
                root_order[item.root],
            )
        )
        return matches
