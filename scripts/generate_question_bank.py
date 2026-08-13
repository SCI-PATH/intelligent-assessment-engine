"""Alias entrypoint for chapter-level question bank generation."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.generate_bank import main


if __name__ == "__main__":
    raise SystemExit(main())
