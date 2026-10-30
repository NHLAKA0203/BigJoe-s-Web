# Big Jo's Supplier Management System

A Flask web application for Big Jo's Restaurant (Berea Centre) to manage suppliers, inventory, purchase orders, and financial reporting.

Built for DUT Financial Accounting 2 – Project Based Learning, 2026.

---

## Tech Stack

| Layer       | Technology           |
|-------------|----------------------|
| Frontend    | HTML, CSS, JavaScript |
| Backend     | Python Flask          |
| ORM         | Flask-SQLAlchemy      |
| Auth        | Flask-Login + Werkzeug password hashing |
| Forms       | Flask-WTF             |
| Database    | SQLite (dev) / PostgreSQL-ready |

---

## Setup Instructions

### 1. Clone / extract the project
```
cd bigjos_system
```

### 2. Create and activate a virtual environment
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the app
```bash
python run.py
```
The app will create the SQLite database automatically on first run. An existing database is upgraded in place, and its stock is capitalised at the current supplier cost as opening inventory.

### 5. Seed sample data
```bash
python seed.py
```

On a new database this also creates two weeks of sample trading, so the reports show figures straight away.

### 6. Open your browser
```
http://127.0.0.1:5000
```

### 7. Run the tests
```bash
python -m unittest discover tests
```

---

## Login Credentials (after seeding)

| Role     | Email                            | Password     |
|----------|----------------------------------|--------------|
| Manager  | manager@bigjos.co.za             | manager123   |
| Supplier | freshproduce@supplier.co.za      | supplier123  |
| Supplier | berea@supplier.co.za             | supplier123  |

---

## Pages

| URL                      | Description                          |
|--------------------------|--------------------------------------|
| `/`                      | Home / landing page                  |
| `/auth/login`            | Login                                |
| `/auth/register`         | Register (Manager or Supplier)       |
| `/manager/dashboard`     | Manager dashboard with KPIs          |
| `/manager/suppliers`     | Supplier directory + search          |
| `/manager/inventory`     | Inventory value, stock levels + alerts |
| `/manager/inventory/<id>` | FIFO batches, usage, NRV write-downs |
| `/manager/payables`      | Unpaid supplier invoices + payment   |
| `/manager/journal`       | General journal, trial balance, control checks |
| `/manager/orders`        | Purchase orders list                 |
| `/manager/orders/new`    | Create a new purchase order          |
| `/manager/reports`       | Financial reports + CSV export       |
| `/manager/notifications` | All notifications                    |
| `/supplier/dashboard`    | Supplier dashboard                   |
| `/supplier/products`     | Manage product catalogue             |
| `/supplier/orders`       | View and action incoming orders      |

---

## Features

- **Role-based authentication** (Manager / Supplier / Admin)
- **Supplier directory** with search and rating display
- **Inventory management** with automated low-stock highlighting and reorder alerts
- **Purchase order workflow**: Create → Submit → Confirm → Dispatch → Deliver
- **Automatic inventory update** when an order is marked Delivered
- **Notification system** — managers and suppliers get in-app alerts
- **Financial reporting** with an IAS 2 cost of sales statement, inventories note and CSV export
- **Double-entry ledger** — every stock movement and payment posts a balanced journal automatically
- **POPIA-aware** — passwords hashed with Werkzeug, no plaintext storage

---

## Accounting Treatment

| Event | Journal entry | Basis |
|-------|---------------|-------|
| Goods delivered | Dr Inventory, Dr VAT Input / Cr Trade Payables | Cost excludes recoverable VAT (IAS 2.11) |
| Kitchen usage | Dr Cost of Sales / Cr Inventory | FIFO cost formula (IAS 2.25) |
| Spoilage or NRV below cost | Dr Inventory Write-downs / Cr Inventory | Lower of cost and NRV (IAS 2.9); expensed in the period (IAS 2.34) |
| Stock count difference | Dr or Cr Cost of Sales / Inventory | Books agreed to physical count |
| Supplier paid | Dr Trade Payables / Cr Bank | Settles the invoice in full |

**Cost of sales** = opening inventory + purchases - closing inventory. The report also totals usage, write-downs and count variances from the ledger and shows whether the two figures agree.

**VAT** is set per product. Big Jo's is assumed to be a registered VAT vendor, and catalogue prices exclude VAT. Standard-rated goods carry 15%; fresh vegetables are zero-rated under Schedule 2 of the VAT Act, so they carry none.

**Why FIFO:** food is physically used oldest-first, and each delivery needs its own expiry date for spoilage to be tracked.

### Known limitations

- No sales module, so there is no revenue, output VAT, gross profit or VAT return.
- Reversals of write-downs (IAS 2.33) are not supported. Perishable stock rarely recovers in value.
- Each invoice is paid in full; part-payments and credit notes are not supported.
- The supplier marks an order as delivered, which is what posts the liability. A real system would have Big Jo's confirm receipt against a goods received note.
- Amounts are dated when they are entered; backdating and period locks are not supported.

---

## Project Structure

```
bigjos/
├── app/
│   ├── static/css/main.css
│   ├── templates/
│   │   ├── base.html
│   │   ├── shared/dashboard_layout.html
│   │   ├── main/home.html
│   │   ├── auth/ (login, register)
│   │   ├── manager/ (dashboard, suppliers, inventory, orders, reports, notifications)
│   │   └── supplier/ (dashboard, products, orders)
│   ├── models/__init__.py   ← SQLAlchemy models
│   ├── forms/__init__.py    ← WTForms
│   ├── auth/__init__.py     ← Auth blueprint
│   ├── manager/__init__.py  ← Manager blueprint
│   ├── supplier/__init__.py ← Supplier blueprint
│   ├── main/__init__.py     ← Home blueprint
│   └── __init__.py          ← App factory
├── config.py
├── run.py
├── seed.py
└── requirements.txt
```

---

*DUT Faculty of Accounting and Informatics | Financial Accounting 2 | 2026*
