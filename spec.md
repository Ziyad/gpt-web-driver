# Project Specification

**(`nodriver`), but with a hybrid input architecture.**

As of 2026, the "cat-and-mouse" game of browser fingerprinting has shifted. The `puppeteer-extra-plugin-stealth` approach—which relies on injecting JavaScript to monkey-patch leaks like `navigator.webdriver`—is now considered "loud" legacy technology. Modern anti-abuse systems (Arkose Labs v4, Cloudflare Turnstile) use heuristic analysis to detect the *patches themselves* (e.g., by checking for Proxy traps on `navigator` properties or inconsistencies in `toString()` outputs).

`nodriver` (the successor to `undetected-chromedriver`) is superior because it is **architecturally** stealthy. It launches the browser without the standard WebDriver binary flags that trigger the "Automation Controlled" status in the first place, removing the need to "lie" to the DOM.

However, simply switching libraries is not enough. To survive long-term, you must address the **CDP (Chrome DevTools Protocol) Event Leak**, which identifies bots by the "synthetic" nature of their input events.

---

## 1. Detection Vectors: The "CDP Leak"

You asked how likely a web host is to detect CDP usage if you aren't using the `navigator.webdriver` flag. The answer is **High**, unless you mitigate specific side effects.

* **The `Runtime.enable` Trap:** Standard automation tools (Puppeteer/Playwright) automatically enable the `Runtime` domain to manage execution contexts. Historically, this created detectable side effects in the V8 engine (e.g., `console.debug` serialization lags). While V8 patched the most obvious of these, sophisticated scripts still monitor for timing discrepancies caused by the debugger's event loop.
* **Synthetic vs. Trusted Events (The Smoking Gun):** This is the primary detection vector for 2026.
* **CDP Input:** When you use `page.type()` or `page.click()`, Chrome generates an event where the `isTrusted` property is technically `true` (mostly), but the event lacks OS-level entropy (pressure, precise timestamp jitter, and trajectory). Arkose Labs correlates these "perfect" inputs with your session; a linear mouse movement followed by 100ms inter-key typing is an immediate red flag.
* **Coordinate Mismatches:** Cloudflare Turnstile specifically checks if click coordinates align with the *viewport* vs. the *iframe*. CDP-generated clicks often fail this coordinate transformation check, whereas real mouse hardware interrupts do not.


## 2. Tech decision

**Verdict:** `nodriver` acts as a "parasite" on a legitimate browser process rather than a "controller" of a test browser, making it significantly harder to fingerprint.

## 3. Persistence Strategy: The "Shadow Profile"

Do **not** spin up a new browser for every request. That is behaviorally anomalous. Conversely, do not point `nodriver` directly at your *running* daily-driver profile, or you will hit `SingletonLock` errors that crash your browser.

**The "Shadow Profile" Strategy:**

1. **One-Time Clone:** Write a script to copy your authenticated Chrome User Data directory (cookies, local storage, Arkose trust tokens) to a separate `~/chrome-shim-profile` folder.
2. **Long-Lived Session:** Launch the browser *once* when your API server starts. Keep the WebSocket connection open.
3. **Refresh Logic:** If the session expires, the shim should alert you to log in manually in the headed window, then re-save the profile.

## 4. Final Recommendation: The "Hybrid" Stack

To maximize account survival, you must separate **Control** (Navigation/Reading) from **Action** (Typing).

**The Stack:** `Python` + `nodriver` (for state) + `PyAutoGUI` (for input).

### Implementation Architecture

1. **Control (Nodriver):** Use `nodriver` to launch the browser, navigate to ChatGPT, and *read* the DOM (scrape the response). Reading via CDP is passive and generally undetectable.
2. **Action (OS-Level):** Do **not** use `await page.select(...).send_keys(...)`. Instead, calculate the element's screen coordinates and use `pyautogui` to physically move the mouse and type. This generates **Hardware Interrupts**, creating truly "Trusted" events that bypass behavioral biometrics.

### Proof-of-Concept (Python 3.12+)

