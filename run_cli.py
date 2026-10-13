"""Local CLI for Ask Business Data (no Streamlit required)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("AI_BI_NL2SQL_ROOT", r"C:\Users\BharadNa\dataiku-langgraph-nlq")

from aibi.ask_service import ask_business_data


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Ask Business Data CLI")
    parser.add_argument("question", nargs="?", help="Business question")
    parser.add_argument("--user", default="local.analyst")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    question = args.question
    if not question:
        question = input("Ask Business Data> ").strip()
    if not question:
        return 1

    result = ask_business_data(question, user_id=args.user)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"status: {result.get('status')}")
        if result.get("clarification"):
            print("clarification:", result["clarification"])
        if result.get("answer"):
            print(result["answer"])
        if result.get("sql_query"):
            print("\nSQL:\n", result["sql_query"])
        print("request_id:", result.get("request_id"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
