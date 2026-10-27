#!/usr/bin/env python3
"""Eluno POS — Single-command entry point.

Usage:
    python run_pos.py demo          # Runs full end-to-end bill, refund, and day-end flow
    python run_pos.py --help        # View all available CLI subcommands
    python run_pos.py test          # Runs all unit and integration test suites
"""

import sys
import unittest

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from pos.cli import main

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Run test suite
        loader = unittest.TestLoader()
        suite = loader.discover("tests")
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        sys.exit(0 if result.wasSuccessful() else 1)
    else:
        main()
