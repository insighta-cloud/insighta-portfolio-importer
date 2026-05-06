# AI Agent Guide — insighta CLI

このドキュメントは AI エージェント（Amazon Q, GitHub Copilot, Cursor 等）がこのツールを操作するためのリファレンスです。
人間向けの説明は [README.md](README.md) を参照してください。

## Overview

証券会社の取引データ → 自動分類・パース → CSV → Insighta API アップロードを行う CLI ツール。
`--non-interactive` (`-ni`) フラグで全プロンプトをスキップし、オプションのみで実行できます。

## Project Structure

```
insighta-cli/
├── sbi/
│   ├── cli.py          # CLI エントリポイント (rich-click)
│   ├── parser.py       # レガシーパーサー + ユーティリティ (Dirs, Trade, Holding, Deposit)
│   ├── parser_v2.py    # input/sbi/ 自動認識パーサー (メイン)
│   ├── analyzer.py     # 損益・ROI 計算
│   ├── api.py          # Insighta OpenAPI クライアント
│   └── i18n.py         # 多言語メッセージ (ja/ko)
├── workspaces/
│   └── <name>/             # --work で指定する作業ディレクトリ
│       ├── input/
│       │   ├── sbi/               # 全ファイルをここに配置 (自動分類)
│       │   ├── manual/            # 手動入力 (seed.csv 等)
│       │   ├── rate.csv           # 期間別為替レート (任意)
│       │   └── ratio.csv          # 銘柄別ポートフォリオ比率 (任意)
│       ├── output/
│       │   ├── history.csv        # parse 結果
│       │   ├── order.csv          # prepare 結果 (注文グループ、キー: group_dt)
│       │   ├── cash_deposits.csv  # prepare 結果 (入金・配当、キー: group_dt)
│       │   ├── upload.yaml        # prepare 結果 (ポートフォリオ設定)
│       │   └── memo.csv           # グループ別メモ (prepare 対話入力 or AI 生成)
│       └── .cache/                # パース済みキャッシュ (UTF-8)
├── templates/          # CSV/YAML テンプレート
├── credentials.yaml    # API キー (gitignore済み)
└── main.py             # python main.py で実行可能
```

## Pipeline

```
Step 1: input/sbi/ にファイル配置 (CSV/HTML を自動分類)
    ↓
Step 2: parse (自動分類 → output/history.csv) + verify (任意)
    ↓
Step 3: prepare (output/history.csv → output/upload.yaml + output/order.csv + output/cash_deposits.csv + output/memo.csv)
    ↓
Step 4: upload (upload.yaml → Insighta API)
```

## Auto-Classification (parser_v2)

`input/sbi/` に配置されたファイルは以下のルールで自動分類されます:

| Type | Extension | Detection |
|------|-----------|-----------|
| `history_csv` | .csv | ヘッダーに「国内約定日」+「約定数量」 |
| `summary` | .html | `stock-holding-table` or `css-djjzqp` |
| `history_html` | .html | `table-row` + `sticker` |
| `domestic_fund` | .csv | ヘッダーに「約定履歴照会」 |
| `currency_exchange` | .csv | ヘッダーに「為替取引注文履歴」 |
| `deposit_gaika` | .csv | ヘッダーに「外貨入出金明細」 |
| `deposit_transfer` | .csv | ヘッダーに「入出金振替操作履歴」 |
| `deposit_dividend` | .csv | ヘッダーに「検索件数」+「受渡日」 |

## Non-Interactive Mode

### Full pipeline (wizard)

```bash
insighta --work sbi-us-stocks wizard --non-interactive \
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
insighta --work sbi-us-stocks parse --rate 155
insighta --work sbi-us-stocks parse --rate-file input/rate.csv

# Step 2: verify
insighta --work sbi-us-stocks verify

# Step 3: prepare (non-interactive)
insighta --work sbi-us-stocks prepare \
  --non-interactive \
  --name "My Portfolio" \
  --currency JPY \
  --budget 100000

# Step 4: upload
insighta --work sbi-us-stocks upload \
  --config workspaces/sbi-us-stocks/output/upload.yaml \
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
| `--start-date` | str | 最初の注文/配当日 | 開始日 (YYYY-MM-DD) |
| `--target-date` | str | start-date + 10y | 目標日 (YYYY-MM-DD) |
| `--credentials` | str | 保存済みパス or "credentials.yaml" | API キーファイルパス |
| `--output-json` | flag | false | 結果を JSON で stdout 出力 |

> **予算の目安**: `workspaces/<name>/output/order.csv` の全注文コストを合算して算出してください。
> ポートフォリオ通貨が JPY の場合、USD 建て注文は `price × quantity × rate` で円換算し、
> JPY 建て注文と合計した金額を予算に設定します。rate が空の注文は直近の rate.csv の値で概算してください。

## Credentials

`--credentials` を省略した場合、以下の順で自動解決されます:

1. `insighta config --credentials <path>` で保存済みのパス
2. 見つからない場合はエラー

```bash
# 一度保存すれば以降は --credentials 不要
insighta config --credentials credentials.yaml
```

### credentials.yaml format

```yaml
api_key: "your-api-key-here"
endpoint: "https://openapi.insighta.cloud"
```

## API Management Commands

| Command | Description |
|---------|-------------|
| `insighta config --credentials <path>` | credentials パスを保存 |
| `insighta list-portfolios` | 自分のポートフォリオ一覧を取得 |
| `insighta search-portfolios --search <keyword>` | 公開ポートフォリオを検索 |
| `insighta delete-portfolio <id> -y` | ポートフォリオを削除 |
| `insighta nav-history <id>` | NAV履歴を取得 |
| `insighta metrics-history <id> --metrics twr` | メトリクス履歴を取得 |

すべて `--output-json` フラグで JSON 出力に対応。`--credentials` は config 保存済みなら省略可。

```bash
# 例
insighta list-portfolios --output-json
insighta search-portfolios --search "米国株" --output-json
insighta delete-portfolio abc123 -y
insighta nav-history abc123 --output-json
insighta metrics-history abc123 --metrics twr --output-json
```

## Memo File

`prepare` 実行時のグループプレビューで入力したメモ、または AI が生成したメモは `workspaces/<name>/output/memo.csv` に保存されます。
`upload` 時に自動で読み込まれ、各グループに適用されます。
`--memo-file` オプションで別ファイルを指定することもできます（override）。

### memo.csv format

`prepare` のプレビュー順番（1, 2, 3...）がキーです。主文・配当・入出金すべてが時系列にマージされた状態の順番です。

```csv
order_group,memo
1,米国株投資開始 AAPL打診買い
2,DIA打診買い ダウ高配当ETFで分散
3,
4,配当利回り4%超で定期積立ルール発動
```

メモが不要なグループは行ごと省略できます（連続した行番号でなくても可）。

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

### AI ワークフロー

```bash
# 1. prepare で order.csv + cash_deposits.csv 生成
insighta --work sbi-us-stocks prepare -ni --name "My Portfolio" --currency JPY --budget 100000

