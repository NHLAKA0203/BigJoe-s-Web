from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

STANDARD_VAT_RATE = 0.15
ZERO_VAT_RATE = 0.0


def utc_now():
    return datetime.now(UTC).replace(tzinfo=None)


class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # manager / supplier / admin
    phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=utc_now)

    supplier_profile = db.relationship('Supplier', backref='user', uselist=False)
    notifications = db.relationship('Notification', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.email}>'


class Supplier(db.Model):
    __tablename__ = 'supplier'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    company_name = db.Column(db.String(120), nullable=False)
    region = db.Column(db.String(100))
    rating = db.Column(db.Float, default=3.0)
    bank_details = db.Column(db.String(200))

    products = db.relationship('Product', backref='supplier', lazy='dynamic')
    orders = db.relationship('PurchaseOrder', backref='supplier', lazy='dynamic')

    def __repr__(self):
        return f'<Supplier {self.company_name}>'


class Product(db.Model):
    __tablename__ = 'product'
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(80))
    unit_cost = db.Column(db.Float, nullable=False)
    unit_of_measure = db.Column(db.String(20), default='kg')
    shelf_life_days = db.Column(db.Integer, default=7)
    available = db.Column(db.Boolean, default=True)
    vat_rate = db.Column(db.Float, default=STANDARD_VAT_RATE)

    inventory = db.relationship('Inventory', backref='product', uselist=False)
    order_lines = db.relationship('OrderLine', backref='product', lazy='dynamic')

    def __repr__(self):
        return f'<Product {self.name}>'


class Inventory(db.Model):
    __tablename__ = 'inventory'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), unique=True)
    qty_on_hand = db.Column(db.Float, default=0)
    reorder_level = db.Column(db.Float, default=5)
    last_restocked = db.Column(db.DateTime)

    batches = db.relationship('InventoryBatch', backref='inventory', lazy='dynamic')

    @property
    def is_low(self):
        return self.qty_on_hand <= self.reorder_level

    @property
    def open_batches(self):
        # Oldest first: this is the FIFO cost flow
        return self.batches.filter(InventoryBatch.qty_remaining > 0).order_by(
            InventoryBatch.received_at, InventoryBatch.id).all()

    @property
    def carrying_value(self):
        return round(sum(b.carrying_value for b in self.open_batches), 2)

    @property
    def expired_batches(self):
        return [b for b in self.open_batches if b.is_expired()]

    def __repr__(self):
        return f'<Inventory product_id={self.product_id} qty={self.qty_on_hand}>'


class InventoryBatch(db.Model):
    __tablename__ = 'inventory_batch'
    id = db.Column(db.Integer, primary_key=True)
    inventory_id = db.Column(db.Integer, db.ForeignKey('inventory.id'), nullable=False)
    order_line_id = db.Column(db.Integer, db.ForeignKey('order_line.id'))
    received_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    expiry_date = db.Column(db.DateTime)
    qty_received = db.Column(db.Float, nullable=False)
    qty_remaining = db.Column(db.Float, nullable=False)
    unit_cost = db.Column(db.Float, nullable=False)  # excl. recoverable VAT (IAS 2.11)
    carrying_value = db.Column(db.Float, nullable=False)  # lower of cost and NRV (IAS 2.9)

    def is_expired(self, as_of=None):
        if not self.expiry_date:
            return False
        return self.expiry_date.date() < (as_of or utc_now()).date()

    @property
    def carrying_unit_cost(self):
        return self.carrying_value / self.qty_remaining if self.qty_remaining else 0

    @property
    def is_written_down(self):
        # A cent of tolerance: part-used batches carry rounding differences
        return self.carrying_value < round(self.qty_remaining * self.unit_cost, 2) - 0.01

    def __repr__(self):
        return f'<InventoryBatch inventory={self.inventory_id} qty={self.qty_remaining}>'


class PurchaseOrder(db.Model):
    __tablename__ = 'purchase_order'
    id = db.Column(db.Integer, primary_key=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    order_date = db.Column(db.DateTime, default=utc_now)
    delivery_date = db.Column(db.DateTime)
    status = db.Column(db.String(30), default='Pending')
    # Pending / Confirmed / Dispatched / Delivered / Rejected
    total_amount = db.Column(db.Float, default=0)  # excl. VAT
    vat_amount = db.Column(db.Float, default=0)
    received_at = db.Column(db.DateTime)  # actual delivery; delivery_date is the supplier's estimate
    notes = db.Column(db.Text)

    manager = db.relationship('User', backref='orders_placed', foreign_keys=[manager_id])
    lines = db.relationship('OrderLine', backref='order', lazy='dynamic', cascade='all, delete-orphan')
    payment = db.relationship('Payment', backref='order', uselist=False)

    def recalculate_total(self):
        lines = self.lines.all()
        self.total_amount = round(sum(l.line_net for l in lines), 2)
        self.vat_amount = round(sum(l.line_vat for l in lines), 2)

    @property
    def gross_amount(self):
        return round((self.total_amount or 0) + (self.vat_amount or 0), 2)

    @property
    def is_paid(self):
        return self.payment is not None and self.payment.status == 'Paid'

    def __repr__(self):
        return f'<PurchaseOrder #{self.id} {self.status}>'


class OrderLine(db.Model):
    __tablename__ = 'order_line'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('purchase_order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    agreed_unit_cost = db.Column(db.Float, nullable=False)
    vat_rate = db.Column(db.Float, default=STANDARD_VAT_RATE)

    @property
    def line_total(self):
        return self.quantity * self.agreed_unit_cost

    @property
    def line_net(self):
        return round(self.line_total, 2)

    @property
    def line_vat(self):
        # Decimal, because 10.50 * 0.15 as a float rounds down to 1.57 rather than 1.58
        vat = Decimal(str(self.line_net)) * Decimal(str(self.vat_rate or 0))
        return float(vat.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

    def __repr__(self):
        return f'<OrderLine order={self.order_id} product={self.product_id}>'


class Payment(db.Model):
    __tablename__ = 'payment'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('purchase_order.id'), unique=True)
    amount = db.Column(db.Float, nullable=False)
    method = db.Column(db.String(50), default='EFT')
    payment_date = db.Column(db.DateTime, default=utc_now)
    status = db.Column(db.String(30), default='Pending')

    def __repr__(self):
        return f'<Payment order={self.order_id} amount={self.amount}>'


class JournalEntry(db.Model):
    __tablename__ = 'journal_entry'
    id = db.Column(db.Integer, primary_key=True)
    entry_date = db.Column(db.DateTime, default=utc_now, nullable=False)
    source = db.Column(db.String(30), nullable=False)
    # opening / purchase / payment / usage / write_down / stock_count
    reference = db.Column(db.String(60))
    memo = db.Column(db.String(255))

    lines = db.relationship('JournalLine', backref='entry', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<JournalEntry #{self.id} {self.source}>'


class JournalLine(db.Model):
    __tablename__ = 'journal_line'
    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey('journal_entry.id'), nullable=False)
    account_code = db.Column(db.String(10), nullable=False)
    debit = db.Column(db.Float, default=0, nullable=False)
    credit = db.Column(db.Float, default=0, nullable=False)

    def __repr__(self):
        return f'<JournalLine {self.account_code} Dr {self.debit} Cr {self.credit}>'


class Notification(db.Model):
    __tablename__ = 'notification'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(30), default='info')  # info / warning / success / danger
    is_read = db.Column(db.Boolean, default=False)
    sent_at = db.Column(db.DateTime, default=utc_now)

    def __repr__(self):
        return f'<Notification user={self.user_id} type={self.type}>'
