# AI Agent Guide — insighta CLI

Reference for AI agents (Amazon Q, GitHub Copilot, Cursor, etc.) operating this tool.
For human-readable documentation, see [README.md](README.md).

## Overview

A CLI tool that parses brokerage trade data → auto-classifies files → converts to CSV → uploads to the insighta cloud API.
Use `--non-interactive` (`-ni`) to skip all prompts and run entirely via options.

## Project Structure

```
insighta-cli/
├── sbi/
│   ├── cli.py          # CLI entry point (rich-click)
│   ├── parser.py       # Auto-classification parser (Dirs, Trade, Holding, Deposit, process_sbi_dir)
│   ├── analyzer.py     # P&L and ROI calculations
│   ├── api.py          # insighta cloud OpenAPI client
│   └── i18n.py         # Localization messages (ja/ko)
├── workspaces/
│   └── <name>/             # Working directory specified by --work
│       ├── input/
│       │   ├── sbi/               # Place all files here (auto-classified)
│       │   ├── manual/            # Manual input files (seed.csv, deposit.csv, etc.)
│       │   ├── rate.csv           # Period-based exchange rates (optional)
│       │   ├── ratio.csv          # Per-ticker portfolio ratio (optional)
│       │   └── project.yaml       # Portfolio settings (overridable via CLI options)
│       ├── output/
│       │   ├── history.csv        # parse output
│       │   ├── order.csv          # prepare output (order groups, key: group_dt)
│       │   ├── cash_deposits.csv  # prepare output (deposits/dividends, key: group_dt)
│       │   ├── upload.yaml        # prepare output (portfolio settings)
│       │   └── memo.csv           # Per-group memos (interactive input or AI-generated)
│       └── .cache/                # Parsed cache (UTF-8)
├── templates/          # Templates: config.yaml, project.yaml, seed.csv, rate.csv, ratio.csv, deposit.csv, memo.csv
├── config.yaml         # Config file (gitignored)
└── main.py             # Runnable via python main.py
```

## Pipeline

```
Step 1: Place files in input/sbi/ (CSV/HTML auto-classified)
    ↓
Step 1.5: Place input/rate.csv (required if any trades are settled in JPY)
    ↓
Step 2: parse (auto-classify → output/history.csv) + verify (optional)
    ↓
Step 3: prepare (output/history.csv → output/upload.yaml + output/order.csv + output/cash_deposits.csv + output/memo.csv)
    ↓
Step 4: upload (upload.yaml → insighta cloud API)
```

## Auto-Classification

Files placed in `input/sbi/` are classified by the following rules:

| Type | Extension | Detection |
|------|-----------|-----------|
| `history_csv` | .csv | Header contains「国内約定日」+「約定数量」 |
| `summary` | .html | Contains `stock-holding-table` or `css-djjzqp` |
| `history_html` | .html | Contains `table-row` + `sticker` |
| `domestic_fund` | .csv | Header contains「約定履歴照会」 |
| `currency_exchange` | .csv | Header contains「為替取引注文履歴」 |
| `deposit_gaika` | .csv | Header contains「外貨入出金明細」 |
| `deposit_transfer` | .csv | Header contains「入出金振替操作履歴」 |
| `deposit_dividend` | .csv | Header contains「検索件数」+「受渡日」 |

## Manual Input Files

Files placed in `input/manual/` are loaded automatically during parse and verify.

| File | Description |
|------|-------------|
| `seed.csv` | Holdings before tool adoption. Columns: `dt,ticker,qty,acct,price,avg,cur,base,rate,settle` |
| `rate.csv` | Period-based exchange rates. See `templates/rate.csv` |
| `deposit.csv` | Manual cash deposits/withdrawals. See `templates/deposit.csv` |

### deposit.csv format

```csv
insighta-deposit
dt,type,amount,cur
2026/05/01 00:00,budget,100000,JPY
2026/05/01 00:00,budget,-85.49,USD
```

- `type`: `budget` (deposit/withdrawal) or `profit` (realized gain/loss)
- Columns `ticker` and `rate` are optional — add them only when needed

## Non-Interactive Mode

### Full pipeline (wizard)

```bash
insighta --work <name> wizard --non-interactive \
  --name "My Portfolio" \
  --description "Imported from SBI" \
  --currency JPY \
  --budget 0 \
  --target-return 0.1 \
  --start-date 2025-01-01 \
  --target-date 2030-01-01 \
  --output-json
```

