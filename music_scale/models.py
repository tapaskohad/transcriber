"""Canonical project models shared by backend workflows."""

from __future__ import annotations

from dataclasses import dataclass, field


def stable_id(prefix: str, index: int) -> str:
    """Build deterministic IDs for generated project entities."""
    safe_prefix = prefix.strip().lower().replace(" ", "_") or "item"
    return f"{safe_prefix}_{max(0, index):06d}"


@dataclass(frozen=True, slots=True)
class NoteEvent:
    """A canonical note event that can be referenced across app features."""

    event_id: str
    note: str
    octave: int
    midi: int
    frequency_hz: float
    start_s: float
    end_s: float
    source: str = "generated"

    @property
    def id(self) -> str:
        return self.event_id

    @property
    def note_name(self) -> str:
        return f"{self.note}{self.octave}"


@dataclass(frozen=True, slots=True)
class TabPosition:
    """A canonical guitar tab position tied to a note event."""

    position_id: str
    event_id: str
    string_id: int
    fret: int
    midi: int
    note: str
    octave: int
    source: str = "generated"

    @property
    def id(self) -> str:
        return self.position_id

    @property
    def tab_token(self) -> str:
        return f"{self.string_id}:{self.fret}"


@dataclass(frozen=True, slots=True)
class PlaybackEvent:
    """Placeholder for future synchronized playback timeline events."""

    playback_id: str = ""
    event_id: str = ""
    start_s: float = 0.0
    duration_s: float = 0.0
    # TODO: Add tempo, transport state, and frontend synchronization metadata.


@dataclass(frozen=True, slots=True)
class Duration:
    """Canonical musical and clock duration."""

    beats: float = 1.0
    seconds: float = 0.5


@dataclass(frozen=True, slots=True)
class Tempo:
    """Timeline tempo metadata."""

    bpm: float = 120.0
    beat_unit: int = 4


@dataclass(frozen=True, slots=True)
class TimeSignature:
    """Timeline meter metadata."""

    beats_per_measure: int = 4
    beat_unit: int = 4


@dataclass(frozen=True, slots=True)
class TimelineMarker:
    """A structural timeline marker such as a bar or group boundary."""

    marker_id: str
    marker_type: str
    label: str
    time_s: float
    beat: float
    measure: int
    bar: int
    group_id: str | None = None


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    """Canonical synchronization event for future playback and exports."""

    timeline_event_id: str
    note_event_id: str
    tab_position_id: str | None
    group_id: str
    note: str
    pitch_class: str
    midi: int | None
    string: int | None
    fret: int | None
    start_s: float
    duration_s: float
    start_beat: float
    duration_beats: float
    measure: int
    bar: int
    source: str


@dataclass(frozen=True, slots=True)
class PlaybackCursor:
    """Placeholder cursor for future transport and synchronized highlighting."""

    current_event_id: str | None = None
    time_s: float = 0.0
    beat: float = 0.0
    is_active: bool = False


@dataclass(frozen=True, slots=True)
class PlaybackStatus:
    """Current transport state for synchronized playback consumers."""

    is_playing: bool = False
    current_time_s: float = 0.0
    current_event: TimelineEvent | None = None
    current_event_id: str | None = None
    loop_enabled: bool = False
    playback_speed: float = 1.0

    @property
    def isPlaying(self) -> bool:
        return self.is_playing

    @property
    def currentTime(self) -> float:
        return self.current_time_s

    @property
    def currentEvent(self) -> TimelineEvent | None:
        return self.current_event

    @property
    def loopEnabled(self) -> bool:
        return self.loop_enabled

    @property
    def playbackSpeed(self) -> float:
        return self.playback_speed


@dataclass(frozen=True, slots=True)
class Timeline:
    """Canonical playback/export timeline."""

    timeline_id: str = "timeline_default"
    events: tuple[TimelineEvent, ...] = ()
    markers: tuple[TimelineMarker, ...] = ()
    tempo: Tempo = field(default_factory=Tempo)
    time_signature: TimeSignature = field(default_factory=TimeSignature)
    duration_s: float = 0.0
    duration_beats: float = 0.0
    beat_grid: tuple[float, ...] = ()
    measure_count: int = 0


