# 馴れ初め 企画リサーチ

2ch馴れ初め系の企画検索ページです。

## GCP/BQ/GCS 認証

BigQuery、GCS、OAuth/ADC認証は `japonismy@gmail.com` に集約して運用します。

YouTube用アカウントと混同しやすいため、GCP/BQ/GCS作業前は必ず `gcloud auth list` と `gcloud config list` で active account を確認します。

詳細:

`C:\Data\ObsidianVault\02_Channels\馴れ初めシネマ\analysis\BQ_GCP_ACCOUNT_POLICY_20260606.md`

公開URL:

https://japonismy.github.io/naresome-kikaku-research/

## 検索対象

- サムネ文字
- タイトル
- タグ

概要欄本文は検索対象にせず、詳細画面の冒頭ダイジェストとCSVダウンロード用に使います。

## データ更新

BigQueryからページ用データを生成します。

```powershell
uv run --with google-cloud-bigquery python generate_portal_data_bq.py
```

## サムネOCR

シニア朗読と同じく `gemini-2.5-flash-lite` を使います。

```powershell
uv run --with google-genai --with google-cloud-bigquery python ocr_missing_thumbnails_gemini.py
```

まず件数や対象だけ確認する場合:

```powershell
uv run --with google-genai --with google-cloud-bigquery python ocr_missing_thumbnails_gemini.py --dry-run --limit 20
```

生成物:

- `data/videos.js`
- `data/transcripts_light.js`
- `reports/build_summary.json`
- `reports/thumbnail_text_missing.csv`
- `reports/channel_scope.csv`

## 対象チャンネル

デフォルトの検索対象は、チャンネル条件と動画タイトル条件の両方を満たす動画です。

動画タイトル条件:

- タイトルに `馴れ初め`、`馴初め`、`なれそめ` のいずれかを含む

- `owned_current`
- `competitor` かつ公開動画あり
- `migration_or_related_competitor`

対象外:

- `inactive_or_no_public_videos`
- `exclude_from_naresome_competitor_analysis`
- `adjacent_out_of_scope`
- `owned_legacy`

現在の対象・対象外一覧は `reports/channel_scope.csv` に出力します。

## 台本/字幕CSV

保全済み字幕から、動画IDごとのCSV資産を作る準備があります。

台帳のみ更新:

```powershell
python inventory_script_assets.py
```

ローカルCSV資産も生成:

```powershell
python inventory_script_assets.py --export-csv-assets
```

CSV実体は大きくなるためGitHub Pagesには直接コミットせず、GCSなどの外部ストレージに置きます。ページ側にはダウンロードURLだけを持たせる想定です。

台本資産台帳をBigQueryへ同期:

```powershell
uv run --with google-cloud-bigquery python sync_script_assets_to_bq.py
```

GCS移行用のステージングと台帳作成:

```powershell
python prepare_gcs_assets.py
```

GCS保存先:

```text
gs://senior-share-staging-570862915709/naresome_script_csv/{video_id}.csv
gs://senior-share-staging-570862915709/naresome_thumbnails/{video_id}.jpg
```

BQ反映:

```powershell
uv run --with google-cloud-bigquery python sync_gcs_assets_to_bq.py
uv run --with google-cloud-bigquery python generate_portal_data_bq.py
```

一括メンテナンス:

```powershell
python run_asset_maintenance.py
```

ページ更新まで行う場合:

```powershell
python run_asset_maintenance.py --deploy
```

このバッチは `gcloud` のアカウントを `japonismy@gmail.com`、プロジェクトを `rugged-destiny-408613` に揃えてから実行します。

ローカルから手動で再生成して公開する場合:

```powershell
uv run --with google-cloud-bigquery python deploy_pages.py
```

## 定期更新

GitHub Actions `.github/workflows/update-data.yml` で毎日 03:50 JST にBigQueryから再生成します。

前提:

- BQ側の日次更新ジョブ `naresome-daily-metadata` が 03:20 JST に完了していること
- GitHub repo secret `GCP_SA_KEY` にBigQuery読み取り用サービスアカウントJSONを設定していること

現在のGCPログインアカウントではサービスアカウント鍵の発行権限がないため、Secret設定は権限のあるアカウントで行う必要があります。
