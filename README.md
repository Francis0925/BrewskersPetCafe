<h1 align="center" style="font-size: 40px;">Brewskers Pet Café</h1>

<p align="center">
  <img src="https://img.shields.io/badge/Python-111111?style=flat-square&logo=python&logoColor=3776AB" alt="Python">
  <img src="https://img.shields.io/badge/Flask-111111?style=flat-square&logo=flask&logoColor=FFFFFF" alt="Flask">
  <img src="https://img.shields.io/badge/SQLite-111111?style=flat-square&logo=sqlite&logoColor=0F80CC" alt="SQLite">
  <br>
  <img src="https://img.shields.io/badge/JavaScript-111111?style=flat-square&logo=javascript&logoColor=F7DF1E" alt="JavaScript">
  <img src="https://img.shields.io/badge/HTML5-111111?style=flat-square&logo=html5&logoColor=E34F26" alt="HTML5">
  <img src="https://img.shields.io/badge/CSS3-111111?style=flat-square&logo=css3&logoColor=1572B6" alt="CSS3">
</p>

<br>

Brewskers Pet Café is a web-based point-of-sale and booking system for a café with a pet lounge. Staff sign in with a role-based account to ring up orders, track stock, book pet grooming and vet visits, and run reports from one place. A Flask backend serves every page, and all records are stored in a single SQLite database.

### Quick start

You need Python 3. The project was developed and tested on Python 3.12.

#### 1. Install the dependencies

**Windows (PowerShell)**

```powershell
cd pet-coffee-shop
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

**macOS / Linux**

```bash
cd pet-coffee-shop
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### 2. Configure environment variables

Copy the example file, then open `.env` and set `SECRET_KEY` to a long random string. Never commit `.env`.

```powershell
# Windows (PowerShell)
Copy-Item .env.example .env
```

```bash
# macOS / Linux
cp .env.example .env
```

> The forgot-password email only works if you also fill in `GMAIL_USER` and a Gmail app password. Everything else works without them.

#### 3. Set up the database

```bash
python3 scripts/setup.py        # Windows: py scripts/setup.py
```

> [!WARNING]
> `scripts/setup.py` builds a brand new database with the demo products and services. **It deletes any existing database first**, so only run it on a fresh install.

#### 4. Run the app

```bash
python3 app.py                  # Windows: py app.py
```

Open <http://127.0.0.1:5000> and sign in with `admin` / `12345678`. Change that password right away from the profile menu (top right).

To load demo orders and appointments, import `sample-data/brewskers-demo-data.zip` from **Administration → Data management**.

### Features

- **Point of sale:** Build an order, take cash, GCash, or card payments, work out change, and print a receipt. The cart supports undo and hold.
- **Orders:** New orders go into a first-in, first-out queue, and "Complete next in line" serves the oldest one. Completed and cancelled orders move to the history page, and the last status change can be undone. Both pages have live search by customer, order number, cashier, and payment method.
- **Inventory:** Products with pictures, stock counts, a low-stock warning, and unique product names.
- **Appointments and schedule:** Book a pet's visit, view the month on a calendar, and mark visits completed or cancelled. Two visits cannot overlap: the system checks the service's length against everything else booked that day.
- **Services:** Manage pet care services with their prices and durations.
- **Reports:** Sales for the last 7 days, top sellers, low stock, and upcoming appointments.
- **Administration:** Staff accounts and roles, store settings, CSV/SQL/database export, import with preview, backups and restore, and maintenance tools.
- **Backups:** Dated, verifiable database backups from the command line or the Administration page. If the database file is missing or empty at startup, the app restores the newest backup automatically.
- **Security:** CSRF protection, rate limiting, security headers, and input validation. See [SECURITY.md](SECURITY.md) for what is and is not covered.

### Roles

| Role | Can use |
|---|---|
| `admin` | Everything, including staff, settings, data tools, and reports |
| `cashier` | Dashboard, point of sale, queued orders, and order history (can reprint receipts) |
| `inventory` | Dashboard and inventory (view and edit) |
| `appointments` | Dashboard, appointments, and schedule (view and edit), plus a read-only view of services |
| `viewer` | Dashboard, inventory, and appointments (view only) |

