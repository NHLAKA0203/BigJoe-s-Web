from datetime import UTC, datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


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

    @property
    def is_low(self):
        return self.qty_on_hand <= self.reorder_level

    def __repr__(self):
        return f'<Inventory product_id={self.product_id} qty={self.qty_on_hand}>'


class PurchaseOrder(db.Model):
    __tablename__ = 'purchase_order'
    id = db.Column(db.Integer, primary_key=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    order_date = db.Column(db.DateTime, default=utc_now)
    delivery_date = db.Column(db.DateTime)
    status = db.Column(db.String(30), default='Pending')
    # Pending / Confirmed / Dispatched / Delivered / Rejected
    total_amount = db.Column(db.Float, default=0)
    notes = db.Column(db.Text)

    manager = db.relationship('User', backref='orders_placed', foreign_keys=[manager_id])
    lines = db.relationship('OrderLine', backref='order', lazy='dynamic', cascade='all, delete-orphan')
    payment = db.relationship('Payment', backref='order', uselist=False)

    def recalculate_total(self):
        self.total_amount = sum(l.line_total for l in self.lines)

    def __repr__(self):
        return f'<PurchaseOrder #{self.id} {self.status}>'


class OrderLine(db.Model):
    __tablename__ = 'order_line'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('purchase_order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    agreed_unit_cost = db.Column(db.Float, nullable=False)

    @property
    def line_total(self):
        return self.quantity * self.agreed_unit_cost

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
