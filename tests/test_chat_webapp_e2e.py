"""
End-to-end tests for the chat webapp.

These tests validate:
1. The DOM structure matches the selectors used by observer.py
2. The full API -> browser -> DOM -> response flow works

Prerequisites for browser-based E2E tests:
- Install playwright: ``pip install playwright``
- Chromium binary available via one of:
  - ``GWD_TEST_CHROMIUM_PATH`` env var pointing to a chromium binary
  - Playwright browsers installed (``playwright install chromium``)
  - Well-known CI path (e.g. ``/opt/toolchains/ms-playwright/chromium-*/...``)

Browser-based tests are marked with ``@pytest.mark.e2e`` and excluded by
default in ``pyproject.toml`` (``-m 'not e2e'``).  Run them explicitly::

    python -m pytest -m e2e

If Playwright or a chromium binary is not available, individual tests skip
with a clear reason message so CI logs always show *why* coverage was dropped.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

# Locate the webapp directory (relative to repo root).
WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"

# Allow overriding the Chromium path via env var for portability.
_CHROMIUM_ENV = "GWD_TEST_CHROMIUM_PATH"

# Well-known paths in CI/Docker images (checked as fallback).
_CHROMIUM_FALLBACK_PATHS = [
    "/opt/toolchains/ms-playwright/chromium-1200/chrome-linux64/chrome",
    "/opt/toolchains/ms-playwright/chromium_headless_shell-1200/chrome-headless-shell-linux64/chrome-headless-shell",
]

# Custom pytest marker for E2E tests
e2e = pytest.mark.e2e


def _find_chromium() -> str | None:
    """Find a Chromium binary: prefer env var, then well-known paths."""
    env_path = os.environ.get(_CHROMIUM_ENV)
    if env_path and os.path.isfile(env_path):
        return env_path
    for p in _CHROMIUM_FALLBACK_PATHS:
        if os.path.isfile(p):
            return p
    return None


@pytest.fixture(scope="module")
def demo_server():
    """Start demo_server serving the webapp directory."""
    from gpt_web_driver.demo_server import serve_directory

    srv = serve_directory(WEBAPP_DIR)
    yield srv
    srv.close()


@pytest.fixture(scope="module")
def browser_and_pw():
    """Launch a Playwright browser (module-scoped for speed).

    Skips with a descriptive reason when Playwright or Chromium is missing
    so that CI logs always explain why E2E coverage was dropped.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        pytest.skip(
            "playwright is required for E2E tests. "
            "Install with: pip install playwright && playwright install chromium"
        )

    exe = _find_chromium()
    if exe is None:
        pytest.skip(
            f"No chromium binary found. Set {_CHROMIUM_ENV} or run "
            "'playwright install chromium'."
        )

    p = sync_playwright().start()
    try:
        browser = p.chromium.launch(headless=True, executable_path=exe)
    except Exception as exc:
        p.stop()
        pytest.skip(f"Cannot launch chromium: {exc}")
    yield browser, p
    browser.close()
    p.stop()


# ---------------------------------------------------------------------------
# Smoke test: validate static HTML contract WITHOUT a browser
# ---------------------------------------------------------------------------


def test_chat_html_contract():
    """
    Lightweight smoke test that validates the webapp's HTML structure
    matches the expected DOM contract (selectors used by observer.py)
    without requiring a browser or Playwright.

    This ensures the core contract is always tested, even in
    environments without browser binaries.
    """
    index_html = WEBAPP_DIR / "index.html"
    content = index_html.read_text(encoding="utf-8")

    # Required elements
    assert 'id="prompt-textarea"' in content, "Missing #prompt-textarea input"
    assert 'id="chat-messages"' in content, "Missing #chat-messages container"
    assert 'id="send-btn"' in content, "Missing #send-btn button"

    # Verify the JS creates DOM nodes with the right attributes
    app_js = (WEBAPP_DIR / "app.js").read_text(encoding="utf-8")
    assert "data-message-author-role" in app_js, (
        "app.js must set data-message-author-role on message nodes"
    )
    assert "data-message-id" in app_js, (
        "app.js must set data-message-id on message nodes"
    )
    assert "whitespace-pre-wrap" in app_js, (
        "app.js must use whitespace-pre-wrap class for content nodes"
    )

    # Verify the CSS references key selectors
    style_css = (WEBAPP_DIR / "style.css").read_text(encoding="utf-8")
    assert ".chat-messages" in style_css, "CSS must style .chat-messages"
    assert ".message-row" in style_css, "CSS must style .message-row"
    assert ".bubble" in style_css, "CSS must style .bubble"


