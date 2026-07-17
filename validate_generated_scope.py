# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
SOURCE_DIR = HERE / "data_sources"
REPORT_DIR = HERE / "reports"


def main() -> int:
    registry = read_csv(SOURCE_DIR / "baseline_competitor_channels.csv")
    included = [
        row
        for row in registry
        if not str(row.get("portal_scope", "") or "").startswith("exclude")
    ]
    excluded = [row for row in registry if row not in included]
    channels = read_js(DATA_DIR / "channels.js", "CHANNEL_DATA")
    videos = read_js(DATA_DIR / "videos.js", "VIDEO_DATA")
    transcripts = read_js(DATA_DIR / "transcripts_light.js", "TRANSCRIPT_DATA")

    assert len(registry) == 33, len(registry)
    assert len(included) == 32, len(included)
    assert [row["channel_name"] for row in excluded] == ["俺たちの馴れ初め"], excluded
    canonical_ids = [row["canonical_channel_id"] for row in included]
    assert len(set(canonical_ids)) == 32 and all(canonical_ids)
    assert len(channels) == 32
    assert len({channel["channel_id"] for channel in channels}) == 32

    allowed_ids = {channel["channel_id"] for channel in channels}
    allowed_titles = {
        normalize(title)
        for channel in channels
        for title in (
            channel.get("channel_name", ""),
            channel.get("db_title", ""),
            channel.get("portal_channel_name", ""),
        )
        if normalize(title)
    }
    excluded_ids = {row["canonical_channel_id"] for row in excluded}
    video_ids = [video["video_id"] for video in videos]
    assert len(video_ids) == len(set(video_ids))
    assert not any(video.get("channel_id") in excluded_ids for video in videos)
    unexpected = [
        video
        for video in videos
        if video.get("channel_id") not in allowed_ids
        and normalize(video.get("channel", "")) not in allowed_titles
    ]
    assert not unexpected, unexpected[:5]

    transcript_ids = [row["video_id"] for row in transcripts]
    assert len(transcript_ids) == len(set(transcript_ids))
    assert set(transcript_ids).issubset(set(video_ids))

    thumbnail_asset_errors = [
        video["video_id"]
        for video in videos
        if video.get("thumbnail_gcs_uri")
        and gcs_stem(video["thumbnail_gcs_uri"]) != video["video_id"]
    ]
    script_asset_errors = [
        video["video_id"]
        for video in videos
        if video.get("script_gcs_uri")
        and gcs_stem(video["script_gcs_uri"]) != video["video_id"]
    ]
    assert not thumbnail_asset_errors
    assert not script_asset_errors

    overrides = read_csv(SOURCE_DIR / "thumbnail_asset_overrides.csv")
    by_video_id = {video["video_id"]: video for video in videos}
    override_errors = [
        row["video_id"]
        for row in overrides
        if by_video_id.get(row["video_id"], {}).get("thumbnail_gcs_uri") != row["gcs_uri"]
    ]
    assert not override_errors

    archive_thumbnails = read_csv(REPORT_DIR / "archive_thumbnail_assets_manifest.csv")
    archive_thumbnail_missing = [
        row["video_id"]
        for row in archive_thumbnails
        if row["video_id"] not in by_video_id
        or by_video_id[row["video_id"]].get("thumbnail_gcs_uri") != row["gcs_uri"]
    ]
    assert not archive_thumbnail_missing

    build_summary = json.loads((REPORT_DIR / "build_summary.json").read_text(encoding="utf-8"))
    report = {
        "ok": True,
        "source_registry_channels": len(registry),
        "public_registry_channels": len(included),
        "excluded_registry_channels": [row["channel_name"] for row in excluded],
        "searchable_videos": len(videos),
        "searchable_channel_ids": len({video.get("channel_id") for video in videos if video.get("channel_id")}),
        "lifecycle_counts": dict(Counter(channel.get("lifecycle", "") for channel in channels)),
        "data_status_counts": dict(Counter(channel.get("data_status", "") for channel in channels)),
        "thumbnail_gcs_assets": sum(1 for video in videos if video.get("thumbnail_gcs_uri")),
        "script_gcs_assets": sum(1 for video in videos if video.get("script_gcs_uri")),
        "copy_archive_thumbnail_links": len(archive_thumbnails),
        "thumbnail_override_links": len(overrides),
        "archive_script_links": build_summary.get("archive_script_link_rows", 0),
        "thumbnail_asset_id_errors": 0,
        "script_asset_id_errors": 0,
        "out_of_scope_videos": 0,
        "duplicate_video_ids": 0,
        "orphan_transcripts": 0,
    }
    (REPORT_DIR / "final_scope_asset_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return [dict(row) for row in csv.DictReader(f)]


def read_js(path: Path, variable_name: str) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8").strip()
    prefix = f"window.{variable_name} = "
    if not text.startswith(prefix):
        raise ValueError(f"Unexpected JS prefix: {path}")
    payload = text[len(prefix):]
    if payload.endswith(";"):
        payload = payload[:-1]
    data = json.loads(payload)
    if not isinstance(data, list):
        raise ValueError(f"Expected list: {path}")
    return data


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", "", text)


def gcs_stem(uri: str) -> str:
    return Path(str(uri).rsplit("/", 1)[-1]).stem


if __name__ == "__main__":
    raise SystemExit(main())
