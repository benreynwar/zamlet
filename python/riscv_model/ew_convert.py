from random import Random
from dataclasses import dataclass
from typing import List, Dict, Tuple

from params import LamletParams
import utils
from utils import uint_to_list_of_uints


def get_rand_bytes(rnd: Random, n: int):
    #ints = [rnd.getrandbits(8) for i in range(n)]
    ints = [i % 256 for i in range(n)]
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


def bits_to_bytes(bits: List[int]) -> bytes:
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
    byts_as_bytes = bytes(byts)
    return byts_as_bytes


def bits_to_int(bits: List[int]):
    value = 0
    for bit in reversed(bits):
        value = value << 1
        value += bit
    return value


@dataclass(frozen=True)
class MemMapping:
    # The vector line index in the small-ew-mapped vector
    src_v: int
    # The word index inside a vector in the small-ew-mapped vector
    src_vw: int
    # The element index inside a vector in the small-ew-mapped vector
    src_ve: int
    # The bit in the word
    src_wb: int
    # The vector line index in the large-ew-mapped vector
    dst_v: int
    # The word index inside a vector in the large-ew-mapped vector
    dst_vw: int
    # The element index inside a vector in the large-ew-mapped vector
    dst_ve: int
    # The bit in the word
    dst_wb: int
    # The number of bits that are mapped
    n_bits: int

    # # The amount of bits that we shift the bits to the left inside the word
    # # when going from the large-ew-mapped vector to the small-ew-mapped vector
    # shift: int
    # # The bit mask to apply when updating the word in the small-ew-mapped vector
    # mask: int

    # The tag use to refer to this mapping for a small-ew-mapped word
    src_tag: int
    # The tag use to refer to this mapping for a large-ew-mapped word
    dst_tag: int

    def dst_mask(self) -> int:
        return ((1 << self.n_bits) - 1) << self.dst_wb
            

@dataclass(frozen=True)
class SmallLargeMapping:
    # The vector line index in the small-ew-mapped vector
    small_v: int
    # The word index inside a vector in the small-ew-mapped vector
    small_vw: int
    # The element index inside a vector in the small-ew-mapped vector
    small_ve: int
    # The bit in the word
    small_wb: int
    # The vector line index in the large-ew-mapped vector
    large_v: int
    # The word index inside a vector in the large-ew-mapped vector
    large_vw: int
    # The element index inside a vector in the large-ew-mapped vector
    large_ve: int
    # The bit in the word
    large_wb: int
    # The number of bits that are mapped
    n_bits: int

    # # The amount of bits that we shift the bits to the left inside the word
    # # when going from the large-ew-mapped vector to the small-ew-mapped vector
    # shift: int
    # # The bit mask to apply when updating the word in the small-ew-mapped vector
    # mask: int

    # The tag use to refer to this mapping for a small-ew-mapped word
    small_tag: int
    # The tag use to refer to this mapping for a large-ew-mapped word
    large_tag: int

    def normalize(self):
        # Normalize to small_v = 0
        return SmallLargeMapping(
            small_v=0,
            small_vw=self.small_vw,
            small_ve=self.small_ve,
            small_wb=self.small_wb,
            large_v=self.large_v - self.small_v,
            large_vw=self.large_vw,
            large_ve=self.large_ve,
            large_wb=self.large_wb,
            n_bits=self.n_bits,
            #shift=self.shift,
            #mask=self.mask,
            small_tag=self.small_tag,
            large_tag=self.large_tag,
            )


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
        vline_words: List[List[int]] = [[] for i in range(n_words)]
        vline_words_as_bytes: List[bytes] = [bytes() for i in range(n_words)]
        for el_index in range(n_elements):
            vline_words[el_index % n_words] += elements[el_index]
        for index in range(n_words):
            assert len(vline_words[index]) == params.word_bytes * 8
            vline_words_as_bytes[index] = bits_to_bytes(vline_words[index])
        #print(f'result is {[[int(x) for x in data] for data in words]}')
        words += vline_words_as_bytes
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


