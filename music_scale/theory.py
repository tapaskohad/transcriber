"""Reusable music theory analysis engine."""

from __future__ import annotations

from dataclasses import asdict, replace
import math
from typing import Iterable, Sequence

from .guitar import STANDARD_TUNING, fret_to_note, fret_to_note_name
from .models import ChordCandidate, IntervalInfo, PositionSuggestion, ScaleAnalysis, TabPosition, stable_id
from .notes import CHROMATIC_NOTES, normalize_many, note_index, transpose
from .scales import COMMON_SCALE_PATTERNS, ScalePattern


INTERVAL_LABELS_BY_SEMITONE: tuple[str, ...] = (
    "1",
    "b2",
    "2",
    "b3",
    "3",
    "4",
    "#4/b5",
    "5",
    "b6",
    "6",
    "b7",
    "7",
)


MODE_FAMILIES: dict[str, str] = {
    "Major (Ionian)": "major",
    "Natural Minor (Aeolian)": "minor",
    "Dorian": "major scale mode",
    "Phrygian": "major scale mode",
    "Lydian": "major scale mode",
    "Mixolydian": "major scale mode",
    "Locrian": "major scale mode",
    "Harmonic Minor": "minor",
    "Melodic Minor": "minor",
    "Major Pentatonic": "pentatonic",
    "Minor Pentatonic": "pentatonic",
    "Blues (Hexatonic)": "blues",
}


SCALE_DESCRIPTIONS: dict[str, str] = {
    "Major (Ionian)": "Stable major sound with a bright tonic center.",
    "Natural Minor (Aeolian)": "Minor sound with a flat third, flat sixth, and flat seventh.",
    "Harmonic Minor": "Minor sound with a raised seventh for stronger dominant pull.",
    "Melodic Minor": "Minor color with raised sixth and seventh scale degrees.",
    "Dorian": "Minor mode with a natural sixth.",
    "Phrygian": "Minor mode with a flat second.",
    "Lydian": "Major mode with a raised fourth.",
    "Mixolydian": "Major-dominant mode with a flat seventh.",
    "Locrian": "Diminished mode with a flat second and flat fifth.",
    "Major Pentatonic": "Five-note major subset with no half-step tension.",
    "Minor Pentatonic": "Five-note minor subset common in guitar phrases.",
    "Blues (Hexatonic)": "Minor pentatonic color with an added blue note.",
}


DIATONIC_MODES: tuple[str, ...] = (
    "Major (Ionian)",
    "Dorian",
    "Phrygian",
    "Lydian",
    "Mixolydian",
    "Natural Minor (Aeolian)",
    "Locrian",
)


DIATONIC_MODE_STEPS: tuple[int, ...] = (0, 2, 4, 5, 7, 9, 11)


CHORD_PATTERNS: tuple[tuple[str, str, tuple[int, ...]], ...] = (
    ("Major", "", (0, 4, 7)),
    ("Minor", "m", (0, 3, 7)),
    ("Diminished", "dim", (0, 3, 6)),
    ("Augmented", "aug", (0, 4, 8)),
    ("Suspended 2", "sus2", (0, 2, 7)),
    ("Suspended 4", "sus4", (0, 5, 7)),
    ("Power Chord", "5", (0, 7)),
    ("Dominant 7", "7", (0, 4, 7, 10)),
    ("Major 7", "maj7", (0, 4, 7, 11)),
    ("Minor 7", "m7", (0, 3, 7, 10)),
    ("Half Diminished", "m7b5", (0, 3, 6, 10)),
    ("Diminished 7", "dim7", (0, 3, 6, 9)),
    ("Added 2", "add2", (0, 2, 4, 7)),
    ("Added 4", "add4", (0, 4, 5, 7)),
    ("Added 6", "6", (0, 4, 7, 9)),
    ("Minor Added 2", "madd2", (0, 2, 3, 7)),
    ("Minor Added 4", "madd4", (0, 3, 5, 7)),
    ("Minor 6", "m6", (0, 3, 7, 9)),
    ("Dominant 9", "9", (0, 2, 4, 7, 10)),
    ("Major 9", "maj9", (0, 2, 4, 7, 11)),
    ("Minor 9", "m9", (0, 2, 3, 7, 10)),
    ("Dominant 11", "11", (0, 4, 5, 7, 10)),
    ("Dominant 13", "13", (0, 4, 7, 9, 10)),
)


