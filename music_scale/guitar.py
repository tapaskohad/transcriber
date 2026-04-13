"""Utilities for converting guitar tab positions into notes."""

from __future__ import annotations

from .notes import CHROMATIC_NOTES, transpose

# Standard tuning with string numbers: 6 = low E, 1 = high E.
STANDARD_TUNING: dict[int, str] = {
    1: "E",
    2: "B",
    4: "D",
    3: "G",
    5: "A",
    6: "E",
}

# Standard tuning in MIDI notes, used for octave-aware note names.
_STANDARD_TUNING_MIDI: dict[int, int] = {
    1: 64,  # E4
    2: 59,  # B3
    3: 55,  # G3
    4: 50,  # D3
    5: 45,  # A2
    6: 40,  # E2
}

_STRING_ALIASES: dict[str, int] = {
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "E4": 1,
    "B3": 2,
    "G3": 3,
    "D3": 4,
    "A2": 5,
    "E2": 6,
    "HIGHE": 1,
    "LOWE": 6,
}


def parse_string_id(raw: str) -> int:
    """Parse user input string id into canonical guitar string number."""
    key = raw.strip().upper().replace(" ", "")
    string_id = _STRING_ALIASES.get(key)
    if string_id is None:
        raise ValueError(
            f"Invalid string '{raw}'. Use 1-6 or aliases like E2, A2, D3, G3, B3, E4."
        )
    return string_id


def parse_fret(raw: str) -> int:
    """Parse a non-negative fret number."""
    try:
        fret = int(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid fret '{raw}'. Use a non-negative integer.") from exc

    if fret < 0:
        raise ValueError(f"Invalid fret '{raw}'. Fret cannot be negative.")
    return fret


def parse_tab_position(token: str) -> tuple[int, int]:
    """Parse tab token in the form <string>:<fret>."""
    parts = token.split(":", 1)
    if len(parts) != 2:
        raise ValueError(
            f"Invalid tab token '{token}'. Use format like 6:3 or E2:3."
        )

    string_id = parse_string_id(parts[0])
    fret = parse_fret(parts[1])
    return string_id, fret


def fret_to_note(string_id: int, fret: int) -> str:
    """Convert guitar string/fret position to pitch class note name."""
    open_note = STANDARD_TUNING.get(string_id)
    if open_note is None:
        raise ValueError(f"Invalid string number '{string_id}'. Use 1-6.")

    if fret < 0:
        raise ValueError("Fret cannot be negative.")

    return transpose(open_note, fret)


def fret_to_note_name(string_id: int, fret: int) -> str:
    """Convert guitar string/fret position to octave-aware note name."""
    open_midi = _STANDARD_TUNING_MIDI.get(string_id)
    if open_midi is None:
        raise ValueError(f"Invalid string number '{string_id}'. Use 1-6.")

    if fret < 0:
        raise ValueError("Fret cannot be negative.")

    midi = open_midi + fret
    note = CHROMATIC_NOTES[midi % len(CHROMATIC_NOTES)]
    octave = (midi // len(CHROMATIC_NOTES)) - 1
    return f"{note}{octave}"
