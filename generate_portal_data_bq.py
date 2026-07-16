# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

from google.cloud import bigquery


PROJECT_ID = "rugged-destiny-408613"
DATASET = "naresome_all"
DATA_DIR = Path("data")
REPORT_DIR = Path("reports")
SOURCE_DIR = Path("data_sources")
OBSERVED_SUPPLEMENT_CSV = SOURCE_DIR / "observed_archive_supplement.csv"
CHANNEL_DISPLAY_RULES_CSV = SOURCE_DIR / "channel_display_rules.csv"
YOUTUBE_CURRENT_STATS_CSV = SOURCE_DIR / "youtube_current_stats.csv"
DIGEST_CHARS = 1600
HIDDEN_FLAGS = {"adult", "manga_reference", "out_of_scope"}
ADULT_TITLE_RE = re.compile(
    r"(?:セックス|セク依存|S(?:EX|[〇○◯●]X)|エッチ|エッ[〇○◯●]|エ[〇○◯●]チ|"
    r"オ[〇○◯●]?ナニー|オ[〇○◯●]ニー|風俗|風[〇○◯●]|AV女優|A[〇○◯●]女優|"
    r"ヤリまく|ヤって|ヤらせ|中出し|中[〇○◯●]し|中に出して|ノーパン|"
    r"ノー[〇○◯●ー]?ブラ|全裸|全[〇○◯●]|全ネ果|爆乳|巨乳|精力剤|"
    r"ラブホ(?:テル)?|ラ[〇○◯●]ホ|Lホテル|ソープ|デリヘル|アソコ|"
    r"あそこ.*(?:触|舐|挟)|おっ?[〇○◯●]い|おっぱい|乳房|勃起|フル[〇○◯●]?ッキ|"
    r"パ[ン〇○◯●]ツ.*(?:中|手|匂|舐|濡)|下着.*(?:透|見|脱)|お股を広げ|"
    r"息子.*(?:暴走|触|サワ|大きく|入れ)|俺のアレ|アレを(?:食|触|舐)|"
    r"大人のおもちゃ|筆お[〇○◯●]し|初体験を捧|ゴムが落ち|1発1万)",
    re.IGNORECASE,
)
MANGA_TITLE_RE = re.compile(r"(?:【漫画】|【恋愛漫画】|ラブコメ漫画|ボイコミ)")


