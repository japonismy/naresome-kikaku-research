# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from google.cloud import bigquery


HERE = Path(__file__).resolve().parent
VAULT_ROOT = Path(r"c:\Data\ObsidianVault")
TOOLS_DIR = VAULT_ROOT / "04_Tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from core.config import Config  # noqa: E402


PROJECT_ID = "rugged-destiny-408613"
DATASET = "naresome_all"
TABLE = "thumbnail_ocr"
THUMB_DIRS = [
    HERE / "gcs_upload_staging" / "naresome_thumbnails",
    HERE / "thumbnail_assets",
]
REPORT_DIR = HERE / "reports"
REPORT_PATH = REPORT_DIR / "gemini_thumbnail_ocr_report.csv"
MODEL_ID = "gemini-2.5-flash-lite"

PROMPT = """You are analyzing a Japanese YouTube thumbnail for 2ch馴れ初め planning research.
Return only JSON.

Schema:
{
  "texts": [
    {"position": "top_upper", "text": "...", "category": "narration", "emphasis": false},
    {"position": "top_lower", "text": "...", "category": "narration", "emphasis": true},
    {"position": "center", "text": "...", "category": "dialogue", "emphasis": false},
    {"position": "bottom_upper", "text": "...", "category": "narration", "emphasis": true},
    {"position": "bottom_lower", "text": "...", "category": "narration", "emphasis": false}
  ],
  "combined": "all visible Japanese text in reading order",
  "notes": "short Japanese note if unreadable"
}

Rules:
- Extract only text visibly written on the thumbnail.
- Do not use the YouTube title unless it is visible in the image.
- Preserve Japanese wording as accurately as possible.
- If no readable text exists, use an empty combined string.
- position must be one of: top_upper, top_lower, center, bottom_upper, bottom_lower.
- category must be one of: narration, dialogue, logo, other.
- Return JSON only.
"""

