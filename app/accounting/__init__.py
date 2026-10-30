"""Double-entry ledger and IAS 2 inventory costing.

Functions here change the session but do not commit, so a caller's stock
movement and its journal entry are saved together or not at all.
"""
from datetime import datetime, timedelta
from sqlalchemy import inspect, text
from app.models import db, utc_now, Product, Inventory, InventoryBatch, PurchaseOrder, \
    OrderLine, Payment, JournalEntry, JournalLine, STANDARD_VAT_RATE, ZERO_VAT_RATE

BANK = '1000'
INVENTORY = '1200'
VAT_INPUT = '1300'
TRADE_PAYABLES = '2100'
CAPITAL = '3000'
COST_OF_SALES = '5000'
WRITE_DOWNS = '5100'

CHART_OF_ACCOUNTS = {
    BANK: 'Bank',
    INVENTORY: 'Inventory',
    VAT_INPUT: 'VAT Input (recoverable from SARS)',
    TRADE_PAYABLES: 'Trade Payables',
    CAPITAL: "Owner's Capital",
    COST_OF_SALES: 'Cost of Sales',
    WRITE_DOWNS: 'Inventory Write-downs (IAS 2.34)',
}

QTY_TOLERANCE = 1e-6


class AccountingError(Exception):
    """A transaction was refused; the message is safe to show to the user."""


# ── Journal ───────────────────────────────────────────────────────────────────
def post_entry(when, source, reference, memo, lines):
    """lines is a list of (account_code, debit, credit)."""
    lines = [(code, round(dr, 2), round(cr, 2)) for code, dr, cr in lines
             if round(dr, 2) or round(cr, 2)]
    if not lines:
        return None
    debits = round(sum(l[1] for l in lines), 2)
    credits = round(sum(l[2] for l in lines), 2)
    if debits != credits:
        raise AccountingError(f'Journal does not balance: Dr {debits} / Cr {credits}.')
    entry = JournalEntry(entry_date=when, source=source, reference=reference, memo=memo)
    for code, dr, cr in lines:
        entry.lines.append(JournalLine(account_code=code, debit=dr, credit=cr))
    db.session.add(entry)
    return entry


def _movement(code, start=None, end=None, source=None):
    """Net debit movement on an account; start and end are inclusive."""
    query = db.session.query(
        db.func.coalesce(db.func.sum(JournalLine.debit - JournalLine.credit), 0)
    ).join(JournalEntry).filter(JournalLine.account_code == code)
    if start is not None:
        query = query.filter(JournalEntry.entry_date >= start)
    if end is not None:
        query = query.filter(JournalEntry.entry_date <= end)
    if source is not None:
        query = query.filter(JournalEntry.source == source)
    return round(query.scalar(), 2)


# ── Inventory transactions ────────────────────────────────────────────────────
def _new_batch(inventory, qty, unit_cost, when, order_line=None):
    shelf_life = inventory.product.shelf_life_days
    batch = InventoryBatch(
        inventory_id=inventory.id,
        order_line_id=order_line.id if order_line else None,
        received_at=when,
        expiry_date=when + timedelta(days=shelf_life) if shelf_life else None,
        qty_received=qty,
        qty_remaining=qty,
        unit_cost=unit_cost,
        carrying_value=round(qty * unit_cost, 2),
    )
    db.session.add(batch)
    return batch


def _relieve(batch, qty):
    """Take qty out of a batch and return the carrying value removed with it."""
    if abs(qty - batch.qty_remaining) < QTY_TOLERANCE:
        # Last of the batch takes whatever is left, so rounding never strands cents
        value = batch.carrying_value
        batch.qty_remaining = 0
        batch.carrying_value = 0
    else:
        value = round(batch.carrying_value * qty / batch.qty_remaining, 2)
        batch.qty_remaining = round(batch.qty_remaining - qty, 3)
        batch.carrying_value = round(batch.carrying_value - value, 2)
    batch.inventory.qty_on_hand = round(batch.inventory.qty_on_hand - qty, 3)
    return value


