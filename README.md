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

## 画面の使い方

- 初期表示は「競合のみ・公開日が新しい順」
- キーワードと各条件は入力・変更時に自動反映
- 「直近30日」「急上昇」「高再生」「資料完備」をワンタップで適用
- 詳細条件から、競合区分、動画区分、チャンネル状態、視聴回数範囲、公開日範囲、OCR、公開状態、資料状態、データ種別を指定
- 一覧は初回100件を表示し、「さらに100件表示」で追加
- カードと詳細画面の再生数・高評価・コメントは、現行値と保全値のうち採用された観測値へ統一
- 詳細画面の「企画情報をコピー」で、タイトル、サムネ文字、冒頭ダイジェスト、YouTube URLをまとめてコピー

「急上昇」は公開後1日あたりの再生数、「チャンネル内突出」は各チャンネルの動画再生中央値に対する倍率で並び替えます。

## データ更新

BigQueryからページ用データを生成します。

```powershell
uv run --python 3.12 --with openpyxl python build_observed_archive_supplement.py
python refresh_baseline_channel_status.py
python refresh_youtube_current_stats.py
uv run --python 3.12 --with google-cloud-bigquery python generate_portal_data_bq.py
```

`refresh_baseline_channel_status.py` は公開対象32チャンネルの公開可否、公開動画数、最新投稿日を確認し、「更新あり」「更新停止」「現在公開なし」を判定する入力を作ります。`refresh_youtube_current_stats.py` は、同じ32チャンネルに属する過去競合動画について現在のYouTube統計を取得します。ローカルでは `YOUTUBE_API_KEY`、GitHub ActionsではGCP Secret Managerの `naresome-youtube-api-key` を使用します。取得不能な削除・非公開動画は、最後に取得できた値または過去の調査値を表示します。

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

元のユーザー指定33チャンネルは `data_sources/baseline_competitor_channels.csv` に記録し、そのうち「俺たちの馴れ初め」は `exclude_adult` として公開・検索対象から外します。公開ページの対象は残る32チャンネルだけです。台帳外にある成人向けチャンネル、漫画・ボイコミ参考チャンネル、その他の旧競合も、BigQueryや旧調査CSVにデータが残っていても公開ページへ出力しません。

公開対象32チャンネルは、固定したcanonical channel IDを優先してBigQueryの `channels` と突合し、次のデータを統合します。

- 現行動画: `videos`
- 停止・削除前の保全動画: `videos_archive_20260527`
- 過去調査の保存行: `observed_archive_supplement.csv`（公開対象32チャンネルに一致する行だけ）
- 現在の再生数等: `youtube_current_stats.csv`
- サムネ保全先: `thumbnail_assets`
- 台本資産: `script_assets`

チャンネル一覧では、現行・停止済み・データなしを削除せずに区別します。BigQueryの動画行がある場合は「DBデータあり」、旧調査の保存行だけがある場合は「保存データあり」、どちらもない場合は「データなし」です。

更新判定はYouTubeチャンネル現況を優先し、公開動画があり最終公開から45日以内なら「更新あり」、45日を超えた場合は「更新停止」、公開動画数が0なら「現在公開なし」とします。YouTube APIが一時的に失敗した場合は前回の現況CSVを保持し、最新日の欠損時だけBigQueryの最終公開日へフォールバックします。

生成前の `data/videos.js` も公開対象32チャンネルに一致する行だけ読み込み、現行DB・履歴DB・過去調査保存行から消えた動画を `portal_snapshot_archive` として残します。これにより、更新中チャンネルの動画が削除・非公開になった場合も、前回公開スナップショットからサイト上の履歴を復元できます。日次ワークフローで生成データをGitへコミットするため、前回値が差分保全の入力になります。

資産は動画IDで結合します。サムネは `thumbnail_assets.gcs_uri` を最優先にし、未保全時はYouTubeの `maxresdefault` / `sddefault` / `hqdefault` へ順次フォールバックします。台本は `script_assets.gcs_csv_uri` を公開URLへ変換し、詳細画面のCSVボタンから取得できるようにします。

生成物:

- `data/channels.js`: 公開対象32チャンネルの突合・更新・保全・資産件数
- `reports/competitor_registry_match.csv`: 突合監査用CSV
- `reports/final_scope_asset_audit.json`: 対象外混入、重複、資産ID結合の自動ゲート結果
- `reports/channel_scope.csv`: BigQuery監視台帳全体の参考レポート（公開スコープの決定には使わない）
- `reports/content_scope.csv`: 公開対象32チャンネル内動画の集計

`data_sources/former_competitor_channels.csv` と `data_sources/channel_display_rules.csv` は旧調査の記録として残しますが、公開対象の選択には使いません。

生成後のスコープ・資産ゲート:

```powershell
python validate_generated_scope.py
```

GCS実体があるのにBigQuery未登録だったサムネは `data_sources/thumbnail_asset_overrides.csv` で明示し、生成時と `sync_gcs_assets_to_bq.py` の両方から動画IDで再結合します。

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

再生成後、最新の未保全サムネを最大150件GCSへ保存してBigQueryへ反映します。これにより、初期表示が `i.ytimg.com` のみに依存する状態を防ぎます。手動実行する場合:

```powershell
uv run --with google-cloud-bigquery --with google-cloud-storage python archive_recent_thumbnails.py --limit 150
uv run --with google-cloud-bigquery python generate_portal_data_bq.py
```

前提:

- BQ側の日次更新ジョブ `naresome-daily-metadata` が 03:20 JST に完了していること
- GitHub repo secret `GCP_SA_KEY` にBigQuery読み取り用サービスアカウントJSONを設定していること

現在のGCPログインアカウントではサービスアカウント鍵の発行権限がないため、Secret設定は権限のあるアカウントで行う必要があります。
