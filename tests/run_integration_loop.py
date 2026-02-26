#!/usr/bin/env python
"""
Run integration tests in a loop for up to 30 minutes.
Exits on first failure (so we can fix) or when time expires.

Interactive retry: use --retry to prompt after each failure, fix, press Enter to continue.
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("USC_INTEGRATION_OUTPUT", "1")

ROOT = Path(__file__).resolve().parent.parent

def main() -> None:
    p = argparse.ArgumentParser(description="Run integration tests in loop")
    p.add_argument("--retry", action="store_true", help="On failure, prompt to fix and retry (for continuous improvement)")
    p.add_argument("--max-minutes", type=float, default=30, help="Max loop duration in minutes (default 30)")
    args = p.parse_args()

    START = time.monotonic()
    MAX_SECONDS = int(args.max_minutes * 60)
    RUN = 0

    while (time.monotonic() - START) < MAX_SECONDS:
        RUN += 1
        elapsed = int(time.monotonic() - START)
        print(f"\n--- Run {RUN} (elapsed {elapsed}s / {MAX_SECONDS}s) ---", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-m", "integration", "-v", "--tb=short"],
            cwd=ROOT,
            env=os.environ,
        )
        if result.returncode != 0:
            print(f"\nFAILED on run {RUN} after {elapsed}s", flush=True)
            if args.retry:
                try:
                    input("\nFix the issue, then press Enter to retry (Ctrl+C to exit)... ")
                except KeyboardInterrupt:
                    sys.exit(result.returncode)
            else:
                sys.exit(result.returncode)
        remaining = MAX_SECONDS - (time.monotonic() - START)
        if remaining < 60:
            break
        print(f"Passed. {int(remaining)}s remaining.", flush=True)

    print(f"\nAll {RUN} runs passed in {int(time.monotonic() - START)}s.", flush=True)


if __name__ == "__main__":
    main()
