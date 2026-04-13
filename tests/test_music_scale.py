from __future__ import annotations

import unittest

from music_scale.guitar import fret_to_note, fret_to_note_name, parse_tab_position
from music_scale.notes import normalize_note
from music_scale.session import MelodySession


class MusicScaleTests(unittest.TestCase):
    def test_note_normalization_supports_flats(self) -> None:
        self.assertEqual(normalize_note("Bb"), "A#")
        self.assertEqual(normalize_note("c#"), "C#")

    def test_tab_position_parsing(self) -> None:
        self.assertEqual(parse_tab_position("6:3"), (6, 3))
        self.assertEqual(fret_to_note(6, 3), "G")

    def test_fret_to_note_name_includes_octave(self) -> None:
        self.assertEqual(fret_to_note_name(5, 0), "A2")
        self.assertEqual(fret_to_note_name(5, 1), "A#2")
        self.assertEqual(fret_to_note_name(5, 12), "A3")

    def test_matching_starts_after_three_unique_notes(self) -> None:
        session = MelodySession()
        session.add_notes(["C", "E"])
        self.assertEqual(session.get_matches(), [])

        session.add_notes(["G"])
        matches = session.get_matches()
        labels = {m.label for m in matches}
        self.assertIn("C Major (Ionian)", labels)


if __name__ == "__main__":
    unittest.main()
