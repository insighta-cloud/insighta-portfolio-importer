# insighta Portfolio Importer

> 🤖 AI エージェントで操作する場合は [README.ai.md](README.ai.md) を参照してください。

[Insighta Cloud](https://insighta.cloud) へのポートフォリオ一括登録を支援するCLIツールです。
証券会社の取引履歴から注文データを抽出し、検証・分析したうえで Insighta API へまとめてアップロードできます。

- **パース**: 証券会社のHTMLから注文履歴を抽出 → CSV変換
- **検証**: CSV集計と実際の保有状況の照合
- **分析**: 実現/未実現損益・総合ROI
- **アップロード**: Insighta API へポートフォリオデータを一括送信

> ⚠️ 現在はSBI証券の海外株式口座のみ対応しています。

## このツールはこんな方向けです

- SBI証券で海外株式を取引している個人投資家
- 取引履歴を [Insighta Cloud](https://insighta.cloud) で一元管理したい方
- 手動でのポートフォリオ登録が面倒な方

## 注意事項

- 取引履歴のHTMLはユーザー自身がブラウザから手動で保存する必要があります
- 現在は海外株式口座のみ対応しています（国内株・投信等は未対応）
- SBI証券のHTML構造が変更された場合、パースが正しく動作しない可能性があります
- アップロード前に必ず `verify` コマンドでデータの正確性を確認してください

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

> **初期予算の目安**: 全注文の購入コスト合計をカバーできる金額を設定してください。
> ポートフォリオ通貨が JPY の場合、USD 建て注文は `価格 × 数量 × 為替レート` で円換算し、JPY 建て注文と合算した金額が目安です。

```bash
insighta parse --rate 155                    # 固定為替レート指定
insighta parse --rate-file input/rate.csv    # 期間別為替レートCSV
insighta upload --credentials credentials.yaml --config upload.yaml
```

---

## 5. ポートフォリオ名・説明・注文メモの書き方

Insighta Cloud のポートフォリオは **運用記録** です。
名前・説明・注文メモには「何を買った/売った」ではなく、**どういう方針で運用しているか** を記載してください。

### ポートフォリオ名

運用方針がひと目でわかる名前を付けます。

| ❌ 悪い例 | ✅ 良い例 |
|-----------|----------|
| `SBI US Stocks 2026` | `米国株 長期成長+高配当` |
| `My Portfolio` | `NISA インデックス積立` |
| `海外株式` | `セクター分散 中長期運用` |

### ポートフォリオ説明（マークダウン対応）

運用の全体像を記載します。構成戦略・目標・リバランス基準などを含めてください。

```markdown
## 運用方針
- **コア**: S&P500 (SPY) + NASDAQ (QQQ) で市場全体をカバー
- **配当**: SPYD で高配当利回りを確保
- **サテライト**: 個別株 (JPM, MAR, RACE) で超過リターンを狙う

## 目標
- 年率 10% リターン
- 配当利回り 3% 以上維持

## リバランス基準
- インデックス比率が 50% を下回ったら買い増し
- 個別株は 1銘柄あたりポートフォリオの 10% 以内
```

### 注文メモ（マークダウン対応）

各注文グループに **その時点での運用判断の根拠** を記載します。

| ❌ 悪い例 | ✅ 良い例 |
|-----------|----------|
| `QQQ 18株購入` | `新NISA枠でインデックスコア構築` |
| `SPYD追加購入` | `配当利回り4%超で定期積立ルール発動` |
| `AES売却+JPM購入` | `公益→金融へセクターローテーション 利上げ局面で金融セクター有利と判断` |
| `SHY新規購入` | `金利ピーク見込みで短期債ETF編入 ポートフォリオの守備力強化` |

> 💡 対話式ウィザードでは `prepare` 実行時にグループごとにメモを入力できます。
> 🤖 AI エージェント利用時は `upload --memo-file memo.csv` で一括適用できます。詳細は [README.ai.md](README.ai.md) を参照。

---

## 6. CSV フォーマット詳細

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

不明な点があれば Discord でお気軽にご連絡ください: `cho05134`

## Disclaimer

- このツールは [insighta cloud Inc.](https://insighta.cloud) が個人投資家の資産管理を支援する目的で開発したものであり、SBI証券株式会社とは一切関係がありません。SBI証券の名称・ロゴ・サービスに関するすべての権利はSBI証券株式会社に帰属します。
- このツールはSBI証券のWebサイトをクローリング・スクレイピングしません。ユーザーが自身のブラウザから手動で保存したHTMLファイルをローカルで解析するのみです。
- このツールは投資助言を目的としたものではありません。分析結果は参考情報であり、投資判断はご自身の責任で行ってください。
- パース結果の正確性は保証されません。アップロード前に必ず `verify` コマンドでデータを確認してください。
- このツールは商業目的での利用はできません。詳細は [LICENSE](LICENSE) をご確認ください。
- SBI証券のWebサイトの構造が変更された場合、パースが正しく動作しない可能性があります。その際は本リポジトリの Issue または Discord でご報告ください。

## License

CC BY-NC 4.0 © 2026 [insighta cloud Inc.](https://insighta.cloud)

このツールは個人利用・非商業目的に限り自由に使用できます。商業目的での利用は禁止されています。
詳細: https://creativecommons.org/licenses/by-nc/4.0/
