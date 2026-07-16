# -*- coding: utf-8 -*-
from __future__ import annotations

import os
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
    run(["uv", "run", "--python", "3.12", "--with", "openpyxl", "python", "build_observed_archive_supplement.py"])
    refresh_cmd = ["uv", "run", "--python", "3.12", "python", "refresh_youtube_current_stats.py"]
    if not os.environ.get("YOUTUBE_API_KEY"):
        refresh_cmd[4:4] = ["--with", "google-cloud-secret-manager"]
    run(refresh_cmd)
    run(["uv", "run", "--python", "3.12", "--with", "google-cloud-bigquery", "python", "generate_portal_data_bq.py"])
    run([
        "git", "add", "data/videos.js", "reports/build_summary.json",
        "reports/content_scope.csv", "data_sources/observed_archive_supplement.csv",
        "data_sources/youtube_current_stats.csv",
    ])
    status = subprocess.run(["git", "status", "--short"], cwd=HERE, text=True, encoding="utf-8", errors="replace", capture_output=True).stdout.strip()
    if not status:
        print("No changes to deploy.")
        return 0
    run(["git", "commit", "-m", "Update naresome research data"])
    run(["git", "push"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
