# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
from pathlib import Path

from google.cloud import bigquery


PROJECT_ID = "rugged-destiny-408613"
DATASET = "naresome_all"
DATA_DIR = Path("data")
REPORT_DIR = Path("reports")
DIGEST_CHARS = 1600


def main() -> int:
    DATA_DIR.mkdir(exist_ok=True)
    REPORT_DIR.mkdir(exist_ok=True)
    client = bigquery.Client(project=PROJECT_ID)

    videos = []
    descriptions = []
    missing = []
    for row in client.query(video_query()).result():
        vid = row.video_id
        thumb_text = compact_text(row.thumbnail_text or "")
        item = {
            "video_id": vid,
            "channel_id": row.channel_id,
            "channel": row.channel or row.channel_id,
            "title": row.title or "",
            "published_at": row.published_at or "",
            "duration_sec": row.duration_sec,
            "view_count": row.view_count or 0,
            "like_count": row.like_count or 0,
            "comment_count": row.comment_count or 0,
            "thumbnail_url": row.thumbnail_url or "",
            "thumbnail_max_url": f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg",
            "thumbnail_fallback_urls": [
                f"https://i.ytimg.com/vi/{vid}/sddefault.jpg",
                f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                row.thumbnail_url or "",
            ],
            "youtube_url": f"https://www.youtube.com/watch?v={vid}",
            "fetched_at": row.fetched_at or "",
            "thumbnail_text": thumb_text,
            "thumbnail_analysis": {
                "main_subject": "",
                "people": "",
                "setting": "",
                "composition": "",
                "emotion_appeal": "",
                "story_hook": "",
            },
            "tags": parse_tags(row.tags),
        }
        videos.append(item)
        if not thumb_text:
            missing.append(
                {
                    "video_id": vid,
                    "channel": item["channel"],
                    "title": item["title"],
                    "view_count": item["view_count"],
                    "published_at": item["published_at"],
                    "fetched_at": item["fetched_at"],
                    "thumbnail_url": item["thumbnail_url"],
                }
            )
        desc = compact_text(row.description or "")
        if desc:
            descriptions.append(
                {
                    "video_id": vid,
                    "digest": desc[:DIGEST_CHARS],
                    "chars": len(desc),
                    "language": "ja",
                    "source": "youtube_description",
                    "fetched_at": row.fetched_at or "",
                }
            )

    write_js(DATA_DIR / "videos.js", "VIDEO_DATA", videos)
    write_js(DATA_DIR / "transcripts_light.js", "TRANSCRIPT_DATA", descriptions)
    write_missing_csv(REPORT_DIR / "thumbnail_text_missing.csv", missing)
    channels = list(client.query(channel_scope_query()).result())
    write_channel_scope_csv(REPORT_DIR / "channel_scope.csv", channels)
    summary = {
        "videos": len(videos),
        "videos_with_thumbnail_text": sum(1 for v in videos if v["thumbnail_text"]),
        "videos_missing_thumbnail_text": len(missing),
        "description_digests": len(descriptions),
        "digest_chars_per_video": DIGEST_CHARS,
        "target_channels": sum(1 for c in channels if c.is_target),
        "excluded_channels": sum(1 for c in channels if not c.is_target),
        "source": "bigquery",
    }
    (REPORT_DIR / "build_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def video_query() -> str:
    return f"""
    WITH ocr AS (
      SELECT
        video_id,
        ARRAY_TO_STRING(
          ARRAY(
            SELECT DISTINCT x
            FROM UNNEST([
              combined_text, emphasis_text, narration_text, dialogue_text,
              top_upper_text, top_lower_text, center_text,
              bottom_upper_text, bottom_lower_text
            ]) x
            WHERE x IS NOT NULL AND x != ''
          ),
          ' '
        ) AS thumbnail_text
      FROM `{PROJECT_ID}.{DATASET}.thumbnail_ocr`
    )
    SELECT
      v.video_id,
      v.channel_id,
      c.title AS channel,
      v.title,
      v.description,
      v.published_at,
      v.duration_sec,
      v.view_count,
      v.like_count,
      v.comment_count,
      v.thumbnail_url_max AS thumbnail_url,
      v.tags,
      v.fetched_at,
      o.thumbnail_text
    FROM `{PROJECT_ID}.{DATASET}.videos` v
    JOIN `{PROJECT_ID}.{DATASET}.channels` c
      USING(channel_id)
    LEFT JOIN ocr o
      USING(video_id)
    WHERE v.thumbnail_url_max IS NOT NULL
      AND v.thumbnail_url_max != ''
      AND COALESCE(c.relation_type, 'competitor') IN ('owned_current', 'competitor', 'migration_or_related_competitor')
      AND COALESCE(c.analysis_status, 'active') NOT IN ('exclude_from_naresome_competitor_analysis')
      AND REGEXP_CONTAINS(NORMALIZE(COALESCE(c.title, ''), NFKC), r'(馴れ初め|馴初め|なれそめ)')
      AND (v.duration_sec IS NULL OR v.duration_sec >= 120)
    ORDER BY COALESCE(v.view_count, 0) DESC
    """


def channel_scope_query() -> str:
    return f"""
    SELECT
      channel_id,
      title,
      COALESCE(relation_type, 'competitor') AS relation_type,
      COALESCE(analysis_status, 'active') AS analysis_status,
      COALESCE(video_count, 0) AS video_count,
      (
        COALESCE(relation_type, 'competitor') IN ('owned_current', 'competitor', 'migration_or_related_competitor')
        AND COALESCE(analysis_status, 'active') NOT IN ('exclude_from_naresome_competitor_analysis', 'inactive_or_no_public_videos')
        AND REGEXP_CONTAINS(NORMALIZE(COALESCE(title, ''), NFKC), r'(馴れ初め|馴初め|なれそめ)')
      ) AS is_target
    FROM `{PROJECT_ID}.{DATASET}.channels`
    ORDER BY is_target DESC, relation_type, analysis_status, video_count DESC, title
    """


def compact_text(text: object) -> str:
    return " ".join(str(text or "").replace("\r", "\n").split())


def parse_tags(value: object) -> list[str]:
    if not value:
        return []
    text = str(value).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [compact_text(x) for x in parsed if compact_text(x)]
    except Exception:
        pass
    return [x.strip() for x in text.replace("、", ",").split(",") if x.strip()]


def write_js(path: Path, name: str, data: object) -> None:
    path.write_text(
        f"window.{name} = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )


def write_missing_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["video_id", "channel", "title", "view_count", "published_at", "fetched_at", "thumbnail_url"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_channel_scope_csv(path: Path, rows: list[object]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["is_target", "channel_id", "title", "relation_type", "analysis_status", "video_count"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: getattr(row, field) for field in fields})


if __name__ == "__main__":
    raise SystemExit(main())
