from random import Random
from dataclasses import dataclass
from typing import List

from params import LamletParams


def get_rand_bytes(rnd: Random, n: int):
    ints = [rnd.getrandbits(8) for i in range(n)]
    #ints = [i % 256 for i in range(n)]
    return bytes(ints)


def byte_to_bits(byt: int):
    assert 0 <= byt < 256
    bits = []
    for _ in range(8):
        bits.append(byt & 1)
        byt = byt >> 1
    assert byt == 0
    return bits


def bytes_to_bits(byts: bytes):
    bits = []
    for byt in byts:
        bits += byte_to_bits(byt)
    return bits


def bits_to_bytes(bits: List[int]):
    assert len(bits) % 8 == 0
    assert all(bit in (0, 1) for bit in bits)
    byt = 0
    byts = []
    f = 1
    for index, bit in enumerate(bits):
        byt += bit * f
        f = f << 1
        if index % 8 == 7:
            byts.append(byt)
            byt = 0
            f = 1
    byts = bytes(byts)
    return byts


def uint_to_list_of_uints(value: int, width: int, length: int):
    reduced = value
    ints = []
    f = 1 << width
    for index in range(length):
        ints.append(reduced % f)
        reduced = reduced >> width
    assert reduced == 0
    return ints


def bits_to_int(bits: List[int]):
    value = 0
    for bit in reversed(bits):
        value = value << 1
        value += bit
    return value


