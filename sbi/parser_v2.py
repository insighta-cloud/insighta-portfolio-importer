"""SBI証券 input/sbi/ 自動認識パーサー (v2)

input/sbi/ にファイルを置くだけで自動分類・パース。
"""

import glob
import os
import re
from dataclasses import dataclass, field
from decimal import Decimal

import pandas as pd

from sbi.parser import (
    Trade, Holding, Deposit, Dirs,
    parse_summary_html, parse_history_html,
    _parse_sbi_transfer, _parse_sbi_gaika_nyushukkin,
    _parse_sbi_exchange,
    EXCHANGE_CURRENCY, JST, _to_jst_iso,
    load_rate_file, lookup_rate,
)

# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class ParseResult:
    trades: list[Trade] = field(default_factory=list)
    holdings: list[Holding] = field(default_factory=list)
    deposits: list[Deposit] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def merge(self, other: "ParseResult"):
        self.trades.extend(other.trades)
        self.holdings.extend(other.holdings)
        self.deposits.extend(other.deposits)
        self.skipped.extend(other.skipped)
        self.warnings.extend(other.warnings)


# ---------------------------------------------------------------------------
# Classify
# ---------------------------------------------------------------------------

def _read_head(filepath: str, n: int = 10) -> tuple[str, list[str]]:
    """ファイル先頭n行を読む。SJIS → UTF-8 の順で試行。"""
    raw = open(filepath, "rb").read(4096)
    for enc in ("shift_jis", "utf-8-sig", "utf-8"):
        try:
            text = raw.decode(enc)
            return enc, text.splitlines()[:n]
        except (UnicodeDecodeError, ValueError):
            continue
    return "utf-8", raw.decode("utf-8", errors="ignore").splitlines()[:n]


def classify(filepath: str) -> str | None:
    """ファイルを自動分類。戻り値はタイプ文字列、不明なら None。"""
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".html":
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            head = f.read(2048)
        if "stock-holding-table" in head or "css-djjzqp" in head:
            return "summary"
        if "table-row" in head and "sticker" in head:
            return "history_html"
        return None

    if ext != ".csv":
        return None

    _, lines = _read_head(filepath)
    text = "\n".join(lines)

    # メタデータ行で判別 (順序重要: 具体的なものから)
    if "期間（国内約定日）" in text or ("国内約定日" in text and "約定数量" in text):
        return "history_csv"
    if "約定履歴照会" in text:
        return "domestic_fund"
    if "為替取引注文履歴" in text:
        return "currency_exchange"
    if "外貨入出金明細" in text:
        return "deposit_gaika"
    if "入出金振替操作履歴" in text or "SBIインデックスファンド入出金" in text:
        return "deposit_transfer"
    if "検索件数" in text and "受渡日" in text:
        return "deposit_dividend"

    return None


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

_EXCHANGE_MAP = {
    "NASDAQ": "NASDAQ",
    "NYSE ARCA": "NYSE Arca",
    "New York Stock Exchange": "NYSE",
    "NYSE": "NYSE",
}

_TICKER_RE = re.compile(r"(\S+)\s*/\s*(.+)$")


def _parse_meigara(name: str) -> tuple[str, str, str]:
    """銘柄名 → (ticker, exchange, base_currency)
    例: 'iシェアーズ 米国国債 1-3年 ETF SHY / NASDAQ' → ('SHY', 'NASDAQ', 'USD')
    """
    m = _TICKER_RE.search(name)
    if not m:
        return name, "", "USD"
    ticker = m.group(1)
    exchange_raw = m.group(2).strip()
    exchange = _EXCHANGE_MAP.get(exchange_raw, exchange_raw)
    base = EXCHANGE_CURRENCY.get(exchange, "USD")
    return ticker, exchange, base


def _find_header_row(filepath: str, marker: str, encoding: str = "shift_jis") -> int:
    """マーカー文字列を含むヘッダー行番号を返す。"""
    with open(filepath, "rb") as f:
        raw = f.read()
    text = raw.decode(encoding, errors="ignore")
    for i, line in enumerate(text.splitlines()):
        if marker in line:
            return i
    return 0