def test_chat_html_accessibility():
    """Verify key accessibility attributes are present in the HTML."""
    content = (WEBAPP_DIR / "index.html").read_text(encoding="utf-8")

    assert "aria-label" in content, "Missing aria-label attributes"
    assert 'role="log"' in content, "Chat container should have role=log"
    assert "<label" in content, "Textarea should have an associated label"
    assert "<noscript" in content, "Should have a noscript fallback"


# ---------------------------------------------------------------------------
# Test: DOM contract — exact selectors from observer.py / ChatUIConfig
# ---------------------------------------------------------------------------


@e2e
def test_chat_dom_contract(demo_server, browser_and_pw):
    """
    Validate the webapp DOM matches the selectors used by observer.py:
    - [data-message-author-role]  (message_selector)
    - .whitespace-pre-wrap        (content_selector)
    - data-message-id attribute   (used by extract_chat_messages)
    - #prompt-textarea            (input_selector)
    """
    browser, _ = browser_and_pw
    page = browser.new_page()
    try:
        page.goto(f"{demo_server.base_url}/index.html", wait_until="domcontentloaded")

        # 1. Verify the textarea input exists
        textarea = page.query_selector("#prompt-textarea")
        assert textarea is not None, "#prompt-textarea not found"
        assert textarea.evaluate("el => el.tagName") == "TEXTAREA"

        # 1b. Verify welcome message is present on load
        welcome = page.query_selector("[data-message-author-role='assistant']")
        assert welcome is not None, "Welcome message should be present on load"
        welcome_content = welcome.query_selector(".whitespace-pre-wrap")
        assert welcome_content is not None, "Welcome message missing content node"

        # 2. Type a message and send
        page.fill("#prompt-textarea", "Hello from test")
        page.keyboard.press("Enter")

        # 3. Wait for the second assistant reply to appear (first is welcome)
        page.wait_for_function(
            "document.querySelectorAll(\"[data-message-author-role='assistant']\").length >= 2",
            timeout=5000,
        )

        # 4. Validate user message
        user_msgs = page.query_selector_all("[data-message-author-role='user']")
        assert len(user_msgs) >= 1, "No user message found"
        user_node = user_msgs[0]

        # data-message-id must be present and non-empty
        user_msg_id = user_node.get_attribute("data-message-id")
        assert user_msg_id, "User message missing data-message-id"

        # .whitespace-pre-wrap child must exist with content
        user_content = user_node.query_selector(".whitespace-pre-wrap")
        assert user_content is not None, "User message missing .whitespace-pre-wrap child"
        assert user_content.text_content().strip() == "Hello from test"

        # 5. Validate assistant message (second one, after welcome)
        asst_msgs = page.query_selector_all("[data-message-author-role='assistant']")
        assert len(asst_msgs) >= 2, "No assistant reply found"
        asst_node = asst_msgs[1]

        asst_msg_id = asst_node.get_attribute("data-message-id")
        assert asst_msg_id, "Assistant message missing data-message-id"

        asst_content = asst_node.query_selector(".whitespace-pre-wrap")
        assert asst_content is not None, "Assistant message missing .whitespace-pre-wrap child"
        asst_text = asst_content.text_content().strip()
        assert len(asst_text) > 0, "Assistant message content is empty"

        # 6. Validate message container has overflow-y: auto
        chat_container = page.query_selector("#chat-messages")
        assert chat_container is not None
        overflow = chat_container.evaluate("el => getComputedStyle(el).overflowY")
        assert overflow == "auto", f"Expected overflow-y: auto, got {overflow}"

        # 7. Validate accessibility attributes
        assert chat_container.get_attribute("role") == "log"
        assert chat_container.get_attribute("aria-label") is not None

        # 8. Verify data-testid attributes for test resilience
        assert page.query_selector("[data-testid='chat-messages']") is not None
        assert page.query_selector("[data-testid='prompt-textarea']") is not None
        assert page.query_selector("[data-testid='send-btn']") is not None

    finally:
        page.close()


@e2e
def test_chat_multiple_messages(demo_server, browser_and_pw):
    """Send multiple messages and verify deterministic canned replies."""
    browser, _ = browser_and_pw
    page = browser.new_page()
    try:
        page.goto(f"{demo_server.base_url}/index.html", wait_until="domcontentloaded")

        # Welcome message is assistant message #1
        page.wait_for_selector("[data-message-author-role='assistant']", timeout=3000)

        for i in range(3):
            page.fill("#prompt-textarea", f"Message {i}")
            page.keyboard.press("Enter")
            # Wait until we have the expected number of assistant replies
            # +1 for welcome message, +1 for 0-based
            expected_count = i + 2  # welcome + (i+1) replies
            page.wait_for_function(
                f"document.querySelectorAll(\"[data-message-author-role='assistant']\").length >= {expected_count}",
                timeout=5000,
            )

        user_msgs = page.query_selector_all("[data-message-author-role='user']")
        asst_msgs = page.query_selector_all("[data-message-author-role='assistant']")
        assert len(user_msgs) == 3
        assert len(asst_msgs) == 4  # welcome + 3 replies

        # All messages must have unique data-message-id
        all_ids = set()
        for node in user_msgs + asst_msgs:
            mid = node.get_attribute("data-message-id")
            assert mid, "Missing data-message-id"
            assert mid not in all_ids, f"Duplicate data-message-id: {mid}"
            all_ids.add(mid)

    finally:
        page.close()


