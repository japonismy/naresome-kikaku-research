# Competitor sheet exports

Place exported Google Sheets files here to import every observed video row into
`data_sources/observed_archive_supplement.csv`.

Supported formats:

- `.xlsx`
- `.csv`

The importer scans sheets/tables that contain these headers:

- `動画URL`
- `動画タイトル`
- `チャンネル名`
- `視聴回数`
- `動画公開日`
- `コメント数`
- `高評価数`
- `リサーチ日時`

Run:

```powershell
uv run --with openpyxl python build_observed_archive_supplement.py
uv run --with google-cloud-bigquery python generate_portal_data_bq.py
```

