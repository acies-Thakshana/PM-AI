"""Shortcut: ``python local/run_ask.py "What is EMEA FRT?" [--domain service_ops]``."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from local.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["ask", *sys.argv[1:]]))
