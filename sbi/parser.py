"""SBI証券 HTML/CSVパーサー"""

import csv
import glob
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

from dataclasses import dataclass as _dc
import os as _os

WORKSPACES_DIR = "workspaces"


@_dc
class Dirs:
    """作業ディレクトリ設定。--work オプションで切り替え可能。"""
    work: str = ""

    @classmethod
    def from_work(cls, work: str = "") -> "Dirs":
        return cls(work=work)

    @property
    def _base(self) -> str:
        return _os.path.join(WORKSPACES_DIR, self.work) if self.work else ""

    @property
    def input(self) -> str:
        return _os.path.join(self._base, "input") if self._base else "input"

    @property
    def output(self) -> str:
        return _os.path.join(self._base, "output") if self._base else "output"

    @property
    def history(self) -> str:
        return _os.path.join(self.input, "history")

    @property
    def summary(self) -> str:
        return _os.path.join(self.input, "summary")

    @property
    def seed(self) -> str:
        return _os.path.join(self.input, "seed")

    @property
    def deposit(self) -> str:
        return _os.path.join(self.input, "deposit")

    @property
    def exchange(self) -> str:
        return _os.path.join(self.input, "currency_exchange")

    @property
    def rate_csv(self) -> str:
        return _os.path.join(self.input, "rate.csv")

    @property
    def ratio_csv(self) -> str:
        return _os.path.join(self.input, "ratio.csv")

    @property
    def history_csv(self) -> str:
        return _os.path.join(self.output, "history.csv")

    @property
    def order_csv(self) -> str:
        return _os.path.join(self.output, "order.csv")

    @property
    def upload_yaml(self) -> str:
        return _os.path.join(self.output, "upload.yaml")

    @property
    def memo_csv(self) -> str:
        return _os.path.join(self.output, "memo.csv")

    @property
    def cash_deposits_csv(self) -> str:
        return _os.path.join(self.output, "cash_deposits.csv")

    @property
    def request_payload_log(self) -> str:
        return _os.path.join(self.output, "request_payload.log")

    def ensure_output(self):
        """output ディレクトリを作成する。"""
        _os.makedirs(self.output, exist_ok=True)


DEFAULT_DIRS = Dirs()

JST = timezone(timedelta(hours=9))

EXCHANGE_CURRENCY = {
    "NYSE": "USD", "NASDAQ": "USD", "NYSE Arca": "USD", "NYSE American": "USD",
    "KOSPI": "KRW", "KOSDAQ": "KRW",
    "TSE": "JPY",
}


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


def _parse_sbi_transfer(filepath: str) -> list[Deposit]:
    """SBI証券 入出金振替操作履歴CSV (UTF-8) をパース.

    ヘッダー行: 受付日時,受付番号,予定日,区分,摘要,出金指示金額,入金指示金額,状態
    """
    deposits: list[Deposit] = []
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    # データ行のヘッダーを探す
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
    """SBI証券 配当金CSV (Shift_JIS) をパース.

    ヘッダー行: 受渡日,口座,商品,銘柄名,数量,受取額(税引後・円)
    """
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
    # 줄바꿈이 금액 안에 포함된 케이스 처리: 전체를 다시 csv로 파싱
    data_text = "\n".join(lines[header_idx:])
    for row in csv.DictReader(data_text.splitlines()):
        dt_raw = row.get("受渡日", "").strip()
        name = row.get("銘柄名", "").strip()
        amt_str = row.get("受取額(税引後・円)", "").strip().replace("\n", "").replace(",", "")
        if not dt_raw or not amt_str:
            continue
        try:
            amount = Decimal(amt_str)
        except Exception:
            continue
        # 티커: 銘柄名의 마지막 공백 구분 단어
        ticker = name.split()[-1] if name else ""
        deposits.append(Deposit(
            dt=_to_jst_iso(dt_raw), amount=amount, cur="JPY",
            type="dividend", ticker=ticker,
        ))
    return deposits


