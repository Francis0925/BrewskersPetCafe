# Brewskers store settings service
# Reads the store profile row and returns it as a StoreSettings object.
# Every page that needs the tax rate or the low stock threshold goes
# through here, so there is exactly one place that loads them.

from backend.helpers import query
from backend.models import StoreSettings


def get_store_settings():
    """Load the current store settings from the store profile row."""
    row = query("SELECT * FROM store_profile LIMIT 1", one=True)
    return StoreSettings.from_row(row)
