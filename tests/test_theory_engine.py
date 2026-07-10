from __future__ import annotations

import unittest

from music_scale.theory import TheoryEngine


class TheoryEngineTests(unittest.TestCase):
    def test_scale_analysis_returns_structured_major_candidate(self) -> None:
        engine = TheoryEngine()

        analyses = engine.analyze_scales(["C", "D", "E", "F", "G", "A", "B"])

        major = next(
            item
            for item in analyses
            if item.root == "C" and item.scale_name == "Major (Ionian)"
        )
        self.assertTrue(major.exact_match)
        self.assertEqual(major.interval_formula, ("1", "2", "3", "4", "5", "6", "7"))
        self.assertEqual(major.extra_notes, ())
        self.assertEqual(major.missing_notes, ())
        self.assertEqual(major.relative_major_minor["root"], "A")
        self.assertEqual(major.mode_family, "major")
        self.assertGreater(len(major.compatible_chords), 0)

    def test_interval_analysis_marks_out_of_scale_notes(self) -> None:
        engine = TheoryEngine()

        intervals = engine.analyze_intervals(
            ["C", "D#", "G"],
            root="C",
            scale_notes=("C", "D", "E", "F", "G", "A", "B"),
        )

        by_note = {item.note: item for item in intervals}
        self.assertEqual(by_note["D#"].degree, "b3")
        self.assertFalse(by_note["D#"].in_scale)
        self.assertEqual(by_note["G"].degree, "5")

    def test_chord_detection_ranks_exact_major_seventh(self) -> None:
        engine = TheoryEngine()

        candidates = engine.detect_chords(["C", "E", "G", "B"])

        self.assertGreater(len(candidates), 0)
        self.assertEqual(candidates[0].name, "Cmaj7")
        self.assertEqual(candidates[0].root, "C")
        self.assertEqual(candidates[0].confidence, 1.0)
        self.assertIn("7", candidates[0].intervals)

    def test_chord_detection_supports_power_chords(self) -> None:
        engine = TheoryEngine()

        candidates = engine.detect_chords(["A", "E"])

        names = {candidate.name for candidate in candidates}
        self.assertIn("A5", names)

    def test_position_suggestions_cover_selected_notes(self) -> None:
        engine = TheoryEngine()

        suggestions = engine.suggest_positions(["E", "G", "A"], max_fret=12)

        self.assertGreater(len(suggestions), 0)
        best = suggestions[0]
        covered = {position.note for position in best.positions}
        self.assertTrue({"E", "G", "A"}.issubset(covered))
        self.assertGreaterEqual(best.confidence, 0.0)
        self.assertLessEqual(best.confidence, 1.0)


if __name__ == "__main__":
    unittest.main()
