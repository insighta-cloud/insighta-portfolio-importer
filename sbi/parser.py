"""SBI証券 パーサー

input/sbi/ にファイルを置くだけで自動分類・パース。
"""

import csv
import glob
import os
import re
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime, timezone, timedelta

import pandas as pd
from bs4 import BeautifulSoup

WORKSPACES_DIR = "workspaces"

JST = timezone(timedelta(hours=9))

EXCHANGE_CURRENCY = {
    "NYSE": "USD", "NASDAQ": "USD", "NYSE Arca": "USD", "NYSE American": "USD",
    "KOSPI": "KRW", "KOSDAQ": "KRW",
    "TSE": "JPY",
}


# ---------------------------------------------------------------------------
# Dirs
# ---------------------------------------------------------------------------

@dataclass
class Dirs:
    """作業ディレクトリ設定。--work オプションで切り替え可能。"""
    work: str = ""

    @classmethod
    def from_work(cls, work: str = "") -> "Dirs":
        return cls(work=work)

    @property
    def _base(self) -> str:
        return os.path.join(WORKSPACES_DIR, self.work) if self.work else ""

    @property
    def input(self) -> str:
        return os.path.join(self._base, "input") if self._base else "input"

    @property
    def output(self) -> str:
        return os.path.join(self._base, "output") if self._base else "output"

    @property
    def cache(self) -> str:
        return os.path.join(self._base, ".cache") if self._base else ".cache"

    @property
    def history(self) -> str:
        return os.path.join(self.input, "history")

    @property
    def summary(self) -> str:
        return os.path.join(self.input, "summary")

    @property
    def seed(self) -> str:
        return os.path.join(self.input, "seed")

    @property
    def deposit(self) -> str:
        return os.path.join(self.input, "deposit")

    @property
    def exchange(self) -> str:
        return os.path.join(self.input, "currency_exchange")

    @property
    def sbi(self) -> str:
        return os.path.join(self.input, "sbi")

    @property
    def manual(self) -> str:
        return os.path.join(self.input, "manual")

    @property
    def rate_csv(self) -> str:
        return os.path.join(self.input, "rate.csv")

    @property
    def ratio_csv(self) -> str:
        return os.path.join(self.input, "ratio.csv")

    @property
    def project_yaml(self) -> str:
        return os.path.join(self.input, "project.yaml")

    @property
    def history_csv(self) -> str:
        return os.path.join(self.output, "history.csv")

    @property
    def order_csv(self) -> str:
        return os.path.join(self.output, "order.csv")

    @property
    def upload_yaml(self) -> str:
        return os.path.join(self.output, "upload.yaml")

    @property
    def memo_csv(self) -> str:
        return os.path.join(self.output, "memo.csv")

    @property
    def cash_deposits_csv(self) -> str:
        return os.path.join(self.output, "cash_deposits.csv")

    @property
    def request_payload_log(self) -> str:
        return os.path.join(self.output, "request_payload.log")

    def ensure_output(self):
        """output ディレクトリを作成する。"""
        os.makedirs(self.output, exist_ok=True)


