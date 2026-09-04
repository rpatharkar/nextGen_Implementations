#!/usr/bin/env python3
"""Restore a SQL Server .bak and export tables to Parquet and/or CSV.

This is the CLI for the Docker exporter in this folder (the Plattsburgh
mssql_bak_to_parquet tool). It does not use the old host-Python CSV path.

Usage:
  ./restore_bak_to_csv.py ./database.bak
  ./restore_bak_to_csv.py ./database.bak --format parquet
  ./restore_bak_to_csv.py ./database.bak --format csv
  ./restore_bak_to_csv.py ./database.bak --format both --out ./export
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXPORTER = ROOT / "mssql_bak_to_parquet.sh"


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def rewrite_legacy_flags(argv: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--keep-container":
            out.append("--keep-sqlserver")
            i += 1
            continue
        if arg == "--keep-db":
            print(
                "Note: --keep-db is ignored. Use --keep-sqlserver to keep the restored database.",
                file=sys.stderr,
            )
            i += 1
            continue
        out.append(arg)
        i += 1
    if "--format" not in out:
        out = ["--format", "csv", *out]
    return out


def main(argv: list[str]) -> int:
    if not EXPORTER.is_file():
        die(f"Missing exporter script: {EXPORTER}")
    if not os.access(EXPORTER, os.X_OK):
        die(f"Exporter is not executable: {EXPORTER}")
    args = rewrite_legacy_flags(argv)
    return subprocess.call(["bash", str(EXPORTER), *args])


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
