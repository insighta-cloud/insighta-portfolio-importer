"""Insighta OpenAPI client."""

import csv
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

import requests
import yaml


log = logging.getLogger(__name__)


def _parse_timestamp(val: str) -> int | None:
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return int(datetime.strptime(val, fmt).replace(tzinfo=timezone.utc).timestamp() * 1000)
        except ValueError:
            continue
    return None


@dataclass
class Credentials:
    api_key: str
    endpoint: str

    @property
    def masked_key(self) -> str:
        if len(self.api_key) <= 8:
            return "****"
        return self.api_key[:4] + "****" + self.api_key[-4:]

    @classmethod
    def from_file(cls, path: str) -> "Credentials":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(api_key=data["api_key"], endpoint=data["endpoint"].rstrip("/"))


@dataclass
class UploadConfig:
    name: str
    description: str
    portfolio_type: str
    currency: str
    budget: Decimal
    balance: Decimal
    order_file: str
    target_return: float = 0.0
    start_date: str = ""
    target_date: str = ""
    items: list = field(default_factory=list)
    cash_deposits_file: str | None = None

    @classmethod
    def from_file(cls, path: str) -> "UploadConfig":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        p = data["portfolio"]
        files = data.get("files", {})
        return cls(
            name=p["name"],
            description=p.get("description", ""),
            portfolio_type=p["type"],
            currency=p["currency"],
            budget=Decimal(str(p["budget"])),
            balance=Decimal(str(p["budget"])),
            target_return=float(p.get("target_return", 0)),
            start_date=p.get("start_date", ""),
            target_date=p.get("target_date", ""),
            items=p.get("items", []),
            order_file=files["order"],
            cash_deposits_file=files.get("cash_deposits"),
        )


@dataclass
class CashDeposit:
    type: str       # budget | dividend
    amount: float
    currency: str | None = None
    ticker: str | None = None
    timestamp: int | None = None


@dataclass
class OrderGroup:
    group_id: str
    currency: str
    items: list = field(default_factory=list)
    cash_deposits: list[CashDeposit] = field(default_factory=list)
    exchange_rate: float | None = None


def load_order_groups(filepath: str) -> list[OrderGroup]:
    """order.csv를 읽어서 order_group별로 묶어 반환 (CSV 출현순 유지)."""
    from collections import OrderedDict
    groups: OrderedDict[str, OrderGroup] = OrderedDict()
    with open(filepath, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gid = row["order_group"]
            rate_val = row.get("rate", "").strip() if row.get("rate") else ""
            if gid not in groups:
                groups[gid] = OrderGroup(
                    group_id=gid,
                    currency=row.get("settle_currency", row["currency"]),
                    exchange_rate=float(rate_val) if rate_val else None,
                )
            groups[gid].items.append({
                "id": row["ticker"],
                "ticker": row["ticker"],
                "quantity": float(row["quantity"]),
                "price": float(row["price"]),
                "currency": row["currency"],
                "price_type": row["price_type"],
                "timestamp": _parse_timestamp(row.get("timestamp", "")),
            })
    return list(groups.values())


def load_cash_deposits(filepath: str) -> dict[str, list[CashDeposit]]:
    """cash_deposits.csv를 읽어서 order_group별로 묶어 반환.

    CSV columns: order_group,type,amount,currency,ticker,timestamp
    """
    groups: dict[str, list[CashDeposit]] = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gid = row["order_group"]
            groups.setdefault(gid, []).append(CashDeposit(
                type=row["type"],
                amount=float(row["amount"]),
                currency=row.get("currency") or None,
                ticker=row.get("ticker") or None,
                timestamp=_parse_timestamp(row.get("timestamp", "")),
            ))
    return groups


def merge_cash_deposits(groups: list[OrderGroup], deposits_by_group: dict[str, list[CashDeposit]]):
    """order group에 cash_deposits를 매핑."""
    for group in groups:
        if group.group_id in deposits_by_group:
            group.cash_deposits = deposits_by_group[group.group_id]


class InsightaClient:
    """Insighta OpenAPI client."""

    def __init__(self, credentials: Credentials):
        self.endpoint = credentials.endpoint
        self.headers = {
            "Authorization": f"Bearer {credentials.api_key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.endpoint}{path}"
        log.debug("%s %s", method, url)
        if "json" in kwargs:
            log.debug("Request body: %s", kwargs["json"])
        resp = requests.request(method, url, headers=self.headers, timeout=30, **kwargs)
        log.debug("Response %s: %s", resp.status_code, resp.text)
        resp.raise_for_status()
        return resp

    def create_portfolio(self, config: UploadConfig) -> str:
        """POST /portfolios → portfolio_id 반환."""
        items = [
            {
                "ticker": str(item["ticker"]),
                "type": str(item.get("type", "stock")),
                "quantity": float(item.get("quantity", 0)),
                "ratio": float(item.get("ratio", 0)),
                "price": float(item.get("price", 0)),
            }
            for item in config.items
        ]
        body = {
            "name": config.name,
            "description": config.description,
            "type": config.portfolio_type,
            "currency": config.currency,
            "budget": float(config.budget),
            "target_return": config.target_return,
            "start_date": config.start_date,
            "target_date": config.target_date,
            "items": items,
        }
        resp = self._request("POST", "/portfolios", json=body)
        return resp.json()["portfolio_id"]

    def send_order(self, portfolio_id: str, order_group: OrderGroup, portfolio_currency: str) -> dict:
        """POST /orders → 주문 그룹 하나 전송."""
        body = {
            "portfolio_id": portfolio_id,
            "currency": portfolio_currency,
            "payment_currency": order_group.currency,
            "items": order_group.items,
        }
        if order_group.currency != portfolio_currency and order_group.exchange_rate:
            body["custom_exchange_rate"] = order_group.exchange_rate
            body["is_custom_exchange_rate"] = True
        if order_group.cash_deposits:
            body["cash_deposits"] = [
                {k: v for k, v in {
                    "type": d.type,
                    "amount": d.amount,
                    "currency": d.currency,
                    "ticker": d.ticker,
                    "timestamp": d.timestamp,
                }.items() if v is not None}
                for d in order_group.cash_deposits
            ]
        resp = self._request("POST", "/orders", json=body)
        return resp.json() if resp.text else {}
