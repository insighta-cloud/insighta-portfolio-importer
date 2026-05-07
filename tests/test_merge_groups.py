"""load_order_groups + 그룹핑 단위 테스트."""
import sys, os, tempfile, csv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sbi.api import OrderGroup, CashDeposit, load_order_groups, _group_hash


def _write_orders_csv(rows: list[dict]) -> str:
    """임시 orders.csv 파일 생성."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8")
    header = ["group_id", "group_dt", "type", "ticker", "quantity", "price", "currency", "settle_currency", "rate", "price_type", "timestamp"]
    w = csv.DictWriter(f, fieldnames=header)
    w.writeheader()
    for row in rows:
        w.writerow(row)
    f.close()
    return f.name


def test_order_and_fee_in_same_group():
    """주문과 fee가 같은 group_id면 하나의 OrderGroup에 합쳐짐."""
    gdt = "2024-12-19 00:00:00"
    gid = _group_hash(gdt, "JPY")
    path = _write_orders_csv([
        {"group_id": gid, "group_dt": gdt, "type": "order", "ticker": "SPYD", "quantity": "87", "price": "44.64", "currency": "USD", "settle_currency": "JPY", "rate": "155.12", "price_type": "LIMIT", "timestamp": "2024-12-19 00:00:00"},
        {"group_id": gid, "group_dt": gdt, "type": "fee", "ticker": "fee:SPYD", "quantity": "", "price": "-0.4416", "currency": "JPY", "settle_currency": "JPY", "rate": "", "price_type": "", "timestamp": "2024-12-19 00:00:00"},
    ])
    try:
        groups = load_order_groups(path)
        assert len(groups) == 1
        assert len(groups[0].items) == 1
        assert groups[0].items[0]["ticker"] == "SPYD"
        assert len(groups[0].cash_deposits) == 1
        assert groups[0].cash_deposits[0].ticker == "fee:SPYD"
        assert groups[0].exchange_rate == 155.12
    finally:
        os.unlink(path)


def test_non_order_deposits_separate_group():
    """비주문 deposit은 별도 그룹."""
    gdt_order = "2024-12-19 00:00:00"
    gdt_deposit = "2024-12-20 00:00:00"
    gid_order = _group_hash(gdt_order, "JPY")
    gid_deposit = _group_hash(gdt_deposit, "deposit")
    path = _write_orders_csv([
        {"group_id": gid_order, "group_dt": gdt_order, "type": "order", "ticker": "SPY", "quantity": "1", "price": "604.0", "currency": "USD", "settle_currency": "JPY", "rate": "155.12", "price_type": "LIMIT", "timestamp": "2024-12-19 00:00:00"},
        {"group_id": gid_deposit, "group_dt": gdt_deposit, "type": "budget", "ticker": "", "quantity": "", "price": "50000.0", "currency": "JPY", "settle_currency": "", "rate": "", "price_type": "", "timestamp": "2024-12-20 00:00:00"},
    ])
    try:
        groups = load_order_groups(path)
        assert len(groups) == 2
        order_g = [g for g in groups if g.items][0]
        deposit_g = [g for g in groups if not g.items][0]
        assert order_g.items[0]["ticker"] == "SPY"
        assert deposit_g.cash_deposits[0].amount == 50000.0
    finally:
        os.unlink(path)


def test_multiple_orders_same_group():
    """같은 group_id의 여러 주문이 하나의 그룹에 합쳐짐."""
    gdt = "2024-12-19 00:00:00"
    gid = _group_hash(gdt, "JPY")
    path = _write_orders_csv([
        {"group_id": gid, "group_dt": gdt, "type": "order", "ticker": "SPYD", "quantity": "87", "price": "44.64", "currency": "USD", "settle_currency": "JPY", "rate": "155.12", "price_type": "LIMIT", "timestamp": "2024-12-19 00:00:00"},
        {"group_id": gid, "group_dt": gdt, "type": "order", "ticker": "SPY", "quantity": "1", "price": "604.0", "currency": "USD", "settle_currency": "JPY", "rate": "155.12", "price_type": "LIMIT", "timestamp": "2024-12-19 00:00:00"},
        {"group_id": gid, "group_dt": gdt, "type": "order", "ticker": "QQQ", "quantity": "18", "price": "535.11", "currency": "USD", "settle_currency": "JPY", "rate": "155.12", "price_type": "LIMIT", "timestamp": "2024-12-19 00:00:00"},
    ])
    try:
        groups = load_order_groups(path)
        assert len(groups) == 1
        assert len(groups[0].items) == 3
        assert groups[0].exchange_rate == 155.12
    finally:
        os.unlink(path)


def test_sorted_by_group_dt():
    """그룹이 group_dt 시간순으로 정렬."""
    rows = []
    for gdt in ["2024-12-20 00:00:00", "2024-12-18 00:00:00", "2024-12-19 00:00:00"]:
        gid = _group_hash(gdt, "JPY")
        rows.append({"group_id": gid, "group_dt": gdt, "type": "order", "ticker": "SPY", "quantity": "1", "price": "600", "currency": "USD", "settle_currency": "JPY", "rate": "155", "price_type": "LIMIT", "timestamp": gdt})
    path = _write_orders_csv(rows)
    try:
        groups = load_order_groups(path)
        assert groups[0].group_dt == "2024-12-18 00:00:00"
        assert groups[1].group_dt == "2024-12-19 00:00:00"
        assert groups[2].group_dt == "2024-12-20 00:00:00"
    finally:
        os.unlink(path)


def test_no_duplicate_memo():
    """같은 group_id의 주문+fee가 하나의 그룹이므로 메모 중복 없음."""
    gdt = "2024-12-19 00:00:00"
    gid = _group_hash(gdt, "JPY")
    path = _write_orders_csv([
        {"group_id": gid, "group_dt": gdt, "type": "order", "ticker": "SPYD", "quantity": "87", "price": "44.64", "currency": "USD", "settle_currency": "JPY", "rate": "155.12", "price_type": "LIMIT", "timestamp": gdt},
        {"group_id": gid, "group_dt": gdt, "type": "fee", "ticker": "fee:SPYD", "quantity": "", "price": "-0.44", "currency": "JPY", "settle_currency": "JPY", "rate": "", "price_type": "", "timestamp": gdt},
        {"group_id": gid, "group_dt": gdt, "type": "order", "ticker": "SPY", "quantity": "1", "price": "604.0", "currency": "USD", "settle_currency": "JPY", "rate": "155.12", "price_type": "LIMIT", "timestamp": gdt},
        {"group_id": gid, "group_dt": gdt, "type": "fee", "ticker": "fee:SPY", "quantity": "", "price": "-0.48", "currency": "JPY", "settle_currency": "JPY", "rate": "", "price_type": "", "timestamp": gdt},
    ])
    try:
        groups = load_order_groups(path)
        # 하나의 그룹만 존재 → 메모가 한 번만 적용됨
        assert len(groups) == 1
        assert len(groups[0].items) == 2
        assert len(groups[0].cash_deposits) == 2
    finally:
        os.unlink(path)


if __name__ == "__main__":
    test_order_and_fee_in_same_group()
    test_non_order_deposits_separate_group()
    test_multiple_orders_same_group()
    test_sorted_by_group_dt()
    test_no_duplicate_memo()
    print("All tests passed ✓")
