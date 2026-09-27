"""A bucketed kd-tree standing in for Rednaxela's ``ags.utils.KdTree`` (the
``WeightedSqrEuclid`` variant Diamond uses, with its optional size limit that
evicts the oldest point) and for the third-generation tree behind the
perceptual gun.

The structure follows the original: 24-point buckets, splits on the widest
weighted axis at the midpoint, bucket doubling when a node has no width, and
an exact nearest-neighbour search with bounds pruning. Distances are weighted
squared Euclidean distances, as ``Entry.distance`` was in Java.
"""
from __future__ import annotations

import math
from collections import deque
from heapq import heappush, heapreplace

BUCKET_SIZE = 24


class Entry:
    __slots__ = ("distance", "value")

    def __init__(self, distance: float, value) -> None:
        self.distance = distance
        self.value = value


class _Node:
    __slots__ = (
        "points",
        "values",
        "scaled",
        "scaled_version",
        "capacity",
        "count",
        "left",
        "right",
        "split_dimension",
        "split_value",
        "min_limit",
        "max_limit",
        "parent",
    )

    def __init__(self, parent: "_Node | None", capacity: int) -> None:
        self.points: list[tuple[float, ...]] | None = []
        self.values: list | None = []
        self.scaled: list[tuple[float, ...]] | None = None
        self.scaled_version = -1
        self.capacity = capacity
        self.count = 0
        self.left: _Node | None = None
        self.right: _Node | None = None
        self.split_dimension = 0
        self.split_value = 0.0
        self.min_limit: list[float] | None = None
        self.max_limit: list[float] | None = None
        self.parent = parent

    def extend_bounds(self, location: tuple[float, ...]) -> None:
        if self.min_limit is None:
            self.min_limit = list(location)
            self.max_limit = list(location)
            return
        min_limit = self.min_limit
        max_limit = self.max_limit
        for i, value in enumerate(location):
            if value != value:  # NaN
                min_limit[i] = math.nan
                max_limit[i] = math.nan
            elif min_limit[i] > value:
                min_limit[i] = value
            elif max_limit[i] < value:
                max_limit[i] = value


