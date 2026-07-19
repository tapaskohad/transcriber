"""Playback timeline foundation.

This module does not play audio. It builds deterministic synchronization
timelines for future playback, export, highlighting, and practice features.
"""

from __future__ import annotations

import math
from typing import Sequence

from .models import (
    Duration,
    NoteEvent,
    PlaybackMetadata,
    ProjectState,
    TabPosition,
    Tempo,
    TimeSignature,
    Timeline,
    TimelineEvent,
    TimelineMarker,
    stable_id,
)


class TimelineBuilder:
    """Build canonical timelines from generated note and tab events."""

    def __init__(
        self,
        *,
        tempo: Tempo | None = None,
        time_signature: TimeSignature | None = None,
        default_duration: Duration | None = None,
    ) -> None:
        self.tempo = tempo or Tempo()
        self.time_signature = time_signature or TimeSignature()
        self.default_duration = default_duration or self._duration_from_beats(1.0)

    def build(
        self,
        events: Sequence[NoteEvent],
        *,
        tabs: Sequence[TabPosition] = (),
        group_lengths: Sequence[int] | None = None,
        source: str = "generated",
    ) -> Timeline:
        """Build a deterministic timeline from generated notes."""
        event_tuple = tuple(events)
        tab_by_event_id = {
            tab.event_id: tab
            for tab in tabs
            if tab.event_id
        }
        group_ids = self._group_ids(len(event_tuple), group_lengths)
        start_beats = self._start_beats(len(event_tuple), group_lengths)

        timeline_events: list[TimelineEvent] = []
        for index, event in enumerate(event_tuple, start=1):
            start_beat = start_beats[index - 1]
            start_s = self._seconds_from_beats(start_beat)
            measure = self._measure_for_beat(start_beat)
            tab = tab_by_event_id.get(event.event_id)
            timeline_events.append(
                TimelineEvent(
                    timeline_event_id=stable_id("timeline_event", index),
                    note_event_id=event.event_id,
                    tab_position_id=tab.position_id if tab else None,
                    group_id=group_ids[index - 1],
                    note=event.note_name,
                    pitch_class=event.note,
                    midi=event.midi if event.midi >= 0 else None,
                    string=tab.string_id if tab else None,
                    fret=tab.fret if tab else None,
                    start_s=round(start_s, 6),
                    duration_s=round(self.default_duration.seconds, 6),
                    start_beat=round(start_beat, 6),
                    duration_beats=round(self.default_duration.beats, 6),
                    measure=measure,
                    bar=measure,
                    source=event.source or source,
                )
            )

        duration_beats = (
            max(
                (event.start_beat + event.duration_beats for event in timeline_events),
                default=0.0,
            )
        )
        duration_s = self._seconds_from_beats(duration_beats)
        return Timeline(
            events=tuple(timeline_events),
            markers=self._markers(timeline_events, duration_beats),
            tempo=self.tempo,
            time_signature=self.time_signature,
            duration_s=round(duration_s, 6),
            duration_beats=round(duration_beats, 6),
            beat_grid=self._beat_grid(duration_beats),
            measure_count=self._measure_count(duration_beats),
        )

    def build_project_state(
        self,
        state: ProjectState,
        *,
        group_lengths: Sequence[int] | None = None,
    ) -> ProjectState:
        """Return a ProjectState copy with canonical timeline metadata attached."""
        timeline = self.build(
            state.generated_events,
            tabs=state.tab_positions,
            group_lengths=group_lengths,
        )
        playback_metadata = PlaybackMetadata(
            timeline=timeline,
            tempo=timeline.tempo,
            time_signature=timeline.time_signature,
            current_cursor=state.current_cursor,
            status=state.playback_status,
        )
        return ProjectState(
            project_id=state.project_id,
            tuning=state.tuning,
            selected_notes=state.selected_notes,
            selected_scale=state.selected_scale,
            generated_events=state.generated_events,
            tab_positions=state.tab_positions,
            playback_timeline=state.playback_timeline,
            timeline=timeline,
            tempo=timeline.tempo,
            playback_metadata=playback_metadata,
            current_cursor=state.current_cursor,
            playback_status=state.playback_status,
            export_metadata=state.export_metadata,
            quality_metadata=state.quality_metadata,
            scale_analyses=state.scale_analyses,
            chord_candidates=state.chord_candidates,
            position_suggestions=state.position_suggestions,
            interval_analysis=state.interval_analysis,
        )

    def _duration_from_beats(self, beats: float) -> Duration:
        return Duration(beats=beats, seconds=self._seconds_from_beats(beats))

    def _seconds_from_beats(self, beats: float) -> float:
        return beats * (60.0 / self.tempo.bpm)

    def _measure_for_beat(self, beat: float) -> int:
        return int(beat // self.time_signature.beats_per_measure) + 1

    def _measure_count(self, duration_beats: float) -> int:
        if duration_beats <= 0:
            return 0
        return int(math.ceil(duration_beats / self.time_signature.beats_per_measure))

    @staticmethod
    def _group_ids(
        event_count: int,
        group_lengths: Sequence[int] | None,
    ) -> tuple[str, ...]:
        if event_count <= 0:
            return ()
        if not group_lengths:
            return tuple("group_000001" for _ in range(event_count))

        group_ids: list[str] = []
        for group_index, raw_length in enumerate(group_lengths, start=1):
            length = max(0, int(raw_length))
            group_ids.extend(stable_id("group", group_index) for _ in range(length))
        if len(group_ids) < event_count:
            group_ids.extend(
                stable_id("group", len(group_lengths) + 1)
                for _ in range(event_count - len(group_ids))
            )
        return tuple(group_ids[:event_count])

    def _start_beats(
        self,
        event_count: int,
        group_lengths: Sequence[int] | None,
    ) -> tuple[float, ...]:
        """Return event starts, with every supplied group sharing one beat.

        ``group_lengths`` already expresses simultaneous note groups at the API
        boundary.  Keeping that relationship here makes the timeline's timing
        agree with its group IDs without changing the Timeline model.
        """
        if event_count <= 0:
            return ()
        if not group_lengths:
            return tuple(
                index * self.default_duration.beats for index in range(event_count)
            )

        starts: list[float] = []
        beat = 0.0
        for raw_length in group_lengths:
            length = max(0, int(raw_length))
            if length <= 0:
                continue
            starts.extend(beat for _ in range(length))
            beat += self.default_duration.beats

        while len(starts) < event_count:
            starts.append(beat)
            beat += self.default_duration.beats
        return tuple(starts[:event_count])

    def _beat_grid(self, duration_beats: float) -> tuple[float, ...]:
        if duration_beats <= 0:
            return ()
        last_beat = int(math.ceil(duration_beats))
        return tuple(float(beat) for beat in range(0, last_beat + 1))

    def _markers(
        self,
        events: Sequence[TimelineEvent],
        duration_beats: float,
    ) -> tuple[TimelineMarker, ...]:
        markers: list[TimelineMarker] = []
        measure_count = self._measure_count(duration_beats)
        for measure in range(1, measure_count + 1):
            beat = float((measure - 1) * self.time_signature.beats_per_measure)
            markers.append(
                TimelineMarker(
                    marker_id=stable_id("marker", len(markers) + 1),
                    marker_type="bar",
                    label=f"Bar {measure}",
                    time_s=round(self._seconds_from_beats(beat), 6),
                    beat=beat,
                    measure=measure,
                    bar=measure,
                )
            )

        seen_groups: set[str] = set()
        for event in events:
            if event.group_id in seen_groups:
                continue
            seen_groups.add(event.group_id)
            markers.append(
                TimelineMarker(
                    marker_id=stable_id("marker", len(markers) + 1),
                    marker_type="group",
                    label=event.group_id,
                    time_s=event.start_s,
                    beat=event.start_beat,
                    measure=event.measure,
                    bar=event.bar,
                    group_id=event.group_id,
                )
            )
        return tuple(markers)
