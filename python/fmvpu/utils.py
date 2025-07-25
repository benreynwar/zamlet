def uint_to_bits(value, width):
    """
    >> uint_to_bits(3)
    [1, 1]
    >> uint_to_bits(16)
    [0, 0, 0, 0, 1]
    """
    bits = []
    for i in range(width):
        bits.append(value % 2)
        value = value // 2
    assert not value
    return bits

def bits_to_uint(bits):
    """
    >> bits_to_uint([1, 0, 1, 1])
    13
    """
    value = 0
    for bit in reversed(bits):
        value = value*2 + bit
    return value


def make_seed(rnd):
    return rnd.getrandbits(32)


def clog2(value: int) -> int:
    """Calculate ceiling log2 - how many bits are required to represent 'value-1'."""
    value = value - 1
    bits = 0
    while value > 0:
        value = value >> 1
        bits += 1
    return bits
