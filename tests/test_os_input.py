import random

from gpt_web_driver.os_input import MouseProfile, OsInput, TypingProfile


class FakePyAutoGUI:
    def __init__(self):
        self.calls = []

    def moveTo(self, x, y, duration):  # noqa: N802
        self.calls.append(("moveTo", x, y, duration))

    def click(self):
        self.calls.append(("click",))

    def write(self, char):
        self.calls.append(("write", char))

    def press(self, key):
        self.calls.append(("press", key))


def test_os_input_uses_injected_pyautogui():
    pag = FakePyAutoGUI()
    rng = random.Random(0)
    os_in = OsInput(dry_run=False, pyautogui_module=pag, rng=rng)

    os_in.move_to(10, 20, profile=MouseProfile(min_move_duration_s=0.2, max_move_duration_s=0.2))
    os_in.click()
    os_in.write_char("a")
    os_in.press("enter")

    assert pag.calls[0] == ("moveTo", 10, 20, 0.2)
    assert pag.calls[1:] == [("click",), ("write", "a"), ("press", "enter")]


def test_human_type_uses_profile_and_writes_chars():
    pag = FakePyAutoGUI()
    os_in = OsInput(dry_run=False, pyautogui_module=pag, rng=random.Random(0))
    import asyncio

    asyncio.run(os_in.human_type("hi", profile=TypingProfile(min_delay_s=0.0, max_delay_s=0.0)))
    assert ("write", "h") in pag.calls
    assert ("write", "i") in pag.calls
