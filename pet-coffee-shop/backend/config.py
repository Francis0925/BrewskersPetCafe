# Brewskers configuration
# Shared constants used across routes

import decimal


LOW_STOCK_LIMIT = 5
TAX_RATE = decimal.Decimal("0.08")
APPOINTMENT_STATUSES = ("scheduled", "completed", "cancelled")
ORDER_STATUSES = ("queued", "completed", "cancelled")

ROLES = (
    "admin",
    "cashier",
    "inventory",
    "appointments",
    "viewer",
)

PERMISSIONS = {
    "admin": {"*"},
    "cashier": {
        "dashboard.read",
        "pos.use",
        "orders.read",
        "orders.reprint",
    },
    "inventory": {
        "dashboard.read",
        "inventory.read",
        "inventory.write",
    },
    "appointments": {
        "dashboard.read",
        "appointments.read",
        "appointments.write",
        "services.read",
    },
    "viewer": {
        "dashboard.read",
        "inventory.read",
        "appointments.read",
    },
}

LANDING_PAGE = {
    "admin": "/dashboard",
    "cashier": "/pos",
    "inventory": "/inventory",
    "appointments": "/appointments",
    "viewer": "/dashboard",
}
