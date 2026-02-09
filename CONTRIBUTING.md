# Contributing

## Dev Setup

Requirements:
- Python 3.12+

Create and activate a virtualenv, then install editable + dev deps:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

If you want to run with real OS-level input (non-dry-run), also install the GUI extra:

```bash
python -m pip install -e ".[gui]"
```

## Tests

```bash
python -m pytest
```

Tests are designed to run without a GUI by:
- avoiding `pyautogui` import unless needed
- monkeypatching a fake `nodriver` module where appropriate

## Lint / Format

```bash
python -m ruff check .
python -m ruff format .
```

## Project Structure

- `src/gpt_web_driver/`: library + CLI implementation
- `scripts/`: small utilities used in the README
- `webapp/`: local deterministic page for quick manual testing