# 2. workspaces/sbi-us-stocks/output/order.csv + cash_deposits.csv を見て memo.csv を作成

# 3. upload (workspaces/sbi-us-stocks/output/memo.csv を自動読み込み)
insighta --work sbi-us-stocks upload --config workspaces/sbi-us-stocks/output/upload.yaml -y

# または別ファイルを指定
insighta --work sbi-us-stocks upload --config workspaces/sbi-us-stocks/output/upload.yaml --memo-file workspaces/sbi-us-stocks/output/memo.csv -y
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
| `workspaces/<name>/output/history.csv` exists | Step 1-2 (parse) をスキップ |
| `workspaces/<name>/output/upload.yaml` + `order.csv` exist | Step 1-3 (parse + prepare) をスキップ |

`--non-interactive` モードでは既存ファイルがあれば自動的に再利用します。
最初からやり直したい場合は、該当ファイルを削除してください:

```bash
rm workspaces/<name>/output/history.csv workspaces/<name>/output/order.csv workspaces/<name>/output/cash_deposits.csv workspaces/<name>/output/upload.yaml workspaces/<name>/output/memo.csv
```

## Prerequisites

- Python >= 3.10
- `workspaces/<name>/input/sbi/` に最低1つの約定履歴CSV or 取引履歴HTML
- アップロードする場合: `credentials.yaml` に有効な API キー

### Install

```bash
pip install git+https://github.com/insighta-cloud/insighta-cli.git
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | 成功 |
| 1 | 失敗 (ファイル未検出、API エラー等) |

## Example: Agent Workflow

```bash
# 1. Install
pip install git+https://github.com/insighta-cloud/insighta-cli.git

# 2. Setup credentials
cp templates/credentials.yaml credentials.yaml
# Edit credentials.yaml with valid API key
insighta config --credentials credentials.yaml

# 3. Ensure input files exist
ls workspaces/sbi-us-stocks/input/sbi/

# 4. Run full pipeline
insighta --work sbi-us-stocks wizard -ni \
  --name "米国株 長期成長+高配当" \
  --description "## 運用方針\n- コア: SPY+QQQ\n- 配当: SPYD\n- 目標: 年率10%" \
  --currency JPY \
  --budget 500000 \
  --output-json

# 5. workspaces/sbi-us-stocks/output/order.csv + cash_deposits.csv を見て memo.csv を作成

# 6. upload (workspaces/sbi-us-stocks/output/memo.csv を自動読み込み)
insighta --work sbi-us-stocks upload \
  --config workspaces/sbi-us-stocks/output/upload.yaml \
  -y --output-json

# 7. Parse JSON result from stdout
# {"status": "success", "portfolio_id": "...", "url": "...", ...}
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `No files found in input/sbi/` | `input/sbi/` が空 | ファイルを配置 |
| `分類不能: xxx` | 未対応ファイル形式 | ファイル内容を確認、対応形式か確認 |
| `注文データが見つかりません` | `output/order.csv` が空 | parse → prepare を再実行 |
| `401 Unauthorized` | API キーが無効 | `credentials.yaml` を確認 |
| `credentials が未指定です` | config 未保存 & --credentials 未指定 | `insighta config --credentials <path>` で保存 |
| verify で差分あり | 履歴期間不足 or seed 不足 | CSV 追加 or `input/manual/seed.csv` に追加 |
| 残高不足区間が表示される | 為替入金データ不足 | 為替取引CSVを `input/sbi/` に追加 |
| USD 残高が合わない | 配当金が JPY で計上されている | 外貨入出金明細CSVを `input/sbi/` に追加 |
