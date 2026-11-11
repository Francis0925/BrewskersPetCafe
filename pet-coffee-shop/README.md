# Brewskers Pet Coffee Shop

Flask and SQLite system for POS, inventory, pet appointments, services, reports and staff management.

## Project structure

```text
pet-coffee-shop/
  app.py                  Entry point only. Run with python app.py
  requirements.txt
  .env.example            Copy to .env and fill in your values
  backend/
    __init__.py
    auth.py               Flask app creation, passwords, login logic, OTP and email
    database.py           Database path and connect_db()
    config.py             Roles, permissions, tax rate and shared constants
    security.py           CSRF, rate limiting, headers, input validation
    permissions.py        current_user(), user_has() and route decorators
    helpers.py            query(), run() and row cleaning
    errors.py             Custom exceptions: RecordError and its subclasses
    models.py             Record classes: Product, Service, Appointment, Cart
    structures.py         Hand-written HashTable, Queue and Stack
    algorithms.py        Hand-written merge sort, binary search and linear search
    pos_state.py          Product index, order queue and undo stacks built on them
    csv_utils.py          CSV import and export helpers
    activity.py           Activity log recording
    routes/
      __init__.py         Imports every route module to register it
      auth_routes.py      Login page, login, forgot and reset password
      profile.py          Sidebar, logout, first login, landing, profile
      dashboard.py        Dashboard page
      pos.py              POS, orders and receipt reprint
      inventory.py        Products and stock
      appointments.py     Appointments and schedule
      services.py         Pet services
      reports.py          Sales reports for admins
      admin.py            Staff management for admins
      data_tools.py       CSV import, export and data reset
  frontend/
    templates/            HTML pages, one per screen, plus _topbar.html
    static/               app.js, style.css, sidebar.css, layout.css, product_images/
  scripts/
    setup.py              Creates a fresh database with seed data
    backup_db.py          Backup, verify and restore the database
  docs/                   Project analysis and database documentation with the ERD
  sample-data/            Demo records to import for presentations
  petcoffeeshop.db        Live SQLite database, created by setup.py
  backups/                Dated database backups, created by backup_db.py
  logs/                   Private application log file
```

## Features

- Orders: Queued / Completed / Cancelled status with separate Queued orders and Order history pages, plus filter and search.
- Order queue: queued orders show their place in line, Complete next in line serves the front of the queue, and Undo last change reverses the most recent status update.
- POS: cart has an Undo button that restores the cart to how it was before the last change.
- Inventory: add a product picture (JPG/PNG/WebP, max 2 MB), change picture later, thumbnails in Inventory and POS.
- Products: names must be unique. Adding an existing name is rejected with a clear message, and a unique index in the database enforces the same rule.
- Import and export:
  - One table as a separate CSV file: Products, Services, Orders, Appointments
  - All data as separate CSV files in one ZIP
  - All data as one SQL file
  - All data as one database file
  - Import a ZIP of CSVs with preview, or restore a .db/.sql file (current DB is backed up first)
- Layout: non-admin staff (cashier, inventory, appointments) use a top menu bar for more space. Admins keep the sidebar with a collapse button. Profile avatar is at the top right in both layouts.
- Scrollbars are thin and themed to the Brewskers colors. Use class `no-scrollbar` to hide a scrollbar completely.
- Settings: admins can edit store profile and create backups from Administration or Settings.

## How to run

```powershell
py -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env and set a long random SECRET_KEY
py scripts/setup.py
py app.py
```

Open http://127.0.0.1:5000 and log in with admin / 12345678, then change the password.

## Backup and restore

```powershell
py scripts/backup_db.py --verify
py scripts/backup_db.py --restore
```

If the live database file is deleted or empty, running backup_db.py restores the latest backup instead of creating a blank database.

## Documentation

- docs/PROJECT_ANALYSIS.md explains the problem, purpose, users by role, information requirements and scope.
- docs/DATABASE.md documents every table, column, key, relationship, index and the normalization reasoning.
- docs/erd.png is the entity relationship diagram of the database.

## Notes

- Do not commit .env, petcoffeeshop.db, backups/ or logs/ to Git.
- Set FLASK_DEBUG=false and APP_ENV=production on a real server.
