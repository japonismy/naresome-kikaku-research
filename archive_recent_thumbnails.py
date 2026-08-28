# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from google.cloud import bigquery, storage

from download_missing_thumbnails import download_best
from sync_gcs_assets_to_bq import load_thumbnail_assets


HERE = Path(__file__).resolve().parent
PROJECT_ID = "rugged-destiny-408613"
BUCKET_NAME = "senior-share-staging-570862915709"
OBJECT_PREFIX = "naresome_thumbnails"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Archive the newest thumbnails that still depend on YouTube image hosts."
    )
    parser.add_argument("--limit", type=int, default=150)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    videos = load_videos()
    targets = sorted(
        (video for video in videos if not has_archived_thumbnail(video)),
        key=lambda video: str(video.get("published_at") or ""),
        reverse=True,
    )[: max(0, args.limit)]

    if args.dry_run or not targets:
        print(
            json.dumps(
                {
                    "targets": len(targets),
                    "latest": [video.get("video_id", "") for video in targets[:10]],
                    "dry_run": args.dry_run,
                },
                ensure_ascii=False,
            )
        )
        return 0

    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(BUCKET_NAME)
    uploaded_rows: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []

    with tempfile.TemporaryDirectory(prefix="naresome-thumbnails-") as temp_dir:
        temp_path = Path(temp_dir)
        downloaded = download_targets(targets, temp_path, max(1, args.workers))
        for video, result, local_path in downloaded:
            video_id = str(video.get("video_id") or "")
            if not local_path.exists():
                failures.append({"video_id": video_id, "error": str(result.get("error") or "download failed")})
                continue
            object_name = f"{OBJECT_PREFIX}/{video_id}.jpg"
            try:
                blob = bucket.blob(object_name)
                blob.cache_control = "public, max-age=31536000, immutable"
                blob.upload_from_filename(str(local_path), content_type="image/jpeg")
                uploaded_rows.append(
                    {
                        "video_id": video_id,
                        "gcs_uri": f"gs://{BUCKET_NAME}/{object_name}",
                        "bytes": local_path.stat().st_size,
                        "error": "",
                    }
                )
            except Exception as exc:  # Keep processing other thumbnails and report exact failures.
                failures.append({"video_id": video_id, "error": f"upload: {type(exc).__name__}: {exc}"})

    if uploaded_rows:
        bigquery_client = bigquery.Client(project=PROJECT_ID)
        load_thumbnail_assets(bigquery_client, uploaded_rows)

    print(
        json.dumps(
            {
                "targets": len(targets),
                "uploaded": len(uploaded_rows),
                "failed": len(failures),
                "failures": failures[:20],
            },
            ensure_ascii=False,
        )
    )
    return 0 if uploaded_rows or not targets else 1


def load_videos() -> list[dict]:
    text = (HERE / "data" / "videos.js").read_text(encoding="utf-8")
    return json.loads(text.removeprefix("window.VIDEO_DATA = ").strip().rstrip(";"))


def has_archived_thumbnail(video: dict) -> bool:
    return bool(video.get("thumbnail_saved_url") or video.get("thumbnail_gcs_uri"))


def download_targets(
    videos: list[dict], temp_path: Path, workers: int
) -> list[tuple[dict, dict[str, object], Path]]:
    def download(video: dict) -> tuple[dict, dict[str, object], Path]:
        local_path = temp_path / f"{video['video_id']}.jpg"
        return video, download_best(str(video["video_id"]), local_path), local_path

    results: list[tuple[dict, dict[str, object], Path]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(download, video) for video in videos]
        for future in as_completed(futures):
            results.append(future.result())
    return results


if __name__ == "__main__":
    raise SystemExit(main())
