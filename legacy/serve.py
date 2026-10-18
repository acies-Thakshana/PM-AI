"""Container entry point. SageMaker starts the image with the argument ``serve``."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("AIBI_PROJECT_ROOT", str(ROOT))
os.environ.setdefault("AIBI_LLM_MODE", "local")
for item in (str(ROOT / "lib" / "python"), str(ROOT)):
    if item not in sys.path:
        sys.path.insert(0, item)

from sagemaker_app.server import main

if __name__ == "__main__":
    main()
