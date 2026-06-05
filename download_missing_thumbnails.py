# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "gcs_upload_staging" / "naresome_thumbnails"
REPORT_PATH = HERE / "reports" / "downloaded_missing_thumbnails.csv"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0 means all.")
    ap.add_argument("--sleep", type=float, default=0.05)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    videos = load_videos()
    targets = [v for v in videos if not v.get("thumbnail_gcs_uri")]
    targets.sort(key=lambda v: int(v.get("view_count") or 0), reverse=True)
    if args.limit:
        targets = targets[: args.limit]

    existing = read_existing_report()
    rows = []
    ok = fail = skipped = 0
    for video in targets:
        video_id = video["video_id"]
        out = OUT_DIR / f"{video_id}.jpg"
        if out.exists() and not args.overwrite:
            rows.append(row(video, "existing", str(out), out.stat().st_size, ""))
            skipped += 1
            continue
        result = download_best(video_id, out)
        rows.append(row(video, result["quality"], str(out) if out.exists() else "", result["bytes"], result["error"]))
        if out.exists():
            ok += 1
        else:
            fail += 1
        time.sleep(args.sleep)

    write_report(merge_rows(existing, rows))
    print(json.dumps({"targets": len(targets), "ok": ok, "fail": fail, "skipped_existing": skipped, "report": str(REPORT_PATH)}, ensure_ascii=False))
    return 0


def load_videos() -> list[dict]:
    text = (HERE / "data" / "videos.js").read_text(encoding="utf-8")
    return json.loads(text.removeprefix("window.VIDEO_DATA = ").strip().rstrip(";"))


def download_best(video_id: str, out: Path) -> dict[str, object]:
    candidates = [
        ("maxresdefault", f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"),
        ("sddefault", f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg"),
        ("hqdefault", f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"),
    ]
    last_error = ""
    for quality, url in candidates:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
            if len(data) < 2048:
                last_error = f"{quality}: too small"
                continue
            out.write_bytes(data)
            return {"quality": quality, "bytes": len(data), "error": ""}
        except (urllib.error.URLError, TimeoutError) as e:
            last_error = f"{quality}: {type(e).__name__}"
    return {"quality": "", "bytes": 0, "error": last_error}


def row(video: dict, quality: str, local_path: str, bytes_size: int, error: str) -> dict[str, object]:
    return {
        "video_id": video.get("video_id", ""),
        "channel": video.get("channel", ""),
        "title": video.get("title", ""),
        "view_count": video.get("view_count", 0),
        "quality": quality,
        "local_path": local_path,
        "bytes": bytes_size,
        "error": error,
    }


def read_existing_report() -> dict[str, dict]:
    if not REPORT_PATH.exists():
        return {}
    with REPORT_PATH.open("r", newline="", encoding="utf-8-sig") as f:
        return {r["video_id"]: r for r in csv.DictReader(f) if r.get("video_id")}


def merge_rows(existing: dict[str, dict], rows: list[dict]) -> list[dict]:
    merged = dict(existing)
    for item in rows:
        if item.get("video_id"):
            merged[item["video_id"]] = item
    return list(merged.values())


def write_report(rows: list[dict]) -> None:
    REPORT_PATH.parent.mkdir(exist_ok=True)
    fields = ["video_id", "channel", "title", "view_count", "quality", "local_path", "bytes", "error"]
    with REPORT_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
