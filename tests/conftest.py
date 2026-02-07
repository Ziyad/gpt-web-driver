import sys
from pathlib import Path

# Make the src-layout package importable for test runs without requiring users
# to set PYTHONPATH or install the package.
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

