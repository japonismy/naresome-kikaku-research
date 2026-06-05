# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
from pathlib import Path

from google.cloud import bigquery


PROJECT_ID = "rugged-destiny-408613"
DATASET = "naresome_all"
HERE = Path(__file__).resolve().parent
REPORT_DIR = HERE / "reports"


def main() -> int:
    client = bigquery.Client(project=PROJECT_ID)
    thumb_rows = load_csv(REPORT_DIR / "gcs_thumbnail_assets_manifest.csv")
    script_rows = load_csv(REPORT_DIR / "gcs_script_csv_manifest.csv")
    load_thumbnail_assets(client, thumb_rows)
    update_script_assets(client, script_rows)
    print(json.dumps({"thumbnail_assets": len(thumb_rows), "script_csv_assets": len(script_rows)}, ensure_ascii=False))
    return 0


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_thumbnail_assets(client: bigquery.Client, rows: list[dict[str, str]]) -> None:
    table_id = f"{PROJECT_ID}.{DATASET}.thumbnail_assets"
    payload = [
        {
            "video_id": r.get("video_id", ""),
            "gcs_uri": r.get("gcs_uri", ""),
            "bytes": int(r.get("bytes") or 0),
            "error": r.get("error", ""),
        }
        for r in rows
        if r.get("video_id")
    ]
    job_config = bigquery.LoadJobConfig(
        schema=[
            bigquery.SchemaField("video_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("gcs_uri", "STRING"),
            bigquery.SchemaField("bytes", "INTEGER"),
            bigquery.SchemaField("error", "STRING"),
        ],
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    client.load_table_from_json(payload, table_id, job_config=job_config).result()


def update_script_assets(client: bigquery.Client, rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    tmp_table = f"{PROJECT_ID}.{DATASET}._script_asset_gcs_updates"
    payload = [
        {
            "video_id": r.get("video_id", ""),
            "gcs_csv_uri": r.get("gcs_uri", ""),
            "bytes": int(r.get("bytes") or 0),
        }
        for r in rows
        if r.get("video_id") and r.get("gcs_uri")
    ]
    job_config = bigquery.LoadJobConfig(
        schema=[
            bigquery.SchemaField("video_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("gcs_csv_uri", "STRING"),
            bigquery.SchemaField("bytes", "INTEGER"),
        ],
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    client.load_table_from_json(payload, tmp_table, job_config=job_config).result()
    client.query(
        f"""
        UPDATE `{PROJECT_ID}.{DATASET}.script_assets` s
        SET gcs_csv_uri = u.gcs_csv_uri
        FROM `{tmp_table}` u
        WHERE s.video_id = u.video_id
        """
    ).result()


if __name__ == "__main__":
    raise SystemExit(main())
