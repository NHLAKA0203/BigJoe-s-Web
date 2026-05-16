"""Run this once to populate the database with sample data.
   python seed.py
"""
from app import create_app
from app.models import db, User, Supplier, Product, Inventory

app = create_app()

with app.app_context():
    db.create_all()

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
            Product(supplier_id=s1.id, name='Potatoes', category='Vegetables', unit_cost=8.50, unit_of_measure='kg', shelf_life_days=14),
            Product(supplier_id=s1.id, name='Onions', category='Vegetables', unit_cost=6.00, unit_of_measure='kg', shelf_life_days=21),
            Product(supplier_id=s1.id, name='Lettuce', category='Vegetables', unit_cost=12.00, unit_of_measure='unit', shelf_life_days=5),
            Product(supplier_id=s1.id, name='Tomatoes', category='Vegetables', unit_cost=14.00, unit_of_measure='kg', shelf_life_days=7),
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
            Product(supplier_id=s2.id, name='Potatoes', category='Vegetables', unit_cost=7.80, unit_of_measure='kg', shelf_life_days=14),
            Product(supplier_id=s2.id, name='Garlic', category='Vegetables', unit_cost=45.00, unit_of_measure='kg', shelf_life_days=30),
            Product(supplier_id=s2.id, name='Shawarma Bread', category='Bread', unit_cost=3.50, unit_of_measure='unit', shelf_life_days=3),
        ]
        for p in products2:
            db.session.add(p)
            db.session.flush()
            inv = Inventory(product_id=p.id, qty_on_hand=3, reorder_level=10)  # Low stock!
            db.session.add(inv)

    db.session.commit()
    print("✅ Database seeded successfully.")
    print()
    print("Login credentials:")
    print("  Manager  — manager@bigjos.co.za  / manager123")
    print("  Supplier — freshproduce@supplier.co.za / supplier123")
    print("  Supplier — berea@supplier.co.za  / supplier123")
