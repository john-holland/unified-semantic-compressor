#!/usr/bin/env python3
r"""
Standalone runner for query_db. Use when the package is not installed.
Adds the repo root to PYTHONPATH and invokes the CLI.

Usage (from any directory):
  python path/to/unified-semantic-compressor/scripts/query_db.py --db path/to/continuum.db --table library_documents

Or with PYTHONPATH set:
  set PYTHONPATH=path\to\unified-semantic-compressor
  python -m unified_semantic_archiver.cli.query_db --db path/to/continuum.db --table library_documents
"""
from __future__ import annotations

import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from unified_semantic_archiver.cli.query_db import main

if __name__ == "__main__":
    sys.exit(main())
