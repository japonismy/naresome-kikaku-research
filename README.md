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
uv run --python 3.12 --with openpyxl python build_observed_archive_supplement.py
python refresh_youtube_current_stats.py
uv run --python 3.12 --with google-cloud-bigquery python generate_portal_data_bq.py
```

`refresh_youtube_current_stats.py` は、BigQueryにない過去競合動画についても現在のYouTube統計を取得します。ローカルでは `YOUTUBE_API_KEY`、GitHub ActionsではGCP Secret Managerの `naresome-youtube-api-key` を使用します。取得不能な削除・非公開動画は、最後に取得できた値または過去の調査値を表示します。

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

デフォルトの検索対象は、監視台帳上の現行チャンネル、停止済みチャンネルの保全動画、過去の競合調査シートに記録された旧競合チャンネルです。チャンネル名や動画タイトルに `馴れ初め` を含むかどうかだけでは判定しません。

- `owned_current`
- `competitor`（現行・停止済みの保全動画を含む）
- `migration_or_related_competitor`

対象外:

- `inactive_or_no_public_videos`
- `exclude_from_naresome_competitor_analysis`
- `adjacent_out_of_scope`
- `owned_legacy`

公開ページには、BigQueryの監視台帳で `competitor` または `migration_or_related_competitor` になっているチャンネルと、`data_sources/former_competitor_channels.csv` で確認済みの過去競合チャンネルだけを出力します。自社チャンネル、成人向け、漫画・元ネタ、その他参考元は公開データに含めません。

現在のBQ対象・対象外一覧は `reports/channel_scope.csv`、ページ上のチャンネル／フラグ別件数は `reports/content_scope.csv` に出力します。

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

GCS未登録サムネをYouTubeから再取得:

```powershell
python download_missing_thumbnails.py --mode all
python prepare_gcs_assets.py
python run_asset_maintenance.py
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

## サムネ画像の保全方針

YouTubeのサムネURLは、動画削除・非公開・差し替えで404になるため、分析対象に入れた動画のサムネは原則として実画像を保存します。

保存先:

```text
gcs_upload_staging/naresome_thumbnails/{video_id}.jpg
gs://senior-share-staging-570862915709/naresome_thumbnails/{video_id}.jpg
```

既存GCS画像をローカルに戻す場合:

```powershell
gcloud storage rsync gs://senior-share-staging-570862915709/naresome_thumbnails gcs_upload_staging/naresome_thumbnails --recursive
```

現行ページ対象のサムネを全件ローカル保存する場合:

```powershell
python download_missing_thumbnails.py --mode all
```

未保存分だけ確認する場合:

```powershell
python download_missing_thumbnails.py --mode missing
```

`sync_gcs_assets_to_bq.py` は既存の `thumbnail_assets` を消さず、マニフェストにある動画IDだけを追加・更新します。

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
