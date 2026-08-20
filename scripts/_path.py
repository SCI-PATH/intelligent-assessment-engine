"""Make ``iae`` importable without an editable install.

``python -m scripts.<name>`` does not put ``src/`` on ``sys.path``. This
helper inserts the repo root and ``src/`` when they are missing.
"""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_src_on_path() -> None:
    root = Path(__file__).resolve().parents[1]
    for candidate in (root, root / "src"):
        text = str(candidate)
        if text not in sys.path:
            sys.path.insert(0, text)


ensure_src_on_path()
