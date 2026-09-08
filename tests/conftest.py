from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from unittest.mock import MagicMock

try:
    import sentence_transformers  # noqa: F401
except ImportError:
    sys.modules["sentence_transformers"] = MagicMock()

