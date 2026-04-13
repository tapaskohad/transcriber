from __future__ import annotations

import unittest

from music_scale.finder import ScaleFinder
from music_scale.notes import CHROMATIC_NOTES
from music_scale.scales import ScalePattern


class FinderEngineTests(unittest.TestCase):
    def test_find_matches_returns_empty_before_min_notes(self) -> None:
        finder = ScaleFinder()

        matches = finder.find_matches(["C", "E"], min_notes=3)

        self.assertEqual(matches, [])

    def test_find_matches_contains_expected_scale(self) -> None:
        finder = ScaleFinder()

        labels = {match.label for match in finder.find_matches(["C", "E", "G"])}

        self.assertIn("C Major (Ionian)", labels)

    def test_find_matches_are_sorted_by_public_contract(self) -> None:
        finder = ScaleFinder()
        root_order = {note: idx for idx, note in enumerate(CHROMATIC_NOTES)}

        matches = finder.find_matches(["C", "E", "G"])
        sort_keys = [
            (len(match.scale_notes), match.pattern_name, root_order[match.root])
            for match in matches
        ]

        self.assertEqual(sort_keys, sorted(sort_keys))

    def test_custom_pattern_library_is_supported(self) -> None:
        finder = ScaleFinder(patterns=(ScalePattern("Major Triad", (0, 4, 7)),))

        matches = finder.find_matches(["C", "E", "G"], min_notes=3)

        self.assertEqual([match.label for match in matches], ["C Major Triad"])


if __name__ == "__main__":
    unittest.main()
