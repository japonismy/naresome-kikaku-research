# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, cwd=HERE, text=True, encoding="utf-8", errors="replace", capture_output=True)
    if proc.returncode:
        raise SystemExit((proc.stderr or proc.stdout).strip())
    if proc.stdout.strip():
        print(proc.stdout.strip())


def main() -> int:
    run(["uv", "run", "--with", "openpyxl", "python", "build_observed_archive_supplement.py"])
    run(["uv", "run", "--with", "google-cloud-bigquery", "python", "generate_portal_data_bq.py"])
    run(["git", "add", "."])
    status = subprocess.run(["git", "status", "--short"], cwd=HERE, text=True, encoding="utf-8", errors="replace", capture_output=True).stdout.strip()
    if not status:
        print("No changes to deploy.")
        return 0
    run(["git", "commit", "-m", "Update naresome research data"])
    run(["git", "push"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
