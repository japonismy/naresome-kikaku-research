# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from google.cloud import bigquery


PROJECT_ID = "rugged-destiny-408613"
DATASET = "naresome_all"
DATA_DIR = Path("data")
REPORT_DIR = Path("reports")
SOURCE_DIR = Path("data_sources")
OBSERVED_SUPPLEMENT_CSV = SOURCE_DIR / "observed_archive_supplement.csv"
CHANNEL_DISPLAY_RULES_CSV = SOURCE_DIR / "channel_display_rules.csv"
FORMER_COMPETITOR_CHANNELS_CSV = SOURCE_DIR / "former_competitor_channels.csv"
BASELINE_COMPETITOR_CHANNELS_CSV = SOURCE_DIR / "baseline_competitor_channels.csv"
YOUTUBE_CURRENT_STATS_CSV = SOURCE_DIR / "youtube_current_stats.csv"
YOUTUBE_CHANNEL_STATUS_CSV = SOURCE_DIR / "youtube_channel_status.csv"
THUMBNAIL_ASSET_OVERRIDES_CSV = SOURCE_DIR / "thumbnail_asset_overrides.csv"
ARCHIVE_THUMBNAIL_ASSETS_CSV = REPORT_DIR / "archive_thumbnail_assets_manifest.csv"
ARCHIVE_SCRIPT_LINKS_CSV = REPORT_DIR / "archive_script_asset_links.csv"
DIGEST_CHARS = 1600
INACTIVE_DAYS = 45
HIDDEN_FLAGS = {"adult", "manga_reference", "out_of_scope"}
CATEGORY_LABELS = {
    "self": "自チャンネル",
    "related": "関連チャンネル",
    "direct_a": "直接競合A",
    "direct_b": "直接競合B",
    "adjacent": "周辺競合",
}
ADULT_TITLE_RE = re.compile(
    r"(?:セックス|セク依存|S(?:EX|[〇○◯●]X)|エッチ|エッ[〇○◯●]|エ[〇○◯●]チ|"
    r"オ[〇○◯●]?ナニー|オ[〇○◯●]ニー|風俗|風[〇○◯●]|AV女優|A[〇○◯●]女優|"
    r"ヤリまく|ヤって|ヤらせ|中出し|中[〇○◯●]し|中に出して|ノーパン|"
    r"ノー[〇○◯●ー]?ブラ|全裸|全[〇○◯●]|全ネ果|爆乳|巨乳|精力剤|"
    r"ラブホ(?:テル)?|ラ[〇○◯●]ホ|Lホテル|ソープ|デリヘル|アソコ|"
    r"あそこ.*(?:触|舐|挟)|おっ?[〇○◯●]い|おっぱい|乳房|勃起|フル[〇○◯●]?ッキ|"
    r"パンツ|パン[〇○◯●]|パ[〇○◯●]ツ|下着|スカート.*(?:中|めく|捲|覗)|"
    r"裸|着替え.*(?:遭遇|見|覗)|押し倒|舐め|ペロペロ|揉ん|お股を広げ|"
    r"息子.*(?:暴走|触|サワ|大き|入れ|丸出し|巨大|立派|見せ|匂)|俺のアレ|アレを(?:食|触|舐)|"
    r"玉や竿|マグナム|暴れ龍|デリケートゾーン|メンエス|エ[ロ●]垢|Gカップ|股間|"
    r"子作りを迫|寝てあげる|アワビ|キノコを添|泡のお店|1人処理|初夜|"
    r"媚[薬〇○◯●]|欲[求〇○◯●]不満|美尻|豊満ボディ|びしょびしょ熟女|デカメロン|"
    r"使用済.*ティッシュ|下の処理|めちゃ(?:くちゃ|めちゃ).*[〇○◯●]ッ|"
    r"初体験|初めてを約束|私を大人にして|ヤリ目|ヤラせ|セクシー.*アノ声|"
    r"オカズに|(?:夜|隣).*アノ声|一人で始め|ア[〇○◯●]コ|[〇○◯●]欲|[〇○◯●]乳|"
    r"アブナイところ.*触|お尻.*触|胸.*(?:触|手を入|押し付|先端|谷間.*見|手を突っ込)|"
    r"大きな胸で迫|脱がして.*ボイン|生理現象でたって|"
    r"大人のおもちゃ|筆お[〇○◯●]し|ゴムが落ち|1発1万)",
    re.IGNORECASE,
)
MANGA_TITLE_RE = re.compile(r"(?:【漫画】|【恋愛漫画】|ラブコメ漫画|ボイコミ)")


