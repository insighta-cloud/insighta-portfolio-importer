# AI Agent Guide — insighta Portfolio Importer

このドキュメントは AI エージェント（Amazon Q, GitHub Copilot, Cursor 等）がこのツールを操作するためのリファレンスです。
人間向けの説明は [README.md](README.md) を参照してください。

## Overview

証券会社の取引履歴 HTML → CSV パース → Insighta API アップロードを行う CLI ツール。
`--non-interactive` (`-ni`) フラグで全プロンプトをスキップし、オプションのみで実行できます。

## Project Structure

```
insighta-portfolio-importer/
├── sbi/
│   ├── cli.py          # CLI エントリポイント (click)
│   ├── parser.py       # HTML → CSV パーサー
│   ├── analyzer.py     # 損益・ROI 計算
│   ├── api.py          # Insighta OpenAPI クライアント
│   └── i18n.py         # 多言語メッセージ (ja/ko)
├── input/
│   ├── history/        # 取引履歴 HTML (必須)
│   ├── summary/        # 保有銘柄 HTML (検証用・任意)
│   ├── seed/           # ツール導入前の保有 CSV (任意)
│   ├── deposit/        # 入金・配当 CSV (任意)
│   └── rate.csv        # 期間別為替レート (任意)
├── output/
│   ├── history.csv     # parse 結果
│   ├── order.csv       # prepare 結果 (API送信用)
│   └── cash_deposits.csv
├── templates/          # CSV/YAML テンプレート
├── credentials.yaml    # API キー (gitignore済み)
├── upload.yaml         # prepare 結果 (ポートフォリオ設定)
└── main.py             # python main.py で実行可能
```

## Pipeline

```
Step 1: HTML配置 (input/history/, input/summary/)
    ↓
Step 2: parse (HTML → output/history.csv) + verify (任意)
    ↓
Step 3: prepare (output/history.csv → upload.yaml + output/order.csv)
    ↓
Step 4: upload (upload.yaml → Insighta API)
```

## Non-Interactive Mode

### Full pipeline (wizard)

```bash
insighta wizard --non-interactive \
  --name "My Portfolio" \
  --description "Imported from SBI" \
  --currency JPY \
  --budget 100000 \
  --target-return 0.1 \
  --start-date 2025-01-01 \
  --target-date 2030-01-01 \
  --credentials credentials.yaml \
  --output-json
```

### Individual commands

```bash
# Step 2: parse
insighta parse --rate 155
insighta parse --rate-file input/rate.csv

# Step 2: verify
insighta verify

# Step 3: prepare (non-interactive)
insighta prepare \
  --non-interactive \
  --history-file output/history.csv \
  --seed-file input/seed/seed.csv \
  --rate-file input/rate.csv \
  --name "My Portfolio" \
  --currency JPY \
  --budget 100000

# Step 4: upload
insighta upload \
  --credentials credentials.yaml \
  --config upload.yaml \
  --yes \
  --output-json
```

## Wizard Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--non-interactive` / `-ni` | flag | false | 全プロンプトをスキップ |
| `--name` | str | "My Portfolio" | ポートフォリオ名 |
| `--description` | str | "Imported from brokerage trade history." | 説明 |
| `--currency` | str | "JPY" (ja) / "KRW" (ko) | 通貨 (USD/JPY/KRW) |
| `--budget` | float | 10000.0 | 初期予算 |
| `--target-return` | float | 0.1 | 目標リターン (%) |
| `--start-date` | str | today | 開始日 (YYYY-MM-DD) |
| `--target-date` | str | today + 5y | 目標日 (YYYY-MM-DD) |
| `--credentials` | str | "credentials.yaml" | API キーファイルパス |
| `--output-json` | flag | false | 結果を JSON で stdout 出力 |

## JSON Output

`--output-json` を指定すると、最終行に JSON が出力されます。

成功時:
```json
{"status": "success", "portfolio_id": "abc123", "url": "https://insighta.cloud/ja/portfolio/abc123", "success": 15, "failed": 0}
```

失敗時:
```json
{"status": "error", "portfolio_id": "abc123", "url": "https://insighta.cloud/ja/portfolio/abc123", "success": 10, "failed": 5}
```

## Resume Behavior

前回の実行結果が残っている場合、自動的にスキップします。

| File | Effect |
|------|--------|
| `output/history.csv` exists | Step 1-2 (parse) をスキップ |
| `upload.yaml` + `output/order.csv` exist | Step 1-3 (parse + prepare) をスキップ |

`--non-interactive` モードでは既存ファイルがあれば自動的に再利用します。
最初からやり直したい場合は、該当ファイルを削除してください:

```bash
rm output/history.csv output/order.csv output/cash_deposits.csv upload.yaml
```

## Prerequisites

- Python >= 3.10
- `input/history/` に最低1つの取引履歴 HTML
- アップロードする場合: `credentials.yaml` に有効な API キー

### Install

```bash
pip install git+https://github.com/insighta-cloud/insighta-portfolio-importer.git
```

### credentials.yaml format

```yaml
api_key: "your-api-key-here"
endpoint: "https://openapi.insighta.cloud"
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | 成功 |
| 1 | 失敗 (HTML未検出、API エラー等) |

## Example: Agent Workflow

```bash
# 1. Install
pip install git+https://github.com/insighta-cloud/insighta-portfolio-importer.git

# 2. Setup credentials
cp templates/credentials.yaml credentials.yaml
# Edit credentials.yaml with valid API key

# 3. Ensure input files exist
ls input/history/*.html

# 4. Run full pipeline
insighta wizard -ni \
  --name "US Stocks 2025" \
  --currency JPY \
  --budget 500000 \
  --credentials credentials.yaml \
  --output-json

# 5. Parse JSON result from stdout
# {"status": "success", "portfolio_id": "...", "url": "...", ...}
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `No history HTML found` | `input/history/` が空 | HTML ファイルを配置 |
| `注文データが見つかりません` | `output/order.csv` が空 | parse → prepare を再実行 |
| `401 Unauthorized` | API キーが無効 | `credentials.yaml` を確認 |
| verify で差分あり | 履歴期間不足 or seed 不足 | HTML 追加 or `input/seed/` に CSV 追加 |