def capitalise_opening_stock(when=None):
    """Give a cost to stock that was entered as a bare quantity."""
    when = when or utc_now()
    total = 0
    for inv in Inventory.query.filter(Inventory.qty_on_hand > 0).all():
        if inv.batches.count() == 0:
            total += _new_batch(inv, inv.qty_on_hand, inv.product.unit_cost, when).carrying_value
    return post_entry(when, 'opening', 'Opening balances', 'Opening inventory at supplier cost', [
        (INVENTORY, total, 0),
        (CAPITAL, 0, total),
    ])


def receive_order(order, when=None):
    """Control passes on delivery: Dr Inventory, Dr VAT Input / Cr Trade Payables."""
    if order.status == 'Delivered':
        raise AccountingError(f'Order #{order.id} has already been received.')
    when = when or utc_now()
    order.recalculate_total()
    for line in order.lines:
        inv = Inventory.query.filter_by(product_id=line.product_id).first()
        if inv is None:
            inv = Inventory(product_id=line.product_id, qty_on_hand=0)
            db.session.add(inv)
            db.session.flush()
        _new_batch(inv, line.quantity, line.agreed_unit_cost, when, order_line=line)
        inv.qty_on_hand = round(inv.qty_on_hand + line.quantity, 3)
        inv.last_restocked = when
    order.status = 'Delivered'
    order.received_at = when
    return post_entry(when, 'purchase', f'PO #{order.id}',
                      f'Goods received from {order.supplier.company_name}', [
                          (INVENTORY, order.total_amount, 0),
                          (VAT_INPUT, order.vat_amount, 0),
                          (TRADE_PAYABLES, 0, order.gross_amount),
                      ])


def _issue(batches, qty, inventory, when, source, memo):
    remaining = qty
    cost = 0
    for batch in batches:
        take = min(remaining, batch.qty_remaining)
        cost += _relieve(batch, take)
        remaining = round(remaining - take, 6)
        if remaining <= QTY_TOLERANCE:
            break
    post_entry(when, source, inventory.product.name, memo, [
        (COST_OF_SALES, cost, 0),
        (INVENTORY, 0, cost),
    ])
    return round(cost, 2)


def record_usage(inventory, qty, when=None):
    """Kitchen usage at FIFO cost. Expired batches cannot be issued, only written off."""
    when = when or utc_now()
    usable = [b for b in inventory.open_batches if not b.is_expired(when)]
    available = round(sum(b.qty_remaining for b in usable), 3)
    if qty <= 0:
        raise AccountingError('Quantity used must be more than zero.')
    if qty > available + QTY_TOLERANCE:
        raise AccountingError(f'Only {available} {inventory.product.unit_of_measure} '
                              f'of unexpired stock is available.')
    return _issue(usable, qty, inventory, when, 'usage',
                  f'Used {qty} {inventory.product.unit_of_measure} at FIFO cost')


def apply_stock_count(inventory, counted, when=None):
    """Bring the books into line with a physical count."""
    when = when or utc_now()
    variance = round(counted - inventory.qty_on_hand, 3)
    unit = inventory.product.unit_of_measure
    if variance < 0:
        _issue(inventory.open_batches, -variance, inventory, when, 'stock_count',
               f'Stock count shortfall of {-variance} {unit}')
    elif variance > 0:
        newest = inventory.batches.order_by(
            InventoryBatch.received_at.desc(), InventoryBatch.id.desc()).first()
        unit_cost = newest.unit_cost if newest else inventory.product.unit_cost
        batch = _new_batch(inventory, variance, unit_cost, when)
        inventory.qty_on_hand = round(inventory.qty_on_hand + variance, 3)
        post_entry(when, 'stock_count', inventory.product.name,
                   f'Stock count surplus of {variance} {unit}', [
                       (INVENTORY, batch.carrying_value, 0),
                       (COST_OF_SALES, 0, batch.carrying_value),
                   ])
    return variance


