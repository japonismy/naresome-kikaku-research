# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from pathlib import Path


HERE = Path(__file__).resolve().parent
VAULT = HERE.parents[2]
DB_PATH = VAULT / "馴れ初めシネマ" / "analysis" / "naresome_db.sqlite"
PRESERVE_DIR = VAULT / "馴れ初めシネマ" / "保全" / "competitor_backup"
REPORT_DIR = HERE / "reports"
ASSET_DIR = HERE / "script_csv_assets"
VIDEO_ID_RE = re.compile(r"(?P<video_id>[A-Za-z0-9_-]{11})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export-csv-assets", action="store_true", help="Create per-video CSV files locally.")
    ap.add_argument("--limit", type=int, default=0, help="Limit CSV asset exports. 0 means all.")
    args = ap.parse_args()

    REPORT_DIR.mkdir(exist_ok=True)
    assets = scan_assets()
    videos = load_target_videos()
    rows = build_rows(videos, assets)
    write_manifest(REPORT_DIR / "script_assets_manifest.csv", rows)

    exported = 0
    if args.export_csv_assets:
        ASSET_DIR.mkdir(exist_ok=True)
        for row in rows:
            if args.limit and exported >= args.limit:
                break
            if not row["best_local_path"]:
                continue
            out = ASSET_DIR / f"{row['video_id']}.csv"
            export_transcript_csv(Path(row["best_local_path"]), out)
            row["local_csv_asset"] = str(out)
            exported += 1
        write_manifest(REPORT_DIR / "script_assets_manifest.csv", rows)

    summary = {
        "target_videos": len(videos),
        "videos_with_script_asset": sum(1 for r in rows if r["best_local_path"]),
        "videos_missing_script_asset": sum(1 for r in rows if not r["best_local_path"]),
        "asset_files_found": sum(len(v) for v in assets.values()),
        "csv_assets_exported": exported,
        "manifest": str(REPORT_DIR / "script_assets_manifest.csv"),
    }
    (REPORT_DIR / "script_assets_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def scan_assets() -> dict[str, list[Path]]:
    by_video: dict[str, list[Path]] = {}
    if not PRESERVE_DIR.exists():
        return by_video
    for path in PRESERVE_DIR.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".vtt", ".txt", ".srt"}:
            continue
        match = VIDEO_ID_RE.search(path.name)
        if not match:
            continue
        by_video.setdefault(match.group("video_id"), []).append(path)
    return by_video


def load_target_videos() -> list[dict[str, object]]:
    text = (HERE / "data" / "videos.js").read_text(encoding="utf-8")
    prefix = "window.VIDEO_DATA = "
    if not text.startswith(prefix):
        raise SystemExit("Unexpected data/videos.js format")
    videos = json.loads(text[len(prefix) :].strip().rstrip(";"))

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    try:
        rows = {
            r["video_id"]: dict(r)
            for r in con.execute("SELECT video_id, thumbnail_local_path FROM videos")
        }
    finally:
        con.close()
    for video in videos:
        video.update(rows.get(video["video_id"], {}))
    return videos


def build_rows(videos: list[dict[str, object]], assets: dict[str, list[Path]]) -> list[dict[str, object]]:
    rows = []
    for video in videos:
        video_id = str(video["video_id"])
        candidates = sorted(assets.get(video_id, []), key=asset_rank)
        best = candidates[0] if candidates else None
        rows.append(
            {
                "video_id": video_id,
                "channel": video.get("channel", ""),
                "title": video.get("title", ""),
                "view_count": video.get("view_count", 0),
                "published_at": video.get("published_at", ""),
                "asset_count": len(candidates),
                "best_type": best.suffix.lower().lstrip(".") if best else "",
                "best_local_path": str(best) if best else "",
                "best_bytes": best.stat().st_size if best else 0,
                "local_csv_asset": "",
            }
        )
    return rows


def asset_rank(path: Path) -> tuple[int, int, str]:
    name = path.name.lower()
    if ".ja-orig" in name:
        priority = 0
    elif ".ja." in name:
        priority = 1
    elif path.suffix.lower() == ".txt":
        priority = 2
    else:
        priority = 3
    return (priority, path.stat().st_size, name)


def export_transcript_csv(src: Path, out: Path) -> None:
    text = src.read_text(encoding="utf-8", errors="replace")
    lines = parse_vtt(text) if src.suffix.lower() == ".vtt" else parse_plain(text)
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["line_no", "start", "end", "text"])
        writer.writeheader()
        for i, item in enumerate(lines, 1):
            writer.writerow({"line_no": i, **item})


def parse_vtt(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    current_time = ("", "")
    buffer: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line or line == "WEBVTT" or line.isdigit():
            flush_vtt(rows, current_time, buffer)
            buffer = []
            current_time = ("", "")
            continue
        if "-->" in line:
            flush_vtt(rows, current_time, buffer)
            buffer = []
            parts = [x.strip().split(" ")[0] for x in line.split("-->", 1)]
            current_time = (parts[0], parts[1] if len(parts) > 1 else "")
            continue
        if line and not line.startswith(("NOTE", "Kind:", "Language:")):
            buffer.append(clean_caption_text(line))
    flush_vtt(rows, current_time, buffer)
    return dedupe_rows(rows)


def flush_vtt(rows: list[dict[str, str]], current_time: tuple[str, str], buffer: list[str]) -> None:
    text = " ".join(x for x in buffer if x).strip()
    if text:
        rows.append({"start": current_time[0], "end": current_time[1], "text": text})


def parse_plain(text: str) -> list[dict[str, str]]:
    rows = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        cleaned = clean_caption_text(line.strip())
        if cleaned:
            rows.append({"start": "", "end": "", "text": cleaned})
    return dedupe_rows(rows)


def clean_caption_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ")
    return " ".join(text.split())


def dedupe_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped = []
    last = ""
    for row in rows:
        if row["text"] == last:
            continue
        deduped.append(row)
        last = row["text"]
    return deduped


def write_manifest(path: Path, rows: list[dict[str, object]]) -> None:
    fields = [
        "video_id",
        "channel",
        "title",
        "view_count",
        "published_at",
        "asset_count",
        "best_type",
        "best_local_path",
        "best_bytes",
        "local_csv_asset",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
