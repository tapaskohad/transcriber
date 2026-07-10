"""Browser UI server for live music scale detection."""

from __future__ import annotations

import base64
import binascii
import cgi
import json
import math
from pathlib import Path
import shutil
import tempfile
import threading
import time
import uuid
import wave
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .finder import ScaleFinder
from .guitar import STANDARD_TUNING, fret_to_note, fret_to_note_name, parse_tab_position
from .melody_transcriber import MelodyTranscriber, format_ascii_tab
from .models import PlaybackStatus
from .notes import CHROMATIC_NOTES, normalize_many
from .playback import TimelineBuilder
from .scales import COMMON_SCALE_PATTERNS
from .theory import TheoryEngine, dataclass_to_dict


_TEMPLATE_DIR = Path(__file__).resolve().parent


def _build_html() -> str:
    return (_TEMPLATE_DIR / "main_ui_template.html").read_text(encoding="utf-8")


def _build_transcriber_html() -> str:
    return (_TEMPLATE_DIR / "transcriber_ui_template.html").read_text(encoding="utf-8")


def _build_tab_sequencer_html() -> str:
    return (_TEMPLATE_DIR / "tab_sequencer_ui_template.html").read_text(encoding="utf-8")


def _chunk_by_lengths(values: list[str], lengths: list[int]) -> list[list[str]]:
    """Split a flat value list into chunks using the provided lengths."""
    if not lengths:
        return [values] if values else []

    chunks: list[list[str]] = []
    cursor = 0
    for length in lengths:
        safe_length = max(0, int(length))
        chunks.append(values[cursor : cursor + safe_length])
        cursor += safe_length

    if cursor < len(values):
        chunks.append(values[cursor:])
    return chunks


