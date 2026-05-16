from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime
from app.models import db, Supplier, Product, Inventory, PurchaseOrder, Notification
from app.models import utc_now
from app.forms import ProductForm, OrderConfirmForm

bp = Blueprint('supplier', __name__, url_prefix='/supplier')


def supplier_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'supplier':
            flash('Access restricted to suppliers.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return login_required(decorated)


def get_supplier():
    return Supplier.query.filter_by(user_id=current_user.id).first_or_404()


# ── Dashboard ─────────────────────────────────────────────────────────────────
@bp.route('/dashboard')
@supplier_required
def dashboard():
    supplier = get_supplier()
    pending = PurchaseOrder.query.filter_by(
        supplier_id=supplier.id, status='Submitted').count()
    confirmed = PurchaseOrder.query.filter_by(
        supplier_id=supplier.id, status='Confirmed').count()
    delivered = PurchaseOrder.query.filter_by(
        supplier_id=supplier.id, status='Delivered').count()
    recent_orders = PurchaseOrder.query.filter_by(
        supplier_id=supplier.id).order_by(
        PurchaseOrder.order_date.desc()).limit(5).all()
    notifications = Notification.query.filter_by(
        user_id=current_user.id, is_read=False).order_by(
        Notification.sent_at.desc()).limit(5).all()
    return render_template('supplier/dashboard.html',
                           supplier=supplier,
                           pending=pending,
                           confirmed=confirmed,
                           delivered=delivered,
                           recent_orders=recent_orders,
                           notifications=notifications)


# ── Products ──────────────────────────────────────────────────────────────────
@bp.route('/products')
@supplier_required
def products():
    supplier = get_supplier()
    products = Product.query.filter_by(supplier_id=supplier.id).all()
    return render_template('supplier/products.html', products=products)


@bp.route('/products/new', methods=['GET', 'POST'])
@supplier_required
def new_product():
    supplier = get_supplier()
    form = ProductForm()
    if form.validate_on_submit():
        product = Product(
            supplier_id=supplier.id,
            name=form.name.data,
            category=form.category.data,
            unit_cost=form.unit_cost.data,
            unit_of_measure=form.unit_of_measure.data,
            shelf_life_days=form.shelf_life_days.data,
            available=form.available.data
        )
        db.session.add(product)
        db.session.flush()
        inventory = Inventory(product_id=product.id, qty_on_hand=0, reorder_level=5)
        db.session.add(inventory)
        db.session.commit()
        flash(f'Product "{product.name}" added.', 'success')
        return redirect(url_for('supplier.products'))
    return render_template('supplier/product_form.html', form=form, title='New Product')


@bp.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@supplier_required
def edit_product(product_id):
    supplier = get_supplier()
    product = Product.query.filter_by(id=product_id, supplier_id=supplier.id).first_or_404()
    form = ProductForm(obj=product)
    if form.validate_on_submit():
        product.name = form.name.data
        product.category = form.category.data
        product.unit_cost = form.unit_cost.data
        product.unit_of_measure = form.unit_of_measure.data
        product.shelf_life_days = form.shelf_life_days.data
        product.available = form.available.data
        db.session.commit()
        flash('Product updated.', 'success')
        return redirect(url_for('supplier.products'))
    return render_template('supplier/product_form.html', form=form, title='Edit Product')


@bp.route('/products/<int:product_id>/delete', methods=['POST'])
@supplier_required
def delete_product(product_id):
    supplier = get_supplier()
    product = Product.query.filter_by(id=product_id, supplier_id=supplier.id).first_or_404()
    db.session.delete(product)
    db.session.commit()
    flash('Product removed.', 'info')
    return redirect(url_for('supplier.products'))


# ── Orders ─────────────────────────────────────────────────────────────────────
@bp.route('/orders')
@supplier_required
def orders():
    supplier = get_supplier()
    status_filter = request.args.get('status', '')
    query = PurchaseOrder.query.filter_by(supplier_id=supplier.id)
    if status_filter:
        query = query.filter_by(status=status_filter)
    orders = query.order_by(PurchaseOrder.order_date.desc()).all()
    return render_template('supplier/orders.html', orders=orders, status_filter=status_filter)


@bp.route('/orders/<int:order_id>', methods=['GET', 'POST'])
@supplier_required
def order_detail(order_id):
    supplier = get_supplier()
    order = PurchaseOrder.query.filter_by(
        id=order_id, supplier_id=supplier.id).first_or_404()
    form = OrderConfirmForm()
    return render_template('supplier/order_detail.html', order=order, form=form)


@bp.route('/orders/<int:order_id>/confirm', methods=['POST'])
@supplier_required
def confirm_order(order_id):
    supplier = get_supplier()
    order = PurchaseOrder.query.filter_by(
        id=order_id, supplier_id=supplier.id).first_or_404()
    form = OrderConfirmForm()
    if form.validate_on_submit():
        order.status = 'Confirmed'
        order.delivery_date = datetime.combine(
            form.delivery_date.data, datetime.min.time())
        db.session.commit()
        notif = Notification(
            user_id=order.manager_id,
            message=f'Order #{order.id} confirmed by {supplier.company_name}. '
                    f'Expected delivery: {form.delivery_date.data}.',
            type='success'
        )
        db.session.add(notif)
        db.session.commit()
        flash('Order confirmed.', 'success')
    return redirect(url_for('supplier.orders'))


@bp.route('/orders/<int:order_id>/reject', methods=['POST'])
@supplier_required
def reject_order(order_id):
    supplier = get_supplier()
    order = PurchaseOrder.query.filter_by(
        id=order_id, supplier_id=supplier.id).first_or_404()
    order.status = 'Rejected'
    db.session.commit()
    notif = Notification(
        user_id=order.manager_id,
        message=f'Order #{order.id} was rejected by {supplier.company_name}.',
        type='danger'
    )
    db.session.add(notif)
    db.session.commit()
    flash('Order rejected.', 'info')
    return redirect(url_for('supplier.orders'))


@bp.route('/orders/<int:order_id>/update_status', methods=['POST'])
@supplier_required
def update_status(order_id):
    supplier = get_supplier()
    order = PurchaseOrder.query.filter_by(
        id=order_id, supplier_id=supplier.id).first_or_404()
    new_status = request.form.get('status')
    valid = ['Confirmed', 'Dispatched', 'Delivered']
    if new_status in valid:
        order.status = new_status
        if new_status == 'Delivered':
            # Auto-update inventory
            for line in order.lines:
                inv = Inventory.query.filter_by(product_id=line.product_id).first()
                if inv:
                    inv.qty_on_hand += line.quantity
                    inv.last_restocked = utc_now()
            notif = Notification(
                user_id=order.manager_id,
                message=f'Order #{order.id} from {supplier.company_name} has been delivered. '
                        f'Inventory updated automatically.',
                type='success'
            )
            db.session.add(notif)
        db.session.commit()
        flash(f'Order status updated to {new_status}.', 'success')
    return redirect(url_for('supplier.orders'))
