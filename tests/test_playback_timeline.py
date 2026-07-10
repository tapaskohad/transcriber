from __future__ import annotations

import unittest

from music_scale.models import NoteEvent, PlaybackStatus, ProjectState, TabPosition
from music_scale.playback import TimelineBuilder


class PlaybackTimelineTests(unittest.TestCase):
    def test_builder_creates_deterministic_default_timeline(self) -> None:
        events = (
            NoteEvent(
                event_id="event_000001",
                note="E",
                octave=4,
                midi=64,
                frequency_hz=329.63,
                start_s=99.0,
                end_s=100.0,
                source="notes",
            ),
            NoteEvent(
                event_id="event_000002",
                note="F#",
                octave=4,
                midi=66,
                frequency_hz=369.99,
                start_s=100.0,
                end_s=101.0,
                source="notes",
            ),
        )
        tabs = (
            TabPosition(
                position_id="tab_000001",
                event_id="event_000001",
                string_id=1,
                fret=0,
                midi=64,
                note="E",
                octave=4,
            ),
            TabPosition(
                position_id="tab_000002",
                event_id="event_000002",
                string_id=1,
                fret=2,
                midi=66,
                note="F#",
                octave=4,
            ),
        )

        timeline = TimelineBuilder().build(events, tabs=tabs)

        self.assertEqual(timeline.tempo.bpm, 120.0)
        self.assertEqual(timeline.time_signature.beats_per_measure, 4)
        self.assertEqual(timeline.duration_beats, 2.0)
        self.assertEqual(timeline.duration_s, 1.0)
        self.assertEqual(timeline.events[0].timeline_event_id, "timeline_event_000001")
        self.assertEqual(timeline.events[0].note_event_id, "event_000001")
        self.assertEqual(timeline.events[0].tab_position_id, "tab_000001")
        self.assertEqual(timeline.events[0].start_s, 0.0)
        self.assertEqual(timeline.events[1].start_s, 0.5)

    def test_builder_assigns_group_ids_and_markers(self) -> None:
        events = tuple(
            NoteEvent(
                event_id=f"event_{index:06d}",
                note="E",
                octave=4,
                midi=64,
                frequency_hz=329.63,
                start_s=0.0,
                end_s=0.5,
            )
            for index in range(1, 5)
        )

        timeline = TimelineBuilder().build(events, group_lengths=[2, 2])

        self.assertEqual(
            [event.group_id for event in timeline.events],
            ["group_000001", "group_000001", "group_000002", "group_000002"],
        )
        marker_types = [marker.marker_type for marker in timeline.markers]
        self.assertIn("bar", marker_types)
        self.assertIn("group", marker_types)

    def test_project_state_preserves_playback_status(self) -> None:
        event = NoteEvent(
            event_id="event_000001",
            note="E",
            octave=4,
            midi=64,
            frequency_hz=329.63,
            start_s=0.0,
            end_s=0.5,
        )
        status = PlaybackStatus(
            is_playing=True,
            current_time_s=0.25,
            loop_enabled=True,
            playback_speed=1.5,
        )
        state = ProjectState(
            generated_events=(event,),
            playback_status=status,
        )

        updated = TimelineBuilder().build_project_state(state)

        self.assertIs(updated.playback_status, status)
        self.assertIs(updated.playbackStatus, status)
        self.assertIs(updated.playback_metadata.status, status)
        self.assertTrue(updated.playbackStatus.isPlaying)
        self.assertEqual(updated.playbackStatus.currentTime, 0.25)
        self.assertTrue(updated.playbackStatus.loopEnabled)
        self.assertEqual(updated.playbackStatus.playbackSpeed, 1.5)


if __name__ == "__main__":
    unittest.main()
