"""A small, offline QR code maker for the Classroom Quiz join address.

Only what the quiz needs: byte mode, error correction level M, versions 1-6
(up to 106 characters, far more than an address like http://192.168.137.1:8800).
Follows the QR Code standard (ISO/IEC 18004); no outside library or internet needed.
"""
from __future__ import annotations

from functools import lru_cache

# version: (error-correction codewords per block, [(blocks, data codewords per block), ...])
_LEVEL_M = {
    1: (10, [(1, 16)]),
    2: (16, [(1, 28)]),
    3: (26, [(1, 44)]),
    4: (18, [(2, 32)]),
    5: (24, [(2, 43)]),
    6: (16, [(4, 27)]),
}
_ALIGNMENT = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34]}
_REMAINDER_BITS = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7}
_FORMAT_LEVEL_M = 0  # the two format bits for level M

# Galois field GF(256) with the QR polynomial x^8 + x^4 + x^3 + x^2 + 1.
_EXP = [0] * 512
_LOG = [0] * 256
_value = 1
for _power in range(255):
    _EXP[_power] = _value
    _LOG[_value] = _power
    _value <<= 1
    if _value & 0x100:
        _value ^= 0x11D
for _power in range(255, 512):
    _EXP[_power] = _EXP[_power - 255]


def _multiply(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _generator(degree: int) -> list[int]:
    poly = [1]
    for power in range(degree):
        poly = [
            (poly[index] if index < len(poly) else 0) ^ (_multiply(poly[index - 1], _EXP[power]) if index else 0)
            for index in range(len(poly) + 1)
        ]
    return poly


def _error_codewords(data: list[int], degree: int) -> list[int]:
    generator = _generator(degree)
    remainder = list(data) + [0] * degree
    for index in range(len(data)):
        factor = remainder[index]
        if factor:
            for offset, coefficient in enumerate(generator):
                remainder[index + offset] ^= _multiply(coefficient, factor)
    return remainder[len(data):]


def _pick_version(length: int) -> int:
    for version, (_, groups) in _LEVEL_M.items():
        capacity = sum(blocks * size for blocks, size in groups)
        # 4 mode bits + 8 count bits, then the bytes themselves.
        if 12 + 8 * length <= capacity * 8:
            return version
    raise ValueError("Text is too long for this QR code maker.")


def _codewords(payload: bytes, version: int) -> list[int]:
    ec_size, groups = _LEVEL_M[version]
    capacity = sum(blocks * size for blocks, size in groups)
    bits: list[int] = []

    def put(value: int, width: int) -> None:
        bits.extend((value >> shift) & 1 for shift in range(width - 1, -1, -1))

    put(0b0100, 4)            # byte mode
    put(len(payload), 8)      # character count (versions 1-9)
    for byte in payload:
        put(byte, 8)
    put(0, min(4, capacity * 8 - len(bits)))  # terminator
    while len(bits) % 8:
        bits.append(0)
    data = [int("".join(map(str, bits[index:index + 8])), 2) for index in range(0, len(bits), 8)]
    pad = 0
    while len(data) < capacity:
        data.append((0xEC, 0x11)[pad % 2])
        pad += 1

    blocks, position = [], 0
    for count, size in groups:
        for _ in range(count):
            blocks.append(data[position:position + size])
            position += size
    errors = [_error_codewords(block, ec_size) for block in blocks]
    result = []
    for index in range(max(len(block) for block in blocks)):
        result.extend(block[index] for block in blocks if index < len(block))
    for index in range(ec_size):
        result.extend(error[index] for error in errors)
    return result


class _Grid:
    def __init__(self, version: int):
        self.size = 17 + 4 * version
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.fixed = [[False] * self.size for _ in range(self.size)]

    def set(self, x: int, y: int, dark: bool) -> None:
        self.dark[y][x] = dark
        self.fixed[y][x] = True


def _format_bits(mask: int) -> int:
    data = (_FORMAT_LEVEL_M << 3) | mask
    remainder = data
    for _ in range(10):
        remainder = (remainder << 1) ^ ((remainder >> 9) * 0x537)
    return ((data << 10) | remainder) ^ 0x5412


def _bit(value: int, index: int) -> bool:
    return (value >> index) & 1 == 1


def _draw_format(grid: _Grid, mask: int) -> None:
    bits = _format_bits(mask)
    size = grid.size
    for index in range(6):
        grid.set(8, index, _bit(bits, index))
    grid.set(8, 7, _bit(bits, 6))
    grid.set(8, 8, _bit(bits, 7))
    grid.set(7, 8, _bit(bits, 8))
    for index in range(9, 15):
        grid.set(14 - index, 8, _bit(bits, index))
    for index in range(8):
        grid.set(size - 1 - index, 8, _bit(bits, index))
    for index in range(8, 15):
        grid.set(8, size - 15 + index, _bit(bits, index))
    grid.set(8, size - 8, True)  # the dark module


def _draw_function_patterns(grid: _Grid, version: int) -> None:
    size = grid.size
    for index in range(size):
        grid.set(6, index, index % 2 == 0)
        grid.set(index, 6, index % 2 == 0)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < size and 0 <= y < size:
                    grid.set(x, y, max(abs(dx), abs(dy)) not in (2, 4))
    positions = _ALIGNMENT[version]
    last = len(positions) - 1
    for i, cx in enumerate(positions):
        for j, cy in enumerate(positions):
            if (i, j) in ((0, 0), (0, last), (last, 0)):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    grid.set(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
    _draw_format(grid, 0)  # reserves the format areas; redrawn once the mask is chosen


def _place_data(grid: _Grid, codewords: list[int], remainder_bits: int) -> None:
    bits = [(word >> shift) & 1 for word in codewords for shift in range(7, -1, -1)] + [0] * remainder_bits
    size, index, right = grid.size, 0, grid.size - 1
    while right >= 1:
        if right == 6:
            right = 5
        upward = ((right + 1) & 2) == 0
        for step in range(size):
            y = size - 1 - step if upward else step
            for x in (right, right - 1):
                if not grid.fixed[y][x] and index < len(bits):
                    grid.dark[y][x] = bits[index] == 1
                    index += 1
        right -= 2


def _masked(mask: int, x: int, y: int) -> bool:
    """The eight standard mask patterns."""
    if mask == 0:
        return (x + y) % 2 == 0
    if mask == 1:
        return y % 2 == 0
    if mask == 2:
        return x % 3 == 0
    if mask == 3:
        return (x + y) % 3 == 0
    if mask == 4:
        return (x // 3 + y // 2) % 2 == 0
    if mask == 5:
        return x * y % 2 + x * y % 3 == 0
    if mask == 6:
        return (x * y % 2 + x * y % 3) % 2 == 0
    return ((x + y) % 2 + x * y % 3) % 2 == 0


def _apply_mask(grid: _Grid, mask: int) -> list[list[bool]]:
    return [
        [grid.dark[y][x] ^ (not grid.fixed[y][x] and _masked(mask, x, y)) for x in range(grid.size)]
        for y in range(grid.size)
    ]


def _penalty(modules: list[list[bool]]) -> int:
    size, score = len(modules), 0
    lines = modules + [list(column) for column in zip(*modules)]
    finder_like = ([True, False, True, True, True, False, True, False, False, False, False],
                   [False, False, False, False, True, False, True, True, True, False, True])
    for line in lines:
        run, previous = 0, None
        for value in line:
            if value == previous:
                run += 1
            else:
                if run >= 5:
                    score += run - 2
                run, previous = 1, value
        if run >= 5:
            score += run - 2
        for start in range(size - 10):
            if line[start:start + 11] in finder_like:
                score += 40
    for y in range(size - 1):
        for x in range(size - 1):
            if modules[y][x] == modules[y][x + 1] == modules[y + 1][x] == modules[y + 1][x + 1]:
                score += 3
    dark = sum(map(sum, modules))
    score += 10 * (abs(dark * 20 - size * size * 10) // (size * size))
    return score


@lru_cache(maxsize=32)
def matrix(text: str) -> tuple[tuple[bool, ...], ...]:
    """The QR code for `text` as rows of dark (True) / light (False) modules."""
    payload = text.encode("utf-8")
    version = _pick_version(len(payload))
    grid = _Grid(version)
    _draw_function_patterns(grid, version)
    _place_data(grid, _codewords(payload, version), _REMAINDER_BITS[version])
    best = None
    for mask in range(8):
        _draw_format(grid, mask)
        modules = _apply_mask(grid, mask)
        score = _penalty(modules)
        if best is None or score < best[0]:
            best = (score, modules)
    return tuple(tuple(row) for row in best[1])


def svg(text: str, quiet_zone: int = 4) -> str:
    """The QR code as a small black-on-white SVG image."""
    modules = matrix(text)
    size = len(modules) + 2 * quiet_zone
    path = "".join(
        f"M{x + quiet_zone} {y + quiet_zone}h1v1h-1z"
        for y, row in enumerate(modules)
        for x, dark in enumerate(row)
        if dark
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'shape-rendering="crispEdges" role="img" aria-label="QR code">'
        f'<rect width="{size}" height="{size}" fill="#fff"/>'
        f'<path d="{path}" fill="#000"/></svg>'
    )
