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
The app will create the SQLite database automatically on first run.

### 5. Seed sample data
```bash
python seed.py
```

### 6. Open your browser
```
http://127.0.0.1:5000
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
| `/manager/inventory`     | Inventory stock levels + alerts      |
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
- **Financial reporting** with COGS summary by supplier and CSV export
- **POPIA-aware** — passwords hashed with Werkzeug, no plaintext storage

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
