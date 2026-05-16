from flask import Blueprint, render_template, redirect, url_for, flash, request, Response
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime
from app.models import db, utc_now, User, Supplier, Product, Inventory, PurchaseOrder, OrderLine, Notification
from app.forms import PurchaseOrderForm, OrderLineForm, InventoryUpdateForm, ReportForm
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
    monthly_spend = db.session.query(
        db.func.sum(PurchaseOrder.total_amount)
    ).filter(
        PurchaseOrder.status == 'Delivered',
        db.extract('month', PurchaseOrder.order_date) == utc_now().month
    ).scalar() or 0
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
    return render_template('manager/inventory.html', items=items)


@bp.route('/inventory/<int:item_id>/edit', methods=['GET', 'POST'])
@manager_required
def edit_inventory(item_id):
    item = Inventory.query.get_or_404(item_id)
    form = InventoryUpdateForm(obj=item)
    if form.validate_on_submit():
        item.qty_on_hand = form.qty_on_hand.data
        item.reorder_level = form.reorder_level.data
        item.last_restocked = utc_now()
        db.session.commit()
        flash('Inventory updated.', 'success')
        return redirect(url_for('manager.inventory'))
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
    form.product_id.choices = [(p.id, f'{p.name} — R{p.unit_cost}/{p.unit_of_measure}')
                                for p in products]
    if form.validate_on_submit() and order.status == 'Pending':
        product = db.session.get(Product, form.product_id.data)
        line = OrderLine(
            order_id=order.id,
            product_id=product.id,
            quantity=form.quantity.data,
            agreed_unit_cost=product.unit_cost
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
    line = OrderLine.query.get_or_404(line_id)
    db.session.delete(line)
    order = db.session.get(PurchaseOrder, order_id)
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
        start = datetime.combine(form.start_date.data, datetime.min.time())
        end = datetime.combine(form.end_date.data, datetime.max.time())
        delivered_orders = PurchaseOrder.query.filter(
            PurchaseOrder.status == 'Delivered',
            PurchaseOrder.order_date >= start,
            PurchaseOrder.order_date <= end
        ).all()
        total_cogs = sum(o.total_amount for o in delivered_orders)
        by_supplier = {}
        for o in delivered_orders:
            name = o.supplier.company_name
            by_supplier[name] = by_supplier.get(name, 0) + o.total_amount
        report_data = {
            'start': form.start_date.data,
            'end': form.end_date.data,
            'total_cogs': total_cogs,
            'order_count': len(delivered_orders),
            'by_supplier': by_supplier,
            'orders': delivered_orders
        }
    return render_template('manager/reports.html', form=form, report_data=report_data)


@bp.route('/reports/export_csv')
@manager_required
def export_csv():
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    try:
        start = datetime.strptime(start_str, '%Y-%m-%d')
        end = datetime.strptime(end_str, '%Y-%m-%d')
    except (TypeError, ValueError):
        flash('Invalid date range for export.', 'danger')
        return redirect(url_for('manager.reports'))
    orders = PurchaseOrder.query.filter(
        PurchaseOrder.status == 'Delivered',
        PurchaseOrder.order_date >= start,
        PurchaseOrder.order_date <= end
    ).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Order #', 'Supplier', 'Order Date', 'Delivery Date', 'Total (R)'])
    for o in orders:
        writer.writerow([o.id, o.supplier.company_name,
                         o.order_date.strftime('%Y-%m-%d'),
                         o.delivery_date.strftime('%Y-%m-%d') if o.delivery_date else '',
                         f'{o.total_amount:.2f}'])
    output.seek(0)
    return Response(output, mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment;filename=bigjos_report.csv'})


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
