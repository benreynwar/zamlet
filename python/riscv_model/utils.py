import struct


def log2ceil(value):
    assert value >= 0
    n_bits = 0
    while value > 0:
        n_bits += 1
        value = value >> 1
    return n_bits


def bytes_to_float(byts):
    assert len(byts) == 4
    float_val = struct.unpack('f', byts)[0]
    return float_val


def float_to_bytes(fl):
    byts = struct.pack('f', fl)
    assert len(byts) == 4
    return byts


def is_power_of_two(value):
    return (value == 2) or ((value > 1) and (value % 2 == 0) and (is_power_of_two(value//2)))
