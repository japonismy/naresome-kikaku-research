# GitHub Actions Secret 設定手順

馴れ初め企画リサーチページの定期更新は、GitHub ActionsがBigQueryを読み取って `data/` と `reports/` を更新します。

対象:

- GitHub repo: `japonismy/naresome-kikaku-research`
- Workflow: `.github/workflows/update-data.yml`
- Secret名: `GCP_SA_KEY`
- 更新時刻: 毎日 03:50 JST

## 必要なGCP権限

GitHub Actions用のサービスアカウントには以下が必要です。

- BigQuery Job User
- BigQuery Data Viewer

既存の `naresome-batch@rugged-destiny-408613.iam.gserviceaccount.com` を使う場合も、上記権限があれば足ります。

## Secret設定

権限のあるGCPアカウントで、サービスアカウントJSONキーを作成します。

```powershell
gcloud iam service-accounts keys create .\naresome-github-actions-key.json `
  --iam-account naresome-batch@rugged-destiny-408613.iam.gserviceaccount.com `
  --project rugged-destiny-408613
```

GitHub Secretに登録します。

```powershell
gh secret set GCP_SA_KEY `
  --repo japonismy/naresome-kikaku-research `
  --body (Get-Content .\naresome-github-actions-key.json -Raw)
```

登録後、ローカルのJSONキーは削除します。

```powershell
Remove-Item .\naresome-github-actions-key.json -Force
```

## 初回確認

```powershell
gh workflow run update-data.yml --repo japonismy/naresome-kikaku-research
gh run list --repo japonismy/naresome-kikaku-research --workflow "Update Data" --limit 3
```

成功すれば、以後は毎日 03:50 JST にページ用データが自動更新されます。
