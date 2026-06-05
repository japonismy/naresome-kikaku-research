# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import shutil
import sqlite3
from pathlib import Path


HERE = Path(__file__).resolve().parent
VAULT = HERE.parents[2]
DB_PATH = VAULT / "馴れ初めシネマ" / "analysis" / "naresome_db.sqlite"
STAGING_DIR = HERE / "gcs_upload_staging"
THUMB_DIR = STAGING_DIR / "naresome_thumbnails"
REPORT_DIR = HERE / "reports"


def main() -> int:
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    target_ids = load_target_ids()
    thumb_rows = stage_thumbnails(target_ids)
    write_csv(REPORT_DIR / "gcs_thumbnail_assets_manifest.csv", thumb_rows)

    script_rows = []
    manifest = REPORT_DIR / "script_assets_manifest.csv"
    if manifest.exists():
        with manifest.open("r", newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("local_csv_asset"):
                    path = Path(row["local_csv_asset"])
                    if path.exists():
                        script_rows.append(
                            {
                                "video_id": row["video_id"],
                                "local_csv_asset": str(path),
                                "bytes": path.stat().st_size,
                                "gcs_uri": f"gs://senior-share-staging-570862915709/naresome_script_csv/{path.name}",
                            }
                        )
    write_csv(REPORT_DIR / "gcs_script_csv_manifest.csv", script_rows)

    summary = {
        "target_videos": len(target_ids),
        "thumbnails_staged": sum(1 for r in thumb_rows if r["local_path"]),
        "thumbnails_missing": sum(1 for r in thumb_rows if not r["local_path"]),
        "script_csv_assets": len(script_rows),
        "staging_dir": str(STAGING_DIR),
    }
    (REPORT_DIR / "gcs_assets_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def load_target_ids() -> set[str]:
    text = (HERE / "data" / "videos.js").read_text(encoding="utf-8")
    prefix = "window.VIDEO_DATA = "
    videos = json.loads(text[len(prefix) :].strip().rstrip(";"))
    return {v["video_id"] for v in videos}


def stage_thumbnails(target_ids: set[str]) -> list[dict[str, object]]:
    staged = existing_staged_thumbnails(target_ids)
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT video_id, thumbnail_local_path
            FROM videos
            WHERE thumbnail_local_path IS NOT NULL AND thumbnail_local_path != ''
            """
        ).fetchall()
    finally:
        con.close()

    out_rows_by_id = dict(staged)
    for row in rows:
        video_id = row["video_id"]
        if video_id not in target_ids:
            continue
        src = resolve_local_path(row["thumbnail_local_path"])
        ext = src.suffix.lower() if src.exists() and src.suffix else ".jpg"
        if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
            ext = ".jpg"
        out = THUMB_DIR / f"{video_id}{ext}"
        error = ""
        if src.exists():
            if not out.exists() or out.stat().st_size != src.stat().st_size:
                shutil.copy2(src, out)
            local_path = str(out)
            bytes_size = out.stat().st_size
            gcs_uri = f"gs://senior-share-staging-570862915709/naresome_thumbnails/{out.name}"
        else:
            local_path = ""
            bytes_size = 0
            gcs_uri = ""
            error = f"missing: {src}"
        out_rows_by_id[video_id] = {
                "video_id": video_id,
                "local_path": local_path,
                "bytes": bytes_size,
                "gcs_uri": gcs_uri,
                "error": error,
            }
    return sorted(out_rows_by_id.values(), key=lambda r: r["video_id"])


def existing_staged_thumbnails(target_ids: set[str]) -> dict[str, dict[str, object]]:
    rows = {}
    if not THUMB_DIR.exists():
        return rows
    for path in THUMB_DIR.iterdir():
        if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        video_id = path.stem
        if video_id not in target_ids:
            continue
        rows[video_id] = {
            "video_id": video_id,
            "local_path": str(path),
            "bytes": path.stat().st_size,
            "gcs_uri": f"gs://senior-share-staging-570862915709/naresome_thumbnails/{path.name}",
            "error": "",
        }
    return rows


def resolve_local_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return VAULT.parent / value


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(exist_ok=True)
    fields = list(rows[0].keys()) if rows else ["video_id", "local_path", "bytes", "gcs_uri", "error"]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
