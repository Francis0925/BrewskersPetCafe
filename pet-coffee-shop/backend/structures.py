# Brewskers data structures
# Hand-written HashTable, Queue and Stack. No dict, deque or list-as-queue shortcuts
# are used for the structure itself.


class _Entry:
    """One key/value pair inside a hash table bucket (a singly linked chain)."""

    __slots__ = ("key", "value", "next")

    def __init__(self, key, value, next_entry=None):
        self.key = key
        self.value = value
        self.next = next_entry


class HashTable:
    """Hash table with separate chaining and automatic resizing.

    Keys can be ints or strings (product ID, SKU). Average put/get/remove is O(1).
    """

    INITIAL_CAPACITY = 16
    MAX_LOAD_FACTOR = 0.75

    def __init__(self, capacity=INITIAL_CAPACITY):
        self._capacity = max(4, capacity)
        self._buckets = [None] * self._capacity
        self._size = 0

    # Hashing

    def _hash(self, key):
        """Our own hash function, so we do not lean on Python's hash()."""
        if isinstance(key, int):
            # Knuth multiplicative hash for integers
            return (key * 2654435761) % (2 ** 32)

        # djb2 for strings (SKUs are case-insensitive)
        value = 5381
        for char in str(key).strip().upper():
            value = ((value << 5) + value + ord(char)) % (2 ** 32)
        return value

    @staticmethod
    def _normalize(key):
        return key.strip().upper() if isinstance(key, str) else key

    def _index(self, key):
        return self._hash(key) % self._capacity

    # Core operations

    def put(self, key, value):
        key = self._normalize(key)
        index = self._index(key)
        node = self._buckets[index]

        while node is not None:
            if node.key == key:
                node.value = value  # update existing key
                return
            node = node.next

        self._buckets[index] = _Entry(key, value, self._buckets[index])
        self._size += 1

        if self._size / self._capacity > self.MAX_LOAD_FACTOR:
            self._resize(self._capacity * 2)

    def get(self, key, default=None):
        key = self._normalize(key)
        node = self._buckets[self._index(key)]

        while node is not None:
            if node.key == key:
                return node.value
            node = node.next

        return default

    def contains(self, key):
        sentinel = object()
        return self.get(key, sentinel) is not sentinel

    def remove(self, key):
        """Remove a key. Returns True if it existed."""
        key = self._normalize(key)
        index = self._index(key)
        node = self._buckets[index]
        previous = None

        while node is not None:
            if node.key == key:
                if previous is None:
                    self._buckets[index] = node.next
                else:
                    previous.next = node.next
                self._size -= 1
                return True
            previous = node
            node = node.next

        return False

    def clear(self):
        self._buckets = [None] * self.INITIAL_CAPACITY
        self._capacity = self.INITIAL_CAPACITY
        self._size = 0

    def values(self):
        result = []
        for head in self._buckets:
            node = head
            while node is not None:
                result.append(node.value)
                node = node.next
        return result

    def _resize(self, new_capacity):
        old_buckets = self._buckets
        self._capacity = new_capacity
        self._buckets = [None] * new_capacity
        self._size = 0

        for head in old_buckets:
            node = head
            while node is not None:
                self.put(node.key, node.value)
                node = node.next

    def __len__(self):
        return self._size

    def __contains__(self, key):
        return self.contains(key)


class _Node:
    __slots__ = ("value", "next")

    def __init__(self, value):
        self.value = value
        self.next = None


class Queue:
    """FIFO queue backed by a singly linked list with head and tail pointers.

    enqueue and dequeue are both O(1).
    """

    def __init__(self):
        self._head = None
        self._tail = None
        self._size = 0

    def enqueue(self, value):
        node = _Node(value)

        if self._tail is None:
            self._head = self._tail = node
        else:
            self._tail.next = node
            self._tail = node

        self._size += 1

    def dequeue(self):
        """Remove and return the front item. Raises IndexError when empty."""
        if self._head is None:
            raise IndexError("dequeue from an empty queue")

        node = self._head
        self._head = node.next

        if self._head is None:
            self._tail = None

        self._size -= 1
        return node.value

    def peek(self):
        if self._head is None:
            raise IndexError("peek at an empty queue")
        return self._head.value

    def remove_where(self, predicate):
        """Remove the first item matching predicate, wherever it is in the line.

        Used when a customer's order is cancelled or completed out of turn.
        Returns the removed item, or None.
        """
        previous = None
        node = self._head

        while node is not None:
            if predicate(node.value):
                if previous is None:
                    self._head = node.next
                else:
                    previous.next = node.next

                if node is self._tail:
                    self._tail = previous

                self._size -= 1
                return node.value

            previous = node
            node = node.next

        return None

    def to_list(self):
        """Front-to-back snapshot, for display."""
        items = []
        node = self._head
        while node is not None:
            items.append(node.value)
            node = node.next
        return items

    def clear(self):
        self._head = self._tail = None
        self._size = 0

    def is_empty(self):
        return self._size == 0

    def __len__(self):
        return self._size


class Stack:
    """LIFO stack backed by a linked list. push, pop and peek are O(1).

    An optional max_size drops the oldest entries so undo history cannot grow forever.
    """

    def __init__(self, max_size=None):
        self._top = None
        self._size = 0
        self._max_size = max_size

    def push(self, value):
        node = _Node(value)
        node.next = self._top
        self._top = node
        self._size += 1

        if self._max_size and self._size > self._max_size:
            self._drop_bottom()

    def pop(self):
        """Remove and return the newest item. Raises IndexError when empty."""
        if self._top is None:
            raise IndexError("pop from an empty stack")

        node = self._top
        self._top = node.next
        self._size -= 1
        return node.value

    def peek(self):
        if self._top is None:
            raise IndexError("peek at an empty stack")
        return self._top.value

    def _drop_bottom(self):
        node = self._top
        while node.next is not None and node.next.next is not None:
            node = node.next
        node.next = None
        self._size -= 1

    def clear(self):
        self._top = None
        self._size = 0

    def is_empty(self):
        return self._size == 0

    def __len__(self):
        return self._size
