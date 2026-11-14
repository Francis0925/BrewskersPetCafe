# Brewskers record classes
# Every stored record can become an object that owns its own data and rules.
# The classes below cover the OOP concepts the system demonstrates:
#
#   Abstraction    Record is an abstract base class. It defines the shared
#                  constructor, from_row() and to_dict(), and requires every
#                  subclass to implement validate().
#   Inheritance     Product and Service inherit from CatalogItem, which
#                  inherits from Record.
#   Polymorphism    is_available() and validate() are called without knowing
#                  which subclass is behind them. A product decides
#                  availability by its status, a service by its active flag.
#   Encapsulation   The Cart keeps its lines private and exposes the running
#                  totals through read-only properties. StoreSettings hides
#                  the tax and low stock conversions the same way, so pages
#                  only ever see safe ready to use values.
#   Overloading     Python has no method overloading, so the shared
#                  constructor accepts any subset of fields and falls back
#                  to class defaults, giving one constructor many call
#                  shapes.
#
# Templates and JSON replies still receive plain dictionaries from to_dict(),
# so nothing outside this module needs to know these classes exist.

import decimal

from abc import ABC, abstractmethod

from backend.config import DEFAULT_LOW_STOCK_LIMIT, DEFAULT_TAX_RATE
from backend.errors import InvalidRecordError, OutOfStockError
from backend.security import validate_appointment


class Record(ABC):
    """Abstract base class for every stored record.

    A record knows its table and columns, can be built from any subset of
    fields, and validates itself. Subclasses implement validate() with
    their own rules; everything shared by all records lives here.
    """

    TABLE = None
    COLUMNS = ()
    DEFAULTS = {}

    def __init__(self, **fields):
        """Build a record from any subset of fields.

        Missing fields fall back to the class defaults, so callers can pass
        only the values they have. Extra columns from joined queries, such
        as service_name, are kept as extra attributes so nothing is lost.
        """
        for column in self.COLUMNS:
            setattr(self, column, fields.pop(column, self.DEFAULTS.get(column)))
        for key, value in fields.items():
            setattr(self, key, value)

    @classmethod
    def from_row(cls, row):
        """Alternate constructor: build a record from a database row."""
        return cls(**dict(row))

    @abstractmethod
    def validate(self):
        """Check this record and raise InvalidRecordError if it is not valid."""

    def to_dict(self):
        """Return a plain dictionary, the shape templates and JSON expect."""
        return dict(self.__dict__)


class CatalogItem(Record):
    """Shared base for things the shop sells or books.

    Products and services both have a price and an availability rule, but
    the rule means something different for each, so CatalogItem leaves
    is_available() abstract and every subclass defines its own version.
    Calling code never needs to know which subclass it holds.
    """

    @abstractmethod
    def is_available(self):
        """Each catalog item decides its own availability rule."""


class Product(CatalogItem):
    """A menu item the shop sells. Knows its own price, stock and rules."""

    TABLE = "products"
    COLUMNS = (
        "product_id", "category", "name", "price", "stock", "status", "image",
    )
    DEFAULTS = {
        "product_id": None,
        "category": "",
        "name": "",
        "price": "",
        "stock": "",
        "status": "available",
        "image": None,
    }

    def is_available(self):
        """A product can be sold while it is not hidden by inventory staff."""
        return self.status == "available"

    def reduce_stock(self, quantity):
        """Take stock out for a cart line.

        Raises OutOfStockError when the request is larger than the shelf, so
        the caller can reject the order before anything is saved. Stock the
        object cannot read as a number counts as an empty shelf, because
        rejecting a sale is safer than guessing.
        """
        try:
            available = int(self.stock or 0)
        except (TypeError, ValueError):
            available = 0

        if quantity > available:
            raise OutOfStockError(self.name, quantity, available)

        self.stock = available - quantity

    def validate(self):
        """Check and normalize every product rule, in order."""
        self.name = str(self.name or "").strip()
        self.category = str(self.category or "").strip()

        if not self.name:
            raise InvalidRecordError("Name is required")

        if not self.category:
            raise InvalidRecordError("Category is required")

        try:
            self.price = float(self.price)
        except (TypeError, ValueError):
            raise InvalidRecordError("Price must be a valid number")

        try:
            stock_text = str(self.stock).strip()
            self.stock = int(stock_text) if stock_text else 0
        except (TypeError, ValueError):
            raise InvalidRecordError("Stock must be a whole number")

        if self.price < 0:
            raise InvalidRecordError("Price cannot be negative")

        if self.stock < 0:
            raise InvalidRecordError("Stock cannot be negative")