# ---------------------------------------------------------------------------
# Test: True end-to-end API hookup
# ---------------------------------------------------------------------------


@e2e
def test_api_e2e_hookup(demo_server):
    """
    Full flow: HTTP POST /v1/chat/completions -> session.chat_completion
    drives the browser -> webapp generates dummy reply -> DOM extraction
    -> HTTP response.

    The MockSession.chat_completion method actually performs Playwright
    browser interactions (fill textarea, press Enter, wait for assistant
    node, extract text) during the API call — proving the full
    API -> browser -> DOM -> response data path.

    Uses Playwright's async API to avoid greenlet/thread conflicts with
    FastAPI's TestClient.
    """
    try:
        import fastapi  # noqa: F401
        from fastapi.testclient import TestClient as _TestClient
    except ModuleNotFoundError:
        pytest.skip("fastapi is required for E2E API test (install with: pip install fastapi)")

    try:
        from playwright.async_api import async_playwright
    except ModuleNotFoundError:
        pytest.skip("playwright is required for E2E API test (install with: pip install playwright)")

    exe = _find_chromium()
    if exe is None:
        pytest.skip(
            f"No chromium binary found. Set {_CHROMIUM_ENV} or run "
            "'playwright install chromium'."
        )

    from gpt_web_driver.api_server import create_app

    _pw = None
    _browser = None
    _page = None
    base_url = demo_server.base_url

    class MockSession:
        """
        A mock session that uses Playwright async API to drive the chat webapp,
        simulating what NibsSession does with OS-level input + nodriver.

        chat_completion() performs the actual browser interaction:
        1. Fill #prompt-textarea with the prompt
        2. Press Enter to send
        3. Wait for a new [data-message-author-role='assistant'] to appear
        4. Extract text from .whitespace-pre-wrap inside the assistant node
        """

        paused_reason = None

        async def start(self) -> None:
            nonlocal _pw, _browser, _page
            _pw = await async_playwright().start()
            _browser = await _pw.chromium.launch(
                headless=True, executable_path=exe
            )
            _page = await _browser.new_page()
            await _page.goto(
                f"{base_url}/index.html", wait_until="domcontentloaded"
            )

        async def close(self) -> None:
            nonlocal _pw, _browser, _page
            if _page:
                await _page.close()
            if _browser:
                await _browser.close()
            if _pw:
                await _pw.stop()

        def resume(self) -> None:
            self.paused_reason = None

        async def chat_completion(self, prompt: str) -> str:
            assert _page is not None, "Browser page not initialized"

            # Track how many assistant messages exist before we act
            before = len(
                await _page.query_selector_all(
                    "[data-message-author-role='assistant']"
                )
            )

            # Type the prompt into the textarea and send
            await _page.fill("#prompt-textarea", prompt)
            await _page.keyboard.press("Enter")

            # Wait for a NEW assistant message to appear
            expected = before + 1
            await _page.wait_for_function(
                f"document.querySelectorAll(\"[data-message-author-role='assistant']\").length >= {expected}",
                timeout=5000,
            )

            # Extract the last assistant message text
            asst_nodes = await _page.query_selector_all(
                "[data-message-author-role='assistant']"
            )
            last_asst = asst_nodes[-1]
            content_node = await last_asst.query_selector(".whitespace-pre-wrap")
            text = await content_node.text_content()
            return text.strip()

    session = MockSession()
    app = create_app(session=session)

    with _TestClient(app) as client:
        r = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Test message"}]},
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        j = r.json()

        # Validate OpenAI-compatible format
        assert "id" in j
        assert j["id"].startswith("chatcmpl_")
        assert j["object"] == "chat.completion"
        assert "model" in j
        assert "choices" in j
        assert len(j["choices"]) == 1
        assert j["choices"][0]["message"]["role"] == "assistant"
        assert j["choices"][0]["finish_reason"] == "stop"
        assert "usage" in j
        assert isinstance(j["usage"]["prompt_tokens"], int)

        # The API response content must be non-empty (a canned reply)
        api_reply = j["choices"][0]["message"]["content"]
        assert len(api_reply) > 0
