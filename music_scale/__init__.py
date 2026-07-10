"""Music scale finder package."""

from .finder import ScaleFinder, ScaleMatch
from .melody_transcriber import MelodyEvent, MelodyTabResult, MelodyTranscriber, TabPosition
from .models import (
    ChordCandidate,
    Duration,
    ExportMetadata,
    IntervalInfo,
    NoteEvent,
    PlaybackEvent,
    PlaybackCursor,
    PlaybackMetadata,
    PlaybackStatus,
    PositionSuggestion,
    ProjectState,
    QualityReport,
    ScaleAnalysis,
    Tempo,
    TimeSignature,
    Timeline,
    TimelineEvent,
    TimelineMarker,
)
from .playback import TimelineBuilder
from .session import MelodySession
from .theory import TheoryEngine

__all__ = [
    "ChordCandidate",
    "Duration",
    "ExportMetadata",
    "IntervalInfo",
    "ScaleFinder",
    "ScaleMatch",
    "ScaleAnalysis",
    "MelodyEvent",
    "MelodyTabResult",
    "MelodyTranscriber",
    "NoteEvent",
    "PlaybackEvent",
    "PlaybackCursor",
    "PlaybackMetadata",
    "PlaybackStatus",
    "PositionSuggestion",
    "ProjectState",
    "QualityReport",
    "TabPosition",
    "Tempo",
    "TimeSignature",
    "Timeline",
    "TimelineBuilder",
    "TimelineEvent",
    "TimelineMarker",
    "MelodySession",
    "TheoryEngine",
]
