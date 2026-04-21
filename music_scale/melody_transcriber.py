"""Independent melody-to-note-and-tab transcription helpers.

This module is intentionally decoupled from the current app flow so it can be
integrated later as a standalone extension.
"""

from __future__ import annotations

import math
import re
import struct
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .notes import CHROMATIC_NOTES, note_index, normalize_note

# Standard tuning in MIDI note numbers.
_STANDARD_TUNING_MIDI: dict[int, int] = {
    6: 40,  # E2
    5: 45,  # A2
    4: 50,  # D3
    3: 55,  # G3
    2: 59,  # B3
    1: 64,  # E4
}

_NOTE_WITH_OCTAVE_RE = re.compile(r"^\s*([A-Ga-g])([#b]?)(\+*)(-?\d+)?\s*$")
_COMPACT_NOTE_RE = re.compile(r"([A-Ga-g])([#b]?)(\+*)(-?\d+)?")
_COMPACT_NOTE_CHARS_RE = re.compile(r"^[A-Ga-g#b+\-0-9]+$")


@dataclass(frozen=True, slots=True)
class MelodyEvent:
    """A detected or provided melody note event."""

    note: str
    octave: int
    midi: int
    frequency_hz: float
    start_s: float
    end_s: float

    @property
    def note_name(self) -> str:
        return f"{self.note}{self.octave}"


@dataclass(frozen=True, slots=True)
class TabPosition:
    """A single guitar tab position for one melody event."""

    string_id: int
    fret: int
    midi: int
    note: str
    octave: int

    @property
    def tab_token(self) -> str:
        return f"{self.string_id}:{self.fret}"


@dataclass(frozen=True, slots=True)
class MelodyTabResult:
    """Result bundle with note events and chosen tab positions."""

    events: tuple[MelodyEvent, ...]
    tabs: tuple[TabPosition, ...]

    @property
    def notes(self) -> tuple[str, ...]:
        return tuple(event.note_name for event in self.events)

    @property
    def tab_tokens(self) -> tuple[str, ...]:
        return tuple(tab.tab_token for tab in self.tabs)

    @property
    def ascii_tab(self) -> str:
        """Render selected tab positions as six-line ASCII guitar tab."""
        return format_ascii_tab(self.tabs)


