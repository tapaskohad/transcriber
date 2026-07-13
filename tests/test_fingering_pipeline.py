from __future__ import annotations

from dataclasses import replace
import unittest

from music_scale.fingering import (
    AnalysisPass,
    AlternateFingeringPass,
    DifficultyPass,
    FingerAssignmentPass,
    FingeringAnalyzer,
    PositionShiftPass,
    PracticePreparationPass,
    QualityPass,
    StretchAnalysisPass,
    ValidationPass,
)
from music_scale.melody_transcriber import MelodyTranscriber
from music_scale.models import (
    AnalysisResults,
    AlternateFingering,
    DifficultyScore,
    FingerAssignment,
    FingeringAnalysis,
    NoteEvent,
    PerformanceAnalysis,
    PositionShift,
    PracticeAnalysis,
    ProjectState,
    QualityReport,
    StretchIssue,
    TabPosition,
    Timeline,
    TimelineEvent,
    stable_id,
)


class RecordingPass(AnalysisPass):
    def __init__(self, name: str, calls: list[str], seen: list[AnalysisResults]) -> None:
        self.name = name
        self._calls = calls
        self._seen = seen

    def run(
        self,
        project_state: ProjectState,
        analysis_results: AnalysisResults,
    ) -> AnalysisResults:
        self._calls.append(self.name)
        self._seen.append(analysis_results)
        return analysis_results