### Individual commands

```bash
# Set default workspace (then --work can be omitted)
insighta workspace <name>

# Step 2: parse
insighta --work <name> parse --rate 155
insighta --work <name> parse --rate-file input/rate.csv

# Step 2: verify
insighta --work <name> verify

# Step 3: prepare (non-interactive)
insighta --work <name> prepare \
  --non-interactive \
  --name "My Portfolio" \
  --currency JPY \
  --budget 0

# Step 4: upload (--work can be omitted if workspace is set)
insighta upload --yes
insighta upload --yes --dry-run   # dry run — no API calls
```

## Wizard Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--non-interactive` / `-ni` | flag | false | Skip all prompts |
| `--name` | str | "My Portfolio" | Portfolio name |
| `--description` | str | "Imported from brokerage trade history." | Description |
| `--currency` | str | "JPY" (ja) / "KRW" (ko) | Base currency (USD/JPY/KRW) |
| `--budget` | float | 10000.0 | Initial budget |
| `--target-return` | float | 0.1 | Target return (%) |
| `--start-date` | str | Earliest order/dividend date | Start date (YYYY-MM-DD) |
| `--target-date` | str | start-date + 10y | Target date (YYYY-MM-DD) |
| `--output-json` | flag | false | Output result as JSON to stdout |

> 💡 Define portfolio settings in `workspaces/<name>/input/project.yaml` to omit the above options. CLI options override project.yaml values.

> **Budget estimate**: Sum up all order costs in `workspaces/<name>/output/order.csv`.
> For JPY-base portfolios, convert USD orders using `price × quantity × rate`, then add JPY orders.
> For orders with no rate, use the nearest value from rate.csv as an approximation.

> ⚠️ **Set `--budget 0` if your deposit history already includes the initial funding.**
> If `input/sbi/` contains a deposit/transfer CSV with incoming funds, those amounts are automatically parsed as `budget` deposits.
> Setting `--budget` separately will double-count them. Use `--budget 0` or set `budget: 0` in `project.yaml`.

## Config

Reads `locale`, `api_key`, and `endpoint` from `config.yaml` in the project root.

```bash
cp templates/config.yaml config.yaml
```

```bash
# Verify config
insighta config
```

## API Management Commands

| Command | Description |
|---------|-------------|
| `insighta list-portfolios` | List your portfolios |
| `insighta search-portfolios --search <keyword>` | Search public portfolios |
| `insighta delete-portfolio <id> -y` | Delete a portfolio |
| `insighta nav-history <id>` | Get NAV history |
| `insighta metrics-history <id> --metrics twr` | Get metrics history |

All commands support `--output-json` for JSON output.

```bash
insighta list-portfolios --output-json
insighta search-portfolios --search "US stocks" --output-json
insighta delete-portfolio abc123 -y
insighta nav-history abc123 --output-json
insighta metrics-history abc123 --metrics twr --output-json
```

## Memo File

Memos entered during `prepare` group preview, or AI-generated memos, are saved to `workspaces/<name>/output/memo.csv`.
They are automatically loaded during `upload` and applied to each group.
Use `--memo-file` to specify an alternative file (override).

> ⚠️ **Running `prepare` will overwrite `memo.csv`.** If you have manually written or AI-generated memos, back them up before re-running `prepare`.

### memo.csv format

The key is the group number shown in the `prepare` preview (1, 2, 3...) — orders, dividends, and deposits merged in chronological order.

```csv
order_group,memo
1,Started US stock investment — AAPL initial position
2,DIA initial position — Dow high-dividend ETF for diversification
3,
4,Dividend yield exceeded 4% — triggered regular accumulation rule
```

Rows for groups without memos can be omitted (non-consecutive numbers are fine).

### Writing Good Memos

Memos should capture **the investment rationale at that point in time**, not just what was bought or sold.
Markdown is supported.

| ❌ Bad | ✅ Good |
|--------|--------|
| `Bought 18 QQQ` | `Building index core position in new NISA account` |
| `Added SPYD` | `Dividend yield exceeded 4% — triggered regular accumulation rule` |
| `Sold AES, bought JPM` | `Sector rotation: utilities → financials. Rate hike environment favors financials` |

Apply the same principle to `--name` and `--description`:

| Field | ❌ Bad | ✅ Good |
|-------|--------|--------|
| `--name` | `SBI US Stocks 2026` | `US Stocks — Long-term Growth + High Dividend` |
| `--description` | `Imported from SBI` | Investment policy in markdown (see example below) |

