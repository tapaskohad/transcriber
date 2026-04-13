# Music Scale Finder

Interactive music scale detection with both desktop and browser UI modes, plus a standalone melody-to-tab transcriber.

## Highlights

- Modular music theory core (`notes`, `scales`, `finder`, `guitar`, `session`)
- Live scale matching after 3+ unique notes
- Browser UI with note palette, guitar fretboard, and transcriber page
- Melody transcription from note tokens, frequency frames, or WAV input
- Local HTTP API endpoints for matching and transcription workflows

## Quick Start (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python run.py
```

Alternative launcher:

```powershell
python -m music_scale
```

After launch, your browser opens automatically. Keep the terminal window open while using the app.

## Development Setup

```powershell
python -m pip install --upgrade pip
pip install -e .[dev]
```

## Run Tests

```powershell
python -m unittest discover -s tests -v
```

## API Notes

- `GET /api/config`
- `POST /api/match` with JSON: `{ "notes": ["C", "E", "G"] }`
- `POST /api/transcribe` with JSON mode payload (`notes`, `frequencies`, or `wav`)

Request validation now includes:

- Query-string-safe route handling
- JSON object validation for POST payloads
- Request body size guardrails

## CI

GitHub Actions runs the unit test suite on Python 3.10 and 3.11 for every push and pull request.
