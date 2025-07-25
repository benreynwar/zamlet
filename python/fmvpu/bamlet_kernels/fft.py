"""
Generates a kernel for a bamlet to do an FFT.
"""

import math
import cmath

from fmvpu.bamlet.bamlet_params import BamletParams
from fmvpu.utils import uint_to_bits, bits_to_uint, clog2


def is_power_two(x):
    if x == 1:
        return True
    n = x//2
    if x != 2*n:
        return False
    return is_power_two(n)


def get_twiddles(n):
    return [cmath.exp(-((0+1j)*i)/n*2*math.pi) for i in range(n)]


def reverse_bit_reorder(data):
    new_data = [None] * len(data)
    address_bits = clog2(len(data))
    for address, d in enumerate(data):
        reversed_addr = bits_to_uint(list(reversed(uint_to_bits(address, address_bits))))
        new_data[reversed_addr] = d
    assert None not in new_data
    return new_data


def fft_stage(data, twiddles, stage_index):
    n = len(data)
    n_stages = clog2(n)
    step = pow(2, stage_index)
    twiddle_step = pow(2, n_stages-1-stage_index)
    new_data = [None] * n
    for index in range(n//step//2):
        for subindex in range(step):
            addr1 = (2*index) * step + subindex
            addr2 = (2*index+1) * step + subindex
            a1 = data[addr1]
            a2 = data[addr2]
            tw_addr = (subindex * twiddle_step) % (n//2)
            tw = twiddles[tw_addr]
            b1 = a1 + a2 * tw
            b2 = a1 - a2 * tw
            new_data[addr1] = b1
            new_data[addr2] = b2
            print(f'a1={a1} a2={a2} tw={tw}  -> b1={b1} b2={b2}')
    assert None not in new_data
    print(f'stage {stage_index}: {data} -> {new_data}')
    return new_data

            
def fft_model(data):
    data = reverse_bit_reorder(data)
    assert is_power_two(len(data))
    twiddles = get_twiddles(len(data))
    n_stages = clog2(len(data))
    for stage_index in range(n_stages):
        data = fft_stage(data, twiddles, stage_index)
    return data


def generate_fft_kernel(params: BamletParams, fft_size: int):
    n_amlets = params.n_amlets
    assert is_power_two(n_amlets)
    assert is_power_two(fft_size)
    local_fft_size = fft_size / n_amlets
    # Receive the twiddle factors and write to the data memory.
    # Write a the fft size to a1
    # Write the number of stages to a2


def main():
    import numpy
    import random
    rnd = random.Random(0)
    data = [rnd.random()+rnd.random()*(0+1j) for i in range(64)]
    model = fft_model(data)
    actual = numpy.fft.fft(data)
    for m, a in zip(model, actual):
        assert abs(m - a) < 1e-6
    print(get_twiddles(8))


if __name__ == '__main__':
    main()

