"""SBI証券 損益分析"""

from dataclasses import dataclass
from decimal import Decimal
from .parser import Holding, Deposit


@dataclass
class RealizedPnL:
    ticker: str
    acct: str
    sell_qty: int
    avg_buy: Decimal
    avg_sell: Decimal
    pnl_per: Decimal
    total_pnl: Decimal
    pct: Decimal


def calc_realized(rows: list[dict]) -> tuple[list[RealizedPnL], Decimal]:
    """CSV行から実現損益を計算"""
    trades: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["ticker"], r["acct"])
        qty, avg = int(r["qty"]), Decimal(r["avg"])
        trades.setdefault(key, {"buys": [], "sells": []})
        if qty > 0:
            trades[key]["buys"].append((qty, avg))
        else:
            trades[key]["sells"].append((-qty, avg))

    results = []
    total = Decimal("0")
    for (ticker, acct), data in sorted(trades.items()):
        if not data["sells"]:
            continue
        buy_qty = sum(q for q, _ in data["buys"])
        buy_amt = sum(Decimal(q) * p for q, p in data["buys"])
        avg_buy = buy_amt / buy_qty if buy_qty else Decimal("0")

        sell_qty = sum(q for q, _ in data["sells"])
        sell_amt = sum(Decimal(q) * p for q, p in data["sells"])
        avg_sell = sell_amt / sell_qty if sell_qty else Decimal("0")

        pnl_per = avg_sell - avg_buy
        total_pnl = pnl_per * sell_qty
        pct = (pnl_per / avg_buy * 100) if avg_buy else Decimal("0")
        total += total_pnl
        results.append(RealizedPnL(ticker, acct, sell_qty, avg_buy, avg_sell, pnl_per, total_pnl, pct))
    return results, total


def calc_unrealized(holdings: list[Holding]) -> tuple[list[Holding], Decimal]:
    """保有銘柄から未実現損益を計算"""
    total = sum((h.pnl for h in holdings), Decimal("0"))
    return holdings, total


def calc_roi(rows: list[dict], holdings: list[Holding], deposits: list[Deposit] | None = None) -> dict:
    """総合ROIを計算（入金額を含む）"""
    total_buy = sum(
        (Decimal(r["qty"]) * Decimal(r["avg"]) for r in rows if int(r["qty"]) > 0),
        Decimal("0"),
    )
    total_sell = sum(
        (Decimal(str(-int(r["qty"]))) * Decimal(r["avg"]) for r in rows if int(r["qty"]) < 0),
        Decimal("0"),
    )
    total_current = sum((Decimal(h.qty) * h.price for h in holdings), Decimal("0"))

    total_deposit = Decimal("0")
    if deposits:
        for d in deposits:
            if d.cur == "USD":
                total_deposit += d.amount
            elif d.rate:
                total_deposit += d.amount / d.rate

    total_pnl = total_sell + total_current - total_buy
    net_invested = total_buy - total_sell
    roi = (total_pnl / net_invested * 100) if net_invested else Decimal("0")

    return {
        "total_buy": total_buy,
        "total_sell": total_sell,
        "total_current": total_current,
        "net_invested": net_invested,
        "total_deposit": total_deposit,
        "total_pnl": total_pnl,
        "roi": roi,
    }