def extract_words(params: LamletParams, src_words: List[bytes], src_ew: int, dst_ew: int, src_offset: int):
    """
    src_words is three vectors
    We want to get the middle dst vector.
    """
    assert len(src_words) == params.j_in_l * 3
    word_mask = (1 << params.word_bytes*8) - 1
    small_ew = min(src_ew, dst_ew)
    ww = params.word_bytes * 8
    n_tags = ww//small_ew * 2
    words = []
    dst_v = 1
    for dst_vw in range(params.j_in_l):
        updating_word = 0
        for tag in range(n_tags):
            if dst_ew > src_ew:
                src_is_small = True
                mapping = get_mapping_from_large_tag(
                        params=params, small_ew=src_ew, large_ew=dst_ew, small_offset=src_offset,
                        large_offset=0, large_v=dst_v, large_vw=dst_vw, large_tag=tag)
                if mapping is None:
                    continue
                src_word = src_words[mapping.small_vw + params.j_in_l*mapping.small_v]
            else:
                src_is_small = False
                mapping = get_mapping_from_small_tag(
                        params=params, small_ew=dst_ew, large_ew=src_ew, small_offset=0,
                        large_offset=src_offset, small_v=dst_v, small_vw=dst_vw, small_tag=tag)
                if mapping is None:
                    continue
                src_word = src_words[mapping.large_vw + params.j_in_l*mapping.large_v]
            src_word_as_int = int.from_bytes(src_word, byteorder='little')
            #print(f'dst vw_index {word_index} msg_index {msg_index} tag={message.tag}')
            #print(f'src_word is {[int(x) for x in src_word]}')
            if not src_is_small:
                # Work out shift to lsb
                shift = mapping.large_wb - mapping.small_wb
                mask = ((1 << mapping.n_bits)-1) << mapping.small_wb
            else:
                shift = mapping.small_wb - mapping.large_wb
                mask = ((1 << mapping.n_bits)-1) << mapping.large_wb
            if shift < 0:
                shifted = (src_word_as_int << (-shift)) & word_mask
            else:
                shifted = src_word_as_int >> shift
            masked = shifted & mask
            #print(f'shifted is {uint_to_list_of_uints(shifted, 8, params.word_bytes)}')
            #print(f'bit_mask is {bin(mask)}')
            #print(f'masked is {uint_to_list_of_uints(masked, 8, params.word_bytes)}')
            masked_word = updating_word & (~mask)
            new_word = masked_word | masked
            #print(f'word is {uint_to_list_of_uints(new_word, 8, params.word_bytes)}')
            old_word_bytes = src_word
            word_bytes = new_word.to_bytes(params.word_bytes, byteorder='little', signed=False)
            updating_word = new_word
        byts = updating_word.to_bytes(params.word_bytes, byteorder='little', signed=False)
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

def get_mapping_for_dst(
        params: LamletParams, src_ew: int, dst_ew: int,
        dst_v: int, dst_vw: int, dst_tag: int, src_offset: int=0, dst_offset: int=0):
    if src_ew > dst_ew:
        small_ew = dst_ew
        large_ew = src_ew
        small_offset = dst_offset
        large_offset = src_offset
        small_v = dst_v
        small_vw = dst_vw
        small_tag = dst_tag
        mapping = get_mapping_from_small_tag(
                params=params, small_ew=small_ew, large_ew=large_ew,
                small_offset=small_offset, large_offset=large_offset,
                small_v=small_v, small_vw=small_vw, small_tag=small_tag)
        if mapping is None:
            return None
        mem_mapping = MemMapping(
                src_v=mapping.large_v,
                src_vw=mapping.large_vw,
                src_ve=mapping.large_ve,
                src_wb=mapping.large_wb,
                dst_v=mapping.small_v,
                dst_vw=mapping.small_vw,
                dst_ve=mapping.small_ve,
                dst_wb=mapping.small_wb,
                n_bits=mapping.n_bits,
                src_tag=mapping.large_tag,
                dst_tag=mapping.small_tag,
                )
    else:
        small_ew = src_ew
        large_ew = dst_ew
        small_offset = src_offset
        large_offset = 0
        large_v = dst_v
        large_vw = dst_vw
        large_tag = dst_tag
        mapping = get_mapping_from_large_tag(
                params=params, small_ew=small_ew, large_ew=large_ew,
                small_offset=small_offset, large_offset=large_offset,
                large_v=large_v, large_vw=large_vw, large_tag=large_tag)
        if mapping is None:
            return None
        mem_mapping = MemMapping(
                src_v=mapping.small_v,
                src_vw=mapping.small_vw,
                src_ve=mapping.small_ve,
                src_wb=mapping.small_wb,
                dst_v=mapping.large_v,
                dst_vw=mapping.large_vw,
                dst_ve=mapping.large_ve,
                dst_wb=mapping.large_wb,
                n_bits=mapping.n_bits,
                src_tag=mapping.small_tag,
                dst_tag=mapping.large_tag,
                )
    return mem_mapping


