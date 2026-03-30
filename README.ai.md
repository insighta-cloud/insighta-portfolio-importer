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

> **予算の目安**: `output/order.csv` の全注文コストを合算して算出してください。
> ポートフォリオ通貨が JPY の場合、USD 建て注文は `price × quantity × rate` で円換算し、
> JPY 建て注文と合計した金額を予算に設定します。rate が空の注文は直近の rate.csv の値で概算してください。

| `--target-return` | float | 0.1 | 目標リターン (%) |
| `--start-date` | str | today | 開始日 (YYYY-MM-DD) |
| `--target-date` | str | today + 5y | 目標日 (YYYY-MM-DD) |
| `--credentials` | str | "credentials.yaml" | API キーファイルパス |
| `--output-json` | flag | false | 結果を JSON で stdout 出力 |

## Memo File

`upload --memo-file` でグループ別メモを一括適用できます。AI エージェントが `output/order.csv` を確認してメモを生成するワークフローを想定しています。

### memo.csv format

```csv
order_group,memo
1,新NISA枠でインデックスコア構築
2,配当利回り4%超で定期積立ルール発動
5,公益→金融へセクターローテーション 利上げ局面で金融セクター有利と判断
```

ファイルは `output/memo.csv` に保存してください。

### Writing Good Memos

メモは「何を買った/売った」ではなく、**その時点での運用判断の根拠** を記載してください。
マークダウンが使えます。

| ❌ Bad | ✅ Good |
|--------|--------|
| `QQQ 18株購入` | `新NISA枠でインデックスコア構築` |
| `SPYD追加購入` | `配当利回り4%超で定期積立ルール発動` |
| `AES売却+JPM購入` | `公益→金融へセクターローテーション 利上げ局面で金融セクター有利と判断` |

同様に、`--name` と `--description` も運用方針を反映してください。

| Field | ❌ Bad | ✅ Good |
|-------|--------|--------|
| `--name` | `SBI US Stocks 2026` | `米国株 長期成長+高配当` |
| `--description` | `SBI証券からインポート` | 運用仕様をマークダウンで記載（下記例参照） |

`--description` の例:

```markdown
## 運用方針
- **コア**: S&P500 (SPY) + NASDAQ (QQQ)
- **配当**: SPYD で高配当利回り確保
- **サテライト**: 個別株 (JPM, MAR, RACE)

## 目標
- 年率 10% リターン
- 配当利回り 3% 以上
```

### Usage

```bash
# 1. prepare で order.csv 生成 (グループ番号確定)
insighta prepare -ni --name "My Portfolio" --currency JPY --budget 100000

# 2. order.csv を確認して memo.csv を作成

# 3. upload 時に memo.csv を適用
insighta upload --credentials credentials.yaml --config upload.yaml --memo-file output/memo.csv -y
```

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
  --name "米国株 長期成長+高配当" \
  --description "## 運用方針\n- コア: SPY+QQQ\n- 配当: SPYD\n- 目標: 年率10%" \
  --currency JPY \
  --budget 500000 \
  --credentials credentials.yaml \
  --output-json

# 5. Generate memo.csv from order.csv (AI analyzes trade intent)
# memo.csv:
# order_group,memo
# 1,新NISA枠でインデックスコア構築
# 2,配当利回り4%超で定期積立ルール発動

# 6. Upload with memos
insighta upload \
  --credentials credentials.yaml \
  --config upload.yaml \
  --memo-file output/memo.csv \
  -y --output-json

# 7. Parse JSON result from stdout
# {"status": "success", "portfolio_id": "...", "url": "...", ...}
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `No history HTML found` | `input/history/` が空 | HTML ファイルを配置 |
| `注文データが見つかりません` | `output/order.csv` が空 | parse → prepare を再実行 |
| `401 Unauthorized` | API キーが無効 | `credentials.yaml` を確認 |
| verify で差分あり | 履歴期間不足 or seed 不足 | HTML 追加 or `input/seed/` に CSV 追加 |