@dataclass(frozen=True, slots=True)
class PlaybackMetadata:
    """Metadata container for future playback state."""

    timeline: Timeline = field(default_factory=Timeline)
    tempo: Tempo = field(default_factory=Tempo)
    time_signature: TimeSignature = field(default_factory=TimeSignature)
    current_cursor: PlaybackCursor = field(default_factory=PlaybackCursor)
    status: PlaybackStatus = field(default_factory=PlaybackStatus)
    # TODO: Add loop points, count-in, metronome, and practice-mode flags.


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Placeholder for future tab quality and playability analysis."""

    score: float | None = None
    warnings: tuple[str, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)
    # TODO: Add movement, span, fingering, readability, and confidence metrics.


@dataclass(frozen=True, slots=True)
class ExportMetadata:
    """Metadata shared by future JSON, MIDI, and MusicXML exporters."""

    title: str = "Music Scale Studio"
    created_by: str = "Music Scale Studio"
    format_version: str = "1"
    # TODO: Add tempo, key signature, time signature, and exporter options.


@dataclass(frozen=True, slots=True)
class IntervalInfo:
    """Scale-degree information for one pitch class."""

    note: str
    degree: str
    semitone: int
    in_scale: bool = True


@dataclass(frozen=True, slots=True)
class ChordCandidate:
    """A ranked chord interpretation for selected pitch classes."""

    name: str
    root: str
    intervals: tuple[str, ...]
    notes: tuple[str, ...]
    confidence: float
    inversion: str | None = None


@dataclass(frozen=True, slots=True)
class PositionSuggestion:
    """A playable guitar position area for a set of pitch classes."""

    position_number: int
    average_fret: float
    span: int
    movement_estimate: float
    open_string_usage: int
    confidence: float
    positions: tuple[TabPosition, ...] = ()


@dataclass(frozen=True, slots=True)
class ScaleAnalysis:
    """Structured analysis for one scale candidate."""

    scale_name: str
    root: str
    interval_formula: tuple[str, ...]
    scale_degrees: tuple[IntervalInfo, ...]
    contained_notes: tuple[str, ...]
    confidence: float
    exact_match: bool
    missing_notes: tuple[str, ...]
    extra_notes: tuple[str, ...]
    relative_major_minor: dict[str, str] = field(default_factory=dict)
    mode_family: str = ""
    description: str = ""
    pentatonic_equivalent: dict[str, str] | None = None
    blues_equivalent: dict[str, str] | None = None
    common_modes: tuple[dict[str, str], ...] = ()
    compatible_chords: tuple[ChordCandidate, ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectState:
    """Single backend source of truth for a generated workstation state."""

    project_id: str = "project_default"
    tuning: tuple[tuple[int, str], ...] = ()
    selected_notes: tuple[str, ...] = ()
    selected_scale: str | None = None
    generated_events: tuple[NoteEvent, ...] = ()
    tab_positions: tuple[TabPosition, ...] = ()
    playback_timeline: tuple[PlaybackEvent, ...] = ()
    timeline: Timeline = field(default_factory=Timeline)
    tempo: Tempo = field(default_factory=Tempo)
    playback_metadata: PlaybackMetadata = field(default_factory=PlaybackMetadata)
    current_cursor: PlaybackCursor = field(default_factory=PlaybackCursor)
    playback_status: PlaybackStatus = field(default_factory=PlaybackStatus)
    export_metadata: ExportMetadata = field(default_factory=ExportMetadata)
    quality_metadata: QualityReport = field(default_factory=QualityReport)
    scale_analyses: tuple[ScaleAnalysis, ...] = ()
    chord_candidates: tuple[ChordCandidate, ...] = ()
    position_suggestions: tuple[PositionSuggestion, ...] = ()
    interval_analysis: tuple[IntervalInfo, ...] = ()
    # TODO: Add fingering analysis and richer workstation project metadata.

    @property
    def playbackStatus(self) -> PlaybackStatus:
        return self.playback_status
