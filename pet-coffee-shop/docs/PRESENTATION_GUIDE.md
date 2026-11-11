# Brewskers Pet Coffee Shop — Presentation Review Guide

Use this guide to explain the system during the defense. It maps every rubric item
from the three subjects (OOP, DSA, Information Management) to the actual code, and
gives a suggested demo flow.

---

## 1. System Overview

**Brewskers** is a point-of-sale and management system for a pet-friendly coffee shop.
It lets staff sell drinks/pastries/pet treats, manage inventory, book grooming and
vet appointments, and lets admins run reports and maintain data.

- **Project type:** CS2A final project, three subjects (OOP, DSA, Information Management)
- **Run:** `py app.py` then open http://127.0.0.1:5000
- **Login:** `admin` / `12345678`
- **Roles (5):** admin, cashier, inventory, appointments, viewer (defined in `backend/config.py`)

---

## 2. Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3 |
| Web framework | Flask |
| Database | SQLite (single file `petcoffeeshop.db`) |
| Templates | Jinja2 (server-rendered HTML) |
| Frontend | Plain HTML / CSS / JavaScript (no framework) |
| Passwords | Werkzeug (bcrypt-style hashing) |
| Config | python-dotenv (`.env`) |
| Dev tooling | (none beyond pip requirements) |

Dependencies are only three: `Flask`, `Werkzeug`, `python-dotenv`.

---

## 3. Architecture

```
app.py                 # entry point, imports routes
backend/
  auth.py              # Flask app, login, OTP email, passwords
  config.py            # roles, permissions, tax, constants
  database.py          # connect_db, migrate_db, schema (11 tables)
  helpers.py           # query(), run(), row cleaning
  security.py          # CSRF, rate limit, headers, validation
  permissions.py       # current_user(), user_has(), @require
  models.py            # OOP classes (Record, CatalogItem, Product, Service, Cart, StoreSettings)
  errors.py            # custom exceptions
  structures.py        # HashTable, Queue, Stack (hand-written)
  algorithms.py        # merge_sort, binary_search, linear_search (hand-written)
  pos_state.py         # in-memory ProductIndex (HashTable), OrderQueue (Queue), StatusUndo (Stack)
  csv_utils.py         # CSV import/export
  activity.py          # activity log
  settings.py          # store profile (tax rate, low stock limit)
  routes/              # one module per feature area
frontend/
  templates/           # Jinja2 templates + partials
  static/              # CSS, JS, images
scripts/
  setup.py             # fresh DB + seed data
  backup_db.py         # Backup, verify and restore the database
docs/
  DATABASE.md, PROJECT_ANALYSIS.md, erd.png
```

**Data flow:** browser -> Flask route -> helpers.query/run -> SQLite. In-memory structures in
`pos_state.py` are rebuilt from the database on demand and invalidated after changes.

---

## 4. Features

- **POS:** product grid, cart, checkout, 12% VAT, payment, receipt, queued orders, undo status
- **Inventory:** CRUD, stock, hide/restore, image upload, duplicate-name check, low-stock alerts
- **Appointments:** book, view, complete/cancel, schedule calendar
- **Services:** CRUD for grooming/vet services
- **Orders:** queued orders, history, search, status changes
- **Reports:** sales summaries
- **Admin:** user/staff management, permissions
- **Settings:** tax rate, low-stock limit, store profile, backups, import/export ZIP
- **Data Management:** 11 maintenance actions with preview + confirmation dialogs
- **Auth:** login, roles, OTP password reset by email, first-login password change

---

## 5. OOP Rubric (30% + 20% + 10% + 10% + 10%)

