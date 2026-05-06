# insighta CLI

> 🤖 AI エージェント（Amazon Q, GitHub Copilot, Cursor 等）での操作を推奨しています。詳細は [CLAUDE.md](CLAUDE.md) を参照してください。

[insighta cloud](https://insighta.cloud) へのポートフォリオ一括登録を支援するCLIツールです。
証券会社の取引データから注文を抽出し、検証・分析したうえで insighta cloud API へまとめてアップロードできます。

![upload preview](docs/images/upload-preview.png)

- **パース**: `input/sbi/` にファイルを置くだけで自動分類・CSV変換
- **検証**: CSV集計と実際の保有状況の照合
- **分析**: 実現/未実現損益・総合ROI
- **アップロード**: insighta cloud API へポートフォリオデータを一括送信
- **API管理**: ポートフォリオ一覧・検索・削除・NAV/メトリクス履歴取得

> ⚠️ 現在はSBI証券の海外株式口座のみ対応しています。
> 🇰🇷 한국어 (미래에셋증권) 지원은 현재 준비중입니다.

## このツールはこんな方向けです

- SBI証券で海外株式を取引している個人投資家
- 取引履歴を [insighta cloud](https://insighta.cloud) で一元管理したい方
- 手動でのポートフォリオ登録が面倒な方

## 注意事項

- 取引データはユーザー自身がSBI証券のWebサイトから手動でダウンロード・保存する必要があります
- 現在は海外株式口座のみ対応しています（国内株・投信は入出金として処理）
- SBI証券のHTML構造が変更された場合、パースが正しく動作しない可能性があります
- アップロード前に必ず `verify` コマンドでデータの正確性を確認してください

## 1. Setup

```bash
pip install git+https://github.com/insighta-cloud/insighta-cli.git
```
または開発用:

```bash
git clone https://github.com/insighta-cloud/insighta-cli.git
cd insighta-cli
pip install -e .
```

インストール後は `insighta` コマンドが使えます。

## 2. API キーの設定

insighta cloud API へのアップロード機能を使う場合に必要です（ローカル分析のみなら不要）。

```bash
cp templates/config.yaml config.yaml
```

`config.yaml` を開いて API キーとロケールを設定します。
API キーは https://insighta.cloud/settings から取得できます。

```yaml
locale: ja
api_key: "your-api-key-here"
endpoint: "https://openapi.insighta.cloud"
```

> ⚠️ `config.yaml` には秘密情報が含まれます。`.gitignore` に追加済みですが、公開リポジトリへのコミットにご注意ください。

## 3. データの準備

`input/sbi/` ディレクトリにファイルを置くだけで、ツールが自動的にファイル種別を判別してパースします。

### 取得元と配置方法

| データ | 取得元 | 形式 |
|--------|--------|------|
| **約定履歴** (必須) | [計座管理 → 取引履歴](https://site2.sbisec.co.jp/ETGate/?_ControlID=WPLETacR007Control&_PageID=DefaultPID&_DataStoreID=DSWPLETacR007Control&getFlg=on&_ActionID=DefaultAID&OutSide=on) | CSV (Shift_JIS) |
| **保有銘柄** (検証用) | 外国株式 → 口座管理 → 保有銘柄 | HTML (Copy outerHTML) |
| **為替取引履歴** | https://member.c.sbisec.co.jp/banking/fc/activity-history | CSV (Shift_JIS) |
| **外貨入出金明細** | https://member.c.sbisec.co.jp/banking/fc/detail-history | CSV (Shift_JIS) |
| **入出金振替履歴** | 入出金・振替 | CSV (Shift_JIS) |
| **配当金** | https://member.c.sbisec.co.jp/banking/fc/detail-history | CSV (Shift_JIS) |

> 💡 約定履歴は **計座管理 → 取引履歴** から取得してください。ここには約定単価だけでなく受渡金額（手数料・税金込み）も含まれるため、正確なコスト計算が可能です。
> 2024年以前のデータは **計座管理 → 取引報告書** から確認できます。

### 自動認識されるファイル種別

| 種別 | 判別条件 |
|------|----------|
| 約定履歴CSV | ヘッダーに「国内約定日」「約定数量」を含む |
| 保有銘柄HTML | `stock-holding-table` を含むHTML |
| 取引履歴HTML | `table-row` + `sticker` を含むHTML |
| 投信約定CSV | ヘッダーに「約定履歴照会」を含む |
| 為替取引CSV | ヘッダーに「為替取引注文履歴」を含む |
| 外貨入出金CSV | ヘッダーに「外貨入出金明細」を含む |
| 入出金振替CSV | ヘッダーに「入出金振替操作履歴」を含む |
| 配当金CSV | ヘッダーに「検索件数」+「受渡日」を含む |

すべてのファイルを `workspaces/<name>/input/sbi/` に配置するだけで OK です。

### 手動入力 (input/manual/)

自動認識できないデータや、ツール導入前の保有分を手動で登録する場合:

| ファイル | 配置先 | 用途 |
|----------|--------|------|
| seed.csv | `workspaces/<name>/input/manual/seed.csv` | ツール導入前の保有銘柄 |
| rate.csv | `workspaces/<name>/input/rate.csv` | 期間別為替レート |
| ratio.csv | `workspaces/<name>/input/ratio.csv` | 銘柄別ポートフォリオ比率 |
| project.yaml | `workspaces/<name>/input/project.yaml` | ポートフォリオ設定 |

### project.yaml

ポートフォリオのメタデータを事前に定義できます。`prepare` / `wizard` 実行時に自動で読み込まれ、CLI オプションで個別にオーバーライド可能です。

```bash
cp templates/project.yaml workspaces/<name>/input/project.yaml
```

```yaml
name: "米国株 長期成長+高配当"
description: |
  ## 運用方針
  - コア: SPY + QQQ
  - 配当: SPYD
currency: JPY
budget: 500000
target_return: 10
start_date: "2025-01-01"
target_date: "2035-01-01"
ratio:
  SPY: 0.4
  QQQ: 0.3
  AAPL: 0.2
```

> 💡 `ratio` を定義すると `input/ratio.csv` より優先されます。どちらもない場合は全銘柄均等配分になります。


## 4. Quick Start

`--work` オプションで作業ディレクトリを指定します。各ポートフォリオのデータは `workspaces/<name>/` 以下に格納されます。

```bash
insighta --work <name>
```

引数なしで実行すると、対話式ウィザードが データ配置 → パース → 検証 → アップロード まで順番に案内します。

> 💡 `--work` を省略した場合はプロジェクトルートの `input/` / `output/` を使用します（後方互換）。

## 5. コマンド一覧

### メインワークフロー

| コマンド | 説明 |
|---------|------|
| `insighta --work <name>` | 対話式ウィザード（全ステップ一括） |
| `insighta --work <name> parse` | `input/sbi/` を自動分類・パース → `output/history.csv` |
| `insighta --work <name> verify` | CSV集計 vs 保有銘柄HTMLの照合 |
| `insighta --work <name> analyze` | 実現/未実現損益 + 総合ROI |
| `insighta --work <name> prepare` | アップロード用ファイル生成（`upload.yaml` + `order.csv`） |
| `insighta --work <name> upload` | insighta cloud API へポートフォリオデータを送信 |

### API管理

| コマンド | 説明 |
|---------|------|
| `insighta config` | config.yaml の設定内容を表示 |
| `insighta list-portfolios` | 自分のポートフォリオ一覧を取得 |
| `insighta search-portfolios --search <keyword>` | 公開ポートフォリオを検索 |
| `insighta delete-portfolio <id> -y` | ポートフォリオを削除 |
| `insighta nav-history <id>` | NAV履歴を取得 |
| `insighta metrics-history <id> --metrics twr` | メトリクス履歴を取得 |

> すべてのAPI管理コマンドは `--output-json` フラグで JSON 出力に対応しています。

### 使用例

```bash
insighta --work <name> parse --rate 155                    # 固定為替レート指定
insighta --work <name> parse --rate-file input/rate.csv    # 期間別為替レートCSV
insighta --work <name> upload --config workspaces/<name>/output/upload.yaml -y
```

> **初期予算の目安**: 全注文の購入コスト合計をカバーできる金額を設定してください。
> ポートフォリオ通貨が JPY の場合、USD 建て注文は `価格 × 数量 × 為替レート` で円換算し、JPY 建て注文と合算した金額が目安です。

---

## 6. ポートフォリオ名・説明・注文メモの書き方

insighta cloud のポートフォリオは **運用記録** です。
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

> 💡 対話式ウィザードでは `prepare` 実行時にグループごとにメモを入力できます。入力したメモは `workspaces/<name>/output/memo.csv` に保存され、`upload` 時に自動で適用されます。
> 🤖 AI エージェント利用時は `prepare` 後に `workspaces/<name>/output/memo.csv` を生成して `upload` してください。詳細は [README.ai.md](README.ai.md) を参照。

---

## 7. CSV フォーマット詳細

### seed CSV

ツール導入前の保有分を手動で登録する場合に使用。`workspaces/<name>/input/manual/seed.csv` に配置。

```csv
dt,ticker,qty,acct,price,avg,cur,base,rate
2021/10/25 00:00,AAPL,1,TT,149.50,149.50,JPY,USD,113.96
```

### rate CSV

通貨ペアごとに期間とレートを定義。`workspaces/<name>/input/rate.csv` に配置。

```csv
from,to,pair,rate
2024/01/01,2024/12/31,USD/JPY,155.50
2025/01/01,2025/12/31,USD/JPY,148.20
2026/02/19 09:00,2026/02/19 15:00,USD/JPY,155.38
```

`from`/`to` は日付のみ (`2024/01/01`) でも、時刻付き (`2024/01/01 09:00`) でも可。
日付のみの場合は `00:00`〜`23:59` として扱います。

### ratio CSV

銘柄ごとのポートフォリオ比率を指定。`workspaces/<name>/input/ratio.csv` に配置。

```csv
ticker,ratio
SPY,0.4
QQQ,0.3
AAPL,0.2
```

- 1 を 100% として指定（例: `0.4` = 40%）
- ファイルがない場合は全銘柄を均等配分
- 現金比率はサーバー側で自動計算されるため指定不要

---

## Support

不明な点があれば Discord でお気軽にご連絡ください: `insighta_cloud`

## Disclaimer

- このツールは [insighta cloud Inc.](https://insighta.cloud) が個人投資家の資産管理を支援する目的で開発したものであり、SBI証券株式会社とは一切関係がありません。SBI証券の名称・ロゴ・サービスに関するすべての権利はSBI証券株式会社に帰属します。
- このツールはSBI証券のWebサイトをクローリング・スクレイピングしません。ユーザーが自身のブラウザから手動で保存したファイルをローカルで解析するのみです。
- このツールは投資助言を目的としたものではありません。分析結果は参考情報であり、投資判断はご自身の責任で行ってください。
- パース結果の正確性は保証されません。アップロード前に必ず `verify` コマンドでデータを確認してください。
- このツールは商業目的での利用はできません。詳細は [LICENSE](LICENSE) をご確認ください。
- SBI証券のWebサイトの構造が変更された場合、パースが正しく動作しない可能性があります。その際は本リポジトリの Issue または Discord でご報告ください。

## License

CC BY-NC 4.0 © 2026 [insighta cloud Inc.](https://insighta.cloud)

このツールは個人利用・非商業目的に限り自由に使用できます。商業目的での利用は禁止されています。
詳細: https://creativecommons.org/licenses/by-nc/4.0/
