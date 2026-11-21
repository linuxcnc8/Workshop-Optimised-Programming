"""Points on a B-spline or NURBS curve (de Boor's algorithm), in pure Python.

Used by the STEP import (spline edges of a part) and meant for the DXF import of splines too (requirement C4).
Points are tuples of any dimension; `weights` makes the curve rational (NURBS).
"""

from __future__ import annotations

from collections.abc import Sequence

Vector = tuple[float, ...]


def expand_knots(multiplicities: Sequence[int], knots: Sequence[float]) -> list[float]:
    """The full knot vector from distinct knots and their multiplicities (as STEP and IGES write them)."""
    full: list[float] = []
    for count, knot in zip(multiplicities, knots):
        full += [float(knot)] * int(count)
    return full


def _span(knots: Sequence[float], degree: int, count: int, u: float) -> int:
    """Index k with knots[k] <= u < knots[k + 1], clamped to the valid range of the curve."""
    low, high = degree, count - 1
    if u >= knots[high + 1]:
        return high
    if u <= knots[low]:
        return low
    while low < high:
        middle = (low + high + 1) // 2
        if knots[middle] <= u:
            low = middle
        else:
            high = middle - 1
    return low


def curve_point(
    degree: int, points: Sequence[Vector], knots: Sequence[float], u: float, weights: Sequence[float] | None = None
) -> Vector:
    """The point of the curve at parameter u. `knots` is the full vector (len(points) + degree + 1 values)."""
    count = len(points)
    if len(knots) != count + degree + 1:
        raise ValueError(f"a B-spline of degree {degree} with {count} points needs {count + degree + 1} knots")
    dimension = len(points[0])
    k = _span(knots, degree, count, u)
    if weights is None:
        work = [list(points[k - degree + j]) + [1.0] for j in range(degree + 1)]
    else:
        work = []
        for j in range(degree + 1):
            w = weights[k - degree + j]
            work.append([c * w for c in points[k - degree + j]] + [w])
    for r in range(1, degree + 1):
        for j in range(degree, r - 1, -1):
            i = k - degree + j
            span = knots[i + degree - r + 1] - knots[i]
            alpha = 0.0 if span == 0 else (u - knots[i]) / span
            work[j] = [(1 - alpha) * a + alpha * b for a, b in zip(work[j - 1], work[j])]
    result = work[degree]
    return tuple(c / result[dimension] for c in result[:dimension])


def parameter_range(degree: int, knots: Sequence[float]) -> tuple[float, float]:
    return knots[degree], knots[len(knots) - degree - 1]


def sample_curve(
    degree: int, points: Sequence[Vector], knots: Sequence[float], count: int, weights: Sequence[float] | None = None
) -> list[tuple[float, Vector]]:
    """`count` (parameter, point) pairs spread evenly over the parameter range, both ends included."""
    start, end = parameter_range(degree, knots)
    count = max(count, 2)
    return [
        (u, curve_point(degree, points, knots, u, weights))
        for u in (start + (end - start) * i / (count - 1) for i in range(count))
    ]
