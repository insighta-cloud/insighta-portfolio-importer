"""insighta-portfolio-importer CLI"""

import glob
import os as _os
import sys

sys.stdout.reconfigure(encoding="utf-8")

import requests
import rich_click as click
from rich.console import Console

console = Console()

click.rich_click.USE_RICH_MARKUP = True
click.rich_click.SHOW_ARGUMENTS = True
click.rich_click.GROUP_ARGUMENTS_OPTIONS = True
click.rich_click.STYLE_COMMANDS_TABLE_COLUMN_WIDTH_RATIO = (1, 2)


@click.group(invoke_without_command=True)
@click.version_option("0.1.0", prog_name="insighta-portfolio-importer")
@click.option("--debug", is_flag=True, help="デバッグモード (APIリクエスト/レスポンスを表示)")
@click.option("--work", default="", help="作業ディレクトリ (例: --work my-portfolio)")
@click.pass_context
def cli(ctx, debug, work):
    """SBI証券のHTMLから保有銘柄・取引履歴をパースし、CSVに変換するツール。"""
    import logging
    from .parser import Dirs
    level = logging.DEBUG if debug else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    ctx.ensure_object(dict)
    ctx.obj["dirs"] = Dirs.from_work(work)
    if ctx.invoked_subcommand is None:
        ctx.invoke(wizard)


@cli.command()
@click.option("--rate", default="", help="固定為替レート (例: 155.12)")
@click.option("--rate-file", default="", help="期間別為替レートCSV (例: input/rate.csv)")
@click.pass_obj
def parse(obj, rate, rate_file):
    """取引履歴HTMLをパースし、CSVを生成する。"""
    import csv
    from rich.table import Table
    from rich.panel import Panel
    from .parser import load_rate_file, lookup_rate

    dirs = obj["dirs"]
    dirs.ensure_output()

    if not rate_file:
        for candidate in [dirs.rate_csv, _os.path.join(dirs.manual, "rate.csv")]:
            if _os.path.exists(candidate):
                rate_file = candidate
                break

    from .parser import process_sbi_dir
    result = process_sbi_dir(dirs.sbi, rate_file=rate_file,
                             cache_dir=_os.path.join(dirs._base or ".", ".cache"))

    rates = load_rate_file(rate_file) if rate_file else []

    # history.csv 出力
    out = dirs.history_csv
    deduped = sorted(result.trades, key=lambda t: t.dt, reverse=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["dt", "ticker", "qty", "acct", "price", "avg", "cur", "base", "rate"])
        for t in deduped:
            r = lookup_rate(rates, t.dt, t.cur, t.base) if rates else (rate if t.cur != t.base else "")
            w.writerow([t.dt, t.ticker, t.qty, t.acct, t.price, t.avg, t.cur, t.base, r or ""])

    # deposits を deposit ディレクトリに保存
    _os.makedirs(dirs.deposit, exist_ok=True)
    dep_out = _os.path.join(dirs.deposit, "_auto_deposits.csv")
    if result.deposits:
        with open(dep_out, "w", newline="", encoding="utf-8") as f:
            f.write("insighta-deposit\n")
            w = csv.writer(f)
            w.writerow(["dt", "type", "amount", "cur", "ticker", "rate"])
            for d in result.deposits:
                w.writerow([d.dt, d.type, d.amount, d.cur, d.ticker, d.rate or ""])

    table = Table(title="パース結果")
    table.add_column("項目")
    table.add_column("件数", justify="right")
    table.add_row("取引", str(len(result.trades)))
    table.add_row("保有銘柄", str(len(result.holdings)))
    table.add_row("入出金", str(len(result.deposits)))
    if result.skipped:
        table.add_row("[yellow]重複除去[/yellow]", str(len(result.skipped)))
    console.print(table)

    for s in result.skipped:
        console.print(f"  [yellow]{s}[/yellow]")
    for w in result.warnings:
        console.print(f"  [yellow]⚠ {w}[/yellow]")

    rate_info = f"rate-file={rate_file}" if rate_file else f"rate={rate or '未指定'}"
    console.print(Panel(f"[bold green]{out}[/bold green] 生成完了  {rate_info}"))


