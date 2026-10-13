"""Dataiku recipe: validate an AI4BI onboarding package. Fail closed."""

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
    from aibi.factory.validate import OnboardingError, validate_domain

    try:
        pkg = validate_domain(domain)
        payload = {
            "status": "ok",
            "domain": domain,
            "entities": [e.logical_entity for e in pkg.entities],
            "joins": [j.id for j in pkg.joins],
        }
    except OnboardingError as exc:
        payload = {"status": "failed", "domain": domain, "error": str(exc)}
        print(json.dumps(payload, indent=2))
        raise
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