def _is_sbi_transfer(filepath: str) -> bool:
    """UTF-8の入出金振替操作履歴CSVかどうか判定."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            head = f.read(512)
        return "入出金振替操作履歴" in head or ("受付日時" in head and "状態" in head)
    except Exception:
        return False


def _is_sbi_distribution(filepath: str) -> bool:
    """Shift_JISの配当金CSVかどうか判定."""
    try:
        with open(filepath, "rb") as f:
            raw = f.read(512)
        text = raw.decode("shift_jis", errors="ignore")
        return "受渡日" in text and "銘柄名" in text
    except Exception:
        return False


def _parse_sbi_exchange(filepath: str) -> list[Deposit]:
    """SBI証券 為替取引注文履歴CSV (Shift_JIS) をパース.

    1件の約定 → JPY出金 + USD入金 の2つのDepositに変換する。
    """
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
        if order_type == "買付":  # JPY → 外貨
            deposits.append(Deposit(dt=dt_iso, amount=-jpy_amount, cur="JPY", type="budget", rate=rate))
            deposits.append(Deposit(dt=dt_iso, amount=qty, cur=foreign_cur, type="budget", rate=rate))
        elif order_type == "売付":  # 外貨 → JPY
            deposits.append(Deposit(dt=dt_iso, amount=-qty, cur=foreign_cur, type="budget", rate=rate))
            deposits.append(Deposit(dt=dt_iso, amount=jpy_amount, cur="JPY", type="budget", rate=rate))
    return deposits


def _is_sbi_exchange(filepath: str) -> bool:
    """Shift_JISの為替取引注文履歴CSVかどうか判定."""
    try:
        with open(filepath, "rb") as f:
            raw = f.read(512)
        text = raw.decode("shift_jis", errors="ignore")
        return "為替取引注文履歴" in text or ("口座区分" in text and "約定レート" in text)
    except Exception:
        return False


def load_deposits(dirs: Dirs = DEFAULT_DIRS) -> list[Deposit]:
    """input/deposit/*.csv を自動判別して読み込む.

    対応形式:
      - SBI入出金振替操作履歴 (UTF-8)
      - SBI配当金CSV (Shift_JIS)
    """
    deposits: list[Deposit] = []
    for fname in sorted(glob.glob(f"{dirs.deposit}/*.csv")):
        if _is_sbi_transfer(fname):
            deposits.extend(_parse_sbi_transfer(fname))
        elif _is_sbi_distribution(fname):
            deposits.extend(_parse_sbi_distribution(fname))
    for fname in sorted(glob.glob(f"{dirs.exchange}/*.csv")):
        if _is_sbi_exchange(fname):
            deposits.extend(_parse_sbi_exchange(fname))
    return deposits


def load_csv_rows(dirs: Dirs = DEFAULT_DIRS) -> list[dict]:
    """input/seed/*.csv + output/history.csv を読み込む"""
    rows = []
    for pattern in [f"{dirs.seed}/*.csv", dirs.history_csv]:
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

        # 거래소에서 base 통화 결정
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


def find_htmls(prefix: str, dirs: Dirs = DEFAULT_DIRS) -> list[str]:
    """input/内の指定プレフィックスのHTMLファイルを検索"""
    dir_map = {"history": dirs.history, "summary": dirs.summary}
    d = dir_map.get(prefix, _os.path.join(dirs.input, prefix))
    files = sorted(glob.glob(f"{d}/*.html"))
    if not files:
        raise FileNotFoundError(f"{d}/ に *.html が見つかりません")
    return files


@dataclass
class RateEntry:
    start: str
    end: str
    pair: str
    rate: Decimal


def load_rate_file(filepath: str) -> list[RateEntry]:
    """為替レートCSVを読み込む

    CSV format:
        from,to,pair,rate
        2024/01/01,2024/12/31,USD/JPY,155.50
    """
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
    """'2026/02/19' → '2026/02/19 00:00', そのまま返す場合も"""
    return val if " " in val else f"{val} 00:00"


def _normalize_dt_end(val: str) -> str:
    """'2026/02/19' → '2026/02/19 23:59', そのまま返す場合も"""
    return val if " " in val else f"{val} 23:59"


def lookup_rate(entries: list[RateEntry], dt: str, cur: str, base: str) -> Decimal | None:
    """決済通貨と基準通貨が異なる場合のみ該当期間のレートを返す"""
    if cur == base:
        return None
    # ISO '2026-02-19T21:29:00+09:00' → '2026/02/19 21:29'
    trade_dt = dt[:16].replace("-", "/").replace("T", " ") if dt else ""
    pair = f"{base}/{cur}"
    for e in entries:
        start = _normalize_dt(e.start)
        end = _normalize_dt_end(e.end)
        if e.pair == pair and start <= trade_dt <= end:
            return e.rate
    return None


# --- helpers ---

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