def main() -> int:
    DATA_DIR.mkdir(exist_ok=True)
    REPORT_DIR.mkdir(exist_ok=True)
    SOURCE_DIR.mkdir(exist_ok=True)
    client = bigquery.Client(project=PROJECT_ID)
    display_rules = load_channel_display_rules()

    videos = []
    video_by_id = {}
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
            "thumbnail_gcs_uri": row.thumbnail_gcs_uri or "",
            "thumbnail_saved_url": gcs_public_url(row.thumbnail_gcs_uri or ""),
            "thumbnail_max_url": f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg",
            "thumbnail_fallback_urls": [
                gcs_public_url(row.thumbnail_gcs_uri or ""),
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
            "script_asset_available": bool(row.script_asset_available),
            "script_gcs_uri": row.gcs_csv_uri or "",
            "script_csv_url": row.public_csv_url or "",
            "tags": parse_tags(row.tags),
            "relation_type": row.relation_type or "competitor",
            "analysis_status": row.analysis_status or "active",
            "content_category": row.content_category or "",
            "watch_scope": row.watch_scope or "full",
            "scope_type": "monitored_channel_archive" if row.source_type == "archive" else "monitored_channel",
            "content_flags": [],
            "default_visible": True,
            "classification_reason": "BigQuery監視チャンネル台帳",
            "source_type": row.source_type or "current",
            "is_archive": row.source_type == "archive",
            "archive_type": "stopped_channel_archive" if row.source_type == "archive" else "current_monitoring",
            "observed_view_count": row.view_count or 0,
            "observed_like_count": row.like_count or 0,
            "observed_comment_count": row.comment_count or 0,
            "observed_at": row.fetched_at or "",
            "max_observed_view_count": row.view_count or 0,
            "latest_observed_at": row.fetched_at or "",
            "observation_sources": [row.source_type or "current"],
            "observation_history": [
                {
                    "observed_at": row.fetched_at or "",
                    "view_count": row.view_count or 0,
                    "like_count": row.like_count or 0,
                    "comment_count": row.comment_count or 0,
                    "source_name": row.source_type or "current",
                    "archive_type": "stopped_channel_archive" if row.source_type == "archive" else "current_monitoring",
                }
            ],
        }
        videos.append(item)
        video_by_id[vid] = item
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

    supplement_summary = load_observed_supplements(videos, video_by_id)
    youtube_stats_summary = load_youtube_current_stats(videos, video_by_id)
    classification_summary = classify_videos(videos, display_rules)
    videos.sort(key=lambda v: int_value(v.get("max_observed_view_count", v.get("view_count", 0))), reverse=True)
    write_js(DATA_DIR / "videos.js", "VIDEO_DATA", videos)
    write_js(DATA_DIR / "transcripts_light.js", "TRANSCRIPT_DATA", descriptions)
    write_missing_csv(REPORT_DIR / "thumbnail_text_missing.csv", missing)
    write_content_scope_csv(REPORT_DIR / "content_scope.csv", videos)
    channels = list(client.query(channel_scope_query()).result())
    write_channel_scope_csv(REPORT_DIR / "channel_scope.csv", channels)
    summary = {
        "videos": len(videos),
        "videos_with_thumbnail_text": sum(1 for v in videos if v["thumbnail_text"]),
        "videos_missing_thumbnail_text": len(missing),
        "description_digests": len(descriptions),
        "digest_chars_per_video": DIGEST_CHARS,
        "videos_with_script_asset": sum(1 for v in videos if v["script_asset_available"]),
        "videos_with_script_gcs_uri": sum(1 for v in videos if v["script_gcs_uri"]),
        "videos_with_script_csv_url": sum(1 for v in videos if v["script_csv_url"]),
        "videos_with_thumbnail_gcs_uri": sum(1 for v in videos if v["thumbnail_gcs_uri"]),
        "videos_from_observed_supplement": supplement_summary["inserted"],
        "videos_updated_by_observed_supplement": supplement_summary["updated"],
        "observed_supplement_rows": supplement_summary["rows"],
        "observed_supplement_path": str(OBSERVED_SUPPLEMENT_CSV),
        "youtube_current_stats_rows": youtube_stats_summary["rows"],
        "youtube_current_stats_merged": youtube_stats_summary["merged"],
        "youtube_current_stats_path": str(YOUTUBE_CURRENT_STATS_CSV),
        "channel_display_rules": len(display_rules),
        "default_visible_videos": classification_summary.get("default_visible", 0),
        "default_hidden_videos": classification_summary.get("default_hidden", 0),
        "adult_flagged_videos": classification_summary.get("adult", 0),
        "manga_reference_flagged_videos": classification_summary.get("manga_reference", 0),
        "out_of_scope_flagged_videos": classification_summary.get("out_of_scope", 0),
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
      v.source_type,
      COALESCE(c.relation_type, 'competitor') AS relation_type,
      COALESCE(c.analysis_status, 'active') AS analysis_status,
      COALESCE(c.content_category, '') AS content_category,
      COALESCE(c.watch_scope, 'full') AS watch_scope,
      o.thumbnail_text,
      IF(sa.video_id IS NOT NULL AND sa.asset_count > 0, TRUE, FALSE) AS script_asset_available,
      sa.gcs_csv_uri,
      sa.public_csv_url,
      ta.gcs_uri AS thumbnail_gcs_uri
    FROM (
      SELECT
        'current' AS source_type,
        video_id,
        channel_id,
        title,
        description,
        published_at,
        duration_sec,
        view_count,
        like_count,
        comment_count,
        thumbnail_url_max,
        tags,
        fetched_at
      FROM `{PROJECT_ID}.{DATASET}.videos`
      UNION ALL
      SELECT
        'archive' AS source_type,
        a.video_id,
        a.channel_id,
        a.title,
        a.description,
        a.published_at,
        a.duration_sec,
        a.view_count,
        a.like_count,
        a.comment_count,
        a.thumbnail_url_max,
        CASE
          WHEN a.tags IS NULL OR a.tags = '' THEN '["archive"]'
          ELSE a.tags
        END AS tags,
        a.fetched_at
      FROM `{PROJECT_ID}.{DATASET}.videos_archive_20260527` a
      WHERE NOT EXISTS (
        SELECT 1
        FROM `{PROJECT_ID}.{DATASET}.videos` cur
        WHERE cur.video_id = a.video_id
      )
    ) v
    JOIN `{PROJECT_ID}.{DATASET}.channels` c
      USING(channel_id)
    LEFT JOIN ocr o
      USING(video_id)
    LEFT JOIN `{PROJECT_ID}.{DATASET}.script_assets` sa
      USING(video_id)
    LEFT JOIN `{PROJECT_ID}.{DATASET}.thumbnail_assets` ta
      USING(video_id)
    WHERE v.thumbnail_url_max IS NOT NULL
      AND v.thumbnail_url_max != ''
      AND COALESCE(c.relation_type, 'competitor') IN ('owned_current', 'competitor', 'migration_or_related_competitor')
      AND COALESCE(c.analysis_status, 'active') NOT IN ('exclude_from_naresome_competitor_analysis')
      AND (v.duration_sec IS NULL OR v.duration_sec >= 120)
    ORDER BY COALESCE(v.view_count, 0) DESC
    """


def channel_scope_query() -> str:
    return f"""
    SELECT
      channel_id,
      title,
      COALESCE(relation_type, 'competitor') AS relation_type,
      COALESCE(content_category, '') AS content_category,
      COALESCE(watch_scope, 'full') AS watch_scope,
      COALESCE(analysis_status, 'active') AS analysis_status,
      COALESCE(video_count, 0) AS video_count,
      (
        COALESCE(relation_type, 'competitor') IN ('owned_current', 'competitor', 'migration_or_related_competitor')
        AND COALESCE(analysis_status, 'active') NOT IN ('exclude_from_naresome_competitor_analysis')
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


def load_channel_display_rules() -> dict[str, dict[str, str]]:
    if not CHANNEL_DISPLAY_RULES_CSV.exists():
        return {}
    with CHANNEL_DISPLAY_RULES_CSV.open("r", newline="", encoding="utf-8-sig") as f:
        rows = csv.DictReader(f)
        return {
            normalize_channel_title(row.get("channel_title", "")): {
                "classification": compact_text(row.get("classification", "")),
                "reason": compact_text(row.get("reason", "")),
            }
            for row in rows
            if compact_text(row.get("channel_title", ""))
        }


def classify_videos(videos: list[dict[str, object]], rules: dict[str, dict[str, str]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in videos:
        flags = set(str(x) for x in item.get("content_flags", []) if x)
        channel = compact_text(item.get("channel", ""))
        title = compact_text(item.get("title", ""))
        rule = rules.get(normalize_channel_title(channel))
        if rule:
            classification = rule["classification"]
            if classification in HIDDEN_FLAGS:
                flags.add(classification)
                item["scope_type"] = classification
            elif classification:
                item["scope_type"] = classification
            item["classification_reason"] = rule["reason"] or "チャンネル表示ルール"
        normalized_title = unicodedata.normalize("NFKC", title)
        if ADULT_TITLE_RE.search(normalized_title):
            flags.add("adult")
            if not rule:
                item["classification_reason"] = "動画タイトルの成人向け表現"
        if MANGA_TITLE_RE.search(normalized_title):
            flags.add("manga_reference")
            if not rule:
                item["classification_reason"] = "動画タイトルの漫画・ボイコミ表現"
        item["content_flags"] = sorted(flags)
        item["default_visible"] = not bool(flags & HIDDEN_FLAGS)
        if item["default_visible"]:
            counts["default_visible"] += 1
        else:
            counts["default_hidden"] += 1
        for flag in flags:
            counts[flag] += 1
    return dict(counts)


def normalize_channel_title(value: object) -> str:
    text = unicodedata.normalize("NFKC", compact_text(value)).casefold()
    return re.sub(r"\s+", "", text)


def load_observed_supplements(videos: list[dict[str, object]], video_by_id: dict[str, dict[str, object]]) -> dict[str, int]:
    summary = {"rows": 0, "inserted": 0, "updated": 0}
    if not OBSERVED_SUPPLEMENT_CSV.exists():
        return summary

    with OBSERVED_SUPPLEMENT_CSV.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            vid = compact_text(row.get("video_id", ""))
            if not vid:
                continue
            summary["rows"] += 1
            observed = {
                "observed_at": compact_text(row.get("observed_at", "")),
                "view_count": int_value(row.get("observed_view_count")),
                "like_count": int_value(row.get("observed_like_count")),
                "comment_count": int_value(row.get("observed_comment_count")),
                "source_name": compact_text(row.get("source_name", "")) or "observed_archive_supplement",
                "archive_type": compact_text(row.get("archive_type", "")) or "competitor_sheet_archive",
            }
            if vid in video_by_id:
                merge_observation(video_by_id[vid], observed)
                summary["updated"] += 1
                continue

            item = make_supplement_video(vid, row, observed)
            videos.append(item)
            video_by_id[vid] = item
            summary["inserted"] += 1
    return summary


def load_youtube_current_stats(videos: list[dict[str, object]], video_by_id: dict[str, dict[str, object]]) -> dict[str, int]:
    summary = {"rows": 0, "merged": 0}
    if not YOUTUBE_CURRENT_STATS_CSV.exists():
        return summary

    with YOUTUBE_CURRENT_STATS_CSV.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            summary["rows"] += 1
            video_id = compact_text(row.get("video_id", ""))
            view_count = compact_text(row.get("view_count", ""))
            item = video_by_id.get(video_id)
            if not item or not view_count:
                continue
            observed = {
                "observed_at": compact_text(row.get("fetched_at", "")),
                "view_count": int_value(view_count),
                "like_count": int_value(row.get("like_count")),
                "comment_count": int_value(row.get("comment_count")),
                "source_name": "youtube_current_stats",
                "archive_type": "youtube_live_snapshot",
            }
            merge_observation(item, observed)
            if not compact_text(item.get("channel_id", "")):
                item["channel_id"] = compact_text(row.get("channel_id", ""))
            summary["merged"] += 1
    return summary


def make_supplement_video(video_id: str, row: dict[str, str], observed: dict[str, object]) -> dict[str, object]:
    thumbnail_url = compact_text(row.get("thumbnail_url", "")) or f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
    thumbnail_gcs_uri = compact_text(row.get("thumbnail_gcs_uri", ""))
    saved_url = compact_text(row.get("thumbnail_saved_url", "")) or gcs_public_url(thumbnail_gcs_uri)
    archive_type = str(observed["archive_type"])
    return {
        "video_id": video_id,
        "channel_id": compact_text(row.get("channel_id", "")),
        "channel": compact_text(row.get("channel_title", "")),
        "title": compact_text(row.get("video_title", "")),
        "published_at": compact_text(row.get("published_at", "")),
        "duration_sec": None,
        "view_count": observed["view_count"],
        "like_count": observed["like_count"],
        "comment_count": observed["comment_count"],
        "thumbnail_url": thumbnail_url,
        "thumbnail_gcs_uri": thumbnail_gcs_uri,
        "thumbnail_saved_url": saved_url,
        "thumbnail_max_url": f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
        "thumbnail_fallback_urls": [
            saved_url,
            f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg",
            f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            thumbnail_url,
        ],
        "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
        "fetched_at": observed["observed_at"],
        "thumbnail_text": "",
        "thumbnail_analysis": {
            "main_subject": "",
            "people": "",
            "setting": "",
            "composition": "",
            "emotion_appeal": "",
            "story_hook": "",
        },
        "script_asset_available": False,
        "script_gcs_uri": "",
        "script_csv_url": "",
        "tags": ["observed_archive", archive_type],
        "relation_type": "former_competitor",
        "analysis_status": "historical_observation",
        "content_category": "",
        "watch_scope": "archive_only",
        "scope_type": "former_competitor",
        "content_flags": [],
        "default_visible": True,
        "classification_reason": "過去の競合調査シート",
        "source_type": "observed_archive",
        "is_archive": True,
        "archive_type": archive_type,
        "observed_view_count": observed["view_count"],
        "observed_like_count": observed["like_count"],
        "observed_comment_count": observed["comment_count"],
        "observed_at": observed["observed_at"],
        "max_observed_view_count": observed["view_count"],
        "latest_observed_at": observed["observed_at"],
        "observation_sources": [observed["source_name"]],
        "observation_history": [observed],
    }


def merge_observation(item: dict[str, object], observed: dict[str, object]) -> None:
    history = item.setdefault("observation_history", [])
    if isinstance(history, list):
        history.append(observed)

    sources = item.setdefault("observation_sources", [])
    source_name = str(observed["source_name"])
    if isinstance(sources, list) and source_name not in sources:
        sources.append(source_name)

    item["max_observed_view_count"] = max(
        int_value(item.get("max_observed_view_count")),
        int_value(observed.get("view_count")),
    )
    observed_at = compact_text(observed.get("observed_at", ""))
    current_at = compact_text(item.get("observed_at", ""))
    if observed_at and (not current_at or observed_at >= current_at):
        item["observed_view_count"] = observed["view_count"]
        item["observed_like_count"] = observed["like_count"]
        item["observed_comment_count"] = observed["comment_count"]
        item["observed_at"] = observed["observed_at"]
        item["view_count"] = observed["view_count"]
        item["like_count"] = observed["like_count"]
        item["comment_count"] = observed["comment_count"]
        item["fetched_at"] = observed["observed_at"]
    if observed_at >= compact_text(item.get("latest_observed_at", "")):
        item["latest_observed_at"] = observed["observed_at"]


def int_value(value: object) -> int:
    text = str(value or "").replace(",", "").strip()
    try:
        return int(float(text))
    except ValueError:
        return 0


def gcs_public_url(uri: str) -> str:
    if not uri.startswith("gs://"):
        return ""
    path = uri.removeprefix("gs://")
    bucket, _, name = path.partition("/")
    if not bucket or not name:
        return ""
    return f"https://storage.googleapis.com/{bucket}/{name}"


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
        fields = [
            "is_target", "channel_id", "title", "relation_type", "content_category",
            "watch_scope", "analysis_status", "video_count",
        ]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: getattr(row, field) for field in fields})


def write_content_scope_csv(path: Path, videos: list[dict[str, object]]) -> None:
    grouped: dict[tuple[object, ...], dict[str, object]] = {}
    for video in videos:
        flags = ",".join(str(x) for x in video.get("content_flags", []))
        key = (
            bool(video.get("default_visible", True)),
            str(video.get("scope_type", "")),
            flags,
            str(video.get("channel_id", "")),
            str(video.get("channel", "")),
        )
        row = grouped.setdefault(
            key,
            {
                "default_visible": key[0],
                "scope_type": key[1],
                "content_flags": key[2],
                "channel_id": key[3],
                "channel": key[4],
                "video_count": 0,
                "sources": set(),
            },
        )
        row["video_count"] = int_value(row["video_count"]) + 1
        sources = row["sources"]
        if isinstance(sources, set):
            sources.add(str(video.get("source_type", "")))

    fields = [
        "default_visible", "scope_type", "content_flags", "channel_id",
        "channel", "video_count", "sources",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in sorted(
            grouped.values(),
            key=lambda x: (not bool(x["default_visible"]), str(x["scope_type"]), -int_value(x["video_count"]), str(x["channel"])),
        ):
            output = dict(row)
            output["sources"] = ",".join(sorted(output["sources"])) if isinstance(output["sources"], set) else ""
            writer.writerow(output)


if __name__ == "__main__":
    raise SystemExit(main())