class Service(CatalogItem):
    """A grooming or vet service that customers book for their pets."""

    TABLE = "services"
    COLUMNS = ("service_id", "name", "price", "duration", "active")
    DEFAULTS = {
        "service_id": None,
        "name": "",
        "price": "",
        "duration": "",
        "active": 1,
    }

    def is_available(self):
        """A service can be booked while it is marked active.

        Active can arrive as a database integer or as text from a CSV row,
        so both forms are understood.
        """
        if isinstance(self.active, str):
            return self.active.strip().lower() in {"1", "true", "yes", "on", "active"}
        return bool(self.active)

    def validate(self):
        """Check and normalize every service rule, in order."""
        self.name = str(self.name or "").strip()

        if not self.name:
            raise InvalidRecordError("Name is required")

        try:
            self.price = float(self.price)
        except (TypeError, ValueError):
            raise InvalidRecordError("Price must be a valid number")

        try:
            self.duration = int(self.duration)
        except (TypeError, ValueError):
            raise InvalidRecordError("Duration must be a whole number")

        if self.price < 0:
            raise InvalidRecordError("Price cannot be negative")

        if self.duration <= 0:
            raise InvalidRecordError("Duration must be greater than zero")


class Appointment(Record):
    """A booked visit: pet, owner, service, date and time.

    The detailed booking rules live in security.validate_appointment so the
    page forms and this model can never disagree. validate() turns that
    shared check into the record's own behavior and raises
    InvalidRecordError with the reason when the booking is not valid.
    """

    TABLE = "appointments"
    COLUMNS = (
        "appointment_id", "pet_name", "pet_type", "breed", "pet_age",
        "owner_name", "phone", "service_id", "appt_date", "appt_time",
        "status", "notes", "photo", "created_by", "created_at",
    )
    DEFAULTS = {
        "appointment_id": None,
        "pet_name": "",
        "pet_type": "Dog",
        "breed": "",
        "pet_age": "",
        "owner_name": "",
        "phone": "",
        "service_id": None,
        "appt_date": "",
        "appt_time": "",
        "status": "scheduled",
        "notes": "",
        "photo": None,
        "created_by": None,
        "created_at": None,
    }

    def validate(self):
        """Return the cleaned booking fields or raise InvalidRecordError."""
        clean, error = validate_appointment(self.to_dict())
        if error:
            raise InvalidRecordError(error)
        return clean


