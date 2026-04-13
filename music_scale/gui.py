"""Tkinter GUI for live music scale detection."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

try:
    from .finder import ScaleFinder
    from .guitar import STANDARD_TUNING, fret_to_note
    from .notes import CHROMATIC_NOTES, note_index
except ImportError:
    # Support running this file directly (e.g., `python music_scale/gui.py`).
    from music_scale.finder import ScaleFinder
    from music_scale.guitar import STANDARD_TUNING, fret_to_note
    from music_scale.notes import CHROMATIC_NOTES, note_index


class ScaleFinderApp:
    """Desktop UI for note entry and live scale matching."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.finder = ScaleFinder()
        self.selected_notes: set[str] = set()

        self.note_buttons: dict[str, tk.Button] = {}
        self.fret_buttons_by_note: dict[str, list[tk.Button]] = {
            note: [] for note in CHROMATIC_NOTES
        }

        self.selected_notes_var = tk.StringVar()
        self.status_var = tk.StringVar()

        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        self.root.title("Music Scale Finder")
        self.root.geometry("1200x760")
        self.root.minsize(980, 680)

        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(
            main,
            text="Music Scale Finder - Click Notes or Guitar Frets",
            font=("Segoe UI", 16, "bold"),
        )
        title.pack(anchor=tk.W)

        subtitle = ttk.Label(
            main,
            text="Scale suggestions update live once at least 3 unique notes are selected.",
            font=("Segoe UI", 10),
        )
        subtitle.pack(anchor=tk.W, pady=(2, 10))

        top = ttk.Frame(main)
        top.pack(fill=tk.X)

        notes_frame = ttk.LabelFrame(top, text="Note Palette", padding=10)
        notes_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        for idx, note in enumerate(CHROMATIC_NOTES):
            btn = tk.Button(
                notes_frame,
                text=note,
                width=6,
                height=2,
                font=("Segoe UI", 10, "bold"),
                command=self._toggle_note_command(note),
            )
            row, col = divmod(idx, 6)
            btn.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")
            self.note_buttons[note] = btn

        for col in range(6):
            notes_frame.grid_columnconfigure(col, weight=1)

        controls_frame = ttk.LabelFrame(top, text="Session", padding=10)
        controls_frame.pack(side=tk.LEFT, fill=tk.Y)

        ttk.Button(controls_frame, text="Clear All", command=self._clear).pack(
            fill=tk.X, pady=(0, 8)
        )
        ttk.Label(
            controls_frame,
            text="Tip: Click again to deselect a note.",
            wraplength=200,
        ).pack(anchor=tk.W)

        selected_frame = ttk.LabelFrame(main, text="Selected Notes", padding=10)
        selected_frame.pack(fill=tk.X, pady=(10, 8))

        ttk.Label(
            selected_frame,
            textvariable=self.selected_notes_var,
            font=("Consolas", 11),
        ).pack(anchor=tk.W)

        fretboard_frame = ttk.LabelFrame(
            main,
            text="Guitar Input (Standard Tuning)",
            padding=10,
        )
        fretboard_frame.pack(fill=tk.BOTH, expand=False, pady=(4, 10))

        self._build_fretboard(fretboard_frame, max_fret=12)

        results_frame = ttk.LabelFrame(main, text="Matching Scales", padding=10)
        results_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            results_frame,
            textvariable=self.status_var,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor=tk.W, pady=(0, 8))

        list_wrap = ttk.Frame(results_frame)
        list_wrap.pack(fill=tk.BOTH, expand=True)

        self.result_list = tk.Listbox(
            list_wrap,
            font=("Consolas", 10),
            activestyle="none",
        )
        self.result_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scroll = ttk.Scrollbar(list_wrap, orient=tk.VERTICAL, command=self.result_list.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.result_list.config(yscrollcommand=scroll.set)

    def _build_fretboard(self, parent: ttk.LabelFrame, max_fret: int) -> None:
        strings = sorted(STANDARD_TUNING.keys())

        ttk.Label(
            parent,
            text="String/Fret",
            font=("Segoe UI", 9, "bold"),
            padding=(3, 2),
        ).grid(row=0, column=0, sticky="w")
        for fret in range(0, max_fret + 1):
            ttk.Label(
                parent,
                text=str(fret),
                font=("Segoe UI", 9, "bold"),
                padding=(3, 2),
            ).grid(
                row=0, column=fret + 1, sticky="nsew"
            )

        for row_index, string_id in enumerate(strings, start=1):
            open_note = STANDARD_TUNING[string_id]
            ttk.Label(
                parent,
                text=f"{string_id} ({open_note})",
                font=("Segoe UI", 9, "bold"),
            ).grid(row=row_index, column=0, padx=3, pady=2, sticky="w")

            for fret in range(0, max_fret + 1):
                note = fret_to_note(string_id, fret)
                btn = tk.Button(
                    parent,
                    text=note,
                    width=4,
                    height=1,
                    font=("Segoe UI", 8),
                    command=self._toggle_note_command(note),
                )
                btn.grid(row=row_index, column=fret + 1, padx=1, pady=1, sticky="nsew")
                self.fret_buttons_by_note[note].append(btn)

        for col in range(max_fret + 2):
            parent.grid_columnconfigure(col, weight=1)

    def _toggle_note(self, note: str) -> None:
        if note in self.selected_notes:
            self.selected_notes.remove(note)
        else:
            self.selected_notes.add(note)
        self._refresh()

    def _toggle_note_command(self, note: str) -> Callable[[], None]:
        def handler() -> None:
            self._toggle_note(note)

        return handler

    def _clear(self) -> None:
        self.selected_notes.clear()
        self._refresh()

    def _refresh(self) -> None:
        ordered_notes = sorted(self.selected_notes, key=note_index)
        if ordered_notes:
            self.selected_notes_var.set(
                f"{len(ordered_notes)} unique: " + ", ".join(ordered_notes)
            )
        else:
            self.selected_notes_var.set("0 unique: (none)")

        self._refresh_button_states()
        self._refresh_matches(ordered_notes)

    def _refresh_button_states(self) -> None:
        for note, btn in self.note_buttons.items():
            self._style_note_button(btn, is_selected=note in self.selected_notes)

        for note, buttons in self.fret_buttons_by_note.items():
            selected = note in self.selected_notes
            for btn in buttons:
                self._style_fret_button(btn, is_selected=selected)

    def _style_note_button(self, button: tk.Button, is_selected: bool) -> None:
        if is_selected:
            button.config(bg="#1f6feb", fg="white", relief=tk.SUNKEN, bd=2)
        else:
            button.config(bg="#f0f0f0", fg="black", relief=tk.RAISED, bd=1)

    def _style_fret_button(self, button: tk.Button, is_selected: bool) -> None:
        if is_selected:
            button.config(bg="#35a853", fg="white", relief=tk.SUNKEN, bd=1)
        else:
            button.config(bg="#f7f7f7", fg="black", relief=tk.RAISED, bd=1)

    def _refresh_matches(self, ordered_notes: list[str]) -> None:
        self.result_list.delete(0, tk.END)

        if len(ordered_notes) < 3:
            needed = 3 - len(ordered_notes)
            self.status_var.set(f"Waiting for at least 3 unique notes ({needed} more needed).")
            return

        matches = self.finder.find_matches(ordered_notes, min_notes=3)
        if not matches:
            self.status_var.set("No matching scales found for this note group.")
            return

        self.status_var.set(f"{len(matches)} matching scales found.")
        for match in matches:
            scale_notes = ", ".join(match.scale_notes)
            self.result_list.insert(tk.END, f"{match.label} -> {scale_notes}")


def main() -> None:
    root = tk.Tk()
    ScaleFinderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