```python
import asyncio
import nodriver as uc
import pyautogui
import random
import os
import shutil

# Define paths
REAL_PROFILE = os.path.expanduser("~/Library/Application Support/Google/Chrome/Default")
SHIM_PROFILE = os.path.expanduser("~/chrome-shim-profile")

async def ensure_profile():
    """Clones real profile to shim profile to capture Auth/Cookies without file locks."""
    if not os.path.exists(SHIM_PROFILE):
        print("Cloning profile for first run...")
        # Exclude massive cache files to speed up copy
        shutil.copytree(REAL_PROFILE, SHIM_PROFILE, ignore=shutil.ignore_patterns("Cache*", "Code Cache"))

async def human_type(text):
    """Types with human-like latency and jitter."""
    for char in text:
        pyautogui.write(char)
        # Random delay between 50ms and 150ms
        await asyncio.sleep(random.uniform(0.05, 0.15))

async def main_loop():
    await ensure_profile()
    
    # Launch HEADED. Headless is a massive flag for Cloudflare.
    browser = await uc.start(
        user_data_dir=SHIM_PROFILE,
        headless=False 
    )
    
    page = await browser.get("https://chatgpt.com")
    
    # Wait for the "Stop Generating" button to ensure readiness (passive check)
    await page.wait_for_selector("textarea[id='prompt-textarea']", timeout=20)
    
    # --- HYBRID INPUT STRATEGY ---
    # 1. Find coordinates via CDP
    textarea = await page.select("textarea[id='prompt-textarea']")
    box = await textarea.bounding_box()
    
    # 2. Bring window to front (OS command)
    browser.bring_to_front()
    
    # 3. Click and Type via OS (Bypasses CDP detection)
    # Add random offset to click within the box, not dead center
    pyautogui.click(x=box.x + 15, y=box.y + 15)
    await human_type("Hello, this is a test prompt.")
    pyautogui.press('enter')
    
    # 4. Scrape response passively
    # ... wait for response logic ...

if __name__ == "__main__":
    uc.loop().run_until_complete(main_loop())

```

### Checklist

1. **Switch to Python.** The tooling for OS-level input (`pyautogui`) and "driverless" automation is vastly superior in Python.
2. **Run Headed.** Always. Minimize the window if you must, but do not use `--headless`.
3. **Rate Limit.** Limit your local API to human speeds (e.g., 1 prompt/minute). Behavioral bans are triggered by volume, not just software signatures.


To prevent CDP detection while using `nodriver`, you must understand that the detection isn't usually triggered by the *presence* of the protocol (browser engineers use it daily), but by the **noise** it generates.

Anti-abuse systems like Arkose Labs and Cloudflare Turnstile fingerprint the CDP by listening for **side effects** in the V8 engine. Specifically, they measure the "serialization latency" (how long it takes the browser to package data to send to your script) and look for "synthetic" input signatures.

Here is the technical strategy to harden `nodriver` and achieve **Radio Silence**.

### 1. The "Silence" Protocol (Code Implementation)

By default, most automation tools enable the `Runtime` and `Log` domains to print console messages to your terminal. **This is a trap.** If `Runtime.enable` is active, the V8 engine has to serialize every console object, creating measurable lag that flags you as a bot.

You must manually disable these domains immediately after the connection is established.

```python
import nodriver as uc

async def stealth_init(page):
    """
    Applies protocol hardening to silence 'chatty' CDP domains 
    that cause V8 serialization latency.
    """
    try:
        # 1. Disable Reporting Domains
        # We want to be "deaf" to the console. This prevents the anti-bot 
        # from spamming complex objects to measure your parsing lag.
        await page.send(uc.cdp.runtime.disable())
        await page.send(uc.cdp.log.disable())
        await page.send(uc.cdp.debugger.disable())
        
        # 2. Defuse "Debugger" Traps
        # Some sites run "debugger;" in a loop. If a devtools client is attached,
        # execution pauses, and their heartbeat script detects the freeze.
        # We tell CDP to ignore all breakpoints.
        await page.send(uc.cdp.debugger.set_breakpoints_active(active=False))
    except Exception:
        # Ignore errors if domains are already disabled
        pass

```

### 2. The "Read-Only" Doctrine

