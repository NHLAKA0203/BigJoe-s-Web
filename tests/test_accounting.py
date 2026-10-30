"""Run from the project root:  python -m unittest discover tests"""
import unittest
from datetime import datetime, timedelta

from flask import g

from app import create_app
from app import accounting as acc
from app.models import db, User, Supplier, Product, Inventory, InventoryBatch, PurchaseOrder, \
    OrderLine, ZERO_VAT_RATE
from config import Config


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False


class AccountingTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.ctx = self.app.app_context()
        self.ctx.push()
        acc.prepare_database()

        self.manager = User(name='Manager', email='m@test.co.za', role='manager')
        self.manager.set_password('secret123')
        self.sup_user = User(name='Supplier', email='s@test.co.za', role='supplier')
        self.sup_user.set_password('secret123')
        db.session.add_all([self.manager, self.sup_user])
        db.session.flush()
        self.supplier = Supplier(user_id=self.sup_user.id, company_name='Acme')
        db.session.add(self.supplier)
        db.session.flush()
        self.lettuce = self.make_product('Lettuce', 12.00, 5, ZERO_VAT_RATE)
        self.beef = self.make_product('Beef', 100.00, 4)
        db.session.commit()
        self.t0 = datetime(2026, 3, 1, 9)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def make_product(self, name, cost, shelf_life, vat_rate=0.15):
        product = Product(supplier_id=self.supplier.id, name=name, unit_cost=cost, category='Food',
                          shelf_life_days=shelf_life, vat_rate=vat_rate)
        db.session.add(product)
        db.session.flush()
        db.session.add(Inventory(product_id=product.id, qty_on_hand=0, reorder_level=1))
        db.session.flush()
        return product

    def deliver(self, items, when):
        order = PurchaseOrder(manager_id=self.manager.id, supplier_id=self.supplier.id,
                              status='Dispatched', order_date=when)
        db.session.add(order)
        db.session.flush()
        for product, qty, cost in items:
            db.session.add(OrderLine(order_id=order.id, product_id=product.id, quantity=qty,
                                     agreed_unit_cost=cost, vat_rate=product.vat_rate))
        db.session.flush()
        acc.receive_order(order, when=when)
        db.session.commit()
        return order

    def balance(self, code):
        return acc._movement(code)


class PurchaseTests(AccountingTestCase):
    def test_delivery_posts_inventory_vat_and_payables(self):
        order = self.deliver([(self.beef, 10, 100.00)], self.t0)
        self.assertEqual(self.balance(acc.INVENTORY), 1000.00)
        self.assertEqual(self.balance(acc.VAT_INPUT), 150.00)
        self.assertEqual(self.balance(acc.TRADE_PAYABLES), -1150.00)
        self.assertEqual(order.gross_amount, 1150.00)

    def test_vat_rounds_half_cents_up(self):
        order = self.deliver([(self.beef, 3, 3.50)], self.t0)
        self.assertEqual(order.vat_amount, 1.58)
        self.assertEqual(order.gross_amount, 12.08)

    def test_zero_rated_goods_carry_no_vat(self):
        self.deliver([(self.lettuce, 10, 12.00)], self.t0)
        self.assertEqual(self.balance(acc.INVENTORY), 120.00)
        self.assertEqual(self.balance(acc.VAT_INPUT), 0)
        self.assertEqual(self.balance(acc.TRADE_PAYABLES), -120.00)

    def test_order_cannot_be_received_twice(self):
        order = self.deliver([(self.beef, 1, 100.00)], self.t0)
        with self.assertRaises(acc.AccountingError):
            acc.receive_order(order)
        self.assertEqual(self.beef.inventory.qty_on_hand, 1)

    def test_payment_clears_payable_once(self):
        order = self.deliver([(self.beef, 10, 100.00)], self.t0)
        acc.pay_order(order, when=self.t0)
        db.session.commit()
        self.assertEqual(self.balance(acc.TRADE_PAYABLES), 0)
        self.assertEqual(self.balance(acc.BANK), -1150.00)
        self.assertEqual(acc.open_payables(), [])
        with self.assertRaises(acc.AccountingError):
            acc.pay_order(order)

    def test_undelivered_order_cannot_be_paid(self):
        order = PurchaseOrder(manager_id=self.manager.id, supplier_id=self.supplier.id,
                              status='Confirmed')
        db.session.add(order)
        db.session.flush()
        with self.assertRaises(acc.AccountingError):
            acc.pay_order(order)


