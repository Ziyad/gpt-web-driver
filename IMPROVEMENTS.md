# Proposed Improvements

Actionable improvement proposals for the gpt-web-driver codebase, organized by
category with priority levels (**High** / **Medium** / **Low**) to help triage.

**Highest-impact items at a glance:** Extract shared box-model pipeline in
`nodriver_dom.py` (1c), add `logging.debug` to the 24 silent `except Exception`
blocks (5a), add `ruff format --check` and `mypy` to CI (4a, 4b), unit-test the
pure-compute `core/physics.py` module (3a).

---

## 1. Code Duplication & DRY Opportunities

**Priority: High**

### 1a. `_env_first` duplicated across modules

`src/gpt_web_driver/browser.py:30` and `src/gpt_web_driver/runner.py:45`
contain identical implementations of `_env_first(env, *keys)`.  Extract to a
shared utility (e.g. `src/gpt_web_driver/core/env.py`) and import from both
call-sites.

### 1b. `_send_dict` helper defined three times in `nodriver_dom.py`

The local helper `_send_dict(method, params)` is copy-pasted inside three
functions in `src/gpt_web_driver/nodriver_dom.py`:

- `selector_viewport_center` (line 157)
- `selector_viewport_quad` (line 270)
- `dom_get_outer_html` (line 566)

Hoist it to a module-level private function to remove the triplication.

### 1c. `selector_viewport_center` / `selector_viewport_quad` share ~80% logic

`src/gpt_web_driver/nodriver_dom.py:129` and line 247 follow the same
structure: resolve node-id, try nodriver `get_box_model` with TypeError
fallback, fall back to dict CDP, extract quad, get layout metrics, adjust for
viewport scroll.  Extract the shared box-model + layout-metric pipeline into a
private `_get_box_model_viewport(page, node_id)` helper and have both functions
call it.

### 1d. DOM helpers re-implemented in `core/observer.py`

`src/gpt_web_driver/core/observer.py` re-implements `_dom_get_document`
(line 22) and `_dom_query_selector` (line 44).  These serve the same purpose as
`_dom_get_document_nodriver` (line 77) and `_dom_query_selector_nodriver`
(line 111) in `src/gpt_web_driver/nodriver_dom.py`, but the implementations
differ: observer.py calls `uc.cdp.dom.*` directly while nodriver_dom.py uses
defensive `getattr` chains for resilience across nodriver versions.
Consolidation would require choosing one pattern -- the `getattr`-based approach
is more robust, so observer.py could switch to importing from nodriver_dom.py,
which it already does for `dom_get_outer_html`, `html_to_text`, and
`wait_for_selector`.

### 1e. `_HTMLToText` in `scripts/extract_chat_messages.py`

`scripts/extract_chat_messages.py:17` implements a standalone `_HTMLToText`
HTMLParser that overlaps with the `html_to_text` function in
`src/gpt_web_driver/nodriver_dom.py:610`.  The script version is richer
(block-level newlines), so either consolidate into the library function with an
option for richer formatting, or import the library version and extend.

### 1f. Metadata JSON write blocks in `browser.py`

`src/gpt_web_driver/browser.py:405` and line 452 write near-identical metadata
JSON blobs with the same keys.  Extract a small helper to deduplicate.

### 1g. `interact()` / `click()` coordinate pipeline in `runner.py`

`src/gpt_web_driver/runner.py:368` (`interact`) and line 406 (`click`) repeat
~20 lines of the same coordinate-transform + OS-input sequence (locate,
viewport, screen, noise, emit, move, execute).  Extract a shared
`_perform_interaction` method.

---

## 2. Type Safety

**Priority: Medium**

### 2a. Untyped `page` / `browser` parameters

The `page` parameter is typed as `Any` in 25+ call-sites across
`src/gpt_web_driver/nodriver_dom.py`, `src/gpt_web_driver/core/observer.py`,
`src/gpt_web_driver/core/driver.py`, and `src/gpt_web_driver/runner.py`.
Define a minimal `Protocol` (e.g. `PageLike`) describing the expected interface
(`send()`, coroutine-based CDP calls) to get IDE support and static-analysis
coverage without a hard dependency on a specific nodriver version.

### 2b. `RunConfig` is a flat 25-field dataclass

`src/gpt_web_driver/runner.py:54` defines `RunConfig` with 25 fields (lines
55-79: `url`, `selector`, `text`, `press_enter`, `dry_run`, `timeout_s`,
`browser_path`, `browser_channel`, `download_browser`, `sandbox`,
`browser_cache_dir`, `cdp_host`, `cdp_port`, `scale_x`, `scale_y`, `offset_x`,
`offset_y`, `noise`, `mouse`, `typing`, `real_profile`, `shim_profile`, `seed`,
`pre_interact_delay_s`, `post_click_delay_s`).  Consider grouping related
fields into sub-dataclasses (e.g. `BrowserConfig`, `CoordConfig`,
`TimingConfig`) to improve readability and reduce the surface area of
`_make_config` in `src/gpt_web_driver/cli.py`.

