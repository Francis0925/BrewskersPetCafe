# Brewskers custom exceptions
# The system raises these instead of built-in errors whenever a record or a
# checkout breaks a business rule. They share the RecordError base class so a
# route can catch the whole family of record problems with one except clause.

class RecordError(Exception):
    """Base class for every record problem in the system."""


class InvalidRecordError(RecordError, ValueError):
    """Raised when a record fails validation before it can be saved.

    It also inherits from ValueError, the built-in error the old validation
    code used, so existing except ValueError handlers keep working.
    """


class OutOfStockError(RecordError):
    """Raised when a cart asks for more stock than the shelf holds."""

    def __init__(self, name, requested, available):
        self.name = name
        self.requested = requested
        self.available = available
        super().__init__(
            f"Not enough stock for {name}: "
            f"requested {requested}, only {available} left"
        )


class InsufficientPaymentError(RecordError):
    """Raised when the cash handed over is less than the order total."""

    def __init__(self, total, paid):
        self.total = total
        self.paid = paid
        super().__init__("Amount tendered is less than the total")
