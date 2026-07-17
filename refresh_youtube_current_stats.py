# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


SOURCE_CSV = Path("data_sources/observed_archive_supplement.csv")
BASELINE_CHANNELS_CSV = Path("data_sources/baseline_competitor_channels.csv")
OUTPUT_CSV = Path("data_sources/youtube_current_stats.csv")
API_URL = "https://www.googleapis.com/youtube/v3/videos"
GCP_PROJECT_ID = "rugged-destiny-408613"
GCP_SECRET_ID = "naresome-youtube-api-key"
FIELDS = [
    "video_id",
    "channel_id",
    "channel_title",
    "video_title",
    "published_at",
    "view_count",
    "like_count",
    "comment_count",
    "fetched_at",
    "availability",
    "checked_at",
]


class YouTubeApiError(RuntimeError):
    pass


def main() -> int:
    api_key = get_api_key()

    video_ids = read_video_ids()
    previous = read_previous_rows()
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    refreshed: dict[str, dict[str, str]] = {}

    try:
        for start in range(0, len(video_ids), 50):
            batch = video_ids[start : start + 50]
            for item in fetch_batch(batch, api_key):
                snippet = item.get("snippet") or {}
                statistics = item.get("statistics") or {}
                video_id = str(item.get("id") or "")
                if not video_id:
                    continue
                refreshed[video_id] = {
                    "video_id": video_id,
                    "channel_id": str(snippet.get("channelId") or ""),
                    "channel_title": str(snippet.get("channelTitle") or ""),
                    "video_title": str(snippet.get("title") or ""),
                    "published_at": str(snippet.get("publishedAt") or ""),
                    "view_count": str(statistics.get("viewCount") or ""),
                    "like_count": str(statistics.get("likeCount") or ""),
                    "comment_count": str(statistics.get("commentCount") or ""),
                    "fetched_at": checked_at,
                    "availability": "public",
                    "checked_at": checked_at,
                }
    except YouTubeApiError as exc:
        if OUTPUT_CSV.exists():
            print(
                json.dumps(
                    {
                        "requested": len(video_ids),
                        "refreshed": False,
                        "preserved_previous_rows": len(previous),
                        "error": str(exc),
                        "output": str(OUTPUT_CSV),
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        raise SystemExit(str(exc)) from None

    rows = []
    for video_id in video_ids:
        if video_id in refreshed:
            rows.append(refreshed[video_id])
            continue
        old = {field: str(previous.get(video_id, {}).get(field, "")) for field in FIELDS}
        old["video_id"] = video_id
        old["availability"] = "unavailable"
        old["checked_at"] = checked_at
        rows.append(old)

    write_rows(rows)
    print(
        json.dumps(
            {
                "requested": len(video_ids),
                "public": len(refreshed),
                "unavailable": len(video_ids) - len(refreshed),
                "output": str(OUTPUT_CSV),
            },
            ensure_ascii=False,
        )
    )
    return 0


def get_api_key() -> str:
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if api_key:
        return api_key
    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{GCP_PROJECT_ID}/secrets/{GCP_SECRET_ID}/versions/latest"
        return client.access_secret_version(request={"name": name}).payload.data.decode("utf-8").strip()
    except Exception as exc:
        raise SystemExit(f"Could not load the YouTube API key: {type(exc).__name__}") from None


def read_video_ids() -> list[str]:
    allowed_channels = read_allowed_channels()
    with SOURCE_CSV.open("r", newline="", encoding="utf-8-sig") as f:
        return list(
            dict.fromkeys(
                row["video_id"].strip()
                for row in csv.DictReader(f)
                if row.get("video_id", "").strip()
                and normalize_channel_title(row.get("channel_title", "")) in allowed_channels
            )
        )


def read_allowed_channels() -> set[str]:
    with BASELINE_CHANNELS_CSV.open("r", newline="", encoding="utf-8-sig") as f:
        channels = {
            normalize_channel_title(row.get("channel_name", ""))
            for row in csv.DictReader(f)
            if normalize_channel_title(row.get("channel_name", ""))
            and not str(row.get("portal_scope", "") or "").startswith("exclude")
        }
    if len(channels) != 32:
        raise SystemExit(f"Public baseline registry must contain 32 unique channels; found {len(channels)}")
    return channels


def normalize_channel_title(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", "", text)


def read_previous_rows() -> dict[str, dict[str, str]]:
    if not OUTPUT_CSV.exists():
        return {}
    with OUTPUT_CSV.open("r", newline="", encoding="utf-8-sig") as f:
        return {row["video_id"]: row for row in csv.DictReader(f) if row.get("video_id")}


def fetch_batch(video_ids: list[str], api_key: str) -> list[dict[str, object]]:
    query = urlencode(
        {
            "part": "snippet,statistics",
            "id": ",".join(video_ids),
            "maxResults": 50,
            "key": api_key,
        }
    )
    try:
        with urlopen(f"{API_URL}?{query}", timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise YouTubeApiError(f"YouTube Data API returned HTTP {exc.code}") from None
    except URLError as exc:
        raise YouTubeApiError(f"YouTube Data API request failed: {exc.reason}") from None
    items = payload.get("items") or []
    return items if isinstance(items, list) else []


def write_rows(rows: list[dict[str, str]]) -> None:
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
