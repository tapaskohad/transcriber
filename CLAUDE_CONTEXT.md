# 1. Project Overview

This project is a local music scale and guitar tab assistant. It lets a user select pitch classes from a note palette or guitar fretboard, finds matching scales, transcribes melodies into note events, maps notes to playable guitar tab positions, and renders ASCII guitar tabs.

Main features:
- Scale Finder: select notes or fretboard cells, then see matching scales once at least 3 unique pitch classes are selected.
- Melody Transcriber: convert note tokens, frequency values, WAV paths, or uploaded WAV files into detected notes, tab tokens, pitch classes, event timing, and ASCII tab.
- Tab Sequencer: click fretboard cells to build an exact note/tab sequence, preserve phrase and line breaks, choose tab strategy, optionally lock a string, and export generated tabs as TXT.
- Theme and route persistence: the unified browser shell supports dark/light theme, mode-specific URLs, and localStorage-backed state.
- Legacy/alternate desktop UI: a Tkinter scale finder exists, but the default launcher opens the browser UI.

Technologies used:
- Python 3.10+ standard library server: `http.server.ThreadingHTTPServer`, no frontend build step.
- Python domain modules: dataclasses, music theory helpers, guitar mapping, WAV PCM decoding, pitch detection.
- Frontend: static HTML templates with inline CSS and vanilla JavaScript.
- Browser APIs: `fetch`, `XMLHttpRequest`, `localStorage`, Clipboard API, File/Blob APIs, `FormData`, drag and drop, optional File System Access API for TXT saving.
- Tests: `unittest`; `pytest`, `ruff`, and `mypy` are optional dev dependencies.

Overall architecture:
- `run.py` and `python -m music_scale` call `music_scale.launcher.main()`, which starts `music_scale.web_ui.main()`.
- `web_ui.py` creates a local threaded HTTP server and serves a single active HTML shell from `main_ui_template.html`.
- The active frontend is a single-page-style app with three modes: Scale Finder, Transcriber, and Tab Sequencer.
- Frontend JavaScript calls JSON endpoints in `web_ui.py`.
- Backend endpoint handlers delegate to pure Python music modules: `notes.py`, `scales.py`, `finder.py`, `guitar.py`, and `melody_transcriber.py`.
- WAV uploads use an async job registry stored on `_ScaleRequestHandler` class variables and polled from the browser.

# 2. Folder Structure