class FifoTests(AccountingTestCase):
    def test_usage_is_charged_at_oldest_cost_first(self):
        self.deliver([(self.beef, 10, 100.00)], self.t0)
        self.deliver([(self.beef, 10, 130.00)], self.t0 + timedelta(days=1))
        cost = acc.record_usage(self.beef.inventory, 12, when=self.t0 + timedelta(days=2))
        db.session.commit()
        self.assertEqual(cost, 10 * 100.00 + 2 * 130.00)
        self.assertEqual(self.beef.inventory.qty_on_hand, 8)
        self.assertEqual(self.beef.inventory.carrying_value, 8 * 130.00)

    def test_expired_stock_cannot_be_used(self):
        self.deliver([(self.lettuce, 10, 12.00)], self.t0)
        with self.assertRaises(acc.AccountingError):
            acc.record_usage(self.lettuce.inventory, 1, when=self.t0 + timedelta(days=6))

    def test_rounding_never_strands_cents(self):
        self.deliver([(self.lettuce, 3, 3.33)], self.t0)
        for _ in range(3):
            acc.record_usage(self.lettuce.inventory, 1, when=self.t0)
        db.session.commit()
        self.assertEqual(self.lettuce.inventory.carrying_value, 0)
        self.assertEqual(self.balance(acc.INVENTORY), 0)
        self.assertEqual(self.balance(acc.COST_OF_SALES), 9.99)


class WriteDownTests(AccountingTestCase):
    def test_spoiled_stock_is_removed_and_expensed(self):
        self.deliver([(self.lettuce, 10, 12.00)], self.t0)
        batch = self.lettuce.inventory.open_batches[0]
        loss = acc.write_down_batch(batch, 4, 0, 'Spoiled', when=self.t0)
        db.session.commit()
        self.assertEqual(loss, 48.00)
        self.assertEqual(self.lettuce.inventory.qty_on_hand, 6)
        self.assertEqual(self.balance(acc.WRITE_DOWNS), 48.00)
        self.assertEqual(self.balance(acc.INVENTORY), 72.00)

    def test_partial_nrv_write_down_keeps_quantity_and_splits_batch(self):
        self.deliver([(self.lettuce, 10, 12.00)], self.t0)
        batch = self.lettuce.inventory.open_batches[0]
        loss = acc.write_down_batch(batch, 4, 5.00, 'Wilting', when=self.t0)
        db.session.commit()
        self.assertEqual(loss, 28.00)
        self.assertEqual(self.lettuce.inventory.qty_on_hand, 10)
        self.assertEqual(self.lettuce.inventory.carrying_value, 6 * 12.00 + 4 * 5.00)
        self.assertEqual(len(self.lettuce.inventory.open_batches), 2)

    def test_nrv_above_cost_is_refused(self):
        self.deliver([(self.lettuce, 10, 12.00)], self.t0)
        batch = self.lettuce.inventory.open_batches[0]
        with self.assertRaises(acc.AccountingError):
            acc.write_down_batch(batch, 1, 15.00, 'Not impaired', when=self.t0)

    def test_expired_batches_write_off_to_nil(self):
        self.deliver([(self.lettuce, 10, 12.00)], self.t0)
        count, total = acc.write_off_expired(when=self.t0 + timedelta(days=6))
        db.session.commit()
        self.assertEqual((count, total), (1, 120.00))
        self.assertEqual(self.lettuce.inventory.qty_on_hand, 0)
        self.assertEqual(self.balance(acc.INVENTORY), 0)


class StockCountTests(AccountingTestCase):
    def test_shortfall_and_surplus_post_to_cost_of_sales(self):
        self.deliver([(self.lettuce, 10, 12.00)], self.t0)
        self.assertEqual(acc.apply_stock_count(self.lettuce.inventory, 8, when=self.t0), -2)
        self.assertEqual(self.balance(acc.COST_OF_SALES), 24.00)
        self.assertEqual(acc.apply_stock_count(self.lettuce.inventory, 9, when=self.t0), 1)
        db.session.commit()
        self.assertEqual(self.balance(acc.COST_OF_SALES), 12.00)
        self.assertEqual(self.lettuce.inventory.qty_on_hand, 9)
        self.assertEqual(self.balance(acc.INVENTORY), 108.00)


