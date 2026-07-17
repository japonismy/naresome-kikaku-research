# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


REGISTRY_CSV = Path("data_sources/baseline_competitor_channels.csv")
OUTPUT_CSV = Path("data_sources/youtube_channel_status.csv")
CHANNELS_API_URL = "https://www.googleapis.com/youtube/v3/channels"
PLAYLIST_ITEMS_API_URL = "https://www.googleapis.com/youtube/v3/playlistItems"
GCP_PROJECT_ID = "rugged-destiny-408613"
GCP_SECRET_ID = "naresome-youtube-api-key"
FIELDS = [
    "channel_id",
    "registry_channel_name",
    "handle",
    "youtube_channel_title",
    "availability",
    "subscriber_count",
    "video_count",
    "uploads_playlist_id",
    "latest_video_id",
    "latest_published_at",
    "checked_at",
]


class YouTubeApiError(RuntimeError):
    pass


def main() -> int:
    registry = read_registry()
    api_key = get_api_key()
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    previous = read_previous_rows()
    try:
        channel_items = fetch_channels([row["canonical_channel_id"] for row in registry], api_key)
    except YouTubeApiError as exc:
        if OUTPUT_CSV.exists():
            print(
                json.dumps(
                    {
                        "registry_channels": len(registry),
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
    for entry in registry:
        channel_id = entry["canonical_channel_id"]
        item = channel_items.get(channel_id)
        if item is None:
            old = {field: str(previous.get(channel_id, {}).get(field, "")) for field in FIELDS}
            old.update(
                {
                    "channel_id": channel_id,
                    "registry_channel_name": entry["channel_name"],
                    "handle": entry["handle"],
                    "availability": "unavailable",
                    "checked_at": checked_at,
                }
            )
            rows.append(old)
            continue

        snippet = item.get("snippet") or {}
        statistics = item.get("statistics") or {}
        content_details = item.get("contentDetails") or {}
        uploads_playlist_id = str(
            ((content_details.get("relatedPlaylists") or {}).get("uploads")) or ""
        )
        video_count = int(str(statistics.get("videoCount") or "0"))
        try:
            latest = (
                fetch_latest_upload(uploads_playlist_id, api_key)
                if uploads_playlist_id and video_count > 0
                else {}
            )
        except YouTubeApiError:
            old = previous.get(channel_id, {})
            latest = {
                "video_id": str(old.get("latest_video_id") or ""),
                "published_at": str(old.get("latest_published_at") or ""),
            }
        rows.append(
            {
                "channel_id": channel_id,
                "registry_channel_name": entry["channel_name"],
                "handle": entry["handle"],
                "youtube_channel_title": str(snippet.get("title") or ""),
                "availability": "public",
                "subscriber_count": str(statistics.get("subscriberCount") or ""),
                "video_count": str(video_count),
                "uploads_playlist_id": uploads_playlist_id,
                "latest_video_id": str(latest.get("video_id") or ""),
                "latest_published_at": str(latest.get("published_at") or ""),
                "checked_at": checked_at,
            }
        )

    write_rows(rows)
    print(
        json.dumps(
            {
                "registry_channels": len(registry),
                "public": sum(1 for row in rows if row["availability"] == "public"),
                "unavailable": sum(1 for row in rows if row["availability"] != "public"),
                "output": str(OUTPUT_CSV),
            },
            ensure_ascii=False,
        )
    )
    return 0


def read_registry() -> list[dict[str, str]]:
    with REGISTRY_CSV.open("r", newline="", encoding="utf-8-sig") as f:
        rows = [
            dict(row)
            for row in csv.DictReader(f)
            if not str(row.get("portal_scope", "") or "").startswith("exclude")
        ]
    channel_ids = [row.get("canonical_channel_id", "").strip() for row in rows]
    if len(rows) != 32 or any(not channel_id for channel_id in channel_ids):
        raise SystemExit("Public baseline registry must contain exactly 32 canonical channel IDs")
    if len(set(channel_ids)) != 32:
        raise SystemExit("Baseline registry contains duplicate canonical channel IDs")
    return rows


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


def fetch_channels(channel_ids: list[str], api_key: str) -> dict[str, dict[str, object]]:
    query = urlencode(
        {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(channel_ids),
            "maxResults": 50,
            "key": api_key,
        }
    )
    payload = fetch_json(f"{CHANNELS_API_URL}?{query}")
    items = payload.get("items") or []
    return {
        str(item.get("id") or ""): item
        for item in items
        if isinstance(item, dict) and item.get("id")
    }


def fetch_latest_upload(playlist_id: str, api_key: str) -> dict[str, str]:
    query = urlencode(
        {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": 1,
            "key": api_key,
        }
    )
    payload = fetch_json(f"{PLAYLIST_ITEMS_API_URL}?{query}", allow_not_found=True)
    items = payload.get("items") or []
    if not items:
        return {}
    item = items[0] if isinstance(items[0], dict) else {}
    snippet = item.get("snippet") or {}
    content_details = item.get("contentDetails") or {}
    return {
        "video_id": str(content_details.get("videoId") or ""),
        "published_at": str(
            content_details.get("videoPublishedAt")
            or snippet.get("publishedAt")
            or ""
        ),
    }


def fetch_json(url: str, *, allow_not_found: bool = False) -> dict[str, object]:
    try:
        with urlopen(url, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if allow_not_found and exc.code == 404:
            return {}
        raise YouTubeApiError(f"YouTube Data API returned HTTP {exc.code}") from None
    except URLError as exc:
        raise YouTubeApiError(f"YouTube Data API request failed: {exc.reason}") from None
    return payload if isinstance(payload, dict) else {}


def read_previous_rows() -> dict[str, dict[str, str]]:
    if not OUTPUT_CSV.exists():
        return {}
    with OUTPUT_CSV.open("r", newline="", encoding="utf-8-sig") as f:
        return {
            row["channel_id"]: row
            for row in csv.DictReader(f)
            if row.get("channel_id")
        }


def write_rows(rows: list[dict[str, str]]) -> None:
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
