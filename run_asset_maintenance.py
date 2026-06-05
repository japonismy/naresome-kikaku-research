# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
REQUIRED_ACCOUNT = "japonismy@gmail.com"
PROJECT = "rugged-destiny-408613"
BUCKET = "gs://senior-share-staging-570862915709"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-upload", action="store_true", help="Regenerate manifests and BQ data without GCS rsync.")
    ap.add_argument("--deploy", action="store_true", help="Commit and push page data after regeneration.")
    args = ap.parse_args()

    ensure_gcloud_account()
    run([sys.executable, "inventory_script_assets.py", "--export-csv-assets"])
    run([sys.executable, "prepare_gcs_assets.py"])

    if not args.skip_upload:
        run(["gcloud", "storage", "rsync", "script_csv_assets", f"{BUCKET}/naresome_script_csv", "--recursive"])
        run(["gcloud", "storage", "rsync", str(Path("gcs_upload_staging") / "naresome_thumbnails"), f"{BUCKET}/naresome_thumbnails", "--recursive"])

    run(["uv", "run", "--with", "google-cloud-bigquery", "python", "sync_script_assets_to_bq.py"])
    run(["uv", "run", "--with", "google-cloud-bigquery", "python", "sync_gcs_assets_to_bq.py"])
    run(["uv", "run", "--with", "google-cloud-bigquery", "python", "generate_portal_data_bq.py"])

    if args.deploy:
        run([sys.executable, "deploy_pages.py"])

    print(json.dumps({"ok": True, "uploaded": not args.skip_upload, "deployed": args.deploy}, ensure_ascii=False))
    return 0


def ensure_gcloud_account() -> None:
    account = output(["gcloud", "config", "get-value", "account"]).strip()
    project = output(["gcloud", "config", "get-value", "project"]).strip()
    if account != REQUIRED_ACCOUNT:
        run(["gcloud", "config", "set", "account", REQUIRED_ACCOUNT])
    if project != PROJECT:
        run(["gcloud", "config", "set", "project", PROJECT])


def output(cmd: list[str]) -> str:
    proc = subprocess.run(
        cmd,
        cwd=HERE,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        shell=(os.name == "nt"),
    )
    if proc.returncode:
        raise SystemExit((proc.stderr or proc.stdout).strip())
    return proc.stdout


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, cwd=HERE, text=True, encoding="utf-8", errors="replace", shell=(os.name == "nt"))
    if proc.returncode:
        raise SystemExit(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