Root files:
- `README.md`: quick start, test command, high-level feature summary, and API notes.
- `pyproject.toml`: package metadata, Python requirement, optional dev dependencies, script entry point, and tool config.
- `run.py`: thin launcher that imports and calls `music_scale.launcher.main()`.
- `.github/`: CI configuration is expected here; tests run on push/PR according to README.
- `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `music_scale_finder.egg-info/`: generated local/dev artifacts, not source.

Package `music_scale/`:
- `__init__.py`: public exports for `ScaleFinder`, `ScaleMatch`, `MelodyTranscriber`, tab result dataclasses, and `MelodySession`.
- `__main__.py`: enables `python -m music_scale`.
- `launcher.py`: chooses the browser UI as the default app experience.
- `web_ui.py`: local HTTP server, routes, JSON request validation, template loading, API handlers, WAV upload job management.
- `main_ui_template.html`: active unified browser application for Scale Finder, Transcriber, and Tab Sequencer.
- `transcriber_ui_template.html`: standalone transcriber shell; currently loaded in tests but not served by active routes.
- `tab_sequencer_ui_template.html`: standalone tab sequencer shell; currently loaded in tests but not served by active routes.
- `notes.py`: chromatic note constants, alias normalization, transposition, and note indexing.
- `scales.py`: scale interval pattern dataclass and common scale pattern library.
- `finder.py`: scale matching engine.
- `guitar.py`: standard tuning helpers, tab token parsing, and fret-to-note conversion.
- `melody_transcriber.py`: melody event models, note/frequency/WAV transcription, tab-position mapping, and ASCII tab rendering.
- `session.py`: batch-aware interactive note session model used by tests and older flows.
- `gui.py`: Tkinter desktop scale finder, separate from the browser UI.

Tests `tests/`:
- `test_web_api.py`: integration-style HTTP API tests, route tests, transcriber payload tests, WAV upload tests, and request validation tests.
- `test_melody_transcriber.py`: transcriber unit tests for notes, frequencies, octave notation, strategies, and preferred tabs.
- `test_music_scale.py`: note normalization, tab parsing, fret note names, and basic matching tests.
- `test_finder_engine.py`: scale finder behavior and sorting contract.
- `test_session_workflow.py`: `MelodySession` tab input, undo, and clear behavior.

# 3. Screen Breakdown

Active browser shell:
- Rendered by `music_scale/main_ui_template.html`.
- Served by `music_scale/web_ui.py` for `/`, `/transcriber`, `/transcriber/`, `/tab-sequencer`, and `/tab-sequencer/`.
- Purpose: one unified app with route-driven modes, shared topbar, shared visual language, and shared client-side state.
- Backend dependencies: `GET /api/config`, `POST /api/match`, `POST /api/transcribe`, `POST /api/transcribe-wav-upload`, `GET /api/transcribe-progress`.

Scale Finder screen:
- Rendered by `main_ui_template.html`, section `#mode-scale`.
- Purpose: select pitch classes via note chips or fretboard cells and display matching scale candidates.
- Backend dependencies: `web_ui._build_config()` for chromatic notes/fretboard config; `web_ui._handle_match()`; `ScaleFinder.find_matches()`; `notes.normalize_many()`; `guitar.fret_to_note()`.

Transcriber screen:
- Rendered by `main_ui_template.html`, section `#mode-transcriber`.
- Purpose: accept note tokens, frequencies, WAV path, or browser-selected WAV file, then render notes, tabs, pitch classes, ASCII tab, and event timing.
- Backend dependencies: `web_ui._handle_transcribe()`, `web_ui._handle_transcribe_wav_upload()`, `web_ui._handle_transcribe_progress()`, `MelodyTranscriber.transcribe_notes()`, `MelodyTranscriber.transcribe_frequencies()`, `MelodyTranscriber.transcribe_wav()`, `format_ascii_tab()`.

Tab Sequencer screen:
- Rendered by `main_ui_template.html`, section `#mode-sequencer`.
- Purpose: build ordered note groups by clicking fretboard cells or editing tokens, preserve exact string/fret preferences, split groups/lines, generate tabs, and save TXT.
- Backend dependencies: `GET /api/config`; `POST /api/transcribe` in notes mode; `web_ui._format_ascii_tab_by_lines()` for explicit line rendering; `MelodyTranscriber.map_events_to_tabs()`.

Standalone Transcriber page:
- File: `music_scale/transcriber_ui_template.html`.
- Purpose: older or alternate isolated transcriber UI with its own hero, meters, WAV controls, output renderer, and TXT export.
- Backend dependencies: same transcriber APIs as the unified transcriber mode.
- Current routing note: `_ScaleRequestHandler` initializes `transcriber_html`, and tests load it, but active `do_GET()` returns the unified shell for `/transcriber`.

Standalone Tab Sequencer page:
- File: `music_scale/tab_sequencer_ui_template.html`.
- Purpose: older or alternate isolated sequencer UI with its own fretboard, sequence editor, Next Line state, and export button.
- Backend dependencies: same config/transcribe APIs as the unified sequencer mode.
- Current routing note: `_ScaleRequestHandler` initializes `tab_sequencer_html`, and tests load it, but active `do_GET()` returns the unified shell for `/tab-sequencer`.

Desktop Tkinter screen:
- File: `music_scale/gui.py`.
- Purpose: desktop-only scale finder with note buttons, fretboard buttons, selected notes, and matching scales.
- Backend dependencies: `ScaleFinder`, `CHROMATIC_NOTES`, `note_index`, `STANDARD_TUNING`, and `fret_to_note`.
- Current launcher note: not the default app path.