COMPATIBLE_CHORDS_BY_PATTERN: dict[str, tuple[str, ...]] = {
    "Major (Ionian)": ("", "m", "m", "", "", "m", "dim"),
    "Natural Minor (Aeolian)": ("m", "dim", "", "m", "m", "", ""),
    "Dorian": ("m", "m", "", "", "m", "dim", ""),
    "Phrygian": ("m", "", "", "m", "dim", "", "m"),
    "Lydian": ("", "", "m", "dim", "", "m", "m"),
    "Mixolydian": ("", "m", "dim", "", "m", "m", ""),
    "Locrian": ("dim", "", "m", "m", "", "", "m"),
}


def _round_score(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def _interval_label(semitone: int) -> str:
    return INTERVAL_LABELS_BY_SEMITONE[semitone % len(INTERVAL_LABELS_BY_SEMITONE)]


def _intervals_for_root(root: str, notes: Sequence[str]) -> tuple[str, ...]:
    root_idx = note_index(root)
    return tuple(_interval_label(note_index(note) - root_idx) for note in notes)


def _notes_from_intervals(root: str, intervals: Sequence[int]) -> tuple[str, ...]:
    return tuple(transpose(root, interval) for interval in intervals)


def _pattern_by_name(patterns: Sequence[ScalePattern], name: str) -> ScalePattern | None:
    for pattern in patterns:
        if pattern.name == name:
            return pattern
    return None


def dataclass_to_dict(value: object) -> dict[str, object]:
    """Convert a model dataclass into JSON-friendly plain structures."""
    converted = asdict(value)
    if isinstance(converted, dict):
        return converted
    raise TypeError("Expected dataclass object.")


class TheoryEngine:
    """Analyze scales, chords, intervals, and guitar positions."""

    def __init__(self, patterns: Sequence[ScalePattern] = COMMON_SCALE_PATTERNS) -> None:
        self._patterns = tuple(patterns)

    def analyze_scales(
        self,
        input_notes: Iterable[str],
        *,
        min_notes: int = 1,
        include_partial: bool = True,
    ) -> list[ScaleAnalysis]:
        notes = normalize_many(input_notes)
        if len(notes) < min_notes:
            return []

        selected = frozenset(notes)
        analyses: list[ScaleAnalysis] = []
        for root in CHROMATIC_NOTES:
            for pattern in self._patterns:
                scale_notes = _notes_from_intervals(root, pattern.intervals)
                scale_set = frozenset(scale_notes)
                contained = tuple(note for note in notes if note in scale_set)
                if not contained:
                    continue

                extra = tuple(note for note in notes if note not in scale_set)
                if extra and not include_partial:
                    continue

                missing = tuple(note for note in scale_notes if note not in selected)
                exact_match = selected == scale_set
                confidence = self._scale_confidence(
                    selected_count=len(notes),
                    scale_count=len(scale_notes),
                    contained_count=len(contained),
                    extra_count=len(extra),
                    exact_match=exact_match,
                )

                if confidence <= 0:
                    continue

                analyses.append(
                    ScaleAnalysis(
                        scale_name=pattern.name,
                        root=root,
                        interval_formula=tuple(_interval_label(step) for step in pattern.intervals),
                        scale_degrees=self.analyze_intervals(
                            notes,
                            root=root,
                            scale_notes=scale_notes,
                        ),
                        contained_notes=contained,
                        confidence=confidence,
                        exact_match=exact_match,
                        missing_notes=missing,
                        extra_notes=extra,
                        relative_major_minor=self._relative_major_minor(root, pattern.name),
                        mode_family=MODE_FAMILIES.get(pattern.name, "other"),
                        description=SCALE_DESCRIPTIONS.get(
                            pattern.name,
                            "Structured scale candidate.",
                        ),
                        pentatonic_equivalent=self._pentatonic_equivalent(root, pattern.name),
                        blues_equivalent=self._blues_equivalent(root, pattern.name),
                        common_modes=self._common_modes(root, pattern.name),
                        compatible_chords=self._compatible_chords(root, pattern),
                    )
                )

        root_order = {note: idx for idx, note in enumerate(CHROMATIC_NOTES)}
        analyses.sort(
            key=lambda item: (
                -item.confidence,
                len(item.extra_notes),
                len(item.missing_notes),
                len(item.contained_notes),
                item.scale_name,
                root_order[item.root],
            )
        )
        return analyses

    @staticmethod
    def _scale_confidence(
        *,
        selected_count: int,
        scale_count: int,
        contained_count: int,
        extra_count: int,
        exact_match: bool,
    ) -> float:
        if selected_count <= 0 or scale_count <= 0:
            return 0.0
        if exact_match:
            return 1.0

        containment = contained_count / selected_count
        coverage = contained_count / scale_count
        extra_penalty = 0.18 * extra_count
        return _round_score((0.72 * containment) + (0.28 * coverage) - extra_penalty)

    def analyze_intervals(
        self,
        input_notes: Iterable[str],
        *,
        root: str,
        scale_notes: Sequence[str] | None = None,
    ) -> tuple[IntervalInfo, ...]:
        notes = normalize_many(input_notes)
        root_note = normalize_many([root])[0]
        root_idx = note_index(root_note)
        scale_set = frozenset(normalize_many(scale_notes or []))

        intervals: list[IntervalInfo] = []
        for note in notes:
            semitone = (note_index(note) - root_idx) % len(CHROMATIC_NOTES)
            intervals.append(
                IntervalInfo(
                    note=note,
                    degree=_interval_label(semitone),
                    semitone=semitone,
                    in_scale=(not scale_set or note in scale_set),
                )
            )
        return tuple(intervals)

    def detect_chords(self, input_notes: Iterable[str]) -> list[ChordCandidate]:
        notes = normalize_many(input_notes)
        if not notes:
            return []

        selected = frozenset(notes)
        candidates: list[ChordCandidate] = []
        for root in CHROMATIC_NOTES:
            if root not in selected:
                continue
            for quality_name, suffix, intervals in CHORD_PATTERNS:
                chord_notes = _notes_from_intervals(root, intervals)
                chord_set = frozenset(chord_notes)
                matched = selected.intersection(chord_set)
                if root not in matched:
                    continue

                missing = chord_set.difference(selected)
                extra = selected.difference(chord_set)
                confidence = self._chord_confidence(
                    selected_count=len(selected),
                    chord_count=len(chord_set),
                    matched_count=len(matched),
                    missing_count=len(missing),
                    extra_count=len(extra),
                )
                if confidence < 0.45:
                    continue

                candidates.append(
                    ChordCandidate(
                        name=self._chord_name(root, suffix, quality_name),
                        root=root,
                        intervals=tuple(_interval_label(interval) for interval in intervals),
                        notes=chord_notes,
                        confidence=confidence,
                        inversion=self._inversion(notes, root, chord_set),
                    )
                )

        root_order = {note: idx for idx, note in enumerate(CHROMATIC_NOTES)}
        candidates.sort(
            key=lambda item: (
                -item.confidence,
                len(item.notes),
                root_order[item.root],
                item.name,
            )
        )
        return candidates

    @staticmethod
    def _chord_confidence(
        *,
        selected_count: int,
        chord_count: int,
        matched_count: int,
        missing_count: int,
        extra_count: int,
    ) -> float:
        if selected_count <= 0 or chord_count <= 0:
            return 0.0
        if matched_count == selected_count == chord_count:
            return 1.0
        coverage = matched_count / chord_count
        precision = matched_count / selected_count
        missing_penalty = 0.08 * missing_count
        extra_penalty = 0.14 * extra_count
        return _round_score((0.58 * precision) + (0.42 * coverage) - missing_penalty - extra_penalty)

    @staticmethod
    def _chord_name(root: str, suffix: str, quality_name: str) -> str:
        if suffix:
            return f"{root}{suffix}"
        if quality_name == "Major":
            return root
        return f"{root} {quality_name}"

    @staticmethod
    def _inversion(notes: Sequence[str], root: str, chord_set: frozenset[str]) -> str | None:
        bass = notes[0] if notes else root
        if bass == root or bass not in chord_set:
            return None
        return bass

    def suggest_positions(
        self,
        input_notes: Iterable[str],
        *,
        min_fret: int = 0,
        max_fret: int = 12,
        window_size: int = 5,
    ) -> list[PositionSuggestion]:
        notes = normalize_many(input_notes)
        if not notes:
            return []
        if min_fret < 0 or max_fret < min_fret:
            raise ValueError("Fret range is invalid.")
        if window_size < 1:
            raise ValueError("window_size must be positive.")

        all_positions = self._positions_for_notes(notes, min_fret=min_fret, max_fret=max_fret)
        if not all_positions:
            return []

        suggestions: list[PositionSuggestion] = []
        position_number = 1
        for start_fret in range(min_fret, max_fret + 1):
            end_fret = min(max_fret, start_fret + window_size - 1)
            selected_positions = [
                position
                for position in all_positions
                if start_fret <= position.fret <= end_fret
            ]
            covered_notes = {position.note for position in selected_positions}
            if not set(notes).issubset(covered_notes):
                continue

            representative = self._representative_positions(notes, selected_positions)
            if not representative:
                continue
            frets = [position.fret for position in representative]
            span = max(frets) - min(frets)
            average_fret = sum(frets) / len(frets)
            movement = self._movement_estimate(representative)
            open_usage = sum(1 for position in representative if position.fret == 0)
            confidence = self._position_confidence(
                span=span,
                movement=movement,
                open_usage=open_usage,
                note_count=len(notes),
                window_size=window_size,
            )
            suggestions.append(
                PositionSuggestion(
                    position_number=position_number,
                    average_fret=round(average_fret, 2),
                    span=span,
                    movement_estimate=round(movement, 2),
                    open_string_usage=open_usage,
                    confidence=confidence,
                    positions=tuple(
                        replace(position, position_id=stable_id("position", idx))
                        for idx, position in enumerate(representative, start=1)
                    ),
                )
            )
            position_number += 1

        suggestions.sort(
            key=lambda item: (
                -item.confidence,
                item.span,
                item.movement_estimate,
                item.average_fret,
            )
        )
        return [
            replace(suggestion, position_number=index)
            for index, suggestion in enumerate(suggestions[:8], start=1)
        ]

    @staticmethod
    def _positions_for_notes(
        notes: Sequence[str],
        *,
        min_fret: int,
        max_fret: int,
    ) -> list[TabPosition]:
        note_set = frozenset(notes)
        positions: list[TabPosition] = []
        index = 1
        for string_id in sorted(STANDARD_TUNING.keys()):
            for fret in range(min_fret, max_fret + 1):
                note = fret_to_note(string_id, fret)
                if note not in note_set:
                    continue
                note_name = fret_to_note_name(string_id, fret)
                octave = int(note_name[len(note) :])
                positions.append(
                    TabPosition(
                        position_id=stable_id("position", index),
                        event_id="",
                        string_id=string_id,
                        fret=fret,
                        midi=0,
                        note=note,
                        octave=octave,
                        source="theory",
                    )
                )
                index += 1
        return positions

    @staticmethod
    def _representative_positions(
        notes: Sequence[str],
        positions: Sequence[TabPosition],
    ) -> list[TabPosition]:
        representatives: list[TabPosition] = []
        previous: TabPosition | None = None
        for note in notes:
            options = [position for position in positions if position.note == note]
            if not options:
                return []
            if previous is None:
                chosen = min(options, key=lambda item: (item.fret == 0, item.fret, item.string_id))
            else:
                chosen = min(
                    options,
                    key=lambda item: (
                        abs(item.fret - previous.fret) + (0.55 * abs(item.string_id - previous.string_id)),
                        item.fret,
                        item.string_id,
                    ),
                )
            representatives.append(chosen)
            previous = chosen
        return representatives

    @staticmethod
    def _movement_estimate(positions: Sequence[TabPosition]) -> float:
        if len(positions) < 2:
            return 0.0
        movement = 0.0
        for previous, current in zip(positions, positions[1:]):
            movement += abs(current.fret - previous.fret)
            movement += 0.55 * abs(current.string_id - previous.string_id)
        return movement

    @staticmethod
    def _position_confidence(
        *,
        span: int,
        movement: float,
        open_usage: int,
        note_count: int,
        window_size: int,
    ) -> float:
        span_score = 1.0 - min(1.0, span / max(1, window_size))
        movement_score = 1.0 - min(1.0, movement / max(1.0, note_count * 4.0))
        open_bonus = min(0.12, open_usage * 0.03)
        return _round_score((0.54 * span_score) + (0.46 * movement_score) + open_bonus)

    def _relative_major_minor(self, root: str, pattern_name: str) -> dict[str, str]:
        if pattern_name == "Major (Ionian)":
            return {"type": "relative_minor", "root": transpose(root, 9), "scale_name": "Natural Minor (Aeolian)"}
        if pattern_name == "Natural Minor (Aeolian)":
            return {"type": "relative_major", "root": transpose(root, 3), "scale_name": "Major (Ionian)"}
        return {}

    @staticmethod
    def _pentatonic_equivalent(root: str, pattern_name: str) -> dict[str, str] | None:
        if pattern_name in {"Major (Ionian)", "Lydian", "Mixolydian"}:
            return {"root": root, "scale_name": "Major Pentatonic"}
        if pattern_name in {"Natural Minor (Aeolian)", "Dorian", "Phrygian"}:
            return {"root": root, "scale_name": "Minor Pentatonic"}
        return None

    @staticmethod
    def _blues_equivalent(root: str, pattern_name: str) -> dict[str, str] | None:
        if pattern_name in {"Natural Minor (Aeolian)", "Dorian", "Minor Pentatonic", "Blues (Hexatonic)"}:
            return {"root": root, "scale_name": "Blues (Hexatonic)"}
        if pattern_name in {"Major (Ionian)", "Major Pentatonic"}:
            return {"root": transpose(root, 9), "scale_name": "Blues (Hexatonic)"}
        return None

    def _common_modes(self, root: str, pattern_name: str) -> tuple[dict[str, str], ...]:
        if pattern_name not in DIATONIC_MODES:
            return ()

        mode_index = DIATONIC_MODES.index(pattern_name)
        parent_major = transpose(root, -DIATONIC_MODE_STEPS[mode_index])
        modes: list[dict[str, str]] = []
        for index, mode_name in enumerate(DIATONIC_MODES):
            modes.append(
                {
                    "root": transpose(parent_major, DIATONIC_MODE_STEPS[index]),
                    "scale_name": mode_name,
                }
            )
        return tuple(modes)

    def _compatible_chords(
        self,
        root: str,
        pattern: ScalePattern,
    ) -> tuple[ChordCandidate, ...]:
        qualities = COMPATIBLE_CHORDS_BY_PATTERN.get(pattern.name)
        if not qualities:
            return ()

        chords: list[ChordCandidate] = []
        for degree_index, suffix in enumerate(qualities):
            chord_root = transpose(root, pattern.intervals[degree_index])
            quality_name = {
                "": "Major",
                "m": "Minor",
                "dim": "Diminished",
            }.get(suffix, "Chord")
            intervals = {
                "": (0, 4, 7),
                "m": (0, 3, 7),
                "dim": (0, 3, 6),
            }.get(suffix, (0, 4, 7))
            chords.append(
                ChordCandidate(
                    name=self._chord_name(chord_root, suffix, quality_name),
                    root=chord_root,
                    intervals=tuple(_interval_label(interval) for interval in intervals),
                    notes=_notes_from_intervals(chord_root, intervals),
                    confidence=1.0,
                )
            )
        return tuple(chords)
