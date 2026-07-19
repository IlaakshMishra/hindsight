"""pytest config for server/tests.

`server/` has no package (`__init__.py`) — `main.py` is a flat script and
Task 1 deliberately kept it that way. To let test modules do plain
`import schema` / `import scrub` regardless of the directory pytest was
invoked from, put `server/` (this file's parent) on sys.path once, here.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SERVER_DIR = Path(__file__).resolve().parent.parent
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))