def write_down_batch(batch, qty, nrv_per_unit, reason, when=None):
    """Reduce stock to net realisable value (IAS 2.9); an NRV of zero removes it as spoiled."""
    when = when or utc_now()
    if qty <= 0 or qty > batch.qty_remaining + QTY_TOLERANCE:
        raise AccountingError(f'Quantity must be between 0 and {batch.qty_remaining}.')
    if nrv_per_unit < 0:
        raise AccountingError('Net realisable value cannot be negative.')
    if nrv_per_unit > 0 and round(nrv_per_unit, 2) >= round(batch.carrying_unit_cost, 2):
        raise AccountingError(
            f'NRV of R{nrv_per_unit:.2f} is not below the carrying amount of '
            f'R{batch.carrying_unit_cost:.2f} per unit, so IAS 2 requires no write-down.')

    inventory = batch.inventory
    is_whole_batch = abs(qty - batch.qty_remaining) < QTY_TOLERANCE
    received_at, expiry_date, unit_cost, line_id = (
        batch.received_at, batch.expiry_date, batch.unit_cost, batch.order_line_id)
    old_value = _relieve(batch, qty)
    new_value = round(qty * nrv_per_unit, 2)
    if new_value > 0:
        # Keep the reduced stock on hand; a part write-down needs its own batch
        target = batch if is_whole_batch else InventoryBatch(
            inventory_id=inventory.id, order_line_id=line_id, received_at=received_at,
            expiry_date=expiry_date, qty_received=qty, unit_cost=unit_cost,
            qty_remaining=0, carrying_value=0)
        db.session.add(target)
        target.qty_remaining = round(qty, 3)
        target.carrying_value = new_value
        inventory.qty_on_hand = round(inventory.qty_on_hand + qty, 3)
    loss = round(old_value - new_value, 2)
    post_entry(when, 'write_down', inventory.product.name, reason, [
        (WRITE_DOWNS, loss, 0),
        (INVENTORY, 0, loss),
    ])
    return loss


def write_off_expired(when=None):
    """Expired food has no realisable value, so every expired batch goes to zero."""
    when = when or utc_now()
    count, total = 0, 0
    for batch in InventoryBatch.query.filter(InventoryBatch.qty_remaining > 0).all():
        if batch.is_expired(when):
            total += write_down_batch(
                batch, batch.qty_remaining, 0,
                f'Expired {batch.expiry_date.strftime("%d %b %Y")}: written off to nil NRV', when)
            count += 1
    return count, round(total, 2)


# ── Payables ──────────────────────────────────────────────────────────────────
def pay_order(order, method='EFT', when=None):
    """Settle a supplier invoice in full: Dr Trade Payables / Cr Bank."""
    if order.status != 'Delivered' or order.received_at is None:
        raise AccountingError(f'Order #{order.id} has not been received, so nothing is owed yet.')
    if order.is_paid:
        raise AccountingError(f'Order #{order.id} has already been paid.')
    when = when or utc_now()
    db.session.add(Payment(order_id=order.id, amount=order.gross_amount, method=method,
                           payment_date=when, status='Paid'))
    return post_entry(when, 'payment', f'PO #{order.id}',
                      f'{method} payment to {order.supplier.company_name}', [
                          (TRADE_PAYABLES, order.gross_amount, 0),
                          (BANK, 0, order.gross_amount),
                      ])


def open_payables():
    orders = PurchaseOrder.query.filter(
        PurchaseOrder.status == 'Delivered',
        PurchaseOrder.received_at.isnot(None)
    ).order_by(PurchaseOrder.received_at).all()
    return [o for o in orders if not o.is_paid]