class StatementTests(AccountingTestCase):
    def scenario(self):
        """Opening R120; purchases R1000; usage R300 and a write-down of R48 in March."""
        self.deliver([(self.lettuce, 10, 12.00)], datetime(2026, 2, 27))
        lettuce_batch = self.lettuce.inventory.open_batches[0]
        self.deliver([(self.beef, 10, 100.00)], datetime(2026, 3, 2))
        acc.record_usage(self.beef.inventory, 3, when=datetime(2026, 3, 3))
        acc.write_down_batch(lettuce_batch, 4, 0, 'Spoiled', when=datetime(2026, 3, 4))
        db.session.commit()

    def test_cost_of_sales_is_opening_plus_purchases_less_closing(self):
        self.scenario()
        s = acc.cost_of_sales_statement(*acc.period_bounds(datetime(2026, 3, 1).date(),
                                                           datetime(2026, 3, 31).date()))
        self.assertEqual(s['opening'], 120.00)
        self.assertEqual(s['purchases'], 1000.00)
        self.assertEqual(s['closing'], 772.00)
        self.assertEqual(s['cost_of_sales'], 348.00)
        self.assertEqual(s['used'], 300.00)
        self.assertEqual(s['write_downs'], 48.00)
        self.assertTrue(s['reconciles'])

    def test_purchases_alone_are_not_cost_of_sales(self):
        self.deliver([(self.beef, 10, 100.00)], datetime(2026, 3, 2))
        s = acc.cost_of_sales_statement(*acc.period_bounds(datetime(2026, 3, 1).date(),
                                                           datetime(2026, 3, 31).date()))
        self.assertEqual(s['purchases'], 1000.00)
        self.assertEqual(s['cost_of_sales'], 0)

    def test_consecutive_periods_roll_forward(self):
        self.scenario()
        feb = acc.cost_of_sales_statement(*acc.period_bounds(datetime(2026, 2, 1).date(),
                                                             datetime(2026, 2, 28).date()))
        mar = acc.cost_of_sales_statement(*acc.period_bounds(datetime(2026, 3, 1).date(),
                                                             datetime(2026, 3, 31).date()))
        self.assertEqual(feb['closing'], mar['opening'])

    def test_trial_balance_and_control_checks_agree(self):
        self.scenario()
        order = self.deliver([(self.beef, 2, 99.99)], datetime(2026, 3, 5))
        acc.pay_order(order, when=datetime(2026, 3, 6))
        db.session.commit()
        rows = acc.trial_balance()
        self.assertEqual(round(sum(r['debit'] for r in rows), 2),
                         round(sum(r['credit'] for r in rows), 2))
        self.assertTrue(all(c['ok'] for c in acc.ledger_checks()), acc.ledger_checks())

    def test_unbalanced_entry_is_refused(self):
        with self.assertRaises(acc.AccountingError):
            acc.post_entry(self.t0, 'usage', 'x', 'x', [(acc.INVENTORY, 10, 0), (acc.BANK, 0, 9)])


class OpeningBalanceTests(AccountingTestCase):
    def test_opening_stock_is_capitalised_once(self):
        self.lettuce.inventory.qty_on_hand = 20
        db.session.flush()
        acc.capitalise_opening_stock(self.t0)
        acc.capitalise_opening_stock(self.t0)
        db.session.commit()
        self.assertEqual(self.balance(acc.INVENTORY), 240.00)
        self.assertEqual(self.balance(acc.CAPITAL), -240.00)
        self.assertEqual(InventoryBatch.query.count(), 1)