class FingeringPipelineTests(unittest.TestCase):
    def _valid_state(self) -> ProjectState:
        return MelodyTranscriber().transcribe_notes(["E4", "F#4", "G4"]).project_state

    def _alternate_state(self) -> ProjectState:
        return MelodyTranscriber().transcribe_notes(["E4", "F#4", "G4", "A4"]).project_state

    def _state_for_tab_frets(self, tab_specs: list[tuple[int, int]]) -> ProjectState:
        note_events: list[NoteEvent] = []
        tab_positions: list[TabPosition] = []
        timeline_events: list[TimelineEvent] = []

        for index, (string_id, fret) in enumerate(tab_specs, start=1):
            event_id = stable_id("event", index)
            tab_id = stable_id("tab", index)
            midi = 60 + index
            start_s = (index - 1) * 0.5
            note_events.append(
                NoteEvent(
                    event_id=event_id,
                    note="C",
                    octave=4,
                    midi=midi,
                    frequency_hz=261.63,
                    start_s=start_s,
                    end_s=start_s + 0.5,
                    source="test",
                )
            )
            tab_positions.append(
                TabPosition(
                    position_id=tab_id,
                    event_id=event_id,
                    string_id=string_id,
                    fret=fret,
                    midi=midi,
                    note="C",
                    octave=4,
                    source="test",
                )
            )
            timeline_events.append(
                TimelineEvent(
                    timeline_event_id=stable_id("timeline_event", index),
                    note_event_id=event_id,
                    tab_position_id=tab_id,
                    group_id=stable_id("group", 1),
                    note="C4",
                    pitch_class="C",
                    midi=midi,
                    string=string_id,
                    fret=fret,
                    start_s=start_s,
                    duration_s=0.5,
                    start_beat=float(index - 1),
                    duration_beats=1.0,
                    measure=1,
                    bar=1,
                    source="test",
                )
            )

        return ProjectState(
            generated_events=tuple(note_events),
            tab_positions=tuple(tab_positions),
            timeline=Timeline(
                timeline_id="timeline_test",
                events=tuple(timeline_events),
                duration_s=len(tab_specs) * 0.5,
                duration_beats=float(len(tab_specs)),
            ),
        )

    def test_analyzer_accepts_valid_project_state(self) -> None:
        state = self._valid_state()
        updated = FingeringAnalyzer().analyze(state)
        results = updated.analysis_results

        self.assertIsInstance(updated, ProjectState)
        self.assertIsNot(updated, state)
        self.assertIsInstance(results, AnalysisResults)
        self.assertIsInstance(results.fingering, FingeringAnalysis)
        self.assertIsInstance(results.performance, PerformanceAnalysis)
        self.assertIsInstance(results.quality, QualityReport)
        self.assertIsInstance(results.practice, PracticeAnalysis)
        self.assertEqual(results.analysis_id, "analysis_results_000001")
        self.assertEqual(len(results.fingering.assignments), len(state.timeline.events))
        self.assertEqual(results.fingering.stretch_issues, ())
        self.assertEqual(results.fingering.position_shifts, ())
        self.assertLessEqual(len(results.fingering.alternate_fingerings), 3)
        self.assertEqual(results.performance.issues, ())
        self.assertEqual(results.quality.score, results.quality.overall_quality_score)
        self.assertIn(results.quality.quality_level, ("Excellent", "Good", "Fair", "Poor"))
        self.assertEqual(results.practice.focus_timeline_event_ids, ())
        self.assertEqual(results.generated_from_timeline_id, state.timeline.timeline_id)

    def test_analyzer_outputs_are_deterministic(self) -> None:
        state = self._valid_state()
        analyzer = FingeringAnalyzer()

        first = analyzer.analyze(state)
        second = analyzer.analyze(state)

        self.assertEqual(first, second)
        self.assertEqual(
            first.analysis_results.performance.difficulty.score_id,
            "difficulty_000001",
        )
        self.assertEqual(
            first.analysis_results.practice.analysis_id,
            "practice_analysis_000001",
        )
        self.assertEqual(
            first.analysis_results.fingering.assignments,
            second.analysis_results.fingering.assignments,
        )

    def test_analyzer_attaches_results_to_project_state_copy(self) -> None:
        state = self._valid_state()
        updated = FingeringAnalyzer().analyze_project_state(state)

        self.assertIsNot(updated, state)
        self.assertEqual(updated.generated_events, state.generated_events)
        self.assertEqual(updated.tab_positions, state.tab_positions)
        self.assertEqual(updated.timeline, state.timeline)
        self.assertEqual(updated.analysis_results.analysis_id, "analysis_results_000001")
        self.assertEqual(state.analysis_results.analysis_id, "analysis_results_default")

    def test_analyze_results_preserves_previous_result_only_contract(self) -> None:
        state = self._valid_state()
        results = FingeringAnalyzer().analyze_results(state)

        self.assertIsInstance(results, AnalysisResults)
        self.assertEqual(results.analysis_id, "analysis_results_000001")

    def test_analyzer_rejects_non_project_state(self) -> None:
        with self.assertRaises(TypeError):
            FingeringAnalyzer().analyze("not a project state")  # type: ignore[arg-type]

    def test_analyzer_rejects_generated_events_without_timeline(self) -> None:
        state = self._valid_state()
        invalid = replace(state, timeline=Timeline())

        with self.assertRaisesRegex(ValueError, "timeline"):
            FingeringAnalyzer().analyze(invalid)

    def test_analyzer_rejects_missing_note_event_reference(self) -> None:
        state = self._valid_state()
        first_event = replace(
            state.timeline.events[0],
            note_event_id="event_999999",
        )
        invalid_timeline = replace(
            state.timeline,
            events=(first_event,) + state.timeline.events[1:],
        )
        invalid = replace(state, timeline=invalid_timeline)

        with self.assertRaisesRegex(ValueError, "missing NoteEvent"):
            FingeringAnalyzer().analyze(invalid)

    def test_default_passes_are_in_deterministic_order(self) -> None:
        passes = FingeringAnalyzer.default_passes()

        self.assertEqual(
            [analysis_pass.name for analysis_pass in passes],
            [
                "validation",
                "finger_assignment",
                "stretch_analysis",
                "position_shift",
                "difficulty",
                "quality",
                "alternate_fingering",
                "practice_preparation",
            ],
        )
        self.assertIsInstance(passes[0], ValidationPass)
        self.assertIsInstance(passes[1], FingerAssignmentPass)
        self.assertIsInstance(passes[2], StretchAnalysisPass)
        self.assertIsInstance(passes[3], PositionShiftPass)
        self.assertIsInstance(passes[4], DifficultyPass)
        self.assertIsInstance(passes[5], QualityPass)
        self.assertIsInstance(passes[6], AlternateFingeringPass)
        self.assertIsInstance(passes[7], PracticePreparationPass)

    def test_every_pass_executes_once_and_results_flow_through_pipeline(self) -> None:
        state = self._valid_state()
        calls: list[str] = []
        seen: list[AnalysisResults] = []
        passes = (
            RecordingPass("first", calls, seen),
            RecordingPass("second", calls, seen),
            RecordingPass("third", calls, seen),
        )

        updated = FingeringAnalyzer(passes=passes).analyze(state)

        self.assertEqual(calls, ["first", "second", "third"])
        self.assertEqual(len(seen), 3)
        self.assertIs(seen[0], seen[1])
        self.assertIs(seen[1], seen[2])
        self.assertIs(updated.analysis_results, seen[0])
        self.assertEqual(updated.generated_events, state.generated_events)
        self.assertEqual(updated.timeline, state.timeline)

    def test_placeholder_passes_return_analysis_results_unchanged(self) -> None:
        state = self._valid_state()
        results = FingeringAnalyzer().analyze_results(state)
        placeholder_passes = (
            PracticePreparationPass(),
        )

        for analysis_pass in placeholder_passes:
            with self.subTest(pass_name=analysis_pass.name):
                self.assertIs(analysis_pass.run(state, results), results)

    def test_analyzer_rejects_pass_that_returns_wrong_type(self) -> None:
        class BadPass(AnalysisPass):
            def run(
                self,
                project_state: ProjectState,
                analysis_results: AnalysisResults,
            ) -> AnalysisResults:
                return "not analysis results"  # type: ignore[return-value]

        with self.assertRaisesRegex(TypeError, "AnalysisResults"):
            FingeringAnalyzer(passes=(BadPass(),)).analyze(self._valid_state())

    def test_finger_assignment_handles_open_strings(self) -> None:
        state = self._state_for_tab_frets([(1, 0), (2, 0)])

        assignments = FingeringAnalyzer().analyze_results(state).fingering.assignments

        self.assertEqual([assignment.finger for assignment in assignments], [None, None])
        self.assertEqual([assignment.position_fret for assignment in assignments], [None, None])
        self.assertEqual([assignment.reason for assignment in assignments], ["open_string", "open_string"])

    def test_finger_assignment_prefers_previous_finger_for_repeated_notes(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 5), (1, 5)])

        assignments = FingeringAnalyzer().analyze_results(state).fingering.assignments

        self.assertEqual([assignment.finger for assignment in assignments], [1, 1, 1])
        self.assertEqual([assignment.position_fret for assignment in assignments], [5, 5, 5])
        self.assertEqual(
            [assignment.reason for assignment in assignments],
            ["one_finger_per_fret", "repeated_note", "repeated_note"],
        )

    def test_finger_assignment_maps_ascending_frets_to_one_finger_per_fret(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 6), (1, 7), (1, 8)])

        assignments = FingeringAnalyzer().analyze_results(state).fingering.assignments

        self.assertEqual([assignment.finger for assignment in assignments], [1, 2, 3, 4])
        self.assertEqual([assignment.position_fret for assignment in assignments], [5, 5, 5, 5])

    def test_finger_assignment_maps_descending_frets_to_one_finger_per_fret(self) -> None:
        state = self._state_for_tab_frets([(1, 8), (1, 7), (1, 6), (1, 5)])

        assignments = FingeringAnalyzer().analyze_results(state).fingering.assignments

        self.assertEqual([assignment.finger for assignment in assignments], [4, 3, 2, 1])
        self.assertEqual([assignment.position_fret for assignment in assignments], [5, 5, 5, 5])

    def test_finger_assignment_keeps_same_string_phrase_in_position(self) -> None:
        state = self._state_for_tab_frets([(2, 5), (2, 6), (2, 6), (2, 7)])

        assignments = FingeringAnalyzer().analyze_results(state).fingering.assignments

        self.assertEqual([assignment.finger for assignment in assignments], [1, 2, 2, 3])
        self.assertEqual([assignment.position_fret for assignment in assignments], [5, 5, 5, 5])

    def test_finger_assignment_keeps_multi_string_phrase_in_position(self) -> None:
        state = self._state_for_tab_frets([(6, 5), (5, 6), (4, 7), (3, 8)])

        assignments = FingeringAnalyzer().analyze_results(state).fingering.assignments

        self.assertEqual([assignment.finger for assignment in assignments], [1, 2, 3, 4])
        self.assertEqual([assignment.position_fret for assignment in assignments], [5, 5, 5, 5])

    def test_finger_assignment_uses_stable_ids_and_canonical_references(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (2, 6)])

        assignments = FingeringAnalyzer().analyze_results(state).fingering.assignments

        self.assertEqual(
            [assignment.assignment_id for assignment in assignments],
            ["finger_assignment_000001", "finger_assignment_000002"],
        )
        self.assertEqual(
            [assignment.timeline_event_id for assignment in assignments],
            [event.timeline_event_id for event in state.timeline.events],
        )
        self.assertEqual(
            [assignment.note_event_id for assignment in assignments],
            [event.event_id for event in state.generated_events],
        )
        self.assertEqual(
            [assignment.tab_position_id for assignment in assignments],
            [tab.position_id for tab in state.tab_positions],
        )
        for assignment in assignments:
            self.assertIsInstance(assignment, FingerAssignment)

    def test_finger_assignment_updates_project_state_without_mutating_inputs(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 6)])

        updated = FingeringAnalyzer().analyze(state)

        self.assertIsNot(updated, state)
        self.assertEqual(state.analysis_results.fingering.assignments, ())
        self.assertEqual(len(updated.analysis_results.fingering.assignments), 2)
        self.assertEqual(updated.generated_events, state.generated_events)
        self.assertEqual(updated.tab_positions, state.tab_positions)
        self.assertEqual(updated.timeline, state.timeline)

    def test_position_shift_reports_no_shift_for_stable_position(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 6), (1, 8)])

        results = FingeringAnalyzer().analyze_results(state)

        self.assertEqual(results.fingering.position_shifts, ())

    def test_position_shift_reports_single_shift(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 9)])

        shifts = FingeringAnalyzer().analyze_results(state).fingering.position_shifts

        self.assertEqual(len(shifts), 1)
        shift = shifts[0]
        self.assertIsInstance(shift, PositionShift)
        self.assertEqual(shift.shift_id, "position_shift_000001")
        self.assertEqual(shift.from_timeline_event_id, "timeline_event_000001")
        self.assertEqual(shift.to_timeline_event_id, "timeline_event_000002")
        self.assertEqual(shift.from_note_event_id, "event_000001")
        self.assertEqual(shift.to_note_event_id, "event_000002")
        self.assertEqual(shift.from_tab_position_id, "tab_000001")
        self.assertEqual(shift.to_tab_position_id, "tab_000002")
        self.assertEqual(shift.from_position_fret, 5)
        self.assertEqual(shift.to_position_fret, 9)
        self.assertEqual(shift.distance, 4)
        self.assertEqual(shift.reason, "position_fret_changed")
        self.assertEqual(shift.confidence, 1.0)

    def test_position_shift_reports_multiple_shifts(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 9), (1, 13)])

        shifts = FingeringAnalyzer().analyze_results(state).fingering.position_shifts

        self.assertEqual(len(shifts), 2)
        self.assertEqual(
            [shift.shift_id for shift in shifts],
            ["position_shift_000001", "position_shift_000002"],
        )
        self.assertEqual(
            [(shift.from_position_fret, shift.to_position_fret) for shift in shifts],
            [(5, 9), (9, 13)],
        )

    def test_position_shift_ignores_repeated_notes_in_same_position(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 5), (1, 6)])

        results = FingeringAnalyzer().analyze_results(state)

        self.assertEqual(results.fingering.position_shifts, ())

    def test_position_shift_ignores_open_strings(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (2, 0), (1, 6)])

        results = FingeringAnalyzer().analyze_results(state)

        self.assertEqual(results.fingering.position_shifts, ())

    def test_position_shift_detects_ascending_phrase_shift(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 6), (1, 10)])

        shifts = FingeringAnalyzer().analyze_results(state).fingering.position_shifts

        self.assertEqual(len(shifts), 1)
        self.assertEqual(shifts[0].from_timeline_event_id, "timeline_event_000002")
        self.assertEqual(shifts[0].to_timeline_event_id, "timeline_event_000003")
        self.assertEqual((shifts[0].from_position_fret, shifts[0].to_position_fret), (5, 10))

    def test_position_shift_detects_descending_phrase_shift(self) -> None:
        state = self._state_for_tab_frets([(1, 10), (1, 6), (1, 5)])

        shifts = FingeringAnalyzer().analyze_results(state).fingering.position_shifts

        self.assertEqual(len(shifts), 1)
        self.assertEqual(shifts[0].from_timeline_event_id, "timeline_event_000001")
        self.assertEqual(shifts[0].to_timeline_event_id, "timeline_event_000002")
        self.assertEqual((shifts[0].from_position_fret, shifts[0].to_position_fret), (10, 5))

    def test_position_shift_outputs_are_deterministic(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 9), (1, 13)])
        analyzer = FingeringAnalyzer()

        first = analyzer.analyze_results(state).fingering.position_shifts
        second = analyzer.analyze_results(state).fingering.position_shifts

        self.assertEqual(first, second)
        self.assertEqual(
            [shift.shift_id for shift in first],
            ["position_shift_000001", "position_shift_000002"],
        )

    def test_position_shift_updates_project_state_without_changing_previous_results(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 9)])
        previous_results = FingeringAnalyzer(
            passes=(ValidationPass(), FingerAssignmentPass(), StretchAnalysisPass())
        ).analyze_results(state)

        updated = FingeringAnalyzer().analyze(state)

        self.assertIsNot(updated, state)
        self.assertEqual(state.analysis_results.fingering.position_shifts, ())
        self.assertEqual(
            updated.analysis_results.fingering.assignments,
            previous_results.fingering.assignments,
        )
        self.assertEqual(
            updated.analysis_results.fingering.stretch_issues,
            previous_results.fingering.stretch_issues,
        )
        self.assertEqual(len(updated.analysis_results.fingering.position_shifts), 1)
        self.assertEqual(updated.generated_events, state.generated_events)
        self.assertEqual(updated.tab_positions, state.tab_positions)
        self.assertEqual(updated.timeline, state.timeline)

    def test_difficulty_scores_very_easy_phrase(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 6), (1, 7)])

        difficulty = FingeringAnalyzer().analyze_results(state).performance.difficulty

        self.assertIsInstance(difficulty, DifficultyScore)
        self.assertEqual(difficulty.score_id, "difficulty_000001")
        self.assertEqual(difficulty.overall_score, 1.5)
        self.assertEqual(difficulty.difficulty_level, "Easy")
        self.assertEqual(difficulty.stretch_score, 0.0)
        self.assertEqual(difficulty.position_shift_score, 0.0)
        self.assertEqual(difficulty.movement_score, 0.0)
        self.assertEqual(difficulty.finger_complexity_score, 1.5)
        self.assertEqual(difficulty.open_string_bonus, 0.0)
        self.assertEqual(difficulty.overall, difficulty.overall_score)
        self.assertEqual(difficulty.label, difficulty.difficulty_level)

    def test_difficulty_scores_moderate_phrase(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 9)])

        difficulty = FingeringAnalyzer().analyze_results(state).performance.difficulty

        self.assertEqual(difficulty.overall_score, 21.0)
        self.assertEqual(difficulty.difficulty_level, "Moderate")
        self.assertEqual(difficulty.stretch_score, 8.0)
        self.assertEqual(difficulty.position_shift_score, 7.0)
        self.assertEqual(difficulty.movement_score, 6.0)
        self.assertEqual(difficulty.finger_complexity_score, 0.0)

    def test_difficulty_scores_difficult_phrase(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 9), (1, 14), (1, 20)])

        difficulty = FingeringAnalyzer().analyze_results(state).performance.difficulty

        self.assertEqual(difficulty.overall_score, 80.0)
        self.assertEqual(difficulty.difficulty_level, "Expert")
        self.assertEqual(difficulty.stretch_score, 35.0)
        self.assertEqual(difficulty.position_shift_score, 25.0)
        self.assertEqual(difficulty.movement_score, 20.0)

    def test_difficulty_applies_open_string_bonus(self) -> None:
        state = self._state_for_tab_frets([(1, 0), (2, 0), (3, 0), (1, 5)])

        difficulty = FingeringAnalyzer().analyze_results(state).performance.difficulty

        self.assertEqual(difficulty.open_string_bonus, 4.5)
        self.assertEqual(difficulty.overall_score, 0.0)
        self.assertEqual(difficulty.difficulty_level, "Easy")

    def test_difficulty_scores_repeated_notes_conservatively(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 5), (1, 5)])

        difficulty = FingeringAnalyzer().analyze_results(state).performance.difficulty

        self.assertEqual(difficulty.overall_score, 0.0)
        self.assertEqual(difficulty.difficulty_level, "Easy")
        self.assertEqual(difficulty.reason_summary, "stretch=0.0; position_shifts=0.0; movement=0.0; finger_complexity=0.0; open_string_bonus=0.0")

    def test_difficulty_weights_large_position_shifts(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 13)])

        difficulty = FingeringAnalyzer().analyze_results(state).performance.difficulty

        self.assertEqual(difficulty.overall_score, 57.0)
        self.assertEqual(difficulty.difficulty_level, "Hard")
        self.assertEqual(difficulty.stretch_score, 30.0)
        self.assertEqual(difficulty.position_shift_score, 15.0)
        self.assertEqual(difficulty.movement_score, 12.0)

    def test_difficulty_weights_multiple_stretches(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 9), (1, 14)])

        difficulty = FingeringAnalyzer().analyze_results(state).performance.difficulty

        self.assertEqual(difficulty.stretch_score, 24.0)
        self.assertEqual(difficulty.position_shift_score, 16.0)
        self.assertEqual(difficulty.movement_score, 13.5)
        self.assertEqual(difficulty.overall_score, 53.5)
        self.assertEqual(difficulty.difficulty_level, "Hard")

    def test_difficulty_outputs_are_deterministic(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 9), (1, 14)])
        analyzer = FingeringAnalyzer()

        first = analyzer.analyze_results(state).performance.difficulty
        second = analyzer.analyze_results(state).performance.difficulty

        self.assertEqual(first, second)
        self.assertEqual(first.score_id, "difficulty_000001")

    def test_difficulty_labels_are_stable(self) -> None:
        analyzer = FingeringAnalyzer()

        easy = analyzer.analyze_results(self._state_for_tab_frets([(1, 5)])).performance.difficulty
        moderate = analyzer.analyze_results(self._state_for_tab_frets([(1, 5), (1, 9)])).performance.difficulty
        hard = analyzer.analyze_results(self._state_for_tab_frets([(1, 5), (1, 13)])).performance.difficulty
        expert = analyzer.analyze_results(
            self._state_for_tab_frets([(1, 5), (1, 9), (1, 14), (1, 20)])
        ).performance.difficulty

        self.assertEqual(
            [easy.difficulty_level, moderate.difficulty_level, hard.difficulty_level, expert.difficulty_level],
            ["Easy", "Moderate", "Hard", "Expert"],
        )

    def test_difficulty_updates_project_state_without_changing_previous_results(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 9)])
        previous_results = FingeringAnalyzer(
            passes=(
                ValidationPass(),
                FingerAssignmentPass(),
                StretchAnalysisPass(),
                PositionShiftPass(),
            )
        ).analyze_results(state)

        updated = FingeringAnalyzer().analyze(state)

        self.assertIsNot(updated, state)
        self.assertEqual(
            updated.analysis_results.fingering.assignments,
            previous_results.fingering.assignments,
        )
        self.assertEqual(
            updated.analysis_results.fingering.stretch_issues,
            previous_results.fingering.stretch_issues,
        )
        self.assertEqual(
            updated.analysis_results.fingering.position_shifts,
            previous_results.fingering.position_shifts,
        )
        self.assertEqual(updated.analysis_results.performance.difficulty.overall_score, 21.0)
        self.assertEqual(updated.generated_events, state.generated_events)
        self.assertEqual(updated.tab_positions, state.tab_positions)
        self.assertEqual(updated.timeline, state.timeline)

    def test_quality_scores_high_quality_fingering(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 6), (1, 7)])

        quality = FingeringAnalyzer().analyze_results(state).quality

        self.assertIsInstance(quality, QualityReport)
        self.assertEqual(quality.overall_quality_score, 100.0)
        self.assertEqual(quality.score, 100.0)
        self.assertEqual(quality.quality_level, "Excellent")
        self.assertEqual(quality.quality_issues, ())
        self.assertEqual(quality.recommendations, ())
        self.assertEqual(quality.warnings, ())
        self.assertEqual(quality.confidence, 1.0)
        self.assertEqual(quality.metrics["compact_bonus"], 5.0)

    def test_quality_scores_poor_quality_fingering(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 9), (1, 14), (1, 20)])

        quality = FingeringAnalyzer().analyze_results(state).quality

        self.assertEqual(quality.overall_quality_score, 26.25)
        self.assertEqual(quality.quality_level, "Poor")
        self.assertEqual(
            quality.quality_issues,
            (
                "unnecessary_stretches",
                "unnecessary_position_shifts",
                "inefficient_movement",
            ),
        )
        self.assertEqual(quality.metrics["stretch_penalty"], 30.0)
        self.assertEqual(quality.metrics["shift_penalty"], 25.0)
        self.assertEqual(quality.metrics["movement_penalty"], 18.75)

    def test_quality_rewards_stable_hand_position(self) -> None:
        state = self._state_for_tab_frets([(2, 5), (2, 6), (2, 8)])

        quality = FingeringAnalyzer().analyze_results(state).quality

        self.assertEqual(quality.overall_quality_score, 100.0)
        self.assertEqual(quality.quality_level, "Excellent")
        self.assertEqual(quality.metrics["shift_penalty"], 0.0)
        self.assertEqual(quality.metrics["movement_penalty"], 0.0)
        self.assertEqual(quality.metrics["compact_bonus"], 5.0)

    def test_quality_flags_excessive_shifts(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 9), (1, 13)])

        quality = FingeringAnalyzer().analyze_results(state).quality

        self.assertEqual(quality.overall_quality_score, 51.0)
        self.assertEqual(quality.quality_level, "Poor")
        self.assertIn("unnecessary_position_shifts", quality.quality_issues)
        self.assertEqual(quality.metrics["shift_penalty"], 20.0)

    def test_quality_flags_unnecessary_stretches(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 9)])

        quality = FingeringAnalyzer().analyze_results(state).quality

        self.assertEqual(quality.overall_quality_score, 75.5)
        self.assertEqual(quality.quality_level, "Good")
        self.assertIn("unnecessary_stretches", quality.quality_issues)
        self.assertEqual(quality.metrics["stretch_penalty"], 9.5)

    def test_quality_outputs_are_deterministic(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 9), (1, 13)])
        analyzer = FingeringAnalyzer()

        first = analyzer.analyze_results(state).quality
        second = analyzer.analyze_results(state).quality

        self.assertEqual(first, second)
        self.assertEqual(first.overall_quality_score, 51.0)

    def test_quality_recommendations_are_stable(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 9), (1, 14), (1, 20)])

        recommendations = FingeringAnalyzer().analyze_results(state).quality.recommendations

        self.assertEqual(
            recommendations,
            (
                "Use a more compact fret span where possible.",
                "Keep the hand in one position when adjacent notes allow it.",
                "Reduce large position jumps between consecutive notes.",
            ),
        )

    def test_quality_updates_project_state_without_changing_previous_analysis(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 9)])
        previous_results = FingeringAnalyzer(
            passes=(
                ValidationPass(),
                FingerAssignmentPass(),
                StretchAnalysisPass(),
                PositionShiftPass(),
                DifficultyPass(),
            )
        ).analyze_results(state)

        updated = FingeringAnalyzer().analyze(state)

        self.assertIsNot(updated, state)
        self.assertEqual(
            updated.analysis_results.fingering.assignments,
            previous_results.fingering.assignments,
        )
        self.assertEqual(
            updated.analysis_results.fingering.stretch_issues,
            previous_results.fingering.stretch_issues,
        )
        self.assertEqual(
            updated.analysis_results.fingering.position_shifts,
            previous_results.fingering.position_shifts,
        )
        self.assertEqual(
            updated.analysis_results.performance.difficulty,
            previous_results.performance.difficulty,
        )
        self.assertEqual(updated.analysis_results.quality.overall_quality_score, 75.5)
        self.assertEqual(updated.generated_events, state.generated_events)
        self.assertEqual(updated.tab_positions, state.tab_positions)
        self.assertEqual(updated.timeline, state.timeline)

    def test_alternate_fingering_generation_is_deterministic(self) -> None:
        state = self._alternate_state()
        analyzer = FingeringAnalyzer()

        first = analyzer.analyze_results(state).fingering.alternate_fingerings
        second = analyzer.analyze_results(state).fingering.alternate_fingerings

        self.assertGreater(len(first), 0)
        self.assertEqual(first, second)
        for alternate in first:
            self.assertIsInstance(alternate, AlternateFingering)

    def test_alternate_fingering_identical_input_produces_identical_candidates(self) -> None:
        state = self._alternate_state()
        duplicate = replace(state)

        first = FingeringAnalyzer().analyze_results(state).fingering.alternate_fingerings
        second = FingeringAnalyzer().analyze_results(duplicate).fingering.alternate_fingerings

        self.assertEqual(first, second)

    def test_alternate_fingering_preserves_pitches(self) -> None:
        state = self._alternate_state()
        expected_midi = tuple(event.midi for event in state.generated_events)

        alternates = FingeringAnalyzer().analyze_results(state).fingering.alternate_fingerings

        for alternate in alternates:
            with self.subTest(candidate_id=alternate.candidate_id):
                self.assertEqual(
                    tuple(tab.midi for tab in alternate.replacement_tab_positions),
                    expected_midi,
                )

    def test_alternate_fingering_preserves_timeline_ids(self) -> None:
        state = self._alternate_state()
        expected_timeline_ids = tuple(
            event.timeline_event_id for event in state.timeline.events
        )

        alternates = FingeringAnalyzer().analyze_results(state).fingering.alternate_fingerings

        for alternate in alternates:
            self.assertEqual(alternate.timeline_event_ids, expected_timeline_ids)

    def test_alternate_fingering_preserves_note_event_ids(self) -> None:
        state = self._alternate_state()
        expected_note_ids = tuple(event.event_id for event in state.generated_events)

        alternates = FingeringAnalyzer().analyze_results(state).fingering.alternate_fingerings

        for alternate in alternates:
            self.assertEqual(alternate.note_event_ids, expected_note_ids)
            self.assertEqual(
                tuple(tab.event_id for tab in alternate.replacement_tab_positions),
                expected_note_ids,
            )

    def test_alternate_fingering_ranking_is_stable(self) -> None:
        state = self._alternate_state()

        alternates = FingeringAnalyzer().analyze_results(state).fingering.alternate_fingerings

        ranking_keys = [
            (
                -(alternate.quality_score),
                alternate.difficulty_score.overall_score if alternate.difficulty_score else 0.0,
                alternate.candidate_id,
            )
            for alternate in alternates
        ]
        self.assertEqual(ranking_keys, sorted(ranking_keys))

    def test_alternate_fingering_updates_project_state(self) -> None:
        state = self._alternate_state()

        updated = FingeringAnalyzer().analyze(state)

        self.assertIsNot(updated, state)
        self.assertEqual(state.analysis_results.fingering.alternate_fingerings, ())
        self.assertGreater(len(updated.analysis_results.fingering.alternate_fingerings), 0)
        self.assertEqual(updated.generated_events, state.generated_events)
        self.assertEqual(updated.tab_positions, state.tab_positions)
        self.assertEqual(updated.timeline, state.timeline)

    def test_alternate_fingering_candidate_ordering_uses_stable_ids(self) -> None:
        state = self._alternate_state()

        alternates = FingeringAnalyzer().analyze_results(state).fingering.alternate_fingerings

        self.assertEqual(
            [alternate.candidate_id for alternate in alternates],
            [
                stable_id("alternate_candidate", index)
                for index in range(1, len(alternates) + 1)
            ],
        )
        self.assertEqual(
            [alternate.alternate_id for alternate in alternates],
            [
                stable_id("alternate_fingering", index)
                for index in range(1, len(alternates) + 1)
            ],
        )

    def test_alternate_fingering_search_pruning_is_deterministic(self) -> None:
        state = self._alternate_state()
        analyzer = FingeringAnalyzer(
            passes=(
                ValidationPass(),
                FingerAssignmentPass(),
                StretchAnalysisPass(),
                PositionShiftPass(),
                DifficultyPass(),
                QualityPass(),
                AlternateFingeringPass(max_candidates=2, beam_width=4),
                PracticePreparationPass(),
            )
        )

        first = analyzer.analyze_results(state).fingering.alternate_fingerings
        second = analyzer.analyze_results(state).fingering.alternate_fingerings

        self.assertEqual(len(first), 2)
        self.assertEqual(first, second)
        self.assertEqual(
            [alternate.candidate_id for alternate in first],
            ["alternate_candidate_000001", "alternate_candidate_000002"],
        )

    def test_stretch_analysis_reports_no_issue_for_comfortable_span(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 6), (1, 8)])

        results = FingeringAnalyzer().analyze_results(state)

        self.assertEqual(results.fingering.stretch_issues, ())

    def test_stretch_analysis_reports_small_stretch(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 9)])

        issues = FingeringAnalyzer().analyze_results(state).fingering.stretch_issues

        self.assertEqual(len(issues), 1)
        issue = issues[0]
        self.assertIsInstance(issue, StretchIssue)
        self.assertEqual(issue.issue_id, "stretch_issue_000001")
        self.assertEqual(issue.timeline_event_ids, ("timeline_event_000001", "timeline_event_000002"))
        self.assertEqual(issue.assignment_ids, ("finger_assignment_000001", "finger_assignment_000002"))
        self.assertEqual(issue.tab_position_ids, ("tab_000001", "tab_000002"))
        self.assertEqual(issue.fret_span, 5)
        self.assertEqual(issue.position_fret, 5)
        self.assertEqual(issue.severity, "info")
        self.assertEqual(issue.reason, "span_exceeds_one_finger_per_fret")
        self.assertEqual(issue.confidence, 0.9)

    def test_stretch_analysis_reports_obvious_stretch_with_higher_severity(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 11)])

        issues = FingeringAnalyzer().analyze_results(state).fingering.stretch_issues

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].fret_span, 7)
        self.assertEqual(issues[0].severity, "high")

    def test_stretch_analysis_ignores_repeated_notes(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 5), (1, 5)])

        results = FingeringAnalyzer().analyze_results(state)

        self.assertEqual(results.fingering.stretch_issues, ())

    def test_stretch_analysis_ignores_open_strings(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (2, 0), (1, 10)])

        results = FingeringAnalyzer().analyze_results(state)

        self.assertEqual(results.fingering.stretch_issues, ())

    def test_stretch_analysis_detects_ascending_phrase_stretch(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 6), (1, 10)])

        issues = FingeringAnalyzer().analyze_results(state).fingering.stretch_issues

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].timeline_event_ids, ("timeline_event_000002", "timeline_event_000003"))
        self.assertEqual(issues[0].fret_span, 5)

    def test_stretch_analysis_detects_descending_phrase_stretch(self) -> None:
        state = self._state_for_tab_frets([(1, 10), (1, 6), (1, 5)])

        issues = FingeringAnalyzer().analyze_results(state).fingering.stretch_issues

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].timeline_event_ids, ("timeline_event_000001", "timeline_event_000002"))
        self.assertEqual(issues[0].fret_span, 5)

    def test_stretch_analysis_outputs_are_deterministic(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 9), (1, 14)])
        analyzer = FingeringAnalyzer()

        first = analyzer.analyze_results(state).fingering.stretch_issues
        second = analyzer.analyze_results(state).fingering.stretch_issues

        self.assertEqual(first, second)
        self.assertEqual(
            [issue.issue_id for issue in first],
            ["stretch_issue_000001", "stretch_issue_000002"],
        )

    def test_stretch_analysis_updates_project_state_without_changing_assignments(self) -> None:
        state = self._state_for_tab_frets([(1, 5), (1, 9)])
        assignment_only = FingeringAnalyzer(
            passes=(ValidationPass(), FingerAssignmentPass())
        ).analyze_results(state)

        updated = FingeringAnalyzer().analyze(state)

        self.assertIsNot(updated, state)
        self.assertEqual(state.analysis_results.fingering.stretch_issues, ())
        self.assertEqual(
            updated.analysis_results.fingering.assignments,
            assignment_only.fingering.assignments,
        )
        self.assertEqual(len(updated.analysis_results.fingering.stretch_issues), 1)
        self.assertEqual(updated.generated_events, state.generated_events)
        self.assertEqual(updated.tab_positions, state.tab_positions)
        self.assertEqual(updated.timeline, state.timeline)

    def test_analyzer_rejects_missing_tab_position_reference(self) -> None:
        state = self._valid_state()
        first_event = replace(
            state.timeline.events[0],
            tab_position_id="tab_999999",
        )
        invalid_timeline = replace(
            state.timeline,
            events=(first_event,) + state.timeline.events[1:],
        )
        invalid = replace(state, timeline=invalid_timeline)

        with self.assertRaisesRegex(ValueError, "missing TabPosition"):
            FingeringAnalyzer().analyze(invalid)

    def test_analyzer_rejects_orphan_tab_position(self) -> None:
        state = self._valid_state()
        orphan_tab = replace(
            state.tab_positions[0],
            event_id="event_999999",
        )
        invalid = replace(
            state,
            tab_positions=(orphan_tab,) + state.tab_positions[1:],
        )

        with self.assertRaisesRegex(ValueError, "missing NoteEvent"):
            FingeringAnalyzer().analyze(invalid)


if __name__ == "__main__":
    unittest.main()
