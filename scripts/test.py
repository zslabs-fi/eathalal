#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest>=8", "requests>=2.31", "Pillow>=10.0"]
# ///
"""Run the test suite in a temporary environment:

    pipx run scripts/test.py        # extra arguments are passed to pytest, e.g. -k city
"""
import sys
from pathlib import Path

import pytest

tests = Path(__file__).resolve().parent.parent / "tests"
sys.exit(pytest.main(["-q", str(tests), *sys.argv[1:]]))
