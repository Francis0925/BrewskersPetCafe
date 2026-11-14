# Brewskers searching and sorting algorithms
# Hand-written merge sort, binary search and linear search. The built-in
# sorted() and list.index() are not used for the features that call these,
# so the algorithms themselves stay visible and testable.


def merge_sort(items, key=None):
    """Stable merge sort. Returns a new list, the input is not changed.

    Time is O(n log n) in the best, average and worst case. Space is O(n)
    for the left and right copies made while merging. Stable means items
    with equal keys keep their original order, which matters when sorting
    by a key like (category, name) where the first part can tie.
    """
    if len(items) <= 1:
        return list(items)

    get_key = key if key is not None else (lambda item: item)
    middle = len(items) // 2
    left = merge_sort(items[:middle], key)
    right = merge_sort(items[middle:], key)
    return _merge(left, right, get_key)


def _merge(left, right, get_key):
    """Combine two already sorted lists into one sorted list."""
    merged = []
    i = 0
    j = 0
    while i < len(left) and j < len(right):
        # Strict comparison on the right side only, so on a tie the item
        # from the left list goes first. That is what keeps the sort stable.
        if get_key(right[j]) < get_key(left[i]):
            merged.append(right[j])
            j += 1
        else:
            merged.append(left[i])
            i += 1
    merged.extend(left[i:])
    merged.extend(right[j:])
    return merged


def binary_search(sorted_items, target, key=None):
    """Iterative binary search for an exact match. Returns an index, or -1.

    The list must already be sorted by the same key, and the target must
    compare equal to a whole key. Time is O(log n) because each loop pass
    halves the remaining range. Space is O(1).
    """
    get_key = key if key is not None else (lambda item: item)
    low = 0
    high = len(sorted_items) - 1
    while low <= high:
        middle = (low + high) // 2
        value = get_key(sorted_items[middle])
        if value == target:
            return middle
        if value < target:
            low = middle + 1
        else:
            high = middle - 1
    return -1


def linear_search(items, predicate):
    """Front to back scan returning the first index where predicate is true.

    Works on unsorted data and on any condition, unlike binary search which
    needs sorted input and an exact target. Time is O(n), space is O(1).
    """
    for index, item in enumerate(items):
        if predicate(item):
            return index
    return -1
