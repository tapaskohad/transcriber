"""Utilities for working with musical notes."""

from __future__ import annotations

from typing import Iterable

CHROMATIC_NOTES: tuple[str, ...] = (
    "C",
    "C#",
    "D",
    "D#",
    "E",
    "F",
    "F#",
    "G",
    "G#",
    "A",
    "A#",
    "B",
)

_NOTE_INDEX = {note: i for i, note in enumerate(CHROMATIC_NOTES)}

# Canonical output is sharp-based pitch classes.
_NOTE_ALIASES: dict[str, str] = {
    "C": "C",
    "B#": "C",
    "C#": "C#",
    "DB": "C#",
    "D": "D",
    "D#": "D#",
    "EB": "D#",
    "E": "E",
    "FB": "E",
    "F": "F",
    "E#": "F",
    "F#": "F#",
    "GB": "F#",
    "G": "G",
    "G#": "G#",
    "AB": "G#",
    "A": "A",
    "A#": "A#",
    "BB": "A#",
    "B": "B",
    "CB": "B",
}


def normalize_note(note: str) -> str:
    """Normalize note names to a canonical sharp representation."""
    cleaned = note.strip().rstrip(",;")
    if not cleaned:
        raise ValueError("Note input is empty.")

    cleaned = cleaned.replace("♯", "#").replace("♭", "b")
    head = cleaned[0].upper()
    tail = cleaned[1:].strip().replace(" ", "")
    tail = tail.replace("b", "B")
    key = f"{head}{tail.upper()}"

    normalized = _NOTE_ALIASES.get(key)
    if normalized is None:
        raise ValueError(f"Invalid note: '{note}'. Use notes like A, A#, Bb, C, F#.")
    return normalized


def normalize_many(notes: Iterable[str]) -> tuple[str, ...]:
    """Normalize many notes and keep only unique pitch classes in input order."""
    ordered_unique: list[str] = []
    seen: set[str] = set()

    for raw in notes:
        note = normalize_note(raw)
        if note not in seen:
            seen.add(note)
            ordered_unique.append(note)
    return tuple(ordered_unique)


def transpose(note: str, semitones: int) -> str:
    """Transpose a note by semitones within one chromatic cycle."""
    normalized = normalize_note(note)
    idx = (_NOTE_INDEX[normalized] + semitones) % len(CHROMATIC_NOTES)
    return CHROMATIC_NOTES[idx]


def note_index(note: str) -> int:
    """Return chromatic index of a normalized note."""
    return _NOTE_INDEX[normalize_note(note)]
