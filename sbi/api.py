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
    def from_config(cls) -> "Credentials":
        from .i18n import load_api_key, load_endpoint
        api_key = load_api_key()
        endpoint = load_endpoint()
        if not api_key or api_key == "your-api-key-here":
            raise ValueError("api_key が config.yaml に設定されていません")
        if not endpoint:
            raise ValueError("endpoint が config.yaml に設定されていません")
        return cls(api_key=api_key, endpoint=endpoint.rstrip("/"))


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
    memo_file: str | None = None
    settings: dict | None = None

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
            memo_file=files.get("memo"),
            settings=p.get("settings"),
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
    memo: str = ""


def load_order_groups(filepath: str) -> list[OrderGroup]:
    """order.csv를 읽어서 (group_dt, settle_currency)별로 묶어 반환."""
    from collections import OrderedDict
    groups: OrderedDict[tuple, OrderGroup] = OrderedDict()
    with open(filepath, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gdt = row["group_dt"]
            settle_cur = row.get("settle_currency", row["currency"])
            rate_val = row.get("rate", "").strip() if row.get("rate") else ""
            key = (gdt, settle_cur)
            if key not in groups:
                groups[key] = OrderGroup(
                    group_id=gdt,
                    currency=settle_cur,
                    exchange_rate=float(rate_val) if rate_val else None,
                )
            groups[key].items.append({
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
    """cash_deposits.csv를 읽어서 group_dt별로 묶어 반환."""
    groups: dict[str, list[CashDeposit]] = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gdt = row["group_dt"]
            groups.setdefault(gdt, []).append(CashDeposit(
                type=row["type"],
                amount=float(row["amount"]),
                currency=row.get("currency") or None,
                ticker=row.get("ticker") or None,
                timestamp=_parse_timestamp(row.get("timestamp", "")),
            ))
    return groups


def merge_and_sort_groups(orders: list[OrderGroup], deposits_by_gdt: dict[str, list[CashDeposit]], memos: dict[str, str]) -> list[OrderGroup]:
    """order + deposit을 group_dt 기준으로 머지하고 시간순 정렬 후 1부터 번호 배정."""
    # 주문 그룹의 group_id → currency 매핑
    existing_curs: dict[str, set[str]] = {}
    for g in orders:
        existing_curs.setdefault(g.group_id, set()).add(g.currency)

    # deposit을 통화별로 분배: 매칭되는 주문 그룹이 없으면 새 그룹 생성
    deps_map = dict(deposits_by_gdt)
    for gdt, deps in deps_map.items():
        by_cur: dict[str, list[CashDeposit]] = {}
        for d in deps:
            c = d.currency or "USD"
            by_cur.setdefault(c, []).append(d)
        for cur, cur_deps in by_cur.items():
            if gdt not in existing_curs or cur not in existing_curs[gdt]:
                g = OrderGroup(group_id=gdt, currency=cur)
                g.cash_deposits = cur_deps
                orders.append(g)
                existing_curs.setdefault(gdt, set()).add(cur)

    # 같은 group_dt + currency의 deposit을 주문 그룹에 붙임
    for g in orders:
        if g.group_id in deps_map and not g.cash_deposits:
            matched = [d for d in deps_map[g.group_id] if (d.currency or g.currency) == g.currency]
            if matched:
                g.cash_deposits = matched
    # group_dt(= 첫 번째 주문 timestamp 또는 deposit timestamp) 기준 정렬
    def _sort_key(g: OrderGroup):
        ts = _parse_timestamp(g.group_id)
        return ts if ts is not None else float("inf")
    orders.sort(key=_sort_key)
    # 순번 배정 후 메모 적용
    for i, g in enumerate(orders, 1):
        g.group_id = str(i)
    for g in orders:
        if g.group_id in memos:
            g.memo = memos[g.group_id]
    return orders


def fetch_ticker_info(tickers: list[str]) -> dict[str, dict]:
    """Insighta /tickers/info API로 sector/industry/type 조회."""
    if not tickers:
        return {}
    resp = requests.get(
        "https://api.insighta.cloud/tickers/info",
        params={"tickers": ",".join(tickers), "conditions": "sector,industry,type"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


class InsightaClient:
    """Insighta OpenAPI client."""

    def __init__(self, credentials: Credentials, output_dir: str = "output"):
        self.endpoint = credentials.endpoint
        self.output_dir = output_dir
        self.headers = {
            "Authorization": f"Bearer {credentials.api_key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        import json as _json
        import os
        url = f"{self.endpoint}{path}"
        payload = kwargs.get("json")
        if payload is not None:
            self._last_payload = payload
            payload_str = _json.dumps(payload, indent=2, ensure_ascii=False)
            log.debug("%s %s\n%s", method, url, payload_str)
            log_path = os.path.join(self.output_dir, "request_payload.log")
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"=== {method} {url} ===\n{payload_str}\n\n")
        else:
            log.debug("%s %s", method, url)
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
                "sector": str(item.get("sector", "N/A")),
                "industry": str(item.get("industry", "N/A")),
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
        if config.settings:
            body["settings"] = config.settings
        resp = self._request("POST", "/portfolios", json=body)
        return resp.json()["portfolio_id"]

    # ── read / search / delete ────────────────────────────────────

    def get_portfolios(self) -> list[dict]:
        """GET /portfolios → return caller's own portfolios."""
        resp = self._request("GET", "/portfolios")
        return resp.json()

    def search_portfolios(
        self,
        search: str | None = None,
        country: str | None = None,
        sort_by: str | None = None,
        last_item: str | None = None,
    ) -> dict:
        """GET /portfolios with search params → search public portfolios."""
        params = {k: v for k, v in {
            "search": search, "country": country,
            "sort_by": sort_by, "last_item": last_item,
        }.items() if v is not None}
        resp = self._request("GET", "/portfolios", params=params)
        return resp.json()

    def delete_portfolio(self, portfolio_id: str) -> None:
        """DELETE /portfolios/{portfolio_id}."""
        self._request("DELETE", f"/portfolios/{portfolio_id}")

    def get_nav_history(self, portfolio_id: str) -> dict:
        """GET /portfolios/{portfolio_id}/nav-history."""
        resp = self._request("GET", f"/portfolios/{portfolio_id}/nav-history")
        return resp.json()

    def get_metrics_history(
        self,
        portfolio_id: str,
        metrics: str = "twr",
        from_t: int | None = None,
        to_t: int | None = None,
    ) -> dict:
        """GET /portfolios/{portfolio_id}/metrics-history."""
        params: dict = {"metrics": metrics}
        if from_t is not None:
            params["from_t"] = str(from_t)
        if to_t is not None:
            params["to_t"] = str(to_t)
        resp = self._request(
            "GET", f"/portfolios/{portfolio_id}/metrics-history",
            params=params)
        return resp.json()

    # ── orders ──────────────────────────────────────────────────

    def send_order(self, portfolio_id: str, order_group: OrderGroup, portfolio_currency: str) -> dict:
        """POST /orders → 주문 그룹 하나 전송."""
        body = {
            "portfolio_id": portfolio_id,
            "currency": portfolio_currency,
            "payment_currency": order_group.currency,
            "items": order_group.items,
        }
        if order_group.memo:
            body["memo"] = order_group.memo
        if order_group.exchange_rate:
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
