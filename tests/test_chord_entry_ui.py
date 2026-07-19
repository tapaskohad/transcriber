from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from music_scale.web_ui import _build_html


@unittest.skipUnless(shutil.which("node"), "Node.js is required for sequencer UI tests.")
class ChordEntryUiTests(unittest.TestCase):
    """Exercise the modifier-driven chord editor without a browser dependency."""

    @classmethod
    def setUpClass(cls) -> None:
        html = _build_html()
        start = html.index("      function normalizeNoteToken")
        end = html.index("      function setSequencerStatus", start)
        cls.editor_source = "\n".join(
            line[6:] if line.startswith("      ") else line
            for line in html[start:end].splitlines()
        )

    def _run_editor_test(self, assertions: str) -> None:
        harness = f"""
"use strict";
const NOTE_WITH_OPTIONAL_TAB_RE = /^([A-Ga-g])([#b]?)(-?\\d+)(?:@([1-6]:\\d+))?$/;
const KEYS = {{ seqEditor: "seqEditor" }};
const writes = new Map();
const seqEls = {{
  editor: {{ value: "" }},
  nextLineBtn: {{
    classList: {{ toggle() {{}} }},
    setAttribute() {{}},
    dataset: {{}},
    textContent: "",
    title: "",
  }},
}};
function writeText(key, value) {{ writes.set(key, value); }}
function pulseOnce() {{}}
function assert(condition, message) {{ if (!condition) throw new Error(message); }}
{self.editor_source}
{assertions}
"""
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            harness_path = Path(directory) / "chord_entry_harness.js"
            harness_path.write_text(harness, encoding="utf-8")
            completed = subprocess.run(
                [str(shutil.which("node")), str(harness_path)],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_modifier_click_creates_two_note_chord(self) -> None:
        self._run_editor_test(
            """
appendSequencerFromFret("C4", 2, 1);
appendSequencerFromFret("E4", 1, 0, { ctrlKey: true });
const layout = parseSequencerLayout(seqEls.editor.value);
assert(layout.groups.length === 1, "modifier must keep the current beat");
assert(layout.groups[0].map((item) => item.note).join(",") === "C4,E4", "two note chord missing");
"""
        )

    def test_modifier_click_creates_three_note_chord(self) -> None:
        self._run_editor_test(
            """
appendSequencerFromFret("C4", 2, 1);
appendSequencerFromFret("E4", 1, 0, { metaKey: true });
appendSequencerFromFret("G4", 1, 3, { shiftKey: true });
const layout = parseSequencerLayout(seqEls.editor.value);
assert(layout.groups.length === 1, "three-note chord must occupy one beat");
assert(layout.groups[0].map((item) => item.note).join(",") === "C4,E4,G4", "three note chord missing");
"""
        )

    def test_undo_deletes_only_one_note_from_a_chord(self) -> None:
        self._run_editor_test(
            """
seqEls.editor.value = "C4@2:1 + E4@1:0 + G4@1:3";
sequencerUndo();
const layout = parseSequencerLayout(seqEls.editor.value);
assert(layout.groups.length === 1, "deleting one note must retain the chord beat");
assert(layout.groups[0].map((item) => item.note).join(",") === "C4,E4", "wrong chord note was deleted");
"""
        )

    def test_text_edit_can_move_one_chord_note_without_moving_its_sibling(self) -> None:
        self._run_editor_test(
            """
const layout = parseSequencerLayout("C4@2:1 + E4@1:0 -> G4@1:3");
const moved = layout.groups[0].pop();
layout.groups[1].push(moved);
seqEls.editor.value = serializeSequencerLayout(layout.groups, layout.lineGroupLengths);
const updated = parseSequencerLayout(seqEls.editor.value);
assert(updated.groups[0].map((item) => item.note).join(",") === "C4", "sibling note moved too");
assert(updated.groups[1].map((item) => item.note).join(",") === "G4,E4", "moved note is not on its new beat");
"""
        )

    def test_chord_text_round_trips_through_persisted_editor_value(self) -> None:
        self._run_editor_test(
            """
const original = "C4@2:1 + E4@1:0 + G4@1:3 -> C5@1:8";
const layout = parseSequencerLayout(original);
const restored = parseSequencerLayout(serializeSequencerLayout(layout.groups, layout.lineGroupLengths));
assert(restored.groups.length === 2, "saved sequence lost a beat");
assert(restored.groups[0].map((item) => item.note).join(",") === "C4,E4,G4", "saved chord lost notes");
"""
        )

    def test_normal_click_after_a_chord_starts_the_next_beat(self) -> None:
        self._run_editor_test(
            """
appendSequencerFromFret("C4", 2, 1);
appendSequencerFromFret("E4", 1, 0, { shiftKey: true });
appendSequencerFromFret("G4", 1, 3);
const layout = parseSequencerLayout(seqEls.editor.value);
assert(layout.groups.length === 2, "unmodified entry must keep monophonic workflow");
assert(layout.groups[0].length === 2 && layout.groups[1].length === 1, "chord/next beat split is wrong");
"""
        )


if __name__ == "__main__":
    unittest.main()
