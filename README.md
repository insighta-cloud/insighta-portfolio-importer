# insighta Portfolio Importer

[Insighta Cloud](https://insighta.cloud) へのポートフォリオ一括登録を支援するCLIツールです。
証券会社の取引履歴から注文データを抽出し、検証・分析したうえで Insighta API へまとめてアップロードできます。

- **パース**: 証券会社のHTMLから注文履歴を抽出 → CSV変換
- **検証**: CSV集計と実際の保有状況の照合
- **分析**: 実現/未実現損益・総合ROI
- **アップロード**: Insighta API へポートフォリオデータを一括送信

> ⚠️ 現在はSBI証券の海外株式口座のみ対応しています。

> 🤖 AI エージェントで操作する場合は [README.ai.md](README.ai.md) を参照してください。`--non-interactive` モードでプロンプトなし実行できます。

## 1. Setup

```bash
pip install git+https://github.com/insighta-cloud/insighta-portfolio-importer.git
```

または:

```bash
git clone https://github.com/insighta-cloud/insighta-portfolio-importer.git
cd insighta-portfolio-importer
pip install .
```

## 2. API キーの設定

Insighta API へのアップロード機能を使う場合に必要です（ローカル分析のみなら不要）。

```bash
cp templates/credentials.yaml credentials.yaml
```

`credentials.yaml` を開いて API キーを設定します。
API キーは https://insighta.cloud/settings から取得できます。

> ⚠️ `credentials.yaml` には秘密情報が含まれます。`.gitignore` に追加済みですが、公開リポジトリへのコミットにご注意ください。

## 3. Quick Start

引数なしで実行すると、対話式ウィザードが HTML配置 → パース → 検証 → アップロード まで順番に案内します。

```bash
insighta
```

## 4. コマンド一覧

| コマンド | 説明 |
|---------|------|
| `insighta` | 対話式ウィザード（全ステップ一括） |
| `insighta parse` | 取引履歴HTMLをパース → `output/history.csv` |
| `insighta verify` | CSV集計 vs HTML実際保有の照合 |
| `insighta analyze` | 実現/未実現損益 + 総合ROI |
| `insighta prepare` | アップロード用ファイル生成（`upload.yaml` + `output/order.csv`） |
| `insighta upload` | Insighta API へポートフォリオデータを送信 |

```bash
insighta parse --rate 155                    # 固定為替レート指定
insighta parse --rate-file input/rate.csv    # 期間別為替レートCSV
insighta upload --credentials credentials.yaml --config upload.yaml
```

---

## 5. CSV フォーマット詳細

### 5.1 seed CSV

ツール導入前の保有分を手動で登録する場合に使用。`input/seed/` に配置。

```csv
dt,ticker,qty,acct,price,avg,cur,base,rate
2021/10/25 00:00,AAPL,1,TT,149.50,149.50,JPY,USD,113.96
```

### 5.2 deposit CSV

入金履歴・配当金を手動で管理する場合に使用。`input/deposit/` に配置。

```csv
dt,type,amount,cur,ticker,rate
2025/01/15 09:00,budget,100000,JPY,,148.20
2025/06/01 10:30,budget,500,USD,,
2025/03/15 09:00,dividend,12.50,USD,AAPL,
```

| カラム | 説明 |
|--------|------|
| `dt` | 日時（`2025/01/15` または `2025/01/15 09:00`） |
| `type` | `budget`（入金） / `dividend`（配当金） |
| `amount` | 金額（マイナスで出金） |
| `cur` | 通貨（JPY, USD など） |
| `ticker` | 配当金の場合のみ銘柄指定 |
| `rate` | 為替レート（任意。空欄の場合は rate.csv から自動取得） |

### 5.3 rate CSV

通貨ペアごとに期間とレートを定義。`input/rate.csv` に配置。

```csv
from,to,pair,rate
2024/01/01,2024/12/31,USD/JPY,155.50
2025/01/01,2025/12/31,USD/JPY,148.20
2026/02/19 09:00,2026/02/19 15:00,USD/JPY,155.38
```

`from`/`to` は日付のみ (`2024/01/01`) でも、時刻付き (`2024/01/01 09:00`) でも可。
日付のみの場合は `00:00`〜`23:59` として扱います。

## Support

不明な点があれば Discord でお気軽にご連絡ください: `insighta_cloud`

## License

MIT License © 2026 [insighta cloud Inc.](https://insighta.cloud)