### 2c. Untyped `session` parameter in `api_server.py`

`src/gpt_web_driver/api_server.py:47` -- `create_app(session, ...)` -- has no
type annotation for `session`.  It duck-types `.start()`, `.close()`,
`.chat_completion()`, `.paused_reason`, `.resume()`.  A `Protocol` class would
make the contract explicit.

### 2d. Untyped `emit` parameter in `cli.py`

`src/gpt_web_driver/cli.py:396` -- `_doctor(ns, *, emit=None)` -- `emit` has
no type annotation.  Adding `Optional[Callable[[dict[str, Any]], None]]` would
improve clarity.

---

## 3. Test Coverage Gaps

**Priority: High**

Note: some modules have partial coverage under different test file names (e.g.
`tests/test_runner_cdp.py` covers parts of `src/gpt_web_driver/runner.py`).
The items below identify modules with no dedicated unit tests at all.

### 3a. No unit tests for `core/physics.py`

`NeuromotorMouse` and `CognitiveTyper` in
`src/gpt_web_driver/core/physics.py` are pure-compute classes with
deterministic (when seeded) output.  They are highly amenable to unit testing
but have no corresponding test file.

### 3b. No unit tests for `core/observer.py`

`extract_chat_messages`, `last_assistant_message_text`, and
`wait_for_assistant_reply` in `src/gpt_web_driver/core/observer.py` lack unit
tests.  The HTML-parsing logic in particular can be tested with static
fixtures.

### 3c. No unit tests for `core/driver.py`

`grant_permissions` and `optimize_connection` in
`src/gpt_web_driver/core/driver.py` have no dedicated tests.

### 3d. No unit tests for `core/safety.py`

`DeadManSwitch`, `beep`, and `maybe_move_active_window_to_virtual_desktop` in
`src/gpt_web_driver/core/safety.py` are untested.

### 3e. No unit tests for `actions/input.py`

`HybridInput`, `_ClipboardHygiene`, and the key-mapping logic in
`src/gpt_web_driver/actions/input.py` have no test file.

### 3f. No tests for `demo_server.py`

`DemoServer` and `serve_directory` in `src/gpt_web_driver/demo_server.py` have
no tests.

---

## 4. CI Hardening

**Priority: High**

### 4a. Add `ruff format --check .` step

CI currently only runs `ruff check .` (`.github/workflows/ci.yml:26`).
Formatting drift is not caught until a developer notices locally.  Add a
`ruff format --check .` step after the lint step.

### 4b. Run `mypy` in CI

`mypy` is declared as a dev dependency (`pyproject.toml:35`) but is never
invoked in CI.  Add a `python -m mypy src/` step, starting with a lenient
config (e.g. `--ignore-missing-imports`) and tightening over time.

### 4c. Add Python 3.13 to the test matrix

The CI matrix currently only tests `"3.12"` (`.github/workflows/ci.yml:13`).
Since the project requires `>=3.12`, adding `"3.13"` ensures forward
compatibility.

### 4d. Enable pip caching

There is no `cache` key on `actions/setup-python` and no `actions/cache` step.
Adding `cache: pip` to the setup-python action reduces CI run time.

### 4e. Run format check before tests

Reorder so that cheap lint/format checks run first and fail fast before the
slower pytest step.

---

## 5. Error Handling & Robustness

**Priority: Medium**

### 5a. Excessive bare `except Exception: pass` in `nodriver_dom.py`

`src/gpt_web_driver/nodriver_dom.py` contains **24** instances of
`except Exception` that silently swallow errors with `pass` or `return`
(verified via `grep -c 'except Exception' src/gpt_web_driver/nodriver_dom.py`).
Key examples:

- Line 242: layout metric failure silently skipped -- viewport offset
  correction becomes wrong without any log message.
- Lines 427, 475-478: querySelector attempts fail silently, making selector
  debugging very difficult.
- Line 628: entire BeautifulSoup code path swallowed on failure.

**Recommendation:** Replace silent `pass` / `return` with at least
`logging.debug(...)` calls so failures are discoverable when troubleshooting.
Where feasible, catch narrower exceptions (e.g. `TypeError`, `KeyError`).

### 5b. Triple-nested try/except in `core/driver.py`

`src/gpt_web_driver/core/driver.py:53` has three levels of nested try/except
for `grant_permissions`.  Consider flattening into a sequence of attempts with
early returns.

### 5c. `api_server.py` leaks internal error details

`src/gpt_web_driver/api_server.py:100` --
`raise HTTPException(status_code=500, detail=str(e))` -- surfaces the raw
exception message to API clients.  Replace with a generic message (e.g.
`"internal error"`) and log the full traceback server-side.

### 5d. Fragile dataclass reconstruction in `nibs.py`

`src/gpt_web_driver/nibs.py:115` uses
`run_cfg.__class__(**{**run_cfg.__dict__, ...})` to create a modified frozen
dataclass.  This breaks if `RunConfig` uses `__slots__` or computed properties.
Use `dataclasses.replace()` instead.

