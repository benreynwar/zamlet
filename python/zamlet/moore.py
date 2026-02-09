"""
Moore curve coordinate mapping for square power-of-2 grids.

A Moore curve is a closed space-filling curve constructed from four
rotated Hilbert sub-curves. It maps a linear index to (x, y) coordinates
such that adjacent indices are spatially adjacent, and the path forms
a closed loop.
"""


def _hilbert_rot(n, x, y, rx, ry):
    """Rotate/flip a quadrant for Hilbert curve computation."""
    if ry == 0:
        if rx == 1:
            x = n - 1 - x
            y = n - 1 - y
        x, y = y, x
    return x, y


def _hilbert_d2xy(n, d):
    """Convert index d to (x, y) on a Hilbert curve for an n x n grid.

    n must be a power of 2.
    """
    x = y = 0
    s = 1
    while s < n:
        rx = 1 if (d & 2) else 0
        ry = 1 if (d & 1) ^ rx else 0
        x, y = _hilbert_rot(s, x, y, rx, ry)
        x += s * rx
        y += s * ry
        d //= 4
        s *= 2
    return x, y


def _hilbert_xy2d(n, x, y):
    """Convert (x, y) to index d on a Hilbert curve for an n x n grid.

    n must be a power of 2.
    """
    d = 0
    s = n // 2
    while s > 0:
        rx = 1 if (x & s) > 0 else 0
        ry = 1 if (y & s) > 0 else 0
        d += s * s * ((3 * rx) ^ ry)
        x, y = _hilbert_rot(s, x, y, rx, ry)
        s //= 2
    return d


def moore_d2xy(n, d):
    """Convert index d to (x, y) on a Moore curve for an n x n grid.

    n must be a power of 2 and >= 2.
    """
    half = n // 2
    quarter = half * half
    quadrant = d // quarter
    local_d = d % quarter
    hx, hy = _hilbert_d2xy(half, local_d)
    if quadrant == 0:
        # Bottom-left: Hilbert rotated 90 degrees CCW
        x = half - 1 - hy
        y = hx
    elif quadrant == 1:
        # Top-left: Hilbert rotated 90 degrees CCW
        x = half - 1 - hy
        y = hx + half
    elif quadrant == 2:
        # Top-right: Hilbert rotated 90 degrees CW
        x = hy + half
        y = half - 1 - hx + half
    else:
        # Bottom-right: Hilbert rotated 90 degrees CW
        x = hy + half
        y = half - 1 - hx
    return x, y


def moore_xy2d(n, x, y):
    """Convert (x, y) to index d on a Moore curve for an n x n grid.

    n must be a power of 2 and >= 2.
    """
    half = n // 2
    quarter = half * half
    if x < half and y < half:
        hx = y
        hy = half - 1 - x
        return 0 * quarter + _hilbert_xy2d(half, hx, hy)
    elif x < half and y >= half:
        hx = y - half
        hy = half - 1 - x
        return 1 * quarter + _hilbert_xy2d(half, hx, hy)
    elif x >= half and y >= half:
        hx = n - 1 - y
        hy = x - half
        return 2 * quarter + _hilbert_xy2d(half, hx, hy)
    else:
        hx = half - 1 - y
        hy = x - half
        return 3 * quarter + _hilbert_xy2d(half, hx, hy)


def test_moore():
    for n in (2, 4, 8, 16):
        seen = set()
        for d in range(n * n):
            x, y = moore_d2xy(n, d)
            assert 0 <= x < n and 0 <= y < n, f"n={n} d={d}: out of bounds"
            assert (x, y) not in seen, f"n={n} d={d}: duplicate coord"
            seen.add((x, y))
            assert moore_xy2d(n, x, y) == d, f"n={n} d={d}: roundtrip failed"
        # All cells visited
        assert len(seen) == n * n
        # Adjacent indices are spatially adjacent (Manhattan distance 1)
        for d in range(n * n):
            x1, y1 = moore_d2xy(n, d)
            x2, y2 = moore_d2xy(n, (d + 1) % (n * n))
            dist = abs(x2 - x1) + abs(y2 - y1)
            assert dist == 1, (
                f"n={n} d={d}->({x1},{y1}), d={d+1}->({x2},{y2}): "
                f"dist={dist}"
            )
    print("All Moore curve tests passed")


if __name__ == '__main__':
    test_moore()
