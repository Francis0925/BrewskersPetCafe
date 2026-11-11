# Brewskers POS in-memory state built on the data structures in structures.py
#
#   ProductIndex  HashTable of products by product_id (rebuilt from the database when stale)
#   OrderQueue    Queue of queued orders, oldest first. Enqueue on order, dequeue on completion
#   StatusUndo    Stack per user of order status changes, so the last change can be undone
#
# The database stays the source of truth. These structures are rebuilt from it on demand.

import threading

from backend.algorithms import linear_search, merge_sort
from backend.helpers import query
from backend.structures import HashTable, Queue, Stack

_lock = threading.RLock()


class ProductIndex:
    def __init__(self):
        self._table = HashTable()
        self._loaded = False

    def invalidate(self):
        """Call after anything changes products (add, stock, hide, import, order stock)."""
        with _lock:
            self._loaded = False

    def _load(self):
        self._table.clear()
        for product in query("SELECT * FROM products"):
            self._table.put(product["product_id"], product)
        self._loaded = True

    def get(self, product_id):
        with _lock:
            if not self._loaded:
                self._load()
            return self._table.get(int(product_id))

    def sellable(self):
        """Available, in-stock products, ordered like the POS grid."""
        with _lock:
            if not self._loaded:
                self._load()
            items = [p for p in self._table.values() if p["status"] == "available" and p["stock"] > 0]
        # Merge sort keeps the POS grid grouped by category then name.
        return merge_sort(items, key=lambda p: (p["category"], p["name"]))


class OrderQueue:
    def __init__(self):
        self._queue = Queue()
        self._loaded = False

    def invalidate(self):
        with _lock:
            self._loaded = False

    def _load(self):
        self._queue.clear()
        rows = query(
            """SELECT order_id, order_no, customer_name, order_date
                 FROM orders WHERE COALESCE(status, 'queued') = 'queued'
                ORDER BY order_date ASC, order_id ASC"""
        )
        for row in rows:
            self._queue.enqueue(row)
        self._loaded = True

    def _ensure(self):
        if not self._loaded:
            self._load()

    def enqueue(self, order):
        with _lock:
            # A fresh load already includes orders saved to the database, so skip the duplicate.
            just_loaded = not self._loaded
            self._ensure()
            if just_loaded and any(o["order_id"] == order["order_id"] for o in self._queue.to_list()):
                return
            self._queue.enqueue(order)

    def dequeue(self):
        """Complete the order at the front of the line. Returns it, or None if empty."""
        with _lock:
            self._ensure()
            return None if self._queue.is_empty() else self._queue.dequeue()

    def remove(self, order_id):
        """Take a specific order out of the line (cancelled, or completed out of turn)."""
        with _lock:
            self._ensure()
            if not self._queue.is_empty() and self._queue.peek()["order_id"] == order_id:
                return self._queue.dequeue()
            return self._queue.remove_where(lambda o: o["order_id"] == order_id)

    def position(self, order_id):
        """1-based place in line, or None."""
        with _lock:
            self._ensure()
            # Linear search because the queue is ordered by arrival time,
            # not by order_id, so a binary search cannot be used here.
            index = linear_search(self._queue.to_list(), lambda o: o["order_id"] == order_id)
            if index >= 0:
                return index + 1
        return None

    def snapshot(self):
        with _lock:
            self._ensure()
            return self._queue.to_list()


class StatusUndo:
    """One Stack of status changes per user. Each entry is (order_id, previous_status)."""

    MAX_HISTORY = 20

    def __init__(self):
        self._stacks = HashTable()

    def push(self, user_id, order_id, previous_status):
        with _lock:
            stack = self._stacks.get(int(user_id))
            if stack is None:
                stack = Stack(max_size=self.MAX_HISTORY)
                self._stacks.put(int(user_id), stack)
            stack.push((order_id, previous_status))

    def pop(self, user_id):
        with _lock:
            stack = self._stacks.get(int(user_id))
            if stack is None or stack.is_empty():
                return None
            return stack.pop()

    def depth(self, user_id):
        with _lock:
            stack = self._stacks.get(int(user_id))
            return 0 if stack is None else len(stack)

    def clear(self):
        with _lock:
            self._stacks = HashTable()


product_index = ProductIndex()
order_queue = OrderQueue()
status_undo = StatusUndo()


def reset_all():
    """Call after bulk data changes (imports, restore, reset)."""
    product_index.invalidate()
    order_queue.invalidate()
    status_undo.clear()
