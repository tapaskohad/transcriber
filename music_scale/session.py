"""State container for interactive melody input."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .finder import ScaleFinder, ScaleMatch
from .guitar import fret_to_note, parse_fret, parse_string_id, parse_tab_position
from .notes import normalize_note


@dataclass
class MelodySession:
    """Track entered notes and query matching scales live."""

    finder: ScaleFinder = field(default_factory=ScaleFinder)
    min_notes_for_match: int = 3
    _notes: list[str] = field(default_factory=list)
    _note_set: set[str] = field(default_factory=set)
    _history: list[list[str]] = field(default_factory=list)

    @property
    def notes(self) -> tuple[str, ...]:
        return tuple(self._notes)

    @property
    def note_count(self) -> int:
        return len(self._note_set)

    def add_notes(self, raw_notes: Iterable[str]) -> list[str]:
        """Add note-name input (A, A#, Bb, ...)."""
        added: list[str] = []

        for token in raw_notes:
            note = normalize_note(token)
            if note not in self._note_set:
                self._note_set.add(note)
                self._notes.append(note)
                added.append(note)

        if added:
            self._history.append(added)
        return added

    def add_tab(self, raw_tokens: Iterable[str]) -> list[str]:
        """Add notes from guitar positions."""
        tokens = list(raw_tokens)
        positions = self._parse_tab_tokens(tokens)

        added: list[str] = []
        for string_id, fret in positions:
            note = fret_to_note(string_id, fret)
            if note not in self._note_set:
                self._note_set.add(note)
                self._notes.append(note)
                added.append(note)

        if added:
            self._history.append(added)
        return added

    def _parse_tab_tokens(self, tokens: list[str]) -> list[tuple[int, int]]:
        if not tokens:
            raise ValueError("No tab positions provided.")

        uses_colon_format = any(":" in token for token in tokens)
        if uses_colon_format:
            return [parse_tab_position(token) for token in tokens]

        if len(tokens) % 2 != 0:
            raise ValueError(
                "Tab input without ':' must be pairs: <string> <fret> [<string> <fret> ...]."
            )

        pairs: list[tuple[int, int]] = []
        for i in range(0, len(tokens), 2):
            string_id = parse_string_id(tokens[i])
            fret = parse_fret(tokens[i + 1])
            pairs.append((string_id, fret))
        return pairs

    def get_matches(self) -> list[ScaleMatch]:
        return self.finder.find_matches(self._notes, min_notes=self.min_notes_for_match)

    def undo(self) -> list[str]:
        """Remove notes that were added in the last successful add command."""
        if not self._history:
            return []

        removed = self._history.pop()
        for note in removed:
            self._note_set.remove(note)
            self._notes.remove(note)
        return removed

    def clear(self) -> None:
        self._notes.clear()
        self._note_set.clear()
        self._history.clear()