# 4. UI Component Hierarchy

Active `main_ui_template.html` hierarchy:

```text
App Shell
 ├── Topbar
 │   ├── Brand
 │   ├── Mode Switch
 │   │   ├── Scale Finder button
 │   │   ├── Transcriber button
 │   │   └── Tab Sequencer button
 │   └── Theme Toggle
 ├── Scale Finder Mode
 │   ├── Note Palette Panel
 │   │   ├── Note Grid
 │   │   ├── Clear Button
 │   │   └── Selected Notes Line
 │   ├── Guitar Input Panel
 │   │   └── Fretboard Table
 │   └── Matching Scales Panel
 │       ├── Status
 │       └── Results List
 ├── Transcriber Mode
 │   ├── Melody Transcriber Panel
 │   │   ├── Input Type Select
 │   │   ├── Melody Textarea
 │   │   ├── WAV Tools
 │   │   │   ├── Choose WAV Button
 │   │   │   ├── Clear WAV Button
 │   │   │   ├── File Line
 │   │   │   └── Drop Zone
 │   │   ├── Octave/Step Controls
 │   │   ├── Transcribe Button
 │   │   ├── Status
 │   │   ├── Summary
 │   │   └── ASCII Tab Output
 │   └── Detected Events Panel
 │       └── Event Rows
 └── Tab Sequencer Mode
     ├── Selected Sequence Panel
     │   ├── Status
     │   ├── Sequence Editor
     │   ├── Update/Copy/Paste/Undo/Clear
     │   ├── Space Button
     │   ├── Next Line Toggle Button
     │   ├── Tab Strategy Select
     │   └── String Lock Select
     ├── Sequencer Fretboard Panel
     │   └── Fretboard Table
     └── Generated Tabs Panel
         ├── Save TXT Button
         ├── Tab Tokens Line
         └── ASCII Tab Output
```

Standalone template hierarchies are similar, but each owns its own hero/header and excludes the shared multi-mode topbar.

# 5. Data Flow

Scale Finder note click:
```text
User clicks note chip
-> toggleScaleNote(note)
-> scaleState.selectedNotes updated
-> persistScaleNotes()
-> refreshScaleUI()
-> refreshScaleMatches()
-> POST /api/match { notes }
-> ScaleFinder.find_matches()
-> response matches
-> #scaleResults and #scaleStatus update
```

Scale Finder fretboard click:
```text
User clicks fretboard cell
-> renderScaleFretboard handler receives fretData.note
-> toggleScaleNote(note)
-> same flow as note chip
-> matching scales update
```

Transcriber note-token flow:
```text
User enters notes and clicks Transcribe
-> runTranscription()
-> tokenizeInputByLine()
-> body = { mode: "notes", note_groups }
-> postJsonWithXhr("/api/transcribe", body)
-> _handle_transcribe()
-> MelodyTranscriber.filter_note_tokens()
-> MelodyTranscriber.transcribe_notes()
-> MelodyTranscriber.map_events_to_tabs()
-> _build_transcribe_payload()
-> frontend updates summary, ASCII tab, events, status
```

Transcriber frequency flow:
```text
User enters frequencies and clicks Transcribe
-> tokenizeInput()
-> body = { mode: "frequencies", frequencies, frame_step_s }
-> /api/transcribe
-> MelodyTranscriber.transcribe_frequencies()
-> pitch smoothing and event creation
-> map_events_to_tabs()
-> render results
```

Transcriber WAV path flow:
```text
User enters WAV path and clicks Transcribe
-> body = { mode: "wav", wav_path }
-> /api/transcribe
-> MelodyTranscriber.transcribe_wav()
-> _read_wav_mono(), _extract_pitch_track(), _events_from_pitch_track()
-> map_events_to_tabs()
-> render results
```