def _run_verify(dirs) -> bool:
    """CSV集計とHTML実際保有を照合する。一致ならTrue、差分ありならFalse。"""
    from decimal import Decimal
    from rich.table import Table
    from rich.panel import Panel
    from .parser import load_csv_rows, aggregate_holdings, process_sbi_dir

    rows = load_csv_rows(dirs)
    holdings = aggregate_holdings(rows)

    rate_file = ""
    for candidate in [dirs.rate_csv, _os.path.join(dirs.manual, "rate.csv")]:
        if _os.path.exists(candidate):
            rate_file = candidate
            break
    _v2_result = process_sbi_dir(dirs.sbi, rate_file=rate_file)

    # CSV集計から移動平均法で取得単価を計算（売却時は平均単価維持、買付時に再計算）
    _avg_price: dict[str, float] = {}
    _hold_qty: dict[str, int] = {}
    sorted_rows = sorted(rows, key=lambda r: r.get("dt", ""))
    for r in sorted_rows:
        t, q, p = r["ticker"], int(r["qty"]), float(r.get("price") or 0)
        if q > 0 and p > 0:
            prev_qty = _hold_qty.get(t, 0)
            prev_avg = _avg_price.get(t, 0.0)
            _avg_price[t] = (prev_avg * prev_qty + p * q) / (prev_qty + q)
            _hold_qty[t] = prev_qty + q
        elif q < 0:
            _hold_qty[t] = _hold_qty.get(t, 0) + q  # reduce qty, keep avg
    csv_avg: dict[str, float] = {t: round(v, 2) for t, v in _avg_price.items() if _hold_qty.get(t, 0) > 0}

    by_acct: dict[str, list[tuple[str, int]]] = {}
    for (ticker, acct), qty in holdings.items():
        by_acct.setdefault(acct, []).append((ticker, qty))
    for acct in by_acct:
        by_acct[acct].sort()

    actual: dict[tuple[str, str], int] = {}
    prices: dict[str, dict] = {}
    for h in _v2_result.holdings:
        actual[(h.ticker, h.acct)] = h.qty
        prices[h.ticker] = {"cost": h.cost, "price": h.price, "pnl": h.pnl}

    for acct in sorted(by_acct):
        icon = "🟢" if acct == "NISA" else "🔵"
        table = Table(title=f"{icon} {acct}")
        table.add_column("Ticker")
        table.add_column("数量", justify="right")
        table.add_column("取得単価", justify="right")
        table.add_column("CSV平均", justify="right")
        table.add_column("現在値", justify="right")
        table.add_column("損益", justify="right")
        table.add_column("検証", justify="center")
        for ticker, qty in by_acct[acct]:
            p = prices.get(ticker, {})
            a_qty = actual.get((ticker, acct))
            check = "[yellow]⚠[/yellow]" if a_qty is None else (
                "[green]✅[/green]" if a_qty == qty else "[red]❌[/red]")
            pnl = p.get("pnl", "-")
            pnl_style = "red" if pnl != "-" and pnl < 0 else "green"
            pnl_str = f"[{pnl_style}]{pnl}[/{pnl_style}]" if pnl != "-" else "-"
            ca = csv_avg.get(ticker)
            ca_str = str(ca) if ca is not None else "-"
            table.add_row(ticker, str(qty), str(p.get("cost", "-")),
                          ca_str, str(p.get("price", "-")), pnl_str, check)
        console.print(table)

    merged: dict[str, int] = {}
    for (ticker, _), qty in holdings.items():
        merged[ticker] = merged.get(ticker, 0) + qty

    table = Table(title="🟡 合算")
    table.add_column("Ticker")
    table.add_column("数量", justify="right")
    table.add_column("取得単価", justify="right")
    table.add_column("CSV平均", justify="right")
    table.add_column("現在値", justify="right")
    for ticker in sorted(merged):
        p = prices.get(ticker, {})
        ca = csv_avg.get(ticker)
        ca_str = str(ca) if ca is not None else "-"
        table.add_row(ticker, str(merged[ticker]), str(p.get("cost", "-")), ca_str, str(p.get("price", "-")))
    console.print(table)

    diffs = []
    for key in set(holdings) | set(actual):
        csv_qty, act_qty = holdings.get(key, 0), actual.get(key, 0)
        if csv_qty != act_qty:
            ticker, acct = key
            diffs.append((acct, ticker, csv_qty, act_qty, act_qty - csv_qty,
                          prices.get(ticker, {}).get("price", "-")))

    if diffs:
        table = Table(title="🔴 差分 (実際 - 集計)")
        table.add_column("口座")
        table.add_column("Ticker")
        table.add_column("集計", justify="right")
        table.add_column("実際", justify="right")
        table.add_column("差分", justify="right")
        table.add_column("現在値", justify="right")
        for acct, ticker, csv_q, act_q, diff, price in sorted(diffs):
            sign = f"+{diff}" if diff > 0 else str(diff)
            table.add_row(acct, ticker, str(csv_q), str(act_q), sign, str(price))
        console.print(table)

    # --- 残高検証: 入金/売買を時系列で追い、通貨別残高がマイナスになる区間を検出 ---
    events: list[tuple[str, str, Decimal, str]] = []  # (dt, label, amount, currency)
    rate_missing: list[tuple[str, str, int, str, str]] = []  # (dt, ticker, qty, cur, base)
    _deposits = _v2_result.deposits
    for d in _deposits:
        events.append((d.dt, f"{d.type} {d.ticker}".strip(), d.amount, d.cur))
    for r in rows:
        dt, ticker = r["dt"], r["ticker"]
        qty, avg = int(r["qty"]), Decimal(r.get("avg", "0") or "0")
        cur = r.get("cur", "USD")
        base = r.get("base", "USD")
        rate = Decimal(r.get("rate", "0") or "0")
        cost = abs(qty) * avg
        if cur != base and rate:
            settle_cost = cost * rate
            settle_cur = cur
        else:
            if cur != base and not rate:
                rate_missing.append((dt[:16], ticker, qty, cur, base))
            settle_cost = cost
            settle_cur = base
        if qty > 0:
            events.append((dt, f"BUY {ticker} x{qty}", -settle_cost, settle_cur))
        elif qty < 0:
            events.append((dt, f"SELL {ticker} x{abs(qty)}", settle_cost, settle_cur))

    if rate_missing:
        table = Table(title="⚠ 為替レート未設定")
        table.add_column("日時")
        table.add_column("Ticker")
        table.add_column("数量", justify="right")
        table.add_column("決済")
        table.add_column("基準")
        for dt, ticker, qty, cur, base in rate_missing:
            table.add_row(dt, ticker, str(qty), cur, base)
        console.print(table)
        console.print("[yellow]rate.csv の期間設定を確認してください。残高計算が不正確になります。[/yellow]")
    def _sort_dt(dt: str) -> str:
        d = dt.replace("/", "-").replace("T", " ")
        parts = d.split(" ")[0].split("-")
        return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}" + d[len(d.split(' ')[0]):]
    events.sort(key=lambda e: _sort_dt(e[0]))

    balances: dict[str, Decimal] = {}
    shortfalls: list[tuple[str, str, str, Decimal]] = []  # (dt, label, currency, balance)
    for dt, label, amount, cur in events:
        balances[cur] = balances.get(cur, Decimal("0")) + amount
        if balances[cur] < 0 and amount < 0:
            shortfalls.append((dt, label, cur, balances[cur]))

    if shortfalls:
        table = Table(title="🟠 残高不足区間")
        table.add_column("日時")
        table.add_column("イベント")
        table.add_column("通貨")
        table.add_column("残高", justify="right")
        for dt, label, cur, bal in shortfalls:
            table.add_row(dt[:16], label, cur, f"[red]{bal:,.2f}[/red]")
        console.print(table)
        console.print("[yellow]入金データ (input/deposit/) が不足している可能性があります。[/yellow]")

    # --- 通貨別最終残高 ---
    if balances:
        table = Table(title="💰 通貨別残高", show_header=False, box=None, padding=(0, 2))
        table.add_column(style="bold")
        table.add_column(justify="right")
        for cur in sorted(balances):
            bal = balances[cur]
            style = "red" if bal < 0 else "green"
            table.add_row(cur, f"[{style}]{bal:,.2f}[/{style}]")
        console.print(table)

    if diffs:
        return False
    if not diffs:
        console.print(Panel("[bold green]✅ 集計と実際保有が完全一致[/bold green]"))
    return True


def _load_memo_file(path: str) -> dict[str, str]:
    """memo CSV (order_group,memo) を読み込んでdictで返す。"""
    import csv
    memos: dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            memos[row["order_group"]] = row.get("memo", "")
    return memos


@cli.command()
@click.pass_obj
def verify(obj):
    """CSV集計とHTML実際保有を照合する。"""
    _run_verify(obj["dirs"])


