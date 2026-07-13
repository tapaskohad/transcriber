from __future__ import annotations

from dataclasses import asdict, replace
import unittest

from music_scale.models import (
    AnalysisResults,
    AlternateFingering,
    DifficultyScore,
    FingerAssignment,
    FingeringAnalysis,
    PerformanceAnalysis,
    PositionShift,
    PracticeAnalysis,
    ProjectState,
    QualityReport,
    StretchIssue,
    TabPosition,
    TabQualityIssue,
    stable_id,
)


class AnalysisModelTests(unittest.TestCase):
    def test_stable_ids_are_deterministic_for_analysis_models(self) -> None:
        self.assertEqual(stable_id("finger_assignment", 1), "finger_assignment_000001")
        self.assertEqual(stable_id("stretch issue", 12), "stretch_issue_000012")
        self.assertEqual(stable_id("alternate", -4), "alternate_000000")

    def test_constructs_fingering_models_with_canonical_references(self) -> None:
        assignment = FingerAssignment(
            assignment_id=stable_id("finger_assignment", 1),
            timeline_event_id="timeline_event_000001",
            note_event_id="event_000001",
            tab_position_id="tab_000001",
            finger=1,
            position_fret=2,
            confidence=0.92,
            reason="Index finger anchors the position.",
        )
        stretch = StretchIssue(
            issue_id=stable_id("stretch", 1),
            timeline_event_ids=("timeline_event_000001", "timeline_event_000002"),
            note_event_ids=("event_000001", "event_000002"),
            tab_position_ids=("tab_000001", "tab_000002"),
            fret_span=5,
            severity="warn",
            message="Wide fret span.",
            suggested_position_fret=3,
        )
        shift = PositionShift(
            shift_id=stable_id("position_shift", 1),
            from_timeline_event_id="timeline_event_000001",
            to_timeline_event_id="timeline_event_000002",
            from_note_event_id="event_000001",
            to_note_event_id="event_000002",
            from_tab_position_id="tab_000001",
            to_tab_position_id="tab_000002",
            from_position_fret=2,
            to_position_fret=7,
            distance=5,
            confidence=0.8,
            reason="Move to upper position for the phrase.",
        )

        self.assertEqual(assignment.timeline_event_id, "timeline_event_000001")
        self.assertEqual(assignment.note_event_id, "event_000001")
        self.assertEqual(assignment.tab_position_id, "tab_000001")
        self.assertEqual(stretch.timeline_event_ids, ("timeline_event_000001", "timeline_event_000002"))
        self.assertEqual(shift.to_tab_position_id, "tab_000002")

    def test_analysis_results_serializes_without_duplicate_timeline_data(self) -> None:
        tab = TabPosition(
            position_id="tab_000001",
            event_id="event_000001",
            string_id=1,
            fret=3,
            midi=67,
            note="G",
            octave=4,
        )
        assignment = FingerAssignment(
            assignment_id="finger_assignment_000001",
            timeline_event_id="timeline_event_000001",
            note_event_id="event_000001",
            tab_position_id="tab_000001",
            finger=3,
        )
        difficulty = DifficultyScore(
            score_id="difficulty_000001",
            overall=42.0,
            label="moderate",
            stretch=12.0,
            movement=18.0,
            speed=4.0,
            position_shifts=3.0,
            string_crossing=2.0,
            fingering=3.0,
            confidence=0.9,
        )
        alternate = AlternateFingering(
            alternate_id="alternate_000001",
            timeline_event_ids=("timeline_event_000001",),
            note_event_ids=("event_000001",),
            tab_positions=(tab,),
            finger_assignments=(assignment,),
            quality_score=0.88,
            difficulty_score=difficulty,
            tradeoffs=("Uses a higher fret.",),
        )
        quality_issue = TabQualityIssue(
            issue_id="quality_issue_000001",
            timeline_event_id="timeline_event_000001",
            note_event_id="event_000001",
            tab_position_id="tab_000001",
            category="movement",
            severity="info",
            message="Small position adjustment.",
            metric=1.5,
        )
        results = AnalysisResults(
            analysis_id="analysis_results_000001",
            fingering=FingeringAnalysis(
                analysis_id="fingering_analysis_000001",
                assignments=(assignment,),
                alternate_fingerings=(alternate,),
                difficulty=difficulty,
            ),
            performance=PerformanceAnalysis(
                analysis_id="performance_analysis_000001",
                difficulty=difficulty,
                movement_score=18.0,
                issues=(quality_issue,),
            ),
            quality=QualityReport(score=0.87, warnings=("Review movement.",)),
            practice=PracticeAnalysis(
                analysis_id="practice_analysis_000001",
                focus_timeline_event_ids=("timeline_event_000001",),
                loop_start_event_id="timeline_event_000001",
                loop_end_event_id="timeline_event_000001",
                recommended_tempo_bpm=96.0,
            ),
            generated_from_timeline_id="timeline_default",
        )

        payload = asdict(results)

        self.assertEqual(payload["analysis_id"], "analysis_results_000001")
        self.assertEqual(
            payload["fingering"]["assignments"][0]["timeline_event_id"],
            "timeline_event_000001",
        )
        self.assertEqual(
            payload["fingering"]["alternate_fingerings"][0]["tab_positions"][0]["position_id"],
            "tab_000001",
        )
        self.assertEqual(payload["performance"]["issues"][0]["category"], "movement")
        self.assertEqual(payload["quality"]["score"], 0.87)
        self.assertEqual(payload["practice"]["recommended_tempo_bpm"], 96.0)
        self.assertNotIn("timeline", payload)
        self.assertNotIn("events", payload)

    def test_project_state_defaults_remain_backwards_compatible(self) -> None:
        state = ProjectState()

        self.assertIsInstance(state.analysis_results, AnalysisResults)
        self.assertIsInstance(state.quality_metadata, QualityReport)
        self.assertEqual(state.analysis_results.analysis_id, "analysis_results_default")
        self.assertEqual(state.generated_events, ())
        self.assertEqual(state.tab_positions, ())

    def test_project_state_preserves_analysis_results_container(self) -> None:
        results = AnalysisResults(
            analysis_id="analysis_results_000123",
            quality=QualityReport(score=0.74, metrics={"movement": 0.2}),
            generated_from_timeline_id="timeline_default",
        )
        state = ProjectState(analysis_results=results)
        updated = replace(state, selected_notes=("E", "G"))

        self.assertIs(state.analysis_results, results)
        self.assertIs(updated.analysis_results, results)
        self.assertEqual(updated.selected_notes, ("E", "G"))


if __name__ == "__main__":
    unittest.main()
