"""Browser UI server for live music scale detection."""

from __future__ import annotations

import json
import math
from pathlib import Path
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from .finder import ScaleFinder
from .guitar import STANDARD_TUNING, fret_to_note, fret_to_note_name
from .melody_transcriber import MelodyTranscriber
from .notes import CHROMATIC_NOTES, normalize_many
from .scales import COMMON_SCALE_PATTERNS


_TEMPLATE_DIR = Path(__file__).resolve().parent


def _build_html() -> str:
    return (_TEMPLATE_DIR / "main_ui_template.html").read_text(encoding="utf-8")


def _build_transcriber_html() -> str:
    return (_TEMPLATE_DIR / "transcriber_ui_template.html").read_text(encoding="utf-8")

def _build_config(max_fret: int = 12, min_notes: int = 3) -> dict[str, Any]:
    strings = sorted(STANDARD_TUNING.keys())
    rows = []

    for string_id in strings:
        open_note = STANDARD_TUNING[string_id]
        open_note_name = fret_to_note_name(string_id, 0)
        fret_data = []
        for fret in range(0, max_fret + 1):
            fret_data.append(
                {
                    "fret": fret,
                    "note": fret_to_note(string_id, fret),
                    "note_name": fret_to_note_name(string_id, fret),
                }
            )
        rows.append(
            {
                "string": string_id,
                "open_note": open_note,
                "open_note_name": open_note_name,
                "frets": fret_data,
            }
        )

    patterns = [
        {
            "id": f"pattern_{index}",
            "name": pattern.name,
            "intervals": list(pattern.intervals),
        }
        for index, pattern in enumerate(COMMON_SCALE_PATTERNS)
    ]

    return {
        "chromatic_notes": list(CHROMATIC_NOTES),
        "max_fret": max_fret,
        "min_notes": min_notes,
        "strings": rows,
        "scale_patterns": patterns,
    }


class _ScaleRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the browser UI and API."""

    finder = ScaleFinder()
    config = _build_config()
    transcriber = MelodyTranscriber(max_fret=config["max_fret"])
    html = _build_html().encode("utf-8")
    transcriber_html = _build_transcriber_html().encode("utf-8")
    max_body_bytes = 512 * 1024

    def log_message(self, format: str, *args: Any) -> None:
        # Silence noisy request logs.
        return

    def _request_path(self) -> str:
        return urlsplit(self.path).path

    def do_GET(self) -> None:
        path = self._request_path()

        if path == "/":
            self._send_html(self.html)
            return

        if path in {"/transcriber", "/transcriber/"}:
            self._send_html(self.transcriber_html)
            return

        if path == "/api/config":
            self._send_json(self.config)
            return

        self._send_json({"error": "Not found."}, status=404)

    def do_POST(self) -> None:
        path = self._request_path()
        body = self._read_json_body()
        if body is None:
            return

        if path == "/api/match":
            self._handle_match(body)
            return

        if path == "/api/transcribe":
            self._handle_transcribe(body)
            return

        self._send_json({"error": "Not found."}, status=404)

    def _read_json_body(self) -> dict[str, Any] | None:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            content_length = int(raw_length)
        except (TypeError, ValueError):
            self._send_json({"error": "Invalid Content-Length header."}, status=400)
            return None

        if content_length < 0:
            self._send_json({"error": "Content-Length cannot be negative."}, status=400)
            return None

        if content_length > self.max_body_bytes:
            self._send_json(
                {"error": f"Request body too large (max {self.max_body_bytes} bytes)."},
                status=413,
            )
            return None

        raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            decoded = raw_body.decode("utf-8")
            parsed = json.loads(decoded)
        except UnicodeDecodeError:
            self._send_json({"error": "Body must be UTF-8 encoded JSON."}, status=400)
            return None
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON."}, status=400)
            return None

        if not isinstance(parsed, dict):
            self._send_json({"error": "JSON body must be an object."}, status=400)
            return None

        return parsed

    def _handle_match(self, body: dict[str, Any]) -> None:
        raw_notes = body.get("notes", [])
        if not isinstance(raw_notes, list):
            self._send_json({"error": "Field 'notes' must be a list."}, status=400)
            return

        try:
            notes = list(normalize_many(str(item) for item in raw_notes))
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        matches = self.finder.find_matches(notes, min_notes=self.config["min_notes"])

        payload = {
            "selected_notes": notes,
            "count": len(notes),
            "matches": [
                {
                    "label": match.label,
                    "root": match.root,
                    "pattern_name": match.pattern_name,
                    "scale_notes": list(match.scale_notes),
                }
                for match in matches
            ],
        }
        self._send_json(payload)

    def _handle_transcribe(self, body: dict[str, Any]) -> None:
        mode = str(body.get("mode", "notes")).strip().lower()

        try:
            if mode == "notes":
                raw_notes = body.get("notes", [])
                if not isinstance(raw_notes, list):
                    raise ValueError("Field 'notes' must be a list.")

                notes = self.transcriber.filter_note_tokens(raw_notes)
                if not notes:
                    raise ValueError(
                        "No note tokens found. Use formats like E4 F#4 G4."
                    )

                result = self.transcriber.transcribe_notes(notes)
            elif mode == "frequencies":
                raw_frequencies = body.get("frequencies", [])
                if not isinstance(raw_frequencies, list):
                    raise ValueError("Field 'frequencies' must be a list.")

                frequencies: list[float] = []
                for item in raw_frequencies:
                    value = float(item)
                    if not math.isfinite(value) or value <= 0:
                        raise ValueError(f"Invalid frequency: {item}")
                    frequencies.append(value)

                if not frequencies:
                    raise ValueError("Provide at least one positive frequency.")

                frame_step_s = float(body.get("frame_step_s", 0.05))
                result = self.transcriber.transcribe_frequencies(
                    frequencies,
                    frame_step_s=frame_step_s,
                )
            elif mode == "wav":
                wav_path = str(body.get("wav_path", "")).strip()
                if not wav_path:
                    raise ValueError("Field 'wav_path' is required for wav mode.")
                result = self.transcriber.transcribe_wav(wav_path)
            else:
                raise ValueError("Unsupported mode. Use notes, frequencies, or wav.")
        except (TypeError, ValueError, FileNotFoundError) as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        pitch_classes: list[str] = []
        seen: set[str] = set()
        for event in result.events:
            if event.note not in seen:
                seen.add(event.note)
                pitch_classes.append(event.note)

        payload = {
            "mode": mode,
            "notes": list(result.notes),
            "tab_tokens": list(result.tab_tokens),
            "ascii_tab": result.ascii_tab,
            "pitch_classes": pitch_classes,
            "events": [
                {
                    "note": event.note_name,
                    "frequency_hz": event.frequency_hz,
                    "start_s": event.start_s,
                    "end_s": event.end_s,
                }
                for event in result.events
            ],
            "tabs": [
                {
                    "string": tab.string_id,
                    "fret": tab.fret,
                    "note": f"{tab.note}{tab.octave}",
                }
                for tab in result.tabs
            ],
        }
        self._send_json(payload)

    def _send_html(self, data: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ScaleRequestHandler)
    host, port = str(server.server_address[0]), server.server_address[1]
    url = f"http://{host}:{port}/"

    print(f"Opening Music Scale Finder at {url}")
    print("Close this terminal window or press Ctrl+C to stop the local server.")

    threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()








































































