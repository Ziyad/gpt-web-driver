from pathlib import Path


def test_no_forbidden_driver_interaction_strings():
    base = Path(__file__).resolve().parents[1] / "src" / "gpt_web_driver"
    forbidden = [
        "page.click",
        "send_keys",
        "page.send_keys",
        "page.evaluate",
        "Runtime.evaluate",
    ]

    for py in base.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for f in forbidden:
            assert f not in text, f"forbidden string {f!r} found in {py}"

