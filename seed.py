"""Run this once to populate the database with sample data.
   python seed.py
"""
from datetime import timedelta
from app import create_app
from app.accounting import prepare_database, capitalise_opening_stock, receive_order, pay_order, \
    record_usage, write_down_batch
from app.models import db, utc_now, User, Supplier, Product, Inventory, PurchaseOrder, OrderLine, \
    ZERO_VAT_RATE

app = create_app()


def stock_of(supplier, name):
    product = Product.query.filter_by(supplier_id=supplier.id, name=name).first()
    return product.inventory


def demo_order(manager, supplier, items, ordered, received):
    order = PurchaseOrder(manager_id=manager.id, supplier_id=supplier.id, status='Dispatched',
                          order_date=ordered, delivery_date=received)
    db.session.add(order)
    db.session.flush()
    for name, qty in items:
        product = Product.query.filter_by(supplier_id=supplier.id, name=name).first()
        db.session.add(OrderLine(order_id=order.id, product_id=product.id, quantity=qty,
                                 agreed_unit_cost=product.unit_cost, vat_rate=product.vat_rate))
    db.session.flush()
    receive_order(order, when=received)
    return order


def seed_demo_transactions(start):
    """Two weeks of trading, so the reports show real figures straight after seeding."""
    capitalise_opening_stock(start)
    manager = User.query.filter_by(email='manager@bigjos.co.za').first()
    fresh = Supplier.query.filter_by(company_name='KZN Fresh Produce').first()
    berea = Supplier.query.filter_by(company_name='Berea Wholesale').first()

    def day(n):
        return start + timedelta(days=n)

    # Kitchen usage, then the rest of the opening lettuce spoils
    record_usage(stock_of(fresh, 'Lettuce'), 12, when=day(2))
    record_usage(stock_of(berea, 'Beef Strips'), 3, when=day(2))
    record_usage(stock_of(fresh, 'Potatoes'), 8, when=day(3))
    record_usage(stock_of(fresh, 'Onions'), 5, when=day(3))
    lettuce = stock_of(fresh, 'Lettuce').open_batches[0]
    write_down_batch(lettuce, lettuce.qty_remaining, 0, 'Lettuce spoiled in cold room', when=day(4))

    # Tomatoes near expiry are only worth R6/kg: reduced to NRV but still on hand.
    # They and the opening bread are left expired, to demonstrate the write-off button.
    tomatoes = stock_of(fresh, 'Tomatoes').open_batches[0]
    write_down_batch(tomatoes, 10, 6.00, 'Overripe tomatoes: NRV below cost', when=day(5))

    # Zero-rated produce, received and paid
    produce = demo_order(manager, fresh, [('Lettuce', 20), ('Tomatoes', 15), ('Potatoes', 30)],
                         ordered=day(9), received=day(10))
    pay_order(produce, when=day(13))

    # Standard-rated goods, received and still owing
    demo_order(manager, berea, [('Beef Strips', 10), ('Shawarma Bread', 50), ('Takeaway Boxes', 100)],
               ordered=day(11), received=day(12))
    record_usage(stock_of(berea, 'Beef Strips'), 4, when=day(13))
    record_usage(stock_of(berea, 'Shawarma Bread'), 30, when=day(13))
    record_usage(stock_of(fresh, 'Lettuce'), 6, when=day(13))


with app.app_context():
    prepare_database()

    # Admin / Manager
    if not User.query.filter_by(email='manager@bigjos.co.za').first():
        mgr = User(name='Big Jo Manager', email='manager@bigjos.co.za', role='manager', phone='031 000 0001')
        mgr.set_password('manager123')
        db.session.add(mgr)

    # Supplier 1
    if not User.query.filter_by(email='freshproduce@supplier.co.za').first():
        u1 = User(name='Sipho Nkosi', email='freshproduce@supplier.co.za', role='supplier', phone='031 000 0002')
        u1.set_password('supplier123')
        db.session.add(u1)
        db.session.flush()
        s1 = Supplier(user_id=u1.id, company_name='KZN Fresh Produce', region='KwaZulu-Natal', rating=4.5)
        db.session.add(s1)
        db.session.flush()
        products1 = [
            Product(supplier_id=s1.id, name='Potatoes', category='Vegetables', unit_cost=8.50, unit_of_measure='kg', shelf_life_days=14, vat_rate=ZERO_VAT_RATE),
            Product(supplier_id=s1.id, name='Onions', category='Vegetables', unit_cost=6.00, unit_of_measure='kg', shelf_life_days=21, vat_rate=ZERO_VAT_RATE),
            Product(supplier_id=s1.id, name='Lettuce', category='Vegetables', unit_cost=12.00, unit_of_measure='unit', shelf_life_days=5, vat_rate=ZERO_VAT_RATE),
            Product(supplier_id=s1.id, name='Tomatoes', category='Vegetables', unit_cost=14.00, unit_of_measure='kg', shelf_life_days=7, vat_rate=ZERO_VAT_RATE),
        ]
        for p in products1:
            db.session.add(p)
            db.session.flush()
            inv = Inventory(product_id=p.id, qty_on_hand=20, reorder_level=5)
            db.session.add(inv)

    # Supplier 2
    if not User.query.filter_by(email='berea@supplier.co.za').first():
        u2 = User(name='Fatima Patel', email='berea@supplier.co.za', role='supplier', phone='031 000 0003')
        u2.set_password('supplier123')
        db.session.add(u2)
        db.session.flush()
        s2 = Supplier(user_id=u2.id, company_name='Berea Wholesale', region='Durban CBD', rating=3.8)
        db.session.add(s2)
        db.session.flush()
        products2 = [
            Product(supplier_id=s2.id, name='Potatoes', category='Vegetables', unit_cost=7.80, unit_of_measure='kg', shelf_life_days=14, vat_rate=ZERO_VAT_RATE),
            Product(supplier_id=s2.id, name='Garlic', category='Vegetables', unit_cost=45.00, unit_of_measure='kg', shelf_life_days=30, vat_rate=ZERO_VAT_RATE),
            Product(supplier_id=s2.id, name='Shawarma Bread', category='Bread', unit_cost=3.50, unit_of_measure='unit', shelf_life_days=3),
            Product(supplier_id=s2.id, name='Beef Strips', category='Meat', unit_cost=120.00, unit_of_measure='kg', shelf_life_days=4),
            Product(supplier_id=s2.id, name='Takeaway Boxes', category='Packaging', unit_cost=2.50, unit_of_measure='unit', shelf_life_days=365),
        ]
        for p in products2:
            db.session.add(p)
            db.session.flush()
            inv = Inventory(product_id=p.id, qty_on_hand=3, reorder_level=10)  # Low stock!
            db.session.add(inv)

    db.session.flush()

    # Only a brand-new database gets the demo trading history
    if PurchaseOrder.query.count() == 0:
        seed_demo_transactions(utc_now() - timedelta(days=14))
    else:
        capitalise_opening_stock()

    db.session.commit()
    print("Database seeded successfully.")
    print()
    print("Login credentials:")
    print("  Manager  - manager@bigjos.co.za  / manager123")
    print("  Supplier - freshproduce@supplier.co.za / supplier123")
    print("  Supplier - berea@supplier.co.za  / supplier123")