Browser WAV upload flow:
```text
User chooses/drops WAV file
-> setSelectedWavFile()
-> runTranscription()
-> postWavUploadWithXhr("/api/transcribe-wav-upload", FormData)
-> _handle_transcribe_wav_upload()
-> _create_job()
-> background thread _run_wav_transcribe_job()
-> frontend polls /api/transcribe-progress?job_id=...
-> completed result returned
-> render results
```

Tab Sequencer fret click:
```text
User clicks sequencer fret cell
-> appendSequencerFromFret(note_name, string, fret)
-> editor token added as E4@1:0 style
-> refreshSequencerTabs()
-> parseSequencerLayout()
-> body = { mode: "notes", note_groups, preferred_tabs, line_group_lengths, tab_strategy, locked_string, group_gap }
-> /api/transcribe
-> preferred tabs and line groups mapped
-> ASCII tab rendered with explicit line blocks
-> tab tokens and ASCII output update
```

Tab Sequencer Next Line:
```text
User clicks Next Line
-> sequencerInsertNextLine()
-> editor gains or removes trailing "||\n"
-> updateSequencerNextLineState()
-> button label and glow switch between Off and On
-> next fret click starts a new explicit tab line
```

# 6. Shared State

Backend class-level state in `_ScaleRequestHandler`:
- `finder`: singleton `ScaleFinder` used by `/api/match`.
- `config`: singleton config dictionary containing chromatic notes, max fret, min notes, strings/frets, and scale patterns.
- `transcriber`: singleton `MelodyTranscriber` using `config["max_fret"]`.
- `html`, `transcriber_html`, `tab_sequencer_html`: template bytes loaded at import/class initialization.
- `max_body_bytes`: JSON body size guard.
- `max_upload_body_bytes`: multipart WAV upload size guard.
- `transcribe_jobs`: in-memory job registry for uploaded WAV processing.
- `transcribe_jobs_lock`: thread lock around job registry updates.
- `transcribe_job_ttl_s`: cleanup horizon for old transcription jobs.

Frontend global state in `main_ui_template.html`:
- `config`: API config loaded from `/api/config`.
- `activeMode`: current mode, synchronized with path and localStorage.
- `scaleState`: selected scale notes, note-to-button map, request token.
- `scaleEls`, `transEls`, `seqEls`: cached DOM references for each mode.
- `selectedWavFile`: browser `File` selected/dropped for WAV upload.
- `lastSequencerExportText`: current generated sequencer TXT export.
- `KEYS`: localStorage keys for theme, active mode, selected notes, transcriber inputs, sequencer inputs.
- `requestToken` fields: scale and sequencer use monotonic tokens to ignore stale async responses.

Frontend global state in standalone templates:
- `transcriber_ui_template.html`: `pendingNoteGroupLengths`, `lastTabsExportText`, `selectedWavFile`, theme/sound/selected count localStorage keys.
- `tab_sequencer_ui_template.html`: `config`, `requestToken`, `lastExportText`, cached DOM refs.

Domain model shared state:
- `ScaleFinder` precomputes `_library` of scale candidates.
- `MelodySession` stores `_notes`, `_note_set`, and `_history`; it is not used by the active browser shell.
- `MelodyTranscriber` stores frequency/fret bounds and playable MIDI limits.

# 7. Important Classes and Functions

Frontend functions in `main_ui_template.html`:
- `setMode(mode, fromHistory)`: switches active UI mode and updates browser history.
- `refreshScaleMatches()`: sends selected notes to `/api/match` and renders scale results.
- `renderFretboard(headEl, bodyEl, onPress)`: builds a reusable fretboard table from `config.strings`.
- `runTranscription()`: validates transcriber input, chooses upload vs JSON mode, calls backend transcription APIs, and renders results.
- `postJsonWithXhr()`: JSON POST helper with progress-friendly error handling.
- `postWavUploadWithXhr()`: multipart upload helper with upload progress.
- `waitForWavJobResult()`: polls async WAV transcription jobs.
- `shiftTranscriberOctave()` and `shiftTranscriberStep()`: mutate note-token text input.
- `parseSequencerLayout()`: parses sequencer editor text into note groups and line-group lengths.
- `appendSequencerFromFret()`: appends exact note/tab tokens from fretboard clicks.
- `updateSequencerNextLineState()`: keeps the Next Line toggle label, aria state, and glow in sync.
- `refreshSequencerTabs()`: submits sequencer groups/preferences to `/api/transcribe` and renders generated tabs.
- `updateSequencerFretboardGlow()`: highlights fretboard notes present in the sequencer.