Example `--description`:

```markdown
## Investment Policy
- **Core**: S&P500 (SPY) + NASDAQ (QQQ)
- **Income**: SPYD for high dividend yield
- **Satellite**: Individual stocks (JPM, MAR, RACE)

## Goals
- 10% annualized return
- Dividend yield ≥ 3%
```

### AI Workflow

```bash
# 1. Set up project.yaml (avoids repeating CLI options)
cp templates/project.yaml workspaces/<name>/input/project.yaml
# Edit project.yaml with portfolio settings

# 2. Run prepare to generate order.csv + cash_deposits.csv
insighta --work <name> prepare -ni

# 3. Review workspaces/<name>/output/order.csv to understand each group,
#    then create workspaces/<name>/output/memo.csv with investment rationale per group.
#    The group number matches the order shown in the prepare preview output.
#
#    Example memo.csv:
#      order_group,memo
#      1,Building index core position in new NISA account
#      3,Dividend yield exceeded 4% — triggered regular accumulation rule
#
#    Groups without memos can be omitted.

# 4. Upload (memo.csv is loaded automatically)
insighta --work <name> upload --config workspaces/<name>/output/upload.yaml -y
```

## JSON Output

With `--output-json`, the final line of stdout is JSON.

Success:
```json
{"status": "success", "portfolio_id": "abc123", "url": "https://insighta.cloud/ja/portfolio/abc123", "success": 15, "failed": 0}
```

Failure:
```json
{"status": "error", "portfolio_id": "abc123", "url": "https://insighta.cloud/ja/portfolio/abc123", "success": 10, "failed": 5}
```

## Resume Behavior

If output files from a previous run exist, steps are skipped automatically.

| File | Effect |
|------|--------|
| `workspaces/<name>/output/history.csv` exists | Skips Step 2 (parse) |
| `workspaces/<name>/output/upload.yaml` + `order.csv` exist | Skips Steps 2–3 (parse + prepare) |

In `--non-interactive` mode, existing files are reused automatically.
To restart from scratch, delete the relevant files:

```bash
rm workspaces/<name>/output/history.csv workspaces/<name>/output/order.csv workspaces/<name>/output/cash_deposits.csv workspaces/<name>/output/upload.yaml workspaces/<name>/output/memo.csv
```

## Prerequisites

- Python >= 3.10
- At least one trade history CSV or HTML in `workspaces/<name>/input/sbi/`
- For upload: valid API key in `config.yaml`

### Install

```bash
pip install git+https://github.com/insighta-cloud/insighta-cli.git
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Failure (file not found, API error, etc.) |

## Example: Full Agent Workflow

```bash
# 1. Install
pip install -e .  # development
# or: pip install git+https://github.com/insighta-cloud/insighta-cli.git

# 2. Set up config
cp templates/config.yaml config.yaml
# Edit config.yaml with a valid API key

# 3. Verify input files exist
ls workspaces/<name>/input/sbi/

# 4. Set up project.yaml (optional — replaces CLI options)
cp templates/project.yaml workspaces/<name>/input/project.yaml
# Edit project.yaml

# 5. Run full pipeline (--name etc. can be omitted if project.yaml is present)
insighta --work <name> wizard -ni --output-json

# 6. Review workspaces/<name>/output/order.csv to understand each group,
#    then create workspaces/<name>/output/memo.csv with investment rationale per group.

# 7. Upload (memo.csv is loaded automatically)
insighta workspace <name>   # set default workspace
insighta upload -y --output-json

# 8. Parse JSON result from stdout
# {"status": "success", "portfolio_id": "...", "url": "...", ...}
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `No files found in input/sbi/` | `input/sbi/` is empty | Place input files |
| `分類不能: xxx` | Unsupported file format | Check file contents and format |
| `注文データが見つかりません` | `output/order.csv` is empty | Re-run parse → prepare |
| `401 Unauthorized` | Invalid API key | Check `config.yaml` |
| `api_key が config.yaml に設定されていません` | config.yaml not set up | Run `cp templates/config.yaml config.yaml` |
| verify shows diff | Incomplete history or missing seed | Add CSVs or update `input/manual/seed.csv` |
| Balance shortfall shown | Missing deposit/transfer data | Add deposit/transfer CSV to `input/sbi/` |
| USD balance mismatch | Dividends recorded in JPY | Add foreign currency deposit CSV to `input/sbi/` |