---

## 6. Documentation Gaps

**Priority: Medium**

### 6a. No architecture / design document

There is no document explaining the project's read-only doctrine (no
`Runtime.evaluate`, no `page.click`, CDP-only approach).  The doctrine is
enforced by `tests/test_read_only_doctrine.py` but undocumented for
contributors.  This test is a good model -- consider documenting the doctrine
itself and referencing the test as the enforcement mechanism, so new
contributors understand the constraint before tripping the test.

### 6b. `CONTRIBUTING.md` omits architectural constraints

`CONTRIBUTING.md` covers dev setup, tests, and lint but does not mention the
read-only doctrine, the CDP-only constraint, or why `Runtime.evaluate` is
forbidden.  Adding a short "Architectural constraints" section that explains
the doctrine and points to `tests/test_read_only_doctrine.py` would prevent
contributors from unknowingly violating these rules.

### 6c. Missing docstrings on public functions

Notable gaps:

| Module | Undocumented public functions |
|---|---|
| `src/gpt_web_driver/runner.py` | `FlowRunner.__init__`, `start`, `close`, `navigate`, `interact`, `click`, `type`, `press`, `wait_for_selector`, `extract_text`, `wait_for_text` (11 methods) |
| `src/gpt_web_driver/nodriver_dom.py` | `dom_get_outer_html`, `normalize_element`, `element_viewport_center`, `maybe_maximize`, `maybe_bring_to_front` |
| `src/gpt_web_driver/cli.py` | `build_parser`, `_make_config`, `_doctor`, `main` |
| `src/gpt_web_driver/flow.py` | `load_flow`, `run_flow` |

### 6d. No flow JSON schema documentation

The flow file format is only shown by example in the README.  A formal schema
(JSON Schema or documented field table) would help users author flows
correctly.

### 6e. No Python library API documentation

Beyond the README's CLI examples, there is no documentation for using
gpt-web-driver as a Python library (importing `FlowRunner`, `RunConfig`, etc.).

---

## 7. Dependency & Packaging

**Priority: Low**

### 7a. `requirements.txt` duplicates `pyproject.toml`

`requirements.txt` lists all dependencies (required + optional) in a flat file
with inline comments marking optional ones (e.g. `# optional: required for
OS-level input`).  `pyproject.toml` is the canonical source with properly
separated extras.  Consider adding a header comment to `requirements.txt`
noting it is a convenience snapshot, not the source of truth, to avoid
confusion when the two files drift.

### 7b. `conftest.py` manually inserts `src/` into `sys.path`

`tests/conftest.py:6` manually prepends `src/` to `sys.path`.  This is
unnecessary when the package is installed in editable mode (`pip install -e .`).

**Tradeoff:** removing this would require all contributors and CI to run
`pip install -e ".[dev]"` before `pytest`, which CONTRIBUTING.md already
documents.  If the goal is zero-install `pytest` support (just clone and run),
keep the injection but add a comment explaining why it exists.

### 7c. No `[all]` extra for combined install

`pyproject.toml` defines six extras (`gui`, `api`, `nibs`, `desktop`, `dev`,
`e2e`) but no `[all]` convenience extra.  The full install command
`pip install -e ".[gui,api,nibs,desktop,dev]"` is unwieldy.  An `[all]` extra
that unions the others would simplify onboarding.

### 7d. `e2e` extra omits `ruff` and `mypy`

The `e2e` extra (`pyproject.toml:37`) includes `pytest` and `playwright` but
not `ruff` or `mypy` from `dev`.  A CI job running E2E tests and lint would
need to install both extras separately.

---

## 8. Architectural Simplification

**Priority: Medium**

### 8a. Long dispatch chain in `flow.py`

`src/gpt_web_driver/flow.py:107` has a 9-branch if/elif chain for action
dispatch with repetitive `step.get("within")` validation (repeated at lines
117, 130, 169, 188, 215).  A dispatch table mapping action names to handler
functions would reduce repetition and make adding new actions easier.

### 8b. God method: `NibsSession.chat_completion`

`src/gpt_web_driver/nibs.py:156` is 144 lines handling mouse movement,
incidental hover, clicking, typing, scroll/flick behavior, and dead-man switch
detection.  Extracting the scroll/flick logic and the interaction-sequence
logic into separate methods or a helper class would improve readability and
testability.

### 8c. CLI argument explosion in `cli.py`

`src/gpt_web_driver/cli.py:56` manually registers 30+ arguments via
`add_common()`.  The `calibrate` subparser (line 280) and `doctor` subparser
(line 221) then partially re-declare overlapping arguments.  Loading defaults
from a config file (TOML) and reducing the argument surface would simplify
maintenance.

### 8d. Repeated conditional nodriver import

`src/gpt_web_driver/nodriver_dom.py` wraps `import nodriver as uc` in
try/except blocks at five separate locations (lines 150, 265, 408, 469, 562).
A single module-level lazy import (e.g.
`_uc = None; try: import nodriver as _uc except: pass`) would eliminate the
repetition.