Backend functions/classes:
- `_ScaleRequestHandler`: HTTP request handler for all pages and API endpoints.
- `_build_config()`: creates frontend config for note palette, fretboards, and scale patterns.
- `_handle_match()`: validates selected notes and returns scale matches.
- `_handle_transcribe()`: validates transcriber payloads and dispatches notes, frequencies, and WAV modes.
- `_handle_transcribe_wav_upload()`: accepts multipart WAV uploads and starts background transcription.
- `_handle_transcribe_progress()`: returns status and result for async WAV jobs.
- `_format_ascii_tab_by_lines()`: renders explicit sequencer lines as separated ASCII tab blocks.
- `_build_transcribe_payload()`: normalizes transcription results into frontend JSON shape.

Domain functions/classes:
- `ScaleFinder.find_matches()`: returns all scales containing the selected pitch classes.
- `normalize_note()` and `normalize_many()`: canonicalize notes and preserve unique pitch class order.
- `fret_to_note()` and `fret_to_note_name()`: convert guitar string/fret positions to pitch class or octave-aware names.
- `parse_tab_position()`: parses `string:fret` tab tokens.
- `MelodyTranscriber.transcribe_notes()`: turns note tokens into timed events and tabs.
- `MelodyTranscriber.transcribe_frequencies()`: turns frequency frames into events and tabs.
- `MelodyTranscriber.transcribe_wav()`: reads WAV audio, extracts pitch, detects notes, and maps tabs.
- `MelodyTranscriber.map_events_to_tabs()`: dynamic-programming path finder for playable guitar positions.
- `format_ascii_tab()`: renders tab positions as six-line ASCII guitar tab.
- `MelodyEvent`, `TabPosition`, `MelodyTabResult`: frontend-facing result models.

# 8. UI Assets

HTML templates:
- `main_ui_template.html`: active app shell; contains all active HTML, CSS, and JavaScript inline.
- `transcriber_ui_template.html`: standalone transcriber shell; stylistically different, includes hero meters and sound toggle.
- `tab_sequencer_ui_template.html`: standalone sequencer shell; simpler focused layout.

CSS:
- All CSS is inline in the templates.
- `main_ui_template.html` defines CSS variables for light/dark themes, panel styling, controls, fretboard, output boxes, responsive layouts, and keyframes.
- `transcriber_ui_template.html` defines its own theme variables, hero shell, panels, WAV upload styles, progress meter, events, and output tab styles.
- `tab_sequencer_ui_template.html` defines a compact sequencer layout, panels, buttons, fretboard table, output box, and Next Line glow.

JavaScript:
- All JavaScript is inline in the templates.
- No bundler, module system, or framework is used.
- Active app logic lives at the bottom of `main_ui_template.html` and owns all frontend state.
- Standalone templates duplicate some parsing, upload, and rendering logic; be careful when changing behavior that should remain consistent.

Fonts:
- `main_ui_template.html`: imports Google Fonts `Cinzel`, `Source Sans 3`, and `IBM Plex Mono`.
- `transcriber_ui_template.html`: inspect before modifying; it imports its own font set and uses a separate brand style.
- `tab_sequencer_ui_template.html`: uses system-style sans and `IBM Plex Mono`-like monospace variables.
- The font imports are remote CSS imports, so offline rendering may fall back to local fonts.

SVG/icons:
- There is no icon library.
- The standalone transcriber uses a text music note brand mark (`♪`).
- Most controls are text buttons.
- Fretboards and outputs are DOM/CSS/HTML tables and text, not SVG or canvas.

