# Proposed Improvements (Current)

Last reviewed: 2026-02-14  
Repository state: `main` at commit `12bec8f`

This file tracks open, actionable improvements. Items that were completed since
the previous draft are listed first so we do not regress.

---

## 0. Completed Since Previous Draft (2026-02-10)

These were proposed previously and are now implemented:

- Shared `_env_first` extraction is done in `src/gpt_web_driver/core/env.py`
  and imported by `src/gpt_web_driver/browser.py` and
  `src/gpt_web_driver/runner.py`.
- `nodriver_dom.py` now has a single module-level `_send_dict` helper in
  `src/gpt_web_driver/nodriver_dom.py`.
- Shared box-model/view-viewport pipeline now exists as
  `_get_box_model_and_viewport_offset` in `src/gpt_web_driver/nodriver_dom.py`.
- CI now runs format + type checks:
  - `ruff format --check` in `.github/workflows/ci.yml`
  - `mypy` in `.github/workflows/ci.yml`
  - Python 3.13 matrix entries in `.github/workflows/ci.yml`
  - pip cache in `.github/workflows/ci.yml`
- `api_server` no longer returns raw exception text; it logs server-side and
  returns a generic internal error shape in `src/gpt_web_driver/api_server.py`.
- `nibs` now uses `dataclasses.replace` for frozen dataclass updates in
  `src/gpt_web_driver/nibs.py`.
- Architecture constraints are now documented in `CONTRIBUTING.md`.
- `requirements.txt` now states it is a convenience snapshot and that
  `pyproject.toml` is canonical.
- `[all]` extra exists in `pyproject.toml`.
- `core/physics.py` now has dedicated tests in `tests/test_physics.py`.

---

## 1. Code Duplication & DRY Opportunities

**Priority: High**

### 1a. DOM helper duplication between `observer.py` and `nodriver_dom.py`

`src/gpt_web_driver/core/observer.py` defines local CDP helpers
(`_dom_get_document`, `_dom_query_selector`, `_dom_query_selector_all`) that
overlap with patterns already in `src/gpt_web_driver/nodriver_dom.py`.

Potential improvement:
- Consolidate around one helper style (preferably the defensive nodriver-shape
  handling used in `nodriver_dom.py`) to reduce maintenance divergence.

### 1b. HTML-to-text logic duplicated in script and library

`scripts/extract_chat_messages.py` has `_HTMLToText`, while
`src/gpt_web_driver/nodriver_dom.py` has `html_to_text`.

Potential improvement:
- Reuse one implementation, or expose formatting modes from the library helper
  so scripts do not re-implement parsing behavior.

### 1c. Metadata JSON write block duplicated in `browser.py`

`src/gpt_web_driver/browser.py` writes almost identical metadata payloads in
two code paths inside `ensure_chrome_for_testing`.

Potential improvement:
- Extract a private `_write_installed_metadata(...)` helper.

### 1d. `interact()` and `click()` share coordinate + OS-input sequence

`src/gpt_web_driver/runner.py` duplicates coordinate transform, noise, emit,
bring-to-front, and move/click sequencing across `interact` and `click`.

Potential improvement:
- Extract a shared private interaction primitive and keep only behavior deltas
  (`text`, `press_enter`) in the public methods.

---

## 2. Type Safety

**Priority: Medium**

### 2a. Heavy use of `Any` for page/browser-like objects

`Any` is used broadly for `page` and `browser` across:
- `src/gpt_web_driver/nodriver_dom.py`
- `src/gpt_web_driver/core/observer.py`
- `src/gpt_web_driver/core/driver.py`
- `src/gpt_web_driver/runner.py`

Potential improvement:
- Define narrow `Protocol` types (`PageLike`, `BrowserLike`) around the methods
  actually used (for example `send`, `get`, `wait_for`, `stop`).

### 2b. `RunConfig` remains a large flat dataclass

`src/gpt_web_driver/runner.py` keeps many unrelated concerns in one config
shape (browser selection, CDP transport, coordinate transform, timing, input).

Potential improvement:
- Group into nested dataclasses (for example browser/cdp/input/timing blocks) to
  reduce coupling in `src/gpt_web_driver/cli.py` config assembly.

### 2c. `session` parameter in `create_app` is untyped

`src/gpt_web_driver/api_server.py` `create_app(*, session, ...)` still relies
on duck typing.

Potential improvement:
- Add a `SessionLike` `Protocol` covering `start`, `close`, `chat_completion`,
  `paused_reason`, and `resume`.

### 2d. `_doctor(..., emit=None)` lacks an explicit callable type

`src/gpt_web_driver/cli.py` leaves `emit` untyped.

Potential improvement:
- Annotate as `Callable[[dict[str, Any]], None] | None`.

---

## 3. Test Coverage Gaps

**Priority: High**

### 3a. No dedicated unit tests for `core/observer.py`

`extract_chat_messages`, `last_assistant_message_text`, and
`wait_for_assistant_reply` in `src/gpt_web_driver/core/observer.py` are not
covered by a dedicated unit test module.

### 3b. No dedicated unit tests for `core/driver.py`

