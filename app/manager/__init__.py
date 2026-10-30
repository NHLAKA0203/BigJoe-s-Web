from flask import Blueprint, render_template, redirect, url_for, flash, request, Response
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime
from app.models import db, utc_now, User, Supplier, Product, Inventory, PurchaseOrder, OrderLine, Notification
from app.forms import PurchaseOrderForm, OrderLineForm, InventoryUpdateForm, ReportForm, \
    UsageForm, WriteDownForm, PaymentForm
from app import accounting
from app.accounting import AccountingError
import csv
import io

bp = Blueprint('manager', __name__, url_prefix='/manager')


def manager_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in ('manager', 'admin'):
            flash('Access restricted to managers.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return login_required(decorated)


# ── Dashboard ────────────────────────────────────────────────────────────────
@bp.route('/dashboard')
@manager_required
def dashboard():
    total_suppliers = Supplier.query.count()
    total_products = Product.query.count()
    pending_orders = PurchaseOrder.query.filter_by(status='Pending').count()
    low_stock = Inventory.query.filter(
        Inventory.qty_on_hand <= Inventory.reorder_level).all()
    recent_orders = PurchaseOrder.query.order_by(
        PurchaseOrder.order_date.desc()).limit(5).all()
    month_start = utc_now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_spend = db.session.query(
        db.func.sum(PurchaseOrder.total_amount)
    ).filter(
        PurchaseOrder.status == 'Delivered',
        PurchaseOrder.received_at >= month_start
    ).scalar() or 0
    inventory_value = sum(i.carrying_value for i in Inventory.query.all())
    payables_total = sum(o.gross_amount for o in accounting.open_payables())
    notifications = Notification.query.filter_by(
        user_id=current_user.id, is_read=False).order_by(
        Notification.sent_at.desc()).limit(5).all()
    return render_template('manager/dashboard.html',
                           total_suppliers=total_suppliers,
                           total_products=total_products,
                           pending_orders=pending_orders,
                           low_stock=low_stock,
                           recent_orders=recent_orders,
                           monthly_spend=monthly_spend,
                           inventory_value=inventory_value,
                           payables_total=payables_total,
                           notifications=notifications)


# ── Suppliers ─────────────────────────────────────────────────────────────────
@bp.route('/suppliers')
@manager_required
def suppliers():
    q = request.args.get('q', '')
    query = Supplier.query
    if q:
        query = query.join(User).filter(
            db.or_(Supplier.company_name.ilike(f'%{q}%'),
                   Supplier.region.ilike(f'%{q}%')))
    suppliers = query.all()
    return render_template('manager/suppliers.html', suppliers=suppliers, q=q)


@bp.route('/suppliers/<int:supplier_id>')
@manager_required
def supplier_detail(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    products = Product.query.filter_by(supplier_id=supplier_id, available=True).all()
    return render_template('manager/supplier_detail.html', supplier=supplier, products=products)


# ── Inventory ─────────────────────────────────────────────────────────────────
@bp.route('/inventory')
@manager_required
def inventory():
    items = Inventory.query.join(Product).join(Supplier).all()
    total_value = round(sum(i.carrying_value for i in items), 2)
    expired_count = sum(len(i.expired_batches) for i in items)
    return render_template('manager/inventory.html', items=items, total_value=total_value,
                           expired_count=expired_count)


def write_down_form_for(item):
    form = WriteDownForm()
    form.batch_id.choices = [
        (b.id, f'Received {b.received_at.strftime("%d %b %Y")} — {b.qty_remaining} '
               f'{item.product.unit_of_measure} @ R{b.carrying_unit_cost:.2f}')
        for b in item.open_batches]
    return form


@bp.route('/inventory/<int:item_id>')
@manager_required
def inventory_detail(item_id):
    item = Inventory.query.get_or_404(item_id)
    return render_template('manager/inventory_detail.html', item=item,
                           usage_form=UsageForm(),
                           write_down_form=write_down_form_for(item))


@bp.route('/inventory/<int:item_id>/usage', methods=['POST'])
@manager_required
def record_usage(item_id):
    item = Inventory.query.get_or_404(item_id)
    form = UsageForm()
    if form.validate_on_submit():
        try:
            cost = accounting.record_usage(item, form.quantity.data)
            db.session.commit()
            flash(f'Usage recorded: R {cost:.2f} charged to Cost of Sales at FIFO cost.', 'success')
        except AccountingError as e:
            db.session.rollback()
            flash(str(e), 'danger')
    else:
        flash('Enter a quantity greater than zero.', 'danger')
    return redirect(url_for('manager.inventory_detail', item_id=item_id))


@bp.route('/inventory/<int:item_id>/write_down', methods=['POST'])
@manager_required
def write_down(item_id):
    item = Inventory.query.get_or_404(item_id)
    form = write_down_form_for(item)
    if form.validate_on_submit():
        batch = db.session.get(accounting.InventoryBatch, form.batch_id.data)
        try:
            loss = accounting.write_down_batch(batch, form.quantity.data, form.nrv_per_unit.data,
                                               form.reason.data)
            db.session.commit()
            flash(f'Write-down of R {loss:.2f} posted (IAS 2.34).', 'success')
        except AccountingError as e:
            db.session.rollback()
            flash(str(e), 'danger')
    else:
        flash('Choose a batch and enter the quantity, NRV and reason.', 'danger')
    return redirect(url_for('manager.inventory_detail', item_id=item_id))


@bp.route('/inventory/write_off_expired', methods=['POST'])
@manager_required
def write_off_expired():
    count, total = accounting.write_off_expired()
    db.session.commit()
    flash(f'{count} expired batch(es) written off: R {total:.2f} expensed.', 'success')
    return redirect(url_for('manager.inventory'))


@bp.route('/inventory/<int:item_id>/edit', methods=['GET', 'POST'])
@manager_required
def edit_inventory(item_id):
    item = Inventory.query.get_or_404(item_id)
    form = InventoryUpdateForm(obj=item)
    if form.validate_on_submit():
        variance = accounting.apply_stock_count(item, form.qty_on_hand.data)
        item.reorder_level = form.reorder_level.data
        db.session.commit()
        if variance:
            flash(f'Stock count variance of {variance:+g} {item.product.unit_of_measure} '
                  f'posted to Cost of Sales.', 'success')
        else:
            flash('Inventory updated.', 'success')
        return redirect(url_for('manager.inventory_detail', item_id=item.id))
    return render_template('manager/edit_inventory.html', form=form, item=item)


# ── Purchase Orders ────────────────────────────────────────────────────────────
@bp.route('/orders')
@manager_required
def orders():
    status_filter = request.args.get('status', '')
    query = PurchaseOrder.query.filter_by(manager_id=current_user.id)
    if status_filter:
        query = query.filter_by(status=status_filter)
    orders = query.order_by(PurchaseOrder.order_date.desc()).all()
    return render_template('manager/orders.html', orders=orders, status_filter=status_filter)


@bp.route('/orders/new', methods=['GET', 'POST'])
@manager_required
def new_order():
    form = PurchaseOrderForm()
    form.supplier_id.choices = [(s.id, s.company_name) for s in Supplier.query.all()]
    if form.validate_on_submit():
        order = PurchaseOrder(
            manager_id=current_user.id,
            supplier_id=form.supplier_id.data,
            notes=form.notes.data,
            status='Pending'
        )
        db.session.add(order)
        db.session.commit()
        # Notify supplier
        supplier = db.session.get(Supplier, form.supplier_id.data)
        notif = Notification(
            user_id=supplier.user_id,
            message=f'New purchase order #{order.id} received from {current_user.name}.',
            type='info'
        )
        db.session.add(notif)
        db.session.commit()
        flash(f'Order #{order.id} created. Add items below.', 'success')
        return redirect(url_for('manager.order_detail', order_id=order.id))
    return render_template('manager/new_order.html', form=form)


@bp.route('/orders/<int:order_id>', methods=['GET', 'POST'])
@manager_required
def order_detail(order_id):
    order = PurchaseOrder.query.get_or_404(order_id)
    form = OrderLineForm()
    products = Product.query.filter_by(supplier_id=order.supplier_id, available=True).all()
    form.product_id.choices = [(p.id, f'{p.name} — R{p.unit_cost}/{p.unit_of_measure} '
                                      f'excl. VAT ({p.vat_rate:.0%} VAT)')
                                for p in products]
    if form.validate_on_submit() and order.status == 'Pending':
        product = db.session.get(Product, form.product_id.data)
        line = OrderLine(
            order_id=order.id,
            product_id=product.id,
            quantity=form.quantity.data,
            agreed_unit_cost=product.unit_cost,
            vat_rate=product.vat_rate
        )
        db.session.add(line)
        order.recalculate_total()
        db.session.commit()
        flash('Item added.', 'success')
        return redirect(url_for('manager.order_detail', order_id=order.id))
    return render_template('manager/order_detail.html', order=order, form=form)


@bp.route('/orders/<int:order_id>/submit', methods=['POST'])
@manager_required
def submit_order(order_id):
    order = PurchaseOrder.query.get_or_404(order_id)
    if order.status != 'Pending':
        flash(f'Order #{order.id} has already been submitted.', 'warning')
        return redirect(url_for('manager.order_detail', order_id=order.id))
    if order.lines.count() == 0:
        flash('Add at least one item before submitting.', 'warning')
        return redirect(url_for('manager.order_detail', order_id=order.id))
    order.status = 'Submitted'
    db.session.commit()
    flash(f'Order #{order.id} submitted to supplier.', 'success')
    return redirect(url_for('manager.orders'))


@bp.route('/orders/<int:order_id>/delete_line/<int:line_id>', methods=['POST'])
@manager_required
def delete_line(order_id, line_id):
    line = OrderLine.query.filter_by(id=line_id, order_id=order_id).first_or_404()
    order = line.order
    if order.status != 'Pending':
        flash('Items can only be removed before the order is submitted.', 'warning')
        return redirect(url_for('manager.order_detail', order_id=order_id))
    db.session.delete(line)
    order.recalculate_total()
    db.session.commit()
    flash('Item removed.', 'info')
    return redirect(url_for('manager.order_detail', order_id=order_id))


# ── Reports ────────────────────────────────────────────────────────────────────
@bp.route('/reports', methods=['GET', 'POST'])
@manager_required
def reports():
    form = ReportForm()
    report_data = None
    if form.validate_on_submit():
        if form.end_date.data < form.start_date.data:
            flash('End date must be on or after the start date.', 'danger')
            return render_template('manager/reports.html', form=form, report_data=None)
        start, end = accounting.period_bounds(form.start_date.data, form.end_date.data)
        delivered_orders = delivered_in_period(start, end)
        by_supplier = {}
        for o in delivered_orders:
            name = o.supplier.company_name
            by_supplier[name] = by_supplier.get(name, 0) + o.total_amount
        report_data = {
            'start': form.start_date.data,
            'end': form.end_date.data,
            'statement': accounting.cost_of_sales_statement(start, end),
            'input_vat': sum(o.vat_amount for o in delivered_orders),
            'order_count': len(delivered_orders),
            'by_supplier': by_supplier,
            'orders': delivered_orders,
            'by_category': accounting.inventory_by_category(),
        }
    return render_template('manager/reports.html', form=form, report_data=report_data)


def delivered_in_period(start, end):
    # Purchases are recognised when goods are received, not when ordered
    return PurchaseOrder.query.filter(
        PurchaseOrder.status == 'Delivered',
        PurchaseOrder.received_at >= start,
        PurchaseOrder.received_at <= end
    ).order_by(PurchaseOrder.received_at).all()


@bp.route('/reports/export_csv')
@manager_required
def export_csv():
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    try:
        start, end = accounting.period_bounds(datetime.strptime(start_str, '%Y-%m-%d').date(),
                                              datetime.strptime(end_str, '%Y-%m-%d').date())
    except (TypeError, ValueError):
        flash('Invalid date range for export.', 'danger')
        return redirect(url_for('manager.reports'))
    statement = accounting.cost_of_sales_statement(start, end)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([f'Cost of sales statement (IAS 2): {start_str} to {end_str}', 'R'])
    for label, key in [('Opening inventory', 'opening'),
                       ('Add: purchases (excl. VAT)', 'purchases'),
                       ('Less: closing inventory', 'closing'),
                       ('Cost of sales', 'cost_of_sales'),
                       ('  of which: kitchen usage at FIFO cost', 'used'),
                       ('  of which: stock count variances', 'variances'),
                       ('  of which: write-downs to NRV', 'write_downs')]:
        writer.writerow([label, f'{statement[key]:.2f}'])
    writer.writerow([])
    writer.writerow(['Order #', 'Supplier', 'Order Date', 'Received Date',
                     'Excl. VAT (R)', 'VAT (R)', 'Incl. VAT (R)', 'Paid'])
    for o in delivered_in_period(start, end):
        writer.writerow([o.id, o.supplier.company_name,
                         o.order_date.strftime('%Y-%m-%d'),
                         o.received_at.strftime('%Y-%m-%d'),
                         f'{o.total_amount:.2f}', f'{o.vat_amount:.2f}',
                         f'{o.gross_amount:.2f}', 'Yes' if o.is_paid else 'No'])
    output.seek(0)
    return Response(output, mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment;filename=bigjos_report.csv'})


# ── Accounting ─────────────────────────────────────────────────────────────────
@bp.route('/payables')
@manager_required
def payables():
    open_orders = accounting.open_payables()
    now = utc_now()
    rows = [{'order': o, 'age': (now - o.received_at).days} for o in open_orders]
    by_supplier = {}
    for o in open_orders:
        name = o.supplier.company_name
        by_supplier[name] = round(by_supplier.get(name, 0) + o.gross_amount, 2)
    return render_template('manager/payables.html', rows=rows, by_supplier=by_supplier,
                           total=round(sum(o.gross_amount for o in open_orders), 2),
                           form=PaymentForm())


@bp.route('/payables/<int:order_id>/pay', methods=['POST'])
@manager_required
def pay_order(order_id):
    order = PurchaseOrder.query.get_or_404(order_id)
    form = PaymentForm()
    if form.validate_on_submit():
        try:
            accounting.pay_order(order, method=form.method.data)
            db.session.commit()
            flash(f'Order #{order.id} paid: R {order.gross_amount:.2f}.', 'success')
        except AccountingError as e:
            db.session.rollback()
            flash(str(e), 'danger')
    return redirect(url_for('manager.payables'))


@bp.route('/journal')
@manager_required
def journal():
    entries = accounting.JournalEntry.query.order_by(
        accounting.JournalEntry.entry_date.desc(), accounting.JournalEntry.id.desc()).all()
    rows = accounting.trial_balance()
    return render_template('manager/journal.html', entries=entries, trial_balance=rows,
                           accounts=accounting.CHART_OF_ACCOUNTS,
                           checks=accounting.ledger_checks(),
                           total_debit=round(sum(r['debit'] for r in rows), 2),
                           total_credit=round(sum(r['credit'] for r in rows), 2))


# ── Notifications ──────────────────────────────────────────────────────────────
@bp.route('/notifications')
@manager_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(
        Notification.sent_at.desc()).all()
    for n in notifs:
        n.is_read = True
    db.session.commit()
    return render_template('manager/notifications.html', notifications=notifs)