Other assets:
- No image assets are present.
- TXT exports are generated in-browser via Blob URLs.

# 9. Dependencies

Entry point dependencies:
```text
run.py
-> music_scale.launcher.main()
-> music_scale.web_ui.main()
-> ThreadingHTTPServer + _ScaleRequestHandler
```

Server dependencies:
```text
web_ui.py
-> finder.ScaleFinder
-> guitar.STANDARD_TUNING, fret_to_note, fret_to_note_name, parse_tab_position
-> melody_transcriber.MelodyTranscriber, format_ascii_tab
-> notes.CHROMATIC_NOTES, normalize_many
-> scales.COMMON_SCALE_PATTERNS
-> main_ui_template.html
-> transcriber_ui_template.html
-> tab_sequencer_ui_template.html
```

Scale matching dependencies:
```text
finder.py
-> notes.CHROMATIC_NOTES, normalize_many, transpose
-> scales.COMMON_SCALE_PATTERNS
```

Guitar dependencies:
```text
guitar.py
-> notes.CHROMATIC_NOTES, transpose
```

Transcriber dependencies:
```text
melody_transcriber.py
-> notes.CHROMATIC_NOTES, note_index, normalize_note
-> Python wave/struct/math/re/dataclasses
```

Session dependencies:
```text
session.py
-> finder.ScaleFinder
-> guitar fret/tab parsers
-> notes.normalize_note
```

Frontend-to-backend API dependencies:
```text
main_ui_template.html
-> GET /api/config
-> POST /api/match
-> POST /api/transcribe
-> POST /api/transcribe-wav-upload
-> GET /api/transcribe-progress
```

# 10. Recommended Claude Context Pack

| File | Why Claude Needs It | Priority |
|---|---|---|
| `music_scale/main_ui_template.html` | Active UI shell, visual design, component layout, animations, interactions, and duplicated frontend business logic. | Essential |
| `music_scale/web_ui.py` | Defines active routes, API response shapes, config data, and backend constraints the UI must respect. | Essential |
| `music_scale/melody_transcriber.py` | Defines transcriber result models, tab strategies, ASCII output shape, and WAV progress behavior used by UI states. | Essential |
| `music_scale/guitar.py` | Explains string/fret notation and fretboard config assumptions used by the UI. | Essential |
| `music_scale/finder.py` | Explains matching scale payload semantics for the Scale Finder screen. | Essential |
| `music_scale/notes.py` | Explains note canonicalization, pitch class ordering, flats/sharps, and transposition. | Helpful |
| `tests/test_web_api.py` | Documents current API contracts, routes, grouped tabs, line breaks, and WAV upload expectations. | Helpful |
| `music_scale/tab_sequencer_ui_template.html` | Useful if preserving the standalone sequencer or comparing duplicated sequencer logic. | Helpful |
| `music_scale/transcriber_ui_template.html` | Useful if preserving the standalone transcriber or mining interaction ideas from its isolated shell. | Helpful |
| `README.md` | High-level app intent and developer commands. | Helpful |
| `music_scale/scales.py` | Scale pattern names and intervals, mostly stable domain data. | Optional |
| `music_scale/session.py` | Older state container, not used in active browser shell but useful for history/undo concepts. | Optional |
| `music_scale/gui.py` | Tkinter alternate UI, not relevant to browser UI/UX unless comparing behavior. | Optional |
| `tests/test_melody_transcriber.py` | Deeper domain behavior around note parsing and tab strategies. | Optional |
| `pyproject.toml` | Tooling and package metadata. | Optional |

# 11. Animation Opportunities

Do not redesign the app; preserve structure and identity. Motion should clarify state and reward interaction.

