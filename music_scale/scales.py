"""Scale definitions used by the finder engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScalePattern:
    """Named interval pattern relative to a root note."""

    name: str
    intervals: tuple[int, ...]


COMMON_SCALE_PATTERNS: tuple[ScalePattern, ...] = (
    ScalePattern("Major (Ionian)", (0, 2, 4, 5, 7, 9, 11)),
    ScalePattern("Natural Minor (Aeolian)", (0, 2, 3, 5, 7, 8, 10)),
    ScalePattern("Harmonic Minor", (0, 2, 3, 5, 7, 8, 11)),
    ScalePattern("Melodic Minor", (0, 2, 3, 5, 7, 9, 11)),
    ScalePattern("Dorian", (0, 2, 3, 5, 7, 9, 10)),
    ScalePattern("Phrygian", (0, 1, 3, 5, 7, 8, 10)),
    ScalePattern("Lydian", (0, 2, 4, 6, 7, 9, 11)),
    ScalePattern("Mixolydian", (0, 2, 4, 5, 7, 9, 10)),
    ScalePattern("Locrian", (0, 1, 3, 5, 6, 8, 10)),
    ScalePattern("Major Pentatonic", (0, 2, 4, 7, 9)),
    ScalePattern("Minor Pentatonic", (0, 3, 5, 7, 10)),
    ScalePattern("Blues (Hexatonic)", (0, 3, 5, 6, 7, 10)),
)
