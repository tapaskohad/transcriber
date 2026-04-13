from __future__ import annotations

import unittest

from music_scale.session import MelodySession


class SessionWorkflowTests(unittest.TestCase):
    def test_add_tab_supports_pair_format(self) -> None:
        session = MelodySession()

        added = session.add_tab(["6", "3", "5", "0"])

        self.assertEqual(added, ["G", "A"])
        self.assertEqual(session.note_count, 2)

    def test_add_tab_requires_even_pair_tokens_without_colon(self) -> None:
        session = MelodySession()

        with self.assertRaises(ValueError):
            session.add_tab(["6", "3", "5"])

    def test_undo_is_batch_aware(self) -> None:
        session = MelodySession()
        session.add_notes(["C", "E"])
        session.add_notes(["G"])

        removed = session.undo()

        self.assertEqual(removed, ["G"])
        self.assertEqual(session.notes, ("C", "E"))

    def test_clear_resets_state_and_history(self) -> None:
        session = MelodySession()
        session.add_notes(["C", "E", "G"])

        session.clear()

        self.assertEqual(session.notes, ())
        self.assertEqual(session.note_count, 0)
        self.assertEqual(session.undo(), [])


if __name__ == "__main__":
    unittest.main()
