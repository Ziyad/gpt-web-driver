Here is the comprehensive **Technical Design Document (TDD)** for the project. This specification is formatted to be pasted directly into a Coding LLM (like Claude 3.5 Sonnet, GPT-4o, or Cursor) to generate the production-ready codebase.

---

# Project Specification: Ghost-Shim (Private ChatGPT API Bridge)

**Classification:** Anti-Evasion Research / Personal Automation
**Target Architecture:** Python 3.12+ • `nodriver` • `pyautogui` • `FastAPI`
**Goal:** Create an undetected, local-only API endpoint (`POST /v1/chat/completions`) backed by a live, headed Chrome instance.

---

## 1. Executive Summary

This system functions as a **Cybernetic Overlay**. It rejects standard browser automation paradigms (which rely on injecting JavaScript or using the WebDriver protocol) in favor of **OS-Level Interaction**.

* **Reading (Input):** Passive CDP DOM inspection (Invisible to page JS).
* **Writing (Output):** Hardware-simulated mouse/keyboard interrupts (Biometrically valid).
* **Environment:** Strictly Headed (Visible), utilizing "Shadow Profiles" and Virtual Desktops to maintain stealth.

---

## 2. Strict Constraints (The "Iron Rules")

**Instructions for the LLM:** Ensure every generated line of code adheres to these prohibitions.

1. **NO `headless=True`:** The browser must always render to a valid GPU surface. Use Virtual Desktop management to hide the window.
2. **NO `page.evaluate()`:** Never execute JavaScript in the page context to scrape text (e.g., `document.body.innerText`). This poisons the stack. Use CDP `DOM.getOuterHTML`.
3. **NO `page.click()` or `page.type()`:** Never use CDP input commands. They lack hardware entropy.
4. **NO White Noise:** Do not use `random.uniform` for movement. All motor noise must be **Pink Noise ()** or correlated brownian motion.
5. **NO WebRTC Blocking:** Local IP leakage is required for residential trust scores.
6. **NO Session Churn:** Do not close/reopen the browser per request. Maintain one long-lived session.

---

## 3. Technology Stack & Dependencies

| Component | Technology | Rationale |
| --- | --- | --- |
| **Driver** | `nodriver` | Connects via Chrome Debugging Protocol (CDP) without the `navigator.webdriver` flag. |
| **Input Physics** | `pyautogui` + `numpy` | Generates "Trusted" events using Quintic Polynomials and Pink Noise. |
| **API Server** | `FastAPI` + `Uvicorn` | Manages the HTTP interface and Request Queue (Single-thread lock). |
| **Parsing** | `BeautifulSoup4` | Parses HTML offline to avoid JS detection vectors. |
| **System** | `pyvda` (Win) / `wmctrl` (Linux) | Manages window visibility/focus on Virtual Desktops. |
| **Clipboard** | `pyperclip` | Handles long-context injection safely. |

---

## 4. Module Architecture

### 4.1. Directory Structure

```text
ghost_shim/
├── main.py                 # FastAPI entry point & Queue Manager
├── config.py               # Paths (Shadow Profile), Offsets, Thresholds
├── core/
│   ├── driver.py           # nodriver lifecycle, CDP hardening
│   ├── neuromotor.py       # Mouse/Keyboard physics engine
│   ├── observer.py         # Passive DOM scraping & State monitoring
│   └── safety.py           # Dead Man's Switch, Permission gating
└── actions/
    ├── interaction.py      # High-level logic (Smart Paste, Stream Chasing)
    └── window.py           # Virtual Desktop / Window Focus logic

```

### 4.2. Detailed Module Specifications

#### **A. `core/driver.py` (The Stealth Layer)**

* **Shadow Profile Strategy:**
* **Goal:** Use the user's real cookies/trust tokens without locking their daily browser.
* **Logic:** On boot, copy the authenticated Chrome `User Data/Default` directory to `~/.ghost-profile`. Exclude heavy folders like `Cache` and `Code Cache`.


* **The "Silence" Protocol:**
* Immediately upon connection, disable "noisy" CDP domains to prevent V8 serialization lag:
```python
await page.send(cdp.runtime.disable())
await page.send(cdp.log.disable())
await page.send(cdp.debugger.disable())

```




* **Permission Hardening:**
* Pre-grant `clipboardReadWrite` and `notifications` via CDP `Browser.grantPermissions` to suppress native popups.



#### **B. `core/neuromotor.py` (The Physics Engine)**

* **Class `NeuromotorMouse`:**
* **Trajectory:** Implement **Minimum Jerk Trajectory** using a Quintic Polynomial:


* **Entropy:** Inject **Pink Noise ()**. Generate white noise  FFT  Filter ()  Inverse FFT. Scale amplitude by current velocity.
* **Targeting:** Never click the exact center. Target a Gaussian point within the inner 50% of the element's bounding box.


* **Class `CognitiveTyper`:**
* **N-Key Rollover:** Use `asyncio` to overlap key presses (press Next before releasing Current).
* **Geometric Latency:** Calculate delay based on physical distance between keys on the QWERTY layout.



#### **C. `actions/interaction.py` (Behavioral Logic)**

* **Hybrid Input Gate:**
* **IF** `len(prompt) < 300`: Use `CognitiveTyper`.
* **IF** `len(prompt) >= 300`: Use **Smart Paste**.
1. Save OS Clipboard.
2. Load Prompt.
3. Simulate `Ctrl+V` (Hardware Keys).
4. Restore OS Clipboard.




* **Inertial Scrolling:**
* While "Stop Generating" is visible, trigger scroll events that decay in frequency (simulating a mouse wheel flick) to keep the latest text in view.


* **Incidental Hovers:**
* Pathfinding to the "Send" button must purposefully intersect other clickable elements (sidebar items) to trigger natural `mouseenter` events.



#### **D. `core/observer.py` (Passive Extraction)**

* **Silent Read:**
* Use `nodriver` to select the chat container node.
* Call `get_content()` (CDP `DOM.getOuterHTML`).
* Pass the raw HTML string to `BeautifulSoup` for parsing.
* **Benefit:** Zero JS execution on the target page.



#### **E. `core/safety.py` (OpSec)**

* **Dead Man's Switch:**
* Monitor URL/DOM for keywords: `challenge`, `arkose`, `turnstile`.
* **Trigger:** If found, pause automation, emit system beep (`\a`), and wait for manual human resolution.



---

## 5. Implementation Scaffolding (Python Interfaces)

Use these interfaces as the blueprint for the implementation.

```python
# core/neuromotor.py
class NeuromotorMouse:
    def _quintic_polynomial(self, start: float, end: float, t: float) -> float:
        """Calculates position at time t using 5th order polynomial."""
        pass

    def _generate_pink_noise(self, samples: int) -> np.ndarray:
        """Generates 1/f noise via FFT."""
        pass

    async def move_to(self, target_x: int, target_y: int):
        """Executes human-like movement with noise injection."""
        pass

# core/observer.py
class SilentExtractor:
    async def get_response(self, page: Tab) -> str:
        """
        Extracts text without executing JS.
        1. Wait for 'stop_generating' to vanish.
        2. html = await node.get_content()
        3. return BeautifulSoup(html).text
        """
        pass

```

---

## 6. Deployment Notes

* **Coordinate Calibration:** The system must calculate `BROWSER_CHROME_Y_OFFSET` (height of URL bar/tabs) on startup to accurately map CDP Viewport coordinates to PyAutoGUI Screen coordinates.
* **Virtual Desktop:** On Windows, use `pyvda` to move the browser to Desktop #2 immediately after launch to keep the user's primary workspace clear.