class StoreSettings:
    """The store profile row plus the numbers administrators can edit.

    Tax rate and low stock threshold used to be hardcoded constants.
    They now live in the store_profile table and every page reads them
    through this class, so the settings form, receipts and low stock
    warnings can never disagree. Bad or missing values always fall back
    to the safe defaults from config.py, so a broken row can never stop
    a page from rendering.
    """

    MAX_TAX_RATE = decimal.Decimal("100")
    MAX_LOW_STOCK_LIMIT = 999

    def __init__(
        self,
        store_name="Brewskers",
        address="",
        phone="",
        email="",
        tax_rate=None,
        low_stock_limit=None,
    ):
        self.store_name = (store_name or "Brewskers").strip() or "Brewskers"
        self.address = (address or "").strip()
        self.phone = (phone or "").strip()
        self.email = (email or "").strip()
        self.tax_rate = self._coerce_percent(tax_rate)
        self.low_stock_limit = self._coerce_limit(low_stock_limit)

    @classmethod
    def from_row(cls, row):
        """Alternate constructor: build the settings from a database row."""
        row = dict(row or {})
        return cls(
            store_name=row.get("store_name"),
            address=row.get("address"),
            phone=row.get("phone"),
            email=row.get("email"),
            tax_rate=row.get("tax_rate"),
            low_stock_limit=row.get("low_stock_limit"),
        )

    @staticmethod
    def _coerce_percent(value):
        """Return a tax percentage as a Decimal, or the default when bad."""
        try:
            percent = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            percent = DEFAULT_TAX_RATE * 100
        if percent < 0 or percent > 100:
            percent = DEFAULT_TAX_RATE * 100
        return percent

    @staticmethod
    def _coerce_limit(value):
        """Return a low stock threshold as an int, or the default when bad."""
        try:
            limit = int(value)
        except (TypeError, ValueError):
            return DEFAULT_LOW_STOCK_LIMIT
        if limit < 0 or limit > 999:
            return DEFAULT_LOW_STOCK_LIMIT
        return limit

    @property
    def tax_rate_fraction(self):
        """The tax rate as a fraction, ready for money math."""
        return self.tax_rate / 100

    @property
    def tax_rate_percent(self):
        """The tax rate as a percent number for forms and labels."""
        return float(self.tax_rate)

    @classmethod
    def parse_tax_rate(cls, value):
        """Turn admin input into a tax percent, or raise InvalidRecordError."""
        try:
            percent = decimal.Decimal(str(value)).quantize(
                decimal.Decimal("0.01"), rounding=decimal.ROUND_HALF_UP
            )
        except (decimal.InvalidOperation, TypeError, ValueError):
            raise InvalidRecordError("Tax rate must be a number")
        if percent < 0 or percent > cls.MAX_TAX_RATE:
            raise InvalidRecordError("Tax rate must be between 0 and 100")
        return percent

    @classmethod
    def parse_low_stock_limit(cls, value):
        """Turn admin input into a threshold, or raise InvalidRecordError."""
        try:
            limit = int(str(value).strip())
        except (TypeError, ValueError):
            raise InvalidRecordError("Low stock threshold must be a whole number")
        if limit < 0 or limit > cls.MAX_LOW_STOCK_LIMIT:
            raise InvalidRecordError("Low stock threshold must be between 0 and 999")
        return limit


class CartLine:
    """One product line inside a cart."""

    def __init__(self, product, quantity):
        self.product = product
        self.quantity = quantity
        self.unit_price = decimal.Decimal(str(product.price))

    @property
    def line_total(self):
        """Price times quantity for this line."""
        return self.unit_price * self.quantity


class Cart:
    """The order being built at the point of sale.

    The cart owns its lines and computes the totals, so checkout code never
    touches the running math directly. Totals are Decimal values rounded to
    centavos the same way the receipts expect. The tax rate is injected by
    the caller from the store settings, so the cart itself never reads the
    database and stays easy to test.
    """

    CENTS = decimal.Decimal("0.01")

    def __init__(self, tax_rate=None):
        """Build an empty cart with an optional tax fraction.

        Without a rate the default from config.py is used, which keeps the
        class working for older callers and tests.
        """
        self._lines = []
        self._tax_rate = tax_rate if tax_rate is not None else DEFAULT_TAX_RATE

    def add(self, product, quantity):
        """Add one product with a quantity to the cart."""
        self._lines.append(CartLine(product, quantity))

    @property
    def lines(self):
        """A copy of the cart lines, safe to iterate while checking out."""
        return list(self._lines)

    @property
    def tax_rate(self):
        """The tax fraction applied to this cart's totals."""
        return self._tax_rate

    @property
    def subtotal(self):
        """Sum of every line total, rounded to centavos."""
        total = decimal.Decimal("0")
        for line in self._lines:
            total += line.line_total
        return total.quantize(self.CENTS, rounding=decimal.ROUND_HALF_UP)

    @property
    def total(self):
        """Subtotal plus tax at this cart's rate, rounded to centavos."""
        return (self.subtotal * (1 + self._tax_rate)).quantize(
            self.CENTS, rounding=decimal.ROUND_HALF_UP
        )

    @property
    def tax(self):
        """The tax part of the total."""
        return self.total - self.subtotal
