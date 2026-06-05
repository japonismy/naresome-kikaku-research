# 馴れ初め 企画リサーチ

2ch馴れ初め競合DB `analysis/naresome_db.sqlite` から生成する静的検索ページ。

## 検索対象

- サムネ文字
- タイトル
- タグ

概要欄本文は検索対象ではなく、詳細画面の冒頭ダイジェストとCSV DLに使う。

## 生成

```powershell
python generate_portal_data.py
```

生成物:

- `index.html`
- `data/videos.js`
- `data/transcripts_light.js`
- `reports/build_summary.json`
- `reports/thumbnail_text_missing.csv`