You must strictly separate your interaction into **Passive (Reading)** and **Active (Writing)**.

* **❌ The Danger Zone: `Runtime.evaluate**`
* Avoid using `await page.evaluate("document.querySelector(...)")`.
* **Why:** This forces the `Runtime` domain to re-enable implicitly to execute your JS. It creates a new execution context and stack trace that can be sniffed.


* **✅ The Safe Zone: `DOM.describeNode**`
* Use `await page.select("selector")` or `page.find()`.
* **Why:** `nodriver` implements these using the `DOM` domain, which queries the browser's render tree directly without executing JavaScript in the page context. This is invisible to the page's JS.



### 3. The "Air-Gapped" Input Strategy

The single biggest "tell" is using CDP for input. `Input.dispatchMouseEvent` creates events with `isTrusted: true`, but they lack **hardware entropy** (pressure, sub-pixel jitter, and driver-level interrupts).

**You must use OS-level input (`pyautogui`) for all clicking and typing.**

The challenge is translating **CDP Coordinates** (Viewport) to **OS Coordinates** (Screen).

```python
import asyncio
import random
import nodriver as uc
import pyautogui

# Calibration: Height of your browser's top bar (URL + Tabs) in pixels.
# You must adjust this for your OS/Theme.
BROWSER_CHROME_OFFSET_Y = 80 
BROWSER_CHROME_OFFSET_X = 0

async def human_interact(page, selector, text=None):
    # 1. PASSIVE LOCATE (CDP)
    # Use CDP only to find *where* the element is.
    element = await page.select(selector)
    if not element:
        raise Exception("Element not found")

    # Get bounding box [x, y, width, height] relative to Viewport
    # Note: 'quads' usually returns [x1, y1, x2, y2...]
    quad = element.quads[0]
    viewport_x = (quad[0] + quad[2]) / 2
    viewport_y = (quad[1] + quad[5]) / 2

    # 2. CALIBRATE (Viewport -> Screen)
    # Ensure browser is maximized for this math to work reliably
    screen_x = viewport_x + BROWSER_CHROME_OFFSET_X
    screen_y = viewport_y + BROWSER_CHROME_OFFSET_Y

    # 3. NOISE INJECTION
    # Robots click the exact float center. Humans miss slightly.
    final_x = screen_x + random.randint(-12, 12)
    final_y = screen_y + random.randint(-5, 5)

    # 4. ACTIVE INPUT (OS Level)
    # Move mouse with duration > 0 to generate trajectory data
    pyautogui.moveTo(final_x, final_y, duration=random.uniform(0.2, 0.6))
    pyautogui.click()
    
    if text:
        # Type with inconsistent latency (simulates cognitive pauses)
        await asyncio.sleep(0.5) # Wait for focus
        for char in text:
            pyautogui.write(char)
            await asyncio.sleep(random.uniform(0.04, 0.12))
        pyautogui.press('enter')

async def main():
    # HEADLESS=False is MANDATORY for PyAutoGUI
    browser = await uc.start(headless=False)
    browser.main_tab.maximize() # Standardize coordinates
    
    page = await browser.get("https://chatgpt.com")
    await stealth_init(page) # Apply hardening

    # Wait safely using DOM domain
    await page.wait_for("textarea[id='prompt-textarea']")
    
    # Execute Hybrid Input
    await human_interact(page, "textarea[id='prompt-textarea']", "Hello world")

if __name__ == "__main__":
    uc.loop().run_until_complete(main())

```

### Summary of Tactics

1. **Deaf & Blind:** Keep `Runtime`, `Log`, and `Debugger` domains disabled. If you need to debug, use `print()` in Python, not `console.log` in the browser.
2. **No-Op Input:** Never use `page.click()` or `page.send_keys()`. These are the "loudest" CDP commands.
3. **Visual Fallback:** If coordinate math gets messy (due to varying window borders), use `pyautogui.locateOnScreen('reference_image.png')` to find the chat box visually. It is slower but 100% detached from CDP.
4. **Single Session:** Do not spin up a new browser for every API request. Launch it once, keep it open, and reuse the WebSocket connection. Behavioral analysis flags accounts that log in 50 times a day.


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