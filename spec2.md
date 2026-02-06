**The Stack:** `Python` + `nodriver` (for state) + `PyAutoGUI` (for input).

### Implementation Architecture

This project is to simulate usage of a browser on a staging version of my app to perform user flows and infer UX characteristics using embedded user monitoring software

1. **Control (Nodriver):** Use `nodriver` to launch the browser, navigate to an aribtrary webpage, and *read* the DOM
2. **Action (OS-Level):** Do **not** use `await page.select(...).send_keys(...)`. Instead, calculate the element's screen coordinates and use `pyautogui` to physically move the mouse and type. This generates **Hardware Interrupts**, creating truly "Trusted" events so our UX recording software (embedded in the test website) picks up the interaction.

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
    
    # Launch HEADED.
    browser = await uc.start(
        user_data_dir=SHIM_PROFILE,
        headless=False 
    )
    
    page = await browser.get("https://localhost:6767")
    
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
3. **Rate Limit.** Limit your local API to human speeds (e.g., 1 prompt/minute).


### 1. Runtime and Log domain setup (Code Implementation)

By default, most automation tools enable the `Runtime` and `Log` domains to print console messages to your terminal. **This is a trap.** If `Runtime.enable` is active, the V8 engine has to serialize every console object, creating measurable lag that is not needed and unwanted.

You must manually disable these domains immediately after the connection is established.

```python
import nodriver as uc

async def stealth_init(page):
    """
    Applies protocol hardening to silence 'noisy' CDP domains 
    that cause V8 serialization lag.
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
* **Why:** This forces the `Runtime` domain to re-enable implicitly to execute your JS. 


* **✅ The Safe Zone: `DOM.describeNode**`
* Use `await page.select("selector")` or `page.find()`.
* **Why:** `nodriver` implements these using the `DOM` domain, which queries the browser's render tree directly which is more performant.



### 3. Browser Input Strategy

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
    
    page = await browser.get("http://localhost:6767")
    await stealth_init(page) # Apply hardening

    # Wait safely using DOM domain
    await page.wait_for("textarea[id='prompt-textarea']")
    
    # Execute Hybrid Input
    await human_interact(page, "textarea[id='prompt-textarea']", "Hello world")

if __name__ == "__main__":
    uc.loop().run_until_complete(main())

```

### Summary of Approach

1. Keep `Runtime`, `Log`, and `Debugger` domains disabled. If we need place debug logs, use `print()` in Python, not `console.log` in the browser.
2. Never use `page.click()` or `page.send_keys()`.
3. If coordinate math gets messy (due to varying window borders), we can possibly use `pyautogui.locateOnScreen('reference_image.png')` 
4. *Single Session:* Do not spin up a new browser for every flow test. We can use the same browser for each


