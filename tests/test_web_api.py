from __future__ import annotations

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from typing import cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from music_scale.finder import ScaleFinder
from music_scale.melody_transcriber import MelodyTranscriber
from music_scale.web_ui import (
    _ScaleRequestHandler,
    _build_config,
    _build_html,
    _build_tab_sequencer_html,
    _build_transcriber_html,
)


class WebApiTests(unittest.TestCase):
    _server: ThreadingHTTPServer
    _thread: threading.Thread
    _base_url: str

    @classmethod
    def setUpClass(cls) -> None:
        handler = _ScaleRequestHandler
        handler.config = _build_config()
        handler.finder = ScaleFinder()
        handler.transcriber = MelodyTranscriber(max_fret=handler.config["max_fret"])
        handler.html = _build_html().encode("utf-8")
        handler.transcriber_html = _build_transcriber_html().encode("utf-8")
        handler.tab_sequencer_html = _build_tab_sequencer_html().encode("utf-8")
        handler.max_body_bytes = 8 * 1024

        cls._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls._thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._thread.start()
        cls._base_url = f"http://127.0.0.1:{cls._server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls._server.shutdown()
        cls._server.server_close()
        cls._thread.join(timeout=2)

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, object] | list[object] | None = None,
    ) -> tuple[int, dict[str, object]]:
        headers: dict[str, str] = {}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(f"{self._base_url}{path}", data=data, method=method, headers=headers)
        try:
            with urlopen(request, timeout=4) as response:
                body = response.read().decode("utf-8")
                parsed = json.loads(body)
                if not isinstance(parsed, dict):
                    self.fail("Expected JSON object response body.")
                return response.status, cast(dict[str, object], parsed)
        except HTTPError as exc:
            body = exc.read().decode("utf-8")
            parsed = json.loads(body)
            if not isinstance(parsed, dict):
                self.fail("Expected JSON object response body.")
            return exc.code, cast(dict[str, object], parsed)

    def _require_str(self, value: object, field: str) -> str:
        if not isinstance(value, str):
            self.fail(f"Expected '{field}' to be a string, got {type(value).__name__}.")
        return value

    def _require_list(self, value: object, field: str) -> list[object]:
        if not isinstance(value, list):
            self.fail(f"Expected '{field}' to be a list, got {type(value).__name__}.")
        return value

    def test_get_config_supports_query_string(self) -> None:
        status, payload = self._request_json("/api/config?cache=1")

        self.assertEqual(status, 200)
        self.assertEqual(payload["min_notes"], 3)
        self.assertEqual(payload["max_fret"], 12)

    def test_match_endpoint_supports_query_string(self) -> None:
        status, payload = self._request_json(
            "/api/match?source=test",
            method="POST",
            payload={"notes": ["C", "E", "G", "C"]},
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["selected_notes"], ["C", "E", "G"])
        self.assertEqual(payload["count"], 3)

    def test_tab_sequencer_page_is_available(self) -> None:
        request = Request(f"{self._base_url}/tab-sequencer", method="GET")
        with urlopen(request, timeout=4) as response:
            body = response.read().decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("Music Scale Studio", body)
        self.assertIn("Tab Sequencer", body)

    def test_mode_routes_share_single_shell(self) -> None:
        pages = ["/", "/transcriber", "/tab-sequencer"]
        for page in pages:
            request = Request(f"{self._base_url}{page}", method="GET")
            with urlopen(request, timeout=4) as response:
                body = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertIn("Music Scale Studio", body)
            self.assertIn("Scale Finder", body)
            self.assertIn("Transcriber", body)
            self.assertIn("Tab Sequencer", body)

    def test_transcribe_notes_mode_returns_expected_data(self) -> None:
        status, payload = self._request_json(
            "/api/transcribe",
            method="POST",
            payload={"mode": "notes", "notes": ["E4", "F#4", "G4"]},
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["notes"], ["E4", "F#4", "G4"])
        self.assertEqual(payload["tab_tokens"], ["1:0", "1:2", "1:3"])

    def test_transcribe_notes_mode_supports_tab_strategy_and_group_gap(self) -> None:
        status, payload = self._request_json(
            "/api/transcribe",
            method="POST",
            payload={
                "mode": "notes",
                "note_groups": [["E4"], ["F#4"]],
                "tab_strategy": "single_string",
                "locked_string": 1,
                "group_gap": 5,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["tab_groups"], [["1:0"], ["1:2"]])
        ascii_tab = self._require_str(payload["ascii_tab"], "ascii_tab")
        self.assertIn("-----", ascii_tab)

    def test_transcribe_notes_mode_as_selected_honors_preferred_tabs(self) -> None:
        status, payload = self._request_json(
            "/api/transcribe",
            method="POST",
            payload={
                "mode": "notes",
                "note_groups": [["E4", "E4"]],
                "tab_strategy": "as_selected",
                "preferred_tabs": ["1:0", "2:5"],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["tab_tokens"], ["1:0", "2:5"])

    def test_transcribe_notes_mode_preserves_note_groups(self) -> None:
        status, payload = self._request_json(
            "/api/transcribe",
            method="POST",
            payload={
                "mode": "notes",
                "note_groups": [["E4", "F#4"], ["G4", "A4"]],
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["note_groups"], [["E4", "F#4"], ["G4", "A4"]])
        self.assertEqual(payload["tab_groups"], [["1:0", "1:2"], ["1:3", "1:5"]])
        ascii_tab = self._require_str(payload["ascii_tab"], "ascii_tab")
        self.assertIn("2---------3", ascii_tab)

    def test_transcribe_notes_mode_accepts_compact_notation_with_lyrics(self) -> None:
        status, payload = self._request_json(
            "/api/transcribe",
            method="POST",
            payload={
                "mode": "notes",
                "note_groups": [
                    ["D#G#A#G#", "D#G#F##G#"],
                    ["Tu", "Paas", "D#+", "C#+", "B"],
                ],
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(
            payload["note_groups"],
            [
                ["D#4", "G#4", "A#4", "G#4", "D#4", "G#4", "F#4", "G#4"],
                ["D#5", "C#5", "B4"],
            ],
        )
        tab_groups_raw = self._require_list(payload["tab_groups"], "tab_groups")
        tab_groups = [
            self._require_list(group, "tab_groups[]")
            for group in tab_groups_raw
        ]
        notes = self._require_list(payload["notes"], "notes")
        self.assertEqual(sum(len(group) for group in tab_groups), len(notes))

    def test_transcribe_notes_mode_plus_octave_falls_back_when_needed(self) -> None:
        status, payload = self._request_json(
            "/api/transcribe",
            method="POST",
            payload={
                "mode": "notes",
                "note_groups": [["D#+", "D#+", "D#+", "F#+E+", "C#+", "D#+", "C#+"]],
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(
            payload["note_groups"],
            [["D#5", "D#5", "D#5", "F#4", "E5", "C#5", "D#5", "C#5"]],
        )
        notes = self._require_list(payload["notes"], "notes")
        self.assertEqual(len(notes), 8)

    def test_rejects_non_object_json_body(self) -> None:
        status, payload = self._request_json(
            "/api/match",
            method="POST",
            payload=["C", "E", "G"],
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "JSON body must be an object.")

    def test_rejects_oversized_request_body(self) -> None:
        large_notes_blob = "C" * 9000
        status, payload = self._request_json(
            "/api/match",
            method="POST",
            payload={"notes": [large_notes_blob]},
        )

        self.assertEqual(status, 413)
        self.assertIn("Request body too large", str(payload["error"]))


if __name__ == "__main__":
    unittest.main()