# ── Reports ───────────────────────────────────────────────────────────────────
def cost_of_sales_statement(start, end):
    """IAS 2 cost of sales: opening inventory + purchases - closing inventory."""
    # Opening-balance entries are opening stock whichever date they fall on
    opening = round(_movement(INVENTORY, end=start - timedelta(microseconds=1))
                    + _movement(INVENTORY, start, end, 'opening'), 2)
    purchases = _movement(INVENTORY, start, end, 'purchase')
    closing = _movement(INVENTORY, end=end)
    cost_of_sales = round(opening + purchases - closing, 2)

    used = _movement(COST_OF_SALES, start, end, 'usage')
    variances = _movement(COST_OF_SALES, start, end, 'stock_count')
    write_downs = _movement(WRITE_DOWNS, start, end)
    ledger_total = round(used + variances + write_downs, 2)
    return {
        'opening': opening,
        'purchases': purchases,
        'available': round(opening + purchases, 2),
        'closing': closing,
        'cost_of_sales': cost_of_sales,
        'used': used,
        'variances': variances,
        'write_downs': write_downs,
        'ledger_total': ledger_total,
        'reconciles': cost_of_sales == ledger_total,
    }


def inventory_by_category():
    """Current carrying amount by classification (IAS 2.36(b))."""
    totals = {}
    for inv in Inventory.query.join(Product).all():
        category = inv.product.category or 'Uncategorised'
        totals[category] = round(totals.get(category, 0) + inv.carrying_value, 2)
    return {k: v for k, v in sorted(totals.items()) if v}


def trial_balance(as_of=None):
    rows = []
    for code, name in CHART_OF_ACCOUNTS.items():
        balance = _movement(code, end=as_of)
        rows.append({
            'code': code,
            'name': name,
            'debit': balance if balance > 0 else 0,
            'credit': -balance if balance < 0 else 0,
        })
    return rows


def ledger_checks():
    """Control checks: the ledger must agree with the records beneath it."""
    batch_total = db.session.query(
        db.func.coalesce(db.func.sum(InventoryBatch.carrying_value), 0)).scalar()
    payables_total = sum(o.gross_amount for o in open_payables())
    debits, credits = db.session.query(
        db.func.coalesce(db.func.sum(JournalLine.debit), 0),
        db.func.coalesce(db.func.sum(JournalLine.credit), 0)).one()
    checks = [
        ('Total debits = total credits', debits, credits),
        ('Inventory account = batch records', _movement(INVENTORY), batch_total),
        ('Trade Payables account = unpaid invoices', -_movement(TRADE_PAYABLES), payables_total),
    ]
    return [{'name': name, 'left': round(left, 2), 'right': round(right, 2),
             'ok': round(left, 2) == round(right, 2)} for name, left, right in checks]


# ── Database upgrade ──────────────────────────────────────────────────────────
NEW_COLUMNS = {
    'product': [('vat_rate', f'FLOAT DEFAULT {STANDARD_VAT_RATE}')],
    'order_line': [('vat_rate', f'FLOAT DEFAULT {STANDARD_VAT_RATE}')],
    'purchase_order': [('vat_amount', 'FLOAT DEFAULT 0'), ('received_at', 'TIMESTAMP')],
}


def prepare_database():
    """Create or upgrade the schema in place, keeping existing data. Safe to re-run."""
    db.create_all()
    inspector = inspect(db.engine)
    added = set()
    for table, columns in NEW_COLUMNS.items():
        existing = {c['name'] for c in inspector.get_columns(table)}
        for name, definition in columns:
            if name not in existing:
                db.session.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {definition}'))
                added.add((table, name))
    db.session.commit()

    if ('product', 'vat_rate') in added:
        # Fresh vegetables are zero-rated under Schedule 2 of the VAT Act
        Product.query.filter_by(category='Vegetables').update({'vat_rate': ZERO_VAT_RATE})
    if ('order_line', 'vat_rate') in added:
        for line in OrderLine.query.all():
            line.vat_rate = line.product.vat_rate
    # Delivered orders are posted to the ledger, so their totals must never change
    for order in PurchaseOrder.query.filter(PurchaseOrder.status != 'Delivered').all():
        order.recalculate_total()
    db.session.commit()

    capitalise_opening_stock()
    db.session.commit()


def period_bounds(start_date, end_date):
    return (datetime.combine(start_date, datetime.min.time()),
            datetime.combine(end_date, datetime.max.time()))