The exact permission list lives in `backend/config.py`.

### Project structure

```text
CS2A_FINAL_PROJECT/
├── README.md, SECURITY.md, CODE_OF_CONDUCT.md
└── pet-coffee-shop/
    ├── app.py                  Entry point
    ├── requirements.txt
    ├── .env.example            Copy to .env
    ├── backend/
    │   ├── auth.py             App setup, login, sessions, password reset email
    │   ├── database.py         connect_db(), schema migrations, automatic restore
    │   ├── config.py           Roles, permissions, shared constants
    │   ├── security.py         CSRF, rate limiting, headers, input validation
    │   ├── permissions.py      current_user() and the access decorators
    │   ├── helpers.py          query() and run()
    │   ├── models.py           Record, CatalogItem, Product, Service, Appointment, Cart
    │   ├── errors.py           RecordError and the other custom exceptions
    │   ├── structures.py       HashTable, Queue, Stack (hand written)
    │   ├── algorithms.py       merge_sort, binary_search, linear_search (hand written)
    │   ├── pos_state.py        Product index, order queue, and undo stacks
    │   ├── csv_utils.py, activity.py, settings.py
    │   └── routes/             One file per area (pos, inventory, appointments, ...)
    ├── frontend/
    │   ├── templates/          One HTML page per screen, plus shared partials
    │   └── static/             style.css, layout.css, sidebar.css, app.js, images
    ├── scripts/
    │   ├── setup.py            Create a fresh database
    │   └── backup_db.py        Back up, verify, and restore
    └── sample-data/            Demo records
```

### Data structures and algorithms

These were written from scratch instead of using the built-ins, and are used by the running system.

| Piece | Where it is used | Time | Space |
|---|---|---|---|
| `HashTable` (chaining, resizes at 0.75 load) | Product lookup at checkout, per-user undo stacks | O(1) average, O(n) worst | O(n) |
| `Queue` (linked list) | Queued orders, first in first out | O(1) enqueue and dequeue | O(n) |
| `Stack` (linked list) | Undo of order status changes | O(1) push and pop | O(n) |
| `merge_sort` | POS product order, queue display | O(n log n) | O(n) |
| `binary_search` | Duplicate product name check | O(log n) | O(1) |
| `linear_search` | Position in the order queue | O(n) | O(1) |

### Backups

```bash
python scripts/backup_db.py --verify     # make a dated backup and check it
python scripts/backup_db.py --restore    # restore the newest backup
```

Backups are saved in `backups/`. Admins can also back up and restore from the Administration page.

### Documentation

| File | Contents |
|---|---|
| [`SECURITY.md`](SECURITY.md) | Existing protections, known gaps, and how to report a problem |
| [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) | Expected behavior in this repository |

### Production

The built-in Flask server is for development only. Before hosting this anywhere real:

- Set `APP_ENV=production`.
- Use a strong, random `SECRET_KEY`.
- Serve over HTTPS behind a production WSGI server.
- Read [SECURITY.md](SECURITY.md) first.

### Developers

**[De Ramos, Cheyenne Lei Z.]**  
**[Lim, Kenshin C.]**  
**[Lopez, Francisco M. III]**  

---

## Coursework Project

**Laguna State Polytechnic University** | **College of Computer Studies**  
**CS2A – Final Project**  
**Instructors:** [Ms. Roxanne Garbo, Sir Rolan C. Sotomayor, Sir Jencel P. Sofer]  
**Academic Year:** [2026-2027]

Brewskers Pet Café is our final project for CS2A. It covers three subjects at once: information management, data structures and algorithms, and object-oriented programming.

| Subject | Where it shows up in the project |
|---|---|
| **Object-Oriented Programming** | Model classes (`Record`, `CatalogItem`, `Product`, `Service`, `Appointment`, `Cart`) and custom exceptions (`RecordError` and others) |
| **Data Structures and Algorithms** | Hand-written `HashTable`, `Queue`, `Stack`, `merge_sort`, `binary_search`, and `linear_search`, used for checkout lookup, the order queue, and undo |
| **Information Management** | SQLite schema with keys, relationships, and indexes, order search, appointment overlap check, reports, activity log, import/export, and backup and restore |

---

*Last Updated: November 2026*
