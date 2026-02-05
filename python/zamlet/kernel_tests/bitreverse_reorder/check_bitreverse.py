def clog2(value):
    """
    >>> clog2(4)
    2
    >>> clog2(1)
    0
    >>> clog2(2)
    1
    >>> clog2(17)
    5
    """
    n = 0
    value = value - 1
    while value > 0:
        n += 1
        value = value >> 1
    return n

def bitreverse(value, n_bits):
    """
    >>> bitreverse(2, 2)
    1
    >>> bitreverse(3, 2)
    3
    >>> bitreverse(3, 4)
    12
    """
    reversed_value = 0
    for bit_index in range(n_bits):
        if value & (1 << bit_index):
            reversed_value |= (1 << (n_bits-1 - bit_index))
    return reversed_value


def bitreverse_a(n, vector_size):
    """
    Works out what addresses we should read for each vector if we're trying to do a bit reversal
    of the address space with vector operations.
    """
    assert n >= vector_size * vector_size
    assert n % vector_size == 0
    n_operations = n//vector_size
    all_addresses = []
    middle_size = n//vector_size//vector_size
    for cycle in range(n_operations):
        addresses = []
        for index in range(vector_size):
            address = (
                    index * (n//vector_size) +
                    (index + cycle*vector_size + cycle//middle_size) % (vector_size * middle_size)
                    )
            addresses.append(address)
        all_addresses.append(addresses)
    check_addresses(all_addresses, n, vector_size)


def check_addresses(all_addresses, n, vector_size):

    flattened_addresses = []
    for addresses in all_addresses:
        flattened_addresses += addresses
    assert set(flattened_addresses) == set(list(range(n)))

    for addresses in all_addresses:
        fronts = []
        backs = []
        for address in addresses:
            front = address % vector_size
            back = bitreverse(address, clog2(n)) % vector_size
            fronts.append(front)
            backs.append(back)
        assert set(fronts) == set(list(range(vector_size)))
        assert set(backs) == set(list(range(vector_size)))


def bitreverse_b(n, vector_size):
    assert n < vector_size * vector_size
    assert n >= vector_size
    all_addresses = []
    for cycle in range(n//vector_size):
        addresses = []
        for index in range(vector_size):
            section_size = vector_size * vector_size // n
            section_index = index//section_size
            index_in_section = index % section_size
            address = (
                    vector_size * section_index +
                    (index_in_section * n//vector_size + section_index + cycle) % vector_size
                    )
            addresses.append(address)
        all_addresses.append(addresses)
    check_addresses(all_addresses, n, vector_size)


def bitreverse_ab(n, vector_size):
    if n < vector_size * vector_size:
        bitreverse_b(n, vector_size)
    else:
        bitreverse_a(n, vector_size)



if __name__ == '__main__':
    for vector_size in (2, 4, 8, 16, 32, 64, 128):
        for n in (2, 4, 8, 16, 32, 64, 128):
            if n >= vector_size:
                print(vector_size, n)
                bitreverse_ab(n, vector_size)




