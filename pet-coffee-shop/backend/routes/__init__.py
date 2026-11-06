# Brewskers route registration
# Importing this package registers every route on the Flask app

from backend.routes import admin
from backend.routes import appointments
from backend.routes import auth_routes
from backend.routes import dashboard
from backend.routes import data_tools
from backend.routes import inventory
from backend.routes import pos
from backend.routes import profile
from backend.routes import reports
from backend.routes import services

__all__ = [
    "admin",
    "appointments",
    "auth_routes",
    "dashboard",
    "data_tools",
    "inventory",
    "pos",
    "profile",
    "reports",
    "services",
]
