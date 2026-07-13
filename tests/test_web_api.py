from __future__ import annotations

import base64
from dataclasses import asdict
import io
import json
import math
import threading
import time
import unittest
import wave
from http.server import ThreadingHTTPServer
from typing import cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from music_scale.finder import ScaleFinder
from music_scale.melody_transcriber import MelodyTranscriber
from music_scale.playback import TimelineBuilder
from music_scale.theory import TheoryEngine
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
        handler.theory = TheoryEngine()
        handler.timeline_builder = TimelineBuilder()
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

    def _request_raw_json(
        self,
        path: str,
        raw_body: bytes,
        *,
        method: str = "POST",
    ) -> tuple[int, dict[str, object]]:
        request = Request(
            f"{self._base_url}{path}",
            data=raw_body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=4) as response:
                parsed = json.loads(response.read().decode("utf-8"))
                if not isinstance(parsed, dict):
                    self.fail("Expected JSON object response body.")
                return response.status, cast(dict[str, object], parsed)
        except HTTPError as exc:
            parsed = json.loads(exc.read().decode("utf-8"))
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

    def _require_dict(self, value: object, field: str) -> dict[str, object]:
        if not isinstance(value, dict):
            self.fail(f"Expected '{field}' to be an object, got {type(value).__name__}.")
        return cast(dict[str, object], value)

    def _require_analysis_error(
        self,
        payload: dict[str, object],
        *,
        code: str,
    ) -> dict[str, object]:
        self.assertFalse(payload["success"])
        error = self._require_dict(payload.get("error"), "error")
        self.assertEqual(list(error.keys()), ["code", "message"])
        self.assertEqual(error["code"], code)
        self.assertIsInstance(error["message"], str)
        return error

    def _analysis_payload(self) -> dict[str, object]:
        result = MelodyTranscriber().transcribe_notes(["E4", "F#4", "G4", "A4"])
        return {"project_state": asdict(result.project_state)}

    def _mutable_analysis_payload(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(json.dumps(self._analysis_payload())))

    def _build_test_wav_bytes(self) -> bytes:
        sample_rate = 8000
        frame_count = int(sample_rate * 0.20)
        amplitude = int(32767 * 0.36)

        frames = bytearray()
        for index in range(frame_count):
            phase = (2.0 * math.pi * 440.0 * index) / sample_rate
            sample = int(amplitude * math.sin(phase))
            frames.extend(sample.to_bytes(2, byteorder="little", signed=True))

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(bytes(frames))

        return buffer.getvalue()

    def _build_test_wav_base64(self) -> str:
        return base64.b64encode(self._build_test_wav_bytes()).decode("ascii")

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

    def test_scale_analyze_endpoint_returns_structured_analysis(self) -> None:
        status, payload = self._request_json(
            "/api/scale/analyze",
            method="POST",
            payload={"notes": ["C", "D", "E", "F", "G", "A", "B"]},
        )

        self.assertEqual(status, 200)
        analyses = self._require_list(payload["analyses"], "analyses")
        major = next(
            item
            for item in analyses
            if isinstance(item, dict)
            and item.get("root") == "C"
            and item.get("scale_name") == "Major (Ionian)"
        )
        self.assertEqual(major["interval_formula"], ["1", "2", "3", "4", "5", "6", "7"])
        self.assertTrue(major["exact_match"])
        self.assertEqual(major["extra_notes"], [])
        self.assertIn("relative_major_minor", major)
        self.assertIn("compatible_chords", major)

    def test_chords_detect_endpoint_returns_ranked_candidates(self) -> None:
        status, payload = self._request_json(
            "/api/chords/detect",
            method="POST",
            payload={"notes": ["C", "E", "G", "B"]},
        )

        self.assertEqual(status, 200)
        candidates = self._require_list(payload["candidates"], "candidates")
        self.assertGreater(len(candidates), 0)
        first = candidates[0]
        self.assertIsInstance(first, dict)
        if isinstance(first, dict):
            self.assertEqual(first["name"], "Cmaj7")
            self.assertEqual(first["root"], "C")
            self.assertEqual(first["confidence"], 1.0)

    def test_positions_suggest_endpoint_returns_playable_positions(self) -> None:
        status, payload = self._request_json(
            "/api/positions/suggest",
            method="POST",
            payload={"notes": ["E", "G", "A"], "max_fret": 12},
        )

        self.assertEqual(status, 200)
        suggestions = self._require_list(payload["suggestions"], "suggestions")
        self.assertGreater(len(suggestions), 0)
        first = suggestions[0]
        self.assertIsInstance(first, dict)
        if isinstance(first, dict):
            self.assertIn("position_number", first)
            self.assertIn("average_fret", first)
            self.assertIn("confidence", first)
            self.assertIn("positions", first)

    def test_playback_prepare_endpoint_returns_timeline(self) -> None:
        status, payload = self._request_json(
            "/api/playback/prepare",
            method="POST",
            payload={"note_groups": [["E4", "F#4"], ["G4"]]},
        )

        self.assertEqual(status, 200)
        timeline = payload.get("timeline")
        self.assertIsInstance(timeline, dict)
        if isinstance(timeline, dict):
            events = self._require_list(timeline.get("events"), "timeline.events")
            self.assertEqual(len(events), 3)
            first = events[0]
            self.assertIsInstance(first, dict)
            if isinstance(first, dict):
                self.assertEqual(first["timeline_event_id"], "timeline_event_000001")
                self.assertEqual(first["note"], "E4")
                self.assertEqual(first["pitch_class"], "E")
                self.assertEqual(first["string"], 1)
                self.assertEqual(first["fret"], 0)
                self.assertEqual(first["group_id"], "group_000001")
            third = events[2]
            self.assertIsInstance(third, dict)
            if isinstance(third, dict):
                self.assertEqual(third["group_id"], "group_000002")

        tempo = payload.get("tempo")
        self.assertIsInstance(tempo, dict)
        if isinstance(tempo, dict):
            self.assertEqual(tempo["bpm"], 120.0)

        markers = self._require_list(payload.get("markers"), "markers")
        self.assertGreater(len(markers), 0)
        playback_status = payload.get("playback_status")
        self.assertIsInstance(playback_status, dict)
        if isinstance(playback_status, dict):
            self.assertFalse(playback_status["is_playing"])
            self.assertEqual(playback_status["current_time_s"], 0.0)
            self.assertIsNone(playback_status["current_event"])
            self.assertFalse(playback_status["loop_enabled"])
            self.assertEqual(playback_status["playback_speed"], 1.0)
        synchronization_ids = self._require_list(
            payload.get("synchronization_ids"),
            "synchronization_ids",
        )
        self.assertEqual(len(synchronization_ids), 3)

    def test_analysis_endpoint_returns_complete_analysis(self) -> None:
        status, payload = self._request_json(
            "/api/analysis",
            method="POST",
            payload=self._analysis_payload(),
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["success"])
        analysis = self._require_dict(payload.get("analysis"), "analysis")
        fingering = self._require_dict(analysis.get("fingering"), "analysis.fingering")
        assignments = self._require_list(fingering.get("assignments"), "assignments")
        self.assertEqual(len(assignments), 4)
        first_assignment = self._require_dict(assignments[0], "assignments[0]")
        self.assertEqual(first_assignment["timeline_event_id"], "timeline_event_000001")
        self.assertEqual(first_assignment["note_event_id"], "event_000001")
        self.assertIn("performance", analysis)
        self.assertIn("quality", analysis)
        self.assertIn("practice", analysis)

    def test_fingering_endpoint_returns_fingering_analysis_only(self) -> None:
        status, payload = self._request_json(
            "/api/fingering",
            method="POST",
            payload=self._analysis_payload(),
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["success"])
        self.assertNotIn("analysis", payload)
        fingering = self._require_dict(payload.get("fingering"), "fingering")
        assignments = self._require_list(fingering.get("assignments"), "assignments")
        alternates = self._require_list(
            fingering.get("alternate_fingerings"),
            "alternate_fingerings",
        )
        self.assertEqual(len(assignments), 4)
        self.assertGreater(len(alternates), 0)
        first_alternate = self._require_dict(alternates[0], "alternate_fingerings[0]")
        self.assertEqual(first_alternate["candidate_id"], "alternate_candidate_000001")

    def test_difficulty_endpoint_returns_difficulty_score_only(self) -> None:
        status, payload = self._request_json(
            "/api/difficulty",
            method="POST",
            payload=self._analysis_payload(),
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["success"])
        self.assertNotIn("analysis", payload)
        difficulty = self._require_dict(payload.get("difficulty"), "difficulty")
        self.assertEqual(difficulty["score_id"], "difficulty_000001")
        self.assertIn(difficulty["difficulty_level"], ["Easy", "Moderate", "Hard", "Expert"])
        self.assertIn("overall_score", difficulty)
        self.assertIn("reason_summary", difficulty)

    def test_quality_endpoint_returns_quality_report_only(self) -> None:
        status, payload = self._request_json(
            "/api/quality",
            method="POST",
            payload=self._analysis_payload(),
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["success"])
        self.assertNotIn("analysis", payload)
        quality = self._require_dict(payload.get("quality"), "quality")
        self.assertIn("overall_quality_score", quality)
        self.assertIn(quality["quality_level"], ["Excellent", "Good", "Fair", "Poor"])
        self.assertIn("quality_issues", quality)
        self.assertIn("recommendations", quality)
        self.assertIn("summary", quality)

    def test_alternates_endpoint_returns_alternate_fingerings_only(self) -> None:
        status, payload = self._request_json(
            "/api/alternates",
            method="POST",
            payload=self._analysis_payload(),
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["success"])
        self.assertNotIn("analysis", payload)
        alternates = self._require_list(payload.get("alternates"), "alternates")
        self.assertGreater(len(alternates), 0)
        first = self._require_dict(alternates[0], "alternates[0]")
        self.assertEqual(first["candidate_id"], "alternate_candidate_000001")
        replacement_tabs = self._require_list(
            first.get("replacement_tab_positions"),
            "replacement_tab_positions",
        )
        self.assertEqual(len(replacement_tabs), 4)

    def test_analysis_endpoints_use_stable_success_contract(self) -> None:
        cases = [
            ("/api/analysis", "analysis"),
            ("/api/fingering", "fingering"),
            ("/api/difficulty", "difficulty"),
            ("/api/quality", "quality"),
            ("/api/alternates", "alternates"),
        ]

        for path, result_key in cases:
            with self.subTest(path=path):
                status, payload = self._request_json(
                    path,
                    method="POST",
                    payload=self._analysis_payload(),
                )

                self.assertEqual(status, 200)
                self.assertEqual(list(payload.keys()), ["success", "data", result_key])
                self.assertTrue(payload["success"])
                data = self._require_dict(payload.get("data"), "data")
                self.assertEqual(list(data.keys()), [result_key])
                self.assertEqual(payload[result_key], data[result_key])

    def test_analysis_response_schema_keeps_stable_core_keys(self) -> None:
        status, payload = self._request_json(
            "/api/analysis",
            method="POST",
            payload=self._analysis_payload(),
        )

        self.assertEqual(status, 200)
        analysis = self._require_dict(payload.get("analysis"), "analysis")
        self.assertEqual(
            list(analysis.keys()),
            [
                "analysis_id",
                "fingering",
                "performance",
                "quality",
                "practice",
                "generated_from_timeline_id",
                "metrics",
            ],
        )
        self.assertNotIn("timeline", analysis)
        self.assertNotIn("generated_events", analysis)

        fingering = self._require_dict(analysis.get("fingering"), "analysis.fingering")
        self.assertEqual(
            list(fingering.keys()),
            [
                "analysis_id",
                "assignments",
                "stretch_issues",
                "position_shifts",
                "alternate_fingerings",
                "difficulty",
                "metrics",
            ],
        )
        assignments = self._require_list(fingering.get("assignments"), "assignments")
        first_assignment = self._require_dict(assignments[0], "assignments[0]")
        self.assertEqual(
            list(first_assignment.keys()),
            [
                "assignment_id",
                "timeline_event_id",
                "note_event_id",
                "tab_position_id",
                "finger",
                "position_fret",
                "confidence",
                "reason",
            ],
        )

    def test_analysis_endpoint_responses_are_deterministic(self) -> None:
        payload = self._analysis_payload()

        first_status, first_payload = self._request_json(
            "/api/analysis",
            method="POST",
            payload=payload,
        )
        second_status, second_payload = self._request_json(
            "/api/analysis",
            method="POST",
            payload=payload,
        )

        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)
        self.assertEqual(first_payload, second_payload)

    def test_analysis_endpoint_preserves_legacy_top_level_result_key(self) -> None:
        status, payload = self._request_json(
            "/api/fingering",
            method="POST",
            payload=self._analysis_payload(),
        )

        self.assertEqual(status, 200)
        data = self._require_dict(payload.get("data"), "data")
        self.assertIn("fingering", payload)
        self.assertEqual(payload["fingering"], data["fingering"])

    def test_analysis_endpoint_accepts_existing_note_payload(self) -> None:
        status, payload = self._request_json(
            "/api/analysis",
            method="POST",
            payload={"note_groups": [["E4", "F#4"], ["G4", "A4"]]},
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["success"])
        analysis = self._require_dict(payload.get("analysis"), "analysis")
        fingering = self._require_dict(analysis.get("fingering"), "analysis.fingering")
        assignments = self._require_list(fingering.get("assignments"), "assignments")
        self.assertEqual(len(assignments), 4)

    def test_analysis_endpoints_reject_unsupported_payload_consistently(self) -> None:
        for path in (
            "/api/analysis",
            "/api/fingering",
            "/api/difficulty",
            "/api/quality",
            "/api/alternates",
        ):
            with self.subTest(path=path):
                status, payload = self._request_json(path, method="POST", payload={})

                self.assertEqual(status, 400)
                self.assertEqual(list(payload.keys()), ["success", "error"])
                error = self._require_analysis_error(payload, code="unsupported_payload")
                self.assertIn("project_state", str(error["message"]))

    def test_analysis_endpoint_rejects_malformed_json_with_contract_error(self) -> None:
        status, payload = self._request_raw_json("/api/analysis", b'{"project_state":')

        self.assertEqual(status, 400)
        self._require_analysis_error(payload, code="malformed_json")

    def test_analysis_endpoint_rejects_non_object_json_with_contract_error(self) -> None:
        status, payload = self._request_json(
            "/api/analysis",
            method="POST",
            payload=["E4", "F#4"],
        )

        self.assertEqual(status, 400)
        self._require_analysis_error(payload, code="invalid_json_body")

    def test_analysis_endpoint_rejects_missing_required_project_fields(self) -> None:
        status, payload = self._request_json(
            "/api/analysis",
            method="POST",
            payload={
                "project_state": {
                    "generated_events": [],
                    "timeline": {"events": []},
                }
            },
        )

        self.assertEqual(status, 400)
        error = self._require_analysis_error(payload, code="missing_required_field")
        self.assertIn("tab_positions", str(error["message"]))

    def test_analysis_endpoint_rejects_invalid_timeline_payload(self) -> None:
        status, payload = self._request_json(
            "/api/analysis",
            method="POST",
            payload={
                "project_state": {
                    "generated_events": [],
                    "tab_positions": [],
                    "timeline": {"events": "not a list"},
                }
            },
        )

        self.assertEqual(status, 400)
        error = self._require_analysis_error(payload, code="invalid_timeline")
        self.assertIn("timeline.events", str(error["message"]))

    def test_analysis_endpoint_rejects_invalid_note_event_payload(self) -> None:
        payload = self._mutable_analysis_payload()
        project = self._require_dict(payload.get("project_state"), "project_state")
        events = self._require_list(project.get("generated_events"), "generated_events")
        first_event = self._require_dict(events[0], "generated_events[0]")
        first_event["start_s"] = "not numeric"

        status, response = self._request_json(
            "/api/analysis",
            method="POST",
            payload=payload,
        )

        self.assertEqual(status, 400)
        error = self._require_analysis_error(response, code="invalid_note_events")
        self.assertIn("start_s", str(error["message"]))

    def test_analysis_endpoint_rejects_invalid_project_state(self) -> None:
        status, payload = self._request_json(
            "/api/analysis",
            method="POST",
            payload={"project_state": {"generated_events": [], "tab_positions": []}},
        )

        self.assertEqual(status, 400)
        error = self._require_analysis_error(payload, code="invalid_timeline")
        self.assertIn("timeline", str(error["message"]))

    def test_transcribe_notes_mode_preserves_api_and_adds_timeline(self) -> None:
        status, payload = self._request_json(
            "/api/transcribe",
            method="POST",
            payload={"mode": "notes", "notes": ["E4", "F#4", "G4"]},
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["notes"], ["E4", "F#4", "G4"])
        self.assertEqual(payload["tab_tokens"], ["1:0", "1:2", "1:3"])
        timeline = payload.get("timeline")
        self.assertIsInstance(timeline, dict)
        if isinstance(timeline, dict):
            events = self._require_list(timeline.get("events"), "timeline.events")
            self.assertEqual(len(events), 3)
            first = events[0]
            self.assertIsInstance(first, dict)
            if isinstance(first, dict):
                self.assertEqual(first["timeline_event_id"], "timeline_event_000001")
                self.assertEqual(first["note"], "E4")
        playback_status = payload.get("playback_status")
        self.assertIsInstance(playback_status, dict)
        if isinstance(playback_status, dict):
            self.assertFalse(playback_status["is_playing"])
            self.assertEqual(playback_status["playback_speed"], 1.0)

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

    def test_unified_shell_contains_playback_synchronization_hooks(self) -> None:
        body = _build_html()

        self.assertIn("id=\"transportBar\"", body)
        self.assertIn("class PlaybackController", body)
        self.assertIn("class SynthAudioEngine", body)
        self.assertIn("AudioContext", body)
        self.assertIn("requestAnimationFrame", body)
        self.assertIn("activeeventchange", body)
        self.assertIn("projectState.playbackStatus", body)
        self.assertIn("projectState.analysisResults", body)
        self.assertIn("buildAnalysisProjectState", body)
        self.assertIn("requestAnalysisForPayload", body)
        self.assertIn('postJsonWithXhr("/api/analysis"', body)
        self.assertIn("data-timeline-event-id", body)
        self.assertIn("togglePlaybackHighlights", body)

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

    def test_transcribe_notes_mode_respects_explicit_tab_lines(self) -> None:
        status, payload = self._request_json(
            "/api/transcribe",
            method="POST",
            payload={
                "mode": "notes",
                "note_groups": [["E4"], ["F#4"], ["G4"], ["A4"], ["B4"], ["C5"]],
                "line_group_lengths": [1, 1, 1, 1, 1, 1],
                "tab_strategy": "single_string",
                "locked_string": 1,
                "group_gap": 5,
            },
        )

        self.assertEqual(status, 200)
        ascii_tab = self._require_str(payload["ascii_tab"], "ascii_tab")
        self.assertEqual(ascii_tab.count("e|"), 6)
        self.assertIn("\n\n", ascii_tab)

    def test_transcribe_notes_mode_accepts_tab_tokens_as_input(self) -> None:
        status, payload = self._request_json(
            "/api/transcribe",
            method="POST",
            payload={
                "mode": "notes",
                "note_groups": [["2:5", "2:8", "1:5"]],
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["note_groups"], [["E4", "G4", "A4"]])
        self.assertEqual(payload["tab_tokens"], ["2:5", "2:8", "1:5"])

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

    def test_transcribe_wav_mode_accepts_base64_payload(self) -> None:
        status, payload = self._request_json(
            "/api/transcribe",
            method="POST",
            payload={
                "mode": "wav",
                "wav_base64": self._build_test_wav_base64(),
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["mode"], "wav")
        notes = self._require_list(payload["notes"], "notes")
        tabs = self._require_list(payload["tab_tokens"], "tab_tokens")
        self.assertEqual(len(notes), len(tabs))

    def test_transcribe_wav_upload_endpoint_accepts_multipart_file(self) -> None:
        wav_bytes = self._build_test_wav_bytes()
        boundary = "----music-scale-test-boundary"
        body = (
            f"--{boundary}\r\n"
            "Content-Disposition: form-data; name=\"wav_file\"; filename=\"sample.wav\"\r\n"
            "Content-Type: audio/wav\r\n\r\n"
        ).encode("utf-8") + wav_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        request = Request(
            f"{self._base_url}/api/transcribe-wav-upload",
            data=body,
            method="POST",
            headers=headers,
        )

        try:
            with urlopen(request, timeout=4) as response:
                parsed = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 202)
        except HTTPError as exc:
            parsed = json.loads(exc.read().decode("utf-8"))
            self.fail(f"Expected 202 response, got {exc.code}: {parsed}")

        job_id = self._require_str(parsed.get("job_id"), "job_id")
        final_payload: dict[str, object] | None = None
        for _ in range(120):
            progress_request = Request(
                f"{self._base_url}/api/transcribe-progress?job_id={job_id}",
                method="GET",
            )
            with urlopen(progress_request, timeout=4) as progress_response:
                progress_payload = json.loads(progress_response.read().decode("utf-8"))
            if bool(progress_payload.get("done", False)):
                final_payload = cast(dict[str, object], progress_payload)
                break
            time.sleep(0.05)

        if final_payload is None:
            self.fail("Timed out waiting for wav transcription job completion.")

        if final_payload.get("error"):
            self.fail(f"WAV transcription job failed: {final_payload.get('error')}")

        result = cast(dict[str, object], final_payload.get("result"))
        self.assertIsInstance(result, dict)

        self.assertEqual(result["mode"], "wav")
        notes = self._require_list(result["notes"], "notes")
        tabs = self._require_list(result["tab_tokens"], "tab_tokens")
        self.assertEqual(len(notes), len(tabs))

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