TEXT_ONLY_PROMPT = """This is a Japanese YouTube thumbnail.
Extract only the visible text written on the image.
Return plain text only. Do not include explanations. Do not use the YouTube title unless it is visible in the image.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0 means all.")
    ap.add_argument("--sleep", type=float, default=0.25)
    ap.add_argument("--min-views", type=int, default=0)
    ap.add_argument("--model", default=MODEL_ID)
    ap.add_argument("--batch-size", type=int, default=20)
    ap.add_argument("--use-page-missing-only", action="store_true", default=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    REPORT_DIR.mkdir(exist_ok=True)
    client = load_genai_client()
    bq = bigquery.Client(project=PROJECT_ID)
    targets = load_targets(bq, args.min_views)
    if args.limit:
        targets = targets[: args.limit]
    print(json.dumps({"targets": len(targets), "model": args.model, "dry_run": args.dry_run}, ensure_ascii=False), flush=True)
    if args.dry_run:
        return 0

    rows = []
    pending_bq_rows = []
    ok = empty = fail = 0
    start = time.time()
    for i, video in enumerate(targets, 1):
        image_path = find_thumbnail(video["video_id"])
        if not image_path:
            fail += 1
            rows.append(report_row(video, "", "thumbnail_not_found"))
            continue
        try:
            ocr = ocr_image(client, args.model, image_path)
            bq_row = to_bq_row(video["video_id"], ocr)
            if bq_row["combined_text"]:
                ok += 1
            else:
                empty += 1
            rows.append(report_row(video, bq_row["combined_text"], bq_row["error"] or ""))
            if not args.dry_run:
                pending_bq_rows.append(bq_row)
        except Exception as e:
            fail += 1
            err = f"{type(e).__name__}: {str(e)[:180]}"
            rows.append(report_row(video, "", err))
            if not args.dry_run:
                pending_bq_rows.append(error_row(video["video_id"], err))

        if pending_bq_rows and (len(pending_bq_rows) >= args.batch_size or i == len(targets)):
            merge_rows(bq, pending_bq_rows)
            pending_bq_rows = []

        if i % 10 == 0 or i == len(targets):
            write_report(rows)
            elapsed = time.time() - start
            print(json.dumps({"done": i, "ok": ok, "empty": empty, "fail": fail, "minutes": round(elapsed / 60, 1)}, ensure_ascii=False), flush=True)
        time.sleep(args.sleep)

    write_report(rows)
    print(json.dumps({"processed": len(targets), "ok": ok, "empty": empty, "fail": fail, "report": str(REPORT_PATH)}, ensure_ascii=False), flush=True)
    return 0


def load_genai_client():
    from google import genai

    key = Config().gemini_api_key
    if not key:
        raise SystemExit("Gemini API key is not configured.")
    return genai.Client(api_key=key)


def load_targets(client: bigquery.Client, min_views: int) -> list[dict[str, object]]:
    text = (HERE / "data" / "videos.js").read_text(encoding="utf-8")
    videos = json.loads(text.removeprefix("window.VIDEO_DATA = ").strip().rstrip(";"))
    candidates = [
        v
        for v in videos
        if not (v.get("thumbnail_text") or "").strip()
        and int(v.get("view_count") or 0) >= min_views
        and find_thumbnail(v["video_id"])
    ]
    existing = load_existing_ocr_ids(client, [v["video_id"] for v in candidates])
    targets = [v for v in candidates if v["video_id"] not in existing]
    targets.sort(key=lambda v: int(v.get("view_count") or 0), reverse=True)
    return targets


def load_existing_ocr_ids(client: bigquery.Client, video_ids: list[str]) -> set[str]:
    if not video_ids:
        return set()
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("video_ids", "STRING", video_ids)]
    )
    rows = client.query(
        f"""
        SELECT video_id
        FROM `{PROJECT_ID}.{DATASET}.{TABLE}`
        WHERE video_id IS NOT NULL
          AND video_id IN UNNEST(@video_ids)
          AND (
            COALESCE(combined_text, '') != ''
            OR COALESCE(emphasis_text, '') != ''
            OR COALESCE(narration_text, '') != ''
            OR COALESCE(dialogue_text, '') != ''
          )
        """,
        job_config=job_config,
    ).result()
    return {r.video_id for r in rows}


def find_thumbnail(video_id: str) -> Path | None:
    for directory in THUMB_DIRS:
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            path = directory / f"{video_id}{ext}"
            if path.exists():
                return path
    return None


def ocr_image(client, model_id: str, image_path: Path) -> dict:
    from google.genai import types

    mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    image_part = types.Part.from_bytes(data=image_path.read_bytes(), mime_type=mime)
    resp = client.models.generate_content(
        model=model_id,
        contents=[PROMPT, image_part],
        config=types.GenerateContentConfig(temperature=0.0, response_mime_type="application/json"),
    )
    try:
        return parse_json(resp.text or "")
    except json.JSONDecodeError:
        fallback = client.models.generate_content(
            model=model_id,
            contents=[TEXT_ONLY_PROMPT, image_part],
            config=types.GenerateContentConfig(temperature=0.0),
        )
        text = clean_text(fallback.text or "")
        return {
            "texts": [{"position": "center", "text": text, "category": "narration", "emphasis": True}],
            "combined": text,
            "notes": "text_only_fallback",
        }


def parse_json(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t.removeprefix("json").strip()
    start, end = t.find("{"), t.rfind("}")
    if start >= 0 and end >= start:
        t = t[start : end + 1]
    return json.loads(t)


def to_bq_row(video_id: str, ocr: dict) -> dict[str, object]:
    texts = ocr.get("texts") or []

    def pick_pos(pos: str) -> str:
        return " / ".join(clean_text(t.get("text", "")) for t in texts if t.get("position") == pos and clean_text(t.get("text", "")))

    def pick_cat(cat: str) -> str:
        return " / ".join(clean_text(t.get("text", "")) for t in texts if t.get("category") == cat and clean_text(t.get("text", "")))

    emphasis = " / ".join(clean_text(t.get("text", "")) for t in texts if t.get("emphasis") and clean_text(t.get("text", "")))
    combined = clean_text(ocr.get("combined", ""))
    if not combined:
        combined = " ".join(clean_text(t.get("text", "")) for t in texts if clean_text(t.get("text", "")))
    return {
        "video_id": video_id,
        "combined_text": combined,
        "emphasis_text": emphasis,
        "narration_text": pick_cat("narration"),
        "dialogue_text": pick_cat("dialogue"),
        "top_upper_text": pick_pos("top_upper"),
        "top_lower_text": pick_pos("top_lower"),
        "center_text": pick_pos("center"),
        "bottom_upper_text": pick_pos("bottom_upper"),
        "bottom_lower_text": pick_pos("bottom_lower"),
        "raw_json": json.dumps(ocr, ensure_ascii=False, separators=(",", ":")),
        "notes": clean_text(ocr.get("notes", "")),
        "error": "",
        "analyzed_at": datetime.now().isoformat(timespec="seconds"),
    }


def error_row(video_id: str, error: str) -> dict[str, object]:
    return {
        "video_id": video_id,
        "combined_text": "",
        "emphasis_text": "",
        "narration_text": "",
        "dialogue_text": "",
        "top_upper_text": "",
        "top_lower_text": "",
        "center_text": "",
        "bottom_upper_text": "",
        "bottom_lower_text": "",
        "raw_json": "",
        "notes": "",
        "error": error,
        "analyzed_at": datetime.now().isoformat(timespec="seconds"),
    }


def merge_rows(client: bigquery.Client, rows: list[dict[str, object]]) -> None:
    tmp = f"{PROJECT_ID}.{DATASET}._thumbnail_ocr_updates"
    schema = [
        bigquery.SchemaField("video_id", "STRING"),
        bigquery.SchemaField("combined_text", "STRING"),
        bigquery.SchemaField("emphasis_text", "STRING"),
        bigquery.SchemaField("narration_text", "STRING"),
        bigquery.SchemaField("dialogue_text", "STRING"),
        bigquery.SchemaField("top_upper_text", "STRING"),
        bigquery.SchemaField("top_lower_text", "STRING"),
        bigquery.SchemaField("center_text", "STRING"),
        bigquery.SchemaField("bottom_upper_text", "STRING"),
        bigquery.SchemaField("bottom_lower_text", "STRING"),
        bigquery.SchemaField("raw_json", "STRING"),
        bigquery.SchemaField("notes", "STRING"),
        bigquery.SchemaField("error", "STRING"),
        bigquery.SchemaField("analyzed_at", "STRING"),
    ]
    client.load_table_from_json(rows, tmp, job_config=bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_TRUNCATE")).result()
    client.query(
        f"""
        MERGE `{PROJECT_ID}.{DATASET}.{TABLE}` T
        USING `{tmp}` S
        ON T.video_id = S.video_id
        WHEN MATCHED THEN UPDATE SET
          combined_text = S.combined_text,
          emphasis_text = S.emphasis_text,
          narration_text = S.narration_text,
          dialogue_text = S.dialogue_text,
          top_upper_text = S.top_upper_text,
          top_lower_text = S.top_lower_text,
          center_text = S.center_text,
          bottom_upper_text = S.bottom_upper_text,
          bottom_lower_text = S.bottom_lower_text,
          raw_json = S.raw_json,
          notes = S.notes,
          error = S.error,
          analyzed_at = S.analyzed_at
        WHEN NOT MATCHED THEN INSERT (
          video_id, combined_text, emphasis_text, narration_text, dialogue_text,
          top_upper_text, top_lower_text, center_text, bottom_upper_text, bottom_lower_text,
          raw_json, notes, error, analyzed_at
        ) VALUES (
          S.video_id, S.combined_text, S.emphasis_text, S.narration_text, S.dialogue_text,
          S.top_upper_text, S.top_lower_text, S.center_text, S.bottom_upper_text, S.bottom_lower_text,
          S.raw_json, S.notes, S.error, S.analyzed_at
        )
        """
    ).result()


def clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\r", "\n").split())


def report_row(video: dict[str, object], text: str, error: str) -> dict[str, object]:
    return {
        "video_id": video.get("video_id", ""),
        "channel": video.get("channel", ""),
        "title": video.get("title", ""),
        "view_count": video.get("view_count", 0),
        "thumbnail_text": text,
        "error": error,
    }


def write_report(rows: list[dict[str, object]]) -> None:
    with REPORT_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["video_id", "channel", "title", "view_count", "thumbnail_text", "error"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