def encode_into_words(params: LamletParams, data: bytes, ew: int):
    #print(f'encoding to ew {ew} data {[int(x) for x in data]}')
    assert len(data) % params.vline_bytes == 0
    words = []
    for vline_index in range(len(data)//params.vline_bytes):
        vline_data = data[vline_index*params.vline_bytes: (vline_index+1)*params.vline_bytes]
        bits = bytes_to_bits(vline_data)
        n_elements = params.vline_bytes*8//ew
        elements = [bits[n*ew: (n+1)*ew] for n in range(n_elements)]
        n_words = params.j_in_l
        vline_words = [[] for i in range(n_words)]
        for el_index in range(n_elements):
            vline_words[el_index % n_words] += elements[el_index]
        for index in range(n_words):
            assert len(vline_words[index]) == params.word_bytes * 8
            vline_words[index] = bits_to_bytes(vline_words[index])
        #print(f'result is {[[int(x) for x in data] for data in words]}')
        words += vline_words
    for word in words:
        assert len(word) == params.word_bytes
    return words


def decode_from_words(params: LamletParams, words: List[bytes], ew: int):
    n_words = params.j_in_l
    assert len(words) == n_words
    assert all(len(word) == params.word_bytes for word in words)
    #bits = bytes_to_bits(data)
    n_elements = params.vline_bytes*8//ew
    #elements = [bits[n*ew: (n+1)*ew] for n in range(n_elements)]
    #n_words = params.j_in_L
    #words = [[] for i in range(n_words)]
    bit_words = [bytes_to_bits(word) for word in words]
    bits = []
    for el_index in range(n_elements):
        word_index = el_index % n_words
        el_in_word = el_index//n_words
        el_bits = bit_words[word_index][el_in_word*ew: (el_in_word+1)*ew]
        bits += el_bits
    data = bits_to_bytes(bits)
    return data


@dataclass
class GetWordMessage:

    v_index: int
    vw_index: int
    shift_left: int
    bit_mask: int


def extract_words(params: LamletParams, src_words: List[List[int]], messages: List[List[GetWordMessage]]):
    """
    src_words is three vectors
    We want to get the middle dst vector.
    """
    assert len(src_words) == params.j_in_l * 3
    word_mask = (1 << params.word_bytes*8) - 1
    words = []
    for word_index, word_messages in enumerate(messages):
        word = 0
        for msg_index, message in enumerate(word_messages):
            src_word = src_words[message.vw_index + params.j_in_l*(1+message.v_index)]
            src_word_int = int.from_bytes(src_word, byteorder='little', signed=False)
            #print(f'vw_index {word_index} msg_index {msg_index}')
            #print(f'src_word is {[int(x) for x in src_word]}')
            if message.shift_left < 0:
                shifted = (src_word_int << (-message.shift_left)) & word_mask
            else:
                shifted = src_word_int >> message.shift_left
            #print(f'shifted is {uint_to_list_of_uints(shifted, 8, params.word_bytes)}')
            masked = shifted & message.bit_mask
            #print(f'masked is {uint_to_list_of_uints(masked, 8, params.word_bytes)}')
            old_word = word
            word = word & (~message.bit_mask)
            word = word | masked
            #print(f'word is {uint_to_list_of_uints(word, 8, params.word_bytes)}')
            old_word_bytes = old_word.to_bytes(params.word_bytes, byteorder='little', signed=False)
            word_bytes = word.to_bytes(params.word_bytes, byteorder='little', signed=False)
        byts = word.to_bytes(params.word_bytes, byteorder='little', signed=False)
        words.append(byts)
    return words


def split_by_factors(value, factors):
    reduced = value
    pieces = []
    for factor in factors:
        pieces.append(reduced % factor)
        reduced = reduced//factor
    assert reduced == 0
    return pieces


def join_by_factors(values, factors):
    assert len(values) == len(factors)
    f = 1
    total = 0
    for value, factor in zip(values, factors):
        assert value < factor
        total += value * f
        f *= factor
    return total

def create_messages_large_src_ew(params: LamletParams, src_ew: int, dst_ew: int, offset: int, start_element: int, n_elements: int):
    n_vectors = 4
    ww = params.word_bytes * 8
    assert src_ew >= dst_ew
    ratio = src_ew//dst_ew
    messages = []
    for dst_vw in range(params.j_in_l):   # word in vector
        uses = {}
        for dst_we in range(ww//dst_ew):
            dst_ve = join_by_factors([dst_vw, dst_we], [params.j_in_l, ww//dst_ew])
            if dst_ve < start_element or dst_ve >= start_element + n_elements:
                continue
            dst_eb = 0
            dst_wb = join_by_factors([dst_eb, dst_we],  [dst_ew, ww//dst_ew])
            logical_address = join_by_factors([dst_eb, dst_vw, dst_we], [dst_ew, params.j_in_l, ww//dst_ew])
            offset_address = logical_address + offset
            src_eb, src_vw, src_we, src_v = split_by_factors(offset_address, [src_ew, params.j_in_l, ww//src_ew, n_vectors])
            src_wb = join_by_factors([src_eb, src_we], [src_ew, ww/src_ew])
            shift = src_wb - dst_wb
            mask = [0] * ww
            # Can we get the full dst_ew bits?
            if (src_eb + dst_ew) < src_ew:
                # Yes we can
                avail_bits = dst_ew
            else:
                avail_bits = src_ew - src_eb
            mask[dst_we*dst_ew+dst_eb: dst_we*dst_ew+dst_eb + avail_bits] = [1] * avail_bits
            if src_vw not in uses:
                uses[src_vw] = []
            uses[src_vw].append((src_v, shift, mask))
            #print(f'------')
            #print(f'dst_vw = {dst_vw}, dst_eb = {dst_eb}, dst_we = {dst_we}')
            #print(f'offset address is {offset_address}')
            #print(f'src_v = {src_v}, src_vw = {src_vw}, src_eb = {src_eb}, src_we = {src_we}')
            #print(f'shift is {shift}, mask is {mask}')
            if avail_bits < dst_ew:
                dst_eb = avail_bits
                dst_wb = join_by_factors([dst_eb, dst_we],  [dst_ew, ww//dst_ew])
                logical_address = join_by_factors([dst_eb, dst_vw, dst_we], [dst_ew, params.j_in_l, ww//dst_ew])
                offset_address = logical_address + offset
                src_eb, src_vw, src_we, src_v = split_by_factors(offset_address, [src_ew, params.j_in_l, ww//src_ew, n_vectors])
                src_wb = join_by_factors([src_eb, src_we], [src_ew, ww/src_ew])
                shift = src_wb - dst_wb
                mask = [0] * ww
                mask[dst_we*dst_ew+dst_eb: dst_we*dst_ew+dst_eb + (dst_ew - avail_bits)] = [1] * (dst_ew - avail_bits)
                if src_vw not in uses:
                    uses[src_vw] = []
                uses[src_vw].append((src_v, shift, mask))
                #print(f'------')
                #print(f'dst_vw = {dst_vw}, dst_eb = {dst_eb}, dst_we = {dst_we}')
                #print(f'offset address is {offset_address}')
                #print(f'src_v = {src_v}, src_vw = {src_vw}, src_eb = {src_eb}, src_we = {src_we}')
                #print(f'shift is {shift}, mask is {mask}')
        word_messages = []
        for src_vw, addrs_shifts_and_masks in uses.items():
            for src_v, shift, mask in addrs_shifts_and_masks:
                bit_mask = bits_to_int(mask)
                message = GetWordMessage(
                    v_index=src_v,
                    vw_index=src_vw,
                    shift_left=shift,
                    bit_mask=bit_mask,
                    )
                word_messages.append(message)
        messages.append(word_messages)
    return messages


def create_messages_small_src_ew(params: LamletParams, src_ew: int, dst_ew: int, offset: int, start_element: int, n_elements: int):
    n_vectors = 4
    ww = params.word_bytes * 8
    assert dst_ew >= src_ew
    ratio = dst_ew//src_ew
    messages = []
    for dst_vw in range(params.j_in_l):   # word in vector
        uses = {}
        for index in range(dst_ew//src_ew):
            dst_eb = src_ew * index
            src_ebs = []
            for dst_we in range(ww//dst_ew):
                dst_ve = join_by_factors([dst_vw, dst_we], [params.j_in_l, ww//dst_ew])
                if dst_ve < start_element or dst_ve >= start_element + n_elements:
                    continue
                dst_wb = join_by_factors([dst_eb, dst_we],  [dst_ew, ww//dst_ew])
                #dst_vw_U, dst_vw_L = split_by_factors(dst_vw, [ratio, params.j_in_l//ratio])
                #dst_eb_U, dst_eb_L = split_by_factors(dst_eb, [ratio, src_ew])
                logical_address = join_by_factors([dst_eb, dst_vw, dst_we], [dst_ew, params.j_in_l, ww//dst_ew])
                offset_address = logical_address + offset
                src_eb, src_vw, src_we, src_v = split_by_factors(offset_address, [src_ew, params.j_in_l, ww//src_ew, n_vectors])
                src_wb = join_by_factors([src_eb, src_we], [src_ew, ww/src_ew])
                shift = src_wb - dst_wb
                mask = [0] * ww
                mask[dst_we*dst_ew+dst_eb: dst_we*dst_ew+dst_eb + (src_ew-src_eb)] = [1] * (src_ew - src_eb)
                #mask[src_we*src_ew+src_eb: (src_we+1)*src_ew] = [1] * (src_ew-src_eb)
                if src_vw not in uses:
                    uses[src_vw] = []
                uses[src_vw].append((src_v, shift, mask))
                src_ebs.append(src_eb)
                #print(f'------')
                #print(f'dst_vw = {dst_vw}, dst_eb = {dst_eb}, dst_we = {dst_we}')
                #print(f'offset address is {offset_address}')
                #print(f'src_v = {src_v}, src_vw = {src_vw}, src_eb = {src_eb}, src_we = {src_we}')
                #print(f'shift is {shift}, mask is {mask}')
            # # As we increment dst_we we increment src_we_U. That will give us a similar segment for a different element in the word.
            # # Because src_we_U maps to the upper bits of the logical address any increase by a multiple of the src_we_U
            # # factor cannot effect any other bits in the address, since it can't overflow into another region.
            # # The shift won't change because this will change the src_wb and dst_wb by the same amount.
            # # The mask will change in a simple way that just shifts the ones.
            # # The src_vw should stay the same
            # assert len(uses) == 1
            # assert len(set(x.shift for x in uses.values())) == 1
            # assert len(set(src_ebs)) == 1
            prev_src_eb = src_ebs[0]

            # Now let's get the other half of those segments if we only got partial segments.
            if prev_src_eb != 0:
                required_bits = prev_src_eb
                dst_eb = index*src_ew + src_ew - prev_src_eb
                for dst_we in range(ww//dst_ew):
                    dst_ve = join_by_factors([dst_vw, dst_we], [params.j_in_l, ww//dst_ew])
                    if dst_ve < start_element or dst_ve >= start_element + n_elements:
                        continue
                    dst_wb = join_by_factors([dst_eb, dst_we],  [dst_ew, ww//dst_ew])
                    logical_address = join_by_factors([dst_eb, dst_vw, dst_we], [dst_ew, params.j_in_l, ww//dst_ew])
                    offset_address = logical_address + offset
                    src_eb, src_vw, src_we, src_v = split_by_factors(offset_address, [src_ew, params.j_in_l, ww//src_ew, n_vectors])
                    src_wb = join_by_factors([src_eb, src_we], [src_ew, ww//src_ew])
                    # We expect that the src_vw has incremented since the overflow from src_eb will flow into that
                    # The shift will also be different since the overflow will effect the wb in src and dst differently.
                    shift = src_wb - dst_wb
                    mask = [0] * ww
                    mask[dst_we*dst_ew+dst_eb: dst_we*dst_ew+dst_eb + required_bits] = [1] * required_bits
                    if src_vw not in uses:
                        uses[src_vw] = []
                    uses[src_vw].append((src_v, shift, mask))
                    #print(f'------')
                    #print(f'dst_vw = {dst_vw}, dst_eb = {dst_eb}, dst_we = {dst_we}')
                    #print(f'offset address is {offset_address}')
                    #print(f'src_v = {src_v}, src_vw = {src_vw}, src_eb = {src_eb}, src_we = {src_we}')
                    #print(f'shift is {shift}, mask is {mask}')
        word_messages = []
        for src_vw, addrs_shifts_and_masks in uses.items():
            for src_v, shift, mask in addrs_shifts_and_masks:
                bit_mask = bits_to_int(mask)
                message = GetWordMessage(
                    v_index=src_v,
                    vw_index=src_vw,
                    shift_left=shift,
                    bit_mask=bit_mask,
                    )
                word_messages.append(message)
        messages.append(word_messages)
    return messages


def create_messages(params: LamletParams, src_ew: int, dst_ew: int, offset: int, start_element: int, n_elements: int):
    """
    Works out what READ_WORD messages need to be sent
      src_ew: The src element width
      dst_ew: The dst element width
      offset: The src offset in bits
      start_element: Which element in the vector we start on.
      n_elements: The number of elements to copy.
    """
    if src_ew <= dst_ew:
        return create_messages_small_src_ew(params, src_ew, dst_ew, offset, start_element, n_elements)
    else:
        return create_messages_large_src_ew(params, src_ew, dst_ew, offset, start_element, n_elements)


@dataclass
class SmallParams:

    word_bytes: int = 2
    j_in_l: int = 4

    @property
    def vline_bytes(self):
        return self.j_in_l * self.word_bytes


def apply_offset(rnd, data: bytes, offset: int):
    bits = bytes_to_bits(data)
    fresh_bits = [rnd.randint(0, 1) for _ in range(offset)]
    if offset > 0:
        bits = fresh_bits + bits[:-offset]
    else:
        bits = bits[offset:] + fresh_bits
    byts = bits_to_bytes(bits)
    return byts


def test_convertion(params: LamletParams, src_ew: int, dst_ew: int, offset: int):
    rnd = Random(0)
    vlb = params.vline_bytes
    random_data = get_rand_bytes(rnd, vlb*3)
    shifted_data = apply_offset(rnd, random_data, offset)
    src_words = encode_into_words(params, random_data, src_ew)
    expected_dst_words = encode_into_words(params, shifted_data[vlb: 2*vlb], dst_ew)
    print(f'src_words = {[[int(x) for x in word] for word in src_words]}')
    print(f'expected_dst_words = {[[int(x) for x in word] for word in expected_dst_words]}')
    n_elements = params.vline_bytes * 8 // dst_ew
    messages = create_messages(params=params, src_ew=src_ew, dst_ew=dst_ew, offset=offset, start_element=0, n_elements=n_elements)
    dst_words = extract_words(params, src_words, messages)
    rcvd_data = decode_from_words(params, dst_words, dst_ew)
    if offset % 8 == 0:
        expected_data = random_data[params.vline_bytes + offset//8: 2*params.vline_bytes + offset//8]
    else:
        random_bits = bytes_to_bits(random_data)
        expected_bits = random_bits[params.vline_bytes * 8 + offset: params.vline_bytes * 2 * 8 + offset]
        expected_data = bits_to_bytes(expected_bits)
    assert expected_data == rcvd_data


def main():
    params = SmallParams(word_bytes=8)
    for src_ew in (1, 2, 4, 8, 16, 32, 64):
        for dst_ew in (1, 2, 4, 8, 16, 32, 64):
            for offset in range(params.vline_bytes*8):
                test_convertion(params, src_ew, dst_ew, offset)


if __name__ == '__main__':
    main()