def _parse_yakujo_csv(filepath: str, rates=None) -> ParseResult:
    """海外株式約定履歴CSV → Trade + fee Deposit リスト

    USD決済: fee = 受渡金額 - 約定単価×数量 (買付) or 約定単価×数量 - 受渡金額 (売却)
    JPY決済: rate があれば fee = 受渡金額 - 約定単価×数量×rate
    """
    result = ParseResult()
    skip = _find_header_row(filepath, "国内約定日,通貨,銘柄名")
    df = pd.read_csv(filepath, encoding="shift_jis", skiprows=skip)

    for _, row in df.iterrows():
        dt_raw = str(row["国内約定日"]).replace("年", "/").replace("月", "/").replace("日", "")
        ticker, exchange, base = _parse_meigara(str(row["銘柄名"]))
        is_buy = row["取引"] == "買付"
        qty = int(row["約定数量"])
        acct = "TT" if row["預り区分"] == "特定" else row["預り区分"]
        price = Decimal(str(row["約定単価"]))
        cur = "USD" if row["通貨"] == "米国ドル" else "JPY"
        settle = Decimal(str(row["受渡金額"]))
        dt_iso = _to_jst_iso(dt_raw)

        result.trades.append(Trade(
            dt=dt_iso, ticker=ticker,
            qty=qty if is_buy else -qty,
            acct=acct, price=price, avg=price, cur=cur, base=base,
        ))

        # 手数料自動計算
        calc = price * qty
        if cur == "USD":
            fee = (settle - calc) if is_buy else (calc - settle)
        elif rates:
            rate = lookup_rate(rates, dt_iso, cur, base)
            if rate:
                fee = (settle - calc * rate) if is_buy else (calc * rate - settle)
            else:
                result.warnings.append(f"rate未設定: {dt_iso[:10]} {ticker} {cur}")
                continue
        else:
            continue

        if fee > 0:
            result.deposits.append(Deposit(
                dt=dt_iso, amount=-fee, cur=cur,
                type="budget", ticker=f"fee:{ticker}",
            ))

    return result


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------

def _parse_domestic_fund(filepath: str) -> ParseResult:
    """国内約定履歴CSV → 投信売買を JPY 現金 Deposit に変換。

    買付 → マイナス(出金), 売却 → プラス(入金)
    """
    result = ParseResult()
    skip = _find_header_row(filepath, "約定日,銘柄", encoding="shift_jis")
    df = pd.read_csv(filepath, encoding="shift_jis", skiprows=skip)

    # 末尾の空行を除去
    df = df.dropna(subset=["約定日"])

    for _, row in df.iterrows():
        dt_raw = str(row["約定日"]).strip()
        trade_type = str(row["取引"]).strip() if pd.notna(row.get("取引")) else ""
        settle_str = str(row["受渡金額/決済損益"]).strip().replace(",", "")

        try:
            amount = Decimal(settle_str)
        except Exception:
            continue

        # 買付 → 現金マイナス, 売却 → 現金プラス
        if "買" in trade_type:
            amount = -amount
        elif "売" not in trade_type:
            continue

        meigara = str(row["銘柄"]).strip() if pd.notna(row.get("銘柄")) else ""

        result.deposits.append(Deposit(
            dt=_to_jst_iso(dt_raw),
            amount=amount,
            cur="JPY",
            type="budget",
            ticker=meigara,
        ))
    return result


_HANDLERS: dict[str, callable] = {
    "summary": lambda fp: _wrap_holdings(fp),
    "history_html": lambda fp: _wrap_history_html(fp),
    "domestic_fund": lambda fp: _parse_domestic_fund(fp),
    "deposit_transfer": lambda fp: ParseResult(deposits=_parse_sbi_transfer(fp)),
    "deposit_gaika": lambda fp: ParseResult(deposits=_parse_sbi_gaika_nyushukkin(fp)),
    "currency_exchange": lambda fp: ParseResult(deposits=_parse_sbi_exchange(fp)),
}


def _wrap_holdings(filepath: str) -> ParseResult:
    holdings = parse_summary_html(filepath)
    return ParseResult(holdings=holdings)