def main() -> int:
    DATA_DIR.mkdir(exist_ok=True)
    REPORT_DIR.mkdir(exist_ok=True)
    SOURCE_DIR.mkdir(exist_ok=True)
    client = bigquery.Client(project=PROJECT_ID)
    baseline_registry_source = load_baseline_competitor_channels()
    baseline_registry = [
        row
        for row in baseline_registry_source
        if not compact_text(row.get("portal_scope", "")).startswith("exclude")
    ]
    excluded_baseline_registry = [
        row
        for row in baseline_registry_source
        if compact_text(row.get("portal_scope", "")).startswith("exclude")
    ]
    baseline_titles = {normalize_channel_title(row["channel_name"]) for row in baseline_registry}
    channel_metrics = list(client.query(channel_metrics_query()).result())
    baseline_channels, baseline_channel_ids = merge_baseline_registry(baseline_registry, channel_metrics)
    youtube_channel_status_summary = attach_youtube_channel_status(baseline_channels)
    prior_videos = read_js_data(DATA_DIR / "videos.js", "VIDEO_DATA")
    prior_transcripts = read_js_data(DATA_DIR / "transcripts_light.js", "TRANSCRIPT_DATA")

    videos = []
    video_by_id = {}
    descriptions = []
    missing = []
    for row in client.query(video_query(baseline_channel_ids)).result():
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
            "script_csv_url": row.public_csv_url or gcs_public_url(row.gcs_csv_uri or ""),
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
            "youtube_availability": "",
            "availability_checked_at": "",
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

    supplement_summary = load_observed_supplements(videos, video_by_id, baseline_titles)
    prior_snapshot_summary = merge_prior_portal_snapshot(
        videos,
        video_by_id,
        prior_videos,
        baseline_channels,
    )
    archive_asset_summary = attach_archive_asset_manifests(video_by_id)
    youtube_stats_summary = load_youtube_current_stats(videos, video_by_id)
    descriptions = merge_prior_transcripts(descriptions, prior_transcripts, set(video_by_id))
    classification_summary = classify_videos(videos, {})
    source_videos = len(videos)
    excluded_videos = [video for video in videos if set(video.get("content_flags", [])) & HIDDEN_FLAGS]
    videos = [video for video in videos if not (set(video.get("content_flags", [])) & HIDDEN_FLAGS)]
    public_video_ids = {str(video["video_id"]) for video in videos}
    descriptions = [row for row in descriptions if str(row["video_id"]) in public_video_ids]
    missing = [
        {
            "video_id": video["video_id"],
            "channel": video.get("channel", ""),
            "title": video.get("title", ""),
            "view_count": video.get("view_count", 0),
            "published_at": video.get("published_at", ""),
            "fetched_at": video.get("fetched_at", ""),
            "thumbnail_url": video.get("thumbnail_url", ""),
        }
        for video in videos
        if not compact_text(video.get("thumbnail_text", ""))
    ]
    videos.sort(key=lambda v: int_value(v.get("max_observed_view_count", v.get("view_count", 0))), reverse=True)
    attach_portal_metrics(baseline_channels, videos)
    validate_baseline_output(baseline_channels, videos)
    write_js(DATA_DIR / "videos.js", "VIDEO_DATA", videos)
    write_js(DATA_DIR / "transcripts_light.js", "TRANSCRIPT_DATA", descriptions)
    write_js(DATA_DIR / "channels.js", "CHANNEL_DATA", baseline_channels)
    write_missing_csv(REPORT_DIR / "thumbnail_text_missing.csv", missing)
    write_content_scope_csv(REPORT_DIR / "content_scope.csv", videos)
    write_content_scope_csv(REPORT_DIR / "excluded_content_scope.csv", excluded_videos)
    channels = list(client.query(channel_scope_query()).result())
    write_channel_scope_csv(REPORT_DIR / "channel_scope.csv", channels)
    write_baseline_registry_match_csv(REPORT_DIR / "competitor_registry_match.csv", baseline_channels)
    summary = {
        "videos": len(videos),
        "source_videos_before_scope_filter": source_videos,
        "scope_excluded_videos": len(excluded_videos),
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
        "supplement_rows_skipped_not_allowlisted": supplement_summary["skipped_not_allowlisted"],
        "observed_supplement_rows": supplement_summary["rows"],
        "observed_supplement_path": str(OBSERVED_SUPPLEMENT_CSV),
        "prior_portal_snapshot_rows": prior_snapshot_summary["rows"],
        "prior_portal_snapshot_inserted": prior_snapshot_summary["inserted"],
        "prior_portal_snapshot_skipped_out_of_scope": prior_snapshot_summary["skipped_out_of_scope"],
        "archive_thumbnail_manifest_rows": archive_asset_summary["thumbnail_rows"],
        "archive_thumbnail_manifest_matched": archive_asset_summary["thumbnail_matched"],
        "archive_thumbnail_manifest_attached": archive_asset_summary["thumbnail_attached"],
        "archive_script_link_rows": archive_asset_summary["script_rows"],
        "archive_script_link_matched": archive_asset_summary["script_matched"],
        "archive_script_link_attached": archive_asset_summary["script_attached"],
        "thumbnail_override_rows": archive_asset_summary["override_rows"],
        "thumbnail_override_matched": archive_asset_summary["override_matched"],
        "thumbnail_override_attached": archive_asset_summary["override_attached"],
        "baseline_registry_source_channels": len(baseline_registry_source),
        "baseline_registry_channels": len(baseline_channels),
        "baseline_registry_excluded_channels": len(excluded_baseline_registry),
        "baseline_registry_excluded_names": [
            str(row.get("channel_name", "")) for row in excluded_baseline_registry
        ],
        "baseline_registry_path": str(BASELINE_COMPETITOR_CHANNELS_CSV),
        "baseline_registry_canonical_ids": sum(
            1 for c in baseline_channels if compact_text(c["canonical_channel_id"])
        ),
        "baseline_registry_bq_matched": sum(1 for c in baseline_channels if c["match_status"] == "BQ突合済み"),
        "baseline_registry_db_data": sum(1 for c in baseline_channels if c["data_status"] == "DBデータあり"),
        "baseline_registry_saved_data": sum(1 for c in baseline_channels if c["data_status"] == "保存データあり"),
        "baseline_registry_no_data": sum(1 for c in baseline_channels if c["data_status"] == "データなし"),
        "baseline_registry_updating": sum(1 for c in baseline_channels if c["lifecycle"] == "競合・更新あり"),
        "baseline_registry_stopped_with_data": sum(
            1
            for c in baseline_channels
            if str(c["lifecycle"]).startswith("過去競合") and c["data_status"] != "データなし"
        ),
        "baseline_registry_with_backup": sum(
            1 for c in baseline_channels if c["backup_status"] != "なし"
        ),
        "baseline_history_preserved_videos": sum(
            int_value(c["history_preserved_count"]) for c in baseline_channels
        ),
        "baseline_git_snapshot_target_videos": sum(
            int_value(c["portal_video_count"]) for c in baseline_channels
        ),
        "youtube_current_stats_rows": youtube_stats_summary["rows"],
        "youtube_current_stats_merged": youtube_stats_summary["merged"],
        "youtube_current_stats_unavailable_marked": youtube_stats_summary["unavailable_marked"],
        "youtube_current_stats_path": str(YOUTUBE_CURRENT_STATS_CSV),
        "youtube_channel_status_rows": youtube_channel_status_summary["rows"],
        "youtube_channel_status_public": youtube_channel_status_summary["public"],
        "youtube_channel_status_unavailable": youtube_channel_status_summary["unavailable"],
        "youtube_channel_status_path": str(YOUTUBE_CHANNEL_STATUS_CSV),
        "scope_mode": "baseline_registry_only",
        "legacy_former_competitor_allowlist_used": False,
        "channel_display_rules_used": 0,
        "default_visible_videos": len(videos),
        "default_hidden_videos": 0,
        "adult_flagged_videos": classification_summary.get("adult", 0),
        "manga_reference_flagged_videos": classification_summary.get("manga_reference", 0),
        "out_of_scope_flagged_videos": classification_summary.get("out_of_scope", 0),
        "bq_legacy_target_channels_reference": sum(1 for c in channels if c.is_target),
        "bq_legacy_excluded_channels_reference": sum(1 for c in channels if not c.is_target),
        "source": "bigquery",
    }
    (REPORT_DIR / "build_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def video_query(channel_ids: list[str]) -> str:
    safe_ids = []
    for channel_id in channel_ids:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", channel_id):
            raise ValueError(f"Unsafe channel_id: {channel_id}")
        safe_ids.append(channel_id)
    if not safe_ids:
        raise ValueError("No baseline competitor channel IDs matched BigQuery")
    channel_id_sql = ", ".join(f"'{channel_id}'" for channel_id in sorted(set(safe_ids)))
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
    WHERE v.channel_id IN ({channel_id_sql})
      AND (v.duration_sec IS NULL OR v.duration_sec >= 120)
    ORDER BY COALESCE(v.view_count, 0) DESC
    """


def channel_metrics_query() -> str:
    return f"""
    WITH db_videos AS (
      SELECT
        'current' AS source_type,
        video_id,
        channel_id,
        published_at,
        view_count
      FROM `{PROJECT_ID}.{DATASET}.videos`
      UNION ALL
      SELECT
        'archive' AS source_type,
        a.video_id,
        a.channel_id,
        a.published_at,
        a.view_count
      FROM `{PROJECT_ID}.{DATASET}.videos_archive_20260527` a
      WHERE NOT EXISTS (
        SELECT 1
        FROM `{PROJECT_ID}.{DATASET}.videos` cur
        WHERE cur.video_id = a.video_id
      )
    )
    SELECT
      c.channel_id,
      c.handle,
      c.title,
      c.subscriber_count,
      c.video_count,
      c.total_view_count,
      c.status AS channel_status,
      c.relation_type,
      c.analysis_status,
      c.last_synced_at,
      COUNT(v.video_id) AS db_video_rows,
      COUNTIF(v.source_type = 'current') AS current_db_video_rows,
      COUNTIF(v.source_type = 'archive') AS archive_db_video_rows,
      COUNTIF(COALESCE(v.view_count, 0) > 0) AS rows_with_views,
      COALESCE(SUM(v.view_count), 0) AS db_sum_video_views,
      MAX(v.published_at) AS latest_video
    FROM `{PROJECT_ID}.{DATASET}.channels` c
    LEFT JOIN db_videos v
      USING(channel_id)
    GROUP BY
      c.channel_id, c.handle, c.title, c.subscriber_count, c.video_count,
      c.total_view_count, c.status, c.relation_type, c.analysis_status, c.last_synced_at
    ORDER BY c.title
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
        COALESCE(relation_type, 'competitor') IN ('competitor', 'migration_or_related_competitor')
        AND COALESCE(analysis_status, 'active') NOT IN ('exclude_from_naresome_competitor_analysis')
      ) AS is_target
    FROM `{PROJECT_ID}.{DATASET}.channels`
    ORDER BY is_target DESC, relation_type, analysis_status, video_count DESC, title
    """


def load_baseline_competitor_channels() -> list[dict[str, object]]:
    if not BASELINE_COMPETITOR_CHANNELS_CSV.exists():
        raise FileNotFoundError(f"Baseline competitor registry not found: {BASELINE_COMPETITOR_CHANNELS_CSV}")
    rows: list[dict[str, object]] = []
    with BASELINE_COMPETITOR_CHANNELS_CSV.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row["provided_subscribers"] = int_value(row.get("provided_subscribers"))
            rows.append(row)
    if len(rows) != 33:
        raise ValueError(f"Baseline competitor registry must contain exactly 33 channels; found {len(rows)}")
    handles = [normalize_handle(row.get("handle", "")) for row in rows]
    duplicates = sorted({handle for handle in handles if handle and handles.count(handle) > 1})
    if duplicates:
        raise ValueError(f"Duplicate handles in baseline competitor registry: {duplicates}")
    if any(not handle for handle in handles):
        raise ValueError("Every baseline competitor channel must have a handle")
    canonical_ids = [compact_text(row.get("canonical_channel_id", "")) for row in rows]
    invalid_ids = [
        channel_id
        for channel_id in canonical_ids
        if channel_id and not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", channel_id)
    ]
    if invalid_ids:
        raise ValueError(f"Invalid canonical channel IDs in baseline registry: {invalid_ids}")
    duplicate_ids = sorted({
        channel_id
        for channel_id in canonical_ids
        if channel_id and canonical_ids.count(channel_id) > 1
    })
    if duplicate_ids:
        raise ValueError(f"Duplicate canonical channel IDs in baseline registry: {duplicate_ids}")
    return rows


def merge_baseline_registry(
    registry: list[dict[str, object]],
    db_rows: list[object],
) -> tuple[list[dict[str, object]], list[str]]:
    by_id = {str(row.channel_id): row for row in db_rows if compact_text(row.channel_id)}
    by_handle = {normalize_handle(row.handle): row for row in db_rows if normalize_handle(row.handle)}
    by_title = {normalize_channel_title(row.title): row for row in db_rows if normalize_channel_title(row.title)}
    channels: list[dict[str, object]] = []
    matched_channel_ids: list[str] = []
    for entry in registry:
        canonical_channel_id = compact_text(entry.get("canonical_channel_id", ""))
        row = by_id.get(canonical_channel_id) if canonical_channel_id else None
        match_method = "canonical_channel_id" if row is not None else ""
        if row is None:
            row = by_handle.get(normalize_handle(entry.get("handle", "")))
            if row is not None:
                match_method = "handle"
        if row is None:
            row = by_title.get(normalize_channel_title(entry.get("channel_name", "")))
            if row is not None:
                match_method = "title"
        matched = row is not None
        category = str(entry.get("category", ""))
        db_video_rows = int(row.db_video_rows or 0) if matched else 0
        current_db_video_rows = int(row.current_db_video_rows or 0) if matched else 0
        archive_db_video_rows = int(row.archive_db_video_rows or 0) if matched else 0
        latest_video = str(row.latest_video or "") if matched else ""
        item = {
            "channel_id": (
                str(row.channel_id)
                if matched
                else canonical_channel_id
                if canonical_channel_id
                else f"manual:{normalize_handle(entry.get('handle', ''))}"
            ),
            "canonical_channel_id": canonical_channel_id,
            "channel_name": str(entry.get("channel_name", "")),
            "portal_channel_name": str(row.title or "") if matched else str(entry.get("channel_name", "")),
            "db_title": str(row.title or "") if matched else "",
            "handle": "@" + normalize_handle(entry.get("handle", "")),
            "category": category,
            "category_label": CATEGORY_LABELS.get(category, category),
            "reference_status": str(entry.get("reference_status", "")),
            "historical_reference": category not in ("self", "related"),
            "provided_subscribers": int_value(entry.get("provided_subscribers")),
            "subscriber_count": int(
                row.subscriber_count
                if matched and row.subscriber_count is not None
                else int_value(entry.get("provided_subscribers"))
            ),
            "channel_status": str(row.channel_status or "") if matched else "",
            "channel_availability": "",
            "youtube_channel_title": "",
            "youtube_video_count": 0,
            "latest_public_video": "",
            "latest_public_video_id": "",
            "last_channel_check": "",
            "db_current_video_count": int(row.video_count or 0) if matched else 0,
            "current_db_video_rows": current_db_video_rows,
            "archive_db_video_rows": archive_db_video_rows,
            "db_channel_total_views": int(row.total_view_count or 0) if matched else 0,
            "db_video_rows": db_video_rows,
            "db_rows_with_views": int(row.rows_with_views or 0) if matched else 0,
            "db_sum_video_views": int(row.db_sum_video_views or 0) if matched else 0,
            "latest_video": latest_video,
            "last_synced_at": str(row.last_synced_at or "") if matched else "",
            "data_available": db_video_rows > 0,
            "data_status": "DBデータあり" if db_video_rows > 0 else "データなし",
            "match_status": "BQ突合済み" if matched else "BQ未登録",
            "match_method": match_method,
            "lifecycle": "更新状況未確認",
            "realtime_target": False,
            "monitor_policy": "weekly_restart_check",
            "backup_status": backup_status(0, 0, db_video_rows),
            "note": str(entry.get("note", "")),
            "youtube_url": f"https://www.youtube.com/@{normalize_handle(entry.get('handle', ''))}",
            "portal_video_count": 0,
            "portal_view_sum": 0,
            "portal_latest_video": "",
            "portal_source_types": "",
            "snapshot_archive_count": 0,
            "observed_archive_count": 0,
            "history_preserved_count": archive_db_video_rows,
            "thumbnail_available_count": 0,
            "thumbnail_preserved_count": 0,
            "script_asset_count": 0,
            "asset_status": "動画データなし",
        }
        channels.append(item)
        if matched:
            matched_channel_ids.append(str(row.channel_id))
    return channels, sorted(set(matched_channel_ids))


def attach_youtube_channel_status(channels: list[dict[str, object]]) -> dict[str, int]:
    summary = {"rows": 0, "public": 0, "unavailable": 0}
    if not YOUTUBE_CHANNEL_STATUS_CSV.exists():
        return summary
    by_id = {str(channel["channel_id"]): channel for channel in channels}
    with YOUTUBE_CHANNEL_STATUS_CSV.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            summary["rows"] += 1
            channel = by_id.get(compact_text(row.get("channel_id", "")))
            if channel is None:
                continue
            availability = compact_text(row.get("availability", ""))
            channel["channel_availability"] = availability
            channel["youtube_channel_title"] = compact_text(row.get("youtube_channel_title", ""))
            channel["youtube_video_count"] = int_value(row.get("video_count"))
            channel["latest_public_video"] = compact_text(row.get("latest_published_at", ""))
            channel["latest_public_video_id"] = compact_text(row.get("latest_video_id", ""))
            channel["last_channel_check"] = compact_text(row.get("checked_at", ""))
            if compact_text(row.get("subscriber_count", "")):
                channel["subscriber_count"] = int_value(row.get("subscriber_count"))
            if availability == "public":
                summary["public"] += 1
            else:
                summary["unavailable"] += 1
    return summary


def attach_portal_metrics(channels: list[dict[str, object]], videos: list[dict[str, object]]) -> None:
    by_id = {
        str(channel["channel_id"]): channel
        for channel in channels
        if not str(channel["channel_id"]).startswith("manual:")
    }
    by_title: dict[str, dict[str, object]] = {}
    for channel in channels:
        for title in (channel["channel_name"], channel["db_title"], channel["portal_channel_name"]):
            normalized = normalize_channel_title(title)
            if normalized:
                by_title[normalized] = channel

    source_types: dict[str, set[str]] = {str(channel["channel_id"]): set() for channel in channels}
    for video in videos:
        channel = by_id.get(str(video.get("channel_id", "")))
        if channel is None:
            channel = by_title.get(normalize_channel_title(video.get("channel", "")))
        if channel is None:
            continue
        channel["portal_channel_name"] = str(video.get("channel", "")) or str(channel["portal_channel_name"])
        channel["portal_video_count"] = int_value(channel["portal_video_count"]) + 1
        channel["portal_view_sum"] = int_value(channel["portal_view_sum"]) + int_value(
            video.get("max_observed_view_count", video.get("view_count", 0))
        )
        published_at = compact_text(video.get("published_at", ""))
        if published_at > compact_text(channel["portal_latest_video"]):
            channel["portal_latest_video"] = published_at
        if (
            compact_text(video.get("thumbnail_url", ""))
            or compact_text(video.get("thumbnail_saved_url", ""))
            or compact_text(video.get("thumbnail_max_url", ""))
        ):
            channel["thumbnail_available_count"] = int_value(channel["thumbnail_available_count"]) + 1
        if compact_text(video.get("thumbnail_gcs_uri", "")) or compact_text(video.get("thumbnail_saved_url", "")):
            channel["thumbnail_preserved_count"] = int_value(channel["thumbnail_preserved_count"]) + 1
        if bool(video.get("script_asset_available")):
            channel["script_asset_count"] = int_value(channel["script_asset_count"]) + 1
        source_type = compact_text(video.get("source_type", ""))
        source_types[str(channel["channel_id"])].add(source_type)
        if source_type == "portal_snapshot_archive":
            channel["snapshot_archive_count"] = int_value(channel["snapshot_archive_count"]) + 1
        if source_type == "observed_archive":
            channel["observed_archive_count"] = int_value(channel["observed_archive_count"]) + 1

    for channel in channels:
        portal_count = int_value(channel["portal_video_count"])
        db_count = int_value(channel["db_video_rows"])
        current_count = int_value(channel["current_db_video_rows"])
        archive_count = int_value(channel["archive_db_video_rows"])
        history_count = min(
            portal_count,
            archive_count
            + int_value(channel["snapshot_archive_count"])
            + int_value(channel["observed_archive_count"]),
        )
        channel["history_preserved_count"] = history_count
        channel["data_available"] = db_count > 0 or portal_count > 0
        channel["data_status"] = (
            "DBデータあり"
            if db_count > 0
            else "保存データあり"
            if portal_count > 0
            else "データなし"
        )
        latest = compact_text(channel["latest_video"]) or compact_text(channel["portal_latest_video"])
        channel["lifecycle"] = lifecycle_label(
            data_available=bool(channel["data_available"]),
            current_db_video_rows=current_count,
            db_channel_video_count=int_value(channel["db_current_video_count"]),
            latest_saved_video=latest,
            channel_status=compact_text(channel["channel_status"]),
            channel_availability=compact_text(channel["channel_availability"]),
            youtube_video_count=int_value(channel["youtube_video_count"]),
            latest_public_video=compact_text(channel["latest_public_video"]),
            last_channel_check=compact_text(channel["last_channel_check"]),
            last_synced_at=compact_text(channel["last_synced_at"]),
        )
        channel["realtime_target"] = channel["lifecycle"] == "競合・更新あり"
        channel["monitor_policy"] = (
            "daily_new_video_and_stats"
            if channel["realtime_target"]
            else "weekly_restart_check"
        )
        channel["backup_status"] = backup_status(portal_count, history_count, db_count)
        channel["portal_source_types"] = ",".join(
            sorted(source for source in source_types[str(channel["channel_id"])] if source)
        )
        if portal_count:
            channel["asset_status"] = (
                f"サムネ保全 {int_value(channel['thumbnail_preserved_count'])}/{portal_count}"
                f"・台本 {int_value(channel['script_asset_count'])}/{portal_count}"
            )


def validate_baseline_output(
    channels: list[dict[str, object]],
    videos: list[dict[str, object]],
) -> None:
    if len(channels) != 32:
        raise ValueError(f"Expected 32 public baseline channels after the explicit adult exclusion; found {len(channels)}")
    allowed_ids = {str(channel["channel_id"]) for channel in channels}
    allowed_titles = {
        normalize_channel_title(title)
        for channel in channels
        for title in (channel["channel_name"], channel["db_title"], channel["portal_channel_name"])
        if normalize_channel_title(title)
    }
    unexpected = sorted({
        f"{video.get('channel_id', '')}:{video.get('channel', '')}"
        for video in videos
        if str(video.get("channel_id", "")) not in allowed_ids
        and normalize_channel_title(video.get("channel", "")) not in allowed_titles
    })
    if unexpected:
        raise ValueError(f"Out-of-scope videos entered the baseline portal: {unexpected[:10]}")


def lifecycle_label(
    *,
    data_available: bool,
    current_db_video_rows: int,
    db_channel_video_count: int,
    latest_saved_video: str,
    channel_status: str,
    channel_availability: str,
    youtube_video_count: int,
    latest_public_video: str,
    last_channel_check: str,
    last_synced_at: str,
) -> str:
    youtube_status_is_fresh = is_recent_date(last_channel_check, 3)
    if youtube_status_is_fresh and channel_availability:
        if channel_availability != "public":
            return "過去競合・現在非公開"
        if youtube_video_count <= 0:
            return "過去競合・現在公開なし"
        latest_public = parse_iso_date(latest_public_video) or parse_iso_date(latest_saved_video)
        if latest_public and latest_public < date.today() - timedelta(days=INACTIVE_DAYS):
            return "過去競合・更新停止"
        if latest_public:
            return "競合・更新あり"
        return "競合・公開中・最新日未確認"

    normalized_status = channel_status.casefold()
    if normalized_status in {"no_videos", "unavailable", "deleted", "inactive"}:
        return "過去競合・現在公開なし"
    if db_channel_video_count <= 0 and current_db_video_rows <= 0:
        return "過去競合・データなし" if not data_available else "過去競合・現在公開なし"
    if last_synced_at and not is_recent_date(last_synced_at, 7):
        return "競合・同期状況要確認"
    parsed = parse_iso_date(latest_saved_video)
    if parsed and parsed < date.today() - timedelta(days=INACTIVE_DAYS):
        return "過去競合・更新停止"
    if parsed:
        return "競合・更新あり"
    return "競合・更新状況未確認"


def is_recent_date(value: str, days: int) -> bool:
    parsed = parse_iso_date(value)
    return bool(parsed and parsed >= date.today() - timedelta(days=days))


def backup_status(portal_video_count: int, history_preserved_count: int, db_video_rows: int) -> str:
    if portal_video_count > 0 and history_preserved_count > 0:
        return f"履歴保全 {history_preserved_count}/{portal_video_count}・Git差分保全"
    if portal_video_count > 0:
        return f"Git前回差分保全 {portal_video_count}本"
    if db_video_rows > 0:
        return "DB保存のみ"
    return "なし"


def parse_iso_date(value: str) -> date | None:
    text = compact_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.date()
        return parsed.astimezone(timezone.utc).date()
    except ValueError:
        return None


def normalize_handle(value: object) -> str:
    return normalize_channel_title(value).lstrip("@")


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


def load_former_competitor_channels() -> set[str]:
    if not FORMER_COMPETITOR_CHANNELS_CSV.exists():
        return set()
    with FORMER_COMPETITOR_CHANNELS_CSV.open("r", newline="", encoding="utf-8-sig") as f:
        return {
            normalize_channel_title(row.get("channel_title", ""))
            for row in csv.DictReader(f)
            if normalize_channel_title(row.get("channel_title", ""))
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


def load_observed_supplements(
    videos: list[dict[str, object]],
    video_by_id: dict[str, dict[str, object]],
    former_competitor_channels: set[str],
) -> dict[str, int]:
    summary = {"rows": 0, "inserted": 0, "updated": 0, "skipped_not_allowlisted": 0}
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

            channel_title = normalize_channel_title(row.get("channel_title", ""))
            if channel_title not in former_competitor_channels:
                summary["skipped_not_allowlisted"] += 1
                continue

            item = make_supplement_video(vid, row, observed)
            videos.append(item)
            video_by_id[vid] = item
            summary["inserted"] += 1
    return summary


def read_js_data(path: Path, variable_name: str) -> list[dict[str, object]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8").strip()
    prefix = f"window.{variable_name} = "
    if not text.startswith(prefix):
        return []
    payload = text[len(prefix):]
    if payload.endswith(";"):
        payload = payload[:-1]
    parsed = json.loads(payload)
    if not isinstance(parsed, list):
        return []
    return [row for row in parsed if isinstance(row, dict)]


def merge_prior_portal_snapshot(
    videos: list[dict[str, object]],
    video_by_id: dict[str, dict[str, object]],
    prior_videos: list[dict[str, object]],
    baseline_channels: list[dict[str, object]],
) -> dict[str, int]:
    summary = {"rows": len(prior_videos), "inserted": 0, "skipped_out_of_scope": 0}
    allowed_ids = {
        str(channel["channel_id"])
        for channel in baseline_channels
        if not str(channel["channel_id"]).startswith("manual:")
    }
    allowed_titles = {
        normalize_channel_title(title)
        for channel in baseline_channels
        for title in (channel["channel_name"], channel["db_title"], channel["portal_channel_name"])
        if normalize_channel_title(title)
    }
    for row in prior_videos:
        video_id = compact_text(row.get("video_id", ""))
        if not video_id or video_id in video_by_id:
            continue
        channel_id = compact_text(row.get("channel_id", ""))
        channel_title = normalize_channel_title(row.get("channel", ""))
        if channel_id not in allowed_ids and channel_title not in allowed_titles:
            summary["skipped_out_of_scope"] += 1
            continue
        item = dict(row)
        item["source_type"] = "portal_snapshot_archive"
        item["scope_type"] = "baseline_portal_snapshot"
        item["analysis_status"] = "historical_snapshot"
        item["is_archive"] = True
        item["archive_type"] = "git_portal_snapshot"
        item["default_visible"] = True
        item["classification_reason"] = "前回公開データからの履歴保全"
        script_gcs_uri = compact_text(item.get("script_gcs_uri", ""))
        if script_gcs_uri and not compact_text(item.get("script_csv_url", "")):
            item["script_csv_url"] = gcs_public_url(script_gcs_uri)
        thumbnail_gcs_uri = compact_text(item.get("thumbnail_gcs_uri", ""))
        if thumbnail_gcs_uri and not compact_text(item.get("thumbnail_saved_url", "")):
            item["thumbnail_saved_url"] = gcs_public_url(thumbnail_gcs_uri)
        sources = [str(source) for source in item.get("observation_sources", []) if source]
        if "portal_snapshot_archive" not in sources:
            sources.append("portal_snapshot_archive")
        item["observation_sources"] = sources
        videos.append(item)
        video_by_id[video_id] = item
        summary["inserted"] += 1
    return summary


def merge_prior_transcripts(
    current: list[dict[str, object]],
    prior: list[dict[str, object]],
    allowed_video_ids: set[str],
) -> list[dict[str, object]]:
    merged = {compact_text(row.get("video_id", "")): row for row in current if compact_text(row.get("video_id", ""))}
    for row in prior:
        video_id = compact_text(row.get("video_id", ""))
        if video_id and video_id in allowed_video_ids and video_id not in merged:
            merged[video_id] = row
    return list(merged.values())


def attach_archive_asset_manifests(
    video_by_id: dict[str, dict[str, object]],
) -> dict[str, int]:
    summary = {
        "thumbnail_rows": 0,
        "thumbnail_matched": 0,
        "thumbnail_attached": 0,
        "script_rows": 0,
        "script_matched": 0,
        "script_attached": 0,
        "override_rows": 0,
        "override_matched": 0,
        "override_attached": 0,
    }
    if ARCHIVE_THUMBNAIL_ASSETS_CSV.exists():
        with ARCHIVE_THUMBNAIL_ASSETS_CSV.open("r", newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                summary["thumbnail_rows"] += 1
                video_id = compact_text(row.get("video_id", ""))
                video = video_by_id.get(video_id)
                if video is None:
                    continue
                summary["thumbnail_matched"] += 1
                gcs_uri = compact_text(row.get("gcs_uri", ""))
                if not gcs_uri or compact_text(video.get("thumbnail_gcs_uri", "")):
                    continue
                saved_url = gcs_public_url(gcs_uri)
                video["thumbnail_gcs_uri"] = gcs_uri
                video["thumbnail_saved_url"] = saved_url
                fallbacks = [
                    saved_url,
                    *[str(url) for url in video.get("thumbnail_fallback_urls", []) if url],
                ]
                video["thumbnail_fallback_urls"] = list(dict.fromkeys(url for url in fallbacks if url))
                summary["thumbnail_attached"] += 1

    if THUMBNAIL_ASSET_OVERRIDES_CSV.exists():
        with THUMBNAIL_ASSET_OVERRIDES_CSV.open("r", newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                summary["override_rows"] += 1
                video_id = compact_text(row.get("video_id", ""))
                video = video_by_id.get(video_id)
                if video is None:
                    continue
                summary["override_matched"] += 1
                gcs_uri = compact_text(row.get("gcs_uri", ""))
                if not gcs_uri or compact_text(video.get("thumbnail_gcs_uri", "")):
                    continue
                saved_url = gcs_public_url(gcs_uri)
                video["thumbnail_gcs_uri"] = gcs_uri
                video["thumbnail_saved_url"] = saved_url
                fallbacks = [
                    saved_url,
                    *[str(url) for url in video.get("thumbnail_fallback_urls", []) if url],
                ]
                video["thumbnail_fallback_urls"] = list(dict.fromkeys(url for url in fallbacks if url))
                summary["override_attached"] += 1

    if ARCHIVE_SCRIPT_LINKS_CSV.exists():
        with ARCHIVE_SCRIPT_LINKS_CSV.open("r", newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                summary["script_rows"] += 1
                video_id = compact_text(row.get("archive_video_id", ""))
                video = video_by_id.get(video_id)
                if video is None:
                    continue
                summary["script_matched"] += 1
                gcs_uri = compact_text(row.get("gcs_csv_uri", ""))
                public_url = compact_text(row.get("public_csv_url", "")) or gcs_public_url(gcs_uri)
                if not gcs_uri and not public_url:
                    continue
                if bool(video.get("script_asset_available")):
                    continue
                video["script_asset_available"] = True
                video["script_gcs_uri"] = gcs_uri
                video["script_csv_url"] = public_url
                summary["script_attached"] += 1
    return summary


def load_youtube_current_stats(videos: list[dict[str, object]], video_by_id: dict[str, dict[str, object]]) -> dict[str, int]:
    summary = {"rows": 0, "merged": 0, "unavailable_marked": 0}
    if not YOUTUBE_CURRENT_STATS_CSV.exists():
        return summary

    with YOUTUBE_CURRENT_STATS_CSV.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            summary["rows"] += 1
            video_id = compact_text(row.get("video_id", ""))
            view_count = compact_text(row.get("view_count", ""))
            item = video_by_id.get(video_id)
            if not item:
                continue
            availability = compact_text(row.get("availability", ""))
            item["youtube_availability"] = availability
            item["availability_checked_at"] = compact_text(row.get("checked_at", ""))
            if availability == "unavailable":
                summary["unavailable_marked"] += 1
                continue
            if not view_count:
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
        "youtube_availability": "",
        "availability_checked_at": "",
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
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_channel_scope_csv(path: Path, rows: list[object]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        fields = [
            "is_target", "channel_id", "title", "relation_type", "content_category",
            "watch_scope", "analysis_status", "video_count",
        ]
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: getattr(row, field) for field in fields})


def write_baseline_registry_match_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = [
        "category",
        "category_label",
        "channel_name",
        "db_title",
        "handle",
        "canonical_channel_id",
        "channel_id",
        "match_status",
        "match_method",
        "data_status",
        "lifecycle",
        "realtime_target",
        "monitor_policy",
        "backup_status",
        "subscriber_count",
        "channel_status",
        "channel_availability",
        "youtube_video_count",
        "latest_public_video",
        "last_channel_check",
        "db_current_video_count",
        "current_db_video_rows",
        "archive_db_video_rows",
        "db_video_rows",
        "db_sum_video_views",
        "portal_video_count",
        "portal_view_sum",
        "latest_video",
        "portal_latest_video",
        "last_synced_at",
        "snapshot_archive_count",
        "observed_archive_count",
        "history_preserved_count",
        "thumbnail_available_count",
        "thumbnail_preserved_count",
        "script_asset_count",
        "portal_source_types",
        "note",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


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