def get_mapping_for_src(
        params: LamletParams, src_ew: int, dst_ew: int,
        src_v: int, src_vw: int, src_tag: int, src_offset:int=0, dst_offset:int=0):
    if dst_ew > src_ew:
        small_ew = src_ew
        large_ew = dst_ew
        small_offset = src_offset
        large_offset = dst_offset
        small_v = src_v
        small_vw = src_vw
        small_tag = src_tag
        mapping = get_mapping_from_small_tag(
                params=params, small_ew=small_ew, large_ew=large_ew,
                small_offset=small_offset, large_offset=large_offset,
                small_v=small_v, small_vw=small_vw, small_tag=small_tag)
        if mapping is None:
            return None
        mem_mapping = MemMapping(
                src_v=mapping.small_v,
                src_vw=mapping.small_vw,
                src_ve=mapping.small_ve,
                src_wb=mapping.small_wb,
                dst_v=mapping.large_v,
                dst_vw=mapping.large_vw,
                dst_ve=mapping.large_ve,
                dst_wb=mapping.large_wb,
                n_bits=mapping.n_bits,
                src_tag=mapping.small_tag,
                dst_tag=mapping.large_tag,
                )
    else:
        small_ew = dst_ew
        large_ew = src_ew
        small_offset = dst_offset
        large_offset = 0
        large_v = src_v
        large_vw = src_vw
        large_tag = src_tag
        mapping = get_mapping_from_large_tag(
                params=params, small_ew=small_ew, large_ew=large_ew,
                small_offset=small_offset, large_offset=large_offset,
                large_v=large_v, large_vw=large_vw, large_tag=large_tag)
        if mapping is None:
            return None
        mem_mapping = MemMapping(
                src_v=mapping.large_v,
                src_vw=mapping.large_vw,
                src_ve=mapping.large_ve,
                src_wb=mapping.large_wb,
                dst_v=mapping.small_v,
                dst_vw=mapping.small_vw,
                dst_ve=mapping.small_ve,
                dst_wb=mapping.small_wb,
                n_bits=mapping.n_bits,
                src_tag=mapping.large_tag,
                dst_tag=mapping.small_tag,
                )
    return mem_mapping


