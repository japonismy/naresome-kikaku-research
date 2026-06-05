# 馴れ初め 企画リサーチ

2ch馴れ初め系の企画検索ページです。

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

生成物:

- `data/videos.js`
- `data/transcripts_light.js`
- `reports/build_summary.json`
- `reports/thumbnail_text_missing.csv`

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
