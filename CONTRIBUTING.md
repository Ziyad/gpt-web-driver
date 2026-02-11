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

If you want to run the local OpenAI-compatible API server (`gpt-web-driver serve`), also install:

```bash
python -m pip install -e ".[api,nibs,gui]"
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

## Architectural Constraints

This project enforces a strict **read-only doctrine**: the browser DOM is
observed exclusively through CDP (Chrome DevTools Protocol) commands such as
`DOM.getDocument`, `DOM.querySelector`, and `DOM.getBoxModel`.  The following
patterns are **forbidden** in library code under `src/gpt_web_driver/`:

- `Runtime.evaluate` / `page.evaluate` -- no JavaScript execution in the page
  context.
- `page.click` / `send_keys` -- no driver-level synthetic input; all input
  flows through OS-level APIs (`pyautogui`).

These constraints are enforced automatically by
`tests/test_read_only_doctrine.py`, which scans the source tree for forbidden
strings.  Any pull request that introduces a forbidden pattern will fail CI.

**Why?**  The read-only doctrine keeps the browser session indistinguishable
from a human operator: passive DOM reads via CDP leave no detectable
JavaScript side-effects, and OS-level input produces real hardware events.

## Project Structure

- `src/gpt_web_driver/`: library + CLI implementation
- `scripts/`: small utilities used in the README
- `webapp/`: local deterministic page for quick manual testing