def get_large_small_mapping(vw: int, ww: int, small_ew: int, large_ew: int,
                large_v: int, large_vw: int, large_we: int, large_eb: int,
                small_v: int, small_vw: int, small_we: int, small_eb: int):

    large_is_second_segment = (large_eb % small_ew) != 0
    large_tag = (large_we * large_ew//small_ew + large_eb//small_ew) * 2 + large_is_second_segment

    small_is_second_segment = (small_eb % small_ew) != 0
    small_tag = small_we * 2 + small_is_second_segment

    bits_to_end_of_large_element = large_ew - large_eb
    bits_to_end_of_small_element = small_ew - small_eb
    n_bits = min(bits_to_end_of_large_element, bits_to_end_of_small_element)
    mask = [0] * ww
    mask[small_we*small_ew+small_eb: small_we*small_ew+small_eb + n_bits] = [1] * n_bits
    mask_as_int = utils.list_of_uints_to_uint(mask, width=1)

    small_wb = join_by_factors([small_eb, small_we], [small_ew, ww//small_ew])
    small_ve = join_by_factors([small_we, small_vw], [ww//small_ew, vw//ww])
    large_wb = join_by_factors([large_eb, large_we], [large_ew, ww//large_ew])
    large_ve = join_by_factors([large_we, large_vw], [ww//large_ew, vw//ww])
    shift = large_wb - small_wb

    return SmallLargeMapping(
        small_v=small_v,
        small_vw=small_vw,
        small_ve=small_ve,
        small_wb=small_wb,
        large_v= large_v,
        large_vw=large_vw,
        large_ve=large_ve,
        large_wb=large_wb,
        n_bits=n_bits,
        small_tag=small_tag,
        large_tag=large_tag,
        )


def get_mapping_from_large_tag(
        params: LamletParams, small_ew: int, large_ew: int,
        small_offset: int, large_offset: int,
        large_v: int, large_vw: int, large_tag: int):
    """
    small_ew: The element width in the small-ew mapped vector
    large_ew: The element width in the large-ew mapped vector
    small_offset: The logical offset in bits of the small-ew mapped vector relative to the vector line.
    large_offset: The logical offset in bits of the large-ew mapped vector relative to the vector line.
    large_vw: Which word in the large-ew mapped vector we want the mapping for.
    large_tag: Which mapping tag.  Represent which segment of the word we want the mapping for.
    """

    vw = params.vline_bytes * 8
    ww = params.word_bytes * 8

    small_element_in_large_word_index = large_tag//2
    is_second_segment = large_tag % 2
    large_we = small_element_in_large_word_index * small_ew // large_ew
    large_eb = small_element_in_large_word_index * small_ew - large_we * large_ew

    if is_second_segment:
        # If we're in the second segment we need to increment large_eb forward to the
        # start of the next src element.
        if (large_offset - small_offset) % small_ew == 0:
            return None
        large_eb += small_ew - (large_eb + small_offset - large_offset) % small_ew
    else:
        # We're in the first segment. But has this segment been included in the previous
        # second segment.
        if (large_offset - small_offset) % small_ew != 0:
            small_element_in_large_element = large_eb//small_ew
            if small_element_in_large_element > 0:
                return None

    # n_vectors is the maximum number of vectors that we might access past the first
    # one. It's just used for splitting up the address.  It can be safely changed to
    # a larger power of two, and we'll get an error if it is too small.
    n_vectors = 4
    ww = params.word_bytes * 8  # word width in bits
    # Work out what the destination address is in the logical address space.
    large_logical_address = join_by_factors([large_eb, large_vw, large_we, large_v], [large_ew, params.j_in_l, ww//large_ew, n_vectors])
    address_in_large_vector = large_logical_address - large_offset
    # We're just copying the vector over.
    # This is where we would make a change if we where doing a strided access or something like that.
    address_in_small_vector = address_in_large_vector
    # In this space we do the offset to work out what the source address is in the logical address space.
    small_logical_address = address_in_small_vector + small_offset
    small_eb, small_vw, small_we, small_v = split_by_factors(small_logical_address, [small_ew, params.j_in_l, ww//small_ew, n_vectors])

    mapping = get_large_small_mapping(vw, ww, small_ew, large_ew,
                          large_v, large_vw, large_we, large_eb,
                          small_v, small_vw, small_we, small_eb)
    return mapping

def get_mapping_from_small_tag(
        params: LamletParams, small_ew: int, large_ew: int,
        small_offset: int, large_offset: int,
        small_v: int, small_vw: int, small_tag: int):
    """
    """
    vw = params.vline_bytes * 8
    ww = params.word_bytes * 8

    n_vectors = 4
    small_we = small_tag//2
    is_second_segment = small_tag % 2
    small_eb = 0

    # If we're in the second segment we need to increment small_eb forward to the
    # start of the next src element.
    if is_second_segment:
        # We need a second segment if the dst element spans 2 large_elements
        ww = params.word_bytes * 8  # word width in bits
        # FIXME: Quite a bit of work to see if we use the second segment.
        # Probably a better way exists.
        small_logical_address = join_by_factors([small_eb, small_vw, small_we, small_v], [small_ew, params.j_in_l, ww//small_ew, n_vectors])
        address_in_small_vector = small_logical_address - small_offset
        address_in_large_vector = address_in_small_vector
        large_logical_address = address_in_large_vector + large_offset
        large_eb, _, _, _ = split_by_factors(large_logical_address, [large_ew, params.j_in_l, ww//large_ew, n_vectors])
        bits_to_end_of_large_element = large_ew - large_eb
        bits_to_end_of_small_element = small_ew - small_eb
        if bits_to_end_of_large_element >= bits_to_end_of_small_element:
            return None
        small_eb += bits_to_end_of_large_element
    # n_vectors is the maximum number of vectors that we might access past the first
    # one. It's just used for splitting up the address.  It can be safely changed to
    # a larger power of two, and we'll get an error if it is too small.
    n_vectors = 4
    small_ve = join_by_factors([small_vw, small_we], [params.j_in_l, ww//small_ew])
    small_wb = join_by_factors([small_eb, small_we],  [small_ew, ww//small_ew])
    small_logical_address = join_by_factors(
            [small_eb, small_vw, small_we, small_v], [small_ew, params.j_in_l, ww//small_ew, n_vectors])
    address_in_small_vector = small_logical_address - small_offset
    address_in_large_vector = address_in_small_vector
    large_logical_address = address_in_large_vector + large_offset
    large_eb, large_vw, large_we, large_v = split_by_factors(large_logical_address, [large_ew, params.j_in_l, ww//large_ew, n_vectors])
    large_ve = join_by_factors([large_vw, large_we], [params.j_in_l, ww//large_ew])

    mapping = get_large_small_mapping(vw, ww, small_ew, large_ew,
                          large_v, large_vw, large_we, large_eb,
                          small_v, small_vw, small_we, small_eb)
    return mapping


@dataclass
class SmallParams:

    word_bytes: int = 2
    j_in_l: int = 4

    @property
    def vline_bytes(self):
        return self.j_in_l * self.word_bytes


def apply_offset(rnd, data: bytes, offset: int):
    bits = bytes_to_bits(data)
    fresh_bits = [rnd.randint(0, 1) for _ in range(abs(offset))]
    if offset > 0:
        bits = fresh_bits + bits[:-offset]
    else:
        bits = bits[-offset:] + fresh_bits
    byts = bits_to_bytes(bits)
    return byts


def test_convertion(params: LamletParams, src_ew: int, dst_ew: int, offset: int):
    rnd = Random(0)
    vlb = params.vline_bytes
    random_data = get_rand_bytes(rnd, vlb*3)
    shifted_data = apply_offset(rnd, random_data, -offset)
    src_words = encode_into_words(params, random_data, src_ew)
    expected_dst_words = encode_into_words(params, shifted_data[vlb: 2*vlb], dst_ew)
    print(f'src_words = {[[int(x) for x in word] for word in src_words]}')
    print(f'expected_dst_words = {[[int(x) for x in word] for word in expected_dst_words]}')
    n_elements = params.vline_bytes * 8 // dst_ew
    #messages = create_messages(params=params, src_ew=src_ew, dst_ew=dst_ew, offset=offset, start_element=0, n_elements=n_elements)
    #dst_words = extract_words(params, src_words, messages)
#def extract_words(params: LamletParams, src_words: List[bytes], src_ew: bool, dst_ew: bool, src_offset: int):
    dst_words = extract_words(params, src_words, src_ew, dst_ew, offset)
    rcvd_data = decode_from_words(params, dst_words, dst_ew)
    if offset % 8 == 0:
        expected_data = random_data[params.vline_bytes + offset//8: 2*params.vline_bytes + offset//8]
    else:
        random_bits = bytes_to_bits(random_data)
        expected_bits = random_bits[params.vline_bytes * 8 + offset: params.vline_bytes * 2 * 8 + offset]
        expected_data = bits_to_bytes(expected_bits)
    assert expected_data == rcvd_data


def test_mappings(params: LamletParams, small_ew: int, large_ew: int, small_offset: int, large_offset: int):
    assert small_ew <= large_ew
    ratio = large_ew//small_ew
    n_tags = (params.word_bytes * 8)//small_ew * 2

    from_large = []#set()
    from_small = []#set()
    for vw_index in range(params.j_in_l):
        for tag in range(n_tags):
            large_mapping = get_mapping_from_large_tag(
                params=params, small_ew=small_ew, large_ew=large_ew, small_offset=small_offset,
                large_offset=large_offset, large_v=1, large_vw=vw_index, large_tag=tag)
            #if large_mapping is not None:
            from_large.append(large_mapping)
            small_mapping = get_mapping_from_small_tag(
                params=params, small_ew=small_ew, large_ew=large_ew, small_offset=small_offset,
                large_offset=large_offset, small_v=1, small_vw=vw_index, small_tag=tag)
            #if small_mapping is not None:
            from_small.append(small_mapping)
    # Normalize to small_v = 0
    normalized_small = [None if m is None else m.normalize() for m in from_small]
    normalized_large = [None if m is None else m.normalize() for m in from_large]
    assert set(normalized_small) == set(normalized_large)



def main():
    params = SmallParams(word_bytes=8)
    for src_ew in (1, 2, 4, 8, 16, 32, 64):
        for dst_ew in (1, 2, 4, 8, 16, 32, 64):
            for src_offset in range(params.vline_bytes*8):
    #for src_ew in (32,):
    #    for dst_ew in (64,):
    #        for src_offset in (16,):
                small_offset = 0
                #print(src_ew, dst_ew, large_offset, small_offset)
                #if src_ew > dst_ew:
                #    continue
                #small_offset, large_offset = large_offset, small_offset
                test_convertion(params, src_ew, dst_ew, src_offset)
                #test_mappings(params, src_ew, dst_ew, small_offset, large_offset)


if __name__ == '__main__':
    main()