def midi_to_note(midi: int) -> tuple[str, int]:
    """Convert MIDI number to (note, octave)."""
    if midi < 0:
        raise ValueError("MIDI note cannot be negative.")

    note = CHROMATIC_NOTES[midi % len(CHROMATIC_NOTES)]
    octave = (midi // len(CHROMATIC_NOTES)) - 1
    return note, octave


def note_to_midi(note: str, octave: int) -> int:
    """Convert note + octave to MIDI number."""
    return (octave + 1) * len(CHROMATIC_NOTES) + note_index(note)


def midi_to_frequency(midi: int, a4_hz: float = 440.0) -> float:
    """Convert MIDI number to frequency in Hz."""
    return a4_hz * (2 ** ((midi - 69) / 12))


def frequency_to_midi(frequency_hz: float, a4_hz: float = 440.0) -> int:
    """Map frequency to nearest MIDI number."""
    if frequency_hz <= 0:
        raise ValueError("Frequency must be positive.")
    return int(round(69 + 12 * math.log2(frequency_hz / a4_hz)))


def frequency_to_note(frequency_hz: float, a4_hz: float = 440.0) -> tuple[str, int, int]:
    """Map frequency to nearest (note, octave, midi)."""
    midi = frequency_to_midi(frequency_hz, a4_hz=a4_hz)
    note, octave = midi_to_note(midi)
    return note, octave, midi


class MelodyTranscriber:
    """Transcribe melodies into normalized notes and playable guitar tabs."""

    def __init__(
        self,
        *,
        min_freq_hz: float = 82.0,
        max_freq_hz: float = 1000.0,
        min_fret: int = 0,
        max_fret: int = 15,
        min_note_duration_s: float = 0.08,
    ) -> None:
        if min_freq_hz <= 0 or max_freq_hz <= min_freq_hz:
            raise ValueError("Frequency bounds are invalid.")
        if min_fret < 0 or max_fret < min_fret:
            raise ValueError("Fret bounds are invalid.")
        if min_note_duration_s <= 0:
            raise ValueError("min_note_duration_s must be positive.")

        self.min_freq_hz = min_freq_hz
        self.max_freq_hz = max_freq_hz
        self.min_fret = min_fret
        self.max_fret = max_fret
        self.min_note_duration_s = min_note_duration_s

        self._playable_min_midi = min(_STANDARD_TUNING_MIDI.values()) + min_fret
        self._playable_max_midi = max(_STANDARD_TUNING_MIDI.values()) + max_fret

    def transcribe_notes(
        self,
        note_tokens: Iterable[str],
        *,
        note_duration_s: float = 0.35,
    ) -> MelodyTabResult:
        """Transcribe explicit note tokens (with or without octave) to tabs."""
        if note_duration_s <= 0:
            raise ValueError("note_duration_s must be positive.")

        events: list[MelodyEvent] = []
        previous_midi: int | None = None
        current_time = 0.0

        for raw in note_tokens:
            note, octave, enforce_octave = self._parse_note_token(raw)
            midi = self._resolve_midi(
                note, octave, previous_midi, enforce_octave=enforce_octave
            )
            previous_midi = midi

            note_name, detected_octave = midi_to_note(midi)
            events.append(
                MelodyEvent(
                    note=note_name,
                    octave=detected_octave,
                    midi=midi,
                    frequency_hz=midi_to_frequency(midi),
                    start_s=current_time,
                    end_s=current_time + note_duration_s,
                )
            )
            current_time += note_duration_s

        tabs = self.map_events_to_tabs(events)
        return MelodyTabResult(events=tuple(events), tabs=tabs)

    @staticmethod
    def filter_note_tokens(note_tokens: Iterable[str]) -> list[str]:
        """Keep valid note tokens and ignore free-text tokens.

        If explicit octave tokens are present (e.g. E4, F#3), only those are
        returned so lyric words like "a" are not mistaken for note A.
        """
        valid_tokens: list[str] = []
        explicit_octave_tokens: list[str] = []

        for raw in note_tokens:
            extracted_tokens = MelodyTranscriber._extract_note_tokens(str(raw))
            for token in extracted_tokens:
                valid_tokens.append(token)
                if any(char.isdigit() for char in token):
                    explicit_octave_tokens.append(token)

        return explicit_octave_tokens if explicit_octave_tokens else valid_tokens

    @staticmethod
    def _extract_note_tokens(raw_token: str) -> list[str]:
        token = (
            str(raw_token)
            .strip()
            .replace("\u266f", "#")
            .replace("\u266d", "b")
            .rstrip(",;")
        )
        if not token:
            return []

        if _NOTE_WITH_OCTAVE_RE.match(token) is not None:
            return [token]

        # Accept compact blobs like D#G#A#G# or F#+E+ while still ignoring
        # free text lyrics.
        if _COMPACT_NOTE_CHARS_RE.match(token) is None:
            return []
        if not any(char in "#+0123456789" for char in token):
            return []

        extracted: list[str] = []
        for match in _COMPACT_NOTE_RE.finditer(token):
            compact_token = (
                f"{match.group(1)}"
                f"{match.group(2) or ''}"
                f"{match.group(3) or ''}"
                f"{match.group(4) or ''}"
            )
            if compact_token:
                extracted.append(compact_token)
        return extracted

    def transcribe_frequencies(
        self,
        frequencies_hz: Iterable[float],
        *,
        frame_step_s: float = 0.01,
    ) -> MelodyTabResult:
        """Transcribe a sequence of frequency frames to notes and tabs."""
        if frame_step_s <= 0:
            raise ValueError("frame_step_s must be positive.")

        pitch_track: list[float | None] = []
        for value in frequencies_hz:
            if value is None or value <= 0:
                pitch_track.append(None)
                continue

            if self.min_freq_hz <= value <= self.max_freq_hz:
                pitch_track.append(float(value))
            else:
                pitch_track.append(None)

        smoothed = self._median_smooth_pitch_track(pitch_track, window=5)
        events = self._events_from_pitch_track(smoothed, frame_step_s=frame_step_s)
        tabs = self.map_events_to_tabs(events)
        return MelodyTabResult(events=tuple(events), tabs=tabs)

    def transcribe_wav(
        self,
        wav_path: str | Path,
        *,
        frame_size_ms: float = 40.0,
        frame_hop_ms: float = 10.0,
    ) -> MelodyTabResult:
        """Transcribe a mono/stereo PCM wav file to notes and tabs."""
        if frame_size_ms <= 0 or frame_hop_ms <= 0:
            raise ValueError("frame_size_ms and frame_hop_ms must be positive.")

        sample_rate, samples = _read_wav_mono(Path(wav_path))
        if not samples:
            return MelodyTabResult(events=(), tabs=())

        frame_size = max(64, int(sample_rate * (frame_size_ms / 1000.0)))
        frame_hop = max(16, int(sample_rate * (frame_hop_ms / 1000.0)))
        pitch_track = self._extract_pitch_track(
            samples,
            sample_rate=sample_rate,
            frame_size=frame_size,
            frame_hop=frame_hop,
        )
        smoothed = self._median_smooth_pitch_track(pitch_track, window=5)
        events = self._events_from_pitch_track(
            smoothed, frame_step_s=(frame_hop / sample_rate)
        )
        tabs = self.map_events_to_tabs(events)
        return MelodyTabResult(events=tuple(events), tabs=tabs)

    def map_events_to_tabs(self, events: Sequence[MelodyEvent]) -> tuple[TabPosition, ...]:
        """Find a smooth guitar fingering path for the melody events."""
        if not events:
            return ()

        candidates_per_event: list[list[TabPosition]] = []
        for event in events:
            candidates = self._candidate_positions(event.midi)
            if not candidates:
                raise ValueError(
                    f"No playable tab position for {event.note_name} within frets "
                    f"{self.min_fret}-{self.max_fret}."
                )
            candidates_per_event.append(candidates)

        scores: list[list[float]] = [
            [math.inf for _ in event_candidates]
            for event_candidates in candidates_per_event
        ]
        parents: list[list[int | None]] = [
            [None for _ in event_candidates] for event_candidates in candidates_per_event
        ]

        for j, position in enumerate(candidates_per_event[0]):
            scores[0][j] = self._position_cost(position)

        for i in range(1, len(candidates_per_event)):
            current_options = candidates_per_event[i]
            previous_options = candidates_per_event[i - 1]
            for j, current_position in enumerate(current_options):
                best_score = math.inf
                best_parent: int | None = None
                for k, previous_position in enumerate(previous_options):
                    candidate_score = (
                        scores[i - 1][k]
                        + self._transition_cost(previous_position, current_position)
                    )
                    if candidate_score < best_score:
                        best_score = candidate_score
                        best_parent = k
                scores[i][j] = best_score
                parents[i][j] = best_parent

        last_index = min(
            range(len(scores[-1])),
            key=lambda idx: scores[-1][idx]
            + self._position_cost(candidates_per_event[-1][idx]),
        )
        chosen: list[TabPosition] = []
        current_idx: int | None = last_index
        for event_idx in range(len(candidates_per_event) - 1, -1, -1):
            if current_idx is None:
                raise RuntimeError("Internal finger-path reconstruction failed.")
            chosen.append(candidates_per_event[event_idx][current_idx])
            current_idx = parents[event_idx][current_idx]

        chosen.reverse()
        return tuple(chosen)

    def _parse_note_token(self, token: str) -> tuple[str, int | None, bool]:
        match = _NOTE_WITH_OCTAVE_RE.match(token)
        if match is None:
            raise ValueError(
                f"Invalid note token '{token}'. Use formats like C, F#, Bb3, G4, C#+."
            )

        note = normalize_note(f"{match.group(1)}{match.group(2) or ''}")
        plus_marks = match.group(3) or ""
        octave_raw = match.group(4)
        if octave_raw is not None:
            return note, int(octave_raw), True
        if plus_marks:
            return note, 4 + len(plus_marks), False
        return note, None, False

    def _resolve_midi(
        self,
        note: str,
        octave: int | None,
        previous_midi: int | None,
        *,
        enforce_octave: bool = True,
    ) -> int:
        if octave is not None:
            preferred_midi = note_to_midi(note, octave)
            if enforce_octave:
                if not self._candidate_positions(preferred_midi):
                    raise ValueError(
                        f"Note {note}{octave} is outside playable range for frets "
                        f"{self.min_fret}-{self.max_fret}."
                    )
                return preferred_midi

            pitch_class = note_index(note)
            candidates = [
                midi
                for midi in range(self._playable_min_midi, self._playable_max_midi + 1)
                if midi % len(CHROMATIC_NOTES) == pitch_class
                and self._candidate_positions(midi)
            ]
            if not candidates:
                raise ValueError(
                    f"No playable octave found for note {note} in range "
                    f"{self._playable_min_midi}-{self._playable_max_midi}."
                )

            if previous_midi is not None:
                return min(
                    candidates,
                    key=lambda midi: (
                        abs(midi - preferred_midi),
                        abs(midi - previous_midi),
                        midi,
                    ),
                )
            return min(candidates, key=lambda midi: (abs(midi - preferred_midi), midi))

        pitch_class = note_index(note)
        candidates = [
            midi
            for midi in range(self._playable_min_midi, self._playable_max_midi + 1)
            if midi % len(CHROMATIC_NOTES) == pitch_class and self._candidate_positions(midi)
        ]
        if not candidates:
            raise ValueError(
                f"No playable octave found for note {note} in range "
                f"{self._playable_min_midi}-{self._playable_max_midi}."
            )

        if previous_midi is not None:
            return min(candidates, key=lambda midi: (abs(midi - previous_midi), midi))

        preferred = note_to_midi(note, 4)
        return min(candidates, key=lambda midi: (abs(midi - preferred), midi))

    def _candidate_positions(self, midi: int) -> list[TabPosition]:
        note, octave = midi_to_note(midi)
        options: list[TabPosition] = []
        for string_id, open_midi in _STANDARD_TUNING_MIDI.items():
            fret = midi - open_midi
            if self.min_fret <= fret <= self.max_fret:
                options.append(
                    TabPosition(
                        string_id=string_id,
                        fret=fret,
                        midi=midi,
                        note=note,
                        octave=octave,
                    )
                )

        options.sort(key=lambda position: (position.fret, position.string_id))
        return options

    @staticmethod
    def _position_cost(position: TabPosition) -> float:
        return 0.08 * position.fret + 0.04 * abs(position.string_id - 2)

    @staticmethod
    def _transition_cost(previous: TabPosition, current: TabPosition) -> float:
        fret_move = abs(current.fret - previous.fret)
        string_move = abs(current.string_id - previous.string_id)
        return fret_move + (0.55 * string_move) + (0.05 * current.fret)

    def _extract_pitch_track(
        self,
        samples: Sequence[float],
        *,
        sample_rate: int,
        frame_size: int,
        frame_hop: int,
    ) -> list[float | None]:
        if len(samples) < frame_size:
            return []

        frame_starts = range(0, len(samples) - frame_size + 1, frame_hop)
        frames: list[Sequence[float]] = []
        rms_values: list[float] = []

        for start in frame_starts:
            frame = samples[start : start + frame_size]
            frames.append(frame)
            rms_values.append(_rms(frame))

        if not rms_values:
            return []

        sorted_rms = sorted(rms_values)
        noise_floor = sorted_rms[max(0, len(sorted_rms) // 6)]
        threshold = max(0.008, noise_floor * 2.5)

        pitch_track: list[float | None] = []
        for frame, rms_value in zip(frames, rms_values):
            if rms_value < threshold:
                pitch_track.append(None)
                continue

            pitch = _autocorrelation_pitch(
                frame,
                sample_rate=sample_rate,
                min_freq_hz=self.min_freq_hz,
                max_freq_hz=self.max_freq_hz,
            )
            pitch_track.append(pitch)
        return pitch_track

    @staticmethod
    def _median_smooth_pitch_track(
        pitch_track: Sequence[float | None], *, window: int
    ) -> list[float | None]:
        if window < 1 or window % 2 == 0:
            raise ValueError("window must be an odd positive integer.")

        half = window // 2
        smoothed: list[float | None] = []
        for i in range(len(pitch_track)):
            left = max(0, i - half)
            right = min(len(pitch_track), i + half + 1)
            values = [value for value in pitch_track[left:right] if value is not None]
            if not values:
                smoothed.append(None)
                continue

            values.sort()
            smoothed.append(values[len(values) // 2])
        return smoothed

    def _events_from_pitch_track(
        self, pitch_track: Sequence[float | None], *, frame_step_s: float
    ) -> list[MelodyEvent]:
        if not pitch_track:
            return []

        midi_track: list[int | None] = []
        for frequency in pitch_track:
            if frequency is None:
                midi_track.append(None)
                continue

            detected_midi = frequency_to_midi(frequency)
            if self._playable_min_midi <= detected_midi <= self._playable_max_midi:
                midi_track.append(detected_midi)
            else:
                midi_track.append(None)

        events: list[MelodyEvent] = []
        i = 0
        while i < len(midi_track):
            midi = midi_track[i]
            if midi is None:
                i += 1
                continue

            start_i = i
            frequencies: list[float] = []
            while i < len(midi_track) and midi_track[i] == midi:
                current_frequency = pitch_track[i]
                if current_frequency is not None:
                    frequencies.append(current_frequency)
                i += 1

            duration = (i - start_i) * frame_step_s
            if duration < self.min_note_duration_s:
                continue

            note, octave = midi_to_note(midi)
            average_frequency = (
                sum(frequencies) / len(frequencies)
                if frequencies
                else midi_to_frequency(midi)
            )
            event = MelodyEvent(
                note=note,
                octave=octave,
                midi=midi,
                frequency_hz=average_frequency,
                start_s=start_i * frame_step_s,
                end_s=i * frame_step_s,
            )
            if (
                events
                and events[-1].midi == event.midi
                and abs(events[-1].end_s - event.start_s) < (frame_step_s * 1.5)
            ):
                previous = events[-1]
                merged_frequency = (previous.frequency_hz + event.frequency_hz) / 2
                events[-1] = MelodyEvent(
                    note=previous.note,
                    octave=previous.octave,
                    midi=previous.midi,
                    frequency_hz=merged_frequency,
                    start_s=previous.start_s,
                    end_s=event.end_s,
                )
            else:
                events.append(event)

        return events


def _rms(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(value * value for value in values) / len(values))


def _autocorrelation_pitch(
    frame: Sequence[float],
    *,
    sample_rate: int,
    min_freq_hz: float,
    max_freq_hz: float,
) -> float | None:
    if not frame:
        return None

    mean = sum(frame) / len(frame)
    centered = [sample - mean for sample in frame]
    energy = sum(sample * sample for sample in centered)
    if energy < 1e-8:
        return None

    min_lag = max(1, int(sample_rate / max_freq_hz))
    max_lag = min(len(centered) - 2, int(sample_rate / min_freq_hz))
    if min_lag >= max_lag:
        return None

    best_lag = -1
    best_corr = 0.0
    for lag in range(min_lag, max_lag + 1):
        corr = 0.0
        for i in range(len(centered) - lag):
            corr += centered[i] * centered[i + lag]
        if corr > best_corr:
            best_corr = corr
            best_lag = lag

    if best_lag <= 0:
        return None

    # Reject very weak periodic matches.
    if (best_corr / energy) < 0.2:
        return None

    return sample_rate / best_lag


def _read_wav_mono(path: Path) -> tuple[int, list[float]]:
    if not path.exists():
        raise FileNotFoundError(f"WAV file not found: {path}")

    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        raw = wav_file.readframes(frame_count)

    if channels < 1:
        raise ValueError("WAV has invalid channel count.")
    if sample_width not in {1, 2, 3, 4}:
        raise ValueError(f"Unsupported sample width: {sample_width} bytes.")

    samples = _decode_pcm(raw, sample_width=sample_width)
    if channels == 1:
        return sample_rate, samples

    mono: list[float] = []
    for i in range(0, len(samples), channels):
        frame = samples[i : i + channels]
        if not frame:
            continue
        mono.append(sum(frame) / len(frame))
    return sample_rate, mono


def _decode_pcm(raw: bytes, *, sample_width: int) -> list[float]:
    if sample_width == 1:
        return [((sample - 128) / 128.0) for sample in raw]

    if sample_width == 2:
        int_samples = struct.unpack(f"<{len(raw) // 2}h", raw)
        return [sample / 32768.0 for sample in int_samples]

    if sample_width == 3:
        float_samples: list[float] = []
        for i in range(0, len(raw), 3):
            chunk = raw[i : i + 3]
            if len(chunk) < 3:
                break
            sign_extension = b"\xff" if chunk[2] & 0x80 else b"\x00"
            as_int = int.from_bytes(
                chunk + sign_extension, byteorder="little", signed=True
            )
            float_samples.append(as_int / 8388608.0)
        return float_samples

    int_samples = struct.unpack(f"<{len(raw) // 4}i", raw)
    return [sample / 2147483648.0 for sample in int_samples]


def format_ascii_tab(
    tabs: Sequence[TabPosition],
    *,
    measure_width: int = 72,
    group_lengths: Sequence[int] | None = None,
    group_gap: int = 7,
) -> str:
    """Format tab positions into classic six-string ASCII tab blocks."""
    string_order = (1, 2, 3, 4, 5, 6)  # high e -> low E
    string_labels = {
        1: "e",
        2: "B",
        3: "G",
        4: "D",
        5: "A",
        6: "E",
    }

    if measure_width < 8:
        raise ValueError("measure_width must be at least 8.")

    if group_gap < 0:
        raise ValueError("group_gap cannot be negative.")

    lanes: dict[int, list[str]] = {string_id: [] for string_id in string_order}

    def append_tab_cell(tab: TabPosition) -> None:
        fret_text = str(tab.fret)
        cell_width = max(2, len(fret_text)) + 1
        for string_id in string_order:
            if string_id == tab.string_id:
                cell = fret_text + ("-" * (cell_width - len(fret_text)))
            else:
                cell = "-" * cell_width
            lanes[string_id].append(cell)

    def append_group_gap() -> None:
        if group_gap == 0:
            return
        dash_cell = "-" * group_gap
        for string_id in string_order:
            lanes[string_id].append(dash_cell)

    if group_lengths:
        cursor = 0
        safe_lengths = [max(0, int(length)) for length in group_lengths]
        for group_index, group_len in enumerate(safe_lengths):
            group_tabs = tabs[cursor : cursor + group_len]
            cursor += group_len
            for tab in group_tabs:
                append_tab_cell(tab)
            has_next_group = group_index < (len(safe_lengths) - 1)
            if has_next_group and group_tabs:
                append_group_gap()

        for tab in tabs[cursor:]:
            append_tab_cell(tab)
    else:
        for tab in tabs:
            append_tab_cell(tab)

    rendered: dict[int, str] = {}
    for string_id in string_order:
        line = "".join(lanes[string_id])
        rendered[string_id] = line if line else "-" * measure_width

    total_width = max(len(line) for line in rendered.values())
    chunk_count = max(1, math.ceil(total_width / measure_width))
    blocks: list[str] = []

    for chunk_index in range(chunk_count):
        start = chunk_index * measure_width
        end = start + measure_width
        for string_id in string_order:
            chunk = rendered[string_id][start:end]
            if not chunk:
                chunk = "-" * min(measure_width, total_width)
            blocks.append(f"{string_labels[string_id]}|{chunk}|")
        if chunk_index < chunk_count - 1:
            blocks.append("")

    return "\n".join(blocks)
