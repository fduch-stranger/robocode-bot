"""Nearest-neighbour and range stores replacing ``ags.utils.KdTree`` and
``lxx.data_analysis``.

The kd-tree keeps Rednaxela's contract that the gun relies on (squared
Euclidean distances, bucketed leaves, k nearest sorted ascending). The range
store replaces the Java ``RTree`` with a bucketed list; both return the same
points, only the traversal differs.
"""
from __future__ import annotations

import heapq
import math

from tomcat_port.lxx_utils import IntervalDouble


class _KdNode:
    __slots__ = ("points", "values", "split_dim", "split_value", "left", "right", "min_bounds", "max_bounds")

    def __init__(self, dimensions: int) -> None:
        self.points: list[list[float]] | None = []
        self.values: list | None = []
        self.split_dim = -1
        self.split_value = 0.0
        self.left: _KdNode | None = None
        self.right: _KdNode | None = None
        self.min_bounds = [math.inf] * dimensions
        self.max_bounds = [-math.inf] * dimensions


class KdTree:
    """Bucketed kd-tree with squared Euclidean distance."""

    BUCKET_SIZE = 24

    def __init__(self, dimensions: int, size_limit: int | None = None) -> None:
        self.dimensions = dimensions
        self.size_limit = size_limit
        self.root = _KdNode(dimensions)
        self._size = 0

    @property
    def size(self) -> int:
        return self._size

    def add_point(self, location: list[float], value) -> None:
        node = self.root
        while node.points is None:
            self._extend_bounds(node, location)
            node = node.right if location[node.split_dim] > node.split_value else node.left
            assert node is not None
        self._extend_bounds(node, location)
        node.points.append(list(location))
        node.values.append(value)
        self._size += 1
        if len(node.points) > self.BUCKET_SIZE:
            self._split(node)

    def _extend_bounds(self, node: _KdNode, location: list[float]) -> None:
        for i in range(self.dimensions):
            value = location[i]
            if value < node.min_bounds[i]:
                node.min_bounds[i] = value
            if value > node.max_bounds[i]:
                node.max_bounds[i] = value

    def _split(self, node: _KdNode) -> None:
        widths = [node.max_bounds[i] - node.min_bounds[i] for i in range(self.dimensions)]
        split_dim = max(range(self.dimensions), key=lambda i: widths[i])
        if widths[split_dim] <= 0:
            return
        assert node.points is not None and node.values is not None
        values_on_dim = sorted(point[split_dim] for point in node.points)
        split_value = values_on_dim[len(values_on_dim) // 2]
        if split_value == node.max_bounds[split_dim]:
            split_value = (node.min_bounds[split_dim] + node.max_bounds[split_dim]) / 2.0
        left = _KdNode(self.dimensions)
        right = _KdNode(self.dimensions)
        for point, value in zip(node.points, node.values):
            child = right if point[split_dim] > split_value else left
            self._extend_bounds(child, point)
            child.points.append(point)
            child.values.append(value)
        if not left.points or not right.points:
            return
        node.split_dim = split_dim
        node.split_value = split_value
        node.left = left
        node.right = right
        node.points = None
        node.values = None

    def nearest_neighbor(self, location: list[float], count: int) -> list[tuple[float, object]]:
        """Return up to ``count`` (squared distance, value) pairs, nearest first."""
        if count <= 0 or self._size == 0:
            return []
        heap: list[tuple[float, int, object]] = []  # max-heap via negative distance
        counter = 0
        dims = self.dimensions

        def bounds_distance(node: _KdNode) -> float:
            total = 0.0
            for i in range(dims):
                value = location[i]
                if value < node.min_bounds[i]:
                    delta = node.min_bounds[i] - value
                    total += delta * delta
                elif value > node.max_bounds[i]:
                    delta = value - node.max_bounds[i]
                    total += delta * delta
            return total

        def visit(node: _KdNode) -> None:
            nonlocal counter
            if node.points is not None:
                for point, value in zip(node.points, node.values):
                    distance = 0.0
                    for i in range(dims):
                        delta = point[i] - location[i]
                        distance += delta * delta
                    if len(heap) < count:
                        heapq.heappush(heap, (-distance, counter, value))
                        counter += 1
                    elif distance < -heap[0][0]:
                        heapq.heapreplace(heap, (-distance, counter, value))
                        counter += 1
                return
            assert node.left is not None and node.right is not None
            first, second = (node.right, node.left) if location[node.split_dim] > node.split_value else (node.left, node.right)
            visit(first)
            if len(heap) < count or bounds_distance(second) < -heap[0][0]:
                visit(second)

        visit(self.root)
        return [(-neg_distance, value) for neg_distance, _, value in sorted(heap, key=lambda item: -item[0])]

    def range_search(self, ranges: list[IntervalDouble]) -> list:
        """Return the values of every point inside the axis-aligned box ``ranges``."""
        result: list = []
        dims = self.dimensions
        lows = [interval.a for interval in ranges]
        highs = [interval.b for interval in ranges]
        stack = [self.root]
        while stack:
            node = stack.pop()
            skip = False
            for i in range(dims):
                if highs[i] < node.min_bounds[i] or lows[i] > node.max_bounds[i]:
                    skip = True
                    break
            if skip:
                continue
            if node.points is not None:
                for point, value in zip(node.points, node.values):
                    inside = True
                    for i in range(dims):
                        coordinate = point[i]
                        if coordinate < lows[i] or coordinate > highs[i]:
                            inside = False
                            break
                    if inside:
                        result.append(value)
                continue
            assert node.left is not None and node.right is not None
            stack.append(node.left)
            stack.append(node.right)
        return result


def plain_location(ts, attributes) -> list[float]:
    return [ts.get_attr_value(attribute) for attribute in attributes]


def normal_location(ts, attributes) -> list[float]:
    return [ts.get_attr_value(attribute) / attribute.max_range.length for attribute in attributes]


class LxxDataPoint:
    __slots__ = ("location", "ts", "payload")

    def __init__(self, location: list[float], ts, payload) -> None:
        self.location = location
        self.ts = ts
        self.payload = payload

    @classmethod
    def create_plain_point(cls, ts, payload, attributes) -> LxxDataPoint:
        return cls(plain_location(ts, attributes), ts, payload)


class GunKdTreeEntry(LxxDataPoint):
    __slots__ = ("distance", "normal_weighted_distance")

    def __init__(self, ts, attributes) -> None:
        super().__init__(normal_location(ts, attributes), ts, attributes)
        self.distance = 0.0
        self.normal_weighted_distance = 0.0


class KdTreeAdapter:
    def __init__(self, attributes, size_limit: int) -> None:
        self.attributes = attributes
        self._delegate = KdTree(len(attributes), size_limit)

    def add_entry(self, entry: GunKdTreeEntry) -> None:
        self._delegate.add_point(entry.location, entry)

    def get_nearest_neighbours(self, ts, count: int | None = None) -> list[GunKdTreeEntry]:
        if count is None:
            count = int(math.sqrt(self._delegate.size))
        result: list[GunKdTreeEntry] = []
        for distance, entry in self._delegate.nearest_neighbor(normal_location(ts, self.attributes), count):
            entry.distance = distance
            result.append(entry)
        return result


class RangeStore:
    """Replacement for ``lxx.data_analysis.r_tree.RTree``: exact range search on a kd-tree."""

    def __init__(self, attributes) -> None:
        self.attributes = attributes
        self._tree = KdTree(len(attributes))

    @property
    def size(self) -> int:
        return self._tree.size

    def insert(self, entry: LxxDataPoint) -> None:
        self._tree.add_point(entry.location, entry)

    def range_search(self, ranges: list[IntervalDouble]) -> list[LxxDataPoint]:
        return self._tree.range_search(ranges)