@cli.command()
@click.option("--locale", default="", hidden=True)
@click.option("--history-file", default="", hidden=True)
@click.option("--seed-file", default="", hidden=True)
@click.option("--rate-file", default="", hidden=True)
@click.option("--non-interactive", "-ni", is_flag=True, hidden=True)
@click.option("--name", "p_name", default="", hidden=True)
@click.option("--description", "p_desc", default="", hidden=True)
@click.option("--currency", "p_currency", default="", hidden=True)
@click.option("--budget", "p_budget", type=float, default=None, hidden=True)
@click.option("--target-return", "p_target_return", type=float, default=None, hidden=True)
@click.option("--start-date", "p_start_date", default="", hidden=True)
@click.option("--target-date", "p_target_date", default="", hidden=True)
@click.pass_obj
def prepare(obj, locale, history_file, seed_file, rate_file, non_interactive,
           p_name, p_desc, p_currency, p_budget, p_target_return, p_start_date, p_target_date):
    """対話式でupload.yaml + order.csvを生成する。"""
    import csv
    import yaml
    from datetime import datetime
    from rich.table import Table
    from rich.panel import Panel
    from .parser import load_rate_file, lookup_rate, process_sbi_dir
    from .i18n import load_locale, msg
    from datetime import timezone, timedelta
    dirs = obj["dirs"]
    dirs.ensure_output()
    if not locale:
        locale = load_locale() or "ja"
    m = msg(locale)
    tz = timezone(timedelta(hours=m["tz_offset"]))
    ni = non_interactive

    # Load project.yaml defaults (CLI options override)
    proj: dict = {}
    if _os.path.exists(dirs.project_yaml):
        with open(dirs.project_yaml, 'r', encoding='utf-8') as f:
            proj = yaml.safe_load(f) or {}
    if not p_name:
        p_name = proj.get('name', '')
    if not p_desc:
        p_desc = proj.get('description', '')
    if not p_currency:
        p_currency = proj.get('currency', '')
    if p_budget is None and proj.get('budget') is not None:
        p_budget = float(proj['budget'])
    if p_target_return is None and proj.get('target_return') is not None:
        p_target_return = float(proj['target_return'])
    if not p_start_date:
        p_start_date = str(proj.get('start_date', '') or '')
    if not p_target_date:
        p_target_date = str(proj.get('target_date', '') or '')

    def _prompt(label, default="", **kw):
        if ni:
            return default
        return click.prompt(label, default=default, **kw)

    def _confirm(label, default=True):
        if ni:
            return default
        return click.confirm(label, default=default)

    today = datetime.now().strftime("%Y-%m-%d")

    # v2 deposits
    _rate_file = ""
    for candidate in [dirs.rate_csv, _os.path.join(dirs.manual, "rate.csv")]:
        if _os.path.exists(candidate):
            _rate_file = candidate
            break
    _v2_deposits = process_sbi_dir(dirs.sbi, rate_file=_rate_file).deposits

    # Determine earliest date from orders + deposits
    def _earliest_date() -> str:
        import csv as _csv, re as _re
        dates = []
        for fpath in [history_file or dirs.history_csv, seed_file or f"{dirs.seed}/seed.csv"]:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    for row in _csv.DictReader(f):
                        dt = row.get("dt", "")[:10].replace("/", "-")
                        if _re.match(r"\d{4}-\d{2}-\d{2}", dt):
                            dates.append(dt)
            except FileNotFoundError:
                pass
        for d in _v2_deposits:
            dt = d.dt[:10]
            if _re.match(r"\d{4}-\d{2}-\d{2}", dt):
                dates.append(dt)
        return min(dates) if dates else today

    start_date_default = _earliest_date()
    target_date_default = datetime(
        int(start_date_default[:4]) + 10,
        int(start_date_default[5:7]),
        int(start_date_default[8:10]),
    ).strftime("%Y-%m-%d")

    name = p_name or _prompt(m["prepare_name"], default="My Portfolio")
    description = p_desc or _prompt(m["prepare_desc"], default="Imported from brokerage trade history.")
    currency = p_currency or _prompt(m["prepare_currency"], type=click.Choice(["USD", "KRW", "JPY"]), default=m["default_currency"])
    budget = p_budget if p_budget is not None else _prompt(m["prepare_budget"], type=float, default=10000.0)
    target_return = p_target_return if p_target_return is not None else _prompt(m["prepare_target_return"], type=float, default=10)
    start_date = p_start_date or _prompt(m["prepare_start_date"], default=start_date_default)
    target_date = p_target_date or _prompt(m["prepare_target_date"], default=target_date_default)

    if not history_file:
        history_file = _prompt(m["prepare_history"], default=dirs.history_csv)
    if not seed_file:
        for candidate in [f"{dirs.seed}/seed.csv", _os.path.join(dirs.manual, "seed.csv")]:
            if _os.path.exists(candidate):
                seed_file = candidate
                break
        if not seed_file:
            seed_file = _prompt(m["prepare_seed"], default=f"{dirs.seed}/seed.csv")
    if not rate_file:
        rate_file = _rate_file or _prompt(m["prepare_rate"], default=dirs.rate_csv)

    do_group = _confirm(m["prepare_group"], default=True)
    if do_group:
        console.print(m["prepare_group_note"])

    # --- Load rows ---
    rows = []
    for fpath in [seed_file, history_file]:
        if not fpath:
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                rows.extend(csv.DictReader(f))
        except FileNotFoundError:
            console.print(f"[yellow]Warning: {fpath} not found, skipping.[/yellow]")

    if not rows:
        console.print("[red]No trade data found. Aborting.[/red]")
        return

    rates = load_rate_file(rate_file) if rate_file else []

    # --- Build order rows ---
    def _date_key(dt_raw: str) -> str:
        d = dt_raw[:10].replace("-", "/") if dt_raw else "unknown"
        parts = d.split("/")
        if len(parts) == 3:
            return f"{parts[0]}/{parts[1].zfill(2)}/{parts[2].zfill(2)}"
        return d

    order_rows = []
    for r in rows:
        dt_raw = r.get("dt", "")
        ticker = r["ticker"]
        qty = int(r["qty"])
        avg = r.get("avg", "0")
        cur = r.get("cur", currency)
        base = r.get("base", "USD")
        rate_val = r.get("rate", "")

        # rate가 비어있으면 rate 파일에서 조회
        if not rate_val and rates:
            looked = lookup_rate(rates, dt_raw, cur, base)
            rate_val = str(looked) if looked else ""

        # timestamp (UTC string: '%Y-%m-%d %H:%M:%S')
        ts = ""
        if dt_raw:
            import re
            if re.match(r"\d{4}-\d{2}-\d{2}T", dt_raw):
                dt_obj = datetime.fromisoformat(dt_raw)
                if dt_obj.tzinfo is None:
                    dt_obj = dt_obj.replace(tzinfo=tz)
            elif re.match(r"\d{4}/\d+/\d+ \d+:\d+", dt_raw):
                dt_obj = datetime.strptime(dt_raw, "%Y/%m/%d %H:%M").replace(tzinfo=tz)
            elif re.match(r"\d{4}/\d+/\d+$", dt_raw):
                dt_obj = datetime.strptime(dt_raw, "%Y/%m/%d").replace(tzinfo=tz)
            else:
                dt_obj = None
            if dt_obj:
                ts = dt_obj.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        date_key = _date_key(dt_raw)

        order_rows.append({
            "date_key": date_key,
            "ticker": ticker,
            "quantity": str(qty),
            "price": avg,
            "currency": base,
            "settle_currency": cur,
            "rate": rate_val,
            "price_type": "LIMIT",
            "timestamp": ts,
        })

    # --- Assign group_dt (대표 UTC timestamp) ---
    # group_dt = 그룹 내 첫 번째 주문의 timestamp (UTC, YYYY-MM-DD HH:MM:SS)
    if do_group:
        group_dt_map: dict[tuple, str] = {}  # (date_key, settle_currency) -> group_dt
        for row in order_rows:
            key = (row["date_key"], row["settle_currency"])
            if key not in group_dt_map:
                group_dt_map[key] = row["timestamp"] or row["date_key"] + " 00:00:00"
            row["group_dt"] = group_dt_map[key]
    else:
        for row in order_rows:
            row["group_dt"] = row["timestamp"] or row["date_key"] + " 00:00:00"

    # --- Split group when same ticker has different prices ---
    from collections import defaultdict
    _seen: dict[str, dict[str, str]] = defaultdict(dict)  # group_dt -> {ticker: price}
    for row in order_rows:
        gdt = row["group_dt"]
        t, p = row["ticker"], row["price"]
        if t in _seen[gdt] and _seen[gdt][t] != p:
            # bump group_dt by 1 second to create a new group
            dt_obj = datetime.strptime(gdt, "%Y-%m-%d %H:%M:%S") + timedelta(seconds=1)
            new_gdt = dt_obj.strftime("%Y-%m-%d %H:%M:%S")
            row["group_dt"] = new_gdt
            _seen[new_gdt][t] = p
        else:
            _seen[gdt][t] = p

    # --- Merge same ticker+price within group ---
    merged_rows: dict[tuple, dict] = {}
    for row in order_rows:
        key = (row["group_dt"], row["ticker"], row["price"])
        if key in merged_rows:
            merged_rows[key]["quantity"] = str(int(merged_rows[key]["quantity"]) + int(row["quantity"]))
        else:
            merged_rows[key] = dict(row)
    order_rows = sorted(merged_rows.values(), key=lambda r: r["timestamp"] or "")

    # --- Write order.csv ---
    order_out = dirs.order_csv
    with open(order_out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group_dt", "ticker", "quantity", "price", "currency", "settle_currency", "rate", "price_type", "timestamp"])
        for row in order_rows:
            w.writerow([
                row["group_dt"], row["ticker"], row["quantity"],
                row["price"], row["currency"], row["settle_currency"], row["rate"], row["price_type"], row["timestamp"],
            ])

    # --- Write cash_deposits.csv ---
    deposits = _v2_deposits
    cash_deposits_out = ""
    if deposits:
        import re as _re

        def _parse_deposit_dt(d):
            try:
                if _re.match(r"\d{4}-\d{2}-\d{2}T", d.dt):
                    dt_obj = datetime.fromisoformat(d.dt)
                    if dt_obj.tzinfo is None:
                        dt_obj = dt_obj.replace(tzinfo=tz)
                    return dt_obj
                elif _re.match(r"\d{4}/\d+/\d+ \d+:\d+", d.dt):
                    return datetime.strptime(d.dt, "%Y/%m/%d %H:%M").replace(tzinfo=tz)
                else:
                    return datetime.strptime(d.dt[:10], "%Y/%m/%d").replace(tzinfo=tz)
            except (ValueError, AttributeError):
                return datetime.max.replace(tzinfo=tz)

        deposits.sort(key=_parse_deposit_dt)
        cash_deposits_out = dirs.cash_deposits_csv
        with open(cash_deposits_out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["group_dt", "type", "amount", "currency", "ticker", "timestamp"])
            for d in deposits:
                dt_obj = _parse_deposit_dt(d)
                ts = dt_obj.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if dt_obj.year < 9999 else ""
                w.writerow([ts, d.type, float(d.amount), d.cur, d.ticker, ts])

    # --- Build portfolio items ---
    from .api import fetch_ticker_info
    ticker_qty: dict[str, int] = {}
    for r in rows:
        t = r["ticker"]
        ticker_qty[t] = ticker_qty.get(t, 0) + int(r["qty"])
    active_tickers = sorted(t for t, q in ticker_qty.items() if q > 0)

    # Load ratio: project.yaml > ratio.csv > equal distribution
    ratios: dict[str, float] = {}
    if proj.get("ratio") and isinstance(proj["ratio"], dict):
        ratios = {k: float(v) for k, v in proj["ratio"].items()}
    else:
        try:
            with open(dirs.ratio_csv, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    ratios[row["ticker"]] = float(row["ratio"])
        except FileNotFoundError:
            equal = round(1.0 / len(active_tickers), 4) if active_tickers else 0
            ratios = {t: equal for t in active_tickers}

    try:
        ticker_info = fetch_ticker_info(active_tickers)
    except Exception:
        ticker_info = {}
    portfolio_items = [
        {
            "ticker": t,
            "type": ticker_info.get(t, {}).get("type", "stock"),
            "quantity": ticker_qty[t],
            "ratio": ratios[t],
            "price": 0,
            "sector": ticker_info.get(t, {}).get("sector", "N/A"),
            "industry": ticker_info.get(t, {}).get("industry", "N/A"),
        }
        for t in active_tickers
    ]

    # --- Write upload.yaml ---
    memo_out = dirs.memo_csv
    files_config = {"order": order_out, "memo": memo_out}
    if cash_deposits_out:
        files_config["cash_deposits"] = cash_deposits_out
    upload_config = {
        "portfolio": {
            "name": name,
            "description": description,
            "type": "record",
            "currency": currency,
            "budget": budget,
            "target_return": target_return,
            "start_date": start_date,
            "target_date": target_date,
            "items": portfolio_items,
        },
        "files": files_config,
    }
    yaml_out = dirs.upload_yaml
    with open(yaml_out, "w", encoding="utf-8") as f:
        yaml.dump(upload_config, f, allow_unicode=True, default_flow_style=False)

    # --- Summary ---
    table = Table(title=m["prepare_result"])
    table.add_column("")
    table.add_column("", justify="right")
    table.add_row(m["prepare_trades"], str(len(order_rows)))
    if deposits:
        budget_count = sum(1 for d in deposits if d.type == "budget")
        dividend_count = sum(1 for d in deposits if d.type == "dividend")
        if budget_count:
            table.add_row(m["prepare_budget_count"], str(budget_count))
        if dividend_count:
            table.add_row(m["prepare_dividend_count"], str(dividend_count))
    group_count = len(set(r["group_dt"] for r in order_rows))
    table.add_row(m["prepare_groups"], str(group_count))
    table.add_row(m["prepare_grouping"], m["prepare_grouping_date"] if do_group else m["prepare_grouping_individual"])
    console.print(table)

    # --- Group preview ---
    from .api import load_order_groups, load_cash_deposits, merge_and_sort_groups
    preview_orders = load_order_groups(order_out)
    preview_deposits = {}
    if cash_deposits_out:
        try:
            preview_deposits = load_cash_deposits(cash_deposits_out)
        except FileNotFoundError:
            pass
    preview_groups = merge_and_sort_groups(preview_orders, preview_deposits, {})
    total_groups = len(preview_groups)
    group_memos: dict[str, str] = {}
    for g in preview_groups:
        console.rule()
        preview = Table(title=f"Group {g.group_id}/{total_groups}  ({g.currency})", show_lines=False)
        preview.add_column("Ticker")
        preview.add_column("Qty", justify="right")
        preview.add_column("Price", justify="right")
        for item in g.items:
            qty = item["quantity"]
            qty_str = f"[green]{qty:+g}[/green]" if qty > 0 else f"[red]{qty:g}[/red]"
            preview.add_row(item["ticker"], qty_str, f"{item['price']:.2f}")
        if g.cash_deposits:
            for d in g.cash_deposits:
                label = f"[dim]{d.type}[/dim]"
                ticker = d.ticker or ""
                preview.add_row(ticker or label, f"[cyan]{d.amount:+,.2f}[/cyan]", d.currency or "")
        console.print(preview)
        memo = _prompt(m["prepare_memo_prompt"], default="")
        if memo:
            group_memos[g.group_id] = memo

    # --- Write memo.csv (group_id = 순번, merge_and_sort_groups 기준) ---
    memo_out = dirs.memo_csv
    with open(memo_out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["order_group", "memo"])
        for gid, memo in group_memos.items():
            w.writerow([gid, memo])

    console.print(Panel(f"[bold green]{m['prepare_done'].format(order=order_out, yaml=yaml_out)}[/bold green]"))

    # --- Dump request payloads to log ---
    import json as _json
    log_path = dirs.request_payload_log
    with open(log_path, "w", encoding="utf-8") as lf:
        # portfolio creation
        portfolio_body = {
            "name": name,
            "description": description,
            "type": "record",
            "currency": currency,
            "budget": budget,
            "target_return": target_return,
            "start_date": start_date,
            "target_date": target_date,
            "items": portfolio_items,
        }
        lf.write("=== POST /portfolios ===\n")
        lf.write(_json.dumps(portfolio_body, indent=2, ensure_ascii=False))
        lf.write("\n\n")
        # order groups
        for g in preview_groups:
            body = {
                "portfolio_id": "<portfolio_id>",
                "currency": currency,
                "payment_currency": g.currency,
                "items": g.items,
            }
            if g.memo:
                body["memo"] = g.memo
            if g.cash_deposits:
                body["cash_deposits"] = [
                    {k: v for k, v in {
                        "type": d.type,
                        "amount": d.amount,
                        "currency": d.currency,
                        "ticker": d.ticker,
                        "timestamp": d.timestamp,
                    }.items() if v is not None}
                    for d in g.cash_deposits
                ]
            lf.write(f"=== POST /orders  Group {g.group_id} ===\n")
            lf.write(_json.dumps(body, indent=2, ensure_ascii=False))
            lf.write("\n\n")
    console.print(f"[dim]{log_path} にリクエストペイロードを出力しました。[/dim]")


@cli.command()
@click.option("--config", required=True, help="Path to upload.yaml (default: output/upload.yaml)")
@click.option("--yes", "-y", is_flag=True, help="確認プロンプトをスキップ")
@click.option("--lang", default="ja", hidden=True)
@click.option("--memo-file", default="", help="グループ別メモCSV (order_group,memo)")
@click.option("--output-json", is_flag=True, help="結果をJSONで出力")
@click.pass_obj
def upload(obj, config, yes, lang, memo_file, output_json):
    """アップロード: upload.yaml + order.csvをInsighta APIに送信する。"""
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress
    from .api import Credentials, UploadConfig, InsightaClient, load_order_groups, load_cash_deposits, merge_and_sort_groups

    dirs = obj["dirs"]
    dirs.ensure_output()

    creds = Credentials.from_config()
    upload_cfg = UploadConfig.from_file(config)
    client = InsightaClient(creds, output_dir=dirs.output)

    memo_path = memo_file or upload_cfg.memo_file
    memos = {}
    if memo_path:
        try:
            memos = _load_memo_file(memo_path)
            console.print(f"[dim]Memos loaded from {memo_path}: {len(memos)} groups[/dim]")
        except FileNotFoundError:
            console.print(f"[yellow]Warning: {memo_path} not found, skipping memos.[/yellow]")

    orders = load_order_groups(upload_cfg.order_file)
    if not orders:
        console.print("[red]注文データが見つかりません。[/red]")
        return

    # 실제 전송 로그 초기화
    with open(dirs.request_payload_log, "w", encoding="utf-8") as _lf:
        pass

    deposits = {}
    if upload_cfg.cash_deposits_file:
        try:
            deposits = load_cash_deposits(upload_cfg.cash_deposits_file)
            deposit_count = sum(len(v) for v in deposits.values())
            console.print(f"[dim]Cash deposits loaded: {deposit_count} entries[/dim]")
        except FileNotFoundError:
            console.print(f"[yellow]Warning: {upload_cfg.cash_deposits_file} not found, skipping.[/yellow]")

    groups = merge_and_sort_groups(orders, deposits, memos)

    order_groups = [g for g in groups if g.items]
    total_items = sum(len(g.items) for g in order_groups)
    total_deposits = sum(len(g.cash_deposits) for g in groups)

    # --- 전송 전 최종 확인 ---
    info = Table(title="アップロード内容", show_header=False, box=None, padding=(0, 2))
    info.add_column(style="bold")
    info.add_column()
    info.add_row("ポートフォリオ", upload_cfg.name)
    info.add_row("説明", upload_cfg.description or "-")
    info.add_row("タイプ", upload_cfg.portfolio_type)
    info.add_row("通貨", upload_cfg.currency)
    info.add_row("初期予算", f"{float(upload_cfg.budget):,.2f}")
    info.add_row("注文グループ", f"{total_items} 件")
    if total_deposits:
        info.add_row("入金 / 配当", f"{total_deposits} 件")
    info.add_row("送信グループ", f"{len(groups)} 件")
    info.add_row("API Key", f"[dim]{creds.masked_key}[/dim]")
    info.add_row("送信先", f"[dim]{creds.endpoint}[/dim]")
    console.print(Panel(info))

    if not yes and not click.confirm("アップロードを実行しますか？"):
        console.print("[yellow]中断しました。[/yellow]")
        return

    # ポートフォリオ作成
    try:
        console.print("ポートフォリオ作成中...", end=" ")
        portfolio_id = client.create_portfolio(upload_cfg)
        console.print(f"[green]✅ {portfolio_id}[/green]")
    except requests.exceptions.HTTPError as e:
        detail = ""
        if e.response is not None:
            try:
                detail = e.response.json().get("message", e.response.text)
            except Exception:
                detail = e.response.text
        console.print(f"[red]❌ 失敗: {e}[/red]")
        if detail:
            console.print(f"[red]   {detail}[/red]")
        raise SystemExit(1)
    except Exception as e:
        console.print(f"[red]❌ 失敗: {e}[/red]")
        raise SystemExit(1)

    # 注文送信
    import time
    success, failed = 0, 0
    total = len(groups)
    with Progress(console=console) as progress:
        task = progress.add_task(f"注文送信中... 0/{total}", total=total)
        for i, group in enumerate(groups, 1):
            try:
                client.send_order(portfolio_id, group, upload_cfg.currency)
                success += 1
                progress.console.print(f"[dim]✓ Group {i}/{total}[/dim]")
            except requests.exceptions.HTTPError as e:
                progress.stop()
                console.print(f"[red]Group {group.group_id} failed: {e}[/red]")
                if e.response is not None:
                    try:
                        detail = e.response.json().get("message", e.response.text)
                    except Exception:
                        detail = e.response.text
                    console.print(f"[red]   {detail}[/red]")
                import json as _json
                console.print(f"[dim]Payload: {_json.dumps(client._last_payload, ensure_ascii=False, indent=2)}[/dim]")
                failed += 1
                break
            except Exception as e:
                progress.stop()
                console.print(f"[red]Group {group.group_id} failed: {e}[/red]")
                failed += 1
                break
            progress.advance(task)
            progress.update(task, description=f"注文送信中... {i}/{total}")
            if group != groups[-1]:
                time.sleep(1)

    # 結果
    table = Table(title="アップロード結果")
    table.add_column("項目")
    table.add_column("値", justify="right")
    table.add_row("Portfolio ID", portfolio_id)
    table.add_row("[green]成功[/green]", str(success))
    if failed:
        table.add_row("[red]失敗[/red]", str(failed))
    console.print(table)
    if not failed:
        url = f"https://insighta.cloud/{lang}/portfolio/{portfolio_id}"
        console.print(f"\n  🔗 {url}")
    if output_json:
        import json as _json
        result = {
            "status": "error" if failed else "success",
            "portfolio_id": portfolio_id,
            "url": f"https://insighta.cloud/{lang}/portfolio/{portfolio_id}",
            "success": success,
            "failed": failed,
        }
        click.echo(_json.dumps(result, ensure_ascii=False))
    if failed:
        raise SystemExit(1)


@cli.command()
@click.option("--non-interactive", "-ni", is_flag=True, help="対話プロンプトをスキップしてデフォルト値で実行")
@click.option("--name", "p_name", default="", help="ポートフォリオ名")
@click.option("--description", "p_desc", default="", help="説明")
@click.option("--currency", "p_currency", default="", help="通貨 (USD/JPY/KRW)")
@click.option("--budget", "p_budget", type=float, default=None, help="初期予算")
@click.option("--target-return", "p_target_return", type=float, default=None, help="目標リターン (%)")
@click.option("--start-date", "p_start_date", default="", help="開始日 (YYYY-MM-DD)")
@click.option("--target-date", "p_target_date", default="", help="目標日 (YYYY-MM-DD)")
@click.option("--output-json", is_flag=True, help="結果をJSONで出力")
@click.pass_obj
def wizard(obj, non_interactive, p_name, p_desc, p_currency, p_budget, p_target_return,
          p_start_date, p_target_date, output_json):
    """対話式ウィザードで全ステップを順番に実行する。"""
    import os
    from rich.panel import Panel
    from rich.table import Table
    from .i18n import load_locale, save_locale, msg
    dirs = obj["dirs"]
    ni = non_interactive

    def _confirm(label, default=True):
        if ni:
            return default
        return click.confirm(label, default=default)

    def _prompt(label, default="", **kw):
        if ni:
            return default
        return click.prompt(label, default=default, **kw)

    # --- 言語選択 (オンボーディング) ---
    locale = load_locale()
    if not locale:
        if ni:
            locale = "ja"
        else:
            console.print(Panel(
                "[bold]insighta portfolio importer[/bold]\n"
                "\n"
                "  🇯🇵  日本語 (SBI証券)\n"
                "  🇰🇷  한국어 (미래에셋증권)",
                title="🌏 Language", border_style="cyan",
            ))
            locale = click.prompt(
                "",
                type=click.Choice(["ja", "ko"]),
                default="ja",
                show_choices=True,
                prompt_suffix="",
            )
        save_locale(locale)

    m = msg(locale)

    # --- オーバービュー ---
    console.print(Panel(
        m["onboarding_welcome"],
        title="🚀 Wizard", border_style="cyan",
    ))

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_column(style="dim")
    for num, name, desc in m["steps"]:
        table.add_row(f"Step {num}", name, desc)
    console.print(table)

    if not ni:
        click.prompt(m["press_enter"], default="", show_default=False, prompt_suffix="")

    # --- Check for previous results ---
    history_csv_exists = os.path.exists(dirs.history_csv)
    prepare_exists = os.path.exists(dirs.upload_yaml) and os.path.exists(dirs.order_csv)

    skip_parse = False
    skip_prepare = False
    rate_file = ""

    if prepare_exists and _confirm(m["resume_prepare"], default=True):
        skip_parse = True
        skip_prepare = True
        console.print(m["resume_reuse"])
    elif history_csv_exists and _confirm(m["resume_history"], default=True):
        skip_parse = True
        console.print(m["resume_reuse"])

    seed_files = glob.glob(f"{dirs.seed}/*.csv")
    rate_exists = os.path.exists(dirs.rate_csv)
    if rate_exists:
        rate_file = dirs.rate_csv

    if not skip_parse:
        while True:
            # === Step 1 ===
            console.print(Panel(f"[bold cyan]{m['step1_title']}[/bold cyan]", border_style="cyan"))
            if not ni:
                console.print(m["step1_guide"])

            if not _confirm(m["step1_confirm"], default=True):
                return

            # === Step 2 ===
            console.print(Panel(f"[bold cyan]{m['step2_title']}[/bold cyan]", border_style="cyan"))

            sbi_files = glob.glob(os.path.join(dirs.sbi, "*"))
            sbi_ok = bool(sbi_files)
            summary_ok = any(f.endswith(".html") for f in sbi_files)

            if not ni:
                status = Table(show_header=False, box=None, padding=(0, 1), title=m["file_detection"])
                status.add_column()
                status.add_column()
                status.add_row(
                    "[green]✅[/green]" if sbi_ok else "[red]❌[/red]",
                    f"input/sbi/ ファイル: {len(sbi_files)} 件" if sbi_ok else "input/sbi/ にファイルがありません",
                )
                if seed_files:
                    status.add_row("[green]✅[/green]", m["seed_found"].format(n=len(seed_files)))
                if rate_exists:
                    status.add_row("[green]✅[/green]", m["rate_found"])
                console.print(status)

            if not sbi_ok:
                if ni:
                    console.print("[red]No files found in input/sbi/. Aborting.[/red]")
                    raise SystemExit(1)
                console.print(f"\ninput/sbi/ にファイルを配置してください。")
                console.print(m["back_to_step1"])
                continue

            console.print()
            rate = ""
            if rate_exists:
                console.print(m["rate_file_auto"])

            ctx = click.get_current_context()
            ctx.invoke(parse, rate=rate, rate_file=rate_file)

            if summary_ok:
                if _confirm(m["verify_confirm"], default=True):
                    console.print()
                    verified = _run_verify(dirs)
                    if not verified:
                        console.print(m["verify_diff_warn"])
                        if ni:
                            console.print("[yellow]Non-interactive: continuing despite diff.[/yellow]")
                        else:
                            choice = click.prompt(
                                m["verify_choice"],
                                type=click.Choice(["back", "continue", "quit"]),
                                default="back",
                                show_choices=True,
                            )
                            if choice == "back":
                                console.print(m["back_to_step1_fix"])
                                continue
                            elif choice == "quit":
                                return
            else:
                console.print(m["summary_skip"])

            break

    if not skip_prepare:
        if not _confirm(m["step3_confirm"], default=True):
            return

        # === Step 3 ===
        console.print(Panel(f"[bold cyan]{m['step3_title']}[/bold cyan]", border_style="cyan"))
        seed_file = seed_files[0] if seed_files else ""
        ctx = click.get_current_context()
        ctx.invoke(prepare, locale=locale, history_file=dirs.history_csv, seed_file=seed_file, rate_file=rate_file,
                   non_interactive=ni, p_name=p_name, p_desc=p_desc, p_currency=p_currency,
                   p_budget=p_budget, p_target_return=p_target_return,
                   p_start_date=p_start_date, p_target_date=p_target_date)

        if not os.path.exists(dirs.upload_yaml) or not os.path.exists(dirs.order_csv):
            return

    if not _confirm(m["step4_confirm"], default=True):
        return

    # === Step 4 ===
    console.print(Panel(f"[bold cyan]{m['step4_title']}[/bold cyan]", border_style="cyan"))

    from .i18n import load_api_key, load_endpoint
    if not load_api_key() or load_api_key() == "your-api-key-here":
        console.print(m["cred_missing"].format(path="config.yaml"))
        if output_json:
            import json as _json
            click.echo(_json.dumps({"status": "error", "message": "config.yaml not configured"}, ensure_ascii=False))
        return

    from .api import Credentials
    creds = Credentials.from_config()
    console.print(f"  API Key:  [dim]{creds.masked_key}[/dim]")
    console.print(f"  Endpoint: [dim]{creds.endpoint}[/dim]")
    if not _confirm(m["cred_confirm"], default=True):
        return

    ctx = click.get_current_context()
    ctx.invoke(upload, config=dirs.upload_yaml, yes=True, lang=locale, memo_file="", output_json=output_json)
    console.print(Panel(m["all_done"], border_style="green"))


@cli.command()
@click.pass_obj
def analyze(obj):
    """実現/未実現損益と総合ROIを分析する。"""
    from rich.table import Table
    from rich.panel import Panel
    from .parser import load_csv_rows
    from .parser import process_sbi_dir
    from .analyzer import calc_realized, calc_unrealized, calc_roi

    dirs = obj["dirs"]

    def _pnl(val) -> str:
        v = float(val)
        s = "green" if v >= 0 else "red"
        return f"[{s}]{v:+,.2f}[/{s}]"

    def _pct(val) -> str:
        v = float(val)
        s = "green" if v >= 0 else "red"
        return f"[{s}]{v:+.1f}%[/{s}]"

    rate_file = ""
    for candidate in [dirs.rate_csv, _os.path.join(dirs.manual, "rate.csv")]:
        if _os.path.exists(candidate):
            rate_file = candidate
            break
    v2r = process_sbi_dir(dirs.sbi, rate_file=rate_file)

    rows = load_csv_rows(dirs)
    holdings = list(v2r.holdings)

    realized, total_realized = calc_realized(rows)
    table = Table(title="売却済み (実現損益)")
    table.add_column("銘柄")
    table.add_column("口座")
    table.add_column("数量", justify="right")
    table.add_column("買avg", justify="right")
    table.add_column("売avg", justify="right")
    table.add_column("損益/株", justify="right")
    table.add_column("総損益", justify="right")
    table.add_column("収益率", justify="right")
    for r in realized:
        table.add_row(r.ticker, r.acct, str(r.sell_qty),
                      f"{r.avg_buy:.2f}", f"{r.avg_sell:.2f}",
                      _pnl(r.pnl_per), _pnl(r.total_pnl), _pct(r.pct))
    console.print(table)
    console.print(f"  実現損益合計: {_pnl(total_realized)} USD\n")

    _, total_unrealized = calc_unrealized(holdings)
    table = Table(title="保有中 (未実現損益)")
    table.add_column("銘柄")
    table.add_column("数量", justify="right")
    table.add_column("取得単価", justify="right")
    table.add_column("現在値", justify="right")
    table.add_column("損益", justify="right")
    table.add_column("収益率", justify="right")
    for h in holdings:
        pct = ((h.price - h.cost) / h.cost * 100) if h.cost else 0
        table.add_row(h.ticker, str(h.qty), f"{h.cost:.2f}", f"{h.price:.2f}",
                      _pnl(h.pnl), _pct(pct))
    console.print(table)
    console.print(f"  未実現損益合計: {_pnl(total_unrealized)} USD\n")

    deposits = v2r.deposits

    roi = calc_roi(rows, holdings, deposits)
    summary = Table(title="総合サマリー", show_header=False, box=None, padding=(0, 2))
    summary.add_column(justify="right", style="bold")
    summary.add_column(justify="right")
    summary.add_row("Total Buy", f"{roi['total_buy']:>12,.2f} USD")
    summary.add_row("Total Sell", f"{roi['total_sell']:>12,.2f} USD")
    summary.add_row("Current Value", f"{roi['total_current']:>12,.2f} USD")
    summary.add_row("Net Invested", f"{roi['net_invested']:>12,.2f} USD")
    if roi['total_deposit']:
        summary.add_row("Total Deposit", f"{roi['total_deposit']:>12,.2f} USD")
    summary.add_row("Total P&L", f"{_pnl(roi['total_pnl'])} USD")
    summary.add_row("ROI", _pct(roi['roi']))
    console.print(Panel(summary))


# ── config & API query commands ─────────────────────────────────


def _make_client():
    from .api import Credentials, InsightaClient
    return InsightaClient(Credentials.from_config())


@cli.command()
def config():
    """config.yaml の設定内容を表示する。"""
    from .i18n import _load_config
    data = _load_config()
    if not data:
        console.print("[dim]config.yaml が見つかりません。cp templates/config.yaml config.yaml で作成してください。[/dim]")
        return
    for k, v in data.items():
        display_v = v if k != "api_key" else (v[:4] + "****" + v[-4:] if len(str(v)) > 8 else "****")
        console.print(f"  {k}: [dim]{display_v}[/dim]")


@cli.command("list-portfolios")
@click.option("--output-json", is_flag=True, help="結果をJSONで出力")
def list_portfolios(output_json):
    """自分のポートフォリオ一覧を取得する。"""
    import json as _json
    client = _make_client()
    data = client.get_portfolios()
    if output_json:
        click.echo(_json.dumps(data, ensure_ascii=False, indent=2))
        return
    from rich.table import Table
    items = data if isinstance(data, list) else data.get("portfolios", data.get("items", []))
    table = Table(title="ポートフォリオ一覧")
    table.add_column("ID")
    table.add_column("名前")
    table.add_column("通貨")
    table.add_column("タイプ")
    for p in items:
        table.add_row(p.get("portfolio_id", p.get("id", "")), p.get("name", ""), p.get("currency", ""), p.get("type", ""))
    console.print(table)


@cli.command("search-portfolios")
@click.option("--search", default=None, help="検索キーワード")
@click.option("--country", default=None, help="国コード (例: JP, KR, US)")
@click.option("--sort-by", default=None, help="ソート基準")
@click.option("--last-item", default=None, help="ページネーション用 last_item")
@click.option("--output-json", is_flag=True, help="結果をJSONで出力")
def search_portfolios_cmd(search, country, sort_by, last_item, output_json):
    """公開ポートフォリオを検索する。"""
    import json as _json
    client = _make_client()
    data = client.search_portfolios(search=search, country=country, sort_by=sort_by, last_item=last_item)
    if output_json:
        click.echo(_json.dumps(data, ensure_ascii=False, indent=2))
        return
    from rich.table import Table
    items = data if isinstance(data, list) else data.get("portfolios", data.get("items", []))
    table = Table(title="検索結果")
    table.add_column("ID")
    table.add_column("名前")
    table.add_column("通貨")
    table.add_column("タイプ")
    for p in items:
        table.add_row(p.get("portfolio_id", p.get("id", "")), p.get("name", ""), p.get("currency", ""), p.get("type", ""))
    console.print(table)


@cli.command("delete-portfolio")
@click.argument("portfolio_id")
@click.option("--yes", "-y", is_flag=True, help="確認プロンプトをスキップ")
def delete_portfolio_cmd(portfolio_id, yes):
    """ポートフォリオを削除する。"""
    if not yes and not click.confirm(f"ポートフォリオ {portfolio_id} を削除しますか？"):
        console.print("[yellow]中断しました。[/yellow]")
        return
    client = _make_client()
    client.delete_portfolio(portfolio_id)
    console.print(f"[green]✅ {portfolio_id} を削除しました。[/green]")


@cli.command("nav-history")
@click.argument("portfolio_id")
@click.option("--output-json", is_flag=True, help="結果をJSONで出力")
def nav_history_cmd(portfolio_id, output_json):
    """ポートフォリオのNAV履歴を取得する。"""
    import json as _json
    client = _make_client()
    data = client.get_nav_history(portfolio_id)
    if output_json:
        click.echo(_json.dumps(data, ensure_ascii=False, indent=2))
        return
    from rich.table import Table
    items = data if isinstance(data, list) else data.get("history", data.get("items", []))
    table = Table(title=f"NAV History: {portfolio_id}")
    table.add_column("日付")
    table.add_column("NAV", justify="right")
    for h in items:
        table.add_row(str(h.get("date", h.get("timestamp", ""))), str(h.get("nav", h.get("value", ""))))
    console.print(table)


@cli.command("metrics-history")
@click.argument("portfolio_id")
@click.option("--metrics", default="twr", help="メトリクス種別 (例: twr)")
@click.option("--from-t", "from_t", type=int, default=None, help="開始タイムスタンプ (ms)")
@click.option("--to-t", "to_t", type=int, default=None, help="終了タイムスタンプ (ms)")
@click.option("--output-json", is_flag=True, help="結果をJSONで出力")
def metrics_history_cmd(portfolio_id, metrics, from_t, to_t, output_json):
    """ポートフォリオのメトリクス履歴を取得する。"""
    import json as _json
    client = _make_client()
    data = client.get_metrics_history(portfolio_id, metrics=metrics, from_t=from_t, to_t=to_t)
    if output_json:
        click.echo(_json.dumps(data, ensure_ascii=False, indent=2))
        return
    from rich.table import Table
    items = data if isinstance(data, list) else data.get("history", data.get("items", []))
    table = Table(title=f"Metrics History ({metrics}): {portfolio_id}")
    table.add_column("日付")
    table.add_column("値", justify="right")
    for h in items:
        table.add_row(str(h.get("date", h.get("timestamp", ""))), str(h.get("value", "")))
    console.print(table)
