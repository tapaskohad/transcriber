from __future__ import annotations

import unittest

from music_scale.melody_transcriber import MelodyTranscriber, frequency_to_note


class MelodyTranscriberTests(unittest.TestCase):
    def test_frequency_to_note_a4(self) -> None:
        note, octave, midi = frequency_to_note(440.0)
        self.assertEqual((note, octave, midi), ("A", 4, 69))

    def test_transcribe_frequencies_returns_notes_and_tabs(self) -> None:
        transcriber = MelodyTranscriber(max_fret=12, min_note_duration_s=0.05)
        frames = [440.0] * 8 + [0.0] * 3 + [493.88] * 8 + [0.0] * 2 + [523.25] * 8

        result = transcriber.transcribe_frequencies(frames, frame_step_s=0.05)

        self.assertEqual(result.notes, ("A4", "B4", "C5"))
        self.assertEqual(result.tab_tokens, ("1:5", "1:7", "1:8"))

    def test_transcribe_note_tokens_with_octaves(self) -> None:
        transcriber = MelodyTranscriber(max_fret=12)

        result = transcriber.transcribe_notes(["E4", "F#4", "G4"])

        self.assertEqual(result.notes, ("E4", "F#4", "G4"))
        self.assertEqual(result.tab_tokens, ("1:0", "1:2", "1:3"))
        self.assertIn("e|0--2--3--|", result.ascii_tab)
        self.assertIn("E|---------|", result.ascii_tab)


    def test_filter_note_tokens_ignores_non_notation_text(self) -> None:
        tokens = [
            "B3", "B3", "B3", "F#4", "F#4", "F#4",
            "In", "Russia", "long", "ago",
            "A",
            "C#4", "D4", "E4",
            "lovely", "dear",
        ]

        filtered = MelodyTranscriber.filter_note_tokens(tokens)

        self.assertEqual(filtered, ["B3", "B3", "B3", "F#4", "F#4", "F#4", "C#4", "D4", "E4"])
    def test_unplayable_note_raises(self) -> None:
        transcriber = MelodyTranscriber(max_fret=12)

        with self.assertRaises(ValueError):
            transcriber.transcribe_notes(["C7"])


if __name__ == "__main__":
    unittest.main()