def _wrap_history_html(filepath: str) -> ParseResult:
    trades, skipped = parse_history_html(filepath)
    return ParseResult(trades=trades, skipped=skipped)


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def _dedup_deposits(deposits: list[Deposit]) -> tuple[list[Deposit], list[str]]:
    """金額+日付近接(±2日)で重複 Deposit を除去。後に出現した方を除去。"""
    from datetime import datetime, timedelta

    def _parse_dt(iso: str) -> datetime | None:
        try:
            return datetime.fromisoformat(iso)
        except Exception:
            return None

    kept: list[Deposit] = []
    skipped: list[str] = []

    for d in deposits:
        dt = _parse_dt(d.dt)
        dup = False
        if dt:
            for k in kept:
                kt = _parse_dt(k.dt)
                if kt and k.cur == d.cur and k.amount == d.amount and abs((dt - kt).days) <= 2:
                    skipped.append(
                        f"重複除去: {d.dt} {d.amount} {d.cur} {d.ticker}"
                        f" ← 既存: {k.dt} {k.amount} {k.cur} {k.ticker}"
                    )
                    dup = True
                    break
        if not dup:
            kept.append(d)

    return kept, skipped


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def process_sbi_dir(sbi_dir: str, cache_dir: str | None = None, rate_file: str = "") -> ParseResult:
    """input/sbi/ ディレクトリ内の全ファイルを自動分類・パース。

    cache_dir が指定された場合、パース済みCSVを UTF-8 で保存する。
    rate_file が指定された場合、JPY決済取引の手数料計算に使用する。
    """
    rates = load_rate_file(rate_file) if rate_file else []
    result = ParseResult()
    files = sorted(glob.glob(os.path.join(sbi_dir, "*")))

    for fp in files:
        if os.path.isdir(fp):
            continue
        file_type = classify(fp)

        if file_type == "history_csv":
            result.merge(_parse_yakujo_csv(fp, rates=rates))
        elif file_type and file_type in _HANDLERS:
            result.merge(_HANDLERS[file_type](fp))
        elif file_type is None:
            result.warnings.append(f"分類不能: {os.path.basename(fp)}")
        else:
            result.warnings.append(f"未対応タイプ ({file_type}): {os.path.basename(fp)}")

    # 重複 Deposit 除去
    result.deposits, dup_skipped = _dedup_deposits(result.deposits)
    result.skipped.extend(dup_skipped)

    if cache_dir:
        _save_cache(result, cache_dir)

    return result


def _save_cache(result: ParseResult, cache_dir: str):
    """パース結果を UTF-8 CSV でキャッシュに保存。"""
    os.makedirs(cache_dir, exist_ok=True)

    if result.trades:
        rows = [
            {
                "dt": t.dt, "ticker": t.ticker, "qty": t.qty, "acct": t.acct,
                "price": str(t.price), "avg": str(t.avg), "cur": t.cur, "base": t.base,
            }
            for t in result.trades
        ]
        pd.DataFrame(rows).to_csv(
            os.path.join(cache_dir, "trades.csv"), index=False, encoding="utf-8"
        )

    if result.holdings:
        rows = [
            {
                "ticker": h.ticker, "acct": h.acct, "qty": h.qty,
                "cost": str(h.cost), "price": str(h.price), "pnl": str(h.pnl),
            }
            for h in result.holdings
        ]
        pd.DataFrame(rows).to_csv(
            os.path.join(cache_dir, "holdings.csv"), index=False, encoding="utf-8"
        )

    if result.deposits:
        rows = [
            {
                "dt": d.dt, "type": d.type, "amount": str(d.amount),
                "cur": d.cur, "ticker": d.ticker,
                "rate": str(d.rate) if d.rate is not None else "",
            }
            for d in result.deposits
        ]
        pd.DataFrame(rows).to_csv(
            os.path.join(cache_dir, "deposits.csv"), index=False, encoding="utf-8"
        )

    if result.warnings:
        with open(os.path.join(cache_dir, "warnings.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(result.warnings))