def _format_ascii_tab_by_lines(
    tabs: Any,
    *,
    group_lengths: list[int],
    line_group_lengths: list[int],
    group_gap: int,
) -> str:
    """Render tab groups across explicit sequencer lines."""
    if not group_lengths:
        return format_ascii_tab(tabs)

    if not line_group_lengths:
        return format_ascii_tab(
            tabs,
            group_lengths=group_lengths,
            group_gap=group_gap,
        )

    if sum(line_group_lengths) != len(group_lengths):
        raise ValueError("Field 'line_group_lengths' must align with note_groups.")

    blocks: list[str] = []
    group_cursor = 0
    tab_cursor = 0
    for line_group_count in line_group_lengths:
        line_group_lengths_slice = group_lengths[
            group_cursor : group_cursor + line_group_count
        ]
        line_tab_count = sum(line_group_lengths_slice)
        if line_tab_count > 0:
            blocks.append(
                format_ascii_tab(
                    tabs[tab_cursor : tab_cursor + line_tab_count],
                    group_lengths=line_group_lengths_slice,
                    group_gap=group_gap,
                )
            )
        group_cursor += line_group_count
        tab_cursor += line_tab_count

    return "\n\n".join(blocks)


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
    theory = TheoryEngine()
    timeline_builder = TimelineBuilder()
    config = _build_config()
    transcriber = MelodyTranscriber(max_fret=config["max_fret"])
    html = _build_html().encode("utf-8")
    transcriber_html = _build_transcriber_html().encode("utf-8")
    tab_sequencer_html = _build_tab_sequencer_html().encode("utf-8")
    max_body_bytes = 12 * 1024 * 1024
    max_upload_body_bytes = 256 * 1024 * 1024
    transcribe_jobs: dict[str, dict[str, Any]] = {}
    transcribe_jobs_lock = threading.Lock()
    transcribe_job_ttl_s = 30 * 60

    def log_message(self, format: str, *args: Any) -> None:
        # Silence noisy request logs.
        return

    def _request_path(self) -> str:
        return urlsplit(self.path).path

    def _request_query(self) -> dict[str, list[str]]:
        return parse_qs(urlsplit(self.path).query, keep_blank_values=True)

    @classmethod
    def _cleanup_old_jobs(cls) -> None:
        now = time.time()
        stale_ids: list[str] = []
        for job_id, job in cls.transcribe_jobs.items():
            updated_at = float(job.get("updated_at", now))
            if now - updated_at <= cls.transcribe_job_ttl_s:
                continue
            stale_ids.append(job_id)
        for job_id in stale_ids:
            cls.transcribe_jobs.pop(job_id, None)

    @classmethod
    def _update_job(cls, job_id: str, **fields: Any) -> None:
        with cls.transcribe_jobs_lock:
            job = cls.transcribe_jobs.get(job_id)
            if job is None:
                return
            job.update(fields)
            job["updated_at"] = time.time()

    @classmethod
    def _create_job(cls, *, filename: str = "") -> str:
        job_id = uuid.uuid4().hex
        created_at = time.time()
        with cls.transcribe_jobs_lock:
            cls._cleanup_old_jobs()
            cls.transcribe_jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "progress_percent": 0.0,
                "message": "Queued",
                "filename": filename,
                "done": False,
                "error": None,
                "result": None,
                "created_at": created_at,
                "updated_at": created_at,
            }
        return job_id

    @classmethod
    def _get_job(cls, job_id: str) -> dict[str, Any] | None:
        with cls.transcribe_jobs_lock:
            job = cls.transcribe_jobs.get(job_id)
            if job is None:
                return None
            return dict(job)

    def do_GET(self) -> None:
        path = self._request_path()

        if path in {"/", "/transcriber", "/transcriber/", "/tab-sequencer", "/tab-sequencer/"}:
            self._send_html(self.html)
            return

        if path == "/api/config":
            self._send_json(self.config)
            return

        if path == "/api/transcribe-progress":
            self._handle_transcribe_progress()
            return

        self._send_json({"error": "Not found."}, status=404)

    def do_POST(self) -> None:
        path = self._request_path()

        if path == "/api/transcribe-wav-upload":
            self._handle_transcribe_wav_upload()
            return

        body = self._read_json_body()
        if body is None:
            return

        if path == "/api/match":
            self._handle_match(body)
            return

        if path == "/api/transcribe":
            self._handle_transcribe(body)
            return

        if path == "/api/scale/analyze":
            self._handle_scale_analyze(body)
            return

        if path == "/api/chords/detect":
            self._handle_chords_detect(body)
            return

        if path == "/api/positions/suggest":
            self._handle_positions_suggest(body)
            return

        if path == "/api/playback/prepare":
            self._handle_playback_prepare(body)
            return

        self._send_json({"error": "Not found."}, status=404)

    def _parse_content_length(self) -> int | None:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            content_length = int(raw_length)
        except (TypeError, ValueError):
            self._send_json({"error": "Invalid Content-Length header."}, status=400)
            return None

        if content_length < 0:
            self._send_json({"error": "Content-Length cannot be negative."}, status=400)
            return None
        return content_length

    def _drain_request_body(self, content_length: int) -> None:
        remaining = max(0, content_length)
        while remaining > 0:
            chunk = self.rfile.read(min(64 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)

    def _read_json_body(self) -> dict[str, Any] | None:
        content_length = self._parse_content_length()
        if content_length is None:
            return None

        if content_length > self.max_body_bytes:
            # Drain oversized request bodies so the client can receive a clean 413 response.
            self._drain_request_body(content_length)
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

    def _read_note_list(self, body: dict[str, Any]) -> list[str] | None:
        raw_notes = body.get("notes", [])
        if not isinstance(raw_notes, list):
            self._send_json({"error": "Field 'notes' must be a list."}, status=400)
            return None

        try:
            return list(normalize_many(str(item) for item in raw_notes))
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return None

    def _handle_scale_analyze(self, body: dict[str, Any]) -> None:
        notes = self._read_note_list(body)
        if notes is None:
            return

        min_notes_raw = body.get("min_notes", 1)
        include_partial_raw = body.get("include_partial", True)
        try:
            min_notes = int(min_notes_raw)
        except (TypeError, ValueError):
            self._send_json({"error": "Field 'min_notes' must be an integer."}, status=400)
            return
        if min_notes < 1:
            self._send_json({"error": "Field 'min_notes' must be positive."}, status=400)
            return

        analyses = self.theory.analyze_scales(
            notes,
            min_notes=min_notes,
            include_partial=bool(include_partial_raw),
        )
        self._send_json(
            {
                "selected_notes": notes,
                "count": len(notes),
                "analyses": [dataclass_to_dict(analysis) for analysis in analyses],
            }
        )

    def _handle_chords_detect(self, body: dict[str, Any]) -> None:
        notes = self._read_note_list(body)
        if notes is None:
            return

        candidates = self.theory.detect_chords(notes)
        self._send_json(
            {
                "selected_notes": notes,
                "count": len(notes),
                "candidates": [dataclass_to_dict(candidate) for candidate in candidates],
            }
        )

    def _handle_positions_suggest(self, body: dict[str, Any]) -> None:
        notes = self._read_note_list(body)
        if notes is None:
            return

        try:
            min_fret = int(body.get("min_fret", 0))
            max_fret = int(body.get("max_fret", self.config["max_fret"]))
            window_size = int(body.get("window_size", 5))
            suggestions = self.theory.suggest_positions(
                notes,
                min_fret=min_fret,
                max_fret=max_fret,
                window_size=window_size,
            )
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        self._send_json(
            {
                "selected_notes": notes,
                "count": len(notes),
                "suggestions": [
                    dataclass_to_dict(suggestion) for suggestion in suggestions
                ],
            }
        )

    def _handle_playback_prepare(self, body: dict[str, Any]) -> None:
        try:
            note_groups, derived_preferred_tabs = self._playback_note_groups(body)
            if not note_groups:
                raise ValueError("No note tokens found. Use formats like E4 F#4 G4.")

            notes = [token for group in note_groups for token in group]
            preferred_tabs = self._playback_preferred_tabs(
                body,
                note_count=len(notes),
                fallback=derived_preferred_tabs,
            )
            result = self.transcriber.transcribe_notes(
                notes,
                preferred_tabs=preferred_tabs,
            )
            timeline = self.timeline_builder.build(
                result.events,
                tabs=result.tabs,
                group_lengths=[len(group) for group in note_groups],
                source="playback_prepare",
            )
        except (TypeError, ValueError) as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        self._send_json(
            {
                "timeline": dataclass_to_dict(timeline),
                "tempo": dataclass_to_dict(timeline.tempo),
                "time_signature": dataclass_to_dict(timeline.time_signature),
                "markers": [dataclass_to_dict(marker) for marker in timeline.markers],
                "playback_status": dataclass_to_dict(PlaybackStatus()),
                "synchronization_ids": [
                    {
                        "timeline_event_id": event.timeline_event_id,
                        "note_event_id": event.note_event_id,
                        "tab_position_id": event.tab_position_id,
                        "group_id": event.group_id,
                    }
                    for event in timeline.events
                ],
            }
        )

    def _playback_note_groups(
        self,
        body: dict[str, Any],
    ) -> tuple[list[list[str]], list[str | None]]:
        raw_note_groups = body.get("note_groups", None)
        note_groups: list[list[str]] = []
        preferred_tabs: list[str | None] = []

        def collect(raw_group: list[Any]) -> None:
            group_tokens: list[str] = []
            group_preferred: list[str | None] = []
            for raw_token in raw_group:
                token = str(raw_token).strip()
                if not token:
                    continue
                try:
                    string_id, fret = parse_tab_position(token)
                except ValueError:
                    extracted = self.transcriber.filter_note_tokens([token])
                    for extracted_token in extracted:
                        group_tokens.append(extracted_token)
                        group_preferred.append(None)
                else:
                    group_tokens.append(fret_to_note_name(string_id, fret))
                    group_preferred.append(f"{string_id}:{fret}")
            if group_tokens:
                note_groups.append(group_tokens)
                preferred_tabs.extend(group_preferred)

        if raw_note_groups is not None:
            if not isinstance(raw_note_groups, list):
                raise ValueError("Field 'note_groups' must be a list of note lists.")
            for raw_group in raw_note_groups:
                if not isinstance(raw_group, list):
                    raise ValueError("Field 'note_groups' must be a list of note lists.")
                collect(raw_group)
            return note_groups, preferred_tabs

        raw_notes = body.get("notes", [])
        if not isinstance(raw_notes, list):
            raise ValueError("Field 'notes' must be a list.")
        collect(raw_notes)
        return note_groups, preferred_tabs

    @staticmethod
    def _playback_preferred_tabs(
        body: dict[str, Any],
        *,
        note_count: int,
        fallback: list[str | None],
    ) -> list[str | None] | None:
        raw_preferred_tabs = body.get("preferred_tabs", None)
        if raw_preferred_tabs is None:
            return fallback if any(token is not None for token in fallback) else None
        if not isinstance(raw_preferred_tabs, list):
            raise ValueError("Field 'preferred_tabs' must be a list.")

        preferred_tabs: list[str | None] = []
        for raw_token in raw_preferred_tabs:
            if raw_token is None:
                preferred_tabs.append(None)
                continue
            token = str(raw_token).strip()
            preferred_tabs.append(token or None)
        if len(preferred_tabs) != note_count:
            raise ValueError("Field 'preferred_tabs' must align with the selected notes.")
        return preferred_tabs

    def _build_transcribe_payload(
        self,
        *,
        mode: str,
        result: Any,
        note_groups_payload: list[list[str]] | None = None,
        tab_groups_payload: list[list[str]] | None = None,
        ascii_tab_payload: str = "",
        timeline_group_lengths: list[int] | None = None,
    ) -> dict[str, Any]:
        pitch_classes: list[str] = []
        seen: set[str] = set()
        for event in result.events:
            if event.note not in seen:
                seen.add(event.note)
                pitch_classes.append(event.note)

        timeline = self.timeline_builder.build(
            result.events,
            tabs=result.tabs,
            group_lengths=timeline_group_lengths,
            source=f"transcribe_{mode}",
        )
        timeline_events = list(timeline.events)

        return {
            "mode": mode,
            "notes": list(result.notes),
            "tab_tokens": list(result.tab_tokens),
            "note_groups": note_groups_payload or [],
            "tab_groups": tab_groups_payload or [],
            "ascii_tab": ascii_tab_payload or result.ascii_tab,
            "pitch_classes": pitch_classes,
            "events": [
                {
                    "timeline_event_id": timeline_events[index].timeline_event_id
                    if index < len(timeline_events)
                    else "",
                    "note_event_id": event.event_id,
                    "note": event.note_name,
                    "frequency_hz": event.frequency_hz,
                    "start_s": event.start_s,
                    "end_s": event.end_s,
                }
                for index, event in enumerate(result.events)
            ],
            "tabs": [
                {
                    "string": tab.string_id,
                    "fret": tab.fret,
                    "note": f"{tab.note}{tab.octave}",
                }
                for tab in result.tabs
            ],
            "timeline": dataclass_to_dict(timeline),
            "tempo": dataclass_to_dict(timeline.tempo),
            "time_signature": dataclass_to_dict(timeline.time_signature),
            "markers": [dataclass_to_dict(marker) for marker in timeline.markers],
            "playback_status": dataclass_to_dict(PlaybackStatus()),
            "synchronization_ids": [
                {
                    "timeline_event_id": event.timeline_event_id,
                    "note_event_id": event.note_event_id,
                    "tab_position_id": event.tab_position_id,
                    "group_id": event.group_id,
                }
                for event in timeline.events
            ],
        }

    def _handle_transcribe_progress(self) -> None:
        query = self._request_query()
        raw_job_id = query.get("job_id", [""])[0]
        job_id = str(raw_job_id).strip()
        if not job_id:
            self._send_json({"error": "Query parameter 'job_id' is required."}, status=400)
            return

        job = self._get_job(job_id)
        if job is None:
            self._send_json({"error": f"Job not found: {job_id}"}, status=404)
            return

        payload = {
            "job_id": job_id,
            "status": job.get("status", "unknown"),
            "progress_percent": float(job.get("progress_percent", 0.0)),
            "message": str(job.get("message", "")),
            "done": bool(job.get("done", False)),
            "error": job.get("error", None),
        }
        if payload["done"] and job.get("result") is not None:
            payload["result"] = job["result"]
        self._send_json(payload)

    def _run_wav_transcribe_job(self, *, job_id: str, wav_path: Path) -> None:
        try:
            estimated_analysis_frames = 0
            try:
                with wave.open(str(wav_path), "rb") as wav_file:
                    frame_count = int(wav_file.getnframes())
                    sample_rate = max(1, int(wav_file.getframerate()))
                    frame_size = max(64, int(sample_rate * (40.0 / 1000.0)))
                    frame_hop = max(16, int(sample_rate * (10.0 / 1000.0)))
                    if frame_count >= frame_size:
                        estimated_analysis_frames = (
                            ((frame_count - frame_size) // frame_hop) + 1
                        )
            except (OSError, wave.Error):
                estimated_analysis_frames = 0

            self._update_job(
                job_id,
                status="running",
                progress_percent=1.0,
                message=(
                    f"Estimated {estimated_analysis_frames} analysis frames"
                    if estimated_analysis_frames > 0
                    else "Preparing WAV"
                ),
                done=False,
                error=None,
                result=None,
            )
            result = self.transcriber.transcribe_wav(
                wav_path,
                progress_callback=lambda progress, stage: self._update_job(
                    job_id,
                    status="running",
                    progress_percent=progress,
                    message=stage or "Transcribing",
                    done=False,
                ),
            )
            payload = self._build_transcribe_payload(
                mode="wav",
                result=result,
                ascii_tab_payload=result.ascii_tab,
            )
            self._update_job(
                job_id,
                status="completed",
                progress_percent=100.0,
                message="Completed",
                done=True,
                error=None,
                result=payload,
            )
        except (TypeError, ValueError, FileNotFoundError, wave.Error) as exc:
            self._update_job(
                job_id,
                status="failed",
                progress_percent=100.0,
                message="Failed",
                done=True,
                error=str(exc),
                result=None,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            self._update_job(
                job_id,
                status="failed",
                progress_percent=100.0,
                message="Failed",
                done=True,
                error=f"Unexpected error: {exc}",
                result=None,
            )
        finally:
            wav_path.unlink(missing_ok=True)

    def _handle_transcribe_wav_upload(self) -> None:
        content_length = self._parse_content_length()
        if content_length is None:
            return
        if content_length <= 0:
            self._send_json({"error": "Upload body is empty."}, status=400)
            return
        if content_length > self.max_upload_body_bytes:
            self._drain_request_body(content_length)
            self._send_json(
                {
                    "error": (
                        "Upload body too large "
                        f"(max {self.max_upload_body_bytes} bytes)."
                    )
                },
                status=413,
            )
            return

        content_type = str(self.headers.get("Content-Type", "")).lower()
        if "multipart/form-data" not in content_type:
            self._send_json(
                {"error": "Use multipart/form-data with field 'wav_file'."},
                status=400,
            )
            return

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": str(content_length),
            },
            keep_blank_values=True,
        )

        if "wav_file" not in form:
            self._send_json({"error": "Field 'wav_file' is required."}, status=400)
            return

        file_field = form["wav_file"]
        if isinstance(file_field, list):
            file_field = file_field[0] if file_field else None
        if file_field is None or getattr(file_field, "file", None) is None:
            self._send_json({"error": "Field 'wav_file' is required."}, status=400)
            return

        filename = str(getattr(file_field, "filename", "") or "").strip()
        if filename and not filename.lower().endswith(".wav"):
            self._send_json({"error": "Uploaded file must be a .wav file."}, status=400)
            return

        with tempfile.NamedTemporaryFile(mode="wb", suffix=".wav", delete=False) as temp_file:
            temp_wav_path = Path(temp_file.name)
            uploaded_stream = file_field.file
            try:
                uploaded_stream.seek(0)
            except (OSError, AttributeError):
                pass
            shutil.copyfileobj(uploaded_stream, temp_file, length=1024 * 1024)

        job_id = self._create_job(filename=filename)
        worker = threading.Thread(
            target=self._run_wav_transcribe_job,
            kwargs={"job_id": job_id, "wav_path": temp_wav_path},
            daemon=True,
        )
        worker.start()
        self._send_json(
            {
                "job_id": job_id,
                "status": "queued",
                "message": "Upload accepted. Transcription started.",
                "monitor_url": f"/api/transcribe-progress?job_id={job_id}",
            },
            status=202,
        )

    def _handle_transcribe(self, body: dict[str, Any]) -> None:
        mode = str(body.get("mode", "notes")).strip().lower()
        tab_strategy = str(body.get("tab_strategy", "balanced")).strip().lower()
        locked_string_raw = body.get("locked_string", None)
        group_gap_raw = body.get("group_gap", 7)
        raw_preferred_tabs = body.get("preferred_tabs", None)
        raw_line_group_lengths = body.get("line_group_lengths", None)
        note_groups_payload: list[list[str]] = []
        tab_groups_payload: list[list[str]] = []
        ascii_tab_payload = ""
        timeline_group_lengths: list[int] | None = None

        try:
            locked_string: int | None = None
            if locked_string_raw is not None and str(locked_string_raw).strip() != "":
                locked_string = int(locked_string_raw)
            group_gap = int(group_gap_raw)
            if group_gap < 0:
                raise ValueError("Field 'group_gap' cannot be negative.")
            if tab_strategy == "as_selected":
                tab_strategy = "balanced"

            if mode == "notes":
                raw_note_groups = body.get("note_groups", None)
                note_groups: list[list[str]] = []
                derived_preferred_tabs: list[str | None] = []

                def _collect_note_group(raw_group: list[Any]) -> None:
                    group_tokens: list[str] = []
                    group_preferred_tabs: list[str | None] = []

                    for raw_token in raw_group:
                        token = str(raw_token).strip()
                        if not token:
                            continue

                        try:
                            string_id, fret = parse_tab_position(token)
                        except ValueError:
                            extracted = self.transcriber.filter_note_tokens([token])
                            for extracted_token in extracted:
                                group_tokens.append(extracted_token)
                                group_preferred_tabs.append(None)
                        else:
                            group_tokens.append(fret_to_note_name(string_id, fret))
                            group_preferred_tabs.append(f"{string_id}:{fret}")

                    if group_tokens:
                        note_groups.append(group_tokens)
                        derived_preferred_tabs.extend(group_preferred_tabs)

                if raw_note_groups is not None:
                    if not isinstance(raw_note_groups, list):
                        raise ValueError("Field 'note_groups' must be a list of note lists.")
                    for raw_group in raw_note_groups:
                        if not isinstance(raw_group, list):
                            raise ValueError("Field 'note_groups' must be a list of note lists.")
                        _collect_note_group(raw_group)
                else:
                    raw_notes = body.get("notes", [])
                    if not isinstance(raw_notes, list):
                        raise ValueError("Field 'notes' must be a list.")
                    _collect_note_group(raw_notes)

                notes = [token for group in note_groups for token in group]
                if not notes:
                    raise ValueError(
                        "No note tokens found. Use formats like E4 F#4 G4."
                    )

                preferred_tabs: list[str | None] | None = None
                if raw_preferred_tabs is not None:
                    if not isinstance(raw_preferred_tabs, list):
                        raise ValueError("Field 'preferred_tabs' must be a list.")
                    preferred_tabs = []
                    for raw_token in raw_preferred_tabs:
                        if raw_token is None:
                            preferred_tabs.append(None)
                        else:
                            token = str(raw_token).strip()
                            preferred_tabs.append(token or None)
                    if len(preferred_tabs) != len(notes):
                        raise ValueError(
                            "Field 'preferred_tabs' must align with the selected notes."
                        )
                elif any(token is not None for token in derived_preferred_tabs):
                    preferred_tabs = derived_preferred_tabs

                result = self.transcriber.transcribe_notes(
                    notes,
                    tab_strategy=tab_strategy,
                    locked_string=locked_string,
                    preferred_tabs=preferred_tabs,
                )
                group_lengths = [len(group) for group in note_groups]
                timeline_group_lengths = group_lengths
                line_group_lengths: list[int] = []
                if raw_line_group_lengths is not None:
                    if not isinstance(raw_line_group_lengths, list):
                        raise ValueError("Field 'line_group_lengths' must be a list.")
                    for raw_count in raw_line_group_lengths:
                        count = int(raw_count)
                        if count <= 0:
                            raise ValueError(
                                "Field 'line_group_lengths' must contain positive integers."
                            )
                        line_group_lengths.append(count)

                note_groups_payload = _chunk_by_lengths(list(result.notes), group_lengths)
                tab_groups_payload = _chunk_by_lengths(list(result.tab_tokens), group_lengths)
                ascii_tab_payload = _format_ascii_tab_by_lines(
                    result.tabs,
                    group_lengths=group_lengths,
                    line_group_lengths=line_group_lengths,
                    group_gap=group_gap,
                )
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
                ascii_tab_payload = result.ascii_tab
            elif mode == "wav":
                wav_base64 = str(body.get("wav_base64", "")).strip()
                wav_path = str(body.get("wav_path", "")).strip()
                if wav_base64:
                    try:
                        wav_bytes = base64.b64decode(wav_base64, validate=True)
                    except (binascii.Error, ValueError) as exc:
                        raise ValueError("Field 'wav_base64' must be valid base64.") from exc
                    if not wav_bytes:
                        raise ValueError("Field 'wav_base64' is empty.")

                    with tempfile.NamedTemporaryFile(
                        mode="wb",
                        suffix=".wav",
                        delete=False,
                    ) as temp_file:
                        temp_file.write(wav_bytes)
                        temp_wav_path = Path(temp_file.name)
                    try:
                        result = self.transcriber.transcribe_wav(temp_wav_path)
                    finally:
                        temp_wav_path.unlink(missing_ok=True)
                elif wav_path:
                    result = self.transcriber.transcribe_wav(wav_path)
                else:
                    raise ValueError(
                        "Provide either 'wav_base64' or 'wav_path' for wav mode."
                    )
                ascii_tab_payload = result.ascii_tab
            else:
                raise ValueError("Unsupported mode. Use notes, frequencies, or wav.")
        except (TypeError, ValueError, FileNotFoundError, wave.Error) as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        payload = self._build_transcribe_payload(
            mode=mode,
            result=result,
            note_groups_payload=note_groups_payload,
            tab_groups_payload=tab_groups_payload,
            ascii_tab_payload=ascii_tab_payload,
            timeline_group_lengths=timeline_group_lengths,
        )
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








































































