"""Dataiku recipe: compile proposed KPI formulae from the data dictionary.

Never invents joins. Writes proposed metric JSON for steward review.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> None:
    root = Path(os.environ.get("AIBI_PROJECT_ROOT") or Path(__file__).resolve().parents[2])
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    domain = os.environ.get("AIBI_DOMAIN", "service_ops")
    activate = os.environ.get("AIBI_ACTIVATE", "false").lower() in {"1", "true", "yes"}
    from aibi.factory.compiler import compile_domain
    from aibi.factory.validate import validate_domain

    pkg = validate_domain(domain)
    metrics = compile_domain(pkg, activate=activate)
    print(
        json.dumps(
            {
                "domain": domain,
                "joins_invented": 0,
                "metrics": [m.model_dump() for m in metrics],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
