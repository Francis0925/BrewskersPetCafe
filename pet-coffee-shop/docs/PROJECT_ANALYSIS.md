# Brewskers Project Analysis

This document explains the problem the Brewskers system solves, who it is
for, what information it must store and process, and how far its scope
goes. It is written about the system as it actually exists in this
repository. The full table and relationship details are in
[DATABASE.md](DATABASE.md).

## Problem Statement

Brewskers is a small pet coffee shop. It sells coffee, pastries and pet
treats at the counter, and it offers bookable care services for pets such
as grooming. Running that business by hand causes recurring problems:

| Problem without a system | Effect on the shop |
|---|---|
| Sales are written on paper receipts | Daily totals take long to add up, receipts cannot be reprinted, and mistakes are hard to catch |
| Stock is counted by eye | Items sell out unnoticed, low stock is discovered only when a customer asks, and nothing warns the staff early |
| Appointments are kept in a notebook | Bookings get double booked, forgotten, or lost, and there is no quick view of who is coming today |
| Tax and totals are computed by hand | Wrong change and wrong tax happen under counter pressure |
| No record of who did what | When a price, a stock count or a booking is wrong, nobody can tell who changed it |
| Anyone can touch anything | There is no way to let a cashier run the register without also letting them change staff accounts or delete records |
| Reports do not exist | The owner cannot see best sellers, daily sales or low stock without re reading every receipt |

## Purpose

The purpose of this project is a single database backed application that
runs the whole shop counter to counter:

| The system | What it gives the shop |
|---|---|
| Point of sale with a cart | Fast checkout with automatic tax, cash change, GCash and card payments, and printable receipts |
| Order queue and history | New orders line up as queued, get completed or cancelled, and any receipt can be reprinted |
| Live inventory | Stock drops with every sale, restocking and picture uploads, low stock warnings against a configurable threshold |
| Appointment scheduling | A calendar and day list of pet bookings with service, owner and pet details, status tracking and validation |
| Services catalog | Pet care services with price and duration that can be activated or deactivated |
| Staff accounts and roles | Five roles with different permissions, hashed passwords, forced password change, password reset by one time code, account deactivation |
| Activity trail | Every important action is logged with who, what and when |
| Reports | Today's sales, weekly revenue, best sellers, low stock and upcoming appointments on one dashboard |
| Backup and recovery | One click backups, verification, restore with automatic safety backup, and automatic restore if the database file is lost |

## Intended Users

The system has five user roles. The role decides the landing page after
login and every screen and action each person can reach.

### Administrator

The owner or shop manager. Lands on the dashboard, and is the only role
that can reach everything:

| Admin does | Where |
|---|---|
| Watch sales, best sellers, low stock and appointments | Dashboard |
| Create staff accounts, change roles, reset passwords, deactivate accounts | Staff page |
| Add, update and remove products and services | Inventory and Services |
| Import and export data, run data maintenance actions with typed confirmation | Data management |
| Take and restore backups | Backup manager |
| Set store details, tax rate and low stock threshold | Settings |
| Read the activity log | Dashboard and data management |

### Cashier

The person at the register. Lands on the POS and cannot touch inventory,
staff or settings. A cashier can run the checkout, watch the order queue,
mark orders completed or cancelled, reprint receipts and read the
dashboard.

### Inventory staff

The person minding the shelves. Lands on the inventory page and can view
products, add new ones with pictures, set or restock stock counts and
remove items from the menu. They cannot sell, book or manage staff.

### Appointments staff

The person handling pets. Lands on the appointments page and can view and
create bookings, update booking status, view the schedule calendar and
read the services list. They cannot sell or change the catalog.

### Viewer

A supervisor or auditor who only needs to look. Lands on the dashboard
with read access to the dashboard, inventory and appointments, and no
write actions anywhere.

## Information Requirements

The system must store and process the following information. Each item
maps to the tables listed in DATABASE.md.

### Sales information

| Must store | Must process |
|---|---|
| Each order with number, date, cashier, customer name, payment method, amount paid, change and status | Build the cart, compute subtotal, tax and total, validate payment, guard against selling more than the shelf holds |
| Each order line with product, quantity and the price charged | Drop stock per line inside one transaction, recompute any receipt, sum best sellers |
| The tax rate applied at sale time | Keep old receipts accurate when the store changes its rate |

### Catalog information

| Must store | Must process |
|---|---|
| Products with category, name, price, stock, status and picture | Search and filter the menu, reject duplicate product names, hide without deleting, warn on low stock |
| Services with name, price, duration and active flag | Offer only active services on the booking form, activate and deactivate |

### Appointment information

| Must store | Must process |
|---|---|
| Pet name, type, breed, age, owner name and phone | Validate required fields, phone format, pet type and no past dates |
| Service, date, time, status, notes, photo and booking staff | Schedule calendar, today and week views, status changes, cancellation |

### Staff and access information

| Must store | Must process |
|---|---|
| Accounts with username, email, hashed password, role and state | Login with rate limiting, sessions and remember me cookies, forced password change, one time reset codes, deactivation |
| Which admin created which account | Accountability for account changes |

### Store configuration and audit information

| Must store | Must process |
|---|---|
| Store name, address, phone, email, tax rate, low stock limit | Print on receipts, drive tax math and low stock warnings, editable in Settings |
| One log row per important action with user, action code, record pointer, description and time | Show the newest activity, prove who changed what |

### Derived information the system must produce

| Output | Computed from |
|---|---|
| Receipt totals with tax and change | Cart lines plus the stored tax rate |
| Daily and weekly sales | Orders grouped by date |
| Best sellers | Order lines joined to orders and products, grouped by product |
| Low stock list | Products below the stored threshold |
| Today's and upcoming appointments | Appointments joined to services |

## Scope and Feasibility

### In scope

Counter sales with receipts and the order queue, inventory and stock
control, pet service booking with a calendar, staff accounts with five
roles, an activity log, a reports dashboard, CSV and ZIP import and
export, data maintenance tools, and backup with restore. All of it is
implemented and running in this repository.

### Out of scope

Online ordering or payment gateways, a customer facing mobile app, multi
branch support with one shared database, loyalty points, and kitchen
display screens. These are real shop needs but they add network services
beyond what a single counter system and a class project require.

### Feasibility

| Aspect | Why the project is achievable |
|---|---|
| Scale | One shop, one counter, one database. SQLite is a single file that handles this volume easily and makes backup a file copy |
| Technology | Python, Flask and SQLite are free, lightweight and run on an ordinary laptop with no installation beyond pip install |
| Data | Eleven tables with clear keys and relationships, as documented in DATABASE.md |
| Effort | The whole system fits one project codebase, and it was built and verified end to end |
| Operation | Runs with py app.py, logs in with an admin account, and recovers itself from a lost database file |

The scope matches a single database system course project: every feature
stores, retrieves or reports structured data, and every screen reads and
writes the one SQLite database described in the companion document.