class KdTree:
    def __init__(self, dimensions: int, size_limit: int | None = None) -> None:
        self.dimensions = dimensions
        self.weights = [1.0] * dimensions
        self._weights_version = 0
        self.size_limit = size_limit
        self._root = _Node(None, BUCKET_SIZE)
        self._location_stack: deque[tuple[float, ...]] | None = deque() if size_limit is not None else None

    def set_weights(self, weights: list[float]) -> None:
        new_weights = list(weights)
        if new_weights != self.weights:
            self.weights = new_weights
            self._weights_version += 1

    def size(self) -> int:
        return self._root.count

    # Insertion --------------------------------------------------------------
    def add_point(self, location, value) -> None:
        point = tuple(float(v) for v in location)
        cursor = self._root
        while cursor.points is None or cursor.count >= cursor.capacity:
            if cursor.points is not None:
                if not self._split(cursor):
                    break
            cursor.count += 1
            cursor.extend_bounds(point)
            cursor = cursor.right if point[cursor.split_dimension] > cursor.split_value else cursor.left
        cursor.points.append(point)
        cursor.values.append(value)
        if cursor.scaled is not None:
            cursor.scaled = None
        cursor.count += 1
        cursor.extend_bounds(point)

        if self._location_stack is not None:
            self._location_stack.append(point)
            if self._root.count > self.size_limit:
                self._remove_old()

    def _split(self, node: _Node) -> bool:
        node.split_dimension = self._find_widest_axis(node)
        split_dimension = node.split_dimension
        min_value = node.min_limit[split_dimension]
        max_value = node.max_limit[split_dimension]
        split_value = (min_value + max_value) * 0.5
        if split_value == math.inf:
            split_value = 1.7976931348623157e308
        elif split_value == -math.inf:
            split_value = -1.7976931348623157e308
        elif split_value != split_value:
            split_value = 0.0
        if min_value == max_value:
            # No width on any axis: double the bucket instead of splitting.
            node.capacity *= 2
            return False
        if split_value == max_value:
            split_value = min_value
        node.split_value = split_value

        left = _Node(node, max(BUCKET_SIZE, node.count))
        right = _Node(node, max(BUCKET_SIZE, node.count))
        for point, value in zip(node.points, node.values):
            child = right if point[split_dimension] > split_value else left
            child.points.append(point)
            child.values.append(value)
            child.count += 1
            child.extend_bounds(point)
        node.left = left
        node.right = right
        node.points = None
        node.values = None
        node.scaled = None
        return True

    def _find_widest_axis(self, node: _Node) -> int:
        weights = self.weights
        widest = 0
        width = (node.max_limit[0] - node.min_limit[0]) * weights[0]
        if width != width:
            width = 0.0
        for i in range(1, self.dimensions):
            new_width = (node.max_limit[i] - node.min_limit[i]) * weights[i]
            if new_width != new_width:
                new_width = 0.0
            if new_width > width:
                widest = i
                width = new_width
        return widest

    def _remove_old(self) -> None:
        location = self._location_stack.popleft()
        cursor = self._root
        while cursor.points is None:
            cursor = cursor.right if location[cursor.split_dimension] > cursor.split_value else cursor.left
        points = cursor.points
        for i in range(len(points)):
            if points[i] is location:
                del points[i]
                del cursor.values[i]
                if cursor.scaled is not None:
                    del cursor.scaled[i]
                node: _Node | None = cursor
                while node is not None:
                    node.count -= 1
                    node = node.parent
                return

    # Search ----------------------------------------------------------------------
    def _scaled_points(self, node: _Node) -> list[tuple[float, ...]]:
        if node.scaled is None or node.scaled_version != self._weights_version:
            weights = self.weights
            node.scaled = [tuple(v * w for v, w in zip(point, weights)) for point in node.points]
            node.scaled_version = self._weights_version
        return node.scaled

    def _region_distance(self, location: tuple[float, ...], node: _Node) -> float:
        min_limit = node.min_limit
        max_limit = node.max_limit
        weights = self.weights
        d = 0.0
        for i, value in enumerate(location):
            if value > max_limit[i]:
                diff = (value - max_limit[i]) * weights[i]
            elif value < min_limit[i]:
                diff = (value - min_limit[i]) * weights[i]
            else:
                continue
            if diff == diff:
                d += diff * diff
        return d

    def nearest_neighbor(self, location, count: int) -> list[Entry]:
        root = self._root
        if count <= 0 or root.count == 0:
            return []
        count = min(count, root.count)
        query = tuple(float(v) for v in location)
        weights = self.weights
        scaled_query = tuple(v * w for v, w in zip(query, weights))
        dist = math.dist
        heap: list[tuple[float, int, object]] = []  # (-distance, tie, value)
        tie = 0
        stack = [root]
        while stack:
            node = stack.pop()
            if node.count == 0:
                continue
            full = len(heap) >= count
            if full and node.min_limit is not None and self._region_distance(query, node) > -heap[0][0]:
                continue
            if node.points is None:
                if query[node.split_dimension] > node.split_value:
                    stack.append(node.left)
                    stack.append(node.right)
                else:
                    stack.append(node.right)
                    stack.append(node.left)
                continue
            scaled = self._scaled_points(node)
            values = node.values
            for i in range(len(scaled)):
                d = dist(scaled[i], scaled_query)
                d *= d
                if len(heap) < count:
                    tie += 1
                    heappush(heap, (-d, tie, values[i]))
                elif d < -heap[0][0]:
                    tie += 1
                    heapreplace(heap, (-d, tie, values[i]))
        return [Entry(-neg, value) for neg, _, value in heap]