class WorkflowTests(AccountingTestCase):
    """The whole flow through the real routes, as a manager and supplier would use it."""

    def setUp(self):
        super().setUp()
        # setUp's app context makes requests share g, where Flask-Login caches the user
        self.app.before_request(self.forget_cached_user)

    @staticmethod
    def forget_cached_user():
        g.pop('_login_user', None)

    def login(self, email):
        client = self.app.test_client()
        response = client.post('/auth/login', data={'email': email, 'password': 'secret123'})
        self.assertEqual(response.status_code, 302)
        return client

    def test_order_to_report_flow(self):
        manager = self.login('m@test.co.za')
        supplier = self.login('s@test.co.za')

        manager.post('/manager/orders/new', data={'supplier_id': self.supplier.id})
        order = PurchaseOrder.query.one()
        url = f'/manager/orders/{order.id}'
        manager.post(url, data={'product_id': self.beef.id, 'quantity': 10})
        manager.post(url, data={'product_id': self.lettuce.id, 'quantity': 5})
        manager.post(f'{url}/submit')

        supplier.post(f'/supplier/orders/{order.id}/confirm', data={'delivery_date': '2026-03-02'})
        supplier.post(f'/supplier/orders/{order.id}/update_status', data={'status': 'Dispatched'})
        supplier.post(f'/supplier/orders/{order.id}/update_status', data={'status': 'Delivered'})
        # A repeated click must not double the stock or the liability
        supplier.post(f'/supplier/orders/{order.id}/update_status', data={'status': 'Delivered'})

        db.session.expire_all()
        order = PurchaseOrder.query.one()
        self.assertEqual(order.status, 'Delivered')
        self.assertEqual(order.gross_amount, 1210.00)
        self.assertEqual(self.beef.inventory.qty_on_hand, 10)
        self.assertEqual(self.balance(acc.TRADE_PAYABLES), -1210.00)

        inv_id = self.beef.inventory.id
        manager.post(f'/manager/inventory/{inv_id}/usage', data={'quantity': 2})
        batch = self.lettuce.inventory.open_batches[0]
        lettuce_id = self.lettuce.inventory.id
        manager.post(f'/manager/inventory/{lettuce_id}/write_down',
                     data={'batch_id': batch.id, 'quantity': 5, 'nrv_per_unit': 0, 'reason': 'Spoiled'})
        manager.post(f'/manager/inventory/{inv_id}/edit',
                     data={'qty_on_hand': 7, 'reorder_level': 2})
        manager.post(f'/manager/payables/{order.id}/pay', data={'method': 'EFT'})

        db.session.expire_all()
        self.assertEqual(self.balance(acc.TRADE_PAYABLES), 0)
        self.assertEqual(self.balance(acc.INVENTORY), 700.00)
        self.assertEqual(self.balance(acc.COST_OF_SALES), 300.00)
        self.assertEqual(self.balance(acc.WRITE_DOWNS), 60.00)
        self.assertTrue(all(c['ok'] for c in acc.ledger_checks()))

        today = order.received_at.strftime('%Y-%m-%d')
        report = manager.post('/manager/reports', data={'start_date': today, 'end_date': today})
        self.assertEqual(report.status_code, 200)
        text = report.get_data(as_text=True)
        self.assertIn('R 360.00', text)
        self.assertIn('Agrees with statement', text)

        export = manager.get(f'/manager/reports/export_csv?start={today}&end={today}')
        csv_text = export.get_data(as_text=True)
        self.assertIn('Cost of sales,360.00', csv_text)
        self.assertIn('1060.00,150.00,1210.00,Yes', csv_text)

    def test_every_manager_page_renders(self):
        self.deliver([(self.beef, 10, 100.00), (self.lettuce, 5, 12.00)], self.t0)
        manager = self.login('m@test.co.za')
        inv_id = self.beef.inventory.id
        for path in ['dashboard', 'inventory', f'inventory/{inv_id}', f'inventory/{inv_id}/edit',
                     'orders', 'orders/1', 'reports', 'payables', 'journal']:
            response = manager.get(f'/manager/{path}')
            self.assertEqual(response.status_code, 200, path)

    def test_delivered_order_cannot_be_rewound(self):
        order = self.deliver([(self.beef, 1, 100.00)], self.t0)
        manager = self.login('m@test.co.za')
        supplier = self.login('s@test.co.za')
        manager.post(f'/manager/orders/{order.id}/submit')
        supplier.post(f'/supplier/orders/{order.id}/reject')
        db.session.expire_all()
        self.assertEqual(db.session.get(PurchaseOrder, order.id).status, 'Delivered')

    def test_product_with_history_is_retired_not_deleted(self):
        self.deliver([(self.beef, 1, 100.00)], self.t0)
        supplier = self.login('s@test.co.za')
        supplier.post(f'/supplier/products/{self.beef.id}/delete')
        db.session.expire_all()
        beef = Product.query.filter_by(name='Beef').one()
        self.assertFalse(beef.available)


if __name__ == '__main__':
    unittest.main()
