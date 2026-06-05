# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
from pathlib import Path

from google.cloud import bigquery


PROJECT_ID = "rugged-destiny-408613"
DATASET = "naresome_all"
TABLE = "script_assets"
HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "reports" / "script_assets_manifest.csv"


def main() -> int:
    if not MANIFEST.exists():
        raise SystemExit("Run inventory_script_assets.py first.")

    rows = load_rows()
    client = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.{DATASET}.{TABLE}"
    job_config = bigquery.LoadJobConfig(
        schema=[
            bigquery.SchemaField("video_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("channel", "STRING"),
            bigquery.SchemaField("title", "STRING"),
            bigquery.SchemaField("view_count", "INTEGER"),
            bigquery.SchemaField("published_at", "STRING"),
            bigquery.SchemaField("asset_count", "INTEGER"),
            bigquery.SchemaField("best_type", "STRING"),
            bigquery.SchemaField("best_local_path", "STRING"),
            bigquery.SchemaField("best_bytes", "INTEGER"),
            bigquery.SchemaField("local_csv_asset", "STRING"),
            bigquery.SchemaField("gcs_csv_uri", "STRING"),
            bigquery.SchemaField("public_csv_url", "STRING"),
        ],
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    client.load_table_from_json(rows, table_id, job_config=job_config).result()
    print(json.dumps({"table": table_id, "rows": len(rows)}, ensure_ascii=False))
    return 0


def load_rows() -> list[dict[str, object]]:
    with MANIFEST.open("r", newline="", encoding="utf-8-sig") as f:
        rows = []
        for row in csv.DictReader(f):
            rows.append(
                {
                    "video_id": row.get("video_id", ""),
                    "channel": row.get("channel", ""),
                    "title": row.get("title", ""),
                    "view_count": int(row.get("view_count") or 0),
                    "published_at": row.get("published_at", ""),
                    "asset_count": int(row.get("asset_count") or 0),
                    "best_type": row.get("best_type", ""),
                    "best_local_path": row.get("best_local_path", ""),
                    "best_bytes": int(row.get("best_bytes") or 0),
                    "local_csv_asset": row.get("local_csv_asset", ""),
                    "gcs_csv_uri": "",
                    "public_csv_url": "",
                }
            )
        return rows


if __name__ == "__main__":
    raise SystemExit(main())
