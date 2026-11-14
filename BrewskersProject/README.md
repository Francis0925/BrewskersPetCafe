# Brewskers Pet Café

A point-of-sale and booking system for a café with a pet lounge. Staff can ring up orders, track stock, book pet grooming and vet visits, and run reports from one place. It is built with Flask and SQLite, with plain HTML, CSS and JavaScript on the front end.

This is our final project for CS2A (Laguna State Polytechnic University, College of Computer Studies). It covers three subjects at once: information management (the database), data structures and algorithms, and object-oriented programming.

## What it does

- **Point of sale.** Build an order, take cash, GCash or card payments, work out change, print a receipt. The cart has undo and hold.
- **Orders.** New orders go into a queue. "Complete next in line" serves the oldest one. Completed and cancelled orders move to the history page, and the last status change can be undone. Both pages have live search (customer, order number, cashier, payment method).
- **Inventory.** Products with pictures, stock counts, a low-stock warning, and unique product names.
- **Appointments and schedule.** Book a pet's visit, see the month on a calendar, mark visits completed or cancelled. Two visits cannot overlap: the system checks the service's length against everything else booked that day.
- **Services.** Manage the pet care services and their prices and durations.
- **Reports.** Sales for the last 7 days, top sellers, low stock, upcoming appointments.
- **Administration.** Staff accounts and roles, store settings, CSV/SQL/database export, import with preview, backups and restore, and maintenance tools.

## Running it

You need Python 3. We developed and tested on 3.12.

Windows (PowerShell):

```powershell
cd pet-coffee-shop
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
Copy-Item .env.example .env
py scripts/setup.py
py app.py
```

macOS or Linux:

```bash
cd pet-coffee-shop
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 scripts/setup.py
python3 app.py
```

Open http://127.0.0.1:5000 and sign in with `admin` / `12345678`. Change that password right away (profile menu, top right).

Notes:

- `scripts/setup.py` builds a brand new database with the demo products and services. **It deletes any existing database first**, so only run it on a fresh install.
- Open `.env` and set `SECRET_KEY` to a long random string. The forgot-password email only works if you also fill in `GMAIL_USER` and a Gmail app password; everything else works without them.
- `sample-data/brewskers-demo-data.zip` can be imported from Administration > Data management if you want demo orders and appointments.

## Roles

| Role | Can use |
|---|---|
| admin | Everything, including staff, settings, data tools and reports |
| cashier | Dashboard, point of sale, queued orders and order history (can reprint receipts) |
| inventory | Dashboard and inventory (view and edit) |
| appointments | Dashboard, appointments and schedule (view and edit), and a read-only look at services |
| viewer | Dashboard, inventory and appointments, view only |

The exact list lives in `backend/config.py`.

## How the code is organised

```text
CS2A_FINAL_PROJECT/
  README.md, SECURITY.md, CODE_OF_CONDUCT.md
  pet-coffee-shop/
    app.py                  Entry point
    requirements.txt
    .env.example            Copy to .env
    backend/
      auth.py               App setup, login, sessions, password reset email
      database.py           connect_db(), schema migrations, automatic restore
      config.py             Roles, permissions, shared constants
      security.py           CSRF, rate limiting, headers, input validation
      permissions.py        current_user() and the access decorators
      helpers.py            query() and run()
      models.py             Record, CatalogItem, Product, Service, Appointment, Cart
      errors.py             RecordError and the other custom exceptions
      structures.py         HashTable, Queue, Stack (hand written)
      algorithms.py         merge_sort, binary_search, linear_search (hand written)
      pos_state.py          Product index, order queue and undo stacks
      csv_utils.py, activity.py, settings.py
      routes/               One file per area (pos, inventory, appointments, ...)
    frontend/
      templates/            One HTML page per screen, plus shared partials
      static/               style.css, layout.css, sidebar.css, app.js, images
    scripts/
      setup.py              Create a fresh database
      backup_db.py          Back up, verify and restore
    tests/                  Unit tests
    sample-data/            Demo records
    docs/                   Project analysis, database notes, ERD
```

## Data structures and algorithms

We wrote these ourselves instead of using the built-ins, and use them in the running system.

| Piece | Where it is used | Time | Space |
|---|---|---|---|
| HashTable (chaining, resizes at 0.75 load) | Product lookup at checkout, per-user undo stacks | O(1) average, O(n) worst | O(n) |
| Queue (linked list) | Queued orders, first in first out | O(1) enqueue and dequeue | O(n) |
| Stack (linked list) | Undo of order status changes | O(1) push and pop | O(n) |
| merge_sort | POS product order, queue display | O(n log n) | O(n) |
| binary_search | Duplicate product name check | O(log n) | O(1) |
| linear_search | Position in the order queue | O(n) | O(1) |

The order search and the appointment overlap check are explained in `docs/DATABASE.md`.

## Tests

From the `pet-coffee-shop` folder:

```bash
python -m unittest discover -s tests -t .
```

The tests use a temporary database, so they never touch your real data. They cover the order search (matching, pagination, escaping) and the appointment conflict rules (overlap cases, cancelled slots, CSV import, edits).

## Backups

```bash
python scripts/backup_db.py --verify     # make a dated backup and check it
python scripts/backup_db.py --restore    # restore the newest backup
```

Backups go in `backups/`. If the live database file is missing or empty when the app starts, it restores the newest backup on its own. Admins can also back up and restore from Administration.

## Documentation

- `docs/PROJECT_ANALYSIS.md`: the problem, the users, requirements and scope.
- `docs/DATABASE.md`: every table and column, keys, relationships, indexes and normalization.
- `docs/erd.png`: the entity relationship diagram.
- `SECURITY.md`: what protections exist, what does not, and how to report a problem.
- `CODE_OF_CONDUCT.md`: how we expect people to behave in this repository.

## Things to know before putting it on a server

The built-in Flask server is for development. If you host this anywhere real, set `APP_ENV=production`, use a proper secret key, serve it over HTTPS behind a production WSGI server, and read `SECURITY.md` first.