Good motion candidates:
- Mode switching: existing `fadeInPanel` and `panelLift` can be refined for smoother continuity between Scale Finder, Transcriber, and Tab Sequencer.
- Note chip selection: add subtle press, selected pulse, or color-fill transition when toggling notes.
- Fretboard cell clicks: add a quick glow/ripple on clicked cells and a more legible selected-note highlight transition.
- Matching scales update: animate result list insertions or use a brief status shimmer while `/api/match` is pending.
- Empty-to-results transitions: scale result list, event list, and generated tab blocks can fade/slide between empty and populated states.
- Transcribe button: add busy state and progress affordance during long note/WAV processing.
- WAV drag and drop: strengthen drag-over transition with border glow and slight panel lift.
- WAV upload/progress: existing textual progress bar could gain a visual meter or animated fill while preserving the mono/status aesthetic.
- Detected events: event rows could stagger in after transcription to make timing data easier to parse.
- ASCII tab output: animate update with a gentle highlight flash, not a full reflow-heavy effect.
- Tab Sequencer Next Line: current On/Off glow can pulse once when armed and softly settle.
- Tab Sequencer editor changes: generated tabs panel can show a stale/pending state after edits before Update Tabs.
- Copy/Paste/Save actions: use small success feedback on the button/status line.
- Theme toggle: dark/light switch can crossfade CSS variables more smoothly; body already transitions background and color.
- Panel hover/focus: keep restrained; panels already have shadows and borders, so motion should be minimal.
- Loading config: initial app load can show a subtle skeleton or progress cue for fretboards.
- Error states: status warnings can slide/fade in or briefly tint the relevant control.
- Reduced motion: `@media (prefers-reduced-motion: reduce)` already disables animation; keep that path intact.

# 12. Design Language

Current active visual design in `main_ui_template.html`:
- Overall aesthetic: warm, tactile, slightly instrument/workbench inspired. It feels like a polished local studio tool rather than a generic SaaS dashboard.
- Visual inspiration: brass/wood tones, etched panel borders, hardware-like controls, fretboard grid, and mono technical readouts.
- Light theme colors: warm tan and parchment surfaces (`#f3ebdc`, `#e8ddc9`, `#d8c5a4`), brown ink (`#2e261d`), muted amber accents (`#d2b378`, `#9d753f`), soft blue note chips.
- Dark theme colors: dark charcoal/brown surfaces (`#121418`, `#1a1e24`, `#2a221d`), cream text (`#f1e2c4`), golden accents (`#ddbf80`, `#ab7e41`).
- Typography: decorative serif `Cinzel` for brand and block titles, `Source Sans 3` for controls/body text, `IBM Plex Mono` for note/token/tab readouts.
- Spacing: compact operational layout, dense but breathable panels, 8-14px gaps in control rows, 14px panel padding, constrained full-viewport app grid.
- Borders: rounded panels around 20px, controls around 12px, inner dashed panel outlines, semi-transparent warm borders.
- Shadows: soft but noticeable panel shadows, inset highlights on controls, glows on active buttons and selected fretboard cells.
- Interaction style: text-heavy controls, hover lift on buttons, active states use gradient fill and glow, mode tabs use class toggles.
- Fretboard styling: table-based grid with sticky first column, small mono cells, warm plate/cell gradients, selected note glow.
- Output styling: mono blocks, scrollable ASCII tab panes, selected-line strips with subtle backgrounds.
- Motion already present: body background transition, hover transforms, panel fade/lift keyframes, ambient background drift, meter width transitions in standalone transcriber.
- Accessibility cues: many controls are semantic buttons/selects/textareas, mode switch has `role="tablist"`, Next Line uses `aria-pressed`, focus-visible outlines exist.
- Design preservation guidance: keep the warm instrument-studio palette, compact workflow-first density, mono technical readouts, and hardware-like controls. Avoid converting it into a bright minimalist card dashboard or a neon game-like interface.

Important implementation caveat for Claude:
- The active UI has significant duplicated logic with the standalone templates. If improving the active app, modify `main_ui_template.html` first. Only update `transcriber_ui_template.html` and `tab_sequencer_ui_template.html` when the standalone pages are intentionally being preserved or re-enabled.