DEFAULT_DIRS = Dirs()


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _to_jst_iso(dt_str: str) -> str:
    """'2026/03/19 15:26' → '2026-03-19T15:26:00+09:00'"""
    if not dt_str:
        return ""
    for fmt in ("%Y/%m/%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(dt_str, fmt).replace(tzinfo=JST).isoformat()
        except ValueError:
            continue
    return dt_str


def _to_decimal(val: str) -> Decimal:
    """文字列 → Decimal（空文字・'-' は 0）"""
    if not val or val == "-":
        return Decimal("0")
    return Decimal(val.replace(",", ""))


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    dt: str          # ISO 8601 JST
    ticker: str
    qty: int
    acct: str
    price: Decimal
    avg: Decimal
    cur: str         # 決済通貨 (JPY or USD)
    base: str = "USD"  # 銘柄の基準通貨


@dataclass
class Holding:
    ticker: str
    acct: str
    qty: int
    cost: Decimal = Decimal("0")
    price: Decimal = Decimal("0")
    pnl: Decimal = Decimal("0")


@dataclass
class Deposit:
    dt: str          # ISO 8601 JST or raw datetime
    amount: Decimal
    cur: str
    type: str = "budget"  # budget | dividend
    ticker: str = ""
    rate: Decimal | None = None


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
# Deposit parsers
# ---------------------------------------------------------------------------

def _parse_sbi_transfer(filepath: str) -> list[Deposit]:
    """SBI証券 入出金振替操作履歴CSV (UTF-8) をパース."""
    deposits: list[Deposit] = []
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    lines = content.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if "受付日時" in line and "状態" in line:
            header_idx = i
            break
    if header_idx is None:
        return deposits
    data_text = "\n".join(lines[header_idx:])
    for row in csv.DictReader(data_text.splitlines()):
        status = row.get("状態", "").strip()
        if status not in ("完了", "確定"):
            continue
        dt_raw = row.get("受付日時", "").strip()
        kubun = row.get("区分", "").strip()
        in_amt = row.get("入金指示金額", "-").strip()
        out_amt = row.get("出金指示金額", "-").strip()
        if kubun == "入金" and in_amt != "-":
            amount = Decimal(in_amt.replace(",", ""))
        elif kubun == "出金" and out_amt != "-":
            amount = -Decimal(out_amt.replace(",", ""))
        else:
            continue
        deposits.append(Deposit(
            dt=_to_jst_iso(dt_raw), amount=amount, cur="JPY", type="budget",
        ))
    return deposits


def _parse_sbi_distribution(filepath: str) -> list[Deposit]:
    """SBI証券 配当金CSV (Shift_JIS) をパース."""
    deposits: list[Deposit] = []
    with open(filepath, "r", encoding="shift_jis") as f:
        content = f.read()
    lines = content.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if "受渡日" in line and "銘柄名" in line:
            header_idx = i
            break
    if header_idx is None:
        return deposits
    data_text = "\n".join(lines[header_idx:])
    for row in csv.DictReader(data_text.splitlines()):
        product = row.get("商品", "").strip()
        if "米国株式" in product:
            continue
        dt_raw = row.get("受渡日", "").strip()
        name = row.get("銘柄名", "").strip()
        amt_str = row.get("受取額(税引後・円)", "").strip().replace("\n", "").replace(",", "")
        if not dt_raw or not amt_str:
            continue
        try:
            amount = Decimal(amt_str)
        except Exception:
            continue
        ticker = name.split()[-1] if name else ""
        deposits.append(Deposit(
            dt=_to_jst_iso(dt_raw), amount=amount, cur="JPY",
            type="dividend", ticker=ticker,
        ))
    return deposits


def _parse_sbi_exchange(filepath: str) -> list[Deposit]:
    """SBI証券 為替取引注文履歴CSV (Shift_JIS) をパース."""
    deposits: list[Deposit] = []
    with open(filepath, "rb") as f:
        raw = f.read()
    content = raw.decode("shift_jis", errors="ignore")
    lines = content.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if "口座区分" in line and "約定レート" in line:
            header_idx = i
            break
    if header_idx is None:
        return deposits
    data_text = "\n".join(lines[header_idx:])
    CURRENCY_MAP = {"米ドル": "USD", "ユーロ": "EUR", "英ポンド": "GBP", "豪ドル": "AUD"}
    for row in csv.DictReader(data_text.splitlines()):
        status = row.get("注文状況", "").strip()
        if status != "約定済":
            continue
        dt_raw = row.get("約定日時", "").strip().replace("\n", "")
        qty_str = row.get("数量", "0").strip().replace(",", "")
        jpy_str = row.get("受渡金額", "0").strip().replace(",", "")
        rate_str = row.get("約定レート", "").strip()
        currency_ja = row.get("通貨", "").strip()
        order_type = row.get("注文種別", "").strip()
        foreign_cur = CURRENCY_MAP.get(currency_ja, currency_ja)
        try:
            qty = Decimal(qty_str)
            jpy_amount = Decimal(jpy_str)
            rate = Decimal(rate_str) if rate_str else None
        except Exception:
            continue
        dt_iso = _to_jst_iso(dt_raw)
        if order_type == "買付":
            deposits.append(Deposit(dt=dt_iso, amount=-jpy_amount, cur="JPY", type="budget", rate=rate))
            deposits.append(Deposit(dt=dt_iso, amount=qty, cur=foreign_cur, type="budget", rate=rate))
        elif order_type == "売付":
            deposits.append(Deposit(dt=dt_iso, amount=-qty, cur=foreign_cur, type="budget", rate=rate))
            deposits.append(Deposit(dt=dt_iso, amount=jpy_amount, cur="JPY", type="budget", rate=rate))
    return deposits


def _parse_sbi_gaika_nyushukkin(filepath: str) -> list[Deposit]:
    """SBI証券 外貨入出金明細CSV をパース. 分配金/配当金 → USD dividend."""
    deposits: list[Deposit] = []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        content = f.read()
    lines = content.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if "入出金日" in line and "区分" in line and "入金額" in line:
            header_idx = i
            break
    if header_idx is None:
        return deposits
    data_text = "\n".join(lines[header_idx:])
    for row in csv.DictReader(data_text.splitlines()):
        kubun = row.get("区分", "").strip()
        tekiyou = row.get("摘要", "").strip()
        dt_raw = row.get("入出金日", "").strip()
        if not dt_raw:
            continue
        if kubun in ("分配金", "配当金"):
            amount_str = row.get("入金額", "0").strip().replace(",", "")
            if not amount_str or amount_str == "0":
                continue
            try:
                amount = Decimal(amount_str)
            except Exception:
                continue
            ticker = ""
            parts = tekiyou.split()
            if parts:
                ticker = parts[0]
            deposits.append(Deposit(
                dt=_to_jst_iso(dt_raw), amount=amount, cur="USD",
                type="dividend", ticker=ticker,
            ))
        elif kubun == "-" and ("外貨出金" in tekiyou or "外貨入金" in tekiyou):
            out_str = row.get("出金額", "0").strip().replace(",", "")
            in_str = row.get("入金額", "0").strip().replace(",", "")
            try:
                out_amt = Decimal(out_str) if out_str and out_str != "0" else Decimal(0)
                in_amt = Decimal(in_str) if in_str and in_str != "0" else Decimal(0)
            except Exception:
                continue
            amount = in_amt - out_amt
            if amount == 0:
                continue
            deposits.append(Deposit(
                dt=_to_jst_iso(dt_raw), amount=amount, cur="USD",
                type="budget", ticker="",
            ))
    return deposits



# ---------------------------------------------------------------------------
# Rate file
# ---------------------------------------------------------------------------

@dataclass
class RateEntry:
    start: str
    end: str
    pair: str
    rate: Decimal


def load_rate_file(filepath: str) -> list[RateEntry]:
    """為替レートCSVを読み込む"""
    entries: list[RateEntry] = []
    with open(filepath, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            entries.append(RateEntry(
                start=row["from"].strip(),
                end=row["to"].strip(),
                pair=row["pair"].strip(),
                rate=Decimal(row["rate"].strip()),
            ))
    return entries


def _normalize_dt(val: str) -> str:
    return val if " " in val else f"{val} 00:00"


def _normalize_dt_end(val: str) -> str:
    return val if " " in val else f"{val} 23:59"


def lookup_rate(entries: list[RateEntry], dt: str, cur: str, base: str) -> Decimal | None:
    """決済通貨と基準通貨が異なる場合のみ該当期間のレートを返す"""
    if cur == base:
        return None
    trade_dt = dt[:16].replace("-", "/").replace("T", " ") if dt else ""
    pair = f"{base}/{cur}"
    for e in entries:
        start = _normalize_dt(e.start)
        end = _normalize_dt_end(e.end)
        if e.pair == pair and start <= trade_dt <= end:
            return e.rate
    return None


# ---------------------------------------------------------------------------
# HTML parsers
# ---------------------------------------------------------------------------

def _text(el, selector: str) -> str:
    found = el.select_one(selector)
    return found.text.strip() if found else ""


def _attr(el, selector: str, attr: str) -> str:
    found = el.select_one(selector)
    return found[attr] if found else ""


def _label_text(el) -> str:
    label = el.select_one("label") if el else None
    if not label:
        return ""
    return label.text.strip().replace(" USD", "").replace(" JPY", "")


def parse_history_html(filename: str) -> tuple[list[Trade], list[str]]:
    """注文履歴HTMLをパースし、約定済み取引リストとスキップ理由を返す"""
    with open(filename, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    trades, skipped = [], []
    for row in soup.select("li.table-row"):
        status = _text(row, ".sticker")
        dt_raw = _text(row, '[data-label="国内注文日時："]')
        ticker = _attr(row, "[data-security-code]", "data-security-code")
        trade_type = _text(row, '[data-label="取引"]')
        is_buy = "買" in trade_type

        acct_raw = _text(row, '[data-label="預り"]')
        acct = "TT" if acct_raw == "特定" else acct_raw

        qty_str = _text(row, '[data-label="数量(未約定数量)"] label')
        price_str = _text(row, '[data-label="現在値"] label')
        avg_str = _text(row, '[data-label="平均約定単価"] label')

        payment = _text(row, '[data-label="決済方法"]')
        cur = "USD" if payment == "外貨" else "JPY"

        qty_signed = qty_str if is_buy else f"-{qty_str}"

        if status != "完了":
            skipped.append(f"[{status}] {dt_raw} {ticker} {qty_signed}")
            continue
        if avg_str in ("-", ""):
            skipped.append(f"[avg無し] {dt_raw} {ticker} {qty_signed}")
            continue

        code_el = row.select_one("[data-security-code]")
        exchange = ""
        if code_el:
            p_el = code_el.select_one("p.md-font-xs")
            if p_el:
                exchange = p_el.text.replace(ticker, "").strip()
        base = EXCHANGE_CURRENCY.get(exchange, "USD")

        trades.append(Trade(
            dt=_to_jst_iso(dt_raw),
            ticker=ticker,
            qty=int(qty_signed),
            acct=acct,
            price=_to_decimal(price_str),
            avg=_to_decimal(avg_str),
            cur=cur,
            base=base,
        ))
    return trades, skipped


def parse_summary_html(filename: str) -> list[Holding]:
    """保有銘柄HTMLをパースし、銘柄リストを返す"""
    with open(filename, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    holdings = []
    current_acct = ""
    for sec in soup.select("li.css-djjzqp"):
        header = sec.select_one("div.bb-light > .font-bold.font-sm") or \
                 sec.select_one(".font-bold.font-sm.p-x-1")
        if header:
            txt = header.text.strip()
            if "特定" in txt:
                current_acct = "TT"
            elif "NISA" in txt:
                current_acct = "NISA"
            continue

        if not current_acct:
            continue

        for el in sec.select("[data-security-code]"):
            ticker = el["data-security-code"]
            parent = el.find_parent("div", class_="p-half")
            if not parent:
                continue
            siblings = parent.find_next_siblings("div")
            vals = [_label_text(s) for s in siblings[:4]]
            if vals[0]:
                holdings.append(Holding(
                    ticker=ticker,
                    acct=current_acct,
                    qty=int(vals[0]),
                    cost=_to_decimal(vals[1]),
                    price=_to_decimal(vals[2]),
                    pnl=_to_decimal(vals[3]),
                ))
    return holdings


# ---------------------------------------------------------------------------
# CSV loaders
# ---------------------------------------------------------------------------

def load_csv_rows(dirs: Dirs = DEFAULT_DIRS) -> list[dict]:
    """input/seed/*.csv + input/manual/seed.csv + output/history.csv を読み込む"""
    rows = []
    for pattern in [f"{dirs.seed}/*.csv", f"{dirs.manual}/seed.csv", dirs.history_csv]:
        for fname in glob.glob(pattern):
            with open(fname, "r", encoding="utf-8") as f:
                rows.extend(csv.DictReader(f))
    return rows


def aggregate_holdings(rows: list[dict]) -> dict[tuple[str, str], int]:
    """CSV行からティッカー×口座ごとの保有数を集計"""
    holdings: dict[tuple[str, str], int] = {}
    for r in rows:
        key = (r["ticker"], r["acct"])
        holdings[key] = holdings.get(key, 0) + int(r["qty"])
    return {k: v for k, v in holdings.items() if v != 0}



# ---------------------------------------------------------------------------
# Auto-classification
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
# CSV parsers (auto-classified)
# ---------------------------------------------------------------------------

_EXCHANGE_MAP = {
    "NASDAQ": "NASDAQ",
    "NYSE ARCA": "NYSE Arca",
    "New York Stock Exchange": "NYSE",
    "NYSE": "NYSE",
}

_TICKER_RE = re.compile(r"(\S+)\s*/\s*(.+)$")


def _parse_meigara(name: str) -> tuple[str, str, str]:
    """銘柄名 → (ticker, exchange, base_currency)"""
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
    """海外株式約定履歴CSV → Trade + fee Deposit リスト"""
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


def _parse_domestic_fund(filepath: str) -> ParseResult:
    """国内約定履歴CSV → 投信売買を JPY 現金 Deposit に変換。"""
    result = ParseResult()
    skip = _find_header_row(filepath, "約定日,銘柄", encoding="shift_jis")
    df = pd.read_csv(filepath, encoding="shift_jis", skiprows=skip)
    df = df.dropna(subset=["約定日"])

    for _, row in df.iterrows():
        dt_raw = str(row["約定日"]).strip()
        trade_type = str(row["取引"]).strip() if pd.notna(row.get("取引")) else ""
        settle_str = str(row["受渡金額/決済損益"]).strip().replace(",", "")

        try:
            amount = Decimal(settle_str)
        except Exception:
            continue

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


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, callable] = {
    "summary": lambda fp: ParseResult(holdings=parse_summary_html(fp)),
    "history_html": lambda fp: ParseResult(trades=parse_history_html(fp)[0], skipped=parse_history_html(fp)[1]),
    "domestic_fund": lambda fp: _parse_domestic_fund(fp),
    "deposit_transfer": lambda fp: ParseResult(deposits=_parse_sbi_transfer(fp)),
    "deposit_gaika": lambda fp: ParseResult(deposits=_parse_sbi_gaika_nyushukkin(fp)),
    "currency_exchange": lambda fp: ParseResult(deposits=_parse_sbi_exchange(fp)),
}


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def _dedup_deposits(deposits: list[Deposit]) -> tuple[list[Deposit], list[str]]:
    """金額+日付近接(±2日)で重複 Deposit を除去。"""
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
    """input/sbi/ ディレクトリ内の全ファイルを自動分類・パース。"""
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
            {"dt": t.dt, "ticker": t.ticker, "qty": t.qty, "acct": t.acct,
             "price": str(t.price), "avg": str(t.avg), "cur": t.cur, "base": t.base}
            for t in result.trades
        ]
        pd.DataFrame(rows).to_csv(os.path.join(cache_dir, "trades.csv"), index=False, encoding="utf-8")

    if result.holdings:
        rows = [
            {"ticker": h.ticker, "acct": h.acct, "qty": h.qty,
             "cost": str(h.cost), "price": str(h.price), "pnl": str(h.pnl)}
            for h in result.holdings
        ]
        pd.DataFrame(rows).to_csv(os.path.join(cache_dir, "holdings.csv"), index=False, encoding="utf-8")

    if result.deposits:
        rows = [
            {"dt": d.dt, "type": d.type, "amount": str(d.amount),
             "cur": d.cur, "ticker": d.ticker,
             "rate": str(d.rate) if d.rate is not None else ""}
            for d in result.deposits
        ]
        pd.DataFrame(rows).to_csv(os.path.join(cache_dir, "deposits.csv"), index=False, encoding="utf-8")

    if result.warnings:
        with open(os.path.join(cache_dir, "warnings.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(result.warnings))