`grant_permissions` and `optimize_connection` in
`src/gpt_web_driver/core/driver.py` do not have focused tests.

### 3c. No dedicated unit tests for `core/safety.py`

`DeadManSwitch`, `beep`, and virtual desktop move helpers in
`src/gpt_web_driver/core/safety.py` are not unit tested.

### 3d. No dedicated unit tests for `actions/input.py`

`HybridInput`, clipboard hygiene behavior, and key-mapping logic in
`src/gpt_web_driver/actions/input.py` do not have direct tests.

### 3e. `demo_server.py` has only indirect coverage

`serve_directory` is exercised in E2E (`tests/test_chat_webapp_e2e.py`), but
`src/gpt_web_driver/demo_server.py` lacks focused unit tests.

---

## 4. CI Hardening (Remaining)

**Priority: Medium**

### 4a. Python 3.13 is still experimental in CI

`.github/workflows/ci.yml` marks 3.13 jobs as `experimental` with
`continue-on-error`.

Potential improvement:
- Graduate 3.13 to required once flakiness or dependency constraints are
  resolved.

### 4b. `mypy` runs in only one matrix cell

Current type checks are limited to a single Linux/Python-3.12 lane.

Potential improvement:
- Expand `mypy` scope (at least a non-experimental 3.13 lane, potentially all
  required lanes if runtime remains acceptable).

---

## 5. Error Handling & Robustness

**Priority: Medium**

### 5a. Broad exception handling is still common in `nodriver_dom.py`

`src/gpt_web_driver/nodriver_dom.py` currently has 20 `except Exception`
handlers. Logging improved substantially, but broad catches remain in hot paths.

Potential improvement:
- Narrow exception types where possible (`TypeError`, `AttributeError`,
  `KeyError`).
- Keep debug logging on fallback paths to preserve diagnosability.

### 5b. `grant_permissions` still has deeply nested fallbacks

`src/gpt_web_driver/core/driver.py` uses multi-level nested try/except blocks.

Potential improvement:
- Refactor into a linear sequence of attempts with explicit helper functions and
  early returns.

### 5c. `nibs.py` still swallows several operational exceptions

`src/gpt_web_driver/nibs.py` intentionally suppresses exceptions in several
auxiliary paths (hover, scrolling, snapshot probes).

Potential improvement:
- Add low-volume `debug` logs for swallowed exceptions to make field diagnosis
  easier without impacting happy-path behavior.

---

## 6. Documentation Gaps

**Priority: Medium**

### 6a. No standalone architecture/design doc

Constraints are documented in `CONTRIBUTING.md`, but there is still no dedicated
architecture document in `docs/` that explains subsystem boundaries and data
flow.

### 6b. No formal flow schema reference

`README.md` includes examples, but there is no normative schema/table for flow
files (`action` payloads, required/optional keys, types, defaults).

Potential improvement:
- Add `docs/flow-schema.md` (or JSON Schema + docs page) and link it from
  README.

### 6c. Python API docs are minimal

`README.md` has a short Python usage snippet, but there is no fuller API
reference for `RunConfig`, `FlowRunner`, `Driver`, and server/session classes.

### 6d. Public docstring coverage remains uneven

Several public or user-facing functions/methods across runner/cli/flow paths
still rely on code readability rather than API-level docstrings.

---

## 7. Dependency & Packaging

**Priority: Low**

### 7a. `tests/conftest.py` still mutates `sys.path`

`tests/conftest.py` prepends `src/` to support zero-install test runs.

Tradeoff:
- Keep current behavior for convenience, or remove it and require editable
  installs consistently (`pip install -e ".[dev]"`).

### 7b. `e2e` extra does not include lint/type tooling

`pyproject.toml` `e2e` extra is focused on runtime E2E dependencies and omits
`ruff`/`mypy`.

Potential improvement:
- Keep as-is (lean E2E env) or add a composed extra (for example `ci`) that
  unions `dev + e2e`.

---

## 8. Architectural Simplification

**Priority: Medium**

### 8a. `flow.py` has a long action dispatch chain

`src/gpt_web_driver/flow.py` uses a long `if/elif` action dispatcher with
repeated validation patterns.

Potential improvement:
- Replace with a dispatch table of action handlers with shared validation
  helpers.

### 8b. `NibsSession.chat_completion` is still a large multi-responsibility method

`src/gpt_web_driver/nibs.py` `chat_completion` handles targeting, motion,
typing, scrolling, dead-man checks, and recovery logic in one method.

Potential improvement:
- Split into smaller private stages (targeting, input, wait loop, failure
  handling) for testability and readability.

### 8c. CLI argument surface remains large

`src/gpt_web_driver/cli.py` still centralizes many arguments in one parser path,
with some repeated patterns across commands.

Potential improvement:
- Factor parser construction into smaller reusable builders, or introduce
  optional config-file defaults.

### 8d. Repeated local `import nodriver as uc` blocks

`src/gpt_web_driver/nodriver_dom.py` repeats defensive local imports in multiple
functions.

Potential improvement:
- Centralize lazy import into a small helper to reduce repetition while keeping
  testability and import-failure resilience.
