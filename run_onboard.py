"""CLI for the AI4BI factory: validate, compile, harvest, ask."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aibi.factory.catalog_executor import execute_catalog_metric
from aibi.factory.compiler import compile_domain
from aibi.factory.harvest import harvest_summary
from aibi.factory.loader import list_domains, load_domain
from aibi.factory.validate import OnboardingError, validate_domain
from aibi.llmkg.engine import ask_with_graph


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def main() -> int:
    parser = argparse.ArgumentParser(description="AI4BI onboarding factory")
    parser.add_argument(
        "command",
        choices=["list", "validate", "compile", "harvest", "ask", "ask-catalog", "eval", "experience"],
    )
    parser.add_argument("--domain", default="service_ops")
    parser.add_argument("--question", default="")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--level", default="")
    args = parser.parse_args()

    if args.command == "list":
        _print({"domains": list_domains()})
        return 0

    try:
        if args.command == "validate":
            pkg = validate_domain(args.domain)
            _print(
                {
                    "domain": args.domain,
                    "status": "ok",
                    "entities": [e.logical_entity for e in pkg.entities],
                    "joins": [j.id for j in pkg.joins],
                    "kpis": [k.family for k in pkg.dictionary.kpis],
                    "custom_objects": [
                        e.source_object for e in pkg.entities if e.is_custom_object
                    ],
                }
            )
            return 0
        if args.command == "compile":
            pkg = validate_domain(args.domain)
            metrics = compile_domain(pkg, activate=args.activate)
            _print(
                {
                    "domain": args.domain,
                    "proposed_metrics": [m.model_dump() for m in metrics],
                    "joins_invented": 0,
                    "status": "proposed" if not args.activate else "certified",
                }
            )
            return 0
        if args.command == "harvest":
            pkg = load_domain(args.domain)
            if not pkg.harvest:
                print("No harvest.yaml in this domain")
                return 1
            _print(harvest_summary(pkg.harvest))
            return 0
        if args.command == "eval":
            from aibi.experience.eval import run_excel_escape

            report = run_excel_escape(args.domain)
            _print(report)
            return 0 if report["failed"] == 0 else 1
        if args.command == "experience":
            from aibi.experience.drill import load_drills, project_only_config
            from aibi.experience.visuals import load_bindings, render_visual, validate_visual_bindings
            from aibi.settings import load_yaml
            from aibi.settings import PROJECT_ROOT

            errors = validate_visual_bindings(args.domain)
            if errors:
                _print({"status": "invalid", "errors": errors})
                return 2
            bindings = [render_visual(b) for b in load_bindings(args.domain)]
            drills = project_only_config(load_drills(args.domain))
            platform = load_yaml(PROJECT_ROOT / "config" / "platform.yaml")
            _print(
                {
                    "hybrid": [
                        "dashboard_orientation",
                        "copilot_exploration",
                        "drill_investigation",
                        "visuals_consumption",
                    ],
                    "visuals": bindings,
                    "drills": drills,
                    "platform": platform,
                }
            )
            return 0
        if args.command == "ask-catalog":
            if not args.question:
                print("Provide --question")
                return 1
            result = execute_catalog_metric(args.question, domain=args.domain)
            if not result:
                print("No certified catalog metric matched")
                return 1
            _print(result)
            return 0
        if args.command == "ask":
            if not args.question:
                print("Provide --question")
                return 1
            result = ask_with_graph(args.question, domain=args.domain)
            _print(result)
            return 0
    except OnboardingError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