### 5.1 Object-Oriented Programming concepts — `backend/models.py`
- **Classes and objects:** `Record`, `CatalogItem`, `Product`, `Service`, `Appointment`, `Cart`, `StoreSettings`
- **Constructors:** `__init__` with `**fields`; `from_row()` alternate constructor
- **Encapsulation:** `Cart` keeps `_lines` private, exposes `subtotal`, `tax`, `total` as read-only properties; `StoreSettings` hides tax/low-stock conversions
- **Inheritance:** `Product`, `Service` -> `CatalogItem` -> `Record`
- **Polymorphism:** `is_available()` and `validate()` called without knowing the subclass
- **Abstraction:** `Record` is an `ABC` with abstract `validate()`
- **Method overloading:** single `__init__(**fields)` accepts any subset of fields (Python's way)
- **Abstract class:** `Record(ABC)`

### 5.2 Functional features
Login, add/edit/delete records, search, display, save/load (SQLite + CSV/ZIP import/export + backups) — all present.

### 5.3 GUI
Web pages, buttons, labels, textboxes, selects (combo boxes), nav menus, tables, fonts/colors.

### 5.4 Exception handling — `backend/errors.py`
Custom exceptions: `RecordError`, `InvalidRecordError`, `OutOfStockError`. Plus validation, file errors, type checks.

### 5.5 Code quality
Modular `backend/` package, reusable helpers, plain-text comments, consistent naming.

---

## 6. DSA Rubric

### A. Data Management — PASS
- CRUD for products, services, orders, appointments, users
- Structures organize records: HashTable (product index, user stacks), Queue (order line), Stack (undo)
- Invalid input / missing records handled (validation, 404s, custom errors)

### B. Data Processing — PASS
- **Hashing:** `HashTable` with own hash functions (Knuth multiplicative for ints, djb2 for strings), separate chaining, auto-resize at 0.75 load, O(1) average. Used as `product_index` at checkout.
- **Searching:** `linear_search` (queue position lookup), `binary_search` (duplicate product name check on sorted list)
- **Sorting:** `merge_sort` (stable, O(n log n)) for POS grid order and queued-orders page

### C. DSA-Based Functionality — PASS
- Multiple structures/algorithms wired into real features (product index, order queue, undo stacks, duplicate check, POS grid sort)
- Realistic test data via sample-data ZIP

### D. Performance Evaluation — SKIPPED (per user); but docstrings already carry Big-O

---

## 7. Information Management Rubric (sections 1-5)

- **Section 1 (problem/purpose/scope):** `docs/PROJECT_ANALYSIS.md`
- **Section 2 (information requirements, 5 roles):** `backend/config.py` ROLES/PERMISSIONS
- **Section 3 (database design):** `docs/DATABASE.md` — all 11 tables, relationships, indexes, 1NF/2NF/3NF justification (intentional `order_items.price` and `orders.tax_rate` snapshots)
- **Section 4 (ERD):** `docs/erd.png` documents the database schema visually
- **Section 5 (implementation):** Flask + SQLite, CRUD, import/export, backups

Sections 6 (testing/docs) and 7 (demo) deferred per user.

---

## 8. Key Code Locations (cheat sheet)

| Concept | File | Symbol |
|---|---|---|
| Abstract base class | `backend/models.py` | `class Record(ABC)` |
| Inheritance | `backend/models.py` | `CatalogItem(Record)`, `Product(CatalogItem)` |
| Encapsulation | `backend/models.py` | `Cart` (private `_lines`, properties) |
| Custom exceptions | `backend/errors.py` | `RecordError`, `InvalidRecordError`, `OutOfStockError` |
| HashTable | `backend/structures.py` | `class HashTable` |
| Queue | `backend/structures.py` | `class Queue` |
| Stack | `backend/structures.py` | `class Stack` |
| Merge sort | `backend/algorithms.py` | `merge_sort()` |
| Binary search | `backend/algorithms.py` | `binary_search()` |
| Linear search | `backend/algorithms.py` | `linear_search()` |
| POS state wiring | `backend/pos_state.py` | `ProductIndex`, `OrderQueue`, `StatusUndo` |
| Duplicate name check | `backend/routes/inventory.py` | add_product (binary search) |
| Roles/permissions | `backend/config.py` | `ROLES`, `PERMISSIONS` |
| Schema/migration | `backend/database.py` | `migrate_db`, `idx_products_name` |

---

## 9. Suggested Demo Flow

1. Login as admin (show role-based landing).
2. Dashboard (stats, low stock).
3. POS: add items to cart, checkout, show receipt + VAT, queued order appears.
4. Queued orders: show queue position, complete an order, undo.
5. Inventory: search/filter, add product (duplicate name -> 409 toast), stock update.
6. Services + Appointments: book, view schedule.
7. Reports: sales summary.
8. Settings: change tax rate, show new order uses new rate, old order keeps snapshot.
9. Data Management: preview + confirm a clear action.
10. Show ERD (docs/erd.png) and DATABASE.md.
11. Show tests passing (duplicate name 14/14, suites).

---

## 10. Test Evidence

- `test_dsa_algorithms.py`: 1215/1215 checks
- `test_duplicate_name.py`: 14/14
- `test_data_maintenance.py`: 103/103
- `test_admin_overhaul.py`, `test_maintenance_new.py`, `test_settings_features.py`: all pass
- Baseline snapshot: 0 differences after all changes
- ERD: 219 verification checks passed

---

## 11. Key Talking Points

- "All data structures are hand-written — no `dict`/`deque`/`sorted()` shortcuts for the structures themselves."
- "The ERD is generated from the live database, so it can never drift from reality."
- "Tax rate is editable and snapshotted per order, so old receipts keep their original tax."
- "Duplicate product check is case-sensitive and includes hidden products, consistent with CSV import upsert."
- "Pillow is installed for the ERD script only, deliberately not in requirements.txt."
- "Comments and section titles are plain text (no decorative symbols)."
- "All verification was done with baseline/after snapshots — zero behavioral differences."
